from __future__ import annotations

from app.orchestration.host import Ctx, error, result
from app.roles.base import BaseRole, eid_for
from app.schemas import GraphLink, GraphNode, GraphPatch, SourceRecord, SourceStatus
from app.scoring.similarity import rerank, tokens
from app.sources.http import SourceError
from app.sources.idea_url import is_self


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

    async def handle(self, msg: dict, ctx: Ctx) -> dict:
        p = msg["payload"]
        queries = [q for q in (p.get("queries") or [p.get("query")]) if q]
        phase = "debate" if msg["type"] == "REQUEST_EVIDENCE" else "scout"
        found: dict[str, SourceRecord] = {}
        failed: str | None = None
        for q in queries:
            try:
                await ctx.emit("tool.call", {"tool": self.tool, "args_summary": q[:120]}, phase=phase)
                hits = await self.search(q, self.per_query)
                if not hits and len(tokens(q)) > 3:  # adaptive broaden-and-retry: keep the 3 most specific terms
                    broad = " ".join(sorted(set(tokens(q)), key=len, reverse=True)[:3])
                    await ctx.emit("tool.call", {"tool": self.tool, "args_summary": f"broadened: {broad}"}, phase=phase)
                    hits = await self.search(broad, self.per_query)
            except SourceError as exc:
                failed = str(exc)
                await ctx.emit("source.failed", {"source": self.source, "error": failed, "reassigned_to": None}, phase=phase)
                break  # the source is unwell; whatever earlier queries returned is still real evidence
            await ctx.emit("tool.result", {"tool": self.tool, "summary": f"{len(hits)} hits", "n_hits": len(hits)}, phase=phase)
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
        if new and not self.already_scored:
            scores, calibrated = await rerank(ctx.board.idea_text, [r.pitch or r.title for r in new])
            for r, sc in zip(new, scores):
                r.retrieval |= {"rerank_score": round(sc, 4), "leg": "live"} | ({} if calibrated else {"uncalibrated": True})
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
