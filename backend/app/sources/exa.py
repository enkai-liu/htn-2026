"""Open-web search through Exa: the products, startups and launch posts that no dataset we ingested contains.

Exa's index is neural, so it takes the planner's natural-language queries as they are, and it returns the page
text with the hit -- which is what lets the critic quote a web page and the verifier check that quote.
"""
from __future__ import annotations

from app.config import get_settings
from app.schemas import SourceRecord
from app.wrangle.schema_map import from_web

from .http import SourceError, post_json

API = "https://api.exa.ai/search"
TEXT_CHARS = 1500  # the pitch cap: one short field feeds the reranker and the quote check
COVERED_ELSEWHERE = ["github.com", "news.ycombinator.com"]  # their own scouts search these with better metadata


async def search(query: str, *, n: int = 5) -> list[SourceRecord]:
    key = get_settings().exa_api_key
    if not key:
        raise SourceError("EXA_API_KEY is not set")
    data = await post_json(API, headers={"x-api-key": key}, body={
        "query": query, "type": "auto", "numResults": n, "excludeDomains": COVERED_ELSEWHERE,
        "contents": {"text": {"maxCharacters": TEXT_CHARS}}})
    return [from_web(r) for r in data.get("results", []) if r.get("url") and (r.get("title") or r.get("text"))]
