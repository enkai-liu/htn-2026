"""Scouts over the indexed corpus (Devpost hackathon projects, YC companies) via Elasticsearch hybrid search."""
from __future__ import annotations

from app.orchestration.registry import register
from app.schemas import SourceRecord
from app.sources.http import SourceError

from .base import ScoutRole


class CorpusScout(ScoutRole):
    already_scored = True  # hybrid search reranks against the full idea with the Jina reranker
    per_query = 12
    idea_full = ""

    async def handle(self, msg: dict, ctx):
        self.idea_full = ctx.board.idea_text
        return await super().handle(msg, ctx)

    async def search(self, query: str, n: int) -> list[SourceRecord]:
        try:
            from app.search.hybrid import search as hybrid_search  # spine lane
        except ImportError as exc:
            raise SourceError(f"search module unavailable: {exc}") from exc
        try:
            return await hybrid_search(query, self.idea_full or query, size=n, sources=[self.source])
        except Exception as exc:  # connection, auth, missing index, inference endpoint down
            raise SourceError(f"elasticsearch: {type(exc).__name__}: {exc}"[:200]) from exc


class DevpostScout(CorpusScout):
    id, source, tool = "scout.devpost", "devpost", "es.hybrid_search[devpost] (BM25 + Jina semantic, RRF, Jina rerank)"


class YCScout(CorpusScout):
    id, source, tool = "scout.yc", "yc", "es.hybrid_search[yc] (BM25 + Jina semantic, RRF, Jina rerank)"
    per_query = 6


register("scout.devpost")(DevpostScout)
register("scout.yc")(YCScout)
