"""The open-web scout: Exa results become `web` records, the request is shaped as documented, and a build without
a key leaves the scout off the team instead of failing the run."""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.sources import exa
from app.sources.http import SourceError
from app.wrangle.blocking import url_keys
from app.wrangle.schema_map import from_web

HIT = {"id": "https://www.idearadar.example.org/", "url": "https://www.idearadar.example.org/?utm_source=x", "title": "IdeaRadar – has it been built",
       "publishedDate": "2025-03-04T00:00:00.000Z", "author": "Acme", "text": "IdeaRadar  searches <b>past</b> hackathon projects. " + "x" * 3000}


def test_a_web_hit_becomes_a_record_keyed_by_its_normalised_url():
    r = from_web(HIT)
    assert r.source == "web" and r.rid.startswith("web:") and r.year == 2025 and r.date_precision == "day"
    assert r.pitch.startswith("IdeaRadar – has it been built. IdeaRadar searches past hackathon projects") and len(r.pitch) <= 1500
    assert r.rid == from_web(HIT | {"url": "http://idearadar.example.org"}).rid  # scheme, www and tracking params are not identity
    assert "idearadar.example.org" in url_keys(r)  # the key the resolver merges on and self-exclusion checks


def test_a_page_with_no_title_or_date_is_still_a_record():
    r = from_web({"url": "https://example.org/launch", "text": "A launch post."})
    assert r.title == "example.org/launch" and r.year is None and r.date_precision is None


async def test_search_sends_the_documented_request(monkeypatch):
    seen = {}

    async def fake_post(url, *, body, headers=None):
        seen.update(url=url, body=body, headers=headers)
        return {"results": [HIT, {"url": "https://empty.example.org"}]}

    monkeypatch.setattr(get_settings(), "exa_api_key", "k")
    monkeypatch.setattr(exa, "post_json", fake_post)
    hits = await exa.search("a tool that checks idea originality", n=4)
    assert [h.source for h in hits] == ["web"]  # the hit with neither title nor text is dropped
    assert seen["url"] == "https://api.exa.ai/search" and seen["headers"] == {"x-api-key": "k"}
    assert seen["body"]["numResults"] == 4 and seen["body"]["contents"] == {"text": {"maxCharacters": 1500}}
    assert "github.com" in seen["body"]["excludeDomains"]


async def test_no_key_is_a_source_error_not_a_request(monkeypatch):
    monkeypatch.setattr(get_settings(), "exa_api_key", "")
    with pytest.raises(SourceError, match="EXA_API_KEY"):
        await exa.search("anything")


def test_the_plan_adds_a_problem_only_query_and_a_hypothetical_writeup():
    from app.roles.conductor import Plan, semantic_queries

    base = {"facets": {"purpose": "check idea originality", "mechanism": "search past projects", "audience": "hackers"},
            "semantic_queries": ["full idea", "purpose and mechanism", "the twist", "a fourth the planner was not asked for"], "keyword_queries": ["idea checker"]}
    full = Plan.model_validate(base | {"problem_query": "Hackers cannot tell whether an idea was already built.", "writeup": "A tool that searches past projects."})
    assert semantic_queries(full) == ["full idea", "purpose and mechanism", "the twist",
                                      "Hackers cannot tell whether an idea was already built.", "A tool that searches past projects."]
    # a model that skips the optional fields still gets a problem-only query, built from the facets; no write-up is invented
    assert semantic_queries(Plan.model_validate(base)) == ["full idea", "purpose and mechanism", "the twist", "check idea originality for hackers"]
    # a query the planner repeated is searched once
    assert semantic_queries(Plan.model_validate(base | {"problem_query": "FULL IDEA"})) == ["full idea", "purpose and mechanism", "the twist"]
