"""openJiuwen host: the same roles, running on openjiuwen agent-core (the SDK underneath JiuwenSwarm).

- Every role becomes a `CommunicableAgent` on a `TeamRuntime`: P2P `send` for request/response, `publish` for pub/sub.
- The run is a `BaseTeam` executed by `Runner.run_agent_team_streaming(..., base=True)`.
- Role events travel through the team session stream (`session.write_stream`) and are forwarded to our EventBus,
  so what the UI shows is what flowed through the openJiuwen runtime.

Select with ORCHESTRATOR=jiuwen. Requires `pip install "backend[jiuwen]"` (Python >=3.11,<3.14).
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Optional

from openjiuwen.core.multi_agent.config import TeamConfig
from openjiuwen.core.multi_agent.schema.team_card import TeamCard
from openjiuwen.core.multi_agent.team import BaseTeam
from openjiuwen.core.multi_agent.team_runtime import CommunicableAgent
from openjiuwen.core.runner import Runner
from openjiuwen.core.single_agent.base import BaseAgent
from openjiuwen.core.single_agent.schema.agent_card import AgentCard

from app.core.blackboard import Blackboard
from app.core.budget import Budget
from app.core.eventbus import EventBus

from . import registry
from .host import Role, error, finalize, summarize

MESSAGE_TIMEOUT = 300.0
_EVENT_KEY = "__whitespace_event__"
_runner_start: asyncio.Future | None = None  # Runner.start() for the loop it was started on


async def _ensure_runner() -> None:
    """Start openJiuwen's Runner once per event loop. Its queues and consumers are bound to the loop that started it."""
    global _runner_start
    loop = asyncio.get_running_loop()
    if _runner_start is None or _runner_start.get_loop() is not loop:
        if _runner_start is not None:  # a previous loop (tests, reloads): its runner state is unusable here
            try:
                await Runner.stop()
            except Exception:
                pass
        _runner_start = asyncio.ensure_future(Runner.start())
    await _runner_start


class RoleAgent(CommunicableAgent, BaseAgent):
    """Adapter: an openJiuwen agent whose behaviour is one of our host-agnostic roles."""

    def __init__(self, card: AgentCard, role: Role, host: "JiuwenHost") -> None:
        super().__init__(card=card)
        self.role, self.host = role, host

    def configure(self, config) -> "RoleAgent":
        return self

    async def invoke(self, inputs: Any, session: Optional[Any] = None) -> Any:
        if not isinstance(inputs, dict) or "type" not in inputs:
            return error("malformed message")
        ctx = JiuwenCtx(self.host, self, session)
        if inputs.get("topic"):  # pub/sub delivery: fire-and-forget, errors become visible events
            try:
                return await self.role.handle(inputs, ctx)
            except Exception as exc:
                await ctx.emit("error", {"message": f"{self.role.id} failed on {inputs.get('topic')}: {exc}", "recoverable": True})
                return error(str(exc))
        if self.role.id not in self.host.started:
            self.host.started.add(self.role.id)
            await ctx.emit("agent.started", {"purpose": self.role.purpose})
        try:
            reply = await self.role.handle(inputs, ctx)
            ok, summary = reply.get("type") != "ERROR", summarize(reply)
        except Exception as exc:  # a role crash must never take the run down
            reply, ok, summary = error(f"{type(exc).__name__}: {exc}"), False, f"{type(exc).__name__}: {exc}"[:140]
        if inputs["type"] in ("TASK", "REPLAN", "REQUEST_EVIDENCE"):  # a retried or re-queried agent reports again, so the UI can show "recovered"
            await ctx.emit("agent.finished", {"ok": ok, "summary": summary})
        return finalize(reply, run_id=self.host.run_id, frm=self.role.id, to=inputs.get("frm")) | {"in_reply_to": inputs.get("mid")}

    async def stream(self, inputs: Any, session: Optional[Any] = None) -> AsyncIterator[Any]:
        await self.invoke(inputs, session)
        if False:
            yield None


