"""Slop Index step 3: scans.parquet -> investigation/results/slop_index.json (the file the /slop-index page reads).

    backend/.venv/bin/python -m investigation.analyze

Definitions (one flagging rule everywhere, the same one the product uses for evidence badges):
  flagged   predicted_class in {ai, mixed} AND confidence_category == "high"   (GPTZero's <1% error band)
  human     predicted_class == human AND confidence_category == "high"          (comparison group for the tie-in test)
  share     flagged / scanned, per year, with a Wilson 95% interval
  placebo   years before ChatGPT existed (2018-2021, pooled): anything flagged there is a false positive, so that
            rate is this detector's empirical false-positive rate ON THIS GENRE. Read every later year against it.
  tie-in    are flagged write-ups closer to their nearest semantic neighbours (nn_sim = mean similarity to the top-5)?
            Mann-Whitney U (normal approx., tie + continuity corrected) and Cliff's delta, within each year, then pooled
            across years as a stratified test so that drift over time cannot produce the effect. Skipped without nn_sim.

Output shape (exactly what the frontend expects; extra keys are additive):
  {generated_at, sample_data, years: [{year, scanned, ai_high, mixed_high, share, ci_low, ci_high,
    by_subclass: {pure_ai, ai_paraphrased, polished, concatenated}}], placebo_fpr: {years, flagged, scanned, rate,
    ci_low, ci_high}, tie_in: {cliffs_delta, p_value, median_nn_sim_flagged, median_nn_sim_human, n_flagged, n_human} | null,
    winners: [...], method: {...}}   + tie_in_by_year: [...]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

from . import common
from .common import PLACEBO_YEARS, REPLAY_MODEL_VERSION, InvestigationError
from .stats import mann_whitney_u, stratified_mann_whitney, wilson_ci

SUBCLASSES = ("pure_ai", "ai_paraphrased", "polished", "concatenated")
MIN_GROUP = 5  # a within-year test needs at least this many write-ups in each group


def _r(x: float | None, digits: int = 4) -> float | None:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), digits)


def _share(k: int, n: int) -> dict[str, float | None]:
    if n == 0:
        return {"share": None, "ci_low": None, "ci_high": None}
    low, high = wilson_ci(k, n)
    return {"share": _r(k / n), "ci_low": _r(low), "ci_high": _r(high)}


def _median(values: list[float]) -> float | None:
    values = sorted(v for v in values if v is not None and not math.isnan(v))
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0


def _truthy(v: Any) -> bool:
    """bool() that treats None / NaN / pandas.NA as False."""
    if v is None:
        return False
    try:
        if v != v:  # NaN
            return False
        return bool(v)
    except (TypeError, ValueError):  # pandas.NA refuses bool()
        return False


def _records(frame: Any) -> list[dict[str, Any]]:
    """DataFrame (or list of dicts) -> plain dicts with normalised types; keeps the maths free of pandas quirks."""
    rows = frame if isinstance(frame, list) else frame.to_dict("records")
    out = []
    for r in rows:
        nn = r.get("nn_sim")
        try:
            nn = None if nn is None or (isinstance(nn, float) and math.isnan(nn)) else float(nn)
        except (TypeError, ValueError):
            nn = None
        sub = r.get("subclass")
        out.append({
            "year": int(r["year"]), "predicted_class": str(r["predicted_class"]).lower(),
            "confidence_category": str(r["confidence_category"]).lower(),
            "subclass": sub if isinstance(sub, str) and sub else None,
            "is_winner": _truthy(r.get("is_winner")),
            "model_version": r.get("model_version"), "nn_sim": nn,
        })
    return out


def is_flagged(r: dict[str, Any]) -> bool:
    return r["predicted_class"] in ("ai", "mixed") and r["confidence_category"] == "high"


def is_confident_human(r: dict[str, Any]) -> bool:
    return r["predicted_class"] == "human" and r["confidence_category"] == "high"


def year_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table = []
    for year in sorted({r["year"] for r in rows}):
        yr = [r for r in rows if r["year"] == year]
        flagged = [r for r in yr if is_flagged(r)]
        ai_high = sum(1 for r in flagged if r["predicted_class"] == "ai")
        mixed_high = len(flagged) - ai_high
        table.append({"year": year, "scanned": len(yr), "ai_high": ai_high, "mixed_high": mixed_high,
                      **_share(len(flagged), len(yr)),
                      "by_subclass": {s: sum(1 for r in flagged if r["subclass"] == s) for s in SUBCLASSES}})
    return table


def placebo_fpr(rows: list[dict[str, Any]], placebo_years: tuple[int, ...] = PLACEBO_YEARS) -> dict[str, Any]:
    pool = [r for r in rows if r["year"] in placebo_years]
    flagged = sum(1 for r in pool if is_flagged(r))
    rate = _share(flagged, len(pool))
    return {"years": sorted({r["year"] for r in pool}), "flagged": flagged, "scanned": len(pool),
            "rate": rate["share"], "ci_low": rate["ci_low"], "ci_high": rate["ci_high"]}


def winner_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Share of winners inside each group: does an AI-flagged write-up win less (or more) often?"""
    groups = {"human": [r for r in rows if r["predicted_class"] == "human"],
              "ai": [r for r in rows if r["predicted_class"] == "ai"],
              "mixed": [r for r in rows if r["predicted_class"] == "mixed"],
              "flagged_high": [r for r in rows if is_flagged(r)],
              "not_flagged": [r for r in rows if not is_flagged(r)]}
    out = []
    for name, grp in groups.items():
        wins = sum(1 for r in grp if r["is_winner"])
        s = _share(wins, len(grp))
        out.append({"group": name, "scanned": len(grp), "winners": wins, "winner_share": s["share"],
                    "ci_low": s["ci_low"], "ci_high": s["ci_high"]})
    return out


