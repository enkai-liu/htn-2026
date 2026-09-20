"""Conductor: decomposes the idea, staffs a team for it, and replans when agents fail or disagree."""
from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel, Field

from app.config import get_settings
from app.llm.router import LLMUnavailable
from app.orchestration import registry
from app.orchestration.host import Ctx, envelope, error, result, task
from app.orchestration.registry import register
from app.roles.base import HOUSE_RULES, BaseRole, clipped
from app.schemas import FACET_KEYS, Facets, GraphLink, GraphNode, GraphPatch, SourceStatus
from app.scoring.similarity import tokens
from app.sources import idea_url
from app.sources.http import SourceError

SCOUT_PURPOSE = {
    "scout.devpost": "260k hackathon projects (Elasticsearch: BM25 + Jina vectors, RRF, Jina rerank)",
    "scout.yc": "YC companies (Elasticsearch hybrid search)",
    "scout.github": "live GitHub repository search",
    "scout.hn": "live Hacker News search",
    "scout.web": "the open web: companies, shipped products and launch posts of any kind, hardware and services included (Exa neural search, page text attached)",
}
SEMANTIC_SCOUTS = ("scout.devpost", "scout.yc", "scout.web")  # these take natural-language queries; the rest want keywords
SHORT_PITCH = 8  # content words: below this a pitch is a topic, not a description
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_ABOUT_THE_PITCH = re.compile(r"\b(the|this|your) (idea|pitch|author|concept|description)\b|\bas (stated|written|pitched)\b"
                              r"|\b(not|n't) (specif|stat|say|mention)|\bunclear\b", re.IGNORECASE)
_A_THING = re.compile(r"(an?|the) \w", re.IGNORECASE)  # "A company that ...", "An app for ...": how a project page opens
DEBATE_TEAM = ["resolver", "critic", "advocate", "judge", "verifier", "synthesizer", "mutator", "actuator"]


class Plan(BaseModel):
    facets: Facets
    semantic_queries: list[str] = Field(description="3 natural-language queries: the full idea; purpose + mechanism; the twist alone")
    keyword_queries: list[str] = Field(description="2-3 short keyword queries (max 5 words each) for lexical search engines")
    problem_query: clipped(300) = Field(default="", description="the problem alone, in one sentence, with NO mention of how this idea "
                                        "solves it: it finds work that attacked the same problem a different way")
    writeup: clipped(600) = Field(default="", description="2-3 plain sentences describing a project that ALREADY built this idea, as its own "
                                  "project page would. Begin 'A company that', 'A tool that', 'A device that' or the like, and say what "
                                  "it makes or does and for whom. Never mention 'the idea', the pitch or its author, and never remark on "
                                  "what is missing. No invented names, numbers or awards")
    known_players: list[str] = Field(default_factory=list, description="up to 8 real companies, products or projects that already do this "
                                     "or something close: the names a domain expert would say at once, the large incumbents and the "
                                     "specialist startups alike. Bare names only, no asides. Each is looked up on the web and dropped if no page is found, so leave out "
                                     "anything you are not sure exists")
    is_research: bool = Field(default=False, description="true only if the idea is a research contribution rather than a product")


def semantic_queries(plan: Plan) -> list[str]:
    """The natural-language queries, one per way prior art can hide: the idea as pitched, its halves, the problem
    without the solution (same need, different approach) and a hypothetical write-up (the corpus is written in the
    register of project pages, not pitches). The two newer shapes are optional in the schema -- some models skip
    optional fields -- so the problem falls back to the facets and a missing write-up is simply not searched."""
    f = plan.facets
    problem = plan.problem_query.strip() or " for ".join(x for x in (f.purpose, f.audience) if x)
    out: list[str] = []
    for q in (*plan.semantic_queries[:3], problem, plan.writeup.strip()):
        if q and q.lower() not in {o.lower() for o in out}:
            out.append(q)
    return out


