"""The evidence browser: which link counts as the product's own site, how a render is judged, and the CDP exchange."""
from __future__ import annotations

import base64
import json

import pytest

from app.config import get_settings
from app.core.blackboard import Blackboard
from app.core.budget import Budget
from app.roles import inspector
from app.roles.inspector import Inspector
from app.schemas import Entity, FusedField
from app.sources import browserbase
from app.sources.browserbase import Render, classify, product_site
from app.sources.http import SourceError
from app.wrangle.schema_map import from_github

GH = {"full_name": "acme/idearadar", "name": "idearadar", "html_url": "https://github.com/acme/idearadar", "homepage": "https://idearadar.example.org",
      "description": "Find out if your idea exists", "created_at": "2025-01-01T00:00:00Z", "pushed_at": "2026-09-01T00:00:00Z"}


def test_a_listing_page_is_not_the_products_own_site():
    assert product_site(["https://github.com/acme/x", "https://www.youtube.com/watch?v=1", "https://acme.example.org/app"]) == "https://acme.example.org/app"
    assert product_site(["https://devpost.com/software/x", "http://localhost:3000", "not a url"]) is None


@pytest.mark.parametrize("render, status", [
    (Render(url="https://a.example.org", error="net::ERR_NAME_NOT_RESOLVED"), "dead"),
    (Render(url="https://a.example.org", http_status=404, title="Not found"), "dead"),
    (Render(url="https://a.example.org", http_status=200, text="There isn't a GitHub Pages site here."), "dead"),
    (Render(url="https://a.example.org", http_status=403, title="Just a moment..."), "blocked"),
    (Render(url="https://a.example.org", http_status=200, text="Please verify you are human to continue"), "blocked"),
    (Render(url="https://a.example.org", final_url="https://www.hugedomains.com/domain_profile.cfm?d=a", http_status=200), "parked"),
    (Render(url="https://a.example.org", http_status=200, text="This domain is for sale. Buy this domain today."), "parked"),
    (Render(url="https://a.example.org", http_status=401, title="Sign in"), "alive"),
    (Render(url="https://a.example.org", http_status=200, title="Acme", text="Acme checks whether your idea has been built before. " * 3), "alive"),
])
def test_the_verdict_is_read_off_the_render(render, status):
    assert classify(render)[0] == status


