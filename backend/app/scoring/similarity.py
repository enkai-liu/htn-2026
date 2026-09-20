"""One similarity scale for every source.

Records come from Elasticsearch (already reranked), Hacker News and GitHub (no score at all). To make crowding
comparable across sources we rerank ALL of them against the full idea with the same Jina reranker on the
Elastic Inference Service. Without Elastic we fall back to a lexical cosine and mark the result uncalibrated.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from app.config import get_settings

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset("a an and are as at be by for from has have in is it its of on or that the this to was we with you your our "
                  "their can will which who what when how not but into using use used app tool platform".split())


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 2]


def lexical_cosine(a: str, b: str) -> float:
    ca, cb = Counter(tokens(a)), Counter(tokens(b))
    if not ca or not cb:
        return 0.0
    dot = sum(ca[t] * cb[t] for t in ca.keys() & cb.keys())
    return dot / (math.sqrt(sum(v * v for v in ca.values())) * math.sqrt(sum(v * v for v in cb.values())))


def clamp01(x: float) -> float:
    return min(max(float(x), 0.0), 1.0)


def from_es_rerank(score: float) -> float:
    """Undo Elasticsearch's positivity transform on text_similarity_reranker hits so they match a direct rerank call.

    ES rewrites a raw relevance score s as max(s, 0) + min(exp(s), 1): 1 + s when s >= 0, exp(s) when s < 0. Left as is,
    reranked hits land in (0, 2] while the live scouts (direct inference calls) land around [-0.2, 0.8]."""
    score = float(score)
    return score - 1.0 if score >= 1.0 else (math.log(score) if score > 0 else -1.0)


# A reader's grade of a hit, as a floor on its similarity. The floors are percentiles of the calibration population --
# how close the nearest neighbours of 300 corpus projects are -- so they live on the reranker's own scale: a hit a
# reader calls the same thing is at least as close as the nearest neighbour of 95% of projects.
GRADE_PERCENTILE = {"same": 0.95, "close": 0.75}
GRADE_SPREAD = 0.25  # share of the reranker's own score kept above the floor, so graded hits still rank among themselves


def graded(score: float, grade: str | None) -> float:
    """The similarity of a hit the reranker scored `score` (unclamped) and a reader graded `grade`.

    The reranker measures whether a text answers a query, word for word: for "ai chipmaker" it gave Groq -0.05 and
    Nvidia -0.03, because their pages say LPU and GPU. A model that reads the two texts knows better, and its grade
    can only raise a score: what the reranker already found close stays where it is."""
    p = GRADE_PERCENTILE.get(grade or "")
    if p is None:
        return clamp01(score)
    from app.search.calibration import get_cdf

    values = get_cdf().values
    return clamp01(max(score, values[round(p * (len(values) - 1))] + GRADE_SPREAD * score))


async def rerank(query: str, texts: list[str], *, clamp: bool = True) -> tuple[list[float], bool]:
    """Returns (scores aligned with `texts`, calibrated). calibrated=False means the lexical fallback was used.
    clamp=False keeps the reranker's negative scores, for a caller that ranks among them before clamping."""
    if not texts:
        return [], True
    s = get_settings()
    if s.has_elastic:
        try:
            from app.search.es import get_async_es  # built by the spine lane

            es = get_async_es()
            resp = await es.inference.inference(task_type="rerank", inference_id=s.es_rerank_inference_id,
                                                query=query, input=[t[:1500] or " " for t in texts])
            scores = [0.0] * len(texts)
            for item in resp["rerank"]:
                scores[item["index"]] = clamp01(item["relevance_score"]) if clamp else float(item["relevance_score"])
            return scores, True
        except Exception:
            pass  # fall through: degrade rather than fail the run; the caller surfaces `uncalibrated`
    return [lexical_cosine(query, t) for t in texts], False


async def embed(texts: list[str]) -> list[list[float]] | None:
    """Jina embeddings via EIS, or None when Elastic is unavailable."""
    s = get_settings()
    if not (s.has_elastic and texts):
        return None
    try:
        from app.search.es import get_async_es

        resp = await get_async_es().inference.inference(task_type="text_embedding", inference_id=s.es_embed_inference_id,
                                                        input=[t[:2000] for t in texts])
        return [row["embedding"] for row in resp["text_embedding"]]
    except Exception:
        return None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