def web_queries(plan: Plan, idea: str) -> list[str]:
    """The open web is searched in the author's own words first, when they are short enough to be a search. The
    planner's rewrites are longer and more particular than what was typed: Exa answered a judge's four words,
    "chipmaker for ai", with Cerebras at the top, and the rewrites with nothing anyone had heard of."""
    own = " ".join(dict.fromkeys(line.strip() for line in idea.splitlines() if line.strip()))
    out = [own] if 0 < len(own) <= 200 else []
    return out + [q for q in semantic_queries(plan) if q.lower() != own.lower()]


def scored_as(plan: Plan, idea: str) -> str | None:
    """The text a few-word pitch is scored as: the planner's write-up of it, or None to score the pitch itself.

    The reranker answers "does this text answer the query", and the crowding percentile was calibrated on project
    write-ups. Given the three words "chipmaking for AI" it put an explainer called "How AI Chips are Made" at 0.34,
    Etched at 0.02 and Cerebras at 0.00: the explainer repeats the words, and a chip company's own description says
    "wafer-scale processors for inference". Against the write-up -- the same idea, as a sentence about what is made
    and for whom -- the same records rank Nvidia, Graphcore, Etched and Cerebras first. A pitch that already is a
    description is left alone: the author's words outrank a paraphrase of them."""
    if len(tokens(idea)) >= SHORT_PITCH:
        return None
    # A planner handed three words has been seen to fill the write-up with remarks on them ("The idea as stated is
    # extremely thin..."). Those sentences describe the pitch, not a project: they are not scored against. And what is left has to open
    # the way it was asked to, as a thing ("A company that ..."): a write-up that does not is remarks all the way
    # through ("Very short, and does not say what subject..."), and the pitch is better scored as typed.
    kept = [s for s in _SENTENCE.split(plan.writeup.strip()) if s and not _ABOUT_THE_PITCH.search(s)]
    return " ".join(kept) if kept and _A_THING.match(kept[0]) else None


