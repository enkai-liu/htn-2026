"""Scoring. Pure functions, documented in docs/scoring.md. Higher = more original. Any axis may abstain (score=None).

Voice (GPTZero) is deliberately NOT here: AI-probability is not unoriginality, so it is its own channel.
"""
from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.schemas import Abstain, AxisScore, Scores
from app.scoring import stats
from app.search.rarity import facet_rarity_from_idf as rarity_from_idf
from app.search.rarity import npmi as npmi_value
from app.search.rarity import pair_atypicality as _pair_atypicality

WEIGHTS = {"crowding": 0.45, "facet_rarity": 0.35, "llm_predictability": 0.20}
COLLISION = 0.80  # cosine above which an LLM-proposed idea counts as "the same idea"

# Axes the RANK is taken over. A percentile rank is only meaningful against a reference population scored
# the SAME way, and llm_predictability costs 12 model calls per document -- 3,600 for a 300-document
# reference. Crowding and facet rarity are Elasticsearch plus one facet extraction, so those two carry the
# rank and llm_predictability is reported as its own axis, like Voice.
RANK_AXES = ("crowding", "facet_rarity")


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


def rcs_percentile() -> Callable[[float], float] | None:
    """The retrieval-conditioned-surprisal reference CDF, or None until `calibration build-rcs` has been run."""
    try:
        from app.search import calibration

        return None if calibration.rcs_is_placeholder() else calibration.rcs_percentile
    except Exception:
        return None


def crowding_lite(sims: list[float]) -> float:
    top = sorted(sims, reverse=True)[:5]
    return 0.6 * top[0] + 0.4 * statistics.fmean(top) if top else 0.0


def crowding(sims: list[float], percentile: Callable[[float], float] | None = None, *, calibrated: bool = True,
             names: list[str] | None = None, rcs: float | None = None,
             rcs_pct: Callable[[float], float] | None = None) -> AxisScore:
    """Two instruments, averaged on the percentile scale (the only scale they share).

        p_rerank = pct(0.6*max(r) + 0.4*mean(top5 r))          how close the nearest existing projects are
        p_rcs    = pct(nats/token the neighbours save)          how much of the pitch the prior art predicts
        O1       = 100 * (1 - mean of whichever are available)

    They fail independently: the reranker measures distance between documents, RCS measures how much
    information the neighbourhood carries about this specific wording. With no surprisal deployment this is
    exactly the single-instrument score it has always been, and says so."""
    if not sims:
        return AxisScore(score=None, note="No prior art was retrieved, so crowding cannot be measured.")
    lite = crowding_lite(sims)
    pcts = {"rerank": (percentile or _fallback_percentile)(lite)}
    if rcs is not None:
        pcts["rcs"] = (rcs_pct or _fallback_percentile)(rcs)
    pct = statistics.fmean(pcts.values())
    notes = []
    if not (calibrated and percentile):
        notes.append("Uncalibrated: similarity scale has not been calibrated against the corpus yet.")
    if rcs is not None and rcs_pct is None:
        notes.append("Surprisal uncalibrated: run `calibration build-rcs`.")
    if rcs is None:
        notes.append("Single instrument (reranker only): no surprisal deployment.")
    detail = {"crowding_lite": round(lite, 3), "percentile": round(pct, 3), "top": (names or [])[:3],
              "calibrated": bool(calibrated and percentile), "instruments": sorted(pcts),
              "percentiles": {k: round(v, 3) for k, v in pcts.items()}}
    if rcs is not None:
        detail["rcs_nats_per_token"] = round(rcs, 4)
    return AxisScore(score=round(100 * (1 - pct), 1), note=" ".join(notes), detail=detail)


def rarity_from_df(df: int, cap: int = 2000) -> float:
    return max(0.0, 1 - math.log1p(df) / math.log1p(cap))


