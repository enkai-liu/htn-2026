"""Scoring invariants from docs/scoring.md: monotonicity, renormalised weights, abstention rules."""
import pytest

from app.schemas import Abstain, AxisScore
from app.scoring import axes
from app.scoring.similarity import lexical_cosine
from app.wrangle.blocking import candidate_pairs, name_sim, norm_name, norm_url
from app.wrangle.schema_map import from_github, from_hn


def test_crowding_is_monotone_in_similarity():
    scores = [axes.crowding([s] * 5).score for s in (0.1, 0.3, 0.5, 0.7, 0.9)]
    assert scores == sorted(scores, reverse=True)  # more similar neighbours -> less original
    assert axes.crowding([]).score is None  # nothing retrieved -> abstain, never "100% original"


def test_one_close_neighbour_matters_more_than_many_distant_ones():
    assert axes.crowding([0.95, 0.1, 0.1, 0.1, 0.1]).score < axes.crowding([0.4] * 5).score


def _boot(**kw) -> axes.BootstrapInputs:
    base = dict(sims=[0.62, 0.55, 0.51, 0.48, 0.44, 0.40, 0.38, 0.35, 0.31, 0.28],
                corpus_n=8110,
                facet_term_dfs={"purpose": {"originality": 40, "idea": 900, "assess": 300},
                                "mechanism": {"novelty": 4, "pivot": 19, "debate": 22, "ai": 582}},
                pair=(22, 1020, 9), cliche_overlap=0.1,
                prior_sims=[0.59, 0.52, 0.48, 0.44, 0.41, 0.39, 0.37, 0.35, 0.33, 0.31, 0.29, 0.27])
    base.update(kw)
    return axes.BootstrapInputs(**base)


def _reference(values):
    """A CDF over a reference population's composite scores, as `calibration.headline_percentile` is."""
    import bisect

    vs = sorted(values)
    return lambda x: (bisect.bisect_left(vs, x) + bisect.bisect_right(vs, x)) / (2 * len(vs))


def test_percentile_rank_is_a_share_of_the_reference_population():
    ref = _reference([float(i) for i in range(100)])  # composites 0..99
    live = {"crowding": 40.0, "facet_rarity": 80.0, "llm_predictability": 60.0}
    raw = axes.rank_composite(live)
    assert axes.percentile_rank(live, ref) == pytest.approx(100 * ref(raw))
    # llm_predictability is NOT in the rank: the reference population is not scored on it
    assert axes.rank_composite(live) == axes.rank_composite({k: v for k, v in live.items() if k in axes.RANK_AXES})
    assert axes.percentile_rank(live, None) is None  # no reference -> no rank, never a guess
    assert axes.rank_composite({"facet_rarity": 50.0}) is None  # crowding is still mandatory


def test_percentile_rank_is_monotone_and_bounded():
    ref = _reference([float(i) for i in range(100)])
    ranks = [axes.percentile_rank({"crowding": c, "facet_rarity": 50.0}, ref) for c in (5, 20, 40, 70, 95)]
    assert ranks == sorted(ranks)
    assert all(0.0 <= r <= 100.0 for r in ranks)


def test_bootstrap_band_replaces_the_invented_formula():
    out = axes.bootstrap_headline(_boot(), b=400)
    assert out is not None
    assert 0 < out.low < out.high < 100
    assert out.diagnostics["replicates"] == 400
    assert set(out.diagnostics["resampled"]) == {"neighbours", "facet_dfs", "model_samples"}
    assert out.rank_low is None and out.rank_high is None  # no reference population supplied


def test_bootstrap_reports_a_rank_interval_when_a_reference_exists():
    ref = _reference([float(i) for i in range(100)])
    out = axes.bootstrap_headline(_boot(rank_reference=ref), b=400)
    assert out.rank_low is not None and out.rank_low < out.rank_high
    assert 0 <= out.rank_low and out.rank_high <= 100


