"""Pure maths + request bodies behind AXIS 1 (crowding percentile) and AXIS 2 (facet rarity). All offline."""
import json
import math

import pytest

from app.search import calibration, rarity, whitespace


# ---------------------------------------------------------------- rarity
def test_rarity_from_df_bounds_and_formula():
    assert rarity.rarity_from_df(0) == 1.0
    assert rarity.rarity_from_df(2000) == 0.0 and rarity.rarity_from_df(10**7) == 0.0  # clamped
    assert rarity.rarity_from_df(-5) == 1.0
    assert rarity.rarity_from_df(50) == pytest.approx(1 - math.log(51) / math.log(2001))
    assert rarity.rarity_from_df(50, cap=100) == pytest.approx(1 - math.log(51) / math.log(101))
    with pytest.raises(ValueError):
        rarity.rarity_from_df(1, cap=0)


def test_rarity_is_monotonically_decreasing():
    values = [rarity.rarity_from_df(df) for df in (0, 1, 3, 10, 50, 200, 1000, 2000)]
    assert values == sorted(values, reverse=True) and len(set(values)) == len(values)


def test_pair_rarity_saturates_earlier_than_a_single_facet():
    assert rarity.pair_rarity(0) == 1.0 and rarity.pair_rarity(200) == 0.0
    assert rarity.pair_rarity(3) == pytest.approx(1 - math.log(4) / math.log(201))
    assert rarity.pair_rarity(50) < rarity.rarity_from_df(50)


def test_idf_endpoints():
    assert rarity.idf(0, 8110) == pytest.approx(math.log(8111))  # never seen
    assert rarity.idf(8110, 8110) == pytest.approx(math.log(8111 / 8111))  # in every document -> 0
    assert rarity.idf(5, 0) == 0.0
    assert rarity.idf(-3, 100) == rarity.idf(0, 100)


def test_facet_rarity_from_idf_ignores_padding_with_common_words():
    """The bug this replaces: a 20-word mechanism matched 12.6% of the corpus under FACET_MATCH and scored
    0.089 -- a measurement of how long the phrase was. Here, words more common than the facet's k most
    distinctive ones cannot enter the top k, so an LLM's verbosity does not move the score at all."""
    n = 8110
    base = {"chatbot": 105, "large": 275, "language": 417}
    padded = {**base, "app": 3000, "using": 4000, "build": 2500, "project": 3100, "web": 1500}
    assert rarity.facet_rarity_from_idf(base, n) == rarity.facet_rarity_from_idf(padded, n)


def test_facet_rarity_from_idf_averages_what_is_there_below_k_terms():
    """A facet with fewer than k content words is the one case padding can move: with one term the 'top 3'
    is a mean of one. Real facets are phrases, so this is a documented edge, not the common path."""
    n = 8110
    one = rarity.facet_rarity_from_idf({"chatbot": 105}, n)
    three = rarity.facet_rarity_from_idf({"chatbot": 105, "team": 262, "build": 2500}, n)
    assert one > three  # the single distinctive term is no longer averaged with commoner company
    assert rarity.facet_rarity_from_idf({"chatbot": 105}, n, k=1) == one


def test_facet_rarity_from_idf_ranks_real_facets_correctly():
    """Measured against the 8.1k corpus; the ordering is the point, the exact values are the regression."""
    n = 8110
    varroa = rarity.facet_rarity_from_idf({"acoustic": 7, "detection": 900, "varroa": 0, "mite": 0, "beehive": 0}, n)
    agents = rarity.facet_rarity_from_idf({"novelty": 4, "pivot": 19, "debate": 22, "ai": 582, "team": 262}, n)
    react = rarity.facet_rarity_from_idf({"flask": 21, "frontend": 74, "react": 92, "web": 1500}, n)
    chatbot = rarity.facet_rarity_from_idf({"chatbot": 105, "large": 275, "language": 417, "model": 900}, n)
    study = rarity.facet_rarity_from_idf({"study": 160, "effectively": 275, "student": 329}, n)
    assert varroa == 1.0  # three terms the corpus has never seen
    assert varroa > agents > react > chatbot > study
    assert round(agents, 2) == 0.71  # was 0.089 under the document-count rule
    assert study < 0.45 and chatbot < 0.45  # cliches land where rarity.py's own comment says they should


