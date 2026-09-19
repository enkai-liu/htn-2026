"""The author's optional link: what we read off it, what we refuse to fetch, and the hit it excludes.

The exclusion is the point. Without it the scouts hand the author their own Devpost listing back as prior art
and the run reports their idea as already built.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.blackboard import Blackboard
from app.core.budget import Budget
from app.roles.scouts.base import ScoutRole
from app.sources import idea_url
from app.sources.http import SourceError
from app.wrangle.schema_map import from_github, from_hn

FIXTURE = Path(__file__).parent / "fixtures" / "devpost_project_page.html"
IDEA = "A tool that checks how original a hackathon idea is by searching past projects and coaching the hacker toward whitespace."


def test_devpost_page_gives_the_planner_the_write_up_and_the_exclusion_key():
    page = idea_url._read_devpost(FIXTURE.read_text(encoding="utf-8"), "https://devpost.com/software/hackanalyzer")
    assert page.kind == "devpost" and page.title
    assert len(page.text) > 200  # the write-up, not just the tagline
    assert "devpost.com/software/hackanalyzer" in page.keys
    context = page.context()
    assert page.title in context and context.startswith("THE AUTHOR'S OWN DEVPOST PAGE")
    assert len(context) < 2200  # capped: one short field bounds the planner's token cost


def test_outbound_links_on_the_page_are_exclusion_keys_too():
    """A Devpost page that links its repo must also exclude that repo when the GitHub scout finds it."""
    page = idea_url._page("https://devpost.com/software/x", "devpost", "X", None, "body",
                          [], ["https://github.com/octocat/x", "https://x.example.org"])
    assert {"devpost.com/software/x", "github.com/octocat/x", "x.example.org"} <= set(page.keys)


@pytest.mark.parametrize("bad", [
    "file:///etc/passwd",
    "ftp://example.com/x",
    "http://localhost:8000/api/health",
    "http://127.0.0.1/",
    "http://[::1]/",
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata
    "http://user:pw@example.com/",
    "",
])
def test_the_server_refuses_to_fetch_what_is_not_a_public_page(bad):
    """The user supplies this URL and the server fetches it, so the gate is here."""
    with pytest.raises(SourceError):
        idea_url.normalize(bad)


def test_a_public_link_is_canonicalised_not_rejected():
    assert idea_url.normalize("  devpost.com/software/hackanalyzer#gallery  ") == "https://devpost.com/software/hackanalyzer"


def test_a_readme_reaches_the_planner_as_prose():
    """GitHub serves a raw README as `application/vnd.github.raw`, which is text however it is spelled."""
    md = (
        "# My Project\n\n"
        "[![badge](https://img.shields.io/x.svg)](https://ci.example)\n\n"
        "**Does** a [thing](https://x.io).\n\n"
        "```py\ncode()\n```\n"
    )
    out = idea_url._markdown_text(md)
    assert "Does a thing" in out and "img.shields.io" not in out and "code()" not in out


def test_is_self_matches_the_record_by_url_not_by_title():
    page = idea_url._page("https://github.com/octocat/mine", "github", "octocat/mine", None, "", [], [])
    mine = from_github({"full_name": "octocat/mine", "html_url": "https://github.com/octocat/mine", "description": "d"})
    other = from_github({"full_name": "someone/other", "html_url": "https://github.com/someone/other", "description": "d"})
    assert idea_url.is_self(mine, page) and not idea_url.is_self(other, page)
    assert not idea_url.is_self(mine, None)  # no link given: nothing is excluded


# -- the scout drops it, visibly ------------------------------------------------------------------------

HIT_MINE = {"objectID": "1", "title": "IdeaRadar", "url": "https://github.com/octocat/mine",
            "story_text": "my own project", "created_at": "2025-06-01T00:00:00Z", "points": 1, "num_comments": 0}
HIT_OTHER = {"objectID": "2", "title": "SomeoneElse", "url": "https://github.com/someone/other",
             "story_text": "a real neighbour", "created_at": "2025-06-01T00:00:00Z", "points": 2, "num_comments": 0}


class FakeCtx:
    def __init__(self, page=None) -> None:
        self.run_id, self.me, self.board, self.budget = "t", "scout.hn", Blackboard(IDEA), Budget()
        self.board.self_page = page
        self.events: list[tuple[str, dict]] = []

    async def emit(self, type: str, data=None, **meta) -> None:
        self.events.append((type, data or {}))


class TwoHits(ScoutRole):
    id, source, tool = "scout.hn", "hn", "fake"

    async def search(self, query: str, n: int):
        return [from_hn(HIT_MINE), from_hn(HIT_OTHER)]


async def test_a_scout_never_returns_the_authors_own_project_as_prior_art():
    page = idea_url._page("https://github.com/octocat/mine", "github", "octocat/mine", None, "", [], [])
    ctx = FakeCtx(page)
    reply = await TwoHits().handle({"type": "TASK", "payload": {"queries": ["q"]}}, ctx)

    assert reply["payload"]["rids"] == ["hn:2"]
    assert "hn:1" not in ctx.board.records and "hn:2" in ctx.board.records
    assert ctx.board.sources["hn"].n_records == 1
    # dropped out loud: a hit that vanishes silently reads as a retrieval bug
    assert any(t == "tool.result" and "excluded 1 hit" in d.get("summary", "") for t, d in ctx.events)
    # and its island is never drawn
    assert not any(t == "graph.patch" and "IdeaRadar" in str(d) for t, d in ctx.events)


async def test_without_a_link_every_hit_still_counts():
    ctx = FakeCtx(None)
    reply = await TwoHits().handle({"type": "TASK", "payload": {"queries": ["q"]}}, ctx)
    assert sorted(reply["payload"]["rids"]) == ["hn:1", "hn:2"]
    assert not any(t == "tool.result" and "excluded" in d.get("summary", "") for t, d in ctx.events)
