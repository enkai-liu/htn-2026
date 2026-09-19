"""Tier 0: YC companies (yc-oss.github.io, ~6k companies, one ~10 MB JSON) -> prior-art index, with semantic_pitch.

    backend/.venv/bin/python -m ingest.load_yc --dry-run --limit 5     # map + print, never touches Elastic
    backend/.venv/bin/python -m ingest.load_yc                         # index everything (semantic)
"""
from __future__ import annotations

import argparse
import json
import sys

from ingest.common import DATA_DIR, add_load_args, print_records, run_load
from ingest.schema_map import from_yc

YC_ALL_URL = "https://yc-oss.github.io/api/companies/all.json"
CACHE = DATA_DIR / "yc" / "all.json"


def fetch_companies(*, refresh: bool = False, url: str = YC_ALL_URL) -> list[dict]:
    if CACHE.exists() and not refresh:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    import httpx

    print(f"fetching {url} …", flush=True)
    resp = httpx.get(url, timeout=60, follow_redirects=True, headers={"User-Agent": "Whitespace-HTN2026/0.1 (hackathon project)"})
    resp.raise_for_status()
    companies = resp.json()
    try:  # cache is a convenience (data/ is git-ignored); a read-only checkout must not break the load
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(companies), encoding="utf-8")
    except OSError as exc:
        print(f"  (could not cache to {CACHE}: {exc})")
    return companies


def iter_records(companies: list[dict], *, limit: int | None = None, skip: int = 0):
    companies = sorted(companies, key=lambda c: str(c.get("slug") or c.get("name") or ""))  # deterministic for --resume
    for company in companies[skip: (limit if limit is not None else None)]:
        try:
            yield from_yc(company)
        except Exception as exc:  # one malformed company must not stop the load
            print(f"  skip {company.get('slug')!r}: {type(exc).__name__}: {exc}", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_load_args(ap)
    ap.add_argument("--refresh", action="store_true", help="re-download instead of using data/yc/all.json")
    args = ap.parse_args(argv)
    companies = fetch_companies(refresh=args.refresh)
    print(f"{len(companies)} YC companies")
    if args.dry_run:
        print_records(iter_records(companies, limit=args.limit), semantic=not args.no_semantic)
        return 0
    from ingest.common import Checkpoint

    ckpt = Checkpoint("yc", resume=args.resume)
    stats = run_load("yc", iter_records(companies, limit=args.limit, skip=ckpt.offset), args,
                     semantic=not args.no_semantic, checkpoint=ckpt)
    return 1 if stats.failed else 0


if __name__ == "__main__":
    sys.exit(main())
