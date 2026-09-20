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
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

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


def load_cdf(path: Path | None = None, placeholder: Callable[[], CrowdingCDF] = placeholder_cdf) -> CrowdingCDF:
    path = path or CALIBRATION_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            meta = {k: v for k, v in data.items() if k not in ("values", "is_placeholder", "version", "n")}
            return CrowdingCDF(data["values"], is_placeholder=bool(data.get("is_placeholder", False)), meta=meta)
        except Exception as exc:  # a corrupt file must not take scoring down
            print(f"[calibration] could not read {path}: {exc}; using the placeholder CDF", file=sys.stderr)
    return placeholder()


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
# Reference distributions for the two token-level instruments (signals/surprisal.py)
# --------------------------------------------------------------------------------------
RCS_FILE = CALIBRATION_DIR / "rcs_cdf.json"
CURVATURE_FILE = CALIBRATION_DIR / "curvature_cdf.json"


def placeholder_rcs_cdf(n: int = 300) -> CrowdingCDF:
    """Stand-in for the retrieval-conditioned-surprisal reference: nats/token over roughly [0, 1.6], most of
    the mass low (for a random project the neighbourhood helps a little; for a clone it helps a lot)."""
    values = [round(1.6 * ((i + 0.5) / n) ** 2.0, 6) for i in range(n)]
    return CrowdingCDF(values, is_placeholder=True, meta={"note": PLACEHOLDER_NOTE, "unit": "nats/token"})


def placeholder_curvature_cdf(n: int = 300) -> CrowdingCDF:
    """Stand-in for the Fast-DetectGPT reference on KNOWN-HUMAN text: roughly standard-normal."""
    values = [round(math.sqrt(2) * math.erf((2 * (i + 0.5) / n) - 1) * 1.2, 6) for i in range(n)]
    return CrowdingCDF(values, is_placeholder=True, meta={"note": PLACEHOLDER_NOTE, "reference": "human pitches"})


_rcs_cdf: CrowdingCDF | None = None
_curvature_cdf: CrowdingCDF | None = None


def get_rcs_cdf(*, reload: bool = False) -> CrowdingCDF:
    global _rcs_cdf
    if _rcs_cdf is None or reload:
        _rcs_cdf = load_cdf(RCS_FILE, placeholder_rcs_cdf)
    return _rcs_cdf


def get_curvature_cdf(*, reload: bool = False) -> CrowdingCDF:
    global _curvature_cdf
    if _curvature_cdf is None or reload:
        _curvature_cdf = load_cdf(CURVATURE_FILE, placeholder_curvature_cdf)
    return _curvature_cdf


def rcs_percentile(value: float) -> float:
    """Where this idea's RCS sits among the calibration projects. 1.0 = the prior art explains it more than
    it explains any of them."""
    return get_rcs_cdf().percentile(value)


def curvature_percentile(value: float) -> float:
    """Where this pitch's curvature sits among KNOWN-HUMAN pitches, so the operating point is explicit: at the
    0.95 mark the false-positive rate on human hackathon writing is 5% by construction, not by a vendor's
    threshold."""
    return get_curvature_cdf().percentile(value)


def rcs_is_placeholder() -> bool:
    return get_rcs_cdf().is_placeholder


def curvature_is_placeholder() -> bool:
    return get_curvature_cdf().is_placeholder


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


async def build_rcs_calibration(n: int = 300, *, seed: int = 42, neighbours: int = 10, concurrency: int = 4,
                                save: bool = True, path: Path | None = None) -> CrowdingCDF:
    """Same design as the crowding CDF, measured with the other instrument: take N random corpus documents,
    retrieve each one's neighbours (self excluded), and record how many nats/token those neighbours save."""
    from app.search.es import get_async_es, require_elastic
    from app.search.hybrid import search
    from app.signals import surprisal

    if not surprisal.available():
        raise RuntimeError("SURPRISAL_BASE_URL is not set: deploy the base model before calibrating RCS")
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
                result = await surprisal.measure_rcs(pitch, [r.pitch for r in recs if r.pitch])
            except Exception:
                result = None
        if result is None:
            skipped += 1
            return
        values.append(result.nats_per_token)

    await asyncio.gather(*(one(d) for d in docs))
    if len(values) < max(20, n // 10):
        raise RuntimeError(f"only {len(values)} of {len(docs)} RCS calibration reads succeeded ({skipped} skipped); "
                           "is the surprisal deployment healthy? Not overwriting the existing CDF.")
    cdf = CrowdingCDF(values, is_placeholder=False, meta={
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(), "index": settings.es_index, "seed": seed,
        "neighbours": neighbours, "skipped": skipped, "unit": "nats/token",
        "model": get_settings().surprisal_model,
        "formula": "mean_t [ log p(x_t | x_<t, neighbours) - log p(x_t | x_<t) ]; self excluded",
    })
    if save:
        target = path or RCS_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(cdf.to_json(), indent=1))
        get_rcs_cdf(reload=True)
    return cdf


