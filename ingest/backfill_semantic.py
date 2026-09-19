"""After Tier 2: add `semantic_pitch` to BM25-only documents with bulk partial updates, newest first.

    backend/.venv/bin/python -m ingest.backfill_semantic --dry-run
    caffeinate -i backend/.venv/bin/python -m ingest.backfill_semantic --limit 20000 --min-year 2022

Only documents with has_semantic != true are touched, and documents the pipeline flagged too_short /
non_english are skipped (they are filtered out of every search, so embedding them would only burn EIS tokens).
Updates go through `pipeline=_none`: the clean pipeline already ran when the document was first indexed, and
running it on a partial doc would mis-compute quality_flags.
Safe to re-run / interrupt: finished documents drop out of the query.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Iterator

from ingest.common import QUALITY_FLAGS_EXCLUDED, bulk_index, get_es, require_elastic

PAGE = 1000


def build_query(min_year: int | None = None) -> dict[str, Any]:
    bool_q: dict[str, Any] = {
        "must": [{"exists": {"field": "pitch"}}],
        "must_not": [{"term": {"has_semantic": True}}, {"terms": {"quality_flags": list(QUALITY_FLAGS_EXCLUDED)}}],
    }
    if min_year is not None:
        bool_q["filter"] = [{"range": {"year": {"gte": min_year}}}]
    return {"bool": bool_q}


def iter_updates(es: Any, index: str, *, min_year: int | None, limit: int | None) -> Iterator[dict[str, Any]]:
    """search_after over (year desc, rid asc): stable even while documents leave the result set."""
    sort = [{"year": {"order": "desc", "missing": "_last"}}, {"rid": "asc"}]
    after = None
    sent = 0
    while True:
        body: dict[str, Any] = {"size": PAGE, "query": build_query(min_year), "sort": sort, "_source": ["rid", "pitch"]}
        if after is not None:
            body["search_after"] = after
        hits = es.search(index=index, body=body)["hits"]["hits"]
        if not hits:
            return
        for h in hits:
            pitch = (h.get("_source") or {}).get("pitch")
            if pitch:
                yield {"rid": h["_id"], "doc": {"semantic_pitch": pitch, "has_semantic": True}}
                sent += 1
                if limit is not None and sent >= limit:
                    return
        after = hits[-1]["sort"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="count the backlog and show the first ids; change nothing")
    ap.add_argument("--limit", type=int, default=None, help="max documents to backfill in this run")
    ap.add_argument("--min-year", type=int, default=None, help="only documents from this year on")
    ap.add_argument("--index", default=None)
    ap.add_argument("--chunk-size", type=int, default=50)
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args(argv)

    settings = require_elastic()
    index = args.index or settings.es_index
    es = get_es()
    backlog = es.count(index=index, body={"query": build_query(args.min_year)})["count"]
    print(f"{backlog} documents in {index} still lack semantic_pitch" + (f" (year >= {args.min_year})" if args.min_year else ""))
    if args.dry_run:
        for upd in iter_updates(es, index, min_year=args.min_year, limit=5):
            print(f"  would update {upd['rid']}  ({len(upd['doc']['semantic_pitch'])} chars)")
        return 0

    def progress(n: int, stats: Any) -> None:
        print(f"[backfill] {stats.summary()}", flush=True)

    stats = bulk_index(iter_updates(es, index, min_year=args.min_year, limit=args.limit), index=index, semantic=True,
                       op_type="update", pipeline="_none", chunk_size=args.chunk_size, threads=args.threads, es=es,
                       on_batch_done=progress)
    print(f"[backfill] DONE {stats.summary()}")
    for err in stats.first_errors:
        print(f"[backfill]   error sample: {err}")
    return 1 if stats.failed else 0


if __name__ == "__main__":
    sys.exit(main())
