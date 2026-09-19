"""The handful of statistics the Slop Index needs, written out with numpy (no scipy in this project).

    wilson_ci(k, n)                  Wilson score interval for a proportion (well behaved near 0, unlike Wald)
    rankdata(a)                      average ranks, ties shared
    mann_whitney_u(x, y)             two-sided, normal approximation, tie-corrected variance, continuity correction
    cliffs_delta(x, y)               P(x > y) - P(x < y), in [-1, 1]
    stratified_mann_whitney(pairs)   van Elteren-style: combine within-stratum U statistics (strata = years)

Each is unit-tested against hand-computed examples in backend/tests/test_investigation_stats.py.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

Z95 = 1.959963984540054  # two-sided 95%


def wilson_ci(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials. n == 0 -> (0.0, 1.0): we know nothing."""
    if n <= 0:
        return 0.0, 1.0
    if not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n, got k={k}, n={n}")
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    # at the boundaries the exact algebra gives 0 and 1; clamp away floating-point dust
    low = 0.0 if k == 0 else max(0.0, centre - half)
    high = 1.0 if k == n else min(1.0, centre + half)
    return low, high


def normal_sf(z: float) -> float:
    """P(Z > z) for a standard normal."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def rankdata(values: Sequence[float] | np.ndarray) -> np.ndarray:
    """1-based ranks; tied values share the average of the ranks they span."""
    a = np.asarray(values, dtype=float)
    n = a.size
    if n == 0:
        return np.empty(0, dtype=float)
    order = np.argsort(a, kind="mergesort")
    sorted_a = a[order]
    # boundaries of runs of equal values
    starts = np.flatnonzero(np.concatenate(([True], sorted_a[1:] != sorted_a[:-1])))
    ends = np.concatenate((starts[1:], [n]))
    ranks_sorted = np.empty(n, dtype=float)
    for s, e in zip(starts, ends):
        ranks_sorted[s:e] = (s + 1 + e) / 2.0  # mean of ranks s+1 .. e
    ranks = np.empty(n, dtype=float)
    ranks[order] = ranks_sorted
    return ranks


def _tie_term(combined: np.ndarray) -> float:
    """sum(t^3 - t) over groups of tied values."""
    _, counts = np.unique(combined, return_counts=True)
    counts = counts.astype(float)
    return float(np.sum(counts**3 - counts))


@dataclass(frozen=True)
class MannWhitney:
    u1: float  # U for the first sample = #(x > y) + 0.5 * #(x == y)
    u2: float
    z: float  # continuity-corrected; sign follows u1 - n1*n2/2
    p_value: float  # two-sided
    n1: int
    n2: int
    mean: float
    variance: float  # tie-corrected

    @property
    def cliffs_delta(self) -> float:
        return 2.0 * self.u1 / (self.n1 * self.n2) - 1.0


def _clean(a: Iterable[float]) -> np.ndarray:
    arr = np.asarray(list(a) if not isinstance(a, np.ndarray) else a, dtype=float)
    return arr[~np.isnan(arr)]


def mann_whitney_u(x: Iterable[float], y: Iterable[float], *, continuity: bool = True) -> MannWhitney:
    """Two-sided Mann-Whitney U test with the normal approximation.

    U1 = R1 - n1(n1+1)/2,  mean = n1 n2 / 2,
    var = n1 n2 / 12 * ((N + 1) - sum(t^3 - t) / (N (N - 1)))      (tie correction),
    z = (U1 - mean -/+ 0.5) / sqrt(var)                             (continuity correction toward the mean).
    NaNs are dropped. With every value tied (variance 0) the p-value is 1."""
    xa, ya = _clean(x), _clean(y)
    n1, n2 = xa.size, ya.size
    if n1 == 0 or n2 == 0:
        raise ValueError("both samples need at least one value")
    combined = np.concatenate((xa, ya))
    ranks = rankdata(combined)
    u1 = float(ranks[:n1].sum() - n1 * (n1 + 1) / 2.0)
    u2 = n1 * n2 - u1
    big_n = n1 + n2
    mean = n1 * n2 / 2.0
    variance = n1 * n2 / 12.0 * ((big_n + 1) - _tie_term(combined) / (big_n * (big_n - 1)))
    z, p = _z_and_p(u1 - mean, variance, continuity)
    return MannWhitney(u1=u1, u2=u2, z=z, p_value=p, n1=n1, n2=n2, mean=mean, variance=variance)


def _z_and_p(diff: float, variance: float, continuity: bool) -> tuple[float, float]:
    if variance <= 0:
        return 0.0, 1.0
    if continuity:
        diff = math.copysign(max(0.0, abs(diff) - 0.5), diff)
    z = diff / math.sqrt(variance)
    return z, min(1.0, 2.0 * normal_sf(abs(z)))


def cliffs_delta(x: Iterable[float], y: Iterable[float]) -> float:
    """(#(x > y) - #(x < y)) / (n1 n2). +1: every x above every y; 0: no dominance. Computed from ranks, O(N log N)."""
    return mann_whitney_u(x, y).cliffs_delta


@dataclass(frozen=True)
class StratifiedMannWhitney:
    z: float
    p_value: float  # two-sided
    cliffs_delta: float  # sum of within-stratum dominance counts / sum of n1*n2
    n1: int
    n2: int
    strata: int


def stratified_mann_whitney(pairs: Iterable[tuple[Iterable[float], Iterable[float]]], *, continuity: bool = True) -> StratifiedMannWhitney | None:
    """Combine within-stratum tests so that a drift across strata (here: years) cannot fake an effect.

    z = sum_k (U1_k - mean_k) / sqrt(sum_k var_k), unit weights. Strata where either group is empty are skipped.
    The pooled Cliff's delta is sum_k (2 U1_k - n1_k n2_k) / sum_k n1_k n2_k: only within-year pairs are compared."""
    results = []
    for x, y in pairs:
        xa, ya = _clean(x), _clean(y)
        if xa.size and ya.size:
            results.append(mann_whitney_u(xa, ya))
    if not results:
        return None
    diff = sum(r.u1 - r.mean for r in results)
    variance = sum(r.variance for r in results)
    z, p = _z_and_p(diff, variance, continuity)
    pairs_total = sum(r.n1 * r.n2 for r in results)
    delta = sum(2.0 * r.u1 - r.n1 * r.n2 for r in results) / pairs_total
    return StratifiedMannWhitney(z=z, p_value=p, cliffs_delta=delta, n1=sum(r.n1 for r in results),
                                 n2=sum(r.n2 for r in results), strata=len(results))
