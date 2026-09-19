"""Hybrid prior-art retrieval: Jina reranker <- RRF <- [BM25 multi_match, semantic(semantic_pitch)].

    text_similarity_reranker(inference_id=<settings>, field=pitch, inference_text=<FULL idea>, window 40)
      <- rrf(window 100, rank_constant 20, filter: drop too_short / non_english / excluded ids)
           <- standard multi_match(title^3, tagline^2, pitch)
           <- standard semantic(semantic_pitch)

Degradation ladder (every step is flagged on the returned records so the UI/confidence can show it):
    reranker fails  -> RRF only          retrieval["uncalibrated"] = True
    semantic fails  -> BM25 only         retrieval["degraded"] = "bm25_only" (and uncalibrated)

CLI:  cd backend && .venv/bin/python -m app.search.hybrid "validate hackathon idea originality" --size 10
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from typing import Any, Iterable, Sequence, get_args

from app.config import get_settings
from app.schemas.records import GPTZeroScan, Source, SourceRecord, Status
from app.scoring.similarity import clamp01, from_es_rerank
from app.search.es import excluded_flags_clause, get_async_es, require_elastic

SOURCE_FIELDS = [
    "rid", "source", "title", "tagline", "url", "year", "tags", "tech", "is_winner", "status", "dedupe_key", "gptzero",
    "hackathon", "pitch",
    # beyond the design's list: needed to hydrate a full SourceRecord (the resolver blocks on `links`)
    "links", "lang", "quality_flags", "date", "date_precision", "traction", "field_provenance", "prize", "first_seen_at",
]
BM25_FIELDS = ["title^3", "tagline^2", "pitch"]
RRF_WINDOW = 100
RRF_RANK_CONSTANT = 20
RERANK_WINDOW = 40
IDEA_TEXT_CAP = 2000  # chars of the idea sent to the reranker as inference_text
# Per-request cap for interactive searches (normal: 0.7-2 s). The client default (30 s x 3 attempts) let one stalled
# request eat a scout's whole 45 s slot; failing fast lets the degradation ladder below do its job.
SEARCH_TIMEOUT_S = 8.0

_SOURCES = set(get_args(Source))
_STATUSES = set(get_args(Status))


def _iso(value: dt.datetime | dt.date | str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dt.datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.isoformat()


def build_hybrid_body(
    q: str,
    idea_full: str,
    *,
    size: int = 25,
    exclude_ids: Sequence[str] = (),
    sources: Iterable[str] | None = None,
    rerank: bool = True,
    first_seen_after: dt.datetime | dt.date | str | None = None,
    semantic: bool = True,
    rerank_inference_id: str | None = None,
) -> dict[str, Any]:
    """Search body exactly per design 2.3. `q` drives both retrieval legs; the reranker always scores
    against `idea_full` (so the purpose-only and twist queries are still judged against the whole idea).

    rerank=False -> the same body without the reranker (RRF only).  semantic=False -> BM25 only (last resort).
    Inference ids come from settings - never hardcoded.
    """
    must_not: list[dict[str, Any]] = [excluded_flags_clause()]
    if exclude_ids:
        must_not.append({"ids": {"values": list(exclude_ids)}})
    bool_filter: dict[str, Any] = {"must_not": must_not}
    positive: list[dict[str, Any]] = []
    if sources:
        positive.append({"terms": {"source": list(sources)}})
    if first_seen_after is not None:
        positive.append({"range": {"first_seen_at": {"gt": _iso(first_seen_after)}}})
    if positive:
        bool_filter["filter"] = positive
    filter_query = {"bool": bool_filter}

    rerank_window = max(RERANK_WINDOW, size)  # the reranker window can never be smaller than `size`
    lexical = {"standard": {"query": {"multi_match": {"query": q, "fields": list(BM25_FIELDS)}}}}
    if semantic:
        retriever: dict[str, Any] = {
            "rrf": {
                "retrievers": [lexical, {"standard": {"query": {"semantic": {"field": "semantic_pitch", "query": q}}}}],
                "filter": filter_query,
                "rank_window_size": max(RRF_WINDOW, rerank_window),
                "rank_constant": RRF_RANK_CONSTANT,
            }
        }
    else:
        lexical["standard"]["filter"] = filter_query
        retriever = lexical
    if rerank:
        retriever = {
            "text_similarity_reranker": {
                "retriever": retriever,
                "field": "pitch",
                "inference_id": rerank_inference_id or get_settings().es_rerank_inference_id,
                "inference_text": (idea_full or q)[:IDEA_TEXT_CAP],
                "rank_window_size": rerank_window,
            }
        }
    return {"retriever": retriever, "size": size, "_source": list(SOURCE_FIELDS)}


def hit_to_record(hit: dict[str, Any], *, query: str, rank: int, reranked: bool, leg: str = "hybrid",
                  extra_retrieval: dict[str, Any] | None = None) -> SourceRecord:
    """One search hit -> SourceRecord. Tolerant by design: a malformed stored field never kills a run."""
    src = hit.get("_source") or {}
    traction = dict(src.get("traction") or {})
    for key in ("is_winner", "hackathon", "prize"):
        if src.get(key) is not None and key not in traction:
            traction[key] = src[key]
    gptzero = None
    if isinstance(src.get("gptzero"), dict):
        try:
            gptzero = GPTZeroScan.model_validate(src["gptzero"])
        except Exception:
            gptzero = None
    score = hit.get("_score")
    retrieval: dict[str, Any] = {
        "query": query,
        "leg": leg,
        "rank": rank,
        # Same 0-1 scale as a direct rerank call (the live scouts): ES shifts reranker scores to keep them positive.
        "rerank_score": round(clamp01(from_es_rerank(score)), 4) if (reranked and score is not None) else None,
        "score": score,
        "dedupe_key": src.get("dedupe_key"),
        "first_seen_at": src.get("first_seen_at"),
    }
    retrieval.update(extra_retrieval or {})

    def _list(name: str) -> list[str]:
        value = src.get(name) or []
        return [str(v) for v in (value if isinstance(value, list) else [value])]

    source = src.get("source") if src.get("source") in _SOURCES else "web"
    status = src.get("status") if src.get("status") in _STATUSES else "unknown"
    precision = src.get("date_precision") if src.get("date_precision") in ("day", "year", "inferred") else None
    date = None
    if src.get("date"):
        try:
            date = dt.date.fromisoformat(str(src["date"])[:10])
        except ValueError:
            date = None
    provenance = {k: v for k, v in (src.get("field_provenance") or {}).items() if v in ("source", "normalized", "imputed")}
    return SourceRecord(
        rid=str(src.get("rid") or hit.get("_id")), source=source, url=str(src.get("url") or ""),
        title=str(src.get("title") or ""), tagline=src.get("tagline"), description="", pitch=str(src.get("pitch") or ""),
        year=src.get("year"), date=date, date_precision=precision, tags=_list("tags"), tech=_list("tech"),
        status=status, traction=traction, links=_list("links"), lang=str(src.get("lang") or "und"),
        quality_flags=_list("quality_flags"), field_provenance=provenance, retrieval=retrieval, gptzero=gptzero,
    )


async def search(
    q: str,
    idea_full: str | None = None,
    *,
    size: int = 25,
    exclude_ids: Sequence[str] = (),
    sources: Iterable[str] | None = None,
    rerank: bool = True,
    first_seen_after: dt.datetime | dt.date | str | None = None,
    es: Any = None,
    index: str | None = None,
) -> list[SourceRecord]:
    """Run the hybrid query and map hits to SourceRecords with
    retrieval={query, leg:"hybrid", rank, rerank_score, ...}. Falls down the degradation ladder on errors."""
    settings = get_settings() if es is not None else require_elastic()  # an injected client (tests) needs no creds
    client = es if es is not None else get_async_es()
    if hasattr(client, "options"):
        client = client.options(request_timeout=SEARCH_TIMEOUT_S, max_retries=1)
    index = index or settings.es_index
    idea_full = idea_full or q
    sources = list(sources) if sources else None
    common = dict(size=size, exclude_ids=exclude_ids, sources=sources, first_seen_after=first_seen_after)

    ladder: list[tuple[dict[str, Any], dict[str, Any]]] = []
    if rerank:
        ladder.append(({"rerank": True, "semantic": True}, {}))
    ladder.append(({"rerank": False, "semantic": True}, {"uncalibrated": True} if rerank else {"uncalibrated": True, "rerank_skipped": True}))
    ladder.append(({"rerank": False, "semantic": False}, {"uncalibrated": True, "degraded": "bm25_only"}))

    last_error: Exception | None = None
    for i, (variant, flags) in enumerate(ladder):
        try:
            resp = await client.search(index=index, body=build_hybrid_body(q, idea_full, **common, **variant))
        except Exception as exc:  # inference 4xx/5xx, EIS 429, timeouts: degrade once per rung
            last_error = exc
            continue
        if i > 0 and last_error is not None:
            flags = {**flags, "degraded_reason": f"{type(last_error).__name__}: {str(last_error)[:200]}"}
        hits = (resp.get("hits") or {}).get("hits") or []
        return [hit_to_record(h, query=q, rank=n, reranked=variant["rerank"], extra_retrieval=flags)
                for n, h in enumerate(hits, 1)]
    assert last_error is not None
    raise last_error


async def search_union(
    queries: Sequence[str],
    idea_full: str,
    *,
    size: int = 25,
    exclude_ids: Sequence[str] = (),
    sources: Iterable[str] | None = None,
    rerank: bool = True,
) -> list[SourceRecord]:
    """The scout pattern: run several queries (full idea, purpose+mechanism, twist) concurrently, every one
    reranked against the FULL idea, union the hits and keep the best-scoring copy of each project.
    De-duplicates on rid, then on the pipeline's dedupe_key (same title+tagline listed twice)."""
    sources = list(sources) if sources else None
    results = await asyncio.gather(
        *[search(q, idea_full, size=size, exclude_ids=exclude_ids, sources=sources, rerank=rerank) for q in queries],
        return_exceptions=True,
    )
    ok = [r for r in results if not isinstance(r, BaseException)]
    if not ok:
        raise next(r for r in results if isinstance(r, BaseException))

    def strength(rec: SourceRecord) -> float:
        s = rec.retrieval.get("rerank_score")
        return float(s) if s is not None else float(rec.retrieval.get("score") or 0.0) - 1e6  # reranked beats un-reranked

    best: dict[str, SourceRecord] = {}
    for rec in (r for batch in ok for r in batch):
        key = rec.rid
        if key not in best or strength(rec) > strength(best[key]):
            best[key] = rec
    by_dedupe: dict[str, SourceRecord] = {}
    for rec in best.values():
        key = rec.retrieval.get("dedupe_key") or rec.rid
        if key not in by_dedupe or strength(rec) > strength(by_dedupe[key]):
            by_dedupe[key] = rec
    merged = sorted(by_dedupe.values(), key=strength, reverse=True)
    for n, rec in enumerate(merged, 1):
        rec.retrieval["union_rank"] = n
    return merged


