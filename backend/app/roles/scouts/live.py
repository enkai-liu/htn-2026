from __future__ import annotations

from app.orchestration.registry import register
from app.schemas import SourceRecord
from app.sources import exa, github, hn

from .base import ScoutRole


class HNScout(ScoutRole):
    id, source, tool = "scout.hn", "hn", "hn.algolia_search"

    async def search(self, query: str, n: int) -> list[SourceRecord]:
        return await hn.search(query, n=n)


class GitHubScout(ScoutRole):
    id, source, tool = "scout.github", "github", "github.search_repositories"
    per_query = 6  # at most 6 GitHub queries per run stays well inside the search rate limit

    async def search(self, query: str, n: int) -> list[SourceRecord]:
        return await github.search(query, n=n)


class WebScout(ScoutRole):
    id, source, tool = "scout.web", "web", "exa.search"
    per_query = 5  # each hit carries 1,500 characters of page text into the reranker: fewer, fuller records

    async def search(self, query: str, n: int) -> list[SourceRecord]:
        return await exa.search(query, n=n)


register("scout.hn")(HNScout)
register("scout.github")(GitHubScout)
register("scout.web")(WebScout)