def test_facet_rarity_from_idf_guards():
    assert rarity.facet_rarity_from_idf({}, 100) is None
    assert rarity.facet_rarity_from_idf({"a": 1}, 0) is None
    assert 0.0 <= rarity.facet_rarity_from_idf({"a": 5, "b": 9000}, 8110) <= 1.0


def test_term_df_body_is_one_bucket_per_term():
    body = rarity.build_term_df_body(["flask", "react", "flask"])  # duplicates collapse
    filters = body["aggs"]["term_df"]["filters"]["filters"]
    assert set(filters) == {"flask", "react"}
    assert filters["flask"] == {"match": {"pitch": "flask"}}
    assert body["size"] == 0 and body["query"]["bool"]["must_not"] == [rarity.excluded_flags_clause()]
    with pytest.raises(ValueError):
        rarity.build_term_df_body([])


def test_parse_term_df_response():
    resp = {"aggregations": {"term_df": {"buckets": {"flask": {"doc_count": 21}, "react": {"doc_count": 92}}}}}
    assert rarity.parse_term_df_response(resp) == {"flask": 21, "react": 92}
    assert rarity.parse_term_df_response({}) == {}


def test_npmi_separates_a_cliche_pairing_from_an_unusual_one():
    n = 200_000
    # "help students study" x "flashcards": 3,000 together, but independence predicts only 800 -> a cliche pairing
    cliche = rarity.npmi(df_a=20_000, df_b=8_000, df_ab=3_000, n=n)
    # "help students study" x "acoustic sensing": 3 together, independence predicts 80 -> genuinely unusual
    unusual = rarity.npmi(df_a=20_000, df_b=800, df_ab=3, n=n)
    assert cliche > 0 > unusual
    # the raw pair df cannot tell them apart in the same direction: it calls the rarer-than-chance pair
    # "rarer" only because 3 < 3000, and would say the same if the pair were 100x MORE common than chance
    assert rarity.pair_atypicality(unusual) > rarity.pair_atypicality(cliche)


def test_npmi_matches_the_formula():
    n, df_a, df_b, df_ab = 1000, 100, 200, 50
    p_ab = df_ab / n
    expected = math.log(p_ab / ((df_a / n) * (df_b / n))) / -math.log(p_ab)
    assert rarity.npmi(df_a, df_b, df_ab, n) == pytest.approx(expected)


def test_npmi_endpoints_and_degenerate_inputs():
    assert rarity.npmi(100, 200, 0, 1000) == -1.0  # never observed together
    assert rarity.npmi(1000, 1000, 1000, 1000) == 1.0  # every document matches both
    assert rarity.npmi(0, 0, 0, 1000) == -1.0  # neither facet exists in the corpus
    assert rarity.npmi(100, 200, 50, 0) is None  # corpus size unknown -> caller falls back to pair_rarity
    assert rarity.npmi(100, 200, 999, 1000) == rarity.npmi(100, 200, 100, 1000)  # joint clamped to the marginals
    assert -1.0 <= rarity.npmi(5, 7, 1, 10_000) <= 1.0


def test_npmi_is_zero_at_independence():
    # df_ab exactly equal to df_a * df_b / n
    assert rarity.npmi(df_a=100, df_b=200, df_ab=20, n=1000) == pytest.approx(0.0, abs=1e-12)


def test_npmi_is_monotone_in_the_joint_count():
    values = [rarity.npmi(1000, 1000, df, 100_000) for df in (1, 5, 20, 100, 500, 1000)]
    assert values == sorted(values) and len(set(values)) == len(values)


