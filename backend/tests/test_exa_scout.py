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
    assert seen["body"]["numResults"] == 4 and seen["body"]["contents"]["text"] == {"maxCharacters": 1500}
    assert "Hardware" in seen["body"]["contents"]["summary"]["query"]  # the summary is asked for in words that do not assume software
    assert "article" in seen["body"]["contents"]["summary"]["schema"]["properties"]["kind"]["enum"]  # and the page says what kind of page it is
    assert "github.com" in seen["body"]["excludeDomains"] and "category" not in seen["body"]
    await exa.search("chipmaker for ai", category="company")
    assert seen["body"]["category"] == "company"


def test_the_summary_leads_the_pitch_and_is_marked_as_not_the_pages_own_words():
    r = from_web({"url": "https://www.cerebras.example/", "title": "Cerebras", "summary": "Cerebras builds wafer-scale AI processors.",
                  "text": "Skip to content. Products. Company. The fastest AI. Anywhere."})
    assert r.pitch.startswith("Cerebras. Cerebras builds wafer-scale AI processors. Skip to content")
    assert r.tagline == "Cerebras builds wafer-scale AI processors." and r.field_provenance["tagline"] == "imputed"
    assert from_web(HIT).tagline is None and "tagline" not in from_web(HIT).field_provenance  # no summary, nothing imputed


async def test_a_lookup_keeps_only_a_page_that_carries_the_name(monkeypatch):
    """Exa answers "Cerebras" with Cerebras and with a medical company called Cerebra. A name from the planner's
    memory is a lead, not evidence: the near miss is dropped, and a product that does not exist finds nothing."""
    async def fake_post(url, *, body, headers=None):
        return {"results": [{"url": "https://cerebraai.example/", "title": "CEREBRA", "text": "Emergency medicine."},
                            {"url": "https://www.cerebras.example/", "title": "Home", "text": "Wafer-scale chips."}]}

    monkeypatch.setattr(get_settings(), "exa_api_key", "k")
    monkeypatch.setattr(exa, "post_json", fake_post)
    assert [r.url for r in await exa.lookup("Cerebras", "semiconductors")] == ["https://www.cerebras.example/"]  # matched on its address
    assert [r.url for r in await exa.lookup("Cerebras (wafer-scale)")] == ["https://www.cerebras.example/"]  # an aside is not part of the name
    assert await exa.lookup("Nonexistent Chips Inc") == [] and await exa.lookup("ab") == []


async def test_a_page_says_what_kind_of_page_it_is(monkeypatch):
    """With a schema Exa's summary is a JSON string: the kind goes to `retrieval`, the sentence leads the pitch as before."""
    async def fake_post(url, *, body, headers=None):
        return {"results": [{"url": "https://etched.example/", "title": "Etched", "text": "Chips.", "summary": '{"kind": "company", "summary": "Etched makes inference chips."}'},
                            {"url": "https://news.example/how-chips-are-made", "title": "How AI chips are made", "text": "An explainer.", "summary": '{"kind": "article", "summary": "An explainer."}'},
                            {"url": "https://plain.example/", "title": "Plain", "text": "A page.", "summary": "Not JSON: a plain summary."}]}

    monkeypatch.setattr(get_settings(), "exa_api_key", "k")
    monkeypatch.setattr(exa, "post_json", fake_post)
    company, article, plain = await exa.search("chipmaking for AI")
    assert company.retrieval["kind"] == "company" and company.pitch.startswith("Etched. Etched makes inference chips. Chips")
    assert exa.is_prior_art(company) and not exa.is_prior_art(article)
    assert plain.tagline == "Not JSON: a plain summary." and exa.is_prior_art(plain)  # a page nobody could classify is kept


async def test_the_web_scout_searches_companies_pages_and_named_players(monkeypatch):
    from app.roles.scouts.live import WebScout
    from test_scout_partial import FakeCtx

    calls = []

    async def fake_search(query, *, n=5, category=None):
        calls.append((query, category))
        page = {"url": f"https://{len(calls)}.example.org/", "title": f"Page {len(calls)}", "text": "A page."}
        return [from_web(page)] + ([] if category else [from_web({"url": f"https://news.example/{len(calls)}", "title": "A story about it", "kind": "article"})])

    async def fake_lookup(name, hint=""):
        calls.append((name, "lookup:" + hint))
        return []

    monkeypatch.setattr(exa, "search", fake_search)
    monkeypatch.setattr(exa, "lookup", fake_lookup)
    ctx = FakeCtx()
    reply = await WebScout().handle({"type": "TASK", "payload": {"queries": ["chipmaker for ai", "q2", "q3"], "hint": "semiconductors",
                                                                 "lookups": ["Nvidia", "Cerebras", "Nvidia"]}}, ctx)
    assert sorted(c for c in calls if c[1] == "company") == [("chipmaker for ai", "company"), ("q2", "company"), ("q3", "company")]
    assert sorted(c for c in calls if c[1] is None) == [("chipmaker for ai", None), ("q2", None)]  # pages of any kind: the first two only
    assert sorted(c for c in calls if str(c[1]).startswith("lookup")) == [("Cerebras", "lookup:semiconductors"), ("Nvidia", "lookup:semiconductors")]
    assert len(reply["payload"]["rids"]) == 5 and ctx.board.sources["web"].status == "ok"  # the two news stories are not prior art
    assert not any(r.retrieval.get("kind") == "article" for r in ctx.board.records.values())
    shown = [d.get("tool") for t, d in ctx.events if t == "tool.call"]
    assert shown.count("exa.search[companies]") == 3 and shown.count("exa.search[pages]") == 2 and shown.count("exa.lookup") == 2  # every way in is visible
    assert sum("1 articles set aside" in d.get("summary", "") for t, d in ctx.events if t == "tool.result") == 2  # and so is what was dropped


