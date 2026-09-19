"""The Slop Index statistics (hand-rolled with numpy, no scipy) checked against hand-computed examples,
plus the year join on Devpost's `submission_period_dates` and the shape of slop_index.json."""
from __future__ import annotations

import datetime as dt
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root: `investigation` is a top-level package

from investigation import analyze  # noqa: E402
from investigation.common import (  # noqa: E402
    clean_writeup,
    is_winner_from_prize,
    looks_english,
    parse_period,
    parse_period_year,
    recent_hackathon_year,
    sample_id_for,
    sample_rank,
)
from investigation.export_public import PUBLIC_COLUMNS  # noqa: E402
from investigation.scan import COLUMNS as SCAN_COLUMNS, pick_pilot_years  # noqa: E402
from investigation.stats import (  # noqa: E402
    cliffs_delta,
    mann_whitney_u,
    normal_sf,
    rankdata,
    stratified_mann_whitney,
    wilson_ci,
)


# ---------------------------------------------------------------------------- Wilson interval
def test_wilson_known_values():
    # classic textbook case: 10 successes in 100 trials -> (0.0552, 0.1744)
    low, high = wilson_ci(10, 100)
    assert low == pytest.approx(0.05522914, abs=1e-7) and high == pytest.approx(0.17436566, abs=1e-7)
    # by hand, p = 0.5, n = 10: centre = 0.5, half = z*sqrt(0.025 + z^2/400)/(1 + z^2/10)
    z = 1.959963984540054
    half = z * math.sqrt(0.025 + z * z / 400) / (1 + z * z / 10)
    assert wilson_ci(5, 10) == pytest.approx((0.5 - half, 0.5 + half), abs=1e-12)
    assert wilson_ci(5, 10) == pytest.approx((0.2366, 0.7634), abs=1e-4)


