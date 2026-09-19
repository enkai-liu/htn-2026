"""Async Elasticsearch access for the backend: one cached client + a guard with a clear error message.

Everything in `app.search` imports offline; only calls that actually hit the network need credentials.
"""
from __future__ import annotations

import os
from typing import Any

from app.config import Settings, get_settings

# Documents carrying one of these pipeline flags are never shown as prior art.
EXCLUDED_QUALITY_FLAGS = ["too_short", "non_english"]

_client: Any = None


class ElasticNotConfigured(RuntimeError):
    """ES_URL / ES_API_KEY are empty. Roles should catch this and emit `source.failed`."""


def require_elastic(settings: Settings | None = None) -> Settings:
    settings = settings or get_settings()
    if not settings.has_elastic:
        raise ElasticNotConfigured(
            "Elastic is not configured: set ES_URL and ES_API_KEY in the repo-root .env (see .env.example), "
            "then run `backend/.venv/bin/python elastic/apply.py --check`."
        )
    return settings


def get_async_es() -> Any:
    """Cached `AsyncElasticsearch` built from settings.

    The async client defaults to aiohttp, which is NOT in the project's dependencies; httpx is. So when
    aiohttp is missing we select elastic-transport's httpx node instead of crashing at import time.
    """
    global _client
    if _client is None:
        settings = require_elastic()
        from elasticsearch import AsyncElasticsearch

        kwargs: dict[str, Any] = dict(
            api_key=settings.es_api_key,
            request_timeout=30.0,
            max_retries=2,
            retry_on_timeout=True,
            retry_on_status=(502, 503, 504),  # not 429: callers degrade (RRF-only) instead of hammering EIS
            server_mode=os.environ.get("ES_SERVER_MODE", "stack"),
        )
        try:
            import aiohttp  # noqa: F401
        except ImportError:
            kwargs["node_class"] = "httpxasync"
        _client = AsyncElasticsearch(settings.es_url, **kwargs)
    return _client


async def close_async_es() -> None:
    """Call from the FastAPI lifespan shutdown (and at the end of CLIs)."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def excluded_flags_clause() -> dict[str, Any]:
    return {"terms": {"quality_flags": list(EXCLUDED_QUALITY_FLAGS)}}
