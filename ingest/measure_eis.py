"""Measure Elastic Inference Service ingest throughput BEFORE sizing Tier 1 (EIS rate limits are undocumented).

Indexes ~1,000 documents WITH semantic_pitch into a throw-away scratch index under
chunk_size in {25, 50, 100} x threads in {1, 4, 8}, and reports docs/s and the number of 429s per combination.
It deletes the scratch index it created - and nothing else - even when interrupted.

    backend/.venv/bin/python -m ingest.measure_eis                       # 1,000 docs split over the 9 combinations
    backend/.venv/bin/python -m ingest.measure_eis --docs 450 --chunk-sizes 25 50 --threads 1 4
    backend/.venv/bin/python -m ingest.measure_eis --source twangodev    # use the local twangodev parquet instead of YC

Also note the billing delta in the Elastic Cloud console before/after: tokens, not requests, are billed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from typing import Any

from ingest.common import DATA_DIR, REPO_ROOT, bulk_index, get_es, now_utc, require_elastic, to_doc

SCRATCH_PREFIX = "prior-art-eis-scratch-"


def _load_apply():
    spec = importlib.util.spec_from_file_location("elastic_apply", REPO_ROOT / "elastic" / "apply.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["elastic_apply"] = mod
    spec.loader.exec_module(mod)
    return mod


def sample_docs(source: str, n: int) -> list[dict[str, Any]]:
    """Representative documents: real pitches of >= 250 chars (short ones would flatter the numbers)."""
    if source == "twangodev":
        from ingest.load_devpost_recent import iter_records, read_rows

        records = iter_records(read_rows())
    else:
        from ingest.load_yc import fetch_companies, iter_records

        records = iter_records(fetch_companies())
    docs = []
    for rec in records:
        if len(rec.pitch) >= 250:
            docs.append(to_doc(rec, semantic=True, with_sections=False))
            if len(docs) >= n:
                break
    return docs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", type=int, default=1000, help="total documents, split evenly over the combinations")
    ap.add_argument("--chunk-sizes", type=int, nargs="+", default=[25, 50, 100])
    ap.add_argument("--threads", type=int, nargs="+", default=[1, 4, 8])
    ap.add_argument("--source", choices=("yc", "twangodev"), default="yc")
    ap.add_argument("--pause", type=float, default=5.0, help="seconds between combinations (lets rate-limit windows reset)")
    ap.add_argument("--tier1", type=int, default=40000, help="Tier-1 size used for the time estimate")
    args = ap.parse_args(argv)

    settings = require_elastic()
    es = get_es()
    apply = _load_apply()
    mapping = apply.render_json(REPO_ROOT / "elastic" / "mappings" / "prior-art-v1.json", apply.template_vars(settings))
    try:
        es.ingest.get_pipeline(id=apply.PIPELINE_NAME)
    except Exception:
        print(f"pipeline {apply.PIPELINE_NAME} is not applied yet: measuring without it (run elastic/apply.py first for the real path)")
        mapping["settings"]["index"].pop("default_pipeline", None)

    combos = [(c, t) for c in args.chunk_sizes for t in args.threads]
    per = max(10, args.docs // len(combos))
    docs = sample_docs(args.source, per * len(combos))
    if len(docs) < per * len(combos):
        per = len(docs) // len(combos)
    print(f"{len(docs)} sample docs from {args.source}; {per} per combination; {len(combos)} combinations")

    scratch = f"{SCRATCH_PREFIX}{int(time.time())}"
    created = False
    results: list[dict[str, Any]] = []
    try:
        es.indices.create(index=scratch, body=mapping)
        created = True
        print(f"created scratch index {scratch} (embed endpoint: {settings.es_embed_inference_id})")
        for n, (chunk_size, threads) in enumerate(combos):
            batch = []
            for doc in docs[n * per:(n + 1) * per]:
                d = dict(doc)
                d["rid"] = f"{doc['rid']}#c{chunk_size}t{threads}"  # unique ids: every combination does real inference
                batch.append(d)
            stats = bulk_index(batch, index=scratch, semantic=True, chunk_size=chunk_size, threads=threads, es=es,
                               max_retries=4, batch_size=len(batch) or 1)
            row = {"chunk_size": chunk_size, "threads": threads, "docs": len(batch), **stats.as_dict()}
            results.append(row)
            print(f"  chunk_size={chunk_size:<4} threads={threads:<2} -> {stats.summary()}", flush=True)
            if n < len(combos) - 1:
                time.sleep(args.pause)
    finally:
        if created and scratch.startswith(SCRATCH_PREFIX):
            try:
                es.indices.delete(index=scratch)
                print(f"deleted scratch index {scratch}")
            except Exception as exc:
                print(f"!! could not delete {scratch}: {exc} — delete it manually")

    print("\nchunk  threads  docs   ok    docs/s   429s  failed  retried")
    for r in results:
        print(f"{r['chunk_size']:<6} {r['threads']:<8} {r['docs']:<6} {r['ok']:<5} {r['docs_per_s']:<8} {r['http_429']:<5} {r['failed']:<7} {r['retried']}")
    good = [r for r in results if r["ok"] and not r["failed"]]
    if good:
        best = max(good, key=lambda r: (r["docs_per_s"], -r["http_429"]))
        hours = args.tier1 / best["docs_per_s"] / 3600 if best["docs_per_s"] else float("inf")
        fit = int(best["docs_per_s"] * 3 * 3600)
        print(f"\nbest: --chunk-size {best['chunk_size']} --threads {best['threads']}  ({best['docs_per_s']} docs/s, {best['http_429']} 429s)")
        print(f"Tier 1 at {args.tier1} docs would take ~{hours:.1f} h; a 3 h budget fits --limit {fit}"
              + ("  (design cut line: < 20 docs/s -> cap Tier 1 at 25k)" if best["docs_per_s"] < 20 else ""))
    out = DATA_DIR / f"measure_eis_{now_utc().strftime('%Y%m%dT%H%M%S')}.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"embed_inference_id": settings.es_embed_inference_id, "source": args.source, "results": results}, indent=1))
        print(f"wrote {out}")
    except OSError as exc:
        print(f"(could not write {out}: {exc})")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
