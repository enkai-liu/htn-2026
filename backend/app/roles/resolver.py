"""Resolver: schema-matched records -> canonical entities. The only role allowed to write entities.

Pipeline: blocking (URL cross-references, name trigrams) -> decision (rule for URL xref, LLM adjudication for the
rest with an explicit `insufficient_evidence` outcome) -> union-find merge -> field fusion with reliability priors
-> visible conflicts and imputed fields.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.llm.router import LLMUnavailable
from app.orchestration.host import Ctx, result
from app.orchestration.registry import register
from app.roles.base import HOUSE_RULES, BaseRole, clipped, eid_for
from app.schemas import Entity, GraphLink, GraphPatch, MergeDecision, SourceRecord
from app.wrangle.blocking import candidate_pairs
from app.wrangle.fuse import fuse

MAX_LLM_PAIRS = 8


class PairVerdict(BaseModel):
    pair: int
    verdict: Literal["same", "different", "insufficient_evidence"]
    rationale: clipped(240)


class Adjudication(BaseModel):
    verdicts: list[PairVerdict]


class Resolver(BaseRole):
    id = "resolver"
    purpose = "Four listings, one project."
    phase = "resolve"

    async def handle(self, msg: dict, ctx: Ctx) -> dict:
        records = list(ctx.board.records.values())
        by_rid = {r.rid: r for r in records}
        decisions: list[MergeDecision] = []
        undecided: list[tuple[str, str, dict]] = []
        for a, b, sig in candidate_pairs(records):
            if sig["url_xref"]:
                decisions.append(MergeDecision(a=a, b=b, verdict="same", signals=sig,
                                               rationale=f"Both records link to {sig['shared_urls'][0]}."))
            else:
                undecided.append((a, b, sig))
        llm_meta: dict = {}
        if undecided:
            llm_decisions, llm_meta = await self._adjudicate(undecided[:MAX_LLM_PAIRS], by_rid, ctx)
            decisions += llm_decisions

        parent = {r.rid: r.rid for r in records}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for d in decisions:
            if d.verdict == "same":
                parent[find(d.a)] = find(d.b)
        groups: dict[str, list[SourceRecord]] = {}
        for r in records:
            groups.setdefault(find(r.rid), []).append(r)

        entities: dict[str, Entity] = {}
        rid_to_eid: dict[str, str] = {}
        for members in groups.values():
            best = max(members, key=lambda r: float(r.retrieval.get("rerank_score") or 0))
            eid = eid_for(best.rid)
            rids = {m.rid for m in members}
            ent = fuse(eid, members, [d for d in decisions if d.verdict == "same" and d.a in rids and d.b in rids])
            entities[eid] = ent
            rid_to_eid |= {m.rid: eid for m in members}
        for d in decisions:  # unresolved pairs stay separate but visibly linked
            if d.verdict == "insufficient_evidence" and rid_to_eid[d.a] != rid_to_eid[d.b]:
                ea, eb = entities[rid_to_eid[d.a]], entities[rid_to_eid[d.b]]
                ea.possible_same_as.append(eb.eid)
                ea.merges.append(d)

        n_merged = n_conflicts = n_imputed = 0
        for ent in entities.values():
            ctx.board.put("entities", self.id, ent.eid, ent)
            badges = []
            if len(ent.records) > 1:
                n_merged += 1
                badges.append("merged")
                absorbed = [f"ent:{eid_for(r)}" for r in ent.records if eid_for(r) != ent.eid]
                meta = llm_meta if any(m.model for m in ent.merges) else {}
                await ctx.emit("entity.merged", {"entity": ent.model_dump(mode="json"), "rids": ent.records, "verdict": "same"}, **meta)
                await ctx.emit("graph.patch", GraphPatch(remove_nodes=absorbed))
            for c in ent.conflicts:
                n_conflicts += 1
                await ctx.emit("conflict.detected", {"eid": ent.eid, "conflict": c.model_dump(mode="json")})
            if ent.conflicts:
                badges.append("conflict")
            if any(f.imputed for f in ent.fields.values()):
                n_imputed += 1
                badges.append("imputed")
            if badges:
                node = {"id": f"ent:{ent.eid}", "label": ent.canonical_name[:60], "val": 1 + 4 * min(max(ent.similarity, 0), 1) + 0.5 * len(ent.records)}
                existing = _existing_badges(ctx, ent)
                await ctx.emit("graph.patch", GraphPatch(update_nodes=[node | {"badges": sorted(set(existing + badges))}]))
            for other in ent.possible_same_as:
                d = next(m for m in ent.merges if m.verdict == "insufficient_evidence")
                await ctx.emit("entity.merged", {"entity": ent.model_dump(mode="json"), "rids": ent.records, "verdict": "insufficient_evidence"}, **llm_meta)
                await ctx.emit("graph.patch", GraphPatch(add_links=[GraphLink(source=f"ent:{ent.eid}", target=f"ent:{other}", kind="possible_same_as",
                                                                              weight=float(d.signals.get("name_sim") or 0.5))]))
        summary = (f"{len(records)} records -> {len(entities)} entities; {n_merged} merged, "
                   f"{sum(len(e.possible_same_as) for e in entities.values())} left open, {n_conflicts} conflicts, {n_imputed} with imputed fields")
        return result(eids=list(entities), summary=summary)

    async def _adjudicate(self, pairs: list[tuple[str, str, dict]], by_rid: dict[str, SourceRecord], ctx: Ctx) -> tuple[list[MergeDecision], dict]:
        """Batched entity matching. Falls back to 'insufficient_evidence' for every pair if the LLM is unavailable."""
        lines = []
        for i, (a, b, sig) in enumerate(pairs):
            ra, rb = by_rid[a], by_rid[b]
            lines.append(f"PAIR {i} (name similarity {sig['name_sim']}):\n"
                         f"  A [{ra.source}, {ra.year}] {ra.title} :: {(ra.pitch or '')[:300]}\n"
                         f"  B [{rb.source}, {rb.year}] {rb.title} :: {(rb.pitch or '')[:300]}")
        system = (HOUSE_RULES + "Task: entity matching. For each pair decide whether A and B are listings of the SAME project/product "
                  "(e.g. a Devpost page and its GitHub repo), DIFFERENT projects, or INSUFFICIENT_EVIDENCE. Similar purpose alone is not "
                  "'same'. Prefer insufficient_evidence over guessing.")
        try:
            adj, res = await self.llm.structured(role=self.id, system=system, user="\n".join(lines), schema=Adjudication,
                                                 session=self.session(ctx), budget=ctx.budget)
            verdicts = {v.pair: v for v in adj.verdicts}
            meta = res.meta()
        except LLMUnavailable as exc:
            verdicts, meta = {}, {}
            await ctx.emit("error", {"message": f"entity adjudication degraded to rules only: {exc}", "recoverable": True})
        out = []
        for i, (a, b, sig) in enumerate(pairs):
            v = verdicts.get(i)
            out.append(MergeDecision(a=a, b=b, signals=sig, model=meta.get("model"),
                                     verdict=v.verdict if v else "insufficient_evidence",
                                     rationale=v.rationale if v else "No adjudication available; left unmerged."))
        return out, meta


def _existing_badges(ctx: Ctx, ent: Entity) -> list[str]:
    out: list[str] = []
    for rid in ent.records:
        r = ctx.board.records.get(rid)
        if r is None:
            continue
        if r.traction.get("is_winner"):
            out.append("winner")
        if r.gptzero and r.gptzero.predicted_class != "human" and r.gptzero.confidence_category == "high":
            out.append("ai_written")
    return out


register("resolver")(Resolver)
