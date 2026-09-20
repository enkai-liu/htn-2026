"""Evidence browser: render a prior-art product's live site in a Browserbase cloud browser and say what is there now.

A listing proves a project existed; it does not prove the product is still running. Many of these sites are
JavaScript apps that a plain HTTP fetch reads as an empty shell, so they are rendered in a real browser: one
session per run, each site visited in turn, a screenshot and the visible text taken from each.

Two rules. (1) The verdict is deterministic -- navigation error, HTTP status, known parking/challenge wording -- so
nothing here is a model's opinion. (2) A bot challenge is reported as `blocked` and left alone: the session is
created with captcha solving OFF and no proxies, because reading a site that asked not to be read is not evidence.

The browser is driven over raw CDP on the `websockets` package the server already ships with, rather than pulling
in a browser-automation framework for four commands.
"""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
import websockets

from app.config import get_settings

from .http import SourceError, client

API = "https://api.browserbase.com/v1/sessions"
SESSION_TIMEOUT_S = 120  # Browserbase ends the session itself if we die before releasing it
NAV_TIMEOUT_S = 10.0
LOAD_TIMEOUT_S = 8.0
SETTLE_S = 1.2  # single-page apps paint after the load event
TEXT_CHARS = 3000
VIEWPORT = {"width": 1280, "height": 800}

# Pages of a listing site are not the product's own site; they are what we already have.
NOT_A_PRODUCT_SITE = ("devpost.com", "github.com", "news.ycombinator.com", "ycombinator.com", "youtube.com", "youtu.be",
                      "docs.google.com", "drive.google.com", "twitter.com", "x.com", "linkedin.com", "figma.com",
                      "facebook.com", "instagram.com", "medium.com", "discord.gg", "discord.com")
CHALLENGE = ("just a moment", "attention required", "verify you are human", "verifying you are human", "checking your browser",
             "are you a robot", "captcha", "unusual traffic", "access denied", "enable javascript and cookies to continue")
PARKED = ("domain is for sale", "domain for sale", "buy this domain", "this domain is parked", "domain parking", "parked free",
          "make an offer on this domain", "this domain may be for sale")
PARKING_HOSTS = ("sedo.com", "hugedomains.com", "afternic.com", "dan.com", "parkingcrew.net", "bodis.com", "godaddy.com")
GONE = ("there isn't a github pages site here", "no such app", "deployment_not_found", "site not found", "project not found",
        "this site can’t be reached", "404: not_found")

_sessions = asyncio.Semaphore(1)  # entry-level Browserbase plans allow one concurrent browser; runs queue rather than 429


@dataclass
class Render:
    url: str
    final_url: str = ""
    http_status: int | None = None
    error: str | None = None  # Chrome's net:: error when the navigation itself failed
    title: str = ""
    text: str = ""
    screenshot: bytes | None = None
    elapsed_ms: int = 0
    notes: list[str] = field(default_factory=list)


def _public(raw: str) -> str | None:
    """An http(s) URL on a named public host, or None. Deliberately NOT resolved here: a domain that no longer
    resolves is the finding, and the browser that follows it is Browserbase's, outside our network."""
    candidate = (raw or "").strip()
    try:
        u = urlparse(candidate if "://" in candidate else f"https://{candidate}")
        host = (u.hostname or "").lower()
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or u.username or u.password or "." not in host or " " in candidate:
        return None
    if host.endswith((".local", ".internal", ".localhost")):
        return None
    try:
        ipaddress.ip_address(host)
        return None  # a bare address is somebody's server, not a product site
    except ValueError:
        return u.geturl()


def product_site(urls: list[str]) -> str | None:
    """The first URL that is the product's own site rather than a page about it, or None."""
    for raw in urls:
        url = _public(raw)
        host = (urlparse(url).hostname or "").removeprefix("www.") if url else ""
        if url and not any(host == h or host.endswith("." + h) for h in NOT_A_PRODUCT_SITE):
            return url
    return None


def classify(r: Render) -> tuple[str, str]:
    """(status, why) with status in alive | dead | parked | blocked. Order matters: a challenge page is often a 403."""
    seen = f"{r.title} {r.text[:1500]}".lower()
    host = (urlparse(r.final_url or r.url).hostname or "").removeprefix("www.")
    if r.error:
        return "dead", f"the browser could not load it ({r.error})"
    if any(m in seen for m in CHALLENGE) or r.http_status in (403, 429):
        return "blocked", "the site answered with a bot challenge or a refusal; we do not work around those"
    if any(host == h or host.endswith("." + h) for h in PARKING_HOSTS) or any(m in seen for m in PARKED):
        return "parked", "the domain is parked or for sale"
    if r.http_status in (404, 410) or (r.http_status or 0) >= 500 or any(m in seen for m in GONE):
        return "dead", f"HTTP {r.http_status}" if r.http_status else "the host serves a 'not found' placeholder"
    if r.http_status == 401:
        return "alive", "up, behind a login"
    return "alive", "rendered" + ("" if len(r.text) >= 40 else ", but almost no visible text")


