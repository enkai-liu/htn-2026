"""Hybrid query body (design 2.3), hit -> SourceRecord mapping and the degradation ladder. All offline."""
import datetime as dt
import json
from pathlib import Path

import pytest

from app.config import Settings
from app.search import es as es_mod
from app.search import hybrid

REPO_ROOT = Path(__file__).resolve().parents[2]
Q, IDEA = "validate hackathon idea originality", "A tool that checks how original a hackathon idea is against past Devpost projects."


def body(**kw):
    kw.setdefault("rerank_inference_id", "my-reranker")
    return hybrid.build_hybrid_body(Q, IDEA, **kw)


def test_default_shape_is_reranker_over_rrf_over_bm25_and_semantic():
    b = body()
    rr = b["retriever"]["text_similarity_reranker"]
    assert rr["field"] == "pitch" and rr["inference_text"] == IDEA and rr["rank_window_size"] == 40
    assert rr["inference_id"] == "my-reranker"
    rrf = rr["retriever"]["rrf"]
    assert (rrf["rank_window_size"], rrf["rank_constant"]) == (100, 20)
    lexical, semantic = rrf["retrievers"]
    assert lexical["standard"]["query"]["multi_match"] == {"query": Q, "fields": ["title^3", "tagline^2", "pitch"]}
    assert semantic["standard"]["query"]["semantic"] == {"field": "semantic_pitch", "query": Q}
    assert rrf["filter"] == {"bool": {"must_not": [{"terms": {"quality_flags": ["too_short", "non_english"]}}]}}
    assert b["size"] == 25
    for f in ("rid", "source", "title", "tagline", "url", "year", "tags", "tech", "is_winner", "status", "dedupe_key",
              "gptzero", "hackathon", "pitch", "links"):
        assert f in b["_source"]
    assert "description" not in b["_source"] and "semantic_pitch" not in b["_source"]
    # retrievers forbid these top-level keys
    assert not {"query", "knn", "sort", "rescore", "search_after"} & set(b)


def test_inference_id_comes_from_settings_not_from_code(monkeypatch):
    monkeypatch.setattr(hybrid, "get_settings", lambda: Settings(_env_file=None, es_rerank_inference_id=".jina-reranker-v2-base-multilingual"))
    b = hybrid.build_hybrid_body(Q, IDEA)
    assert b["retriever"]["text_similarity_reranker"]["inference_id"] == ".jina-reranker-v2-base-multilingual"
    source = (REPO_ROOT / "backend" / "app" / "search" / "hybrid.py").read_text()
    assert ".jina-" not in source


def test_filters_exclude_ids_sources_first_seen_after():
    after = dt.datetime(2026, 9, 19, 8, 0, tzinfo=dt.timezone.utc)
    b = body(exclude_ids=["devpost:devspot"], sources=["devpost", "yc"], first_seen_after=after)
    f = b["retriever"]["text_similarity_reranker"]["retriever"]["rrf"]["filter"]["bool"]
    assert {"ids": {"values": ["devpost:devspot"]}} in f["must_not"]
    assert {"terms": {"source": ["devpost", "yc"]}} in f["filter"]
    assert {"range": {"first_seen_at": {"gt": "2026-09-19T08:00:00+00:00"}}} in f["filter"]


def test_rerank_false_is_rrf_only_and_semantic_false_is_bm25_only():
    rrf_only = body(rerank=False)
    assert list(rrf_only["retriever"]) == ["rrf"] and "my-reranker" not in json.dumps(rrf_only)
    assert rrf_only["retriever"]["rrf"] == body()["retriever"]["text_similarity_reranker"]["retriever"]["rrf"]
    bm25 = body(rerank=False, semantic=False, exclude_ids=["x"])
    assert list(bm25["retriever"]) == ["standard"] and "semantic" not in json.dumps(bm25)
    assert {"ids": {"values": ["x"]}} in bm25["retriever"]["standard"]["filter"]["bool"]["must_not"]


def test_windows_grow_with_size_and_idea_text_is_capped():
    b = body(size=120)
    rr = b["retriever"]["text_similarity_reranker"]
    assert rr["rank_window_size"] == 120 and rr["retriever"]["rrf"]["rank_window_size"] == 120
    long = hybrid.build_hybrid_body(Q, "x" * 10_000, rerank_inference_id="r")
    assert len(long["retriever"]["text_similarity_reranker"]["inference_text"]) == hybrid.IDEA_TEXT_CAP


def test_python_builder_matches_the_committed_query_template():
    import jinja2

    tpl = jinja2.Template((REPO_ROOT / "elastic" / "queries" / "hybrid.json.j2").read_text())
    idea = 'An "AI" <study buddy> & more\nsecond line'
    rendered = json.loads(tpl.render(q=Q, idea_full=idea, exclude_ids=["devpost:a"], rerank_id="my-reranker", size=25,
                                     source_fields=hybrid.SOURCE_FIELDS))
    assert rendered == hybrid.build_hybrid_body(Q, idea, exclude_ids=["devpost:a"], rerank_inference_id="my-reranker")


