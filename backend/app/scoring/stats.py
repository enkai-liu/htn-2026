"""The statistics the score needs to be honest about itself. Pure functions, no scipy.

    wilson_ci(k, n)              interval for a proportion; well behaved at df=0, unlike Wald
    dkw_epsilon(n)               how wrong an empirical CDF built from n points can be, at 1-alpha
    gpd_fit_pwm(exceedances)     Generalised Pareto by probability-weighted moments (Hosking & Wallis 1987)
    gpd_sf(x, xi, sigma)         its survival function
    tail_percentile(...)         empirical CDF below the threshold, fitted GPD above it
    bootstrap_ci(values, alpha)  percentile interval of a bootstrap sample

Why each of these is here, from a real run whose headline read `14 +- 10.8`:

  crowding_lite = 0.435 sat at the 97.7th percentile of a 300-point calibration set. About seven calibration
  documents were above it. The difference between 0.977 and 0.990 is the difference between O1 = 2.3 and
  O1 = 1.0, and an empirical CDF with n = 300 cannot resolve it: DKW puts +-0.078 on ANY percentile it
  reports. The headline was being decided in the one region where the estimator is blindest, and said
  nothing about it. `tail_percentile` fits the tail instead of counting seven points, and `dkw_epsilon`
  makes the remaining calibration error part of the published interval.

  `+- 10.8` came from `8 + 40*jury_std + 6*abstains`, a formula with no derivation. On a geometric mean
  sitting at 14 a symmetric band is not even well defined: it implies 3.2 to 24.8, but the axes are clamped
  at 1 and the mean is strongly asymmetric near the floor. `bootstrap_ci` replaces it with the spread the
  measurement actually has, which is asymmetric because the estimator is.
"""
from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

Z95 = 1.959963984540054