# ---------------------------------------------------------------------------------------------- Browserbase REST
async def _create_session() -> dict:
    s = get_settings()
    body = {"timeout": SESSION_TIMEOUT_S, "browserSettings": {"viewport": VIEWPORT, "solveCaptchas": False, "blockAds": True}}
    if s.browserbase_project_id:
        body["projectId"] = s.browserbase_project_id
    try:
        resp = await client().post(API, json=body, headers={"X-BB-API-Key": s.browserbase_api_key}, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise SourceError(f"HTTP {exc.response.status_code} from api.browserbase.com") from exc
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise SourceError(f"{type(exc).__name__} from api.browserbase.com") from exc


async def _release(session_id: str) -> None:
    try:  # best effort: the session timeout is the backstop
        await client().post(f"{API}/{session_id}", json={"status": "REQUEST_RELEASE"},
                            headers={"X-BB-API-Key": get_settings().browserbase_api_key}, timeout=10)
    except httpx.HTTPError:
        pass


# ---------------------------------------------------------------------------------------------- CDP
class _CDP:
    """The few lines of Chrome DevTools Protocol we need: numbered calls, and events kept until someone asks."""

    def __init__(self, ws) -> None:
        self.ws, self.n, self.events = ws, 0, []

    async def _next(self, deadline: float) -> dict:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError
        return json.loads(await asyncio.wait_for(self.ws.recv(), left))

    async def call(self, method: str, params: dict | None = None, *, session: str | None = None, timeout: float = 10.0) -> dict:
        self.n += 1
        mid = self.n
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}} | ({"sessionId": session} if session else {})))
        deadline = time.monotonic() + timeout
        while True:
            msg = await self._next(deadline)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise SourceError(f"browser: {method}: {msg['error'].get('message', 'failed')}"[:200])
                return msg.get("result") or {}
            self.events.append(msg)

    async def wait_for(self, method: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while not any(e.get("method") == method for e in self.events):
            try:
                self.events.append(await self._next(deadline))
            except TimeoutError:
                return False
        return True


_READ_PAGE = ("JSON.stringify({title: document.title || '', href: location.href, "
              f"text: ((document.body && document.body.innerText) || '').slice(0, {TEXT_CHARS})}})")


async def _visit(cdp: _CDP, sid: str, url: str) -> Render:
    started, r = time.monotonic(), Render(url=url)
    cdp.events.clear()
    try:
        nav = await cdp.call("Page.navigate", {"url": url}, session=sid, timeout=NAV_TIMEOUT_S)
        if nav.get("errorText"):
            r.error = nav["errorText"]
        else:
            if not await cdp.wait_for("Page.loadEventFired", LOAD_TIMEOUT_S):
                r.notes.append(f"still loading after {LOAD_TIMEOUT_S:.0f} s; read as it stood")
            await asyncio.sleep(SETTLE_S)
            docs = [e["params"]["response"] for e in cdp.events if e.get("method") == "Network.responseReceived"
                    and e["params"].get("type") == "Document" and e["params"].get("frameId") == nav.get("frameId")]
            if docs:  # the last document response is the one after any redirects
                r.http_status = docs[-1].get("status")
            page = await cdp.call("Runtime.evaluate", {"expression": _READ_PAGE, "returnByValue": True}, session=sid)
            seen = json.loads((page.get("result") or {}).get("value") or "{}")
            r.title, r.text, r.final_url = seen.get("title", "")[:200], " ".join(seen.get("text", "").split()), seen.get("href", "")
            shot = await cdp.call("Page.captureScreenshot", {"format": "jpeg", "quality": 55}, session=sid, timeout=15)
            r.screenshot = base64.b64decode(shot["data"]) if shot.get("data") else None
    except TimeoutError:
        r.error = r.error or "timed out"
    r.elapsed_ms = int((time.monotonic() - started) * 1000)
    return r


async def render(urls: list[str]) -> list[Render]:
    """Render each URL in ONE cloud browser session, in order. Raises SourceError only when no browser could be had;
    a site that will not load is a result (that is the finding), not an error."""
    if not get_settings().has_browser:
        raise SourceError("BROWSERBASE_API_KEY is not set")
    async with _sessions:
        session = await _create_session()
        try:
            async with websockets.connect(session["connectUrl"], max_size=32 * 1024 * 1024, open_timeout=20) as ws:
                cdp = _CDP(ws)
                pages = [t for t in (await cdp.call("Target.getTargets"))["targetInfos"] if t.get("type") == "page"]
                target = pages[0]["targetId"] if pages else (await cdp.call("Target.createTarget", {"url": "about:blank"}))["targetId"]
                sid = (await cdp.call("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
                await cdp.call("Page.enable", session=sid)
                await cdp.call("Network.enable", session=sid)
                return [await _visit(cdp, sid, u) for u in urls]
        except (OSError, TimeoutError, websockets.WebSocketException, KeyError) as exc:
            raise SourceError(f"browser session failed: {type(exc).__name__}"[:200]) from exc
        finally:
            await _release(session["id"])
