"""Tiers 1 and 2: alvanlii/devpost-hackathon-projects (261,940 rows) -> prior-art index.

    # Tier 1 (overnight): up to 40k rows WITH semantic_pitch; winners first, then newest first
    caffeinate -i nohup backend/.venv/bin/python -m ingest.load_devpost_hf --tier 1 --limit 40000 --resume >> logs/ingest.log 2>&1 &
    # Tier 2 (minutes): every remaining row, BM25-only (full-corpus significant_text backgrounds + lexical leg)
    backend/.venv/bin/python -m ingest.load_devpost_hf --tier 2 --limit 40000 --resume
    backend/.venv/bin/python -m ingest.load_devpost_hf --tier 1 --dry-run --limit 5

Both tiers are cut from ONE deterministic order (winner desc, year desc, row asc; one row per project URL):
tier 1 = order[:limit], tier 2 = order[limit:] - so pass the SAME --limit to both. Documents are written with
op_type=create, which (a) makes re-runs cheap and (b) never clobbers a richer Tier-0 document of the same
project (twangodev rows carry links/READMEs) or downgrades a semantic document to BM25-only. Use --overwrite
to re-index after a parser fix. Sizing: measure first (`python -m ingest.measure_eis`) and pick --limit so
tier 1 finishes in <= 3 h.
"""
from __future__ import annotations

import argparse
import sys
from typing import Iterator

from ingest.common import Checkpoint, SourceRecord, add_load_args, print_records, run_load
from ingest.download_hf import local_path
from ingest.schema_map import from_alvanlii, load_hackathons, parse_listish, parse_submission_dates, slug_from_url

READ_BATCH = 2000


def build_order(path, hackathons: dict[int, dict]) -> list[int]:
    """Row indices: winners first, then newest hackathon year first, then file order; first row per project wins."""
    import pyarrow.parquet as pq

    cols = pq.read_table(path, columns=["hackathon_id", "prize", "project_link"]).to_pydict()
    year_of = {hid: (parse_submission_dates(h.get("submission_period_dates"))[0] or 0) for hid, h in hackathons.items()}
    keyed = []
    for i, (hid, prize, link) in enumerate(zip(cols["hackathon_id"], cols["prize"], cols["project_link"])):
        if not link:
            continue
        winner = prize not in (None, "", "[]") and bool(parse_listish(prize))
        keyed.append((0 if winner else 1, -year_of.get(hid, 0), i, link))
    keyed.sort()
    seen: set[str] = set()
    order: list[int] = []
    for _, _, i, link in keyed:
        slug = slug_from_url(link)
        if slug in seen:
            continue
        seen.add(slug)
        order.append(i)
    return order


def iter_records(path, order: list[int], hackathons: dict[int, dict]) -> Iterator[SourceRecord]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pq.read_table(path, memory_map=True)
    for start in range(0, len(order), READ_BATCH):
        idx = order[start:start + READ_BATCH]
        for row in table.take(pa.array(idx)).to_pylist():
            try:
                yield from_alvanlii(row, hackathons)
            except Exception as exc:  # a broken row is logged and skipped; the load keeps going
                print(f"  skip {row.get('project_link')!r}: {type(exc).__name__}: {exc}", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_load_args(ap)
    ap.add_argument("--tier", type=int, choices=(1, 2), required=True, help="1 = first --limit rows with semantic; 2 = the rest, BM25-only")
    ap.add_argument("--overwrite", action="store_true", help="op_type=index instead of create (re-index after a parser fix)")
    ap.add_argument("--max-rows", type=int, default=None, help="tier 2 only: stop after N rows of the tier (smoke runs)")
    ap.set_defaults(limit=40000)
    args = ap.parse_args(argv)

    parquet, hk_path = local_path("alvanlii"), local_path("hackathons")
    for p in (parquet, hk_path):
        if not p.exists():
            raise SystemExit(f"{p} is missing. Run: backend/.venv/bin/python -m ingest.download_hf --only alvanlii hackathons --yes")
    hackathons = load_hackathons(hk_path)
    print(f"{len(hackathons)} hackathons; computing the row order …", flush=True)
    order = build_order(parquet, hackathons)
    tier_rows = order[:args.limit] if args.tier == 1 else order[args.limit:]
    if args.tier == 2 and args.max_rows:
        tier_rows = tier_rows[:args.max_rows]
    semantic = args.tier == 1 and not args.no_semantic
    print(f"{len(order)} unique projects; tier {args.tier} = {len(tier_rows)} rows (tier-1 limit {args.limit}); semantic={semantic}")

    if args.dry_run:
        print_records(iter_records(parquet, tier_rows[:50], hackathons), semantic=semantic)
        return 0

    job = f"devpost_hf_tier{args.tier}"
    ckpt = Checkpoint(job, resume=args.resume)
    if args.tier == 2 and ckpt.offset and ckpt.state.get("tier1_limit") not in (None, args.limit):
        raise SystemExit(f"checkpoint was written with --limit {ckpt.state.get('tier1_limit')}, not {args.limit}: "
                         "tier 2 offsets would not line up. Re-run with the original --limit or without --resume.")
    ckpt.state["tier1_limit"] = args.limit
    stats = run_load(job, iter_records(parquet, tier_rows[ckpt.offset:], hackathons), args, semantic=semantic,
                     op_type="index" if args.overwrite else "create", checkpoint=ckpt)
    return 1 if stats.failed else 0


if __name__ == "__main__":
    sys.exit(main())