def test_pair_atypicality_maps_npmi_onto_the_rarity_scale():
    assert rarity.pair_atypicality(-1.0) == 1.0
    assert rarity.pair_atypicality(0.0) == 0.5
    assert rarity.pair_atypicality(1.0) == 0.0
    assert rarity.pair_atypicality(None) is None
    assert rarity.pair_atypicality(-7.0) == 1.0  # clamped


def test_corpus_count_body_excludes_the_same_documents_as_a_facet_count():
    body = rarity.build_corpus_count_body()
    assert body["query"]["bool"]["must_not"] == [rarity.excluded_flags_clause()]
    assert "must" not in body["query"]["bool"]  # no facet constraint: this is the denominator N
    scoped = rarity.build_corpus_count_body(["devpost", "yc"])
    assert scoped["query"]["bool"]["filter"] == [{"terms": {"source": ["devpost", "yc"]}}]


def test_cliche_overlap():
    idea = "AI flashcards for students studying from PDFs"
    assert rarity.idea_terms(idea) == {"flashcard", "student", "studying", "pdf"}
    assert rarity.cliche_overlap(idea, ["flashcard", "student", "quiz"]) == 0.5
    assert rarity.cliche_overlap(idea, []) == 0.0 and rarity.cliche_overlap("", ["x"]) == 0.0
    assert rarity.cliche_overlap(idea, ["flashcards", "students", "study", "pdf"]) == 1.0  # light stemming on both sides


def test_neighbourhood_body_is_the_two_step_significant_text():
    body = rarity.build_neighbourhood_body(["devpost:a", "devpost:b"])
    assert body["size"] == 0 and body["query"] == {"ids": {"values": ["devpost:a", "devpost:b"]}}
    aggs = body["aggs"]
    assert aggs["cliches"] == {"significant_text": {"field": "pitch", "size": 20, "min_doc_count": 3, "filter_duplicate_text": True}}
    assert aggs["tag_cliches"] == {"significant_terms": {"field": "tags", "size": 15, "min_doc_count": 3}}
    assert aggs["by_year"] == {"terms": {"field": "year", "size": 12, "order": {"_key": "asc"}}}
    assert aggs["winners"] == {"filter": {"term": {"is_winner": True}}}
    assert "background_filter" not in json.dumps(body)  # background = the whole index


def test_parse_neighbourhood_response():
    resp = {"hits": {"total": {"value": 50}}, "aggregations": {
        "cliches": {"buckets": [{"key": "flashcard", "doc_count": 12, "bg_count": 300, "score": 4.2}]},
        "tag_cliches": {"buckets": [{"key": "Education", "doc_count": 30, "bg_count": 9000, "score": 0.4}]},
        "tech_cliches": {"buckets": []},
        "by_year": {"buckets": [{"key": 2023, "doc_count": 9}, {"key": 2024, "doc_count": 31}]},
        "winners": {"doc_count": 7}}}
    out = rarity.parse_neighbourhood_response(resp)
    assert out["n"] == 50 and out["winners"] == 7
    assert out["cliche_terms"] == [{"term": "flashcard", "doc_count": 12, "bg_count": 300, "score": 4.2}]
    assert out["by_year"] == [{"year": 2023, "count": 9}, {"year": 2024, "count": 31}]
    assert rarity.parse_neighbourhood_response({}) == {"n": 0, "cliche_terms": [], "tag_cliches": [], "tech_cliches": [],
                                                       "by_year": [], "winners": 0}


class FakeES:
    def __init__(self, count=0, search=None):
        self._count, self._search, self.calls = count, search or {}, []

    async def count(self, *, index, body):
        self.calls.append(("count", index, body))
        return {"count": self._count}

    async def search(self, *, index, body, **kw):
        self.calls.append(("search", index, body))
        return self._search


