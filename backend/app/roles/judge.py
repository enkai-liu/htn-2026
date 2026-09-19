"""Judge: a jury of different model families. Their DISAGREEMENT is a signal: it lowers confidence and triggers
a targeted re-query. Also runs the LLM-predictability probe: do models, given only the problem, propose this idea?
"""
from __future__ import annotations

import asyncio
import statistics

from pydantic import BaseModel, Field

from app.llm.models import JURY_MODELS, PRIOR_MODELS
from app.llm.router import LLMUnavailable
from app.orchestration.host import Ctx, result
from app.orchestration.registry import register
from app.roles.base import HOUSE_RULES, BaseRole
from app.schemas import GraphLink, GraphNode, GraphPatch
from app.scoring.similarity import cosine, embed, lexical_cosine

FACETS = ("purpose", "mechanism")
SPLIT = 0.25


class Overlap(BaseModel):
    entity: int
    purpose: float = Field(ge=0, le=1)
    mechanism: float = Field(ge=0, le=1)
    why: str = Field(max_length=200)


class Ballot(BaseModel):
    overlaps: list[Overlap]


class Proposals(BaseModel):
    ideas: list[str] = Field(description="three distinct one-sentence project ideas")


class Judge(BaseRole):
    id = "judge"
    purpose = "Count the votes, measure the split."
    phase = "debate"

    async def handle(self, msg: dict, ctx: Ctx) -> dict:
        p = msg["payload"]
        if p.get("kind") == "priors":
            return await self._priors(ctx)
        return await self._vote(ctx, only_eid=p.get("revote_eid"))

    # -- jury --------------------------------------------------------------------------------------------
    async def _vote(self, ctx: Ctx, only_eid: str | None) -> dict:
        board = ctx.board
        contested = {board.evidence[c.evidence[0]].eid for c in board.claims.values() if c.kind == "exists" and c.evidence}
        ents = [e for e in board.top_entities(12) if e.eid in contested and (only_eid is None or e.eid == only_eid)][:4]
        if not ents:
            return result(max_disagreement=0.0, summary="nothing contested")
        f = board.facets
        listing = "\n".join(f"ENTITY {i}: {e.canonical_name} :: {e.summary[:400]}" for i, e in enumerate(ents))
        system = (HOUSE_RULES + "Role: juror. For each entity rate from 0 to 1 how much it overlaps the idea on PURPOSE (same goal for "
                  "the same kind of user) and on MECHANISM (same way of achieving it). 1 = identical, 0 = unrelated. One short reason each.")
        user = f"IDEA: {board.idea_text}\nPURPOSE: {f.purpose}\nMECHANISM: {f.mechanism}\n\n{listing}"

        async def juror(model: str) -> tuple[str, Ballot | None]:
            try:
                ballot, _ = await self.llm.structured(role=self.id, system=system, user=user, schema=Ballot, model=model,
                                                      temperature=0.0, max_tokens=900, session=f"{ctx.run_id}:juror:{model}", budget=ctx.budget)
                return model, ballot
            except LLMUnavailable:
                return model, None  # a juror that cannot answer is dropped, visibly

        ballots = await asyncio.gather(*(juror(m) for m in JURY_MODELS))
        dropped = [m for m, b in ballots if b is None]
        if dropped:
            await ctx.emit("error", {"message": f"jurors dropped: {dropped}", "recoverable": True})
        worst = (0.0, None, None)
        for i, ent in enumerate(ents):
            for facet in FACETS:
                votes = [{"model": m, "score": getattr(o, facet), "why": o.why}
                         for m, b in ballots if b for o in b.overlaps if o.entity == i]
                if not votes:
                    continue
                scores = [v["score"] for v in votes]
                mean, std = statistics.fmean(scores), (statistics.pstdev(scores) if len(scores) > 1 else 0.0)
                vote = {"subject": f"{ent.canonical_name}: {facet}" + (" (re-vote)" if only_eid else ""), "eid": ent.eid, "facet": facet,
                        "votes": votes, "mean": round(mean, 3), "std": round(std, 3)}
                board.append("jury", self.id, vote)
                await ctx.emit("jury.vote", vote)
                if std > worst[0]:
                    worst = (std, ent, facet)
        std, ent, facet = worst
        payload = {"max_disagreement": round(std, 3), "n_jurors": len(ballots) - len(dropped)}
        if ent is not None and std >= SPLIT:
            payload |= {"disputed_eid": ent.eid, "disputed_facet": facet,
                        "tiebreak_query": f"{getattr(board.facets, facet)} {ent.canonical_name}"[:120]}
        return result(**payload, summary=f"max juror disagreement {std:.2f}")

    # -- LLM-predictability ------------------------------------------------------------------------------
    async def _priors(self, ctx: Ctx) -> dict:
        """Give models ONLY the problem and audience. If they independently propose the idea, it is predictable."""
        board, f = ctx.board, ctx.board.facets
        system = ("You are brainstorming hackathon projects. Propose exactly three DISTINCT project ideas, one sentence each, "
                  "for the problem and audience given. Reply as JSON: {\"ideas\": [..3 strings..]}.")
        user = f"PROBLEM: {f.purpose}\nAUDIENCE: {f.audience or 'general'}"

        async def sample(model: str) -> list[tuple[str, str]]:
            try:
                props, _ = await self.llm.structured(role=self.id, system=system, user=user, schema=Proposals, model=model,
                                                     temperature=1.0, max_tokens=500, session=f"{ctx.run_id}:prior:{model}", budget=ctx.budget)
                return [(model, t.strip()) for t in props.ideas[:3] if t.strip()]
            except LLMUnavailable:
                return []

        samples = [s for batch in await asyncio.gather(*(sample(m) for m in PRIOR_MODELS)) for s in batch]
        if not samples:
            return result(n=0, summary="no model could be sampled")
        target = f"{f.mechanism}. {f.twist}. {board.idea_text}"[:1500]
        vecs = await embed([target] + [t for _, t in samples])
        calibrated = vecs is not None
        sims = [cosine(vecs[0], v) for v in vecs[1:]] if calibrated else [lexical_cosine(target, t) for _, t in samples]
        nodes, links = [], []
        for i, ((model, text), sim) in enumerate(zip(samples, sims), 1):
            row = {"model": model, "text": text, "similarity": round(float(sim), 3)} | ({} if calibrated else {"uncalibrated": True})
            board.append("priors", self.id, row)
            await ctx.emit("prior.sample", row, phase="score", model=model)
            nodes.append(GraphNode(id=f"prior:{i}", kind="prior", label=text[:60], similarity=float(sim), val=1.2))
            links.append(GraphLink(source="idea", target=f"prior:{i}", kind="similar", weight=float(sim)))
        await ctx.emit("graph.patch", GraphPatch(add_nodes=nodes, add_links=links), phase="score")
        return result(n=len(samples), calibrated=calibrated, summary=f"{len(samples)} samples from {len(PRIOR_MODELS)} model families")


register("judge")(Judge)