def test_rank_interval_widens_with_the_reference_populations_own_dkw_error():
    ref = _reference([float(i) for i in range(100)])
    tight = axes.bootstrap_headline(_boot(rank_reference=ref, rank_dkw=0.0), b=400)
    loose = axes.bootstrap_headline(_boot(rank_reference=ref, rank_dkw=0.078), b=400)
    assert (loose.rank_high - loose.rank_low) > (tight.rank_high - tight.rank_low)


def test_bootstrap_band_is_deterministic_for_a_given_seed():
    a = axes.bootstrap_headline(_boot(), b=200, seed=5)
    b = axes.bootstrap_headline(_boot(), b=200, seed=5)
    assert (a.low, a.high) == (b.low, b.high)


def test_bootstrap_band_widens_with_calibration_error():
    """DKW says a 300-point CDF is worth +-0.078 on ANY percentile; that has to reach the interval."""
    tight = axes.bootstrap_headline(_boot(dkw=0.0), b=400)
    loose = axes.bootstrap_headline(_boot(dkw=0.078), b=400)
    assert (loose.high - loose.low) > (tight.high - tight.low)


def test_bootstrap_band_widens_with_a_noisier_neighbourhood():
    """crowding_lite leans on max(r) over ten retrieved documents, so a spread-out neighbourhood is
    genuinely less certain than a tight one, and the interval should say so."""
    tight = axes.bootstrap_headline(_boot(sims=[0.50] * 10), b=400)
    spread = axes.bootstrap_headline(_boot(sims=[0.95, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2]), b=400)
    assert (spread.high - spread.low) > (tight.high - tight.low)


def test_bootstrap_band_needs_a_neighbourhood():
    assert axes.bootstrap_headline(_boot(sims=[])) is None
    assert not axes.BootstrapInputs().usable


def test_assemble_reports_an_asymmetric_interval_when_it_can():
    crowd, rar, pred = AxisScore(score=3.0), AxisScore(score=56.0), AxisScore(score=71.0)
    s = axes.assemble(crowd, rar, pred, jury_std=0.05, conf=0.8, abstain=Abstain(active=False), boot=_boot())
    assert s.low is not None and s.high is not None
    assert s.low < s.high
    # the geometric mean is not symmetric down here, which is exactly why `headline +- band` was wrong
    assert abs((s.high - s.headline) - (s.headline - s.low)) > 0.5
    assert s.band == pytest.approx((s.high - s.low) / 2, abs=0.05)


def test_assemble_without_bootstrap_inputs_keeps_the_legacy_band():
    crowd, rar, pred = AxisScore(score=40.0), AxisScore(score=80.0), AxisScore(score=60.0)
    s = axes.assemble(crowd, rar, pred, jury_std=0.05, conf=0.8, abstain=Abstain(active=False))
    assert s.low is None and s.high is None and s.band == 10.0


def test_assemble_reports_the_rank_when_a_reference_exists():
    ref = _reference([float(i) for i in range(100)])
    crowd, rar, pred = AxisScore(score=3.0), AxisScore(score=56.0), AxisScore(score=71.0)
    s = axes.assemble(crowd, rar, pred, jury_std=0.05, conf=0.8, abstain=Abstain(active=False),
                      boot=_boot(rank_reference=ref, rank_dkw=0.078))
    assert s.rank is not None and 0 <= s.rank <= 100
    assert s.rank_low is not None and s.rank_low <= s.rank_high
    assert s.rank_axes == list(axes.RANK_AXES)  # the rank says which axes it is over
    assert s.headline is not None  # the raw composite is still there underneath


def test_assemble_has_no_rank_without_a_reference_population():
    crowd, rar, pred = AxisScore(score=3.0), AxisScore(score=56.0), AxisScore(score=71.0)
    s = axes.assemble(crowd, rar, pred, jury_std=0.05, conf=0.8, abstain=Abstain(active=False), boot=_boot())
    assert s.rank is None and s.rank_axes == []  # abstain rather than invent a percentile


