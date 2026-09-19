"""Host-agnostic contracts. Roles implement `Role` against `Ctx` and never import a specific runtime.

Two hosts implement Ctx: asyncio_host (always available) and jiuwen_host (openjiuwen agent-core TeamRuntime).
Select with ORCHESTRATOR=asyncio|jiuwen.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.core.blackboard import Blackboard
from app.core.budget import Budget
from app.schemas import Message


class Ctx(Protocol):
    run_id: str
    me: str
    board: Blackboard
    budget: Budget

    async def send(self, to: str, msg: dict, timeout: float = 120.0) -> dict:
        """P2P request/response. Returns the recipient's reply envelope (type RESULT | ERROR | ABSTAIN ...)."""

    async def publish(self, topic: str, msg: dict) -> None:
        """Fire-and-forget pub/sub to every role subscribed to `topic` (fnmatch patterns)."""

    async def emit(self, type: str, data: Any = None, **meta: Any) -> None:
        """Emit an AgentEvent attributed to this role. meta: phase, to, model, provider, latency_ms, tokens, cost_usd."""

    def members(self) -> list[str]:
        """Role ids currently on the team (dynamic team formation)."""

    def form_team(self, role_ids: list[str]) -> None:
        """Conductor only: restrict the addressable team for this run."""


@runtime_checkable
class Role(Protocol):
    id: str
    purpose: str
    phase: str  # default phase for this role's events
    subscriptions: list[str]

    async def handle(self, msg: dict, ctx: Ctx) -> dict: ...


class RoleError(Exception):
    pass


def envelope(type: str, payload: dict | None = None, **extra: Any) -> dict:
    """Partial message; the host fills mid, run_id, ts and frm."""
    return {"type": type, "payload": payload or {}, **extra}


def task(**payload: Any) -> dict:
    return envelope("TASK", payload)


def result(**payload: Any) -> dict:
    return envelope("RESULT", payload)


def error(message: str, **payload: Any) -> dict:
    return envelope("ERROR", {"message": message, **payload})


def finalize(msg: dict, *, run_id: str, frm: str, to: str | None = None, topic: str | None = None) -> dict:
    """Validate and complete an envelope into a full Message dict (host-owned fields are overwritten)."""
    body = {k: v for k, v in msg.items() if k in ("type", "payload", "in_reply_to", "budget")}
    return Message(run_id=run_id, frm=frm, to=to, topic=topic, **body).model_dump(mode="json")


def summarize(msg: dict, limit: int = 140) -> str:
    p = msg.get("payload") or {}
    for key in ("summary", "query", "reason", "message"):
        if p.get(key):
            return str(p[key])[:limit]
    keys = ", ".join(f"{k}={len(v) if isinstance(v, (list, dict)) else str(v)[:24]}" for k, v in list(p.items())[:4])
    return keys[:limit]
