"""Seed the hero-demo prior art explicitly: fetch + parse a handful of public Devpost project pages into
SourceRecords, write them to data/seeds.json, and index them (semantic) when Elastic is configured.

    backend/.venv/bin/python -m ingest.seed_known_prior_art --dry-run            # fetch + parse + print, no Elastic
    backend/.venv/bin/python -m ingest.seed_known_prior_art                      # + data/seeds.json + index
    backend/.venv/bin/python -m ingest.seed_known_prior_art --url https://devpost.com/software/<slug>   # extra seeds
    backend/.venv/bin/python -m ingest.seed_known_prior_art --html-dir some/dir  # parse saved <slug>.html, no fetching

Polite by construction: project pages only (never /software/search), a descriptive browser User-Agent,
<= 1 request/second, and it STOPS on 403/429/202 instead of working around them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ingest.common import DATA_DIR, BlockedError, PoliteFetcher, SourceRecord, bulk_index, get_settings, print_records
from ingest.devpost_page import parse_project_page
from ingest.schema_map import slug_from_url

SEED_URLS = [
    "https://devpost.com/software/hackanalyzer",  # HackHarvard 2023: similarity/originality of hackathon ideas
    "https://devpost.com/software/devspot",  # HackPSU Spring 2024: validates idea originality against Devpost
    "https://devpost.com/software/plagia",  # "A plagiarism detector for hackers" (alvanlii hackathon_id 20817)
]
SEEDS_FILE = DATA_DIR / "seeds.json"


def collect(urls: list[str], html_dir: Path | None) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    fetcher = None if html_dir else PoliteFetcher()
    try:
        for url in urls:
            try:
                if html_dir:
                    html = (html_dir / f"{slug_from_url(url)}.html").read_text(encoding="utf-8")
                else:
                    html = fetcher.get(url)
                records.append(parse_project_page(html, url))
                print(f"  parsed {url} -> {records[-1].rid} ({len(records[-1].pitch)} char pitch)")
            except BlockedError as exc:
                print(f"  BLOCKED: {exc}")
                break
            except Exception as exc:
                print(f"  skip {url}: {type(exc).__name__}: {exc}")
    finally:
        if fetcher is not None:
            fetcher.close()
    return records


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", action="append", default=[], help="extra Devpost project page(s) to seed")
    ap.add_argument("--html-dir", default=None, help="read <slug>.html from this directory instead of fetching")
    ap.add_argument("--dry-run", action="store_true", help="parse and print only: no seeds.json, no Elastic")
    ap.add_argument("--index", default=None)
    args = ap.parse_args(argv)

    urls = list(dict.fromkeys([*SEED_URLS, *args.url]))
    records = collect(urls, Path(args.html_dir) if args.html_dir else None)
    if not records:
        print("no seeds parsed")
        return 1
    if args.dry_run:
        print_records(records, n=len(records))
        return 0

    SEEDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEDS_FILE.write_text(json.dumps([r.model_dump(mode="json") for r in records], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(records)} seeds to {SEEDS_FILE}")

    settings = get_settings()
    if not settings.has_elastic:
        print("Elastic is not configured (ES_URL / ES_API_KEY empty): seeds were NOT indexed. Re-run once .env is filled.")
        return 0
    stats = bulk_index(records, index=args.index or settings.es_index, semantic=True, chunk_size=10, threads=1,
                       quarantine_index=settings.es_quarantine_index)
    print(f"indexed seeds: {stats.summary()}")
    for err in stats.first_errors:
        print(f"  error sample: {err}")
    return 1 if stats.failed else 0


if __name__ == "__main__":
    sys.exit(main())