class JiuwenCtx:
    def __init__(self, host: "JiuwenHost", agent: RoleAgent, session: Optional[Any]) -> None:
        self._host, self._agent, self._session = host, agent, session
        self.me = agent.role.id
        self.run_id, self.board, self.budget = host.run_id, host.board, host.budget
        self._sid = session.get_session_id() if session is not None else host.session_id

    async def send(self, to: str, msg: dict, timeout: float = 120.0) -> dict:
        full = finalize(msg, run_id=self.run_id, frm=self.me, to=to)
        if not self._host.on_team(to):
            return finalize(error(f"{to!r} is not on this run's team"), run_id=self.run_id, frm=to, to=self.me)
        await self.emit("message.sent", {"mid": full["mid"], "msg_type": full["type"], "to": to, "summary": summarize(full)}, to=to)
        failure = f"{to} returned no reply"
        try:
            reply = await self._agent.send(message=full, recipient=self._host.aid(to), session_id=self._sid, timeout=timeout)
        except Exception as exc:  # TeamRuntime timeout or routing failure
            reply, failure = None, f"{to} did not answer: {type(exc).__name__}: {exc}"[:200]
        if not isinstance(reply, dict) or "type" not in reply:
            await self.emit("error", {"message": failure, "recoverable": True})
            return finalize(error(failure), run_id=self.run_id, frm=to, to=self.me)
        return reply

    async def publish(self, topic: str, msg: dict) -> None:
        full = finalize(msg, run_id=self.run_id, frm=self.me, topic=topic)
        await self._agent.publish(message=full, topic_id=topic, session_id=self._sid)

    async def emit(self, type: str, data: Any = None, **meta: Any) -> None:
        phase = meta.pop("phase", None) or self._agent.role.phase
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="json")
        session = self._session or self._host.team_session
        if session is not None and self._host.streaming:
            # Through the openJiuwen session stream; JiuwenHost.run() forwards it to the EventBus.
            await session.write_stream({_EVENT_KEY: True, "agent": self.me, "phase": phase, "type": type, "data": data or {}, "meta": meta})
        else:
            await self._host.emit_direct(self.me, phase, type, data, **meta)

    def members(self) -> list[str]:
        return self._host.members()

    def form_team(self, role_ids: list[str]) -> None:
        if self.me != "conductor":
            raise PermissionError("only the conductor forms the team")
        self._host.form_team(role_ids)


class OriginalityTeam(BaseTeam):
    def __init__(self, card: TeamCard, config: TeamConfig, host: "JiuwenHost") -> None:
        super().__init__(card=card, config=config)
        self.host = host
        # Card + provider registration is lazy: an agent is only instantiated when a message first reaches it,
        # which is what makes dynamic team formation cheap.
        # Agent ids are global inside openJiuwen's resource manager, so they are namespaced per run: two concurrent
        # investigations must never share (or collide on) agent instances.
        for rid in registry.known_roles():
            card_ = AgentCard(id=host.aid(rid), name=host.aid(rid), description=registry.create(rid).purpose)
            self.add_agent(card_, (lambda c=card_, r=rid: RoleAgent(c, registry.create(r), host)))

    async def _run(self, message: Any, session: Any) -> Any:
        self.host.team_session = session
        self.host.session_id = session.get_session_id()
        await self.runtime.start()
        for rid in registry.known_roles():
            for topic in registry.create(rid).subscriptions:
                await self.subscribe(self.host.aid(rid), topic)
        full = finalize({"type": "TASK", "payload": message}, run_id=self.host.run_id, frm="user", to="conductor")
        return await self.runtime.send(message=full, recipient=self.host.aid("conductor"), sender="user",
                                       session_id=self.host.session_id, timeout=MESSAGE_TIMEOUT)

    async def invoke(self, message: Any, session: Optional[Any] = None) -> Any:
        if session is None:
            raise ValueError("OriginalityTeam needs a team session: use Runner.run_agent_team(..., base=True)")
        return await self._run(message, session)

    async def stream(self, message: Any, session: Optional[Any] = None) -> AsyncIterator[Any]:
        if session is None:
            raise ValueError("OriginalityTeam needs a team session: use Runner.run_agent_team_streaming(..., base=True)")

        async def go() -> None:
            try:
                self.host.final = await self._run(message, session)
            except Exception as exc:
                self.host.final = finalize(error(f"{type(exc).__name__}: {exc}"), run_id=self.host.run_id, frm="conductor", to="user")
            finally:
                self.host.streaming = False  # post-run re-scores and actions emit directly
                await session.close_stream()

        t = asyncio.create_task(go())
        try:
            async for chunk in session.stream_iterator():
                yield chunk
        finally:
            await t


