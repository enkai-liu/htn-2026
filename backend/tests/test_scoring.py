"""Scoring invariants from docs/scoring.md: monotonicity, renormalised weights, abstention rules."""
import pytest

from app.schemas import AxisScore
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
