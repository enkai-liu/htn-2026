"""Shared plumbing for every `python -m ingest.<name>` script.

* puts `backend/` on sys.path so `app.config` / `app.schemas` import from the repo root
* sync Elasticsearch client factory from settings (+ a clear error when credentials are missing)
* `to_doc`      SourceRecord -> Elasticsearch document (`semantic_pitch` only when semantic=True)
* `bulk_index`  bulk helper with 429 back-off, `_id = rid`, per-run stats, client-side quarantine
* `Checkpoint`  JSON file under ingest/.checkpoints/ for `--resume`
* `PoliteFetcher` 1 req/s HTML fetcher that STOPS on 403 / 429 / 202-challenge instead of working around it
"""
from __future__ import annotations

import datetime as dt
import json
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:  # `python -m ingest.x` runs from the repo root, `app` lives in backend/
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import DATA_DIR, Settings, get_settings  # noqa: E402
from app.schemas.records import SourceRecord  # noqa: E402

CHECKPOINT_DIR = Path(__file__).resolve().parent / ".checkpoints"
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})  # EIS throttling shows up as 429 (sometimes 5xx)
QUALITY_FLAGS_EXCLUDED = ("too_short", "non_english")


class ElasticNotConfigured(RuntimeError):
    pass


def require_elastic(settings: Settings | None = None) -> Settings:
    settings = settings or get_settings()
    if not settings.has_elastic:
        raise ElasticNotConfigured(
            "Elastic is not configured: set ES_URL and ES_API_KEY in the repo-root .env "
            "(see .env.example), then run `backend/.venv/bin/python elastic/apply.py --check`."
        )
    return settings


def get_es(settings: Settings | None = None, *, request_timeout: float = 180.0):
    """Sync client. 429 is deliberately NOT retried by the transport (it retries without back-off);
    `bulk_index` handles it with exponential back-off and counts it."""
    import os

    from elasticsearch import Elasticsearch

    settings = require_elastic(settings)
    return Elasticsearch(
        settings.es_url,
        api_key=settings.es_api_key,
        request_timeout=request_timeout,
        max_retries=2,
        retry_on_timeout=False,
        retry_on_status=(502, 503, 504),
        http_compress=True,
        # Serverless normally accepts the default headers; export ES_SERVER_MODE=serverless if it complains
        # about the "compatible-with" media type.
        server_mode=os.environ.get("ES_SERVER_MODE", "stack"),
    )