class JiuwenHost:
    name = "jiuwen"

    def __init__(self, run_id: str, bus: EventBus, board: Blackboard, budget: Budget) -> None:
        self.run_id, self.bus, self.board, self.budget = run_id, bus, board, budget
        self.started: set[str] = set()
        self._team_ids: set[str] | None = None
        self.team: OriginalityTeam | None = None
        self.team_session: Any = None
        self.session_id: str | None = None
        self.streaming = True
        self.final: dict | None = None
        self.mirrored = 0  # events that travelled through the openJiuwen session stream

    def aid(self, role_id: str) -> str:
        """Runtime-wide agent id for one of this run's roles."""
        return f"{self.run_id}.{role_id}"

    # -- team ------------------------------------------------------------------------------------------
    def form_team(self, role_ids: list[str]) -> None:
        self._team_ids = set(role_ids) | {"conductor"}

    def on_team(self, role_id: str) -> bool:
        return (self._team_ids is None or role_id in self._team_ids) and role_id in registry.known_roles()

    def members(self) -> list[str]:
        return sorted(self._team_ids) if self._team_ids is not None else registry.known_roles()

    def phase_of(self, role_id: str) -> str:
        try:
            return registry.create(role_id).phase
        except KeyError:
            return "plan"

    async def emit_direct(self, agent: str, phase: str, type: str, data: Any = None, **meta: Any) -> None:
        await self.bus.emit(agent, phase, type, data, **meta)

    # -- entry points ----------------------------------------------------------------------------------
    async def run(self, inputs: dict[str, Any], timeout: float = MESSAGE_TIMEOUT) -> dict:
        await _ensure_runner()
        card = TeamCard(id=f"originality-{self.run_id}", name="originality_team", description="prior-art investigation swarm")
        config = TeamConfig().configure_max_agents(24).configure_timeout(MESSAGE_TIMEOUT).configure_concurrency(200)
        self.team = OriginalityTeam(card, config, self)
        await Runner.resource_mgr.add_agent_team(card, lambda: self.team)
        try:
            async for chunk in Runner.run_agent_team_streaming(agent_team=card.id, inputs=inputs, base=True):
                payload = getattr(chunk, "payload", chunk)
                if isinstance(payload, dict) and payload.get(_EVENT_KEY):
                    self.mirrored += 1
                    await self.bus.emit(payload["agent"], payload["phase"], payload["type"], payload["data"], **(payload.get("meta") or {}))
        finally:
            self.streaming = False
            await Runner.resource_mgr.remove_agent_team(team_id=card.id)
        return self.final or finalize(error("team ended without a result"), run_id=self.run_id, frm="conductor", to="user")

    async def deliver(self, frm: str, to: str, msg: dict, timeout: float) -> dict:
        """Post-run requests from the API (re-score a mutation, run an action) go straight onto the team runtime."""
        if self.team is None or not self.on_team(to):
            return finalize(error(f"{to!r} is not available"), run_id=self.run_id, frm=to, to=frm)
        full = finalize(msg, run_id=self.run_id, frm=frm, to=to)
        await self.team.runtime.start()
        try:
            reply = await self.team.runtime.send(message=full, recipient=self.aid(to), sender=frm, session_id=self.session_id, timeout=timeout)
        except Exception as exc:
            reply = finalize(error(f"{type(exc).__name__}: {exc}"), run_id=self.run_id, frm=to, to=frm)
        return reply if isinstance(reply, dict) else finalize(error("no reply"), run_id=self.run_id, frm=to, to=frm)
