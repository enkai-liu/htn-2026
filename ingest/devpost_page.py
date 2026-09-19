"""Parse normally-served public Devpost HTML: a project page -> SourceRecord, a hackathon gallery page ->
project links. Pure functions (HTML in, data out) so they are testable from saved fixtures.

DOM facts (checked 2026-09-19 on devpost.com/software/hackanalyzer and a /project-gallery page):
  #app-title                         project name            #software-header p.large      tagline
  #app-details-left > div (no id)    write-up HTML (h2/p/ul) #built-with .cp-tag           tech
  ul[data-role=software-urls] a      outbound links          #submissions .software-list-content  hackathon + .winner labels
  time.timeago[datetime]             update timestamps       #app-team .software-team-member      team
  gallery:  .gallery-item a.link-to-software, h5, p.tagline, aside.entry-badge img.winner, ul.pagination li.next a
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ingest import common  # noqa: F401  (sys.path side effect)
from ingest.parse_sections import build_pitch, clean_text, extract_tech, guess_lang, html_to_text, normalise_ws, parse_sections
from ingest.schema_map import normalise_links, slug_from_url

from app.schemas.records import SourceRecord


def _text(node: Any) -> str:
    return normalise_ws(node.get_text(" ", strip=True)) if node is not None else ""


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    return (tag.get("content") or "").strip() or None if tag else None


def parse_project_page(html: str, url: str | None = None) -> SourceRecord:
    soup = BeautifulSoup(html, "html.parser")
    url = (url or _meta(soup, "og:url") or "").split("?")[0].rstrip("/")
    if "/software/" not in url:
        raise ValueError(f"not a Devpost project page: {url!r}")
    title = _text(soup.select_one("#app-title")) or (_meta(soup, "og:title") or slug_from_url(url))
    tagline = _text(soup.select_one("#software-header p.large")) or _meta(soup, "og:description")
    prov: dict[str, str] = {"url": "source", "title": "source", "description": "normalized", "pitch": "normalized"}
    if tagline:
        prov["tagline"] = "source"

    # The write-up is the id-less <div> inside #app-details-left (siblings: #gallery, #built-with, nav.app-links).
    body_html = ""
    left = soup.select_one("#app-details-left")
    if left is not None:
        for child in left.find_all(recursive=False):
            if child.name == "div" and not child.get("id"):
                body_html += str(child)
    description = clean_text(html_to_text(body_html)) if body_html else ""
    sections = parse_sections(description)

    tech, tech_prov = extract_tech([_text(t) for t in soup.select("#built-with .cp-tag")], sections=sections)
    if tech_prov:
        prov["tech"] = tech_prov
    links = normalise_links([a.get("href", "") for a in soup.select("ul[data-role='software-urls'] a[href]")])
    if links:
        prov["links"] = "source"

    traction: dict[str, Any] = {}
    prizes: list[str] = []
    year = date = precision = None
    for i, block in enumerate(soup.select("#submissions .software-list-content")):
        link = block.select_one("p a[href]") or block.select_one("a[href]")
        if i == 0 and link is not None:
            traction["hackathon"] = _text(link)
            traction["hackathon_url"] = link.get("href")
            host = urlsplit(link.get("href", "")).netloc
            if host.endswith(".devpost.com"):
                traction["hackathon_id"] = host.split(".")[0]
        for li in block.select("ul li"):
            if li.select_one(".winner") is not None:
                prizes.append(re.sub(r"^winner\s+", "", _text(li), flags=re.I))
    traction["is_winner"] = bool(prizes)
    if prizes:
        traction["prize"] = prizes
    members = soup.select("#app-team .software-team-member")
    if members:
        traction["team_size"] = len(members)
    likes = soup.select_one(".software-likes .side-count, a.like-button .side-count")
    if likes is not None and _text(likes).isdigit():
        traction["likes"] = int(_text(likes))

    stamps = []
    for t in soup.select("time[datetime]"):
        try:
            stamps.append(dt.datetime.fromisoformat(t["datetime"]))
        except ValueError:
            continue
    if stamps:  # the earliest update on the page is the "started this project" entry
        date = min(stamps).date()
        year, precision = date.year, "day"
        prov.update(date="normalized", year="normalized")
    else:
        m = re.search(r"(20\d{2})", str(traction.get("hackathon_url") or "") + " " + str(traction.get("hackathon") or ""))
        if m:
            year, precision = int(m.group(1)), "year"
            prov["year"] = "imputed"

    pitch = build_pitch(title, tagline, description, sections=sections)
    lang = guess_lang(pitch)
    if lang != "und":
        prov["lang"] = "imputed"
    return SourceRecord(
        rid=f"devpost:{slug_from_url(url)}", source="devpost", url=url, title=title, tagline=tagline or None,
        description=description, pitch=pitch, year=year, date=date, date_precision=precision, tags=[], tech=tech,
        status="unknown", traction=traction, links=links, lang=lang, field_provenance=prov,
    )


def parse_gallery_page(html: str, base_url: str) -> tuple[list[dict[str, Any]], str | None]:
    """-> ([{url, title, tagline, is_winner}], next_page_url or None)"""
    soup = BeautifulSoup(html, "html.parser")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in soup.select(".gallery-item"):
        a = item.select_one("a.link-to-software[href]")
        if a is None:
            continue
        url = a["href"].split("?")[0].rstrip("/")
        if "/software/" not in url or url in seen:
            continue
        seen.add(url)
        entries.append({
            "url": url,
            "title": _text(item.select_one("h5")),
            "tagline": _text(item.select_one("p.tagline")) or None,
            "is_winner": item.select_one("aside.entry-badge img.winner, .winner") is not None,
        })
    nxt = soup.select_one("ul.pagination li.next:not(.unavailable) a[href]")
    next_url = urljoin(base_url, nxt["href"]) if nxt is not None and nxt.get("href") not in (None, "#") else None
    return entries, next_url
