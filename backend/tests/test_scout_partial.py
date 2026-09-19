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


async def test_hits_before_a_failure_survive_as_a_degraded_source():
    ctx = FakeCtx()
    reply = await Flaky().handle({"type": "TASK", "payload": {"queries": ["good", "bad", "never reached"]}}, ctx)
    assert reply["type"] == "RESULT" and len(reply["payload"]["rids"]) == 1
    st = ctx.board.sources["hn"]
    assert (st.status, st.n_records) == ("degraded", 1) and "503" in st.error
    types = [t for t, _ in ctx.events]
    assert "source.failed" in types and "evidence.found" in types
    assert types.count("tool.call") == 2  # the third query was not attempted


async def test_nothing_found_before_the_failure_is_still_a_failed_source():
    ctx = FakeCtx()
    reply = await Flaky().handle({"type": "TASK", "payload": {"queries": ["bad", "good"]}}, ctx)
    assert reply["type"] == "ERROR" and ctx.board.sources["hn"].status == "failed"
    assert not ctx.board.records
