"""AgentEvent is the single SSE payload and the JSONL replay format. See docs/events.md for payload shapes."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Phase = Literal["plan", "scout", "resolve", "debate", "verify", "score", "mutate", "act", "done"]

EVENT_TYPES: frozenset[str] = frozenset(
    {
        # lifecycle
        "run.started",
        "facets.extracted",
        "team.formed",
        "agent.started",
        "agent.finished",
        "run.finished",
        "error",
        # tools and messages
        "tool.call",
        "tool.result",
        "message.sent",
        # sources and evidence
        "source.failed",
        "evidence.found",
        # resolution
        "entity.merged",
        "conflict.detected",
        # claims and debate
        "claim.proposed",
        "claim.challenged",
        "claim.resolved",
        "requery.issued",
        "jury.vote",
        "verify.result",
        # signals
        "voice.result",
        "prior.sample",
        "surprisal.measured",
        # scoring and graph
        "score.updated",
        "graph.patch",
        # coaching and actions
        "mutation.proposed",
        "mutation.scored",
        "coach.message",
        "coach.pitch",
        "action.proposed",
        "action.done",
        "budget.updated",
    }
)


class AgentEvent(BaseModel):
    seq: int
    run_id: str
    ts: float
    agent: str
    to: str | None = None
    phase: Phase
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    provider: str | None = None  # baseten | openrouter
    latency_ms: int | None = None
    tokens: dict[str, int] | None = None
    cost_usd: float | None = None

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in EVENT_TYPES:
            raise ValueError(f"unknown event type {v!r}; add it to EVENT_TYPES and docs/events.md")
        return v
