from __future__ import annotations

from app.config import get_settings
from app.schemas import SourceRecord
from app.wrangle.schema_map import from_github

from .http import get_json

API = "https://api.github.com/search/repositories"


async def search(query: str, *, n: int = 8) -> list[SourceRecord]:
    token = get_settings().github_token
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"  # 30 req/min instead of 10
    data = await get_json(API, params={"q": query, "per_page": n, "sort": "stars"}, headers=headers)
    return [from_github(r) for r in data.get("items", [])]