def facet_rarity(facet_dfs: dict[str, int] | None, pair_df: int | None, cliche_overlap: float | None,
                 *, pair_npmi: float | None = None, pair_expected: float | None = None,
                 facet_rarities: dict[str, float] | None = None,
                 facet_terms: dict[str, Any] | None = None) -> AxisScore:
    """Per-facet rarity from the term-frequency profile; the pair term from NPMI.

    `facet_rarities` (mean IDF of each facet's most distinctive terms) is length-invariant and is what the
    axis uses when it is available. `facet_dfs` + `rarity_from_df` is the old single-document-count path,
    kept as the fallback: it measured phrase length as much as rarity, scoring a 20-word mechanism 0.089
    because any 3 of its words matched 12.6% of the corpus.

    NPMI asks whether purpose and mechanism co-occur more or less than independence predicts, which is the
    question the axis is for: a common purpose combined with a common mechanism in a way nobody has tried is
    the interesting case, and a raw pair df scores it the same as two rare facets. See search/rarity.py."""
    if facet_rarities:
        rar = {k: round(v, 3) for k, v in facet_rarities.items()}
        measure = "idf"
    elif facet_dfs:
        rar = {k: round(rarity_from_df(v), 3) for k, v in facet_dfs.items()}
        measure = "df"
    else:
        return AxisScore(score=None, note="Needs the indexed corpus (Elasticsearch) to count how common each facet is.")
    if pair_npmi is not None:
        pair = (1.0 - max(-1.0, min(1.0, pair_npmi))) / 2.0
    elif pair_df is not None:
        pair = rarity_from_df(pair_df, cap=200)
    else:
        pair = statistics.fmean(rar.values())
    cliche = cliche_overlap if cliche_overlap is not None else 0.0
    score = 100 * (0.5 * statistics.fmean(rar.values()) + 0.3 * pair + 0.2 * (1 - cliche))
    rarest = max(rar, key=rar.get)
    note = f"Rarest facet: {rarest}."
    detail = {"rarity": rar, "df": facet_dfs, "pair_purpose_mechanism": round(pair, 3), "pair_df": pair_df,
              "cliche_overlap": round(cliche, 3), "pair_measure": "npmi" if pair_npmi is not None else "df",
              "facet_measure": measure}
    if facet_terms:
        detail["facet_terms"] = facet_terms
    if pair_npmi is not None:
        detail["pair_npmi"] = round(pair_npmi, 3)
        detail["pair_expected"] = pair_expected
        if pair_expected is not None and pair_df is not None:
            direction = "rarer" if pair_npmi < 0 else "more common"
            note += (f" Purpose+mechanism appear together in {pair_df} projects; independence predicts "
                     f"{pair_expected:g} ({direction} than chance, NPMI {pair_npmi:+.2f}).")
    return AxisScore(score=round(score, 1), note=note, detail=detail)


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


def combine(scores: dict[str, float]) -> float | None:
    """Weighted geometric mean over the axes that did not abstain (weights renormalised)."""
    if "crowding" not in scores:
        return None
    total = sum(WEIGHTS[k] for k in scores)
    return 100 * math.exp(sum(WEIGHTS[k] / total * math.log(max(v, 1.0) / 100) for k, v in scores.items()))


def rank_composite(scores: dict[str, float]) -> float | None:
    """The raw composite restricted to RANK_AXES: the quantity the reference population is scored on."""
    return combine({k: v for k, v in scores.items() if k in RANK_AXES})


def percentile_rank(scores: dict[str, float], reference: Callable[[float], float] | None) -> float | None:
    """Where this idea's composite falls among real hackathon projects scored identically, as a percentage.

    63 means "63% of the reference projects scored lower" -- a statement about a named population that can
    be checked, rather than 63 points on a scale nobody defined. The weights inside the composite still are
    not derived from anything, but they now only have to preserve an ORDERING, which is a far weaker claim
    than the one a raw 0-100 score was making."""
    raw = rank_composite(scores)
    if raw is None or reference is None:
        return None
    return 100.0 * reference(raw)


def headline(axes: dict[str, AxisScore], jury_std: float) -> tuple[float | None, float | None]:
    """Point estimate plus the legacy heuristic band. `assemble` prefers `bootstrap_headline`.

    The `8 + 40*jury_std` band has no derivation, and on a geometric mean near the floor a SYMMETRIC band is
    not even well defined: a run that read `14 +- 10.8` was claiming 3.2 to 24.8 for an estimator whose axes
    are clamped at 1 and whose spread up there is strongly one-sided. Kept only for the no-inputs path."""
    live = {k: a.score for k, a in axes.items() if a.score is not None}
    point = combine(live)
    if point is None:
        return None, None
    band = min(30.0, 8 + 40 * jury_std + 6 * (len(WEIGHTS) - len(live)))
    return round(point, 1), round(band, 1)


