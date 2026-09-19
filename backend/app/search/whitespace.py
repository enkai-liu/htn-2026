"""Whitespace finder: which popular technologies / themes are (almost) absent from an idea's neighbourhood?

    1. neighbourhood = top-200 documents for the PURPOSE-ONLY query (RRF, no reranker - we need breadth)
    2. terms aggregation on `tech` and `tags` over exactly those ids
    3. compare with a cached global top-150 of the whole corpus
    4. candidate  <=>  global_count >= 500  and  neighbourhood_count <= 1

The candidates seed the mutator ("move one facet into the whitespace") and are LLM-filtered downstream.
`whitespace_candidates` is pure and unit-tested; the rest needs Elastic.
"""
from __future__ import annotations

import time
from typing import Any, Iterable, Mapping

from app.config import get_settings
from app.search.es import excluded_flags_clause, get_async_es, require_elastic
from app.search.hybrid import build_hybrid_body

FIELDS = ("tech", "tags")
GLOBAL_TOP = 150
NEIGHBOURHOOD_SIZE = 200
MIN_GLOBAL = 500
MAX_LOCAL = 1
FULL_CORPUS_DOCS = 262_000  # the thresholds above were chosen for the full Devpost corpus
CACHE_TTL_S = 3600.0

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def clear_cache() -> None:
    _cache.clear()


# --------------------------------------------------------------------------------------
# Pure
# --------------------------------------------------------------------------------------
def effective_min_global(total_docs: int, min_global: int = MIN_GLOBAL) -> int:
    """500 is right for ~262k docs. While only Tier 0/1 is loaded, scale it down (floor 25) so the finder
    still returns something instead of silently going empty."""
    if total_docs >= 100_000:
        return min_global
    return max(25, round(min_global * total_docs / FULL_CORPUS_DOCS))


def whitespace_candidates(
    global_counts: Mapping[str, int],
    neighbourhood_counts: Mapping[str, int],
    *,
    min_global: int = MIN_GLOBAL,
    max_local: int = MAX_LOCAL,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Terms that are popular globally but (nearly) unused next to this idea, most popular first."""
    out = [
        {"term": term, "global_count": g, "neighbourhood_count": int(neighbourhood_counts.get(term, 0))}
        for term, g in global_counts.items()
        if g >= min_global and int(neighbourhood_counts.get(term, 0)) <= max_local
    ]
    out.sort(key=lambda c: (-c["global_count"], c["term"]))
    return out[:limit]


def build_global_terms_body(size: int = GLOBAL_TOP) -> dict[str, Any]:
    return {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"must_not": [excluded_flags_clause()]}},
        "aggs": {f: {"terms": {"field": f, "size": size}} for f in FIELDS},
    }


def build_neighbour_ids_body(purpose: str, *, size: int = NEIGHBOURHOOD_SIZE, sources: Iterable[str] | None = None) -> dict[str, Any]:
    body = build_hybrid_body(purpose, purpose, size=size, sources=sources, rerank=False)
    body["_source"] = False
    return body


def build_terms_over_ids_body(ids: list[str], include: Mapping[str, list[str]] | None = None) -> dict[str, Any]:
    aggs: dict[str, Any] = {}
    for f in FIELDS:
        terms: dict[str, Any] = {"field": f, "size": max(GLOBAL_TOP, 10)}
        if include and include.get(f):
            terms["include"] = list(include[f])  # exact counts for the global top terms only
            terms["size"] = len(include[f])
        aggs[f] = {"terms": terms}
    return {"size": 0, "query": {"ids": {"values": ids}}, "aggs": aggs}


def _counts(resp: Mapping[str, Any], field: str) -> dict[str, int]:
    return {str(b["key"]): int(b["doc_count"]) for b in ((resp.get("aggregations") or {}).get(field) or {}).get("buckets", [])}


# --------------------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------------------
async def global_top_terms(*, es: Any = None, index: str | None = None, size: int = GLOBAL_TOP, refresh: bool = False) -> dict[str, Any]:
    """{"total": <docs>, "tech": {term: count}, "tags": {...}} - cached for an hour per index."""
    settings = get_settings() if es is not None else require_elastic()
    index = index or settings.es_index
    hit = _cache.get(index)
    if hit and not refresh and time.monotonic() - hit[0] < CACHE_TTL_S:
        return hit[1]
    client = es if es is not None else get_async_es()
    resp = dict(await client.search(index=index, body=build_global_terms_body(size)))
    total = (resp.get("hits") or {}).get("total") or {}
    data = {"total": int(total.get("value", 0)) if isinstance(total, dict) else int(total or 0),
            **{f: _counts(resp, f) for f in FIELDS}}
    _cache[index] = (time.monotonic(), data)
    return data


async def neighbourhood_terms(purpose: str, *, es: Any = None, index: str | None = None, size: int = NEIGHBOURHOOD_SIZE,
                              sources: Iterable[str] | None = None, include: Mapping[str, list[str]] | None = None) -> dict[str, Any]:
    settings = get_settings() if es is not None else require_elastic()
    index = index or settings.es_index
    client = es if es is not None else get_async_es()
    try:
        first = await client.search(index=index, body=build_neighbour_ids_body(purpose, size=size, sources=sources))
    except Exception:  # semantic leg unavailable (EIS): a BM25 neighbourhood is still informative
        body = build_hybrid_body(purpose, purpose, size=size, sources=sources, rerank=False, semantic=False)
        body["_source"] = False
        first = await client.search(index=index, body=body)
    ids = [h["_id"] for h in (first.get("hits") or {}).get("hits", [])]
    if not ids:
        return {"n": 0, **{f: {} for f in FIELDS}}
    resp = dict(await client.search(index=index, body=build_terms_over_ids_body(ids, include)))
    return {"n": len(ids), **{f: _counts(resp, f) for f in FIELDS}}


async def find_whitespace(purpose: str, *, es: Any = None, index: str | None = None, min_global: int | None = None,
                          max_local: int = MAX_LOCAL, sources: Iterable[str] | None = None, limit: int = 25) -> dict[str, Any]:
    """-> {"tech": [candidates], "tags": [candidates], "neighbourhood_size", "min_global", "corpus_docs"}"""
    glob = await global_top_terms(es=es, index=index)
    threshold = min_global if min_global is not None else effective_min_global(glob["total"])
    include = {f: list(glob[f]) for f in FIELDS}
    local = await neighbourhood_terms(purpose, es=es, index=index, sources=sources, include=include)
    return {
        "neighbourhood_size": local["n"],
        "corpus_docs": glob["total"],
        "min_global": threshold,
        "max_local": max_local,
        **{f: whitespace_candidates(glob[f], local[f], min_global=threshold, max_local=max_local, limit=limit) if local["n"] else []
           for f in FIELDS},
    }
