"""A reader's grade is a floor under the reranker's score: it can lift a hit the reranker read too literally, never lower one."""
from __future__ import annotations

import asyncio

from test_scout_partial import FakeCtx

from app.llm import router as router_mod
from app.llm.router import LLMResult, LLMUnavailable
from app.roles.scouts import base as scout_base
from app.roles.scouts.base import ScoutRole
from app.scoring.similarity import GRADE_PERCENTILE, graded
from app.search.calibration import get_cdf
from app.wrangle.schema_map import from_web


def floor(grade: str) -> float:
    values = get_cdf().values
    return values[round(GRADE_PERCENTILE[grade] * (len(values) - 1))]


def test_a_grade_is_a_floor_on_the_rerankers_scale():
    assert graded(-0.05, "same") > graded(-0.05, "close") > graded(-0.05, "adjacent") == 0.0  # Groq for "ai chipmaker": -0.05
    assert graded(0.05, "same") > graded(-0.05, "same") >= floor("same") - 0.05  # graded hits still rank among themselves
    assert graded(0.9, "close") == 0.9 and graded(0.9, "unrelated") == 0.9  # and a grade never lowers a score
    assert graded(0.2, None) == 0.2 and graded(-0.3, None) == 0.0


class Reader:
    available = True

    def __init__(self, grades=None, fail: Exception | None = None, delay: float = 0.0):
        self.grades, self.fail, self.delay, self.users = grades or [], fail, delay, []

    async def structured(self, *, role, schema, user, budget=None, **kw):
        self.users.append(user)
        await asyncio.sleep(self.delay)
        if self.fail:
            raise self.fail
        return schema(grades=self.grades), LLMResult(text="", model="fake/reader", provider="baseten", latency_ms=5, tokens_in=10, tokens_out=5, cost_usd=0.0)


class Web(ScoutRole):
    id, source, tool = "scout.web", "web", "fake"

    async def search(self, query: str, n: int):
        return [from_web({"url": "https://groq.example/", "title": "Groq", "summary": "Groq builds LPU processors for fast AI inference.", "text": "Inference."}),
                from_web({"url": "https://melten.example/", "title": "Melten", "summary": "Software that helps engineers design chips.", "text": "EDA."})]


async def run(monkeypatch, reader: Reader, scores=(-0.05, 0.27)):
    async def fake_rerank(query, texts, *, clamp=True):
        return list(scores), True

    monkeypatch.setattr(router_mod, "_router", reader)
    monkeypatch.setattr(scout_base, "rerank", fake_rerank)
    ctx = FakeCtx()
    await Web().handle({"type": "TASK", "payload": {"queries": ["ai chipmaker"]}}, ctx)
    by_title = {r.title: r for r in ctx.board.records.values()}
    return ctx, by_title["Groq"], by_title["Melten"]


async def test_a_hit_the_reranker_read_too_literally_is_lifted_and_says_so(monkeypatch):
    reader = Reader([{"n": 1, "match": "same"}, {"n": 0, "match": "adjacent"}, {"n": 7, "match": "same"}])  # hits are listed nearest first
    ctx, groq, melten = await run(monkeypatch, reader)
    assert "HIT 0 [web] Melten" in reader.users[0] and "HIT 1 [web] Groq :: Groq builds LPU processors" in reader.users[0]
    assert groq.retrieval["grade"] == "same" and groq.retrieval["rerank_raw"] == 0.0 and groq.retrieval["rerank_score"] > melten.retrieval["rerank_score"]
    assert melten.retrieval["grade"] == "adjacent" and melten.retrieval["rerank_score"] == 0.27 and "rerank_raw" not in melten.retrieval
    nodes = {n.label: n.similarity for t, d in ctx.events if t == "graph.patch" for n in d.add_nodes}
    assert nodes["Groq"] == groq.retrieval["rerank_score"]  # the map is drawn from the graded score
    assert any(d.get("tool") == "grade.hits" and "1 scored higher" in d["summary"] for t, d in ctx.events if t == "tool.result")


async def test_without_a_reader_the_reranker_scores_stand(monkeypatch):
    for reader in (Reader(fail=LLMUnavailable("down")), Reader([{"n": 1, "match": "same"}], delay=0.05)):
        monkeypatch.setattr(scout_base, "GRADE_TIMEOUT_S", 0.01)
        ctx, groq, melten = await run(monkeypatch, reader)
        assert (groq.retrieval["rerank_score"], melten.retrieval["rerank_score"]) == (0.0, 0.27) and "grade" not in groq.retrieval
        assert any(t == "error" and d["recoverable"] for t, d in ctx.events)  # said, not silent
