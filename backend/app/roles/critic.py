"""Critic: argues the idea has been done, with quotes. It can send scouts back out when it sees a gap."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from app.orchestration.host import Ctx, envelope, result
from app.orchestration.registry import register
from app.roles.base import HOUSE_RULES, BaseRole, clipped
from app.schemas import Claim, Entity, Evidence

MAX_FOLLOWUPS = 2
COVERS = {"scout.devpost": "past hackathon projects", "scout.yc": "YC companies", "scout.github": "open-source repositories",
          "scout.hn": "Hacker News launches and discussion", "scout.web": "the open web: shipped products, startups, app stores"}
SITE = {"devpost": "Devpost", "yc": "Y Combinator", "github": "GitHub", "hn": "Hacker News", "arxiv": "arXiv", "web": "Web"}


class ExistsClaim(BaseModel):
    entity: int = Field(description="index of the entity in the list you were given")
    text: clipped(260) = Field(description="one-sentence claim that this prior work already does (part of) the idea")
    quote: clipped(300) = Field(description="verbatim excerpt from that entity's text supporting the claim")
    facets: list[str] = Field(default_factory=list, description="which facets overlap: purpose, mechanism, audience, data, twist")


class FollowUp(BaseModel):
    facet: str
    query: clipped(120)
    scout: str = Field(description="one of the scouts on the team, e.g. scout.devpost")
    reason: clipped(200)


class Critique(BaseModel):
    claims: list[ExistsClaim]
    followups: list[FollowUp] = Field(default_factory=list, description="at most 2 searches that could change your verdict")


def citation(n: int, ent: Entity, url: str, source: str, year: int | None) -> str:
    return f'[{n}] {ent.canonical_name} team. "{ent.canonical_name}." {SITE.get(source, source)}. {year or "n.d."}. {url}'


class Critic(BaseRole):
    id = "critic"
    purpose = "This has been done. Prove me wrong."
    phase = "debate"

    async def handle(self, msg: dict, ctx: Ctx) -> dict:
        board = ctx.board
        claims = await self._critique(ctx, self._bench(board), allow_followups=True)
        return result(cids=[c.cid for c in claims], summary=f"{len(claims)} 'already exists' claims")

    async def _critique(self, ctx: Ctx, entities: list[Entity], *, allow_followups: bool) -> list[Claim]:
        board = ctx.board
        if not entities:
            return []
        f = board.facets
        listing = "\n".join(
            f"ENTITY {i} [{'+'.join(e.sources)}] {e.canonical_name} (similarity {e.similarity:.2f})\n  TEXT: {self._text(ctx, e)[:700]}"
            for i, e in enumerate(entities))
        scouts = [m for m in ctx.members() if m.startswith("scout.")]
        system = (HOUSE_RULES + "Role: hostile prior-art critic. Make the strongest honest case that the idea is NOT original. "
                  "One claim per entity that genuinely overlaps; skip entities that do not. Each quote must be copied verbatim from that "
                  f"entity's TEXT. Then list up to {MAX_FOLLOWUPS} follow-up searches (only if they could change the verdict), each sent "
                  "to the scout whose ground it is: " + "; ".join(f"{s} ({COVERS.get(s, 'search')})" for s in scouts) + ".")
        user = (f"IDEA: {board.idea_text}\nFACETS: purpose={f.purpose} | mechanism={f.mechanism} | audience={f.audience} | twist={f.twist}\n\n{listing}")
        crit, res = await self.llm.structured(role=self.id, system=system, user=user, schema=Critique, session=self.session(ctx), budget=ctx.budget)

        out: list[Claim] = []
        for c in crit.claims:
            if not 0 <= c.entity < len(entities):
                continue
            ent = entities[c.entity]
            rec = board.records[ent.records[0]]
            n = len(board.evidence) + 1
            ev = Evidence(evid=f"ev{n}", eid=ent.eid, rid=rec.rid, quote=c.quote.strip(), url=rec.url,
                          citation=citation(n, ent, rec.url, rec.source, rec.year))
            board.put("evidence", self.id, ev.evid, ev)
            claim = Claim(cid=f"c{len(board.claims) + 1}", kind="exists", text=c.text.strip(), by=self.id, evidence=[ev.evid])
            board.put("claims", self.id, claim.cid, claim)
            out.append(claim)
            await ctx.emit("claim.proposed", {"claim": claim.model_dump(mode="json"), "evidence": [ev.model_dump(mode="json")],
                                              "facets": c.facets}, **res.meta())

        # a model that fills `query` with the scout's name sent GitHub searching for "scout.github": not a search
        followups = [fu for fu in crit.followups if fu.scout in scouts and fu.query.strip() and not fu.query.strip().startswith("scout.")
                     ][:MAX_FOLLOWUPS] if allow_followups else []
        if followups and not ctx.budget.low():
            async def ask(fu: FollowUp) -> list[str]:
                await ctx.emit("requery.issued", {"reason": fu.reason, "facet": fu.facet, "query": fu.query, "to": fu.scout}, to=fu.scout)
                reply = await ctx.send(fu.scout, envelope("REQUEST_EVIDENCE", {"query": fu.query, "facet": fu.facet, "reason": fu.reason}), timeout=40)
                return (reply.get("payload") or {}).get("rids") or []

            new_rids = [rid for rids in await asyncio.gather(*(ask(fu) for fu in followups)) for rid in rids]
            if new_rids:  # new evidence arrived: have it resolved, then look once more at what is new
                await ctx.send("resolver", envelope("TASK", {"reason": "critic follow-up evidence"}), timeout=60)
                fresh = [e for e in board.top_entities(12) if set(e.records) & set(new_rids)]
                out += await self._critique(ctx, fresh[:4], allow_followups=False)
        return out

    @staticmethod
    def _bench(board) -> list[Entity]:
        """The eight nearest entities, plus up to three players the web scout looked up by name. The reranker is
        literal -- it put Nvidia at 0.02 for "chipmaker for ai" because its page says GPU, not chip -- so the
        incumbents a reader expects to see argued would otherwise never reach a model that knows better."""
        top = board.top_entities(8)
        named = [e for e in board.top_entities(len(board.entities)) if e not in top and any(
            str(board.records[r].retrieval.get("query", "")).startswith("lookup:") for r in e.records if r in board.records)]
        return top + named[:3]

    @staticmethod
    def _text(ctx: Ctx, ent: Entity) -> str:
        return " ".join((ctx.board.records[r].pitch or ctx.board.records[r].title) for r in ent.records if r in ctx.board.records)


register("critic")(Critic)
