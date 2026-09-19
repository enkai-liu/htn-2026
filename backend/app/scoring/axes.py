"""Scoring. Pure functions, documented in docs/scoring.md. Higher = more original. Any axis may abstain (score=None).

Voice (GPTZero) is deliberately NOT here: AI-probability is not unoriginality, so it is its own channel.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Callable

from app.schemas import Abstain, AxisScore, Scores

WEIGHTS = {"crowding": 0.45, "facet_rarity": 0.35, "llm_predictability": 0.20}
COLLISION = 0.80  # cosine above which an LLM-proposed idea counts as "the same idea"


def _fallback_percentile(x: float) -> float:
    """Used only until search/calibration.py has a real CDF: a logistic centred on 0.5."""
    return 1 / (1 + math.exp(-8 * (x - 0.5)))


def corpus_percentile() -> Callable[[float], float] | None:
    """The calibration CDF built from the indexed corpus, or None until `app.search.calibration build` has been run.
    Every crowding score in a run (the idea AND its mutations) must go through the same function."""
    try:
        from app.search import calibration

        return None if calibration.is_placeholder() else calibration.percentile
    except Exception:
        return None


def crowding_lite(sims: list[float]) -> float:
    top = sorted(sims, reverse=True)[:5]
    return 0.6 * top[0] + 0.4 * statistics.fmean(top) if top else 0.0


def crowding(sims: list[float], percentile: Callable[[float], float] | None = None, *, calibrated: bool = True,
             names: list[str] | None = None) -> AxisScore:
    if not sims:
        return AxisScore(score=None, note="No prior art was retrieved, so crowding cannot be measured.")
    lite = crowding_lite(sims)
    pct = (percentile or _fallback_percentile)(lite)
    note = "" if (calibrated and percentile) else "Uncalibrated: similarity scale has not been calibrated against the corpus yet."
    return AxisScore(score=round(100 * (1 - pct), 1), note=note,
                     detail={"crowding_lite": round(lite, 3), "percentile": round(pct, 3), "top": (names or [])[:3], "calibrated": bool(calibrated and percentile)})


def rarity_from_df(df: int, cap: int = 2000) -> float:
    return max(0.0, 1 - math.log1p(df) / math.log1p(cap))


def facet_rarity(facet_dfs: dict[str, int] | None, pair_df: int | None, cliche_overlap: float | None) -> AxisScore:
    if not facet_dfs:
        return AxisScore(score=None, note="Needs the indexed corpus (Elasticsearch) to count how common each facet is.")
    rar = {k: round(rarity_from_df(v), 3) for k, v in facet_dfs.items()}
    pair = rarity_from_df(pair_df, cap=200) if pair_df is not None else statistics.fmean(rar.values())
    cliche = cliche_overlap if cliche_overlap is not None else 0.0
    score = 100 * (0.5 * statistics.fmean(rar.values()) + 0.3 * pair + 0.2 * (1 - cliche))
    rarest = max(rar, key=rar.get)
    return AxisScore(score=round(score, 1), note=f"Rarest facet: {rarest}.",
                     detail={"rarity": rar, "df": facet_dfs, "pair_purpose_mechanism": round(pair, 3), "pair_df": pair_df, "cliche_overlap": round(cliche, 3)})


def llm_predictability(priors: list[dict], percentile: Callable[[float], float] | None = None) -> AxisScore:
    if not priors:
        return AxisScore(score=None, note="No model samples were collected.")
    sims = [float(p["similarity"]) for p in priors]
    mx = max(sims)
    hit_rate = sum(s > COLLISION for s in sims) / len(sims)
    calibrated = not any(p.get("uncalibrated") for p in priors)
    pct = (percentile or (lambda v: min(max((v - 0.3) / 0.6, 0.0), 1.0)))(mx)
    score = 100 * (1 - 0.6 * pct - 0.4 * hit_rate)
    return AxisScore(score=round(max(score, 0.0), 1), note="" if calibrated else "Uncalibrated: lexical similarity was used (no embedding service).",
                     detail={"max_similarity": round(mx, 3), "hit_rate": round(hit_rate, 3), "n_samples": len(sims),
                             "models": sorted({p["model"] for p in priors}), "calibrated": calibrated})


def headline(axes: dict[str, AxisScore], jury_std: float) -> tuple[float | None, float | None]:
    """Weighted geometric mean over the axes that did not abstain (weights renormalised)."""
    live = {k: a.score for k, a in axes.items() if a.score is not None}
    if "crowding" not in live:
        return None, None
    total = sum(WEIGHTS[k] for k in live)
    log_sum = sum(WEIGHTS[k] / total * math.log(max(v, 1.0) / 100) for k, v in live.items())
    band = min(30.0, 8 + 40 * jury_std + 6 * (len(WEIGHTS) - len(live)))
    return round(100 * math.exp(log_sum), 1), round(band, 1)


def confidence(*, coverage: float, jury_std: float, verified_share: float, canary_pass: float) -> float:
    jury_norm = min(jury_std / 0.35, 1.0)
    return round(0.35 * coverage + 0.25 * (1 - jury_norm) + 0.25 * verified_share + 0.15 * canary_pass, 3)


def decide_abstain(*, coverage: float, corpus_ok: bool, conf: float, missing: list[str]) -> Abstain:
    if not corpus_ok or coverage < 0.5:
        return Abstain(active=True, reason="Insufficient evidence: " + (", ".join(missing) or "too few sources answered") + ".")
    if conf < 0.45:
        return Abstain(active=True, reason=f"Low confidence ({conf:.2f}): the evidence is thin or the jury disagreed. Axes are shown; the headline is withheld.")
    return Abstain(active=False)


def assemble(crowd: AxisScore, rarity: AxisScore, pred: AxisScore, *, jury_std: float, conf: float, abstain: Abstain) -> Scores:
    h, band = headline({"crowding": crowd, "facet_rarity": rarity, "llm_predictability": pred}, jury_std)
    if abstain.active:
        h, band = None, None
    return Scores(crowding=crowd, facet_rarity=rarity, llm_predictability=pred, headline=h, band=band, confidence=conf, abstain=abstain)
