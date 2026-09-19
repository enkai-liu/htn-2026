"""Mutator: coaching. Proposes facet swaps grounded in corpus whitespace, then RE-SCORES each one against evidence,
so the user sees the neighbourhood thin out instead of taking the suggestion on faith (SciMON-style loop).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import get_settings
from app.orchestration.host import Ctx, error, result
from app.orchestration.registry import register
from app.roles.base import HOUSE_RULES, BaseRole, clipped
from app.schemas import GraphLink, GraphNode, GraphPatch, Mutation
from app.scoring import axes
from app.scoring.similarity import rerank


class Swap(BaseModel):
    facet: str = Field(description="purpose | mechanism | audience | data | twist")
    frm: clipped(120)
    to: clipped(160)
    rationale: clipped(260)
    pitch: clipped(500) = Field(description="the rewritten idea in 1-2 sentences")
    grounded_in: list[str] = Field(default_factory=list, description="whitespace terms or evidence this swap is based on")


class Swaps(BaseModel):
    mutations: list[Swap]


class Mutator(BaseRole):
    id = "mutator"
    purpose = "Move one facet into the whitespace."
    phase = "mutate"

    async def handle(self, msg: dict, ctx: Ctx) -> dict:
        p = msg["payload"]
        if p.get("rescore"):
            mu = ctx.board.mutations.get(p["rescore"])
            if mu is None:
                return error(f"unknown mutation {p['rescore']!r}")
            await self._score(ctx, mu)
            return result(mid=mu.mid, delta=mu.delta, axes=mu.axes)
        return await self._propose(ctx, n=2 if ctx.budget.low() else 3)

    async def _propose(self, ctx: Ctx, n: int) -> dict:
        board, f = ctx.board, ctx.board.facets
        stats = board.stats.get("corpus") or {}
        whitespace = await self._whitespace(ctx)
        cliches = [c.term for c in (stats.get("cliches") or [])][:10]
        neighbours = "\n".join(f"- {e.canonical_name}: {e.summary[:160]}" for e in board.top_entities(6))
        differs = [c.text for c in board.claims.values() if c.kind == "differs"]
        system = (HOUSE_RULES + f"Role: originality coach. Propose exactly {n} mutations. Each changes ONE facet of the idea so it moves away "
                  "from the crowded neighbours while keeping what is already distinctive. Ground each swap in the WHITESPACE terms (common "
                  "in the corpus overall, absent near this idea) or in a stated difference. Avoid the CLICHE terms. Be concrete and buildable "
                  "in a weekend; no buzzwords.")
        user = (f"IDEA: {board.idea_text}\nFACETS: purpose={f.purpose} | mechanism={f.mechanism} | audience={f.audience} | data={f.data} | twist={f.twist}\n"
                f"CROWDED NEIGHBOURS:\n{neighbours}\nCLICHE TERMS: {cliches}\nWHITESPACE TERMS: {[w.term for w in whitespace][:12]}\nALREADY DISTINCTIVE: {differs}")
        swaps, res = await self.llm.structured(role=self.id, system=system, user=user, schema=Swaps, temperature=1.0,
                                               session=self.session(ctx), budget=ctx.budget)
        muts = []
        for i, s in enumerate(swaps.mutations[:n], 1):
            mu = Mutation(mid=f"mu{len(board.mutations) + 1}", **s.model_dump())
            board.put("mutations", self.id, mu.mid, mu)
            muts.append(mu)
            await ctx.emit("mutation.proposed", {"mutation": mu.model_dump(mode="json")}, **res.meta())
            await ctx.emit("graph.patch", GraphPatch(
                add_nodes=[GraphNode(id=f"mut:{mu.mid}", kind="mutation", label=mu.to[:60], similarity=board.scores.crowding.detail.get("crowding_lite") if board.scores else None, val=3)],
                add_links=[GraphLink(source="idea", target=f"mut:{mu.mid}", kind="mutation_of", weight=0.8)]))
        for mu in muts:
            await self._score(ctx, mu)
        if whitespace:
            stats["whitespace"] = whitespace
        return result(mids=[m.mid for m in muts], summary=f"{len(muts)} mutations, each re-scored against the evidence")

    async def _score(self, ctx: Ctx, mu: Mutation) -> None:
        """Re-run retrieval for the mutated pitch and recompute crowding. Falls back to reranking known neighbours."""
        board = ctx.board
        sims: list[float] = []
        calibrated = True
        if get_settings().has_elastic:
            try:
                from app.search.hybrid import search as hybrid_search

                hits = await hybrid_search(mu.pitch, mu.pitch, size=10)
                sims = [float(h.retrieval.get("rerank_score") or 0) for h in hits]
            except Exception as exc:
                await ctx.emit("error", {"message": f"mutation re-search degraded: {type(exc).__name__}: {exc}"[:200], "recoverable": True})
        if not sims:
            ents = board.top_entities(10)
            sims, calibrated = await rerank(mu.pitch, [e.summary for e in ents])
        before = board.scores.crowding.score if (board.scores and board.scores.crowding.score is not None) else None
        after = axes.crowding(sims, axes.corpus_percentile(), calibrated=calibrated).score
        mu.axes = {"crowding": after} if after is not None else None
        mu.delta = round(after - before, 1) if (after is not None and before is not None) else None
        board.put("mutations", self.id, mu.mid, mu)
        await ctx.emit("mutation.scored", {"mid": mu.mid, "delta": mu.delta, "axes": mu.axes})
        await ctx.emit("graph.patch", GraphPatch(update_nodes=[{"id": f"mut:{mu.mid}", "similarity": round(axes.crowding_lite(sims), 3)}]))

    async def _whitespace(self, ctx: Ctx) -> list:
        if not get_settings().has_elastic:
            return []
        try:
            from app.schemas import TermStat
            from app.search.whitespace import find_whitespace

            found = await find_whitespace(ctx.board.facets.purpose)
            rows = sorted(found.get("tech", []) + found.get("tags", []), key=lambda c: -c["global_count"])
            return [TermStat(term=c["term"], global_count=c["global_count"], neighbourhood_count=c["neighbourhood_count"]) for c in rows[:20]]
        except Exception as exc:
            await ctx.emit("error", {"message": f"whitespace finder unavailable: {type(exc).__name__}: {exc}"[:200], "recoverable": True})
            return []


register("mutator")(Mutator)