class FakeSocket:
    """Answers CDP calls the way Chrome does, with the events a navigation produces arriving before its reply is read."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.inbox: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, raw: str) -> None:
        msg = json.loads(raw)
        self.sent.append(msg)
        method, reply = msg["method"], {}
        if method == "Target.getTargets":
            reply = {"targetInfos": [{"type": "page", "targetId": "T1"}]}
        elif method == "Target.attachToTarget":
            reply = {"sessionId": "S1"}
        elif method == "Page.navigate":
            if "gone" in msg["params"]["url"]:
                reply = {"frameId": "F1", "errorText": "net::ERR_NAME_NOT_RESOLVED"}
            else:
                reply = {"frameId": "F1"}
                for status in (301, 200):  # a redirect first: the last document response is the one that counts
                    self.inbox.append(json.dumps({"method": "Network.responseReceived", "params": {"type": "Document", "frameId": "F1", "response": {"status": status}}}))
                self.inbox.append(json.dumps({"method": "Page.loadEventFired", "params": {}}))
        elif method == "Runtime.evaluate":
            reply = {"result": {"value": json.dumps({"title": "IdeaRadar", "href": "https://idearadar.example.org/home", "text": "Find  out if\nyour idea exists."})}}
        elif method == "Page.captureScreenshot":
            reply = {"data": base64.b64encode(b"\xff\xd8jpeg").decode()}
        self.inbox.insert(0, json.dumps({"id": msg["id"], "result": reply})) if method != "Page.navigate" else self.inbox.append(json.dumps({"id": msg["id"], "result": reply}))

    async def recv(self) -> str:
        return self.inbox.pop(0)


@pytest.fixture
def browser(monkeypatch):
    sock, calls = FakeSocket(), {"created": [], "released": []}

    async def create():
        calls["created"].append(1)
        return {"id": "sess1", "connectUrl": "wss://connect.example/sess1"}

    async def release(sid):
        calls["released"].append(sid)

    monkeypatch.setattr(get_settings(), "browserbase_api_key", "k")
    monkeypatch.setattr(browserbase, "_create_session", create)
    monkeypatch.setattr(browserbase, "_release", release)
    monkeypatch.setattr(browserbase.websockets, "connect", lambda *a, **k: sock)
    monkeypatch.setattr(browserbase, "SETTLE_S", 0)
    return sock, calls


async def test_one_session_renders_every_site_and_is_always_released(browser):
    sock, calls = browser
    live, gone = await browserbase.render(["https://idearadar.example.org", "https://gone.example.org"])
    assert (live.http_status, live.title, live.text, live.final_url) == (200, "IdeaRadar", "Find out if your idea exists.", "https://idearadar.example.org/home")
    assert live.screenshot == b"\xff\xd8jpeg" and classify(live)[0] == "alive"
    assert gone.error == "net::ERR_NAME_NOT_RESOLVED" and gone.screenshot is None and classify(gone)[0] == "dead"
    assert calls == {"created": [1], "released": ["sess1"]}
    assert all(m.get("sessionId") == "S1" for m in sock.sent if m["method"].startswith(("Page.", "Network.", "Runtime.")))


async def test_the_session_never_asks_for_captcha_solving(monkeypatch):
    seen = {}

    class Resp:
        def raise_for_status(self): ...
        def json(self): return {"id": "s", "connectUrl": "wss://x"}

    class Client:
        async def post(self, url, *, json, headers, timeout):
            seen.update(url=url, body=json, headers=headers)
            return Resp()

    monkeypatch.setattr(get_settings(), "browserbase_api_key", "k")
    monkeypatch.setattr(get_settings(), "browserbase_project_id", "p")
    monkeypatch.setattr(browserbase, "client", lambda: Client())
    await browserbase._create_session()
    assert seen["body"]["browserSettings"]["solveCaptchas"] is False and "proxies" not in seen["body"]
    assert seen["body"]["projectId"] == "p" and seen["headers"] == {"X-BB-API-Key": "k"}


async def test_no_key_is_a_source_error(monkeypatch):
    monkeypatch.setattr(get_settings(), "browserbase_api_key", "")
    with pytest.raises(SourceError, match="BROWSERBASE_API_KEY"):
        await browserbase.render(["https://a.example.org"])


class FakeCtx:
    def __init__(self) -> None:
        self.run_id, self.me, self.board, self.budget = "rtest", "inspector", Blackboard("an idea"), Budget()
        self.events: list[tuple[str, dict]] = []

    async def emit(self, type: str, data=None, **meta) -> None:
        self.events.append((type, data if isinstance(data, dict) else data.model_dump()))


async def test_a_dead_site_contradicts_an_active_listing(monkeypatch, tmp_path):
    ctx, rec = FakeCtx(), from_github(GH)
    ctx.board.put("records", "scout.github", rec.rid, rec)
    ctx.board.put("entities", "resolver", "e1", Entity(eid="e1", canonical_name="idearadar", records=[rec.rid], sources=["github"], similarity=0.6,
                                                        fields={"status": FusedField(value="active", provenance=[rec.rid], imputed=True)}))
    ctx.board.put("entities", "resolver", "e2", Entity(eid="e2", canonical_name="no site", records=[], similarity=0.9))

    async def render(urls):
        assert urls == ["https://idearadar.example.org"]  # the homepage, not the repo page; the entity with no site is passed over
        return [Render(url=urls[0], error="net::ERR_NAME_NOT_RESOLVED", screenshot=None, elapsed_ms=900)]

    monkeypatch.setattr(browserbase, "render", render)
    monkeypatch.setattr(inspector, "SHOTS_DIR", tmp_path)
    reply = await Inspector().handle({"type": "TASK", "payload": {}}, ctx)
    assert reply["type"] == "RESULT" and reply["payload"]["checked"] == 1
    site = ctx.board.sites["e1"]
    assert site.status == "dead" and site.screenshot is None and site.conflict.resolution == "dead"
    assert [v.value for v in site.conflict.values] == ["site dead", "active"]
    assert [t for t, _ in ctx.events] == ["tool.call", "site.checked", "conflict.detected", "tool.result"]


async def test_a_screenshot_is_saved_and_addressed_by_run_and_entity(monkeypatch, tmp_path):
    ctx, rec = FakeCtx(), from_github(GH)
    ctx.board.put("records", "scout.github", rec.rid, rec)
    ctx.board.put("entities", "resolver", "e1", Entity(eid="e1", canonical_name="idearadar", records=[rec.rid], similarity=0.6))

    async def render(urls):
        return [Render(url=urls[0], final_url=urls[0], http_status=200, title="IdeaRadar", text="Find out if your idea exists. " * 4, screenshot=b"jpg")]

    monkeypatch.setattr(browserbase, "render", render)
    monkeypatch.setattr(inspector, "SHOTS_DIR", tmp_path)
    await Inspector().handle({"type": "TASK", "payload": {}}, ctx)
    site = ctx.board.sites["e1"]
    assert (site.status, site.screenshot, site.conflict) == ("alive", "/api/runs/rtest/shots/e1.jpg", None)
    assert (tmp_path / "rtest-e1.jpg").read_bytes() == b"jpg"


async def test_no_browser_is_a_gap_not_a_crash(monkeypatch):
    ctx, rec = FakeCtx(), from_github(GH)
    ctx.board.put("records", "scout.github", rec.rid, rec)
    ctx.board.put("entities", "resolver", "e1", Entity(eid="e1", canonical_name="idearadar", records=[rec.rid], similarity=0.6))

    async def render(urls):
        raise SourceError("HTTP 429 from api.browserbase.com")

    monkeypatch.setattr(browserbase, "render", render)
    reply = await Inspector().handle({"type": "TASK", "payload": {}}, ctx)
    assert reply["type"] == "ERROR" and not ctx.board.sites
    assert ("error", {"message": "evidence browser unavailable: HTTP 429 from api.browserbase.com", "recoverable": True}) in ctx.events
