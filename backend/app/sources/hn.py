from __future__ import annotations

from app.schemas import SourceRecord
from app.wrangle.schema_map import from_hn

from .http import get_json

API = "https://hn.algolia.com/api/v1/search"


async def search(query: str, *, n: int = 8) -> list[SourceRecord]:
    data = await get_json(API, params={"query": query, "tags": "story", "hitsPerPage": n})
    return [from_hn(h) for h in data.get("hits", []) if h.get("title")]
