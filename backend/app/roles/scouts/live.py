from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlsplit

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
    """The one scout that is not a software catalogue: Devpost, YC, GitHub and HN all lean to code, so whoever
    makes chips, runs clinics or sells a service is found here or nowhere. Three ways in: every query as company
    homepages, the first of them again as pages of any kind (a product page, a launch post, a paper -- where no
    company site says it), and a lookup of each player the planner named.

    What comes back is prior art or it is nothing: a news story, an explainer or a listicle about the topic is not a
    thing that exists beside the idea, and it is set aside before it is scored."""

    id, source, tool = "scout.web", "web", "exa.search[companies]"
    per_query = 8  # each hit carries 1,500 characters of page text into the reranker: fewer, fuller records
    page_queries, per_page_query, max_lookups = 2, 8, 8

    async def search(self, query: str, n: int) -> list[SourceRecord]:
        return [r for r in await exa.search(query, n=n, category="company") if exa.is_prior_art(r)]

    def collapse(self, new: list[SourceRecord], ctx) -> list[SourceRecord]:
        """A company's homepage, pricing page and blog are one company: counted apart they crowd the map and the
        score with a single competitor. Where the homepage is among the hits it stands for its site, at the best
        similarity any of its pages earned; a host with no homepage hit (a news site's articles) is left alone.
        A page found later, on a follow-up about a company already on the board, is kept -- it is what the critic
        asked for -- and linked to that homepage, which is the key the resolver merges on."""
        def site(r: SourceRecord) -> str:
            return (urlsplit(r.url).hostname or r.url).lower().removeprefix("www.")

        def is_home(r: SourceRecord) -> bool:
            return not urlsplit(r.url).path.strip("/")

        known = {site(r): r for r in ctx.board.records.values() if r.source == "web" and is_home(r)}
        sites: dict[str, list[SourceRecord]] = defaultdict(list)
        for r in new:
            sites[site(r)].append(r)
        out: list[SourceRecord] = []
        for host, pages in sites.items():
            home = next((r for r in pages if is_home(r)), None)
            if home is None or len(pages) == 1:
                for r in pages if host in known else []:
                    r.links.append(known[host].url)
                out += pages
                continue
            best = max(pages, key=lambda r: float(r.retrieval.get("rerank_score") or 0))
            home.retrieval |= {"rerank_score": best.retrieval.get("rerank_score"), "pages": len(pages)}
            out.append(home)
        return out

    def extra(self, payload, ctx, phase):
        async def run(tool: str, shown: str, job) -> list[SourceRecord]:
            await ctx.emit("tool.call", {"tool": tool, "args_summary": shown[:120]}, phase=phase)
            found = await job
            hits = [r for r in found if exa.is_prior_art(r)]
            aside = f", {len(found) - len(hits)} articles set aside" if len(found) > len(hits) else ""
            await ctx.emit("tool.result", {"tool": tool, "summary": f"{len(hits)} hits{aside}", "n_hits": len(hits)}, phase=phase)
            return hits

        queries = [q for q in (payload.get("queries") or [payload.get("query")]) if q]
        hint = str(payload.get("hint") or "")
        return [(q, run("exa.search[pages]", q, exa.search(q, n=self.per_page_query)))
                for q in queries[:self.page_queries]] + [
            (f"lookup: {name}", run("exa.lookup", name, exa.lookup(name, hint)))
            for name in list(dict.fromkeys(payload.get("lookups") or []))[:self.max_lookups]]


register("scout.hn")(HNScout)
register("scout.github")(GitHubScout)
register("scout.web")(WebScout)
