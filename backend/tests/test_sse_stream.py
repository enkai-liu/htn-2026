"""The SSE endpoint consumed over a real socket (uvicorn + httpx streaming), the way a browser's EventSource sees it."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import uvicorn

from app.config import get_settings
from app.llm import router as router_mod
from app.main import app

IDEA = "A tool that checks how original a hackathon idea is by searching past projects and coaching the hacker toward whitespace."


@pytest.fixture
async def base_url():
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off"))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await serving


async def _read(resp: httpx.Response, *, stop_after: int | None = None) -> list[dict]:
    """Parses SSE frames into {id, event, data}. Comment lines (keep-alive pings) are skipped, as EventSource does."""
    frames: list[dict] = []
    cur: dict = {}
    async for line in resp.aiter_lines():
        if line.startswith(":"):
            continue
        if line == "":
            if "data" in cur:
                frames.append(cur)
                if stop_after is not None and len(frames) >= stop_after:
                    return frames
            cur = {}
            continue
        key, _, value = line.partition(":")
        cur[key] = value.removeprefix(" ")
    return frames


async def test_recorded_run_keeps_streaming_across_sleeps(base_url):
    """speed=4 leaves real sleeps between events: the stream must survive them (not just deliver the first burst)."""
    async with httpx.AsyncClient(timeout=20) as client, client.stream("GET", f"{base_url}/api/runs/mock/events?speed=4", headers={"Origin": "http://localhost:3000"}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["access-control-allow-origin"] == "*"
        frames = await _read(resp, stop_after=12)  # then hang up mid-stream, like a closed tab
    assert [int(f["id"]) for f in frames] == list(range(1, 13))
    for f in frames:
        ev = json.loads(f["data"])
        assert f["event"] == ev["type"] and int(f["id"]) == ev["seq"]
    assert frames[0]["event"] == "run.started"


async def test_recorded_run_completes_and_resumes_from_last_event_id(base_url):
    async with httpx.AsyncClient(timeout=20) as client:
        async with client.stream("GET", f"{base_url}/api/runs/mock/events?speed=0") as resp:
            frames = await _read(resp)
        assert [int(f["id"]) for f in frames] == list(range(1, 126))
        assert frames[-1]["event"] == "run.finished"

        async with client.stream("GET", f"{base_url}/api/runs/mock/events?speed=0", headers={"Last-Event-ID": "120"}) as resp:
            tail = await _read(resp)
        assert [int(f["id"]) for f in tail] == [121, 122, 123, 124, 125]

        assert (await client.get(f"{base_url}/api/runs/nope/events")).status_code == 404


async def test_live_run_streams_backlog_then_stays_open(base_url, monkeypatch):
    """A live run with no LLM configured fails fast. Its `error` event must arrive as an ordinary named SSE message
    (browsers also route that name to EventSource.onerror: see frontend/lib/sse.ts), and the stream stays open."""
    s = get_settings()
    monkeypatch.setattr(s, "baseten_api_key", "")
    monkeypatch.setattr(s, "openrouter_api_key", "")
    monkeypatch.setattr(router_mod, "_router", None)
    async with httpx.AsyncClient(timeout=20) as client:
        run_id = (await client.post(f"{base_url}/api/runs", json={"idea_text": IDEA})).json()["run_id"]
        async with client.stream("GET", f"{base_url}/api/runs/{run_id}/events") as resp:
            assert resp.status_code == 200
            frames = await asyncio.wait_for(_read(resp, stop_after=4), timeout=10)
    assert [f["event"] for f in frames] == ["run.started", "agent.started", "agent.finished", "error"]
    last = json.loads(frames[-1]["data"])
    assert last["data"]["recoverable"] is False and "BASETEN_API_KEY" in last["data"]["message"]
    monkeypatch.setattr(router_mod, "_router", None)
