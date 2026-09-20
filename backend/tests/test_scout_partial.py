"""A scout that answers some queries and then fails keeps what it found: degraded, not lost."""
from __future__ import annotations

from app.core.blackboard import Blackboard
from app.core.budget import Budget
from app.roles.scouts.base import ScoutRole
from app.sources.http import SourceError
from app.wrangle.schema_map import from_hn

IDEA = "A tool that checks how original a hackathon idea is by searching past projects and coaching the hacker toward whitespace."
HIT = {"objectID": "4001", "title": "Show HN: IdeaRadar – find out if your hackathon idea exists", "url": "https://idearadar.example.org",
       "story_text": "IdeaRadar searches past hackathon projects.", "created_at": "2025-06-01T00:00:00Z", "points": 12, "num_comments": 3}


class FakeCtx:
    def __init__(self) -> None:
        self.run_id, self.me, self.board, self.budget = "t", "scout.hn", Blackboard(IDEA), Budget()
        self.events: list[tuple[str, dict]] = []

    async def emit(self, type: str, data=None, **meta) -> None:
        self.events.append((type, data or {}))


class Flaky(ScoutRole):
    id, source, tool = "scout.hn", "hn", "fake"

    async def search(self, query: str, n: int):
        if query == "bad":
            raise SourceError("HTTP 503 from hn.algolia.com")
        return [from_hn(HIT)]


async def test_hits_survive_a_failed_query_as_a_degraded_source():
    ctx = FakeCtx()
    reply = await Flaky().handle({"type": "TASK", "payload": {"queries": ["good", "bad", "also bad"]}}, ctx)
    assert reply["type"] == "RESULT" and len(reply["payload"]["rids"]) == 1
    st = ctx.board.sources["hn"]
    assert (st.status, st.n_records) == ("degraded", 1) and "503" in st.error
    types = [t for t, _ in ctx.events]
    assert "evidence.found" in types
    assert types.count("tool.call") == 3  # the queries go out together, so every one is attempted
    assert types.count("source.failed") == 1  # and a sick source is announced once, not once per query


async def test_a_failure_before_a_good_query_no_longer_loses_it():
    ctx = FakeCtx()
    reply = await Flaky().handle({"type": "TASK", "payload": {"queries": ["bad", "good"]}}, ctx)
    assert reply["type"] == "RESULT" and ctx.board.sources["hn"].status == "degraded"
    assert ctx.board.records[reply["payload"]["rids"][0]].retrieval["query"] == "good"


async def test_every_query_failing_is_a_failed_source():
    ctx = FakeCtx()
    reply = await Flaky().handle({"type": "TASK", "payload": {"queries": ["bad", "bad"]}}, ctx)
    assert reply["type"] == "ERROR" and ctx.board.sources["hn"].status == "failed"
    assert not ctx.board.records


async def test_queries_run_concurrently():
    import asyncio

    class Slow(ScoutRole):
        id, source, tool = "scout.hn", "hn", "fake"
        live = peak = 0

        async def search(self, query: str, n: int):
            Slow.live += 1
            Slow.peak = max(Slow.peak, Slow.live)
            await asyncio.sleep(0.01)
            Slow.live -= 1
            return [from_hn(HIT | {"objectID": query})]

    ctx = FakeCtx()
    reply = await Slow().handle({"type": "TASK", "payload": {"queries": ["1", "2", "3"]}}, ctx)
    assert Slow.peak == 3
    assert reply["payload"]["rids"] and set(reply["payload"]["rids"]) == {"hn:1", "hn:2", "hn:3"}
