from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.config import FIXTURES_DIR, RUNS_DIR
from app.core import runstore
from app.core.eventbus import load_jsonl, replay
from app.orchestration.host import task
from app.schemas import AgentEvent

router = APIRouter(prefix="/api")

ACTIONS = {"arm_watch", "draft_pitch", "writeback"}


class RunRequest(BaseModel):
    idea_text: str = Field(min_length=1, max_length=5000)
    url: str | None = Field(default=None, max_length=500)


def _sse(ev: AgentEvent) -> dict:
    return {"id": str(ev.seq), "event": ev.type, "data": json.dumps(ev.model_dump(mode="json", exclude_none=True))}


def _recorded(name: str) -> Path | None:
    """mock -> fixture; otherwise a golden run or a finished run persisted on disk. Names are sanitised."""
    safe = "".join(c for c in name if c.isalnum() or c in "-_")
    if not safe or safe != name:
        return None
    for p in (FIXTURES_DIR / "mock_run.jsonl" if safe == "mock" else None, FIXTURES_DIR / "golden" / f"{safe}.jsonl", RUNS_DIR / f"{safe}.jsonl"):
        if p is not None and p.exists():
            return p
    return None


async def _stream_recorded(path: Path, speed: float, after: int) -> AsyncIterator[dict]:
    async for ev in replay(load_jsonl(path), speed=speed, after_seq=after):
        yield _sse(ev)


@router.post("/runs")
async def create_run(req: RunRequest) -> dict:
    idea = req.idea_text.strip()
    if not idea:  # min_length counts whitespace
        raise HTTPException(422, "idea_text is empty")
    try:
        run = runstore.create_run(idea, req.url)
    except runstore.RunLimitExceeded as exc:
        raise HTTPException(429, str(exc)) from exc
    return {"run_id": run.run_id}


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, speed: float = Query(1.5, ge=0, le=20), last_event_id: str | None = Header(default=None)):
    after = int(last_event_id) if (last_event_id or "").isdigit() else 0
    run = runstore.get_run(run_id)
    if run is not None:
        async def live() -> AsyncIterator[dict]:
            async for ev in run.bus.subscribe(after_seq=after):
                yield _sse(ev)

        return EventSourceResponse(live())
    path = _recorded(run_id)
    if path is None:
        raise HTTPException(404, f"unknown run {run_id!r}")
    return EventSourceResponse(_stream_recorded(path, speed, after))


@router.get("/replay/{name}/events")
async def replay_events(name: str, speed: float = Query(1.5, ge=0, le=20), last_event_id: str | None = Header(default=None)):
    path = _recorded(name)
    if path is None:
        raise HTTPException(404, f"no recorded run named {name!r}")
    after = int(last_event_id) if (last_event_id or "").isdigit() else 0
    return EventSourceResponse(_stream_recorded(path, speed, after))


@router.get("/runs/{run_id}")
async def get_report(run_id: str) -> dict:
    run = runstore.get_run(run_id)
    if run is not None:
        if run.report is None:
            raise HTTPException(404, "run has not finished yet")
        return run.report.model_dump(mode="json")
    path = _recorded(run_id)
    if path is None:
        raise HTTPException(404, f"unknown run {run_id!r}")
    final = next((ev for ev in reversed(load_jsonl(path)) if ev.type == "run.finished"), None)
    if final is None:
        raise HTTPException(404, "recorded run has no report")
    return final.data["report"]


@router.post("/runs/{run_id}/mutations/{mid}/rescore")
async def rescore(run_id: str, mid: str) -> dict:
    run = runstore.get_run(run_id)
    if run is None:
        raise HTTPException(409, "re-scoring needs a live run (this is a recording)")
    if mid not in run.board.mutations:
        raise HTTPException(404, f"unknown mutation {mid!r}")
    reply = await run.host.deliver("user", "mutator", task(rescore=mid), timeout=60)
    return {"ok": reply.get("type") == "RESULT", **(reply.get("payload") or {})}


class CoachRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    mid: str | None = Field(default=None, max_length=40)  # a proposed mutation the author wants to talk through


@router.post("/runs/{run_id}/coach")
async def coach(run_id: str, req: CoachRequest) -> dict:
    """One turn of the coaching conversation. The reply arrives on the event stream (coach.message, coach.pitch)."""
    run = runstore.get_run(run_id)
    if run is None:
        raise HTTPException(409, "coaching needs a live run (this is a recording)")
    if not req.text.strip():
        raise HTTPException(422, "say something first")
    if req.mid is not None and req.mid not in run.board.mutations:
        raise HTTPException(404, f"unknown mutation {req.mid!r}")
    if run.coach_lock.locked():
        raise HTTPException(409, "the coach is still answering your last message")
    async with run.coach_lock:
        runstore.keep_alive(run)
        reply = await run.host.deliver("user", "mutator", task(chat=req.text.strip(), mid=req.mid), timeout=90)
        runstore.keep_alive(run)
    return {"ok": reply.get("type") == "RESULT", **(reply.get("payload") or {})}


@router.post("/runs/{run_id}/actions/{action}")
async def act(run_id: str, action: str, body: dict | None = None) -> dict:
    if action not in ACTIONS:
        raise HTTPException(404, f"unknown action {action!r}; expected one of {sorted(ACTIONS)}")
    run = runstore.get_run(run_id)
    if run is None:
        raise HTTPException(409, "actions need a live run (this is a recording)")
    reply = await run.host.deliver("user", "actuator", task(action=action, confirmed=True, **(body or {})), timeout=60)
    return {"ok": reply.get("type") == "RESULT", **(reply.get("payload") or {})}
