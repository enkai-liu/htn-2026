from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api import runs
from app.config import REPO_ROOT, get_settings

app = FastAPI(title="Whitespace", version="0.1.0")
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


@app.get("/api/investigation/slop-index")
async def slop_index() -> dict:
    path = REPO_ROOT / "investigation" / "results" / "slop_index.json"
    if not path.exists():
        raise HTTPException(404, "investigation has not been run yet")
    return json.loads(path.read_text())