# --------------------------------------------------------------------------------------
# Proportions
# --------------------------------------------------------------------------------------
def wilson_ci(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials. n == 0 -> (0.0, 1.0): we know nothing.

    Every document frequency in AXIS 2 is k out of N, and the corpus is itself a sample of the projects that
    exist, so a df is an estimate with an interval, not a fact."""
    if n <= 0:
        return 0.0, 1.0
    if not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n, got k={k}, n={n}")
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (0.0 if k == 0 else max(0.0, centre - half)), (1.0 if k == n else min(1.0, centre + half))


# --------------------------------------------------------------------------------------
# How much an empirical CDF can be wrong
# --------------------------------------------------------------------------------------
def dkw_epsilon(n: int, alpha: float = 0.05) -> float:
    """Dvoretzky-Kiefer-Wolfowitz: with probability 1-alpha, sup_x |F_n(x) - F(x)| <= sqrt(ln(2/alpha)/(2n)).

    n=300 -> 0.078, n=1000 -> 0.043, n=5000 -> 0.019. This is a property of the calibration SET SIZE, so it
    applies to every percentile the CDF reports and it does not shrink by looking harder at one query."""
    if n <= 0:
        return 1.0
    return min(1.0, math.sqrt(math.log(2.0 / alpha) / (2.0 * n)))


# --------------------------------------------------------------------------------------
# The tail (peaks over threshold)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class GPD:
    """Generalised Pareto fitted to the exceedances over `threshold`.

    xi > 0 heavy tail, xi = 0 exponential, xi < 0 bounded (there is a hardest-possible value)."""

    xi: float
    sigma: float
    threshold: float
    n_exceed: int
    n_total: int

    @property
    def tail_mass(self) -> float:
        """P(X > threshold), estimated empirically: the GPD only models the shape above it."""
        return self.n_exceed / self.n_total if self.n_total else 0.0


def gpd_sf(x: float, xi: float, sigma: float) -> float:
    """P(Z > x) for a Generalised Pareto with scale sigma, shape xi, over an exceedance z = value - threshold."""
    if x <= 0:
        return 1.0
    if sigma <= 0:
        return 0.0
    if abs(xi) < 1e-9:
        return math.exp(-x / sigma)
    base = 1.0 + xi * x / sigma
    if base <= 0:  # past the upper endpoint of a bounded (xi < 0) tail
        return 0.0
    return base ** (-1.0 / xi)


def gpd_fit_pwm(exceedances: Sequence[float]) -> tuple[float, float] | None:
    """Probability-weighted moments (Hosking & Wallis 1987). Closed form, no optimiser, and far steadier than
    maximum likelihood at the sample sizes a calibration set gives us.

        a0 = mean(z),  a1 = (1/n) sum (1 - p_i) z_(i),  p_i = (i - 0.35)/n   (z sorted ascending)
        k  = a0/(a0 - 2 a1) - 2,   alpha = 2 a0 a1/(a0 - 2 a1)               (Hosking parameterisation)
        xi = -k,  sigma = alpha                                              (standard parameterisation)

    Returns None when the sample is too small or degenerate to fit."""
    z = sorted(float(v) for v in exceedances if v > 0)
    n = len(z)
    if n < 10:
        return None
    a0 = sum(z) / n
    a1 = sum((1.0 - (i + 1 - 0.35) / n) * v for i, v in enumerate(z)) / n
    denom = a0 - 2.0 * a1
    if abs(denom) < 1e-12 or a0 <= 0:
        return None
    k = a0 / denom - 2.0
    sigma = 2.0 * a0 * a1 / denom
    if sigma <= 0 or not math.isfinite(sigma) or not math.isfinite(k):
        return None
    return -k, sigma


def fit_tail(values: Sequence[float], *, tail_fraction: float = 0.10, min_exceed: int = 20) -> GPD | None:
    """Fit the top `tail_fraction` of a calibration set. None when there are too few points up there to fit."""
    vals = sorted(float(v) for v in values)
    n = len(vals)
    if n < min_exceed * 2:
        return None
    idx = max(0, min(n - min_exceed, int(math.floor(n * (1.0 - tail_fraction)))))
    threshold = vals[idx]
    exceed = [v - threshold for v in vals[idx:] if v > threshold]
    if len(exceed) < min_exceed:
        return None
    fit = gpd_fit_pwm(exceed)
    if fit is None:
        return None
    xi, sigma = fit
    return GPD(xi=xi, sigma=sigma, threshold=threshold, n_exceed=len(exceed), n_total=n)


def tail_percentile(value: float, sorted_values: Sequence[float], gpd: GPD | None,
                    empirical: float) -> float:
    """Empirical mid-rank below the threshold, fitted GPD above it.

    Below the threshold the empirical CDF has plenty of points and is the better estimate. Above it, counting
    the handful of calibration documents that happen to be higher throws away all the resolution exactly
    where the headline is most sensitive, so the fitted tail takes over and the two agree at the join."""
    if gpd is None or value <= gpd.threshold:
        return empirical
    # Above the threshold the fit REPLACES the empirical value; it does not merely raise it. Taking
    # max(empirical, fitted) would let the saturated empirical CDF (1.0 for anything above the largest
    # calibration point) win exactly where the fit is needed, which is the resolution loss this function
    # exists to remove. The two agree at the join by construction, because tail_mass = n_exceed/n_total,
    # so the combined function is continuous and monotone. The empirical CDF is also biased up here: with
    # 300 draws the largest is not the population maximum, so the fit being LOWER than it is correct.
    sf = gpd.tail_mass * gpd_sf(value - gpd.threshold, gpd.xi, gpd.sigma)
    # never exactly 1.0: O1 = 100*(1 - pct) feeds a logarithm
    return min(1.0 - 1e-9, 1.0 - sf)


# --------------------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------------------
def bootstrap_ci(values: Sequence[float], alpha: float = 0.10) -> tuple[float, float]:
    """Percentile interval of an already-computed bootstrap sample. Default 90% (5th to 95th)."""
    vals = sorted(float(v) for v in values)
    if not vals:
        raise ValueError("bootstrap_ci needs at least one replicate")
    if len(vals) == 1:
        return vals[0], vals[0]

    def q(p: float) -> float:
        pos = p * (len(vals) - 1)
        lo = math.floor(pos)
        hi = min(lo + 1, len(vals) - 1)
        return vals[lo] + (pos - lo) * (vals[hi] - vals[lo])

    return q(alpha / 2), q(1.0 - alpha / 2)


def resample(values: Sequence[float], rng: random.Random) -> list[float]:
    """One nonparametric bootstrap replicate: draw len(values) with replacement."""
    n = len(values)
    return [values[rng.randrange(n)] for _ in range(n)] if n else []


def resample_count(k: int, n: int, rng: random.Random) -> int:
    """One parametric bootstrap replicate of a document frequency: k' ~ Binomial(n, k/n).

    A df is a count over a corpus that is itself a sample, so its sampling error belongs in the interval.
    Normal approximation with a continuity-style clamp; exact enough beside everything else here."""
    if n <= 0 or k <= 0:
        return 0
    if k >= n:
        return n
    p = k / n
    sd = math.sqrt(n * p * (1.0 - p))
    return max(0, min(n, int(round(rng.gauss(k, sd)))))
