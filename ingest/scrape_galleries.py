"""Live source: walk a hackathon's public Devpost gallery -> project pages -> SourceRecords with
first_seen_at = now (so the idea watch fires on genuinely new submissions).

    backend/.venv/bin/python -m ingest.scrape_galleries hackthenorth2026 --max-pages 1 --max-projects 5 --dry-run
    backend/.venv/bin/python -m ingest.scrape_galleries hackthenorth2026 --max-pages 3

Manners (non-negotiable): gallery + project pages only (NEVER devpost.com/software/search), descriptive
browser User-Agent, <= 1 request/second, exponential back-off on 5xx, and the crawl STOPS on the first
403 / 429 / 202-challenge. Keep --max-pages small; this is a demo feed, not a crawler.

Documents are written with op_type=create and projects that are already indexed are not even fetched, so
a re-run never resets an existing document's first_seen_at (which would re-fire every watch).
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from ingest.common import (DATA_DIR, BlockedError, PoliteFetcher, SourceRecord, bulk_index, get_es, get_settings,
                           now_utc, print_records, to_doc)
from ingest.devpost_page import parse_gallery_page, parse_project_page
from ingest.schema_map import slug_from_url


def gallery_url(subdomain: str, page: int = 1) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,80}", subdomain):
        raise SystemExit(f"{subdomain!r} is not a Devpost hackathon subdomain (expected e.g. hackthenorth2026)")
    return f"https://{subdomain}.devpost.com/project-gallery?page={page}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subdomain", help="hackathon subdomain, e.g. hackthenorth2026 (-> https://hackthenorth2026.devpost.com)")
    ap.add_argument("--max-pages", type=int, default=2, help="gallery pages to walk (24 projects each)")
    ap.add_argument("--max-projects", type=int, default=60, help="hard cap on project pages fetched in this run")
    ap.add_argument("--dry-run", action="store_true", help="fetch + parse + print; never touches Elastic")
    ap.add_argument("--index", default=None)
    args = ap.parse_args(argv)

    settings = get_settings()
    use_es = settings.has_elastic and not args.dry_run
    es = get_es() if use_es else None
    index = args.index or settings.es_index
    records: list[SourceRecord] = []
    skipped_known = 0
    url: str | None = gallery_url(args.subdomain)
    pages = 0
    with PoliteFetcher() as fetcher:
        try:
            while url and pages < args.max_pages and len(records) < args.max_projects:
                entries, next_url = parse_gallery_page(fetcher.get(url), url)
                pages += 1
                print(f"gallery page {pages}: {len(entries)} projects ({url})", flush=True)
                if not entries:
                    break
                for entry in entries:
                    if len(records) >= args.max_projects:
                        break
                    rid = f"devpost:{slug_from_url(entry['url'])}"
                    if es is not None and es.exists(index=index, id=rid):
                        skipped_known += 1
                        continue
                    try:
                        rec = parse_project_page(fetcher.get(entry["url"]), entry["url"])
                    except BlockedError:
                        raise
                    except Exception as exc:
                        print(f"  skip {entry['url']}: {type(exc).__name__}: {exc}", flush=True)
                        continue
                    rec.traction.setdefault("hackathon_id", args.subdomain)
                    if entry.get("is_winner"):
                        rec.traction["is_winner"] = True
                    records.append(rec)
                    print(f"  + {rec.rid}  {rec.title!r}", flush=True)
                url = next_url
        except BlockedError as exc:
            print(f"STOPPING: {exc}")

    print(f"{len(records)} new project pages parsed, {skipped_known} already indexed (not re-fetched)")
    if not records:
        return 0
    if args.dry_run:
        print_records(records, n=5)
        return 0
    out = DATA_DIR / "galleries" / f"{args.subdomain}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([r.model_dump(mode="json") for r in records], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out}")
    if es is None:
        print("Elastic is not configured: records were saved but NOT indexed.")
        return 0
    seen_at = now_utc()
    docs = [to_doc(r, semantic=True, first_seen_at=seen_at) for r in records]
    stats = bulk_index(docs, index=index, semantic=True, chunk_size=25, threads=1, es=es, op_type="create",
                       quarantine_index=settings.es_quarantine_index)
    print(f"indexed with first_seen_at={seen_at.isoformat()}: {stats.summary()}")
    for err in stats.first_errors:
        print(f"  error sample: {err}")
    return 1 if stats.failed else 0


if __name__ == "__main__":
    sys.exit(main())