def test_assemble_drops_the_interval_when_it_abstains():
    crowd, rar, pred = AxisScore(score=3.0), AxisScore(score=56.0), AxisScore(score=71.0)
    s = axes.assemble(crowd, rar, pred, jury_std=0.05, conf=0.2,
                      abstain=Abstain(active=True, reason="thin"), boot=_boot())
    assert (s.headline, s.band, s.low, s.high, s.rank, s.rank_low) == (None,) * 6


def test_crowding_fuses_the_two_instruments_on_the_percentile_scale():
    sims = [0.5] * 5
    rerank_only = axes.crowding(sims)
    both = axes.crowding(sims, rcs=1.2)
    assert rerank_only.detail["instruments"] == ["rerank"] and both.detail["instruments"] == ["rcs", "rerank"]
    assert "Single instrument" in rerank_only.note and "Single instrument" not in both.note
    assert both.detail["rcs_nats_per_token"] == 1.2
    # the fused percentile is the mean of the two
    assert both.detail["percentile"] == pytest.approx(
        (rerank_only.detail["percentile"] + both.detail["percentiles"]["rcs"]) / 2, abs=5e-4)


def test_crowding_falls_when_the_prior_art_explains_more_of_the_pitch():
    sims = [0.5] * 5
    scores = [axes.crowding(sims, rcs=r).score for r in (0.1, 0.5, 1.0, 1.5)]
    assert scores == sorted(scores, reverse=True)  # more nats saved by the neighbours -> less original


def test_crowding_still_abstains_with_no_prior_art_even_if_surprisal_answered():
    assert axes.crowding([], rcs=1.4).score is None


def test_facet_rarity_prefers_npmi_and_falls_back_to_the_pair_df():
    dfs = {"purpose": 20_000, "mechanism": 8_000}
    cliche_pair = axes.facet_rarity(dfs, pair_df=3_000, cliche_overlap=0.2, pair_npmi=0.31, pair_expected=800)
    unusual_pair = axes.facet_rarity(dfs, pair_df=3, cliche_overlap=0.2, pair_npmi=-0.72, pair_expected=80)
    assert unusual_pair.score > cliche_pair.score
    assert cliche_pair.detail["pair_measure"] == "npmi" and cliche_pair.detail["pair_npmi"] == 0.31
    assert "independence predicts 800" in cliche_pair.note
    fallback = axes.facet_rarity(dfs, pair_df=3_000, cliche_overlap=0.2)
    assert fallback.detail["pair_measure"] == "df" and "pair_npmi" not in fallback.detail


def test_facet_rarity_pair_term_is_monotone_in_npmi():
    dfs = {"purpose": 500, "mechanism": 500}
    scores = [axes.facet_rarity(dfs, pair_df=10, cliche_overlap=0.0, pair_npmi=v).score
              for v in (1.0, 0.5, 0.0, -0.5, -1.0)]
    assert scores == sorted(scores) and len(set(scores)) == 5


def test_facet_rarity_monotone_and_abstains_without_corpus():
    common = axes.facet_rarity({"purpose": 1500, "mechanism": 1200}, pair_df=150, cliche_overlap=0.5).score
    rare = axes.facet_rarity({"purpose": 1500, "mechanism": 3}, pair_df=0, cliche_overlap=0.1).score
    assert rare > common
    assert axes.facet_rarity(None, None, None).score is None
    assert axes.rarity_from_df(0) == 1.0 and axes.rarity_from_df(10**6) == 0.0


def test_llm_predictability():
    predictable = axes.llm_predictability([{"model": "a", "similarity": 0.92}, {"model": "b", "similarity": 0.88}]).score
    surprising = axes.llm_predictability([{"model": "a", "similarity": 0.35}, {"model": "b", "similarity": 0.30}]).score
    assert surprising > predictable
    assert axes.llm_predictability([]).score is None
    assert "Uncalibrated" in axes.llm_predictability([{"model": "a", "similarity": 0.5, "uncalibrated": True}]).note