# --------------------------------------------------------------------------------------
# SourceRecord -> document
# --------------------------------------------------------------------------------------
def _iso(value: dt.date | dt.datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.isoformat()
    return value.isoformat()


def to_doc(
    record: SourceRecord,
    *,
    semantic: bool,
    first_seen_at: dt.datetime | dt.date | str | None = None,
    with_sections: bool = True,
) -> dict[str, Any]:
    """Build the Elasticsearch document for `prior-art-v1` (mapping is `dynamic: strict`).

    * `semantic_pitch` (semantic_text -> Jina on EIS) is only set when `semantic=True`; Tier 2 is BM25-only.
    * `first_seen_at` defaults to the project's own date so historical loads never trigger the watch;
      only live-scraped documents pass `first_seen_at=now`.
    * `retrieval` is query-time state and is never indexed. `quality_flags`, `dedupe_key`, `lang` (when
      lang_ident is available) and `ingested_at` are owned by the ingest pipeline.
    """
    from ingest.parse_sections import parse_sections  # local import: keeps `common` import-light

    tr = dict(record.traction or {})
    doc: dict[str, Any] = {
        "rid": record.rid,
        "source": record.source,
        "url": record.url,
        "title": record.title,
        "tagline": record.tagline,
        "description": record.description,
        "pitch": record.pitch,
        "year": record.year,
        "date": _iso(record.date),
        "date_precision": record.date_precision,
        "tags": list(record.tags),
        "tech": list(record.tech),
        "links": list(record.links),
        "status": record.status,
        "traction": tr,
        "field_provenance": dict(record.field_provenance),
        "lang": record.lang,
        "quality_flags": list(record.quality_flags),
        "hackathon": tr.get("hackathon"),
        "hackathon_id": None if tr.get("hackathon_id") is None else str(tr["hackathon_id"]),
        "is_winner": bool(tr["is_winner"]) if "is_winner" in tr else None,
        "prize": "; ".join(map(str, tr["prize"])) if isinstance(tr.get("prize"), (list, tuple)) else tr.get("prize"),
        "has_semantic": bool(semantic),
    }
    seen = first_seen_at or record.date or (f"{record.year:04d}-01-01" if record.year else None)
    doc["first_seen_at"] = _iso(seen)
    if record.gptzero is not None:
        doc["gptzero"] = record.gptzero.model_dump(mode="json", exclude_none=True)
    if with_sections and record.source == "devpost" and record.description:
        writeup = record.description.split("\n\n## README (", 1)[0]  # appended READMEs are not write-up sections
        sections = {k.replace(":", "_"): v for k, v in parse_sections(writeup).items()}
        if sections:
            doc["sections"] = sections  # object with enabled:false -> stored, not indexed
    if semantic and record.pitch:
        doc["semantic_pitch"] = record.pitch
    return {k: v for k, v in doc.items() if v is not None and v != {}}


# --------------------------------------------------------------------------------------
# Bulk indexing
# --------------------------------------------------------------------------------------
@dataclass
class BulkStats:
    ok: int = 0
    skipped_existing: int = 0  # op_type=create hitting a document that is already there (409)
    failed: int = 0
    quarantined: int = 0
    retried: int = 0
    rounds: int = 0
    seconds: float = 0.0
    status_counts: Counter = field(default_factory=Counter)  # every non-2xx item status, incl. retried 429s
    first_errors: list[str] = field(default_factory=list)

    @property
    def http_429(self) -> int:
        return self.status_counts.get(429, 0)

    @property
    def docs_per_s(self) -> float:
        return round(self.ok / self.seconds, 2) if self.seconds > 0 else 0.0

    def merge(self, other: "BulkStats") -> None:
        for name in ("ok", "skipped_existing", "failed", "quarantined", "retried", "rounds", "seconds"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.status_counts.update(other.status_counts)
        self.first_errors = (self.first_errors + other.first_errors)[:5]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "skipped_existing": self.skipped_existing, "failed": self.failed,
            "quarantined": self.quarantined, "retried": self.retried, "rounds": self.rounds,
            "seconds": round(self.seconds, 2), "docs_per_s": self.docs_per_s, "http_429": self.http_429,
            "status_counts": {str(k): v for k, v in sorted(self.status_counts.items(), key=lambda kv: str(kv[0]))},
            "first_errors": self.first_errors,
        }

    def summary(self) -> str:
        d = self.as_dict()
        return (f"ok={d['ok']} skipped_existing={d['skipped_existing']} failed={d['failed']} quarantined={d['quarantined']} "
                f"retried={d['retried']} 429s={d['http_429']} {d['docs_per_s']} docs/s in {d['seconds']}s")


def chunked(items: Iterable[Any], size: int) -> Iterator[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _as_action(doc: Any, *, index: str, semantic: bool, op_type: str) -> dict[str, Any]:
    if isinstance(doc, SourceRecord):
        doc = to_doc(doc, semantic=semantic)
    else:
        doc = dict(doc)
        if not semantic:
            doc.pop("semantic_pitch", None)
            doc["has_semantic"] = False
        elif doc.get("pitch") and "semantic_pitch" not in doc:
            doc["semantic_pitch"] = doc["pitch"]
            doc["has_semantic"] = True
    if op_type == "update":  # partial update: caller passes {"rid": .., "doc": {...}}
        return {"_op_type": "update", "_index": index, "_id": doc["rid"], "doc": doc["doc"]}
    return {"_op_type": op_type, "_index": index, "_id": doc["rid"], "_source": doc}


def _error_text(info: Mapping[str, Any]) -> str:
    err = info.get("error")
    if isinstance(err, Mapping):
        cause = err.get("caused_by") or {}
        return f"{err.get('type')}: {err.get('reason')}" + (f" <- {cause.get('type')}: {cause.get('reason')}" if cause else "")
    return str(err)


def bulk_index(
    docs: Iterable[SourceRecord | Mapping[str, Any]],
    *,
    index: str,
    semantic: bool,
    chunk_size: int = 50,
    threads: int = 4,
    es: Any = None,
    op_type: str = "index",
    pipeline: str | None = None,
    max_retries: int = 6,
    initial_backoff: float = 2.0,
    max_backoff: float = 60.0,
    batch_size: int | None = None,
    quarantine_index: str | None = None,
    on_batch_done: Callable[[int, BulkStats], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> BulkStats:
    """Index `docs` with `_id = rid` (re-runs are idempotent) and return per-run stats.

    Uses `helpers.parallel_bulk` (threads > 1) or `helpers.streaming_bulk` for each pass. The helpers
    either hide 429 retries (streaming) or do not retry at all (parallel), so retries live here: items that
    fail with a retryable status - or a whole pass that dies on a timeout - go into another round after an
    exponential back-off with jitter, and every 429 is counted (measure_eis needs the number).
    Items that fail permanently (mapping / inference 4xx) are copied to the quarantine index with
    `ingest_error`, mirroring what the ingest pipeline's on_failure does server-side.

    Work is done in macro-batches (`batch_size` docs); `on_batch_done(n_docs_in_batch, stats)` fires after
    each one so loaders can persist a checkpoint.
    """
    from elasticsearch import helpers
    from elastic_transport import TransportError

    client = es if es is not None else get_es()
    total = BulkStats()
    started = time.monotonic()
    batch_size = batch_size or max(chunk_size * max(threads, 1) * 8, 500)
    bulk_kwargs: dict[str, Any] = {"pipeline": pipeline} if pipeline else {}

    def one_pass(actions: list[dict[str, Any]]) -> Iterator[tuple[bool, dict[str, Any]]]:
        common = dict(chunk_size=chunk_size, max_chunk_bytes=20 * 1024 * 1024, raise_on_error=False,
                      raise_on_exception=False, **bulk_kwargs)
        if threads <= 1:
            yield from helpers.streaming_bulk(client, actions, max_retries=0, **common)
        else:
            yield from helpers.parallel_bulk(client, actions, thread_count=threads, queue_size=threads, **common)

    for batch in chunked(docs, batch_size):
        stats = BulkStats()
        pending = {}
        for d in batch:
            action = _as_action(d, index=index, semantic=semantic, op_type=op_type)
            pending[action["_id"]] = action
        dead: list[tuple[dict[str, Any], str]] = []
        for attempt in range(max_retries + 1):
            stats.rounds += 1
            retry_ids: list[str] = []
            try:
                for ok, item in one_pass(list(pending.values())):
                    _, info = next(iter(item.items()))
                    _id, status = info.get("_id"), info.get("status")
                    if ok:
                        stats.ok += 1
                        pending.pop(_id, None)
                        continue
                    stats.status_counts[status] += 1
                    if status == 409 and op_type == "create":
                        stats.skipped_existing += 1
                        pending.pop(_id, None)
                    elif status in RETRYABLE_STATUS:
                        retry_ids.append(_id)
                    else:
                        stats.failed += 1
                        reason = _error_text(info)
                        if len(stats.first_errors) < 5:
                            stats.first_errors.append(f"{_id}: [{status}] {reason}"[:400])
                        action = pending.pop(_id, None)
                        if action is not None:
                            dead.append((action, f"[{status}] {reason}"))
            except TransportError as exc:  # timeout / connection reset mid-pass: everything still pending is retried
                stats.status_counts[type(exc).__name__] += 1
                retry_ids = list(pending)
                if len(stats.first_errors) < 5:
                    stats.first_errors.append(f"transport: {type(exc).__name__}: {exc}"[:400])
            if not pending or not retry_ids:
                break
            if attempt == max_retries:
                break
            stats.retried += len(retry_ids)
            delay = min(max_backoff, initial_backoff * (2 ** attempt)) * (0.5 + random.random() / 2)
            print(f"  [bulk] {len(retry_ids)} docs throttled/unavailable (429s so far: {stats.http_429}); "
                  f"retry {attempt + 1}/{max_retries} in {delay:.1f}s", flush=True)
            sleep(delay)
        for _id, action in pending.items():  # still pending after all rounds
            stats.failed += 1
            dead.append((action, "gave up after retries (throttled / unavailable)"))
        if dead and quarantine_index and op_type != "update":
            stats.quarantined += _quarantine(client, dead, quarantine_index)
        total.merge(stats)
        total.seconds = time.monotonic() - started
        if on_batch_done is not None:
            on_batch_done(len(batch), total)
    total.seconds = time.monotonic() - started
    return total


def _quarantine(client: Any, dead: list[tuple[dict[str, Any], str]], quarantine_index: str) -> int:
    """Best-effort copy of rejected documents (without the semantic field) to the lenient quarantine index."""
    from elasticsearch import helpers

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    actions = []
    for action, reason in dead:
        src = {k: v for k, v in (action.get("_source") or {}).items() if k != "semantic_pitch"}
        src.update(ingest_error=reason[:2000], ingested_at=now, quarantined_by="client")
        actions.append({"_op_type": "index", "_index": quarantine_index, "_id": action["_id"], "_source": src})
    try:
        ok, _ = helpers.bulk(client, actions, raise_on_error=False, raise_on_exception=False, pipeline="_none")
        return int(ok)
    except Exception as exc:  # quarantine is a courtesy; never let it kill an ingest run
        print(f"  [bulk] could not write {len(actions)} docs to {quarantine_index}: {exc}", flush=True)
        return 0


# --------------------------------------------------------------------------------------
# Checkpoints
# --------------------------------------------------------------------------------------
class Checkpoint:
    """Offset into a *deterministically ordered* row stream. `_id = rid` makes a partially repeated
    batch harmless, so we only ever need "how many rows of the stream are done"."""

    def __init__(self, job: str, *, resume: bool, directory: Path | None = None):
        self.path = (directory or CHECKPOINT_DIR) / f"{job}.json"
        self.state: dict[str, Any] = {"job": job, "offset": 0}
        if resume and self.path.exists():
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
            print(f"[checkpoint] resuming {job} at offset {self.offset} ({self.path})")
        elif self.path.exists():
            print(f"[checkpoint] ignoring existing {self.path.name} (pass --resume to continue from offset "
                  f"{json.loads(self.path.read_text(encoding="utf-8")).get('offset')})")

    @property
    def offset(self) -> int:
        return int(self.state.get("offset", 0))

    def advance(self, n: int, stats: BulkStats | None = None, **extra: Any) -> None:
        self.state["offset"] = self.offset + n
        self.state["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        if stats is not None:
            self.state["stats"] = stats.as_dict()
        self.state.update(extra)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1))
        tmp.replace(self.path)  # atomic: a crash never leaves a half-written checkpoint


# --------------------------------------------------------------------------------------
# Polite fetching (Devpost project pages, galleries, /api/hackathons - NEVER /software/search)
# --------------------------------------------------------------------------------------
class BlockedError(RuntimeError):
    """The site said no (403 / 429 / 202 challenge). We stop; we do not work around it."""


class PoliteFetcher:
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36 Whitespace-HTN2026/0.1 (student hackathon project; max 1 req/s)"
    )
    FORBIDDEN_PATHS = ("/software/search",)  # behind bot detection; deliberately left alone

    def __init__(self, *, min_interval: float = 1.0, timeout: float = 20.0, max_retries: int = 3):
        import httpx

        self.min_interval = max(1.0, float(min_interval))  # hard floor: never faster than 1 request / second
        self.max_retries = max_retries
        self._last = 0.0
        self._client = httpx.Client(
            timeout=timeout, follow_redirects=True,
            headers={"User-Agent": self.USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/json;q=0.9",
                     "Accept-Language": "en-US,en;q=0.9"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PoliteFetcher":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def get(self, url: str) -> str:
        import httpx
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        if parts.netloc.endswith("devpost.com") and any(parts.path.startswith(p) for p in self.FORBIDDEN_PATHS):
            raise ValueError(f"refusing to fetch {url}: {parts.path} is off-limits by project policy")
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                resp = self._client.get(url)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise
                time.sleep(min(30.0, 2.0 * 2 ** attempt))
                print(f"  [fetch] {type(exc).__name__} on {url}; retrying", flush=True)
                continue
            if resp.status_code in (403, 429) or resp.status_code == 202:
                raise BlockedError(f"{url} answered HTTP {resp.status_code}; stopping instead of working around it")
            if resp.status_code >= 500 and attempt < self.max_retries:
                time.sleep(min(30.0, 2.0 * 2 ** attempt))
                continue
            resp.raise_for_status()
            return resp.text
        raise RuntimeError(f"could not fetch {url}")


# --------------------------------------------------------------------------------------
# Shared CLI plumbing for the loaders
# --------------------------------------------------------------------------------------
def add_load_args(ap: Any, *, chunk_size: int = 50, threads: int = 4) -> None:
    ap.add_argument("--dry-run", action="store_true", help="map rows and print records; never touches Elastic")
    ap.add_argument("--limit", type=int, default=None, help="only the first N rows")
    ap.add_argument("--index", default=None, help="target index (default: settings.es_index)")
    ap.add_argument("--chunk-size", type=int, default=chunk_size, help="docs per bulk request (EIS embeds every doc: keep it small)")
    ap.add_argument("--threads", type=int, default=threads, help="parallel bulk workers")
    ap.add_argument("--no-semantic", action="store_true", help="BM25-only: do not populate semantic_pitch")
    ap.add_argument("--resume", action="store_true", help="continue from ingest/.checkpoints/<job>.json")


def print_records(records: Iterable[SourceRecord], *, n: int = 5, semantic: bool = True) -> int:
    """--dry-run output: a readable summary per record plus the exact document of the first one."""
    count = 0
    for rec in records:
        count += 1
        if count > n:
            continue
        min_len = 60 if rec.source == "yc" else 250  # same rule as the prior-art-clean pipeline script
        flags = (["too_short"] if len(rec.pitch) < min_len else []) + (["non_english"] if rec.lang not in ("en", "und") else [])
        print(f"--- {rec.rid}  [{rec.source}] {rec.title!r}  year={rec.year} status={rec.status} lang={rec.lang} "
              f"would_flag={flags or '-'}")
        print(f"    url:      {rec.url}")
        print(f"    tagline:  {(rec.tagline or '')[:140]}")
        print(f"    pitch:    ({len(rec.pitch)} chars) {rec.pitch[:220]}{'…' if len(rec.pitch) > 220 else ''}")
        print(f"    tags={rec.tags[:6]} tech={rec.tech[:8]} links={rec.links[:3]}")
        print(f"    traction={json.dumps(rec.traction, ensure_ascii=False, default=str)[:200]}")
        print(f"    provenance={rec.field_provenance}")
        if count == 1:
            doc = to_doc(rec, semantic=semantic)
            doc = {k: (v if not isinstance(v, str) or len(v) < 160 else v[:160] + "…") for k, v in doc.items() if k != "sections"}
            print("    first document as it would be indexed (sections omitted, long strings cut):")
            print("    " + json.dumps(doc, ensure_ascii=False, default=str, indent=1).replace("\n", "\n    "))
    print(f"\n[dry-run] mapped {count} records; nothing was sent to Elastic.")
    return count


def run_load(job: str, records: Iterable[SourceRecord], args: Any, *, semantic: bool, op_type: str = "index",
             skip: int = 0, checkpoint: "Checkpoint | None" = None) -> BulkStats:
    """records -> bulk_index with a checkpoint after every macro-batch. `records` must already be positioned
    after the checkpoint offset (callers slice their deterministic row order with `checkpoint.offset`)."""
    settings = require_elastic()
    index = args.index or settings.es_index
    ckpt = checkpoint or Checkpoint(job, resume=getattr(args, "resume", False))
    print(f"[{job}] -> {index}  semantic={semantic} op_type={op_type} chunk_size={args.chunk_size} threads={args.threads} "
          f"start_offset={ckpt.offset}", flush=True)

    def progress(n: int, stats: BulkStats) -> None:
        ckpt.advance(n, stats)
        print(f"[{job}] offset={ckpt.offset}  {stats.summary()}", flush=True)

    stats = bulk_index(records, index=index, semantic=semantic, chunk_size=args.chunk_size, threads=args.threads,
                       op_type=op_type, quarantine_index=settings.es_quarantine_index, on_batch_done=progress)
    print(f"[{job}] DONE  {stats.summary()}")
    for err in stats.first_errors:
        print(f"[{job}]   error sample: {err}")
    return stats


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


__all__ = [
    "REPO_ROOT", "BACKEND_DIR", "DATA_DIR", "CHECKPOINT_DIR", "QUALITY_FLAGS_EXCLUDED", "Settings", "get_settings",
    "SourceRecord", "ElasticNotConfigured", "require_elastic", "get_es", "to_doc", "BulkStats", "bulk_index",
    "chunked", "Checkpoint", "BlockedError", "PoliteFetcher", "now_utc", "add_load_args", "print_records", "run_load",
]
