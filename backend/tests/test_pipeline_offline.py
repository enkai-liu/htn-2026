"""End-to-end run with a fake LLM and fake sources: real host, real roles, real scoring, contract-valid events."""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.core import runstore
from app.core.blackboard import Blackboard, BlackboardPermissionError
from app.llm import router as router_mod
from app.llm.router import LLMResult
from app.schemas import EVENT_TYPES, Facets, Report
from app.sources import github, hn
from app.sources.http import SourceError
from app.wrangle.schema_map import from_github, from_hn

IDEA = ("A tool that checks how original a hackathon idea is by searching past projects, letting AI agents argue about whether it "
        "has been done, verifying every claim against its source, and then coaching the hacker toward a less crowded version of the idea "
        "with each suggestion re-scored against the evidence.")

GH = {"full_name": "acme/idearadar", "name": "idearadar", "html_url": "https://github.com/acme/idearadar", "homepage": "https://idearadar.example.org",
      "description": "IdeaRadar checks whether your hackathon idea already exists by searching past projects with keywords.",
      "topics": ["hackathon"], "language": "Python", "created_at": "2023-02-01T00:00:00Z", "pushed_at": "2023-03-01T00:00:00Z",
      "stargazers_count": 14, "archived": False}
HN = {"objectID": "4001", "title": "Show HN: IdeaRadar – find out if your hackathon idea exists", "url": "https://idearadar.example.org",
      "story_text": "We built IdeaRadar, which is actively maintained, to search past hackathon projects.", "created_at": "2025-06-01T00:00:00Z",
      "points": 120, "num_comments": 40}


class FakeRouter:
    available = True

    def __init__(self):
        self.calls: list[str] = []

    def _res(self, model="fake/model"):
        return LLMResult(text="**Crowded purpose, different mechanism.** IdeaRadar already searches past projects [1].", model=model,
                         provider="baseten", latency_ms=5, tokens_in=100, tokens_out=20, cost_usd=0.0001)

    async def chat(self, *, role, budget=None, **kw):
        self.calls.append(f"chat:{role}")
        if budget:
            budget.charge(tokens_in=100, tokens_out=20, cost_usd=0.0001)
        return self._res()

    async def structured(self, *, role, schema, model=None, budget=None, **kw):
        self.calls.append(f"{role}:{schema.__name__}")
        if budget:
            budget.charge(tokens_in=100, tokens_out=20, cost_usd=0.0001)
        name = schema.__name__
        if name == "Plan":
            obj = schema(facets=Facets(purpose="check whether a hackathon idea already exists", mechanism="multi-agent retrieval and debate",
                                       audience="hackers", data="past hackathon projects", twist="coaching with re-scoring", domain="developer tools",
                                       keywords=["hackathon idea originality"]),
                         semantic_queries=[IDEA, "hackathon idea originality checker", "coaching re-scoring"],
                         keyword_queries=["hackathon idea checker", "idea originality"])
        elif name == "Adjudication":
            obj = schema(verdicts=[])
        elif name == "Critique":
            obj = schema(claims=[{"entity": 0, "text": "IdeaRadar already checks whether a hackathon idea exists.",
                                  "quote": "checks whether your hackathon idea already exists", "facets": ["purpose"]},
                                 {"entity": 0, "text": "IdeaRadar won a Nobel prize for this.", "quote": "awarded the Nobel prize for hackathons", "facets": []}],
                         followups=[{"facet": "twist", "query": "coaching hackathon idea", "scout": "scout.github", "reason": "does anyone coach?"}])
        elif name == "Defence":
            obj = schema(responses=[{"cid": "c1", "type": "REBUTTAL", "text": "Same purpose; keyword search is a different mechanism."}],
                         differences=[{"text": "No prior work re-scores suggestions against evidence.", "facet": "twist"}])
        elif name == "Ballot":
            mech = {"zai-org/GLM-5.3-Flash": 0.1, "deepseek-ai/DeepSeek-V4.1-Flash": 0.9}.get(model, 0.2)  # a split jury
            obj = schema(overlaps=[{"entity": 0, "purpose": 0.9, "mechanism": mech, "why": "test"}])
        elif name == "Proposals":
            obj = schema(ideas=["A search engine over old hackathon projects.", "A chatbot that rates ideas.", "A sponsor prize matcher."])
        elif name == "Swaps":
            obj = schema(mutations=[{"facet": "audience", "frm": "hackers", "to": "organisers screening submissions", "rationale": "absent nearby",
                                     "pitch": "A triage console for hackathon organisers that flags recycled projects with verified evidence.",
                                     "grounded_in": ["organizer"]}] * 3)
        else:  # pragma: no cover
            raise AssertionError(f"unexpected schema {name}")
        return obj, self._res(model or "fake/model")