async def test_facet_and_pair_df_use_count_with_graded_match():
    fake = FakeES(count=42)
    assert await rarity.facet_df("sign language", es=fake, index="i") == 42
    assert await rarity.pair_df("sign language", "smart glasses", sources=["devpost"], es=fake, index="i") == 42
    (_, _, single), (_, _, pair) = fake.calls
    assert single["query"]["bool"]["must"] == [{"match": {"pitch": {"query": "sign language", "minimum_should_match": rarity.FACET_MATCH}}}]
    assert [m["match"]["pitch"]["query"] for m in pair["query"]["bool"]["must"]] == ["sign language", "smart glasses"]
    assert all(m["match"]["pitch"]["minimum_should_match"] == "2<-50% 6<3" for m in pair["query"]["bool"]["must"])
    assert pair["query"]["bool"]["filter"] == [{"terms": {"source": ["devpost"]}}]
    assert {"terms": {"quality_flags": ["too_short", "non_english"]}} in single["query"]["bool"]["must_not"]
    with pytest.raises(ValueError):
        rarity.build_facet_count_body("  ")


async def test_neighbourhood_stats_short_circuits_on_no_ids():
    fake = FakeES()
    assert (await rarity.neighbourhood_stats([], es=fake))["n"] == 0 and fake.calls == []
    fake = FakeES(search={"hits": {"total": {"value": 2}}, "aggregations": {"winners": {"doc_count": 1}}})
    out = await rarity.neighbourhood_stats(["a", "b"], es=fake, index="i")
    assert out["n"] == 2 and out["winners"] == 1 and fake.calls[0][2]["query"] == {"ids": {"values": ["a", "b"]}}


# ---------------------------------------------------------------- calibration
def test_crowding_lite_formula():
    scores = [0.2, 0.9, None, 0.8, 0.7, 0.1, 0.05]
    assert calibration.crowding_lite(scores) == pytest.approx(0.6 * 0.9 + 0.4 * (0.9 + 0.8 + 0.7 + 0.2 + 0.1) / 5)
    assert calibration.crowding_lite([0.5]) == pytest.approx(0.5)
    assert calibration.crowding_lite([]) == 0.0 and calibration.crowding_lite([None]) == 0.0


def test_placeholder_cdf_is_labelled_and_monotone():
    cdf = calibration.placeholder_cdf()
    assert cdf.is_placeholder is True and "PLACEHOLDER" in cdf.meta["note"] and len(cdf.values) == 300
    assert cdf.values == sorted(cdf.values)
    pcts = [cdf.percentile(v) for v in (-1.0, 0.1, 0.3, 0.5, 0.7, 0.9, 5.0)]
    # never exactly 1.0 any more: O1 = 100*(1 - pct) feeds a logarithm, and the fitted tail keeps resolving
    # above the largest calibration value instead of flattening onto it
    assert pcts == sorted(pcts) and pcts[0] == 0.0 and 0.999 < pcts[-1] < 1.0
    assert cdf.empirical(5.0) == 1.0  # the raw empirical CDF still saturates, as it must


def test_percentile_is_mid_rank():
    cdf = calibration.CrowdingCDF([0.2, 0.4, 0.4, 0.8])
    assert cdf.percentile(0.1) == 0.0 and cdf.percentile(0.3) == 0.25 and cdf.percentile(0.4) == 0.5 and cdf.percentile(0.9) == 1.0
    with pytest.raises(ValueError):
        calibration.CrowdingCDF([])


def test_measured_cdf_roundtrip_and_corrupt_file_fallback(tmp_path):
    path = tmp_path / "crowding_cdf.json"
    measured = calibration.CrowdingCDF([0.3, 0.1, 0.2], meta={"rerank_inference_id": "r", "index": "prior-art-v1"})
    path.write_text(json.dumps(measured.to_json()))
    loaded = calibration.load_cdf(path)
    assert loaded.is_placeholder is False and loaded.values == [0.1, 0.2, 0.3] and loaded.meta["rerank_inference_id"] == "r"
    path.write_text("{not json")
    assert calibration.load_cdf(path).is_placeholder is True
    assert calibration.load_cdf(tmp_path / "missing.json").is_placeholder is True


