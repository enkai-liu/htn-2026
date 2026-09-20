"""Blocking: cheap candidate generation so entity matching is not O(n^2) LLM calls."""
from __future__ import annotations

import re
from itertools import combinations
from urllib.parse import parse_qs, urlparse

from app.schemas import SourceRecord

_GENERIC_HOSTS = {"github.com", "devpost.com", "youtube.com", "youtu.be", "news.ycombinator.com", "twitter.com", "x.com",
                  "linkedin.com", "figma.com", "docs.google.com", "drive.google.com", "vercel.app", "netlify.app", "herokuapp.com"}

_ID_IN_QUERY = {("news.ycombinator.com", "/item"): "id", ("youtube.com", "/watch"): "v"}


def norm_url(url: str) -> str | None:
    """Canonical key for a URL: host + path, no scheme/www/query/trailing slash. Repo URLs keep owner/name only."""
    try:
        u = urlparse(url if "://" in url else f"https://{url}")
    except ValueError:
        return None
    host = (u.hostname or "").lower().removeprefix("www.")
    if not host:
        return None
    path = re.sub(r"/+$", "", u.path or "").lower()
    if host == "github.com":
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2:
            return None
        path = "/" + "/".join(parts[:2]).removesuffix(".git")
    if host in _GENERIC_HOSTS and not path:
        return None
    if (host, path) in _ID_IN_QUERY:  # the page IS its query string: without it every HN story was one key, and one entity
        ident = parse_qs(u.query).get(_ID_IN_QUERY[host, path])
        if not ident:
            return None
        path += f"?{_ID_IN_QUERY[host, path]}={ident[0]}"
    return host + path


def url_keys(r: SourceRecord) -> set[str]:
    return {k for k in (norm_url(u) for u in [r.url, *r.links]) if k}


def norm_name(title: str) -> str:
    name = title.strip()
    if " " not in name and "/" in name:
        name = name.split("/")[-1]  # "owner/repo" -> "repo"
    name = re.sub(r"^(show hn|launch hn|ask hn)\s*:\s*", "", name, flags=re.I)
    name = re.split(r"\s+[-–—|]\s+|:\s+|,\s+", name, maxsplit=1)[0]  # "PitchProbe – find out who..." -> "PitchProbe"
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def trigrams(s: str) -> set[str]:
    s = f"  {s} "
    return {s[i:i + 3] for i in range(len(s) - 2)}


def name_sim(a: str, b: str) -> float:
    ta, tb = trigrams(norm_name(a)), trigrams(norm_name(b))
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def candidate_pairs(records: list[SourceRecord], *, name_threshold: float = 0.6) -> list[tuple[str, str, dict]]:
    """Pairs worth adjudicating, with their signals. url_xref pairs are decided by rule; the rest go to the LLM."""
    out = []
    keys = {r.rid: url_keys(r) for r in records}
    for a, b in combinations(records, 2):
        shared = keys[a.rid] & keys[b.rid]
        ns = name_sim(a.title, b.title)
        if shared or ns >= name_threshold:
            out.append((a.rid, b.rid, {"url_xref": bool(shared), "shared_urls": sorted(shared)[:3], "name_sim": round(ns, 2)}))
    return out