def _hosts():
    try:
        import openjiuwen  # noqa: F401

        return ["asyncio", "jiuwen"]
    except ImportError:  # the main venv does not carry openjiuwen's 86 dependencies
        return ["asyncio", pytest.param("jiuwen", marks=pytest.mark.skip(reason="openjiuwen not installed in this venv"))]


@pytest.fixture(params=_hosts())
def offline(monkeypatch, request):
    s = get_settings()
    monkeypatch.setattr(s, "orchestrator", request.param)
    monkeypatch.setattr(s, "es_url", "")  # no Elasticsearch: corpus scouts are skipped and the headline must abstain
    monkeypatch.setattr(s, "es_api_key", "")
    monkeypatch.setattr(s, "gptzero_mode", "replay")
    fake = FakeRouter()
    monkeypatch.setattr(router_mod, "_router", fake)
    state = {"hn_calls": 0}

    async def gh_search(query, *, n=8):
        return [from_github(GH)]

    async def hn_search(query, *, n=8):
        state["hn_calls"] += 1
        if state["hn_calls"] == 1:
            raise SourceError("TimeoutException from hn.algolia.com after 3 attempts")
        return [from_hn(HN)]

    monkeypatch.setattr(github, "search", gh_search)
    monkeypatch.setattr(hn, "search", hn_search)
    return fake


async def test_full_run_offline(offline):
    run = runstore.create_run(IDEA)
    await run.task
    events = run.bus.history
    types = [e.type for e in events]
    assert events[0].data["orchestrator"] == get_settings().orchestrator, [e.data for e in events if e.type == "error"]
    if run.host.name == "jiuwen":  # events must really have travelled through the openJiuwen session stream
        assert run.host.mirrored > 50
    assert set(types) <= EVENT_TYPES
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert types[0] == "run.started" and types[-1] == "run.finished", [e.data for e in events if e.type == "error"]

    # dynamic team formation: corpus scouts skipped with a reason
    team = next(e for e in events if e.type == "team.formed").data
    assert {s["agent"] for s in team["skipped"]} >= {"scout.devpost", "scout.yc", "scout.arxiv"}

    # failure handling: HN failed once, was retried by the conductor, and ended up degraded rather than lost
    assert "source.failed" in types
    report = Report.model_validate(events[-1].data["report"])
    assert {s.source: s.status for s in report.sources}["hn"] == "degraded"

    # entity resolution: GitHub repo and the Show HN thread share a homepage -> one entity, with a visible status conflict
    merged = [e for e in events if e.type == "entity.merged" and e.data["verdict"] == "same"]
    assert merged and set(merged[0].data["entity"]["sources"]) == {"github", "hn"}
    ent = next(e for e in report.entities if len(e.records) == 2)
    assert ent.canonical_name.lower() == "idearadar"
    assert any(c.field == "last_activity" for c in ent.conflicts)
    assert ent.fields["status"].imputed  # derived from pushed_at, so it is marked as inferred

    # genuine collaboration: critic sent a scout back out; the split jury triggered a conductor re-query and a re-vote
    requeries = [e for e in events if e.type == "requery.issued"]
    assert {e.agent for e in requeries} == {"critic", "conductor"}
    assert any("re-vote" in e.data["subject"] for e in events if e.type == "jury.vote")

    # the verifier's veto: the fabricated quote is not verified and never reaches the synthesizer prompt as fact
    status = {c.text: c.status for c in report.claims}
    assert status["IdeaRadar already checks whether a hackathon idea exists."] == "verified"
    assert status["IdeaRadar won a Nobel prize for this."] == "unverified_lead"

    # abstention: without the corpus the headline is withheld, but the axes that can be computed still are
    assert report.scores.abstain.active and report.scores.headline is None
    assert "corpus" in report.scores.abstain.reason
    assert report.scores.crowding.score is not None and report.scores.llm_predictability.score is not None
    assert report.scores.facet_rarity.score is None

    # coaching: every mutation was re-scored
    assert len(report.mutations) == 3 and all(m.axes for m in report.mutations)
    assert types.count("mutation.scored") == 3
    assert "action.proposed" in types and report.summary_md


