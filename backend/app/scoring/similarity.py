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


async def rerank(query: str, texts: list[str]) -> tuple[list[float], bool]:
    """Returns (scores aligned with `texts`, calibrated). calibrated=False means the lexical fallback was used."""
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
                scores[item["index"]] = float(item["relevance_score"])
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
