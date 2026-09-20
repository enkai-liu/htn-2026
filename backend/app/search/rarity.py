"""Search-side primitives for AXIS 2 (facet rarity) - docs/design-full.md section 2.6.

    rarity_f = mean IDF of the k most distinctive terms of facet f, / log(N+1)   (length-invariant)
    pair     = (1 - npmi(purpose, mechanism)) / 2            observed co-occurrence vs. what independence predicts
    cliche   = |idea_terms ∩ significant_text(neighbours)| / |idea_terms|
    O2       = 100 * (0.5 * mean_f rarity_f + 0.3 * pair + 0.2 * (1 - cliche))      (assembled in scoring/axes.py)

The pair term used to be `1 - log(1+df_ab)/log(1+200)`, which only counts how many documents match both facets
and so cannot distinguish a rare combination of two common facets (what a hackathon idea wants) from a pair whose
halves are both rare. NPMI compares the joint count with the product of the marginals and does. `pair_rarity`
remains the fallback for when the corpus size is unknown.

Per-facet rarity no longer comes from a document count at all. A `minimum_should_match` rule has to serve
both a three-word facet and a twenty-word one, and none does: requiring every word made every LLM-written
phrase unique, and the fix for that (any 3 words of a long phrase) made a 20-word mechanism match 12.6% of
the corpus and score 0.089. `facet_rarity_from_idf` reads the term-frequency profile instead, which is
length-invariant by construction.

Network functions: neighbourhood_stats, facet_term_dfs, facet_profile, facet_df, pair_df, corpus_size, pair_stats.
Pure functions:    rarity_from_df, idf, facet_rarity_from_idf, pair_rarity, npmi, pair_atypicality,
                   cliche_overlap, parse_neighbourhood_response, parse_term_df_response, build_* bodies.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

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
    """1.0 = nobody has this facet, 0.0 = at least `cap` documents do. Log-scaled, clamped to [0, 1].

    Still used for the NPMI marginals, where a lenient match rule largely cancels between the joint and the
    product of the marginals. NOT used for per-facet rarity any more: see `facet_rarity_from_idf`."""
    df = max(0.0, float(df))
    if cap <= 0:
        raise ValueError("cap must be positive")
    return max(0.0, min(1.0, 1.0 - math.log1p(df) / math.log1p(cap)))


# --------------------------------------------------------------------------------------
# Per-facet rarity from the term-frequency profile (replaces a single FACET_MATCH document count)
# --------------------------------------------------------------------------------------
IDF_TOP_K = 3


def idf(df: int, n: int) -> float:
    """Smoothed inverse document frequency in nats: log((N+1)/(df+1)). 0 for a term in every document,
    log(N+1) for one the corpus has never seen."""
    if n <= 0:
        return 0.0
    return math.log((n + 1) / (max(0, int(df)) + 1))


def facet_rarity_from_idf(term_dfs: Mapping[str, int], n: int, k: int = IDF_TOP_K) -> float | None:
    """Rarity of ONE facet from the corpus frequency of its words: the mean IDF of its k most distinctive
    terms, divided by log(N+1) so the result lands in [0, 1].

    A facet is not a phrase the corpus either contains or does not; it is a bundle of concepts, and its
    rarity is how unusual the most distinctive of those concepts are. Counting documents that "match the
    facet" needed a `minimum_should_match` rule, and no such rule survives both ends: requiring every word
    made every LLM-written phrase unique (df=0, everything maximally rare), while the fix for that -- any 3
    words of a long phrase -- made a 20-word mechanism match 1,020 of 8,110 documents (12.6% of the corpus)
    for rarity 0.089. That number measured the length of the phrase, not the rarity of the idea.

    Taking a FIXED k most-distinctive terms is length-invariant by construction: a one-word facet and a
    twenty-word facet are scored on the same scale. Measured on the 8.1k corpus:

        'Acoustic detection of varroa mite wingbeats'                       1.00   (beehive/mite/varroa unseen)
        'Team of AI agents that search prior art, debate novelty, ...'      0.71   (was 0.089)
        'A web app with a React frontend and a Flask backend'               0.56
        'An AI chatbot powered by a large language model'                   0.40
        'help students study more effectively'                              0.39
    """
    if n <= 0 or not term_dfs:
        return None
    top = sorted((idf(df, n) for df in term_dfs.values()), reverse=True)[: max(1, k)]
    return max(0.0, min(1.0, (sum(top) / len(top)) / math.log(n + 1)))


def build_term_df_body(terms: Sequence[str], sources: Iterable[str] | None = None) -> dict[str, Any]:
    """One `filters` aggregation with a bucket per term: exact whole-index document frequencies in a single
    request. (`_termvectors` also reports doc_freq, but its statistics are shard-local.)"""
    terms = [t for t in dict.fromkeys(t.strip() for t in terms) if t]
    if not terms:
        raise ValueError("at least one term is required")
    bool_q: dict[str, Any] = {"must_not": [excluded_flags_clause()]}
    if sources:
        bool_q["filter"] = [{"terms": {"source": list(sources)}}]
    return {"size": 0, "query": {"bool": bool_q},
            "aggs": {"term_df": {"filters": {"filters": {t: {"match": {"pitch": t}} for t in terms}}}}}


def parse_term_df_response(resp: dict[str, Any]) -> dict[str, int]:
    buckets = ((resp.get("aggregations") or {}).get("term_df") or {}).get("buckets") or {}
    return {t: int(b.get("doc_count", 0)) for t, b in buckets.items()} if isinstance(buckets, dict) else {}


def pair_rarity(df: int | float, cap: int = PAIR_DF_CAP) -> float:
    """Rarity of a facet *combination* (purpose AND mechanism); saturates much earlier than a single facet.

    Kept as the fallback for when the corpus size is unknown. Prefer `npmi` + `pair_atypicality`: a raw pair df
    cannot tell "rare combination of two common facets" (the interesting case) from "both facets are rare"."""
    return rarity_from_df(df, cap)


def npmi(df_a: int, df_b: int, df_ab: int, n: int) -> float | None:
    """Normalised pointwise mutual information of two facets co-occurring in the corpus, in [-1, +1].

        pmi  = log( p(a,b) / (p(a) p(b)) )          p(x) = df_x / n
        npmi = pmi / -log p(a,b)                    (Bouma normalisation)

    +1  the two facets ALWAYS appear together: a fixed phrase ("machine learning" + "neural network")
     0  independent: they co-occur exactly as often as chance predicts
    -1  they never appear together: nobody has combined them -> this is the whitespace

    This is the quantity AXIS 2 actually wants. `1 - log(1+df_ab)/log(1+200)` only sees how many documents match
    both, so "help students study" + "flashcards" (3,000 hits, but ~4x MORE than independence predicts: a cliche
    pairing) and "help students study" + "acoustic sensing" (3 hits, ~26x LESS than chance: genuinely unusual)
    score alike. NPMI separates them, and it is the same observed-vs-expected comparison as the z-score in
    Uzzi et al., *Atypical Combinations and Scientific Impact* (Science, 2013).

    Returns None when the corpus size is unknown (n <= 0); the caller then falls back to `pair_rarity`.
    """
    if n <= 0:
        return None
    df_a, df_b, df_ab = max(0, int(df_a)), max(0, int(df_b)), max(0, int(df_ab))
    df_ab = min(df_ab, df_a, df_b, n)  # a co-occurrence count cannot exceed either marginal
    if df_ab == 0:
        return -1.0  # never observed together; the limit of the formula, and the convention
    p_ab = df_ab / n
    if p_ab >= 1.0:
        return 1.0  # every document matches both: perfect association, and -log p(a,b) = 0
    pmi = math.log(p_ab / ((df_a / n) * (df_b / n)))
    return max(-1.0, min(1.0, pmi / -math.log(p_ab)))


def pair_atypicality(npmi_value: float | None) -> float | None:
    """Map NPMI in [-1, +1] onto the [0, 1] rarity scale the other AXIS 2 terms use (1 = most original).

    npmi = -1 (never combined) -> 1.0     npmi = 0 (independent) -> 0.5     npmi = +1 (always together) -> 0.0
    """
    if npmi_value is None:
        return None
    return (1.0 - max(-1.0, min(1.0, float(npmi_value)))) / 2.0


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


async def facet_term_dfs(facet_text: str, *, sources: Iterable[str] | None = None, es: Any = None,
                         index: str | None = None) -> dict[str, int]:
    """Whole-index document frequency of every content word of a facet, in one request."""
    terms = sorted(idea_terms(facet_text))
    if not terms:
        return {}
    settings = get_settings() if es is not None else require_elastic()
    client = es if es is not None else get_async_es()
    resp = await client.search(index=index or settings.es_index, body=build_term_df_body(terms, sources))
    return parse_term_df_response(dict(resp))


async def facet_profile(facet_text: str, n: int, *, k: int = IDF_TOP_K, sources: Iterable[str] | None = None,
                        es: Any = None, index: str | None = None) -> dict[str, Any]:
    """One facet's rarity plus the evidence for it: the terms that drove it and how common each one is."""
    dfs = await facet_term_dfs(facet_text, sources=sources, es=es, index=index)
    rarity = facet_rarity_from_idf(dfs, n, k)
    top = sorted(dfs.items(), key=lambda kv: kv[1])[:k]
    return {"rarity": rarity, "term_dfs": dfs, "top_terms": [{"term": t, "df": df} for t, df in top],
            "unseen": sorted(t for t, df in dfs.items() if df == 0), "n_terms": len(dfs)}


