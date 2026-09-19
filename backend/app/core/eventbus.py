"""Per-run event bus: assigns seq, persists JSONL (the replay format), fans out to SSE subscribers."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.config import RUNS_DIR
from app.schemas import AgentEvent

_DONE = object()


class EventBus:
    def __init__(self, run_id: str, *, persist: bool = True) -> None:
        self.run_id = run_id
        self.history: list[AgentEvent] = []
        self._subs: set[asyncio.Queue] = set()
        self._closed = False
        self._path: Path | None = None
        if persist:
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            self._path = RUNS_DIR / f"{run_id}.jsonl"
            self._path.write_text("", encoding="utf-8")

    @property
    def closed(self) -> bool:
        return self._closed

    async def emit(self, agent: str, phase: str, type: str, data: Any = None, **meta: Any) -> AgentEvent:
        """meta: to, model, provider, latency_ms, tokens, cost_usd."""
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="json")
        ev = AgentEvent(
            seq=len(self.history) + 1, run_id=self.run_id, ts=round(time.time(), 3), agent=agent, phase=phase,
            type=type, data=data or {}, **meta,
        )
        self.history.append(ev)
        if self._path is not None:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev.model_dump(mode="json", exclude_none=True)) + "\n")
        for q in list(self._subs):
            q.put_nowait(ev)
        return ev

    async def close(self) -> None:
        self._closed = True
        for q in list(self._subs):
            q.put_nowait(_DONE)

    async def subscribe(self, after_seq: int = 0) -> AsyncIterator[AgentEvent]:
        """Yields history after `after_seq` (Last-Event-ID resume), then live events until the run closes."""
        q: asyncio.Queue = asyncio.Queue()
        backlog = [ev for ev in self.history if ev.seq > after_seq]
        self._subs.add(q)
        try:
            last = after_seq
            for ev in backlog:
                last = ev.seq
                yield ev
            if self._closed:
                return
            while True:
                item = await q.get()
                if item is _DONE:
                    return
                if item.seq > last:  # drop anything already delivered from the backlog
                    last = item.seq
                    yield item
        finally:
            self._subs.discard(q)


def load_jsonl(path: Path) -> list[AgentEvent]:
    return [AgentEvent(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def replay(events: list[AgentEvent], *, speed: float = 1.5, max_gap: float = 2.5, after_seq: int = 0) -> AsyncIterator[AgentEvent]:
    """Re-stream a recorded run with its original timing divided by `speed`."""
    prev_ts: float | None = None
    for ev in events:
        if ev.seq <= after_seq:
            prev_ts = ev.ts
            continue
        if prev_ts is not None and speed > 0:
            await asyncio.sleep(min(max(ev.ts - prev_ts, 0.0), max_gap) / speed)
        prev_ts = ev.ts
        yield ev
