"""In-memory registry of live runs. Each run owns a bus, a blackboard, a budget and a host.

A run is admitted only while fewer than `max_live_runs` are executing. After it ends it stays for `run_retention_s`
(re-scores, actions and late SSE clients keep working), then the bus is closed and the entry dropped; from then on
the API serves it from `backend/runs/{run_id}.jsonl` like any recording.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.core.blackboard import Blackboard
from app.core.budget import Budget
from app.core.eventbus import EventBus
from app.schemas import Report


@dataclass
class Run:
    run_id: str
    idea_text: str
    url: str | None
    bus: EventBus
    board: Blackboard
    budget: Budget
    host: Any
    task: asyncio.Task | None = None
    report: Report | None = None
    created: float = field(default_factory=time.time)
    evict: asyncio.TimerHandle | None = None
    coach_lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # one coaching turn at a time

    @property
    def active(self) -> bool:
        return self.task is not None and not self.task.done()


class RunLimitExceeded(RuntimeError):
    pass


_RUNS: dict[str, Run] = {}


def get_run(run_id: str) -> Run | None:
    return _RUNS.get(run_id)


def live_runs() -> list[Run]:
    return [r for r in _RUNS.values() if r.active]


def _make_host(run_id: str, bus: EventBus, board: Blackboard, budget: Budget) -> tuple[Any, str | None]:
    """Returns (host, warning). Falls back to the asyncio host if the openjiuwen host cannot be loaded."""
    from app.orchestration.asyncio_host import AsyncioHost

    if get_settings().orchestrator == "jiuwen":
        try:
            from app.orchestration.jiuwen_host import JiuwenHost

            return JiuwenHost(run_id, bus, board, budget), None
        except Exception as exc:  # ImportError, dependency conflicts, API drift
            return AsyncioHost(run_id, bus, board, budget), f"openjiuwen host unavailable ({type(exc).__name__}: {exc}); using asyncio host"
    return AsyncioHost(run_id, bus, board, budget), None


def create_run(idea_text: str, url: str | None = None) -> Run:
    import app.roles  # noqa: F401  (registers role factories)

    s = get_settings()
    if len(live_runs()) >= s.max_live_runs:
        raise RunLimitExceeded(f"{s.max_live_runs} runs are already in progress; try again in a minute")
    run_id = "r" + uuid.uuid4().hex[:8]
    bus = EventBus(run_id)
    board = Blackboard(idea_text, url)
    budget = Budget(max_calls=s.budget_max_calls, max_tokens=s.budget_max_tokens, max_seconds=s.budget_max_seconds)
    host, warning = _make_host(run_id, bus, board, budget)
    run = Run(run_id=run_id, idea_text=idea_text, url=url, bus=bus, board=board, budget=budget, host=host)
    _RUNS[run_id] = run
    run.task = asyncio.create_task(_drive(run, warning))
    return run


async def evict(run_id: str) -> None:
    """Close the bus (SSE clients see end-of-stream) and forget the run. Its JSONL on disk remains the replay."""
    run = _RUNS.pop(run_id, None)
    if run is None:
        return
    if run.evict is not None:
        run.evict.cancel()
    await run.bus.close()


def keep_alive(run: Run) -> None:
    """The author is still talking to the coach: a finished run gets a fresh retention window instead of being evicted mid-conversation."""
    if run.evict is None:
        return  # still executing; _drive schedules the eviction when it ends
    run.evict.cancel()
    loop = asyncio.get_running_loop()
    run.evict = loop.call_later(get_settings().run_retention_s, lambda: loop.create_task(evict(run.run_id)))


async def _drive(run: Run, warning: str | None) -> None:
    bus = run.bus
    await bus.emit("conductor", "plan", "run.started", {"idea_text": run.idea_text, "orchestrator": run.host.name, "replay": False})
    if warning:
        await bus.emit("conductor", "plan", "error", {"message": warning, "recoverable": True})
    try:
        reply = await run.host.run({"idea_text": run.idea_text, "url": run.url})
        payload = reply.get("payload") or {}
        if reply.get("type") == "RESULT" and payload.get("report"):
            run.report = Report.model_validate(payload["report"])
            await bus.emit("conductor", "done", "budget.updated", run.budget.snapshot())
            await bus.emit("conductor", "done", "run.finished", {"report": run.report.model_dump(mode="json")})
        else:
            await bus.emit("conductor", "done", "error", {"message": payload.get("message") or "run ended without a report", "recoverable": False})
    except Exception as exc:
        await bus.emit("conductor", "done", "error", {"message": f"{type(exc).__name__}: {exc}", "recoverable": False})
    finally:
        # The bus stays open for the retention window so re-scores and actions keep streaming to the same client.
        # A TimerHandle (not a Task) so nothing is left pending if the loop shuts down first.
        loop = asyncio.get_running_loop()
        run.evict = loop.call_later(get_settings().run_retention_s, lambda: loop.create_task(evict(run.run_id)))