def build_corpus_count_body(sources: Iterable[str] | None = None) -> dict[str, Any]:
    """Every scoreable document: the denominator N in the NPMI expectation."""
    bool_q: dict[str, Any] = {"must_not": [excluded_flags_clause()]}
    if sources:
        bool_q["filter"] = [{"terms": {"source": list(sources)}}]
    return {"query": {"bool": bool_q}}


async def corpus_size(*, sources: Iterable[str] | None = None, es: Any = None, index: str | None = None) -> int:
    """N for the NPMI expectation: how many documents the df counts were drawn from."""
    return await _count(build_corpus_count_body(sources), es=es, index=index)


async def pair_stats(a: str, b: str, *, sources: Iterable[str] | None = None, es: Any = None,
                     index: str | None = None) -> dict[str, Any]:
    """Everything AXIS 2 needs about one facet pair: both marginals, the joint, N, and the resulting NPMI.

    Four `_count` calls in parallel. `expected` is what independence would predict, so the report can say
    "3 projects combine these; chance predicts 80" instead of only "3 projects"."""
    import asyncio

    df_a, df_b, df_ab, n = await asyncio.gather(
        facet_df(a, sources=sources, es=es, index=index),
        facet_df(b, sources=sources, es=es, index=index),
        pair_df(a, b, sources=sources, es=es, index=index),
        corpus_size(sources=sources, es=es, index=index),
    )
    value = npmi(df_a, df_b, df_ab, n)
    return {"df_a": df_a, "df_b": df_b, "df_ab": df_ab, "n": n, "npmi": value,
            "expected": round(df_a * df_b / n, 2) if n > 0 else None,
            "atypicality": pair_atypicality(value)}