def test_module_level_percentile_works_before_calibration(monkeypatch):
    monkeypatch.setattr(calibration, "_cdf", calibration.placeholder_cdf())
    assert 0.0 <= calibration.percentile(0.5) <= 1.0 and calibration.is_placeholder() is True


def test_calibration_sample_body_only_draws_searchable_semantic_docs():
    q = calibration.build_sample_body(300, 42)
    fs = q["query"]["function_score"]
    assert q["size"] == 300 and fs["random_score"] == {"seed": 42, "field": "_seq_no"}
    assert {"term": {"has_semantic": True}} in fs["query"]["bool"]["filter"]


# ---------------------------------------------------------------- whitespace
def test_whitespace_candidates_rule():
    glob = {"python": 9000, "unity": 700, "arduino": 650, "rust": 300, "react": 8000}
    local = {"python": 80, "react": 40, "unity": 1}
    out = whitespace.whitespace_candidates(glob, local)
    assert out == [{"term": "unity", "global_count": 700, "neighbourhood_count": 1},
                   {"term": "arduino", "global_count": 650, "neighbourhood_count": 0}]  # rust is below the global bar
    assert whitespace.whitespace_candidates(glob, local, max_local=0) == out[1:]
    assert [c["term"] for c in whitespace.whitespace_candidates(glob, local, min_global=100)] == ["unity", "arduino", "rust"]


def test_effective_min_global_scales_down_for_a_partial_corpus():
    assert whitespace.effective_min_global(262_000) == 500 and whitespace.effective_min_global(150_000) == 500
    assert whitespace.effective_min_global(8_500) == 25 and whitespace.effective_min_global(40_000) == 76


def test_whitespace_bodies():
    g = whitespace.build_global_terms_body()
    assert g["size"] == 0 and g["aggs"]["tech"] == {"terms": {"field": "tech", "size": 150}} and "tags" in g["aggs"]
    n = whitespace.build_neighbour_ids_body("help students study")
    assert n["size"] == 200 and n["_source"] is False and list(n["retriever"]) == ["rrf"]  # purpose-only, no reranker
    assert n["retriever"]["rrf"]["rank_window_size"] == 200
    t = whitespace.build_terms_over_ids_body(["a"], include={"tech": ["unity", "rust"], "tags": []})
    assert t["query"] == {"ids": {"values": ["a"]}} and t["aggs"]["tech"]["terms"]["include"] == ["unity", "rust"]


async def test_find_whitespace_end_to_end_with_a_fake_client():
    whitespace.clear_cache()

    class ES:
        def __init__(self):
            self.n = 0

        async def search(self, *, index, body, **kw):
            self.n += 1
            if "retriever" in body:
                return {"hits": {"hits": [{"_id": f"devpost:{i}"} for i in range(200)]}}
            if "ids" in body.get("query", {}):
                return {"aggregations": {"tech": {"buckets": [{"key": "python", "doc_count": 150}]}, "tags": {"buckets": []}}}
            return {"hits": {"total": {"value": 262_000}}, "aggregations": {
                "tech": {"buckets": [{"key": "python", "doc_count": 90_000}, {"key": "arduino", "doc_count": 4_000}]},
                "tags": {"buckets": [{"key": "Health", "doc_count": 12_000}]}}}

    es = ES()
    out = await whitespace.find_whitespace("help students study", es=es, index="i")
    assert out["neighbourhood_size"] == 200 and out["min_global"] == 500
    assert [c["term"] for c in out["tech"]] == ["arduino"] and [c["term"] for c in out["tags"]] == ["Health"]
    await whitespace.find_whitespace("another purpose", es=es, index="i")
    assert es.n == 5  # the global top terms were served from the cache the second time
    whitespace.clear_cache()
