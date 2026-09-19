"""In-memory registry of live runs. Each run owns a bus, a blackboard, a budget and a host."""
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


_RUNS: dict[str, Run] = {}


def get_run(run_id: str) -> Run | None:
    return _RUNS.get(run_id)


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
    run_id = "r" + uuid.uuid4().hex[:8]
    bus = EventBus(run_id)
    board = Blackboard(idea_text, url)
    budget = Budget(max_calls=s.budget_max_calls, max_tokens=s.budget_max_tokens, max_seconds=s.budget_max_seconds)
    host, warning = _make_host(run_id, bus, board, budget)
    run = Run(run_id=run_id, idea_text=idea_text, url=url, bus=bus, board=board, budget=budget, host=host)
    _RUNS[run_id] = run
    run.task = asyncio.create_task(_drive(run, warning))
    return run


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
    # The bus stays open after run.finished so re-scores and actions can keep streaming to the same client.
