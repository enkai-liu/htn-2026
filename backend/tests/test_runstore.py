"""Live-run lifecycle: admission cap, retention, eviction, and what the API serves afterwards."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.api.runs import _recorded
from app.config import RUNS_DIR, get_settings
from app.core import runstore
from app.llm import router as router_mod
from app.main import app

IDEA = "A tool that checks how original a hackathon idea is by searching past projects and coaching the hacker toward whitespace."


@pytest.fixture
def no_llm(monkeypatch):
    """Runs end immediately with a non-recoverable error: the conductor has no provider to plan with."""
    s = get_settings()
    monkeypatch.setattr(s, "baseten_api_key", "")
    monkeypatch.setattr(s, "openrouter_api_key", "")
    monkeypatch.setattr(router_mod, "_router", None)
    return s


async def test_admission_is_capped_by_runs_still_executing(no_llm, monkeypatch):
    monkeypatch.setattr(no_llm, "max_live_runs", 1)
    first = runstore.create_run(IDEA)
    with pytest.raises(runstore.RunLimitExceeded, match="1 runs are already in progress"):
        runstore.create_run(IDEA)
    await first.task
    second = runstore.create_run(IDEA)  # a finished run no longer occupies a slot
    await second.task
    assert first.run_id != second.run_id


async def test_api_answers_429_when_full(no_llm, monkeypatch):
    monkeypatch.setattr(no_llm, "max_live_runs", 1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        ok = await c.post("/api/runs", json={"idea_text": IDEA})
        full = await c.post("/api/runs", json={"idea_text": IDEA})
    assert ok.status_code == 200
    assert full.status_code == 429 and "in progress" in full.json()["detail"]
    await runstore.get_run(ok.json()["run_id"]).task


async def test_finished_run_is_retained_then_evicted_and_served_from_disk(no_llm, monkeypatch):
    monkeypatch.setattr(no_llm, "run_retention_s", 0.2)
    run = runstore.create_run(IDEA)
    await run.task
    seen: list[str] = []

    async def late_client() -> None:
        async for ev in run.bus.subscribe():  # joins after the run ended: gets the backlog, then end-of-stream on eviction
            seen.append(ev.type)

    consumer = asyncio.create_task(late_client())
    await asyncio.sleep(0.05)
    assert runstore.get_run(run.run_id) is run and not consumer.done()  # inside the retention window
    await asyncio.sleep(0.3)
    assert runstore.get_run(run.run_id) is None
    assert run.bus.closed
    await asyncio.wait_for(consumer, 1)
    assert seen[0] == "run.started" and seen[-1] == "error"
    assert _recorded(run.run_id) == RUNS_DIR / f"{run.run_id}.jsonl"  # the recording outlives the object


async def test_evicting_twice_or_an_unknown_run_is_harmless(no_llm):
    run = runstore.create_run(IDEA)
    await run.task
    await runstore.evict(run.run_id)
    await runstore.evict(run.run_id)
    await runstore.evict("nope")
    assert runstore.get_run(run.run_id) is None
