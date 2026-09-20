"""The statistics that replaced the invented constants (scoring/stats.py). Hand-computed where possible."""
import math
import random

import pytest

from app.scoring import stats


# ---------------------------------------------------------------- Wilson
def test_wilson_matches_the_algebra_and_behaves_at_the_edges():
    lo, hi = stats.wilson_ci(5, 20)
    z2 = stats.Z95**2
    denom = 1 + z2 / 20
    centre = (0.25 + z2 / 40) / denom
    half = stats.Z95 * math.sqrt(0.25 * 0.75 / 20 + z2 / 1600) / denom
    assert (lo, hi) == pytest.approx((centre - half, centre + half))
    assert stats.wilson_ci(0, 50)[0] == 0.0 and stats.wilson_ci(50, 50)[1] == 1.0
    assert stats.wilson_ci(0, 0) == (0.0, 1.0)  # no data -> we know nothing
    with pytest.raises(ValueError):
        stats.wilson_ci(5, 2)


def test_wilson_narrows_as_n_grows():
    widths = [stats.wilson_ci(n // 4, n)[1] - stats.wilson_ci(n // 4, n)[0] for n in (20, 200, 2000)]
    assert widths == sorted(widths, reverse=True)


# ---------------------------------------------------------------- DKW
def test_dkw_matches_the_bound_and_the_numbers_we_quote():
    assert stats.dkw_epsilon(300) == pytest.approx(math.sqrt(math.log(40) / 600))
    assert round(stats.dkw_epsilon(300), 3) == 0.078  # the 300-point calibration set in use
    assert round(stats.dkw_epsilon(1000), 3) == 0.043
    assert stats.dkw_epsilon(0) == 1.0


def test_dkw_shrinks_only_with_the_calibration_set():
    assert stats.dkw_epsilon(4 * 300) == pytest.approx(stats.dkw_epsilon(300) / 2)


# ---------------------------------------------------------------- GPD
def test_gpd_sf_endpoints_and_the_exponential_limit():
    assert stats.gpd_sf(0, 0.2, 1.0) == 1.0
    assert stats.gpd_sf(-1, 0.2, 1.0) == 1.0
    assert stats.gpd_sf(2.0, 0.0, 1.0) == pytest.approx(math.exp(-2.0))  # xi = 0 is exponential
    assert stats.gpd_sf(1.0, 1.0, 1.0) == pytest.approx(0.5)  # (1 + 1*1/1)^-1
    assert stats.gpd_sf(10.0, -0.5, 1.0) == 0.0  # bounded tail, past the endpoint
    assert stats.gpd_sf(1.0, 0.2, 0.0) == 0.0


def test_gpd_sf_is_monotone():
    vals = [stats.gpd_sf(x, 0.15, 0.5) for x in (0.1, 0.5, 1.0, 3.0, 10.0)]
    assert vals == sorted(vals, reverse=True)


def test_gpd_pwm_recovers_an_exponential_tail():
    """xi = 0 exactly is the exponential; PWM on a clean exponential sample should land near it."""
    rng = random.Random(7)
    sample = [rng.expovariate(1 / 2.0) for _ in range(4000)]
    xi, sigma = stats.gpd_fit_pwm(sample)
    assert abs(xi) < 0.08
    assert sigma == pytest.approx(2.0, rel=0.10)


def test_gpd_pwm_recovers_a_heavy_tail():
    """Inverse-CDF sampling from a GPD with xi = 0.3, sigma = 1.0."""
    rng = random.Random(11)
    xi_true, sigma_true = 0.3, 1.0
    sample = [sigma_true / xi_true * ((1 - rng.random()) ** -xi_true - 1) for _ in range(6000)]
    xi, sigma = stats.gpd_fit_pwm(sample)
    assert xi == pytest.approx(xi_true, abs=0.08)
    assert sigma == pytest.approx(sigma_true, rel=0.15)


def test_gpd_pwm_declines_degenerate_samples():
    assert stats.gpd_fit_pwm([1.0, 2.0]) is None  # too few
    assert stats.gpd_fit_pwm([0.0] * 50) is None  # nothing positive


# ---------------------------------------------------------------- tail percentile
def _calibration(n=300, seed=3):
    rng = random.Random(seed)
    return sorted(rng.betavariate(2, 5) for _ in range(n))


def test_fit_tail_needs_enough_points_up_there():
    assert stats.fit_tail([0.1, 0.2, 0.3]) is None
    gpd = stats.fit_tail(_calibration())
    assert gpd is not None and gpd.n_total == 300 and gpd.n_exceed >= 20
    assert gpd.tail_mass == pytest.approx(gpd.n_exceed / 300)


def test_tail_percentile_resolves_above_the_threshold_where_counting_cannot():
    """The complaint: crowding_lite 0.435 read 0.977 with ~7 of 300 documents above it, and 0.977 vs 0.990
    is O1 = 2.3 vs O1 = 1.0. Counting gives the same answer for very different values; the fit does not."""
    vals = _calibration()
    gpd = stats.fit_tail(vals)
    # values spread across the upper tail, where only a handful of calibration points sit above each one
    probes = [vals[-20], vals[-10], vals[-6], vals[-3]]
    fitted = [stats.tail_percentile(x, vals, gpd, _midrank(x, vals)) for x in probes]
    assert fitted == sorted(fitted) and len(set(fitted)) == 4  # the fit separates them
    assert all(0.9 < p < 1.0 for p in fitted)  # up in the tail, but never certain
    # the fitted percentile is strictly finer-grained than the handful of order statistics up there
    assert fitted[-1] - fitted[0] > 0.02


def _midrank(x, vals):
    import bisect

    return (bisect.bisect_left(vals, x) + bisect.bisect_right(vals, x)) / (2 * len(vals))


def test_tail_percentile_never_returns_exactly_one():
    """O1 = 100*(1 - pct), so pct == 1.0 is a zero fed to a logarithm."""
    vals = _calibration()
    gpd = stats.fit_tail(vals)
    assert stats.tail_percentile(vals[-1] + 10.0, vals, gpd, 1.0) < 1.0


def test_tail_percentile_leaves_the_body_of_the_distribution_alone():
    vals = _calibration()
    gpd = stats.fit_tail(vals)
    median = vals[150]
    assert stats.tail_percentile(median, vals, gpd, 0.5) == 0.5
    assert stats.tail_percentile(median, vals, None, 0.5) == 0.5  # no fit -> empirical


def test_tail_percentile_joins_the_empirical_cdf_continuously_at_the_threshold():
    """tail_mass = n_exceed/n_total, so the fitted curve starts exactly where counting left off."""
    vals = _calibration()
    gpd = stats.fit_tail(vals)
    just_above = gpd.threshold + 1e-12
    assert stats.tail_percentile(just_above, vals, gpd, _midrank(gpd.threshold, vals)) == \
        pytest.approx(1.0 - gpd.tail_mass, abs=1e-6)
    assert _midrank(gpd.threshold, vals) == pytest.approx(1.0 - gpd.tail_mass, abs=0.02)


def test_the_fit_replaces_rather_than_raises_the_saturated_empirical_value():
    """Above the largest calibration point the empirical CDF reads 1.0 for everything. If the fit only ever
    RAISED it, every extreme value would collapse back to one percentile -- the failure being fixed here.
    The empirical CDF is also biased up there: with n draws the largest is not the population maximum."""
    vals = _calibration()
    gpd = stats.fit_tail(vals)
    above = [v for v in (vals[-1] + 0.005, vals[-1] + 0.02)]
    assert all(_midrank(x, vals) == 1.0 for x in above)  # counting has given up
    fitted = [stats.tail_percentile(x, vals, gpd, 1.0) for x in above]
    assert fitted[0] < fitted[1] < 1.0  # the fit has not


# ---------------------------------------------------------------- bootstrap
def test_bootstrap_ci_brackets_and_widens_with_spread():
    tight = stats.bootstrap_ci([50.0 + i * 0.01 for i in range(1000)])
    wide = stats.bootstrap_ci([10.0 + i * 0.08 for i in range(1000)])
    assert tight[0] < 50.5 < tight[1]
    assert (wide[1] - wide[0]) > (tight[1] - tight[0])
    assert stats.bootstrap_ci([7.0]) == (7.0, 7.0)
    with pytest.raises(ValueError):
        stats.bootstrap_ci([])


def test_bootstrap_ci_alpha_controls_the_width():
    vals = [float(i) for i in range(1000)]
    assert (stats.bootstrap_ci(vals, 0.50)[1] - stats.bootstrap_ci(vals, 0.50)[0]) < \
           (stats.bootstrap_ci(vals, 0.02)[1] - stats.bootstrap_ci(vals, 0.02)[0])


def test_resample_draws_with_replacement_from_the_sample():
    rng = random.Random(1)
    out = stats.resample([1.0, 2.0, 3.0], rng)
    assert len(out) == 3 and set(out) <= {1.0, 2.0, 3.0}
    assert stats.resample([], rng) == []


def test_resample_count_stays_in_range_and_centres_on_the_observed_count():
    rng = random.Random(2)
    draws = [stats.resample_count(1020, 8110, rng) for _ in range(400)]
    assert all(0 <= d <= 8110 for d in draws)
    assert abs(sum(draws) / len(draws) - 1020) < 15
    assert stats.resample_count(0, 100, rng) == 0 and stats.resample_count(100, 100, rng) == 100
    assert stats.resample_count(5, 0, rng) == 0