class Conductor(BaseRole):
    id = "conductor"
    purpose = "Decompose, staff, replan."
    phase = "plan"

    async def handle(self, msg: dict, ctx: Ctx) -> dict:
        board = ctx.board
        if not self.llm.available:
            return error("No LLM provider is configured. Set BASETEN_API_KEY (or OPENROUTER_API_KEY) in .env.")
        await self._read_link(ctx)
        try:
            plan = await self._plan(ctx)
        except LLMUnavailable as exc:
            return error(f"planning failed: {exc}")
        scouts = await self._form_team(ctx, plan)

        # Voice is independent of the search, so it runs alongside the scouts (and finishes before the verifier is needed again).
        await asyncio.gather(ctx.send("verifier", task(kind="voice"), timeout=45), self._scout(ctx, plan, scouts))
        await ctx.emit("budget.updated", ctx.budget.snapshot(), phase="scout")

        if board.records:
            await ctx.send("resolver", task(reason="initial resolution"), timeout=90)
            await self._debate(ctx, scouts)
            # Three independent checks on what the debate produced: the quotes, the LLM priors, and the products' live sites.
            await asyncio.gather(ctx.send("verifier", task(kind="claims"), timeout=90),
                                 ctx.send("judge", task(kind="priors"), timeout=60),
                                 *([ctx.send("inspector", task(), timeout=80)] if "inspector" in ctx.members() else []))
        await ctx.send("synthesizer", task(kind="score"), timeout=90)
        if board.records and not ctx.budget.exhausted():
            await ctx.send("mutator", task(), timeout=120)
        else:
            ctx.budget.degraded = True
        await ctx.send("actuator", task(), timeout=30)
        await ctx.emit("budget.updated", ctx.budget.snapshot(), phase="act")
        final = await ctx.send("synthesizer", task(kind="report"), timeout=90)
        if final.get("type") != "RESULT":
            return error((final.get("payload") or {}).get("message", "report failed"))
        return result(report=final["payload"]["report"], summary="run complete")

    # -- the author's own link ---------------------------------------------------------------------------
    async def _read_link(self, ctx: Ctx) -> None:
        """Read the optional Devpost/GitHub link before planning: it describes the idea better than the pitch box,
        and its URL keys are what stop the scouts handing the author their own project back as prior art.

        A link that will not load degrades the run (one visible event) instead of ending it: the pitch is still
        an idea worth investigating.
        """
        raw = ctx.board.url
        if not raw:
            return
        await ctx.emit("tool.call", {"tool": "fetch.idea_link", "args_summary": raw[:120]})
        try:
            page = await idea_url.read(raw)
        except SourceError as exc:
            await ctx.emit("error", {"message": f"could not read {raw[:80]}: {exc}", "recoverable": True})
            return
        except Exception as exc:  # a malformed page is the page's problem, not the run's
            await ctx.emit("error", {"message": f"could not read {raw[:80]}: {type(exc).__name__}", "recoverable": True})
            return
        ctx.board.set("self_page", self.id, page)
        await ctx.emit("tool.result", {"tool": "fetch.idea_link", "summary": page.summary(), "n_hits": 1})

    # -- plan --------------------------------------------------------------------------------------------
    async def _plan(self, ctx: Ctx) -> Plan:
        system = (HOUSE_RULES + "Role: planner. Decompose the idea into facets: purpose (the goal, for whom), mechanism (how it works), "
                  "audience, data (what it consumes), twist (what the author thinks is new), domain (2-3 words), keywords. "
                  "Facet values are short noun phrases in plain words. Then write the search queries, the problem_query and the writeup, "
                  "and name the known_players. The idea can be anything -- software, hardware, a physical product, a service, a "
                  "business, research: describe it as what it is and never assume it is an app. However thin the idea is, do not "
                  "comment on it: the writeup describes a project, it is not feedback to the author.")
        page = ctx.board.self_page
        user = f"IDEA: {ctx.board.idea_text}" + (f"\n\n{page.context()}" if page else "")
        plan, res = await self.llm.structured(role=self.id, system=system, user=user, schema=Plan,
                                              session=self.session(ctx), budget=ctx.budget)
        ctx.board.set("facets", self.id, plan.facets)
        await ctx.emit("facets.extracted", {"facets": plan.facets.model_dump()}, **res.meta())
        if text := scored_as(plan, ctx.board.idea_text):
            ctx.board.set("scored_as", self.id, text)
            await ctx.emit("tool.result", {"tool": "plan.scored_as", "n_hits": 0, "summary":
                           f"a {len(ctx.board.idea_text.split())}-word pitch: similarity is measured against the planner's description of it: {text}"[:400]})
        live = [k for k in FACET_KEYS if getattr(plan.facets, k)]
        await ctx.emit("graph.patch", GraphPatch(
            add_nodes=[GraphNode(id="idea", kind="idea", label="Your idea", val=8)]
            + [GraphNode(id=f"facet:{k}", kind="facet", label=getattr(plan.facets, k)[:48], val=2.5) for k in live],
            add_links=[GraphLink(source="idea", target=f"facet:{k}", kind="has_facet") for k in live]))
        return plan

    async def _form_team(self, ctx: Ctx, plan: Plan) -> list[str]:
        """Dynamic team formation: who joins depends on the idea and on what is reachable right now."""
        settings, known = get_settings(), set(registry.known_roles())
        has_es = settings.has_elastic
        scouts, skipped = [], []
        for sid in ("scout.devpost", "scout.yc", "scout.github", "scout.hn", "scout.web"):
            if sid not in known:
                skipped.append({"agent": sid, "why": "not available in this build"})
            elif sid in ("scout.devpost", "scout.yc") and not has_es:
                skipped.append({"agent": sid, "why": "Elasticsearch is not configured"})
                ctx.board.put("sources", self.id, sid.split(".")[1], SourceStatus(source=sid.split(".")[1], status="skipped", error="Elasticsearch is not configured"))
            elif sid == "scout.web" and not settings.has_web_search:
                skipped.append({"agent": sid, "why": "EXA_API_KEY is not set"})
                ctx.board.put("sources", self.id, "web", SourceStatus(source="web", status="skipped", error="EXA_API_KEY is not set"))
            else:
                scouts.append(sid)
        skipped.append({"agent": "scout.arxiv", "why": "arXiv scout is not enabled in this build" if plan.is_research
                        else "the idea is a product, not a research contribution"})
        browser = "inspector" in known and settings.has_browser
        if not browser:
            skipped.append({"agent": "inspector", "why": "BROWSERBASE_API_KEY is not set" if "inspector" in known else "not available in this build"})
        team = scouts + [r for r in DEBATE_TEAM if r in known] + (["inspector"] if browser else [])
        ctx.form_team(team)
        await ctx.emit("team.formed", {"team": [{"agent": a, "purpose": SCOUT_PURPOSE.get(a) or registry.create(a).purpose} for a in team],
                                       "skipped": skipped})
        return scouts

    # -- scout -------------------------------------------------------------------------------------------
    async def _scout(self, ctx: Ctx, plan: Plan, scouts: list[str]) -> None:
        def brief(sid: str) -> dict:
            if sid == "scout.web":  # the only scout that can look a name up, so the planner's known players go to it
                return {"queries": web_queries(plan, ctx.board.idea_text) or [ctx.board.idea_text[:200]],
                        "lookups": [n.strip() for n in plan.known_players if n.strip()], "hint": plan.facets.domain}
            return {"queries": (semantic_queries(plan) if sid in SEMANTIC_SCOUTS else plan.keyword_queries[:3]) or [ctx.board.idea_text[:200]]}

        replies = await asyncio.gather(*(ctx.send(s, task(**brief(s)), timeout=60) for s in scouts))  # search, rerank, then a reader's grade
        for sid, reply in zip(scouts, replies):
            if reply.get("type") != "ERROR":
                continue
            # Failure handling: one broadened retry, then degrade visibly (confidence drops with source coverage).
            retry = await ctx.send(sid, envelope("REPLAN", {"queries": plan.facets.keywords[:1] or plan.keyword_queries[:1],
                                                            "summary": "one broadened retry, then degrade"}), timeout=30)
            source = sid.split(".")[1]
            if retry.get("type") != "ERROR":
                st = ctx.board.sources.get(source)
                ctx.board.put("sources", self.id, source, SourceStatus(source=source, status="degraded", n_records=st.n_records if st else 0,
                                                                       error="first attempt failed; retry succeeded"))

    # -- debate ------------------------------------------------------------------------------------------
    async def _debate(self, ctx: Ctx, scouts: list[str]) -> None:
        await ctx.send("critic", task(), timeout=150)
        if not any(c.kind == "exists" for c in ctx.board.claims.values()):
            return
        await ctx.send("advocate", task(), timeout=90)
        verdict = (await ctx.send("judge", task(), timeout=90)).get("payload") or {}
        if verdict.get("disputed_eid") and scouts:
            if ctx.budget.low():
                ctx.budget.degraded = True
                await ctx.emit("budget.updated", ctx.budget.snapshot(), phase="debate")
                return
            # The jury split: that disagreement is information. Send a scout after exactly the disputed facet, then re-vote.
            scout = "scout.devpost" if "scout.devpost" in scouts else scouts[0]
            await ctx.emit("requery.issued", {"reason": f"jury split (std {verdict['max_disagreement']:.2f}) on {verdict['disputed_facet']}",
                                              "facet": verdict["disputed_facet"], "query": verdict["tiebreak_query"], "to": scout}, phase="debate", to=scout)
            more = await ctx.send(scout, envelope("REQUEST_EVIDENCE", {"query": verdict["tiebreak_query"], "facet": verdict["disputed_facet"]}), timeout=40)
            if (more.get("payload") or {}).get("rids"):
                await ctx.send("resolver", task(reason="evidence from jury tie-break"), timeout=60)
            await ctx.send("judge", task(revote_eid=verdict["disputed_eid"]), timeout=60)


register("conductor")(Conductor)