HIT = {
    "_id": "devpost:devspot", "_score": 0.8123, "_index": "prior-art-v1",
    "_source": {
        "rid": "devpost:devspot", "source": "devpost", "title": "DevSpot", "tagline": "Validate ideas", "pitch": "DevSpot. Validate ideas.",
        "url": "https://devpost.com/software/devspot", "year": 2024, "date": "2024-03-17", "date_precision": "inferred",
        "tags": "Education", "tech": ["flask", "react"], "links": ["https://github.com/kartikey-onlineGOD/DevSpot"],
        "is_winner": True, "hackathon": "HackPSU Spring 2024", "status": "unknown", "dedupe_key": "abc", "lang": "en",
        "traction": {"team_size": 1}, "field_provenance": {"year": "normalized", "bogus": "guessed"},
        "gptzero": {"predicted_class": "ai", "confidence_category": "high", "ai_sentence_share": 0.7},
    },
}


def test_hit_to_record():
    rec = hybrid.hit_to_record(HIT, query=Q, rank=1, reranked=True)
    assert rec.rid == "devpost:devspot" and rec.year == 2024 and rec.date == dt.date(2024, 3, 17)
    assert rec.tags == ["Education"]  # a single keyword value comes back as a scalar
    assert rec.traction == {"team_size": 1, "is_winner": True, "hackathon": "HackPSU Spring 2024"}
    assert rec.links == ["https://github.com/kartikey-onlineGOD/DevSpot"]
    assert rec.gptzero.predicted_class == "ai" and rec.gptzero.confidence_category == "high"
    assert rec.field_provenance == {"year": "normalized"}
    r = rec.retrieval
    assert (r["query"], r["leg"], r["rank"], r["rerank_score"], r["dedupe_key"]) == (Q, "hybrid", 1, 0.8123, "abc")
    # RRF-only scores are not reranker scores; malformed stored fields never raise
    loose = hybrid.hit_to_record({"_id": "x:1", "_score": 0.03, "_source": {"source": "nope", "status": "??", "date": "garbage",
                                                                           "gptzero": {"predicted_class": "robot"}}},
                                 query=Q, rank=2, reranked=False)
    assert loose.rid == "x:1" and loose.source == "web" and loose.status == "unknown" and loose.date is None and loose.gptzero is None
    assert loose.retrieval["rerank_score"] is None and loose.retrieval["score"] == 0.03


class FakeES:
    """Async client double: fails while `fail(body)` is true, otherwise returns one hit."""

    def __init__(self, fail):
        self.fail, self.bodies = fail, []

    async def search(self, *, index, body, **kw):
        self.bodies.append(body)
        if self.fail(body):
            raise RuntimeError("inference endpoint unavailable (429)")
        return {"hits": {"hits": [HIT]}}


async def test_search_happy_path_is_calibrated():
    fake = FakeES(lambda b: False)
    recs = await hybrid.search(Q, IDEA, size=5, es=fake, index="prior-art-v1")
    assert len(fake.bodies) == 1 and "text_similarity_reranker" in fake.bodies[0]["retriever"]
    assert recs[0].retrieval["rerank_score"] == 0.8123 and "uncalibrated" not in recs[0].retrieval
    assert recs[0].retrieval["leg"] == "hybrid" and recs[0].retrieval["rank"] == 1


async def test_reranker_failure_retries_once_without_rerank_and_flags_uncalibrated():
    fake = FakeES(lambda b: "text_similarity_reranker" in b["retriever"])
    recs = await hybrid.search(Q, IDEA, es=fake, index="i")
    assert [list(b["retriever"])[0] for b in fake.bodies] == ["text_similarity_reranker", "rrf"]
    r = recs[0].retrieval
    assert r["uncalibrated"] is True and r["rerank_score"] is None and r["score"] == 0.8123
    assert "inference endpoint unavailable" in r["degraded_reason"]


async def test_semantic_failure_falls_back_to_bm25_then_raises_when_everything_fails():
    fake = FakeES(lambda b: "standard" not in b["retriever"])
    recs = await hybrid.search(Q, IDEA, es=fake, index="i")
    assert [list(b["retriever"])[0] for b in fake.bodies] == ["text_similarity_reranker", "rrf", "standard"]
    assert recs[0].retrieval["degraded"] == "bm25_only" and recs[0].retrieval["uncalibrated"] is True
    with pytest.raises(RuntimeError, match="unavailable"):
        await hybrid.search(Q, IDEA, es=FakeES(lambda b: True), index="i")


async def test_search_without_credentials_fails_with_a_clear_message(monkeypatch):
    monkeypatch.setattr(es_mod, "get_settings", lambda: Settings(_env_file=None, es_url="", es_api_key=""))
    with pytest.raises(es_mod.ElasticNotConfigured, match="ES_URL and ES_API_KEY"):
        await hybrid.search(Q, IDEA)


async def test_search_union_keeps_the_best_copy_per_project(monkeypatch):
    def rec(rid, score, dedupe=None):
        h = {"_id": rid, "_score": score, "_source": {"rid": rid, "source": "devpost", "title": rid, "url": "u", "dedupe_key": dedupe}}
        return hybrid.hit_to_record(h, query="q", rank=1, reranked=True)

    batches = {"full": [rec("devpost:a", 0.4), rec("devpost:b", 0.9, "k1")], "twist": [rec("devpost:a", 0.7), rec("devpost:b2", 0.5, "k1")]}

    async def fake_search(q, idea_full, **kw):
        return batches[q]

    monkeypatch.setattr(hybrid, "search", fake_search)
    merged = await hybrid.search_union(["full", "twist"], IDEA)
    assert [(r.rid, r.retrieval["rerank_score"]) for r in merged] == [("devpost:b", 0.9), ("devpost:a", 0.7)]
    assert [r.retrieval["union_rank"] for r in merged] == [1, 2]