def tie_in(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    have = [r for r in rows if r["nn_sim"] is not None]
    flagged = [r for r in have if is_flagged(r)]
    human = [r for r in have if is_confident_human(r)]
    if not flagged or not human:
        return None, []
    by_year: list[dict[str, Any]] = []
    strata = []
    for year in sorted({r["year"] for r in have}):
        f = [r["nn_sim"] for r in flagged if r["year"] == year]
        h = [r["nn_sim"] for r in human if r["year"] == year]
        if not f or not h:
            continue
        strata.append((f, h))
        if len(f) >= MIN_GROUP and len(h) >= MIN_GROUP:
            mw = mann_whitney_u(f, h)
            by_year.append({"year": year, "cliffs_delta": _r(mw.cliffs_delta), "p_value": _r(mw.p_value, 6),
                            "median_nn_sim_flagged": _r(_median(f)), "median_nn_sim_human": _r(_median(h)),
                            "n_flagged": len(f), "n_human": len(h)})
    pooled = stratified_mann_whitney(strata)
    if pooled is None:
        return None, by_year
    used_f = [v for f, _ in strata for v in f]
    used_h = [v for _, h in strata for v in h]
    return ({"cliffs_delta": _r(pooled.cliffs_delta), "p_value": _r(pooled.p_value, 6),
             "median_nn_sim_flagged": _r(_median(used_f)), "median_nn_sim_human": _r(_median(used_h)),
             "n_flagged": len(used_f), "n_human": len(used_h)}, by_year)


def build_slop_index(frame: Any, *, sample_summary: dict[str, Any] | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    rows = _records(frame)
    if not rows:
        raise InvestigationError("no scans to analyse")
    synthetic = sum(1 for r in rows if r["model_version"] == REPLAY_MODEL_VERSION)
    pooled, per_year = tie_in(rows)
    versions = sorted({str(r["model_version"]) for r in rows if r["model_version"]})
    return {
        "generated_at": (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds"),
        "sample_data": synthetic > 0,  # true = replay fixtures in the data: NOT findings
        "years": year_table(rows),
        "placebo_fpr": placebo_fpr(rows),
        "tie_in": pooled,
        "tie_in_by_year": per_year,
        "winners": winner_table(rows),
        "method": {
            "corpus": "Devpost hackathon write-ups: alvanlii/devpost-hackathon-projects (2018-2024, year = end of the "
                      "hackathon's submission period) and twangodev/devpost-hacks (2025-2026).",
            "sampling": "Year-stratified; English write-ups of >= 600 characters; each truncated to 1,800 characters at a "
                        "sentence boundary so the detector sees comparable lengths every year; fixed seed.",
            "detector": "GPTZero /v2/predict/text. We read predicted_class, confidence_category and subclass only.",
            "model_versions": versions,
            "flag_rule": "predicted_class in {ai, mixed} AND confidence_category == 'high'",
            "interval": "Wilson score, 95%",
            "placebo": "Years before ChatGPT (2018-2021) pooled: their flag rate is the detector's empirical false-positive "
                       "rate on this genre. Shares in later years should be read against it, not against zero.",
            "tie_in_test": "nn_sim = mean similarity to the 5 nearest semantic neighbours. Flagged vs confidently-human "
                           "write-ups: Mann-Whitney U (normal approximation, tie and continuity corrected), two-sided, and "
                           f"Cliff's delta. Reported within year (>= {MIN_GROUP} per group) and pooled as a year-stratified test.",
            "caveats": [
                ("A detector flag is not proof of AI authorship; at 'high' confidence GPTZero reports <1% error on "
                 "its own benchmarks, and the placebo rate shows what that means here."),
                "Writing style and Devpost's template prompts drifted over these years independently of AI.",
                "AI-written does not mean unoriginal. The tie-in test measures an association, not a cause.",
                "Aggregates only: no project, team or student is identified.",
            ],
            "n_scanned": len(rows), "n_synthetic": synthetic,
            "sample": sample_summary,
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scans", default=str(common.SCANS_PATH))
    ap.add_argument("--neighbours", default=str(common.NEIGHBOURS_PATH), help="optional parquet with sample_id, nn_sim")
    ap.add_argument("--out", default=str(common.SLOP_INDEX_PATH))
    args = ap.parse_args(argv)

    pd = common.require_pandas()
    scans_path = Path(args.scans)
    if not scans_path.exists():
        raise InvestigationError(f"{scans_path} not found. Run: backend/.venv/bin/python -m investigation.scan --pilot")
    frame = pd.read_parquet(scans_path)
    nb = Path(args.neighbours)
    if "nn_sim" not in frame.columns and nb.exists():
        frame = frame.merge(pd.read_parquet(nb)[["sample_id", "nn_sim"]].drop_duplicates("sample_id"), on="sample_id", how="left")
    if "nn_sim" not in frame.columns:
        print("note: no nn_sim column (run investigation/neighbours.py): the tie-in test is skipped, tie_in = null")

    summary_path = scans_path.parent / "sample_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else None
    result = build_slop_index(frame, sample_summary=summary)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")

    if result["sample_data"]:
        print("WARNING: synthetic replay-fixture scans are present -> sample_data: true. These are NOT findings.")
    print(f"{'year':>6} {'scanned':>8} {'flagged':>8} {'share':>8}   95% CI")
    for y in result["years"]:
        print(f"{y['year']:>6} {y['scanned']:>8} {y['ai_high'] + y['mixed_high']:>8} {y['share']:>8.1%}   "
              f"[{y['ci_low']:.1%}, {y['ci_high']:.1%}]   {y['by_subclass']}")
    p = result["placebo_fpr"]
    if p["scanned"]:
        print(f"placebo FPR {p['years']}: {p['flagged']}/{p['scanned']} = {p['rate']:.1%}  [{p['ci_low']:.1%}, {p['ci_high']:.1%}]")
    t = result["tie_in"]
    if t:
        print(f"tie-in (year-stratified): Cliff's delta {t['cliffs_delta']:+.3f}, p = {t['p_value']:.4g}, "
              f"n = {t['n_flagged']} flagged vs {t['n_human']} human")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
