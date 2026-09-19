"""Search-side primitives for AXIS 2 (facet rarity) - docs/design-full.md section 2.6.

    rarity_f = 1 - log(1 + df_f) / log(1 + 2000)             df_f  = docs matching most words of one facet (FACET_MATCH)
    pair     = 1 - log(1 + df(purpose AND mechanism)) / log(1 + 200)
    cliche   = |idea_terms ∩ significant_text(neighbours)| / |idea_terms|
    O2       = 100 * (0.5 * mean_f rarity_f + 0.3 * pair + 0.2 * (1 - cliche))      (assembled in scoring/axes.py)

Network functions: neighbourhood_stats (two-step significant_text), facet_df, pair_df (`_count`).
Pure functions:    rarity_from_df, pair_rarity, cliche_overlap, parse_neighbourhood_response, build_* bodies.
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable, Sequence

from app.config import get_settings
from app.search.es import excluded_flags_clause, get_async_es, require_elastic

FACET_DF_CAP = 2000
PAIR_DF_CAP = 200
# minimum_should_match for a facet phrase: 1-2 terms must all match, 3-6 terms need half, longer phrases any 3.
# Requiring ALL words made every LLM-written facet phrase unique (df=0, even for 'AI chatbot for student mental health'),
# so every idea scored as maximally rare; long phrases (the planner writes 10-20 words for a detailed pitch) stayed
# unique even at 50%. Measured on the 8.5k corpus: cliches (short or long phrasing) -> mean rarity 0.36-0.43,
# a crowded plant-care idea -> 0.45-0.49, a novel idea (acoustic varroa-mite detection) -> 0.95.
FACET_MATCH = "2<-50% 6<3"


# --------------------------------------------------------------------------------------
# Pure maths
# --------------------------------------------------------------------------------------
def rarity_from_df(df: int | float, cap: int = FACET_DF_CAP) -> float:
    """1.0 = nobody has this facet, 0.0 = at least `cap` documents do. Log-scaled, clamped to [0, 1]."""
    df = max(0.0, float(df))
    if cap <= 0:
        raise ValueError("cap must be positive")
    return max(0.0, min(1.0, 1.0 - math.log1p(df) / math.log1p(cap)))


def pair_rarity(df: int | float, cap: int = PAIR_DF_CAP) -> float:
    """Rarity of a facet *combination* (purpose AND mechanism); saturates much earlier than a single facet."""
    return rarity_from_df(df, cap)


_WORD = re.compile(r"[a-z0-9][a-z0-9+#.-]*[a-z0-9+#]|[a-z0-9]")
_STOP = frozenset(
    "a an and are as at be by for from has have in into is it its of on or our so that the their them then "
    "there these this to was we were which who will with you your can using use used uses via app application "
    "platform project tool system build built make makes help helps user users".split()
)


def idea_terms(text: str) -> set[str]:
    """Content words of the idea, lightly stemmed the way the `english` analyzer would (plural s)."""
    out = set()
    for w in _WORD.findall(text.lower()):
        if w in _STOP or len(w) < 3:
            continue
        out.add(w[:-1] if w.endswith("s") and not w.endswith("ss") and len(w) > 3 else w)
    return out


def cliche_overlap(idea_text: str, cliche_terms: Iterable[str]) -> float:
    """Share of the idea's content words that are neighbourhood clichés (significant_text keys are
    analyzed tokens, so compare on a light stem of both sides). 0.0 when the idea has no content words."""
    terms = idea_terms(idea_text)
    if not terms:
        return 0.0
    cliches = set()
    for t in cliche_terms:
        t = t.lower()
        cliches.add(t)
        cliches.add(t[:-1] if t.endswith("s") and len(t) > 3 else t)
    hits = {t for t in terms if t in cliches or any(t.startswith(c) and len(c) >= 4 for c in cliches)}
    return len(hits) / len(terms)


# --------------------------------------------------------------------------------------
# Request bodies (pure, unit-tested)
# --------------------------------------------------------------------------------------
def build_neighbourhood_body(ids: Sequence[str]) -> dict[str, Any]:
    """Step 2 of the two-step significant_text: foreground = the top-50 neighbour ids, background = the
    whole index. `filter_duplicate_text` stops boilerplate copied across write-ups from looking significant."""
    return {
        "size": 0,
        "query": {"ids": {"values": list(ids)}},
        "aggs": {
            "cliches": {"significant_text": {"field": "pitch", "size": 20, "min_doc_count": 3, "filter_duplicate_text": True}},
            "tag_cliches": {"significant_terms": {"field": "tags", "size": 15, "min_doc_count": 3}},
            "tech_cliches": {"significant_terms": {"field": "tech", "size": 15, "min_doc_count": 3}},
            "by_year": {"terms": {"field": "year", "size": 12, "order": {"_key": "asc"}}},
            "winners": {"filter": {"term": {"is_winner": True}}},
        },
    }


def build_facet_count_body(*facets: str, sources: Iterable[str] | None = None) -> dict[str, Any]:
    """`_count` body: documents whose pitch matches EVERY facet, each facet by FACET_MATCH of its words."""
    facets = tuple(f.strip() for f in facets if f and f.strip())
    if not facets:
        raise ValueError("at least one non-empty facet is required")
    bool_q: dict[str, Any] = {
        "must": [{"match": {"pitch": {"query": f, "minimum_should_match": FACET_MATCH}}} for f in facets],
        "must_not": [excluded_flags_clause()],
    }
    if sources:
        bool_q["filter"] = [{"terms": {"source": list(sources)}}]
    return {"query": {"bool": bool_q}}


def _buckets(agg: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [
        {"term": b.get("key"), "doc_count": b.get("doc_count", 0), "bg_count": b.get("bg_count"), "score": b.get("score")}
        for b in (agg or {}).get("buckets", [])
    ]


def parse_neighbourhood_response(resp: dict[str, Any]) -> dict[str, Any]:
    aggs = resp.get("aggregations") or {}
    total = (resp.get("hits") or {}).get("total")
    n = total.get("value") if isinstance(total, dict) else total
    return {
        "n": n or 0,
        "cliche_terms": _buckets(aggs.get("cliches")),
        "tag_cliches": _buckets(aggs.get("tag_cliches")),
        "tech_cliches": _buckets(aggs.get("tech_cliches")),
        "by_year": [{"year": b.get("key"), "count": b.get("doc_count", 0)} for b in (aggs.get("by_year") or {}).get("buckets", [])],
        "winners": (aggs.get("winners") or {}).get("doc_count", 0),
    }


# --------------------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------------------
async def neighbourhood_stats(ids: Sequence[str], *, es: Any = None, index: str | None = None) -> dict[str, Any]:
    """Cliché terms (significant_text on pitch), tag/tech clichés (significant_terms), by-year counts and
    the number of winners among the given neighbour `_id`s (step 1 = the ids of a hybrid search)."""
    if not ids:
        return parse_neighbourhood_response({})
    settings = get_settings() if es is not None else require_elastic()
    client = es if es is not None else get_async_es()
    resp = await client.search(index=index or settings.es_index, body=build_neighbourhood_body(ids), track_total_hits=True)
    return parse_neighbourhood_response(dict(resp))


async def _count(body: dict[str, Any], *, es: Any = None, index: str | None = None) -> int:
    settings = get_settings() if es is not None else require_elastic()
    client = es if es is not None else get_async_es()
    resp = await client.count(index=index or settings.es_index, body=body)
    return int(resp["count"])


async def facet_df(facet_text: str, *, sources: Iterable[str] | None = None, es: Any = None, index: str | None = None) -> int:
    """Document frequency of one facet: pitches matching most of its words (FACET_MATCH)."""
    return await _count(build_facet_count_body(facet_text, sources=sources), es=es, index=index)


async def pair_df(a: str, b: str, *, sources: Iterable[str] | None = None, es: Any = None, index: str | None = None) -> int:
    """Document frequency of a facet combination: pitches matching `a` AND `b` (each by FACET_MATCH)."""
    return await _count(build_facet_count_body(a, b, sources=sources), es=es, index=index)
