"""Plain-asyncio host: in-process message passing with the same semantics as the openjiuwen TeamRuntime host.

P2P `send` awaits the recipient's handler under a timeout; `publish` fans out to subscribers as background tasks.
Every agent-to-agent message becomes a `message.sent` event so the collaboration is visible in the UI.
"""
from __future__ import annotations

import asyncio
import fnmatch
from typing import Any

from app.core.blackboard import Blackboard
from app.core.budget import Budget
from app.core.eventbus import EventBus

from . import registry
from .host import Role, error, finalize, summarize


class AsyncioHost:
    name = "asyncio"

    def __init__(self, run_id: str, bus: EventBus, board: Blackboard, budget: Budget) -> None:
        self.run_id, self.bus, self.board, self.budget = run_id, bus, board, budget
        self._roles: dict[str, Role] = {}
        self._team: set[str] | None = None  # None = everyone addressable (before team.formed)
        self._started: set[str] = set()
        self._bg: set[asyncio.Task] = set()

    # -- team ------------------------------------------------------------------------------------------
    def form_team(self, role_ids: list[str]) -> None:
        self._team = set(role_ids) | {"conductor"}

    def members(self) -> list[str]:
        return sorted(self._team) if self._team is not None else registry.known_roles()

    def _role(self, role_id: str) -> Role:
        if self._team is not None and role_id not in self._team:
            raise KeyError(f"{role_id!r} is not on this run's team")
        if role_id not in self._roles:
            self._roles[role_id] = registry.create(role_id)
        return self._roles[role_id]

    def ctx(self, role_id: str) -> AsyncioCtx:
        return AsyncioCtx(self, role_id)

    # -- delivery --------------------------------------------------------------------------------------
    async def deliver(self, frm: str, to: str, msg: dict, timeout: float) -> dict:
        full = finalize(msg, run_id=self.run_id, frm=frm, to=to)
        sender_phase = self._roles[frm].phase if frm in self._roles else "plan"
        try:
            role = self._role(to)
        except KeyError as exc:
            return finalize(error(str(exc)), run_id=self.run_id, frm=to, to=frm)
        if frm != "user":
            await self.bus.emit(frm, msg.get("phase") or sender_phase, "message.sent",
                                {"mid": full["mid"], "msg_type": full["type"], "to": to, "summary": summarize(full)}, to=to)
        ctx = self.ctx(to)
        if to not in self._started:
            self._started.add(to)
            await ctx.emit("agent.started", {"purpose": role.purpose})
        try:
            reply = await asyncio.wait_for(role.handle(full, ctx), timeout=timeout)
            ok, summary = reply.get("type") != "ERROR", summarize(reply)
        except asyncio.TimeoutError:
            reply, ok, summary = error(f"{to} timed out after {timeout:.0f}s"), False, f"timed out after {timeout:.0f}s"
        except Exception as exc:  # a role crash must never take the run down
            reply, ok, summary = error(f"{type(exc).__name__}: {exc}"), False, f"{type(exc).__name__}: {exc}"[:140]
        if full["type"] in ("TASK", "REPLAN", "REQUEST_EVIDENCE"):  # a retried or re-queried agent reports again, so the UI can show "recovered"
            await ctx.emit("agent.finished", {"ok": ok, "summary": summary})
        return finalize(reply, run_id=self.run_id, frm=to, to=frm) | {"in_reply_to": full["mid"]}

    async def fanout(self, frm: str, topic: str, msg: dict) -> None:
        full = finalize(msg, run_id=self.run_id, frm=frm, topic=topic)
        for rid in self.members():
            if rid == frm:
                continue
            try:
                role = self._role(rid)
            except KeyError:
                continue
            if any(fnmatch.fnmatch(topic, pat) for pat in role.subscriptions):
                t = asyncio.create_task(self._safe_handle(role, full, rid))
                self._bg.add(t)
                t.add_done_callback(self._bg.discard)

    async def _safe_handle(self, role: Role, full: dict, rid: str) -> None:
        try:
            await role.handle(full, self.ctx(rid))
        except Exception as exc:
            await self.bus.emit(rid, role.phase, "error", {"message": f"{rid} failed on {full.get('topic')}: {exc}", "recoverable": True})

    # -- entry point -----------------------------------------------------------------------------------
    async def run(self, inputs: dict[str, Any], timeout: float = 300.0) -> dict:
        try:
            return await self.deliver("user", "conductor", {"type": "TASK", "payload": inputs}, timeout)
        finally:
            for t in list(self._bg):
                t.cancel()


class AsyncioCtx:
    def __init__(self, host: AsyncioHost, me: str) -> None:
        self._host, self.me = host, me
        self.run_id, self.board, self.budget = host.run_id, host.board, host.budget

    async def send(self, to: str, msg: dict, timeout: float = 120.0) -> dict:
        return await self._host.deliver(self.me, to, msg, timeout)

    async def publish(self, topic: str, msg: dict) -> None:
        await self._host.fanout(self.me, topic, msg)

    async def emit(self, type: str, data: Any = None, **meta: Any) -> None:
        role = self._host._roles.get(self.me)
        phase = meta.pop("phase", None) or (role.phase if role else "plan")
        await self._host.bus.emit(self.me, phase, type, data, **meta)

    def members(self) -> list[str]:
        return self._host.members()

    def form_team(self, role_ids: list[str]) -> None:
        if self.me != "conductor":
            raise PermissionError("only the conductor forms the team")
        self._host.form_team(role_ids)