def test_headline_needs_crowding_and_renormalises_weights():
    crowd, rar, pred = AxisScore(score=40), AxisScore(score=80), AxisScore(score=60)
    none = AxisScore(score=None)
    full, band_full = axes.headline({"crowding": crowd, "facet_rarity": rar, "llm_predictability": pred}, jury_std=0.05)
    partial, band_partial = axes.headline({"crowding": crowd, "facet_rarity": none, "llm_predictability": none}, jury_std=0.05)
    assert 40 < full < 80 and partial == 40.0  # with one axis the geometric mean is that axis
    assert band_partial > band_full  # abstaining axes widen the uncertainty band
    assert axes.headline({"crowding": none, "facet_rarity": rar, "llm_predictability": pred}, jury_std=0.0) == (None, None)
    wide, _ = axes.headline({"crowding": crowd, "facet_rarity": rar, "llm_predictability": pred}, jury_std=0.3), None
    assert wide[1] > band_full  # a split jury widens the band


def test_abstention_rules():
    assert axes.decide_abstain(coverage=0.9, corpus_ok=False, conf=0.9, missing=["devpost skipped"]).active
    assert axes.decide_abstain(coverage=0.4, corpus_ok=True, conf=0.9, missing=[]).active
    low = axes.decide_abstain(coverage=0.9, corpus_ok=True, conf=0.3, missing=[])
    assert low.active and "confidence" in low.reason.lower()
    assert not axes.decide_abstain(coverage=0.9, corpus_ok=True, conf=0.8, missing=[]).active
    scores = axes.assemble(AxisScore(score=50), AxisScore(score=50), AxisScore(score=50), jury_std=0.0, conf=0.3,
                           abstain=axes.decide_abstain(coverage=0.9, corpus_ok=True, conf=0.3, missing=[]))
    assert scores.headline is None and scores.crowding.score == 50  # axes still shown, headline withheld


def test_confidence_components():
    best = axes.confidence(coverage=1, jury_std=0, verified_share=1, canary_pass=1)
    assert best == pytest.approx(1.0)
    assert axes.confidence(coverage=1, jury_std=0.35, verified_share=1, canary_pass=1) == pytest.approx(0.75)
    assert axes.confidence(coverage=0.5, jury_std=0, verified_share=1, canary_pass=1) < best


def test_blocking_and_name_normalisation():
    assert norm_url("https://www.GitHub.com/Acme/IdeaRadar.git/") == "github.com/acme/idearadar"
    assert norm_url("https://github.com") is None  # generic hosts without a path are not identifying
    assert norm_name("Show HN: IdeaRadar – find out if your idea exists") == "idearadar"
    assert norm_name("acme/idearadar") == "idearadar"
    assert norm_name("A/B testing for hackathons") != "btestingforhackathons"  # a slash in prose is not owner/repo
    assert name_sim("IdeaRadar", "acme/idearadar") == 1.0
    gh = from_github({"full_name": "acme/idearadar", "name": "idearadar", "html_url": "https://github.com/acme/idearadar",
                      "homepage": "https://idearadar.example.org", "description": "x", "created_at": "2023-01-01T00:00:00Z",
                      "pushed_at": "2023-02-01T00:00:00Z"})
    hn = from_hn({"objectID": "1", "title": "Show HN: Something else entirely", "url": "https://idearadar.example.org/", "created_at": "2025-01-01T00:00:00Z"})
    pairs = candidate_pairs([gh, hn])
    assert len(pairs) == 1 and pairs[0][2]["url_xref"] is True  # different names, same homepage -> candidate by URL
    assert gh.field_provenance["status"] == "imputed" and gh.status == "dormant"


def test_lexical_fallback_orders_sensibly():
    idea = "check whether a hackathon idea already exists by searching past projects"
    assert lexical_cosine(idea, "search past hackathon projects to see if your idea exists") > lexical_cosine(idea, "a recipe app for your fridge")