async def build_curvature_calibration(n: int = 300, *, seed: int = 42, before_year: int = 2022, concurrency: int = 4,
                                      save: bool = True, path: Path | None = None) -> CrowdingCDF:
    """The Fast-DetectGPT reference, built from write-ups finished BEFORE ChatGPT launched (2022-11-30).

    Those are the placebo years investigation/README.md already argues are human, so the resulting quantile is
    an explicit false-positive rate on this genre rather than a borrowed threshold. A flag above the 95th
    percentile of this set means "more machine-like than 95% of pre-ChatGPT hackathon writing"."""
    from app.search.es import get_async_es, require_elastic
    from app.signals import surprisal

    if not surprisal.available():
        raise RuntimeError("SURPRISAL_BASE_URL is not set: deploy the base model before calibrating curvature")
    settings = require_elastic()
    body = build_sample_body(n, seed)
    body["query"]["function_score"]["query"]["bool"]["filter"].append({"range": {"year": {"lt": before_year}}})
    resp = await get_async_es().search(index=settings.es_index, body=body)
    docs = (resp.get("hits") or {}).get("hits", [])
    if not docs:
        raise RuntimeError(f"no pre-{before_year} documents in {settings.es_index}: the human reference needs them")
    sem = asyncio.Semaphore(concurrency)
    values: list[float] = []
    skipped = 0

    async def one(doc: dict[str, Any]) -> None:
        nonlocal skipped
        pitch = (doc.get("_source") or {}).get("pitch") or ""
        async with sem:
            try:
                result = await surprisal.measure_curvature(pitch)
            except Exception:
                result = None
        if result is None:
            skipped += 1
            return
        values.append(result.d)

    await asyncio.gather(*(one(d) for d in docs))
    if len(values) < max(20, n // 10):
        raise RuntimeError(f"only {len(values)} of {len(docs)} curvature reads succeeded ({skipped} skipped); "
                           "not overwriting the existing CDF.")
    cdf = CrowdingCDF(values, is_placeholder=False, meta={
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(), "index": settings.es_index, "seed": seed,
        "reference": f"human: pitches from before {before_year}", "skipped": skipped,
        "model": get_settings().surprisal_model,
        "formula": "d = (sum log p(x_t) - sum mu_t) / sqrt(sum sigma_t^2), top-k renormalised",
    })
    if save:
        target = path or CURVATURE_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(cdf.to_json(), indent=1))
        get_curvature_cdf(reload=True)
    return cdf


def _cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Calibration CDFs: crowding, RCS, Fast-DetectGPT curvature")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, help_text in (("build", "crowding: sample N docs, query each, store the sorted crowding_lite values"),
                            ("build-rcs", "RCS: same sample, store the sorted nats/token the neighbours save"),
                            ("build-curvature", "Voice: store the curvature of N pre-ChatGPT (human) pitches")):
        b = sub.add_parser(name, help=help_text)
        b.add_argument("--n", type=int, default=300)
        b.add_argument("--seed", type=int, default=42)
        b.add_argument("--concurrency", type=int, default=4)
        if name == "build-curvature":
            b.add_argument("--before-year", type=int, default=2022, help="ChatGPT launched 2022-11-30")
    sub.add_parser("show", help="print every CDF in use (placeholder or measured)")
    args = ap.parse_args(argv)
    targets = {"build": CALIBRATION_FILE, "build-rcs": RCS_FILE, "build-curvature": CURVATURE_FILE}
    if args.cmd == "show":
        for label, cdf, file in (("crowding", get_cdf(reload=True), CALIBRATION_FILE),
                                 ("rcs", get_rcs_cdf(reload=True), RCS_FILE),
                                 ("curvature", get_curvature_cdf(reload=True), CURVATURE_FILE)):
            qs = {q: cdf.values[min(len(cdf.values) - 1, int(q / 100 * len(cdf.values)))] for q in (5, 25, 50, 75, 95)}
            print(json.dumps({"cdf": label, "file": str(file), "is_placeholder": cdf.is_placeholder,
                              "n": len(cdf.values), "quantiles": qs, **cdf.meta}, indent=1))
        return 0

    async def run() -> CrowdingCDF:
        from app.search.es import close_async_es

        try:
            if args.cmd == "build-rcs":
                return await build_rcs_calibration(args.n, seed=args.seed, concurrency=args.concurrency)
            if args.cmd == "build-curvature":
                return await build_curvature_calibration(args.n, seed=args.seed, concurrency=args.concurrency,
                                                         before_year=args.before_year)
            return await build_calibration(args.n, seed=args.seed, concurrency=args.concurrency)
        finally:
            await close_async_es()

    try:
        cdf = asyncio.run(run())
    except Exception as exc:
        print(f"calibration failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    target = targets[args.cmd]
    print(f"saved {len(cdf.values)} values to {target} (min={cdf.values[0]:.4f} median={cdf.values[len(cdf.values) // 2]:.4f} max={cdf.values[-1]:.4f})")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
