"""Tier 0: twangodev/devpost-hacks (config `all`, 2,222 projects from 2024-2026) -> prior-art index, with
semantic_pitch. These rows carry `other_links` (GitHub repos), so they double as entity-resolution ground truth.

    backend/.venv/bin/python -m ingest.download_hf --only twangodev --yes      # 6 MB, once
    backend/.venv/bin/python -m ingest.load_devpost_recent --dry-run --limit 5
    backend/.venv/bin/python -m ingest.load_devpost_recent
"""
from __future__ import annotations

import argparse
import sys

from ingest.common import Checkpoint, add_load_args, print_records, run_load
from ingest.download_hf import local_path
from ingest.schema_map import from_twangodev


def read_rows(path=None) -> list[dict]:
    import pyarrow.parquet as pq

    path = path or local_path("twangodev")
    if not path.exists():
        raise SystemExit(f"{path} is missing. Run: backend/.venv/bin/python -m ingest.download_hf --only twangodev --yes")
    rows = pq.read_table(path).to_pylist()
    rows.sort(key=lambda r: (str(r.get("hackathon")), str(r.get("url"))))  # deterministic order for --resume
    return rows


def iter_records(rows: list[dict], *, limit: int | None = None, skip: int = 0):
    seen: set[str] = set()
    for row in rows[skip: (limit if limit is not None else None)]:
        try:
            rec = from_twangodev(row)
        except Exception as exc:
            print(f"  skip {row.get('url')!r}: {type(exc).__name__}: {exc}", flush=True)
            continue
        if rec.rid in seen:  # the same project submitted to two hackathons in this dataset
            continue
        seen.add(rec.rid)
        yield rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_load_args(ap)
    ap.add_argument("--parquet", default=None, help="path to the twangodev parquet (default: data/twangodev/all/train/0000.parquet)")
    args = ap.parse_args(argv)
    from pathlib import Path

    rows = read_rows(Path(args.parquet) if args.parquet else None)
    print(f"{len(rows)} twangodev rows")
    if args.dry_run:
        print_records(iter_records(rows, limit=args.limit), semantic=not args.no_semantic)
        return 0
    ckpt = Checkpoint("devpost_recent", resume=args.resume)
    stats = run_load("devpost_recent", iter_records(rows, limit=args.limit, skip=ckpt.offset), args,
                     semantic=not args.no_semantic, checkpoint=ckpt)
    return 1 if stats.failed else 0


if __name__ == "__main__":
    sys.exit(main())