def test_a_few_word_pitch_is_scored_as_the_planners_description_of_it():
    from app.core.blackboard import Blackboard
    from app.roles.conductor import Plan, scored_as

    plan = Plan.model_validate({"facets": {"purpose": "make chips", "mechanism": "design accelerators"}, "semantic_queries": [], "keyword_queries": [],
                                "writeup": "A company that designs processors for training and running AI models."})
    assert scored_as(plan, "ai chipmaker") == plan.writeup
    long = "A desk-sized machine that etches custom inference accelerators overnight from a netlist, so a university lab can tape out a test chip without a foundry slot."
    assert scored_as(plan, long) is None  # a pitch that is already a description is scored as written
    assert scored_as(Plan.model_validate(plan.model_dump() | {"writeup": ""}), "ai chipmaker") is None  # some models skip optional fields
    # both of these came back from the planner for a few-word pitch: remarks on the pitch are not a description of a project
    mixed = plan.writeup + " The idea as stated is extremely thin: it names only the domain."
    assert scored_as(Plan.model_validate(plan.model_dump() | {"writeup": mixed}), "ai chipmaker") == plan.writeup
    remarks = "The description is very short and does not specify the subject area, how the AI decides on grades, or what is claimed as new."
    assert scored_as(Plan.model_validate(plan.model_dump() | {"writeup": remarks}), "ai grading for teachers") is None
    assert scored_as(Plan.model_validate(plan.model_dump() | {"writeup": "Very short. Grading could mean anything."}), "ai grading for teachers") is None
    board = Blackboard("ai chipmaker")
    assert board.similarity_text == "ai chipmaker"
    board.set("scored_as", "conductor", plan.writeup)
    assert board.similarity_text == plan.writeup and board.idea_text == "ai chipmaker"  # every agent still reads the pitch as typed


def test_the_web_is_searched_in_the_authors_own_words_first():
    from app.roles.conductor import Plan, web_queries

    plan = Plan.model_validate({"facets": {"purpose": "make chips", "mechanism": "design accelerators"}, "semantic_queries": ["a startup that designs AI accelerators", "Chipmaker for AI"],
                                "keyword_queries": [], "known_players": ["Nvidia"]})
    assert web_queries(plan, "chipmaker for ai\nchipmaker for ai\n")[:2] == ["chipmaker for ai", "a startup that designs AI accelerators"]
    assert "Chipmaker for AI" not in web_queries(plan, "chipmaker for ai")  # the planner echoing the pitch is one search, not two
    assert web_queries(plan, "x" * 400)[0] == "a startup that designs AI accelerators"  # a long pitch is not a search query


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


def test_a_companys_pages_fold_into_its_homepage_but_a_news_sites_articles_do_not():
    from app.roles.scouts.live import WebScout

    def page(url, score):
        r = from_web({"url": url, "title": url, "text": "A page."})
        r.retrieval["rerank_score"] = score
        return r

    from test_scout_partial import FakeCtx
    from app.wrangle.blocking import url_keys

    ctx = FakeCtx()
    out = WebScout().collapse([page("https://vibegrade.example/", 0.2), page("https://www.vibegrade.example/pricing", 0.5),
                               page("https://news.example/a-startup", 0.3), page("https://news.example/another-startup", 0.1)], ctx)
    assert sorted(r.url for r in out) == ["https://news.example/a-startup", "https://news.example/another-startup", "https://vibegrade.example/"]
    home = next(r for r in out if "vibegrade" in r.url)
    assert home.retrieval["rerank_score"] == 0.5 and home.retrieval["pages"] == 2  # the site is as close as its closest page
    # a follow-up search later finds another of its pages: kept, and tied to the homepage by the key the resolver merges on
    ctx.board.put("records", "scout.web", home.rid, home)
    later = WebScout().collapse([page("https://vibegrade.example/blog/rubrics", 0.4), page("https://news.example/third", 0.1)], ctx)
    assert len(later) == 2 and url_keys(later[0]) & url_keys(home) and not url_keys(later[1]) & url_keys(home)


async def test_results_that_are_not_pages_are_dropped(monkeypatch):
    async def fake_post(url, *, body, headers=None):
        return {"results": [HIT, {"url": "https://exa.ai/library/organization/y04", "title": "GradeMe AI"}, {"url": "https://http/www.x.ai", "title": "X"}]}

    monkeypatch.setattr(get_settings(), "exa_api_key", "k")
    monkeypatch.setattr(exa, "post_json", fake_post)
    assert [r.title for r in await exa.search("q")] == ["IdeaRadar – has it been built"]


def test_two_hacker_news_stories_do_not_share_a_url_key():
    """The query string was dropped, so every story's key was news.ycombinator.com/item and the resolver merged
    seven unrelated stories into one entity by rule."""
    from app.wrangle.blocking import norm_url

    a, b = norm_url("https://news.ycombinator.com/item?id=39628835"), norm_url("https://news.ycombinator.com/item?id=43948976")
    assert a == "news.ycombinator.com/item?id=39628835" and a != b
    assert norm_url("https://www.youtube.com/watch?v=Z2HQQ0d_FqM&t=3") == "youtube.com/watch?v=Z2HQQ0d_FqM"
    assert norm_url("https://news.ycombinator.com/item") is None  # no id, no page
    assert norm_url("https://example.org/launch?utm_source=x") == "example.org/launch"  # everywhere else a query is still noise
