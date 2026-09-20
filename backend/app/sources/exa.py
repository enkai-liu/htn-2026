"""Open-web search through Exa: the products, startups and launch posts that no dataset we ingested contains.

Exa's index is neural, so it takes natural-language queries as they are, and it returns the page text with the
hit -- which is what lets the critic quote a web page and the verifier check that quote. We also ask for a
two-sentence summary of each page: a homepage is slogans and navigation, and ranked on that text alone Cerebras
came 47th for "chipmaker for ai". The summary is written in the register of a YC or Devpost description, so one
reranker can compare a chip company with a hackathon project.
"""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urlsplit

from app.config import get_settings
from app.schemas import SourceRecord
from app.wrangle.schema_map import from_web

from .http import SourceError, post_json

API = "https://api.exa.ai/search"
TEXT_CHARS = 1500  # the pitch cap: one short field feeds the reranker and the quote check
SUMMARY_QUERY = ("What does this company, product or project make or do, and for whom? Two plain sentences. "
                 "Hardware, services and research count as much as software.")
# The same question of every page, and the kind of page it is beside the answer. Prior art is something that exists --
# a company, a product, a project -- and a search for "chipmaking for AI" returned eight explainers and news stories
# about chips: whoever wrote about the topic, not whoever works on it. The reranker liked them better than Cerebras,
# too, because an article repeats the words of the pitch. Nothing here names a domain or sees the idea (see SUMMARY_QUERY).
PRIOR_ART_KINDS = ("company", "product", "project", "research")
SUMMARY_SCHEMA = {"type": "object", "required": ["kind", "summary"], "properties": {
    "kind": {"type": "string", "enum": [*PRIOR_ART_KINDS, "article", "other"], "description": (
        "What this page is. company: the site or profile of a business or organisation. product: the page of one product or "
        "service that someone sells or ships. project: something a person or team built -- an open-source repository, a "
        "hackathon entry, a demo, a prototype. research: a paper or technical report presenting a system its authors built. "
        "article: news, an explainer, a glossary entry, a listicle, a market report, a forum thread, an opinion piece -- "
        "writing ABOUT a topic or about other people's products. other: anything else.")},
    "summary": {"type": "string", "description": SUMMARY_QUERY}}}
COVERED_ELSEWHERE = ["github.com", "news.ycombinator.com"]  # their own scouts search these with better metadata
_WORD = re.compile(r"[a-z0-9]+")
_ASIDE = re.compile(r"\s*[(\[].*?[)\]]")
_slots: dict[int, asyncio.Semaphore] = {}


def _slot() -> asyncio.Semaphore:
    """A run sends a dozen searches at once; Exa meters queries per second and a 429 is not retried. One semaphore
    per event loop, because the openjiuwen host and the tests each run their own."""
    return _slots.setdefault(id(asyncio.get_running_loop()), asyncio.Semaphore(4))


async def search(query: str, *, n: int = 5, category: str | None = None) -> list[SourceRecord]:
    """`category="company"` restricts Exa to company homepages: the lane that finds who already sells this,
    whatever they sell, where the plain lane returns whoever wrote about it."""
    key = get_settings().exa_api_key
    if not key:
        raise SourceError("EXA_API_KEY is not set")
    body = {"query": query, "type": "auto", "numResults": n, "excludeDomains": COVERED_ELSEWHERE,
            "contents": {"text": {"maxCharacters": TEXT_CHARS}, "summary": {"query": SUMMARY_QUERY, "schema": SUMMARY_SCHEMA}}}
    if category:
        body["category"] = category
    async with _slot():
        data = await post_json(API, headers={"x-api-key": key}, body=body)
    return [from_web(_read_summary(r)) for r in data.get("results", []) if _is_page(r.get("url")) and (r.get("title") or r.get("text"))]


def _read_summary(hit: dict) -> dict:
    """With a schema the summary arrives as a JSON string. One that does not parse is kept as the plain summary it
    then is, and its page as a page of no known kind: a failed classification is not a reason to lose a hit."""
    try:
        got = json.loads(hit.get("summary") or "")
    except ValueError:
        return hit
    if not isinstance(got, dict):
        return hit
    return hit | {"summary": got.get("summary"), "kind": got.get("kind")}


def is_prior_art(r: SourceRecord) -> bool:
    """False for a page that is writing about the topic. A page whose kind nobody could tell stays."""
    return r.retrieval.get("kind") not in ("article", "other")


def _is_page(url: str | None) -> bool:
    """Exa has returned its own directory entries (exa.ai/library/...) and an address with no host (https://http/www...)."""
    host = (urlsplit(url or "").hostname or "").lower()
    return "." in host and host.removeprefix("www.") != "exa.ai"


def _squash(s: str) -> str:
    return "".join(_WORD.findall(s.lower()))


async def lookup(name: str, hint: str = "") -> list[SourceRecord]:
    """Find the page of one named company or product. The name is a lead from the planner's memory, not evidence:
    a hit only counts if the name is in its title or its address, so a product that does not exist finds nothing
    rather than its nearest neighbour (looking up "Cerebras" also returns a medical company called Cerebra)."""
    want = _squash(_ASIDE.sub("", name))  # the planner writes "Google (TPU)": the aside helps the search, not the match
    if len(want) < 3:
        return []
    hits = await search(f"{name} {hint}".strip(), n=3, category="company")
    return [r for r in hits if want in _squash(r.title) or want in _squash(r.url)][:1]
