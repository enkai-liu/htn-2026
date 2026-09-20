from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import runs
from app.config import get_settings
from app.search.es import close_async_es
from app.sources.http import close_client


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_async_es()  # the cached AsyncElasticsearch and the live-source httpx pool own sockets; nothing else closes them
    await close_client()


app = FastAPI(title="Whitespace", version="0.1.0", lifespan=lifespan)
# Demo API with no cookies or auth: open CORS keeps the replay site and localhost both working.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], expose_headers=["*"])
app.include_router(runs.router)


@app.get("/api/health")
async def health() -> dict:
    s = get_settings()
    return {
        "ok": True,
        "orchestrator": s.orchestrator,
        "configured": {
            "elastic": s.has_elastic, "kibana": bool(s.kibana_url), "baseten": bool(s.baseten_api_key),
            "openrouter": bool(s.openrouter_api_key), "gptzero": bool(s.gptzero_api_key), "gptzero_mode": s.gptzero_mode,
            "github_token": bool(s.github_token), "browserbase": bool(s.browserbase_api_key), "slack": bool(s.slack_webhook_url),
        },
    }