def test_wilson_boundaries():
    z2 = 1.959963984540054 ** 2
    low, high = wilson_ci(0, 50)
    assert low == 0.0 and high == pytest.approx(z2 / (50 + z2), abs=1e-12)  # = 0.0713: "0 of 50" is not "0%"
    low, high = wilson_ci(50, 50)
    assert high == 1.0 and low == pytest.approx(50 / (50 + z2), abs=1e-12)
    assert wilson_ci(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson_ci(11, 10)
    # the interval always contains the point estimate and narrows with n
    for k, n in [(1, 7), (3, 150), (30, 150), (149, 150)]:
        lo, hi = wilson_ci(k, n)
        assert 0.0 <= lo <= k / n <= hi <= 1.0
    assert (wilson_ci(30, 150)[1] - wilson_ci(30, 150)[0]) > (wilson_ci(300, 1500)[1] - wilson_ci(300, 1500)[0])


# ---------------------------------------------------------------------------- ranks
def test_rankdata_averages_ties():
    assert rankdata([1, 2, 2, 3, 2, 3, 4, 4, 5]).tolist() == [1, 3, 3, 5.5, 3, 5.5, 7.5, 7.5, 9]
    assert rankdata([10, 30, 20]).tolist() == [1, 3, 2]
    assert rankdata([7, 7, 7]).tolist() == [2, 2, 2]
    assert rankdata([]).tolist() == []


# ---------------------------------------------------------------------------- Mann-Whitney U
def test_mann_whitney_no_ties_hand_computed():
    # x entirely below y: U1 = 0. mean = 4.5, var = 3*3*7/12 = 5.25, z = (0 - 4.5 + 0.5)/sqrt(5.25) = -1.745743
    r = mann_whitney_u([1, 2, 3], [4, 5, 6])
    assert (r.u1, r.u2, r.n1, r.n2) == (0.0, 9.0, 3, 3)
    assert r.mean == 4.5 and r.variance == pytest.approx(5.25)
    assert r.z == pytest.approx(-1.7457431, abs=1e-6)
    assert r.p_value == pytest.approx(0.0808556, abs=1e-6)  # = scipy.stats.mannwhitneyu(..., method="asymptotic")
    assert r.cliffs_delta == -1.0


def test_mann_whitney_with_ties_hand_computed():
    # pooled sorted: 1x 2x 2x 2y 3x 3y 4y 4y 5y -> ranks 1, 3, 3, 3, 5.5, 5.5, 7.5, 7.5, 9
    # R_x = 1 + 3 + 3 + 5.5 = 12.5 ; U_x = 12.5 - 4*5/2 = 2.5   (pairs: 1 win + 3 ties*0.5)
    # ties: t = 3, 2, 2 -> sum(t^3 - t) = 24 + 6 + 6 = 36 ; var = 20/12 * (10 - 36/72) = 15.8333
    # z = (2.5 - 10 + 0.5) / sqrt(15.8333) = -1.759186 ; p = 0.078546
    x, y = [1, 2, 2, 3], [2, 3, 4, 4, 5]
    r = mann_whitney_u(x, y)
    assert r.u1 == 2.5 and r.u2 == 17.5 and r.mean == 10.0
    assert r.variance == pytest.approx(15.8333333, abs=1e-6)
    assert r.z == pytest.approx(-1.7591864, abs=1e-6)
    assert r.p_value == pytest.approx(0.0785459, abs=1e-6)
    assert r.p_value == pytest.approx(2 * normal_sf(abs(r.z)))
    untied_variance = 4 * 5 * (9 + 1) / 12
    assert r.variance < untied_variance, "the tie correction must shrink the variance"
    without_cc = mann_whitney_u(x, y, continuity=False)
    assert without_cc.z == pytest.approx(-7.5 / math.sqrt(15.8333333), abs=1e-6) and without_cc.p_value < r.p_value


def test_mann_whitney_symmetry_and_degenerate_cases():
    x, y = [3.1, 4.7, 1.2, 9.9, 5.0, 5.0], [2.2, 8.4, 5.0, 7.7]
    a, b = mann_whitney_u(x, y), mann_whitney_u(y, x)
    assert a.p_value == pytest.approx(b.p_value) and a.z == pytest.approx(-b.z) and a.u1 == b.u2
    assert a.u1 + a.u2 == len(x) * len(y)
    same = mann_whitney_u([5, 5, 5], [5, 5])
    assert same.p_value == 1.0 and same.z == 0.0 and same.cliffs_delta == 0.0
    identical = mann_whitney_u([1, 2, 3, 4], [1, 2, 3, 4])
    assert identical.p_value == 1.0 and identical.cliffs_delta == 0.0
    assert mann_whitney_u([1.0, float("nan"), 2.0], [3.0, 4.0]).n1 == 2, "NaNs are dropped"
    with pytest.raises(ValueError):
        mann_whitney_u([], [1, 2])


def test_mann_whitney_detects_a_clear_shift():
    rng = np.random.default_rng(42)
    r = mann_whitney_u(rng.normal(0.62, 0.05, 60), rng.normal(0.55, 0.05, 200))
    assert r.p_value < 1e-6 and r.cliffs_delta > 0.5
    null = mann_whitney_u(rng.normal(0.55, 0.05, 60), rng.normal(0.55, 0.05, 200))
    assert null.p_value > 0.01 and abs(null.cliffs_delta) < 0.25


# ---------------------------------------------------------------------------- Cliff's delta
def test_cliffs_delta_hand_computed():
    assert cliffs_delta([4, 5, 6], [1, 2, 3]) == 1.0
    assert cliffs_delta([1, 2, 3], [4, 5, 6]) == -1.0
    # x = [1,2,2,3], y = [2,3,4,4,5]: x>y once (3>2), x<y 16 times, 3 ties -> (1 - 16)/20
    assert cliffs_delta([1, 2, 2, 3], [2, 3, 4, 4, 5]) == pytest.approx(-0.75)
    # x = [1,3,5], y = [2,4]: wins (3>2, 5>2, 5>4) = 3, losses (1<2, 1<4, 3<4) = 3
    assert cliffs_delta([1, 3, 5], [2, 4]) == pytest.approx(0.0)
    assert cliffs_delta([2, 4, 6, 8], [1, 3, 5]) == pytest.approx((9 - 3) / 12)


def test_cliffs_delta_equals_brute_force_pair_counting():
    rng = np.random.default_rng(7)
    for _ in range(50):
        x = rng.integers(0, 6, size=rng.integers(1, 12)).tolist()  # small integer range -> plenty of ties
        y = rng.integers(0, 6, size=rng.integers(1, 12)).tolist()
        wins = sum(a > b for a in x for b in y)
        losses = sum(a < b for a in x for b in y)
        assert cliffs_delta(x, y) == pytest.approx((wins - losses) / (len(x) * len(y)), abs=1e-12)
        assert cliffs_delta(x, y) == pytest.approx(-cliffs_delta(y, x), abs=1e-12)


# ---------------------------------------------------------------------------- stratified (within-year) pooling
def test_stratified_test_hand_computed():
    # strata from the two examples above: sum(U - mean) = -4.5 + -7.5 = -12 ; sum var = 5.25 + 15.8333 = 21.0833
    # z = (-12 + 0.5) / sqrt(21.0833) = -2.504541 ; delta = ((0 - 9) + (5 - 20)) / (9 + 20) = -24/29
    r = stratified_mann_whitney([([1, 2, 3], [4, 5, 6]), ([1, 2, 2, 3], [2, 3, 4, 4, 5]), ([], [1.0]), ([2.0], [])])
    assert r.strata == 2 and (r.n1, r.n2) == (3 + 4, 3 + 5)
    assert r.z == pytest.approx(-2.5045413, abs=1e-6)
    assert r.p_value == pytest.approx(2 * normal_sf(2.5045413), abs=1e-7)
    assert r.cliffs_delta == pytest.approx(-24 / 29)
    assert stratified_mann_whitney([([], [1.0])]) is None


def test_stratification_removes_a_pure_year_effect():
    """Flagged write-ups are concentrated in the later year AND nn_sim drifts up over time, but within each year the two
    groups are identical. Lumping the years shows a spurious effect; the stratified test does not."""
    rng = np.random.default_rng(3)
    early = rng.normal(0.50, 0.03, 400)
    late = rng.normal(0.60, 0.03, 400)
    strata = [(early[:20], early[20:]), (late[:200], late[200:])]
    lumped = mann_whitney_u(np.concatenate([early[:20], late[:200]]), np.concatenate([early[20:], late[200:]]))
    pooled = stratified_mann_whitney(strata)
    assert lumped.p_value < 1e-6 and lumped.cliffs_delta > 0.3
    assert pooled.p_value > 0.01 and abs(pooled.cliffs_delta) < 0.15


# ---------------------------------------------------------------------------- the year join
@pytest.mark.parametrize(("period", "start", "end"), [
    ("Oct 01 - Dec 04, 2024", dt.date(2024, 10, 1), dt.date(2024, 12, 4)),
    ("Feb 27 - 28, 2016", dt.date(2016, 2, 27), dt.date(2016, 2, 28)),
    ("Mar 10, 2018", dt.date(2018, 3, 10), dt.date(2018, 3, 10)),
    ("Sep 27 - 28, 2025", dt.date(2025, 9, 27), dt.date(2025, 9, 28)),
    ("Dec 15, 2023 - Jan 20, 2024", dt.date(2023, 12, 15), dt.date(2024, 1, 20)),  # spans two years, both stated
    ("Nov 30, 2022 - Feb 01, 2023", dt.date(2022, 11, 30), dt.date(2023, 2, 1)),
    ("Dec 28 - Jan 02, 2024", dt.date(2023, 12, 28), dt.date(2024, 1, 2)),  # spans two years, start year implied
    ("Sept 05 – 07, 2019", dt.date(2019, 9, 5), dt.date(2019, 9, 7)),  # en dash, four-letter month
])
def test_parse_period(period, start, end):
    assert parse_period(period) == (start, end)
    assert parse_period_year(period) == end.year


def test_year_is_the_end_of_the_submission_period():
    assert parse_period_year("Dec 15, 2023 - Jan 20, 2024") == 2024
    assert parse_period_year("Dec 20, 2019 - Jan 05, 2020") == 2020
    assert parse_period_year("Oct 01 - Dec 04, 2024") == 2024


def test_unparseable_periods():
    assert parse_period_year("Spring 2021 (dates TBA)") == 2021  # falls back to the last year mentioned
    assert parse_period_year("Feb 30, 2021") == 2021  # impossible date -> still a usable year
    for bad in ("", "   ", "Ended", None, 12345, float("nan")):
        assert parse_period_year(bad) is None  # type: ignore[arg-type]
        assert parse_period(bad) == (None, None)  # type: ignore[arg-type]


def test_recent_dataset_years_come_from_the_verified_slug_table():
    assert recent_hackathon_year("cal-hacks-12-0") == 2025 and recent_hackathon_year("hackgt-12") == 2025
    assert recent_hackathon_year("madhacks") == 2024 and recent_hackathon_year("pennapps-xxv") == 2024
    assert recent_hackathon_year("treehacks-2026") == 2026 and recent_hackathon_year("Hacktech-By-Caltech-2026 ") == 2026
    assert recent_hackathon_year("some-new-hack-2027") == 2027  # a year in the slug is trusted
    assert recent_hackathon_year("mystery-hack") is None and recent_hackathon_year(None) is None


# ---------------------------------------------------------------------------- sampling helpers
def test_language_gate_and_cleaning():
    english = ("We built this at 3am after the projector in our lecture hall died for the third time that week. It is held "
               "together with a Raspberry Pi, two zip ties and a servo that we pulled out of an old car, and it works.")
    spanish = ("Construimos esta aplicacion para ayudar a los estudiantes a encontrar companeros de estudio en su universidad. "
               "La aplicacion utiliza inteligencia artificial para emparejar a los usuarios segun sus horarios y materias.")
    assert looks_english(english) and not looks_english(spanish)
    assert not looks_english("你好" * 200) and not looks_english("") and not looks_english("too short to tell")
    assert clean_writeup("Inspiration\r\n\r\n\r\n\r\nWe  built\tit.  \n next line") == "Inspiration\n\nWe built it.\nnext line"
    assert clean_writeup(None) == ""


def test_winner_flag_from_the_prize_column():
    assert [is_winner_from_prize(p) for p in ("['1st Place']", "['Best Use of MongoDB Atlas', 'Wolfram Prize']", "[]", "", None, float("nan"))] == \
        [True, True, False, False, False, False]
    assert is_winner_from_prize(["x"]) and not is_winner_from_prize([]) and not is_winner_from_prize(np.array([]))


def test_sample_ids_are_stable_opaque_and_rank_is_independent():
    url = "https://devpost.com/software/devspot"
    assert sample_id_for(url) == sample_id_for(url.upper() + " ") and len(sample_id_for(url)) == 16
    assert "devspot" not in sample_id_for(url)
    assert sample_id_for(url, seed=1) != sample_id_for(url, seed=2)
    assert sample_rank(url)[:16] != sample_id_for(url)


def test_pilot_years():
    assert pick_pilot_years([2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026], (2019, 2023, 2024, 2026)) == [2019, 2023, 2024, 2026]
    assert len(pick_pilot_years([2018, 2019, 2021, 2022, 2023, 2024], (2019, 2023, 2024, 2026))) == 4
    assert pick_pilot_years([2023, 2024], (2019, 2023, 2024, 2026)) == [2023, 2024]


# ---------------------------------------------------------------------------- slop_index.json
def _rows() -> list[dict]:
    rng = np.random.default_rng(11)
    rows = []

    def add(year, cls, conf, sub=None, n=1, winner_every=0, nn=0.5):
        for i in range(n):
            rows.append({"sample_id": f"{year}-{cls}-{conf}-{len(rows)}", "year": year, "predicted_class": cls,
                         "confidence_category": conf, "subclass": sub, "ai_sentence_share": 0.0, "n_words": 280,
                         "is_winner": bool(winner_every and i % winner_every == 0), "model_version": "2025-11-28-base",
                         "nn_sim": float(rng.normal(nn, 0.02))})

    add(2018, "human", "high", n=48); add(2018, "human", "medium", n=1); add(2018, "ai", "high", "pure_ai", n=1)
    add(2021, "human", "high", n=49); add(2021, "mixed", "low", "polished", n=1)  # low confidence: never counted
    add(2024, "human", "high", n=30, winner_every=3, nn=0.50)
    add(2024, "ai", "high", "pure_ai", n=8, winner_every=8, nn=0.60); add(2024, "ai", "high", "ai_paraphrased", n=2, nn=0.60)
    add(2024, "mixed", "high", "polished", n=7, nn=0.60); add(2024, "mixed", "high", "concatenated", n=3, nn=0.60)
    return rows


def test_slop_index_has_exactly_the_shape_the_frontend_expects():
    out = analyze.build_slop_index(_rows(), now=dt.datetime(2026, 9, 19, 12, 0, tzinfo=dt.timezone.utc))
    assert set(out) == {"generated_at", "sample_data", "years", "placebo_fpr", "tie_in", "tie_in_by_year", "winners", "method"}
    assert out["generated_at"] == "2026-09-19T12:00:00+00:00" and out["sample_data"] is False

    assert [y["year"] for y in out["years"]] == [2018, 2021, 2024]
    for y in out["years"]:
        assert set(y) == {"year", "scanned", "ai_high", "mixed_high", "share", "ci_low", "ci_high", "by_subclass"}
        assert set(y["by_subclass"]) == {"pure_ai", "ai_paraphrased", "polished", "concatenated"}
        assert y["ci_low"] <= y["share"] <= y["ci_high"]
    y2024 = out["years"][2]
    assert (y2024["scanned"], y2024["ai_high"], y2024["mixed_high"], y2024["share"]) == (50, 10, 10, 0.4)
    assert y2024["by_subclass"] == {"pure_ai": 8, "ai_paraphrased": 2, "polished": 7, "concatenated": 3}
    assert (y2024["ci_low"], y2024["ci_high"]) == pytest.approx(wilson_ci(20, 50), abs=1e-4)
    assert out["years"][1]["share"] == 0.0 and out["years"][1]["by_subclass"]["polished"] == 0, "low confidence is not a flag"

    assert out["placebo_fpr"] == {"years": [2018, 2021], "flagged": 1, "scanned": 100, "rate": 0.01,
                                  "ci_low": pytest.approx(wilson_ci(1, 100)[0], abs=1e-4),
                                  "ci_high": pytest.approx(wilson_ci(1, 100)[1], abs=1e-4)}

    assert set(out["tie_in"]) == {"cliffs_delta", "p_value", "median_nn_sim_flagged", "median_nn_sim_human", "n_flagged", "n_human"}
    # 2024 separates cleanly (delta ~ 1 over 20 x 30 pairs); 2018's lone flagged row adds 48 pairs of pure noise
    assert out["tie_in"]["cliffs_delta"] > 0.8 and out["tie_in"]["p_value"] < 1e-6
    assert out["tie_in_by_year"][0]["cliffs_delta"] > 0.95
    assert out["tie_in"]["median_nn_sim_flagged"] > out["tie_in"]["median_nn_sim_human"]
    assert (out["tie_in"]["n_flagged"], out["tie_in"]["n_human"]) == (21, 78)  # only years that have both groups
    assert [t["year"] for t in out["tie_in_by_year"]] == [2024], "2018 has a single flagged write-up: too few for its own test"

    groups = {w["group"]: w for w in out["winners"]}
    assert set(groups) == {"human", "ai", "mixed", "flagged_high", "not_flagged"}
    assert groups["human"]["winners"] == 10 and groups["ai"]["winners"] == 1 and groups["flagged_high"]["scanned"] == 21
    assert isinstance(out["method"], dict) and out["method"]["n_scanned"] == 150
    import json

    json.dumps(out)  # must be plain JSON (no numpy scalars, no NaN)


def test_tie_in_is_null_without_nn_sim_and_synthetic_rows_are_flagged():
    rows = [{k: v for k, v in r.items() if k != "nn_sim"} for r in _rows()]
    out = analyze.build_slop_index(rows)
    assert out["tie_in"] is None and out["tie_in_by_year"] == []
    rows[0]["model_version"] = "replay-fixture"
    out = analyze.build_slop_index(rows)
    assert out["sample_data"] is True and out["method"]["n_synthetic"] == 1


def test_works_from_a_dataframe_with_missing_values():
    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame(_rows())
    frame.loc[frame.index[:5], "nn_sim"] = np.nan
    frame.loc[frame.index[:5], "subclass"] = None
    out = analyze.build_slop_index(frame)
    assert out["years"][2]["share"] == 0.4 and out["tie_in"] is not None


def test_public_export_carries_no_identifiers():
    assert PUBLIC_COLUMNS == ["year", "predicted_class", "confidence_category", "subclass", "nn_sim", "is_winner"]
    assert "sample_id" in SCAN_COLUMNS and "sample_id" not in PUBLIC_COLUMNS
    from investigation.export_public import public_rows

    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame(_rows())
    frame["project_url"] = "https://devpost.com/software/secret"
    rows = public_rows(frame)
    assert len(rows) == len(frame) and all(list(r) == PUBLIC_COLUMNS for r in rows)
    assert "secret" not in str(rows) and "2024-ai" not in str(rows)
    assert [r["year"] for r in rows] != sorted(r["year"] for r in rows), "rows are shuffled"