# --------------------------------------------------------------------------------------
# The interval the measurement actually has
# --------------------------------------------------------------------------------------
@dataclass
class BootstrapInputs:
    """Everything the headline was computed from, kept so the spread can be resampled from it.

    Nothing here costs another network call: the reranker scores, the document frequencies and the model
    samples were all already fetched to produce the point estimate."""

    sims: list[float] = field(default_factory=list)  # reranker scores of the resolved neighbours
    percentile: Callable[[float], float] | None = None
    dkw: float = 0.0  # calibration-set error on any percentile this CDF reports
    rcs: float | None = None
    rcs_pct: Callable[[float], float] | None = None
    rcs_dkw: float = 0.0
    facet_term_dfs: dict[str, dict[str, int]] = field(default_factory=dict)  # facet -> {term: df}
    corpus_n: int = 0
    pair: tuple[int, int, int] | None = None  # df_purpose, df_mechanism, df_both
    cliche_overlap: float | None = None
    prior_sims: list[float] = field(default_factory=list)
    pred_percentile: Callable[[float], float] | None = None
    rank_reference: Callable[[float], float] | None = None  # CDF of the reference population's composite
    rank_dkw: float = 0.0

    @property
    def usable(self) -> bool:
        return bool(self.sims)


@dataclass(frozen=True)
class Interval:
    """The bootstrap's answer: an interval on the raw composite and one on the percentile rank."""

    low: float
    high: float
    rank_low: float | None
    rank_high: float | None
    diagnostics: dict[str, Any]


def _o1(sims: Sequence[float], percentile: Callable[[float], float] | None, rcs: float | None,
        rcs_pct: Callable[[float], float] | None, jitter: float = 0.0, rcs_jitter: float = 0.0) -> float:
    pcts = [_clip01((percentile or _fallback_percentile)(crowding_lite(list(sims))) + jitter)]
    if rcs is not None:
        pcts.append(_clip01((rcs_pct or _fallback_percentile)(rcs) + rcs_jitter))
    return 100 * (1 - statistics.fmean(pcts))


def _o2(facet_rarities: Sequence[float], pair_term: float, cliche: float) -> float:
    return 100 * (0.5 * statistics.fmean(facet_rarities) + 0.3 * pair_term + 0.2 * (1 - cliche))


def _o3(sims: Sequence[float], percentile: Callable[[float], float] | None) -> float:
    mx = max(sims)
    hit_rate = sum(s > COLLISION for s in sims) / len(sims)
    pct = (percentile or (lambda v: min(max((v - 0.3) / 0.6, 0.0), 1.0)))(mx)
    return max(100 * (1 - 0.6 * pct - 0.4 * hit_rate), 0.0)


def _clip01(x: float) -> float:
    return min(1.0, max(0.0, x))