# --------------------------------------------------------------------------------------
def _cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Hybrid prior-art search (BM25 + Jina semantic -> RRF -> Jina rerank)")
    ap.add_argument("query")
    ap.add_argument("--idea", help="full idea text for the reranker (defaults to the query)")
    ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--source", action="append", help="restrict to a source (repeatable): devpost, yc, ...")
    ap.add_argument("--exclude", action="append", default=[], help="document _id / rid to exclude (repeatable)")
    ap.add_argument("--no-rerank", action="store_true", help="RRF only")
    ap.add_argument("--print-body", action="store_true", help="print the search body and exit (works offline)")
    ap.add_argument("--json", action="store_true", help="print records as JSON lines")
    args = ap.parse_args(argv)

    if args.print_body:
        print(json.dumps(build_hybrid_body(args.query, args.idea or args.query, size=args.size, exclude_ids=args.exclude,
                                           sources=args.source, rerank=not args.no_rerank), indent=2))
        return 0

    async def run() -> list[SourceRecord]:
        from app.search.es import close_async_es

        try:
            return await search(args.query, args.idea, size=args.size, exclude_ids=args.exclude, sources=args.source,
                                rerank=not args.no_rerank)
        finally:
            await close_async_es()

    try:
        records = asyncio.run(run())
    except Exception as exc:
        print(f"search failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if not records:
        print("no hits (is the corpus ingested? run `python elastic/apply.py --check`)")
        return 1
    flags = {k: v for k, v in records[0].retrieval.items() if k in ("uncalibrated", "degraded", "degraded_reason")}
    if flags:
        print(f"!! degraded retrieval: {flags}")
    for rec in records:
        if args.json:
            print(rec.model_dump_json(exclude={"description"}))
            continue
        score = rec.retrieval.get("rerank_score") if rec.retrieval.get("rerank_score") is not None else rec.retrieval.get("score")
        win = " [winner]" if rec.traction.get("is_winner") else ""
        print(f"{rec.retrieval['rank']:>2}. {score if score is None else round(score, 4)!s:<8} [{rec.source}] {rec.title} ({rec.year or '?'}){win}")
        print(f"      {rec.url}")
        print(f"      {(rec.tagline or rec.pitch)[:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