async def test_no_llm_configured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "baseten_api_key", "")
    monkeypatch.setattr(s, "openrouter_api_key", "")
    monkeypatch.setattr(router_mod, "_router", None)
    run = runstore.create_run(IDEA)
    await run.task
    last = run.bus.history[-1]
    assert last.type == "error" and "BASETEN_API_KEY" in last.data["message"]
    monkeypatch.setattr(router_mod, "_router", None)


def test_blackboard_permissions():
    board = Blackboard("idea")
    with pytest.raises(BlackboardPermissionError):
        board.put("entities", "critic", "e1", object())  # only the resolver writes entities
    with pytest.raises(BlackboardPermissionError):
        board.set("voice", "synthesizer", None)  # only the verifier writes voice
    board.put("records", "scout.hn", "hn:1", object())  # any scout may add records


async def test_post_run_rescore_streams_to_same_bus(offline):
    """After run.finished the bus stays open: an API-triggered re-score reaches the mutator on either host."""
    from app.orchestration.host import task

    run = runstore.create_run(IDEA)
    await run.task
    before = len(run.bus.history)
    reply = await run.host.deliver("user", "mutator", task(rescore="mu1"), timeout=30)
    assert reply["type"] == "RESULT" and reply["payload"]["mid"] == "mu1", reply
    assert [e.type for e in run.bus.history[before:]].count("mutation.scored") == 1


@pytest.mark.skipif(len([h for h in _hosts() if isinstance(h, str)]) < 2, reason="openjiuwen not installed in this venv")
async def test_host_parity(monkeypatch, request):
    """Same roles, two runtimes: the asyncio host and the openJiuwen host must produce the same event-type multiset."""
    from collections import Counter

    counts = {}
    for host in ("asyncio", "jiuwen"):
        monkeypatch.setattr(get_settings(), "orchestrator", host)
        request.getfixturevalue  # noqa: B018
        s = get_settings()
        for k in ("es_url", "es_api_key"):
            monkeypatch.setattr(s, k, "")
        monkeypatch.setattr(router_mod, "_router", FakeRouter())
        state = {"n": 0}

        async def gh_search(query, *, n=8):
            return [from_github(GH)]

        async def hn_search(query, *, n=8, _state=state):
            _state["n"] += 1
            if _state["n"] == 1:
                raise SourceError("TimeoutException from hn.algolia.com after 3 attempts")
            return [from_hn(HN)]

        monkeypatch.setattr(github, "search", gh_search)
        monkeypatch.setattr(hn, "search", hn_search)
        run = runstore.create_run(IDEA)
        await run.task
        assert run.host.name == host
        counts[host] = Counter(e.type for e in run.bus.history)
    assert counts["asyncio"] == counts["jiuwen"], {k: (counts["asyncio"][k], counts["jiuwen"][k]) for k in counts["asyncio"] | counts["jiuwen"] if counts["asyncio"][k] != counts["jiuwen"][k]}