def bootstrap_headline(inp: BootstrapInputs, *, b: int = 1000, seed: int = 20260919,
                       alpha: float = 0.10) -> Interval | None:
    """Resample every input the score was built from and report the interval of the results.

    Four sources of spread, each resampled the way it actually varies:

      retrieved neighbours   nonparametric bootstrap over the reranker scores. `crowding_lite` leans on
                             max(r), a single order statistic of ten selected documents, so this is large
                             and it should be.
      calibration set        the percentile itself is read off an empirical CDF of finite size. DKW bounds
                             that error at sqrt(ln(40)/2n) = 0.078 for n=300; we draw uniformly inside the
                             bound, a conservative stand-in for a simultaneous bound that is not a
                             distribution. It does not shrink by looking harder at one query: build a
                             bigger calibration set.
      document frequencies   df ~ Binomial(N, df/N): the corpus is a sample of the projects that exist.
      model samples          nonparametric bootstrap over the twelve prior-collision similarities.

    Returns an Interval at the 1-alpha level, or None without enough inputs to resample."""
    if not inp.usable:
        return None
    rng = random.Random(seed)
    facets = [dfs for dfs in inp.facet_term_dfs.values() if dfs]
    draws: list[float] = []
    rank_draws: list[float] = []
    for _ in range(b):
        live: dict[str, float] = {"crowding": _o1(
            stats.resample(inp.sims, rng), inp.percentile, inp.rcs, inp.rcs_pct,
            jitter=rng.uniform(-inp.dkw, inp.dkw), rcs_jitter=rng.uniform(-inp.rcs_dkw, inp.rcs_dkw))}
        if facets and inp.corpus_n > 0:
            rarities = []
            for dfs in facets:
                shaken = {t: stats.resample_count(df, inp.corpus_n, rng) for t, df in dfs.items()}
                r = rarity_from_idf(shaken, inp.corpus_n)
                if r is not None:
                    rarities.append(r)
            if rarities:
                pair_term = 0.5
                if inp.pair is not None:
                    a, bb, ab = (stats.resample_count(v, inp.corpus_n, rng) for v in inp.pair)
                    pair_term = _pair_atypicality(npmi_value(a, bb, min(ab, a, bb), inp.corpus_n)) or 0.5
                live["facet_rarity"] = _o2(rarities, pair_term, inp.cliche_overlap or 0.0)
        if inp.prior_sims:
            live["llm_predictability"] = _o3(stats.resample(inp.prior_sims, rng), inp.pred_percentile)
        point = combine(live)
        if point is not None:
            draws.append(point)
        if inp.rank_reference is not None:
            r = percentile_rank(live, inp.rank_reference)
            if r is not None:
                # the reference CDF is itself finite, so its own DKW error rides on every rank it reports
                rank_draws.append(_clip01((r + rng.uniform(-inp.rank_dkw, inp.rank_dkw) * 100) / 100) * 100)
    if len(draws) < b // 2:
        return None
    lo, hi = stats.bootstrap_ci(draws, alpha)
    rlo = rhi = None
    if len(rank_draws) >= b // 2:
        rlo, rhi = stats.bootstrap_ci(rank_draws, alpha)
    return Interval(low=lo, high=hi, rank_low=rlo, rank_high=rhi, diagnostics={
        "replicates": len(draws), "alpha": alpha, "dkw": round(inp.dkw, 4), "rank_dkw": round(inp.rank_dkw, 4),
        "rank_axes": list(RANK_AXES),
        "resampled": sorted({"neighbours"} | ({"facet_dfs"} if facets else set())
                            | ({"model_samples"} if inp.prior_sims else set()))})


def confidence(*, coverage: float, jury_std: float, verified_share: float, canary_pass: float) -> float:
    jury_norm = min(jury_std / 0.35, 1.0)
    return round(0.35 * coverage + 0.25 * (1 - jury_norm) + 0.25 * verified_share + 0.15 * canary_pass, 3)


def decide_abstain(*, coverage: float, corpus_ok: bool, conf: float, missing: list[str]) -> Abstain:
    if not corpus_ok or coverage < 0.5:
        return Abstain(active=True, reason="Insufficient evidence: " + (", ".join(missing) or "too few sources answered") + ".")
    if conf < 0.45:
        return Abstain(active=True, reason=f"Low confidence ({conf:.2f}): the evidence is thin or the jury disagreed. Axes are shown; the headline is withheld.")
    return Abstain(active=False)


def assemble(crowd: AxisScore, rarity: AxisScore, pred: AxisScore, *, jury_std: float, conf: float,
             abstain: Abstain, boot: BootstrapInputs | None = None) -> Scores:
    """The headline plus its interval. With `boot` the interval is the bootstrap's, and it is asymmetric
    because the geometric mean is; without it, the legacy heuristic band."""
    axes_now = {"crowding": crowd, "facet_rarity": rarity, "llm_predictability": pred}
    h, band = headline(axes_now, jury_std)
    live = {k: a.score for k, a in axes_now.items() if a.score is not None}
    low = high = rank = rank_low = rank_high = None
    reference = boot.rank_reference if boot is not None else None
    r = percentile_rank(live, reference)
    if r is not None:
        rank = round(r, 1)
    interval = bootstrap_headline(boot) if (boot is not None and h is not None) else None
    if interval is not None:
        low, high = round(interval.low, 1), round(interval.high, 1)
        band = round((interval.high - interval.low) / 2, 1)  # one number for callers that want one
        if interval.rank_low is not None:
            rank_low, rank_high = round(interval.rank_low, 1), round(interval.rank_high, 1)
        crowd.detail["interval_method"] = interval.diagnostics
    if abstain.active:
        h = band = low = high = rank = rank_low = rank_high = None
    return Scores(crowding=crowd, facet_rarity=rarity, llm_predictability=pred, headline=h, band=band,
                  low=low, high=high, rank=rank, rank_low=rank_low, rank_high=rank_high,
                  rank_axes=list(RANK_AXES) if rank is not None else [], confidence=conf, abstain=abstain)
