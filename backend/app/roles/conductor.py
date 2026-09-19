"""Conductor: decomposes the idea, staffs a team for it, and replans when agents fail or disagree."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from app.config import get_settings
from app.llm.router import LLMUnavailable
from app.orchestration import registry
from app.orchestration.host import Ctx, envelope, error, result, task
from app.orchestration.registry import register
from app.roles.base import HOUSE_RULES, BaseRole
from app.schemas import FACET_KEYS, Facets, GraphLink, GraphNode, GraphPatch, SourceStatus
from app.sources import idea_url
from app.sources.http import SourceError

SCOUT_PURPOSE = {
    "scout.devpost": "260k hackathon projects (Elasticsearch: BM25 + Jina vectors, RRF, Jina rerank)",
    "scout.yc": "YC companies (Elasticsearch hybrid search)",
    "scout.github": "live GitHub repository search",
    "scout.hn": "live Hacker News search",
}
DEBATE_TEAM = ["resolver", "critic", "advocate", "judge", "verifier", "synthesizer", "mutator", "actuator"]


class Plan(BaseModel):
    facets: Facets
    semantic_queries: list[str] = Field(description="3 natural-language queries: the full idea; purpose + mechanism; the twist alone")
    keyword_queries: list[str] = Field(description="2-3 short keyword queries (max 5 words each) for lexical search engines")
    is_research: bool = Field(default=False, description="true only if the idea is a research contribution rather than a product")


class Conductor(BaseRole):
    id = "conductor"
    purpose = "Decompose, staff, replan."
    phase = "plan"

    async def handle(self, msg: dict, ctx: Ctx) -> dict:
        board = ctx.board
        if not self.llm.available:
            return error("No LLM provider is configured. Set BASETEN_API_KEY (or OPENROUTER_API_KEY) in .env, or open /runs/mock for a recorded run.")
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
            await asyncio.gather(ctx.send("verifier", task(kind="claims"), timeout=90),
                                 ctx.send("judge", task(kind="priors"), timeout=60))
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
                  "Facet values are short noun phrases in plain words. Then write the search queries.")
        page = ctx.board.self_page
        user = f"IDEA: {ctx.board.idea_text}" + (f"\n\n{page.context()}" if page else "")
        plan, res = await self.llm.structured(role=self.id, system=system, user=user, schema=Plan,
                                              session=self.session(ctx), budget=ctx.budget)
        ctx.board.set("facets", self.id, plan.facets)
        await ctx.emit("facets.extracted", {"facets": plan.facets.model_dump()}, **res.meta())
        live = [k for k in FACET_KEYS if getattr(plan.facets, k)]
        await ctx.emit("graph.patch", GraphPatch(
            add_nodes=[GraphNode(id="idea", kind="idea", label="Your idea", val=8)]
            + [GraphNode(id=f"facet:{k}", kind="facet", label=getattr(plan.facets, k)[:48], val=2.5) for k in live],
            add_links=[GraphLink(source="idea", target=f"facet:{k}", kind="has_facet") for k in live]))
        return plan

    async def _form_team(self, ctx: Ctx, plan: Plan) -> list[str]:
        """Dynamic team formation: who joins depends on the idea and on what is reachable right now."""
        has_es, known = get_settings().has_elastic, set(registry.known_roles())
        scouts, skipped = [], []
        for sid in ("scout.devpost", "scout.yc", "scout.github", "scout.hn"):
            if sid not in known:
                skipped.append({"agent": sid, "why": "not available in this build"})
            elif sid in ("scout.devpost", "scout.yc") and not has_es:
                skipped.append({"agent": sid, "why": "Elasticsearch is not configured"})
                ctx.board.put("sources", self.id, sid.split(".")[1], SourceStatus(source=sid.split(".")[1], status="skipped", error="Elasticsearch is not configured"))
            else:
                scouts.append(sid)
        skipped.append({"agent": "scout.arxiv", "why": "arXiv scout is not enabled in this build" if plan.is_research
                        else "the idea is a product, not a research contribution"})
        team = scouts + [r for r in DEBATE_TEAM if r in known]
        ctx.form_team(team)
        await ctx.emit("team.formed", {"team": [{"agent": a, "purpose": SCOUT_PURPOSE.get(a) or registry.create(a).purpose} for a in team],
                                       "skipped": skipped})
        return scouts

    # -- scout -------------------------------------------------------------------------------------------
    async def _scout(self, ctx: Ctx, plan: Plan, scouts: list[str]) -> None:
        def queries(sid: str) -> list[str]:
            corpus = sid in ("scout.devpost", "scout.yc")
            return (plan.semantic_queries[:3] if corpus else plan.keyword_queries[:3]) or [ctx.board.idea_text[:200]]

        replies = await asyncio.gather(*(ctx.send(s, task(queries=queries(s)), timeout=45) for s in scouts))
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
