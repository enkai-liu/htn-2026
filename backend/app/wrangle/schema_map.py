"""Schema matching for LIVE sources: heterogeneous API payloads -> the canonical SourceRecord.

Dataset-backed sources (Devpost, YC) are mapped at ingest time in ingest/schema_map.py. Every mapped field
records its provenance: `source` (copied), `normalized` (reshaped), `imputed` (inferred, shown as such in the UI).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Any

from app.schemas import SourceRecord
from app.wrangle.blocking import norm_url

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# The mapping table shown in the UI / README (canonical field <- source field).
MAPPING_TABLE: dict[str, dict[str, str]] = {
    "hn": {"title": "title", "description": "story_text", "url": "objectID -> news.ycombinator.com/item?id=", "links": "url",
           "date": "created_at", "traction": "points, num_comments"},
    "github": {"title": "full_name", "tagline": "description", "url": "html_url", "links": "homepage", "tags": "topics",
               "tech": "language", "date": "created_at", "status": "archived + pushed_at (derived)", "traction": "stargazers_count, pushed_at"},
    "web": {"title": "title", "description": "text (page body, first 1500 chars)", "url": "url", "date": "publishedDate",
            "traction": "author"},
    "devpost": {"title": "title", "tagline": "brief_desc | tagline", "description": "full_desc | description", "tags": "tags",
                "tech": "built_with (or imputed from 'How we built it')", "year": "hackathons.json submission_period_dates",
                "traction": "prize -> is_winner", "links": "other_links"},
    "yc": {"title": "name", "tagline": "one_liner", "description": "long_description", "year": "batch", "status": "status",
           "links": "website", "tags": "industries + tags"},
}


def clean(text: str | None, limit: int | None = None) -> str:
    out = _WS.sub(" ", _TAG.sub(" ", text or "")).strip()
    return out[:limit] if limit else out


def _pitch(*parts: str | None, limit: int = 1500) -> str:
    return clean(". ".join(p.strip().rstrip(".") for p in parts if p and p.strip()), limit)


def from_hn(hit: dict[str, Any]) -> SourceRecord:
    created = _parse_dt(hit.get("created_at"))
    body = clean(hit.get("story_text"))
    links = [hit["url"]] if hit.get("url") else []
    return SourceRecord(
        rid=f"hn:{hit['objectID']}", source="hn", url=f"https://news.ycombinator.com/item?id={hit['objectID']}",
        title=clean(hit.get("title")) or "(untitled)", description=body, pitch=_pitch(hit.get("title"), body),
        year=created.year if created else None, date=created.date() if created else None,
        date_precision="day" if created else None, links=links, lang="en",
        traction={"points": hit.get("points") or 0, "comments": hit.get("num_comments") or 0},
        field_provenance={"title": "source", "description": "normalized", "date": "source", "links": "source"},
    )


def from_github(repo: dict[str, Any], *, now: dt.datetime | None = None) -> SourceRecord:
    now = now or dt.datetime.now(dt.timezone.utc)
    created, pushed = _parse_dt(repo.get("created_at")), _parse_dt(repo.get("pushed_at"))
    if repo.get("archived"):
        status, status_prov = "dead", "source"
    elif pushed is None:
        status, status_prov = "unknown", "source"
    else:  # dormant if nothing was pushed for 18 months: a derived judgement, so it is marked imputed
        status, status_prov = ("dormant" if (now - pushed).days > 548 else "active"), "imputed"
    links = [u for u in (repo.get("homepage"),) if u]
    return SourceRecord(
        rid=f"github:{repo['full_name'].lower()}", source="github", url=repo["html_url"], title=repo["full_name"],
        tagline=clean(repo.get("description")) or None, description=clean(repo.get("description")),
        pitch=_pitch(repo.get("name"), repo.get("description")), year=created.year if created else None,
        date=created.date() if created else None, date_precision="day" if created else None,
        tags=list(repo.get("topics") or []), tech=[repo["language"].lower()] if repo.get("language") else [],
        status=status, links=links, lang="en",
        traction={"stars": repo.get("stargazers_count") or 0, "pushed_at": repo.get("pushed_at")},
        field_provenance={"title": "source", "tagline": "source", "tags": "source", "tech": "normalized",
                          "status": status_prov, "date": "source"},
    )


def from_web(hit: dict[str, Any]) -> SourceRecord:
    """An Exa search result. A web page has no native id, so the rid is a hash of its normalised URL: the same page
    found by two queries is one record, and the resolver still merges it with a Devpost/GitHub record by URL key."""
    url = hit["url"]
    published = _parse_dt(hit.get("publishedDate"))
    body = clean(hit.get("text"))
    title = clean(hit.get("title")) or (norm_url(url) or url)[:80]
    # Exa's summary of the page, not the page's own words: it leads the pitch because a homepage's first 1,500
    # characters are slogans and navigation, and it is marked imputed so nobody takes it for the site's copy.
    summary = clean(hit.get("summary"), 500) or None
    return SourceRecord(
        rid="web:" + hashlib.sha1((norm_url(url) or url).encode()).hexdigest()[:12], source="web", url=url, title=title,
        tagline=summary, description=body[:4000], pitch=_pitch(title, summary, body), year=published.year if published else None,
        date=published.date() if published else None, date_precision="day" if published else None,
        traction={"author": hit["author"]} if hit.get("author") else {},
        field_provenance={"title": "source", "description": "normalized"} | ({"date": "source"} if published else {})
        | ({"tagline": "imputed"} if summary else {}),
        retrieval={"kind": hit["kind"]} if hit.get("kind") else {},  # company, product, project, research, article, other
    )


def _parse_dt(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
