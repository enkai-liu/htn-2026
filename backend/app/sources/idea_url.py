"""The author's own link: read it, and make sure the run cannot cite the idea against itself.

A pasted Devpost page or GitHub repo is the idea in more detail than the pitch box holds, so its write-up joins
the planner's input. It is also, by definition, the one hit that must never count as prior art: without an
exclusion the scouts find the author's own listing and the tool reports their idea as already built.

The exclusion key is the same `norm_url` the resolver blocks on, so a Devpost page that links its repo also
excludes that repo when the GitHub scout finds it.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from app.config import get_settings
from app.schemas import SourceRecord
from app.sources.http import SourceError, get_json, get_page
from app.wrangle.blocking import norm_url, url_keys

CONTEXT_CHARS = 1500  # the corpus caps `pitch` at 1500 too: one short field bounds both token cost and drift
_BLANKS = re.compile(r"[ \t]*\n\s*\n\s*")
_GITHUB_REPO = re.compile(r"^/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


@dataclass
class IdeaPage:
    """What the author's link says about their own idea, plus every URL that therefore refers to it."""

    url: str
    kind: str  # devpost | github | web
    title: str
    tagline: str | None = None
    text: str = ""
    tech: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)  # norm_url keys that mean "this hit is the author's own project"

    def context(self) -> str:
        """The block appended to the planner's input, labelled so the model reads it as the author's own page."""
        head = " - ".join(p for p in (self.title, self.tagline) if p)
        tech = f"\nBUILT WITH: {', '.join(self.tech[:12])}" if self.tech else ""
        return f"THE AUTHOR'S OWN {self.kind.upper()} PAGE ({self.url}):\n{head}{tech}\n{self.text[:CONTEXT_CHARS]}".strip()

    def summary(self) -> str:
        return f"{self.kind}: {self.title[:60]} ({len(self.text)} chars read); excluded from prior art"


def normalize(raw: str) -> str:
    """Canonicalise a pasted link and refuse anything that is not a public web page.

    The user supplies the URL and the server fetches it, so this is the SSRF gate: http(s) only, a host that
    resolves to a public address, no embedded credentials.
    """
    candidate = (raw or "").strip()
    if not candidate:
        raise SourceError("no link given")
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    u = urlsplit(candidate)
    if u.scheme not in ("http", "https"):
        raise SourceError(f"{u.scheme or 'that'} links cannot be fetched; use http(s)")
    if u.username or u.password:
        raise SourceError("links with credentials in them are not fetched")
    if not u.hostname:
        raise SourceError("that link has no host")
    reject_private(u.hostname.lower())
    return urlunsplit((u.scheme, u.netloc, u.path or "/", u.query, ""))


def reject_private(host: str) -> None:
    """Loopback, link-local and private ranges are not public prior art; they are this machine and its network."""
    if host in ("localhost", "localhost.localdomain") or host.endswith((".local", ".internal", ".localhost")):
        raise SourceError(f"{host} is not a public address")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SourceError(f"could not resolve {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or not ip.is_global:
            raise SourceError(f"{host} resolves to a non-public address ({ip})")


async def read(raw_url: str) -> IdeaPage:
    """Fetch and read the author's link. Raises SourceError; the caller degrades rather than failing the run."""
    url = normalize(raw_url)
    split = urlsplit(url)
    host = (split.hostname or "").lower().removeprefix("www.")
    if host == "github.com" and _GITHUB_REPO.match(split.path or ""):
        return await _read_github(url, split.path)
    html, final_url = await get_page(url)
    final_host = (urlsplit(final_url).hostname or "").lower()
    reject_private(final_host)  # a redirect must not land somewhere private either
    if final_host.endswith("devpost.com") and "/software/" in final_url:
        return _read_devpost(html, final_url)
    return _read_web(html, final_url)


def _read_devpost(html: str, url: str) -> IdeaPage:
    """The DOM facts here mirror ingest/devpost_page.py, which parses these same pages at ingest time."""
    soup = BeautifulSoup(html, "html.parser")
    title = _text(soup.select_one("#app-title")) or _meta(soup, "og:title") or "(untitled project)"
    tagline = _text(soup.select_one("#software-header p.large")) or _meta(soup, "og:description")
    body = ""
    left = soup.select_one("#app-details-left")
    if left is not None:
        for child in left.find_all(recursive=False):
            if child.name == "div" and not child.get("id"):  # the write-up is the one id-less div in there
                body += child.get_text("\n", strip=True) + "\n"
        body = body or left.get_text("\n", strip=True)
    tech = [t for t in (_text(x) for x in soup.select("#built-with .cp-tag")) if t]
    links = [a.get("href", "") for a in soup.select("ul[data-role='software-urls'] a[href]")]
    return _page(url, "devpost", title, tagline, body, tech, links)


def _read_web(html: str, url: str) -> IdeaPage:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    title = _meta(soup, "og:title") or _text(soup.select_one("title")) or urlsplit(url).netloc
    main = soup.select_one("main") or soup.select_one("article") or soup.body
    return _page(url, "web", title, _meta(soup, "og:description"),
                 main.get_text("\n", strip=True) if main is not None else "", [], [])


async def _read_github(url: str, path: str) -> IdeaPage:
    match = _GITHUB_REPO.match(path)
    owner, name = match.groups() if match else ("", "")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = get_settings().github_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    repo = await get_json(f"https://api.github.com/repos/{owner}/{name}", headers=headers)
    try:  # a repo with no README is normal; the description still describes the idea
        readme, _ = await get_page(f"https://api.github.com/repos/{owner}/{name}/readme",
                                   headers={**headers, "Accept": "application/vnd.github.raw"},
                                   extra_types=("application/vnd.github.raw",))
    except SourceError:
        readme = ""
    tech = [t for t in ([repo.get("language")] + list(repo.get("topics") or [])) if t]
    links = [u for u in (repo.get("homepage"), repo.get("html_url")) if u]
    return _page(repo.get("html_url") or url, "github", repo.get("full_name") or f"{owner}/{name}",
                 repo.get("description"), _markdown_text(readme), tech, links)


def _page(url: str, kind: str, title: str, tagline: str | None, body: str, tech: list[str], links: list[str]) -> IdeaPage:
    keys = {k for k in (norm_url(u) for u in [url, *links]) if k}
    return IdeaPage(url=url, kind=kind, title=(title or "").strip(), tagline=(tagline or "").strip() or None,
                    text=_BLANKS.sub("\n\n", (body or "").strip()), tech=tech[:12],
                    links=[u for u in links if u], keys=sorted(keys))


def _markdown_text(md: str) -> str:
    """Enough of a README for the planner: drop badges, code fences and heading marks, keep the prose."""
    md = re.sub(r"```.*?```", " ", md, flags=re.DOTALL)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md)
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"^[#>*\-\s]+", "", md, flags=re.MULTILINE)
    md = re.sub(r"\*\*|__|`", "", md)  # inline emphasis left over once the line markers are gone
    return _BLANKS.sub("\n\n", md.strip())


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node is not None else ""


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    return ((tag.get("content") or "").strip() or None) if tag else None


def is_self(record: SourceRecord, page: IdeaPage | None) -> bool:
    """True when a retrieved hit IS the author's own project, by the same URL keys the resolver blocks on."""
    return page is not None and bool(url_keys(record) & set(page.keys))
