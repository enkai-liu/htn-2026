"""Crowding calibration (AXIS 1): turn a raw reranker-based crowding value into a percentile.

    r_i           = reranker score of neighbour i against the full idea (top 10)
    crowding_lite = 0.6 * max(r) + 0.4 * mean(top-5 r)
    pct           = share of the 300 calibration documents whose own crowding_lite is <= this value
    O1            = 100 * (1 - pct)                                  (assembled in scoring/axes.py)

Calibration = take 300 random corpus documents, use each one's pitch as the query (self excluded), compute
its crowding_lite, keep the sorted array. It depends on the reranker model AND the corpus, so rebuild it
after Tier 1 and whenever ES_RERANK_INFERENCE_ID changes:

    cd backend && .venv/bin/python -m app.search.calibration build --n 300
    cd backend && .venv/bin/python -m app.search.calibration show

Until that has run, a clearly-labelled PLACEHOLDER CDF keeps scoring alive (`is_placeholder()` is True and
the UI/confidence should say "uncalibrated").
"""
from __future__ import annotations

import argparse
import asyncio
import bisect
import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from app.config import FIXTURES_DIR, get_settings

CALIBRATION_DIR = FIXTURES_DIR / "calibration"
CALIBRATION_FILE = CALIBRATION_DIR / "crowding_cdf.json"
PLACEHOLDER_NOTE = (
    "PLACEHOLDER - synthetic values, NOT measured. Run `python -m app.search.calibration build` once the "
    "corpus is ingested; percentiles from this CDF are only good enough to keep the pipeline running."
)


def crowding_lite(scores: Sequence[float | None]) -> float:
    """0.6 * max(r) + 0.4 * mean(top-5 r); 0.0 for an empty neighbourhood (nothing similar exists)."""
    rs = sorted((float(s) for s in scores if s is not None), reverse=True)
    if not rs:
        return 0.0
    top5 = rs[:5]
    return 0.6 * rs[0] + 0.4 * (sum(top5) / len(top5))


@dataclass
class CrowdingCDF:
    values: list[float]  # sorted ascending
    is_placeholder: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.values = sorted(float(v) for v in self.values)
        if not self.values:
            raise ValueError("a calibration CDF needs at least one value")

    def percentile(self, value: float) -> float:
        """Mid-rank empirical CDF in [0, 1]: 0 = less crowded than everything we calibrated on."""
        lo = bisect.bisect_left(self.values, value)
        hi = bisect.bisect_right(self.values, value)
        return (lo + hi) / (2 * len(self.values))

    def to_json(self) -> dict[str, Any]:
        return {"version": 1, "is_placeholder": self.is_placeholder, **self.meta, "n": len(self.values), "values": self.values}


def placeholder_cdf(n: int = 300) -> CrowdingCDF:
    """Deterministic synthetic stand-in: a smooth, right-skewed spread over the [0.05, 0.95] score range
    (most random projects have moderately similar neighbours, few have near-duplicates)."""
    values = [round(0.05 + 0.90 * ((i + 0.5) / n) ** 1.6, 6) for i in range(n)]
    return CrowdingCDF(values, is_placeholder=True, meta={"note": PLACEHOLDER_NOTE})


def load_cdf(path: Path | None = None) -> CrowdingCDF:
    path = path or CALIBRATION_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text())
            meta = {k: v for k, v in data.items() if k not in ("values", "is_placeholder", "version", "n")}
            return CrowdingCDF(data["values"], is_placeholder=bool(data.get("is_placeholder", False)), meta=meta)
        except Exception as exc:  # a corrupt file must not take scoring down
            print(f"[calibration] could not read {path}: {exc}; using the placeholder CDF", file=sys.stderr)
    return placeholder_cdf()


_cdf: CrowdingCDF | None = None


def get_cdf(*, reload: bool = False) -> CrowdingCDF:
    global _cdf
    if _cdf is None or reload:
        _cdf = load_cdf()
    return _cdf


def percentile(value: float) -> float:
    """Percentile of a crowding_lite value against the calibration set (placeholder until calibrated)."""
    return get_cdf().percentile(value)


def is_placeholder() -> bool:
    return get_cdf().is_placeholder


