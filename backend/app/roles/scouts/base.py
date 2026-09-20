from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Literal

from pydantic import BaseModel

from app.llm.models import GLM_FLASH
from app.llm.router import LLMUnavailable
from app.orchestration.host import Ctx, error, result
from app.roles.base import HOUSE_RULES, BaseRole, eid_for
from app.schemas import GraphLink, GraphNode, GraphPatch, SourceRecord, SourceStatus
from app.scoring.similarity import clamp01, graded, rerank, tokens
from app.sources.http import SourceError
from app.sources.idea_url import is_self

GRADE_BATCH = 60  # hits read in one call, nearest first
GRADE_MODEL = GLM_FLASH  # 47 hits in 4.7 s; the scouts' DeepSeek Flash spent 17 s on the same call and returned nothing valid
GRADE_TIMEOUT_S = 25  # a grade is a second opinion: the scout does not wait long for it, and answers without it


class Grade(BaseModel):
    n: int
    match: Literal["same", "close", "adjacent", "unrelated"]


class Grades(BaseModel):
    grades: list[Grade]


class ScoutRole(BaseRole):
    """Searches one source family. Handles TASK {queries} and REQUEST_EVIDENCE {query} (critic/judge re-queries)."""

    purpose = "If it was built, I find it."
    phase = "scout"
    source = ""
    tool = ""
    per_query = 8
    already_scored = False  # True when the backend search already reranked against the idea

    async def search(self, query: str, n: int) -> list[SourceRecord]:  # pragma: no cover
        raise NotImplementedError

    def extra(self, payload: dict, ctx: Ctx, phase: str) -> list[tuple[str, Awaitable[list[SourceRecord]]]]:
        """Searches beside the queries, as (label, job): a scout whose source has more than one way in."""
        return []

    def collapse(self, new: list[SourceRecord], ctx: Ctx) -> list[SourceRecord]:
        """Scored hits, before they become evidence: a scout whose source lists one thing several times folds them here."""
        return new

    async def _one(self, q: str, ctx: Ctx, phase: str) -> list[SourceRecord]:
        await ctx.emit("tool.call", {"tool": self.tool, "args_summary": q[:120]}, phase=phase)
        hits = await self.search(q, self.per_query)
        if not hits and len(tokens(q)) > 3:  # adaptive broaden-and-retry: keep the 3 most specific terms
            broad = " ".join(sorted(set(tokens(q)), key=len, reverse=True)[:3])
            await ctx.emit("tool.call", {"tool": self.tool, "args_summary": f"broadened: {broad}"}, phase=phase)
            hits = await self.search(broad, self.per_query)
        await ctx.emit("tool.result", {"tool": self.tool, "summary": f"{len(hits)} hits", "n_hits": len(hits)}, phase=phase)
        return hits

    async def _grade(self, new: list[SourceRecord], raw: dict[str, float], ctx: Ctx, phase: str) -> None:
        """A reader's second opinion on the reranker: one call reads every new hit beside the idea and says how close
        the thing it describes is. A grade of same or close puts a floor under the hit's similarity (see `graded`);
        the reranker's own score is kept beside it. No model, a slow model, a malformed answer: the scores stand."""
        if not new or not self.llm.available or ctx.budget.low():
            return
        batch = sorted(new, key=lambda r: -float(r.retrieval.get("rerank_score") or 0))[:GRADE_BATCH]
        f = ctx.board.facets
        system = (HOUSE_RULES + "Task: grade search hits. For each numbered hit, say how close the thing it describes is to the IDEA.\n"
                  "same: it does what the idea does, for the same kind of customer -- a direct competitor, or this idea already built.\n"
                  "close: the same problem or the same core mechanism, with one notable difference -- another audience, one "
                  "component rather than the whole, another approach.\n"
                  "adjacent: the same field, a different job. A tool FOR the people the idea would compete with is adjacent.\n"
                  "unrelated: anything else, and any text that only writes about the topic.\n"
                  "Judge what the thing is from its text, not the words it shares with the idea. Grade every hit.")
        user = (f"IDEA: {ctx.board.idea_text[:1500]}" + (f"\nPURPOSE: {f.purpose}\nDOMAIN: {f.domain}" if f else "") + "\n\n"
                + "\n".join(f"HIT {i} [{r.source}] {r.title[:80]} :: {(r.tagline or r.pitch or '')[:320]}" for i, r in enumerate(batch)))
        try:
            got, res = await asyncio.wait_for(self.llm.structured(role=self.id, system=system, user=user, schema=Grades, model=GRADE_MODEL, max_tokens=2500,
                                                                  session=self.session(ctx), budget=ctx.budget), GRADE_TIMEOUT_S)
        except (TimeoutError, LLMUnavailable) as exc:
            await ctx.emit("error", {"message": f"{self.id}: hits were not graded, reranker scores stand ({type(exc).__name__})", "recoverable": True}, phase=phase)
            return
        lifted = 0
        for g in got.grades:
            if not 0 <= g.n < len(batch):
                continue
            r = batch[g.n]
            before = float(r.retrieval.get("rerank_score") or 0)
            after = round(graded(raw.get(r.rid, before), g.match), 4)
            r.retrieval |= {"grade": g.match} | ({"rerank_score": after, "rerank_raw": before} if after > before else {})
            lifted += after > before
        await ctx.emit("tool.result", {"tool": "grade.hits", "n_hits": lifted, "summary":
                       f"read {len(batch)} hits beside the idea: {sum(g.match == 'same' for g in got.grades)} the same thing, "
                       f"{sum(g.match == 'close' for g in got.grades)} close; {lifted} scored higher than the reranker had them"}, phase=phase, **res.meta())

    async def handle(self, msg: dict, ctx: Ctx) -> dict:
        p = msg["payload"]
        queries = [q for q in (p.get("queries") or [p.get("query")]) if q]
        phase = "debate" if msg["type"] == "REQUEST_EVIDENCE" else "scout"
        found: dict[str, SourceRecord] = {}
        failed: str | None = None
        # The queries are independent, so they go out together: a scout costs its slowest query, not the sum of them.
        extra = self.extra(p, ctx, phase)
        outcomes = await asyncio.gather(*(self._one(q, ctx, phase) for q in queries), *(job for _, job in extra), return_exceptions=True)
        labels = queries + [label for label, _ in extra]
        for q, hits in zip(labels, outcomes):  # merged in query order, so the result does not depend on which came back first
            if isinstance(hits, SourceError):
                if failed is None:  # said once per scout; whatever the other queries returned is still real evidence
                    failed = str(hits)
                    await ctx.emit("source.failed", {"source": self.source, "error": failed, "reassigned_to": None}, phase=phase)
                continue
            if isinstance(hits, BaseException):
                raise hits
            for r in hits:
                r.retrieval.setdefault("query", q)
                found.setdefault(r.rid, r)
        if failed and not found:
            ctx.board.put("sources", self.id, self.source, SourceStatus(source=self.source, status="failed", error=failed))
            return error(failed, source=self.source)

        # The author's own project is not prior art for itself. Dropped here, at the one place every source's hits
        # pass through, and said out loud: a silently missing hit looks like a retrieval bug.
        mine = [r for r in found.values() if is_self(r, ctx.board.self_page)]
        for r in mine:
            found.pop(r.rid, None)
        if mine:
            await ctx.emit("tool.result", {"tool": self.tool, "n_hits": 0, "summary":
                           f"excluded {len(mine)} hit(s) that are the author's own link: " + ", ".join(r.title[:40] for r in mine)}, phase=phase)

        new = [r for rid, r in found.items() if rid not in ctx.board.records]
        raw: dict[str, float] = {}
        if new and not self.already_scored:
            scores, calibrated = await rerank(ctx.board.similarity_text, [r.pitch or r.title for r in new], clamp=False)
            for r, sc in zip(new, scores):
                raw[r.rid] = sc
                r.retrieval |= {"rerank_score": round(clamp01(sc), 4), "leg": "live"} | ({} if calibrated else {"uncalibrated": True})
        await self._grade(new, raw, ctx, phase)
        new = self.collapse(new, ctx)
        new.sort(key=lambda r: -float(r.retrieval.get("rerank_score") or 0))
        for r in new:
            ctx.board.put("records", self.id, r.rid, r)
            await ctx.emit("evidence.found", {"record": r.model_dump(mode="json"), "eid": eid_for(r.rid)}, phase=phase)
            sim = float(r.retrieval.get("rerank_score") or 0)
            badges = (["winner"] if r.traction.get("is_winner") else []) + (
                ["ai_written"] if r.gptzero and r.gptzero.predicted_class != "human" and r.gptzero.confidence_category == "high" else [])
            await ctx.emit("graph.patch", GraphPatch(
                add_nodes=[GraphNode(id=f"ent:{eid_for(r.rid)}", kind="entity", label=r.title[:60], source=r.source,
                                     similarity=sim, year=r.year, url=r.url, badges=badges, val=1 + 4 * min(max(sim, 0), 1))],
                add_links=[GraphLink(source="idea", target=f"ent:{eid_for(r.rid)}", kind="similar", weight=sim)]), phase=phase)

        prev = ctx.board.sources.get(self.source)
        total = (prev.n_records if prev and prev.status in ("ok", "degraded") else 0) + len(new)
        status = "degraded" if failed else "ok"
        ctx.board.put("sources", self.id, self.source, SourceStatus(source=self.source, status=status, n_records=total, error=failed))
        return result(rids=[r.rid for r in new], summary=f"{len(new)} new records from {self.source}"
                      + (f" before it failed: {failed}"[:160] if failed else ""))