# --------------------------------------------------------------------------------------
# Building (needs Elastic + the reranker)
# --------------------------------------------------------------------------------------
def build_sample_body(n: int, seed: int) -> dict[str, Any]:
    from app.search.es import excluded_flags_clause

    return {
        "size": n,
        "_source": ["rid", "pitch"],
        "query": {
            "function_score": {
                "query": {"bool": {"filter": [{"term": {"has_semantic": True}}], "must_not": [excluded_flags_clause()]}},
                "random_score": {"seed": seed, "field": "_seq_no"},
                "boost_mode": "replace",
            }
        },
    }


async def build_calibration(n: int = 300, *, seed: int = 42, neighbours: int = 10, concurrency: int = 4,
                            save: bool = True, path: Path | None = None) -> CrowdingCDF:
    from app.search.es import get_async_es, require_elastic
    from app.search.hybrid import search

    settings = require_elastic()
    es = get_async_es()
    resp = await es.search(index=settings.es_index, body=build_sample_body(n, seed))
    docs = (resp.get("hits") or {}).get("hits", [])
    if not docs:
        raise RuntimeError(f"no documents with has_semantic=true in {settings.es_index}; ingest Tier 0/1 first")
    sem = asyncio.Semaphore(concurrency)
    values: list[float] = []
    skipped = 0

    async def one(doc: dict[str, Any]) -> None:
        nonlocal skipped
        pitch = (doc.get("_source") or {}).get("pitch") or ""
        async with sem:
            try:
                recs = await search(pitch[:1500], pitch, size=neighbours, exclude_ids=[doc["_id"]])
            except Exception:
                skipped += 1
                return
        # A degraded (RRF-only) answer has scores on a different scale: never mix it into the CDF.
        if not recs or recs[0].retrieval.get("uncalibrated"):
            skipped += 1
            return
        values.append(crowding_lite([r.retrieval.get("rerank_score") for r in recs]))

    await asyncio.gather(*(one(d) for d in docs))
    if len(values) < max(20, n // 10):
        raise RuntimeError(f"only {len(values)} of {len(docs)} calibration queries were reranked ({skipped} skipped); "
                           "is the rerank inference endpoint healthy? Not overwriting the existing CDF.")
    cdf = CrowdingCDF(values, is_placeholder=False, meta={
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(), "index": settings.es_index, "seed": seed,
        "neighbours": neighbours, "skipped": skipped, "rerank_inference_id": settings.es_rerank_inference_id,
        "embed_inference_id": settings.es_embed_inference_id,
        "formula": "crowding_lite = 0.6*max(r) + 0.4*mean(top5 r); self excluded",
    })
    if save:
        target = path or CALIBRATION_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(cdf.to_json(), indent=1))
        get_cdf(reload=True)
    return cdf


def _cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Crowding calibration CDF")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="sample N docs, query each against the corpus, store the sorted crowding_lite values")
    b.add_argument("--n", type=int, default=300)
    b.add_argument("--seed", type=int, default=42)
    b.add_argument("--concurrency", type=int, default=4)
    sub.add_parser("show", help="print the CDF in use (placeholder or measured)")
    args = ap.parse_args(argv)
    if args.cmd == "show":
        cdf = get_cdf(reload=True)
        qs = {q: cdf.values[min(len(cdf.values) - 1, int(q / 100 * len(cdf.values)))] for q in (5, 25, 50, 75, 95)}
        print(json.dumps({"file": str(CALIBRATION_FILE), "is_placeholder": cdf.is_placeholder, "n": len(cdf.values),
                          "quantiles": qs, **cdf.meta}, indent=1))
        return 0

    async def run() -> CrowdingCDF:
        from app.search.es import close_async_es

        try:
            return await build_calibration(args.n, seed=args.seed, concurrency=args.concurrency)
        finally:
            await close_async_es()

    try:
        cdf = asyncio.run(run())
    except Exception as exc:
        print(f"calibration failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"saved {len(cdf.values)} values to {CALIBRATION_FILE} (min={cdf.values[0]:.4f} median={cdf.values[len(cdf.values) // 2]:.4f} max={cdf.values[-1]:.4f})")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
