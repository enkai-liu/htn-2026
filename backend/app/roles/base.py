from __future__ import annotations

import hashlib
from typing import Annotated, Any

from pydantic import BeforeValidator

from app.llm.router import LLMRouter, get_router
from app.orchestration.host import Ctx


class BaseRole:
    id: str = ""
    purpose: str = ""
    phase: str = "plan"
    subscriptions: list[str] = []

    @property
    def llm(self) -> LLMRouter:
        return get_router()

    def session(self, ctx: Ctx) -> str:
        return f"{ctx.run_id}:{self.id}"  # x-session-affinity: keep this role's calls on one replica

    async def handle(self, msg: dict, ctx: Ctx) -> dict:  # pragma: no cover
        raise NotImplementedError


def eid_for(rid: str) -> str:
    """Stable entity id for a record before resolution; the resolver keeps the best record's id as canonical."""
    return "e" + hashlib.sha1(rid.encode()).hexdigest()[:7]


def clipped(n: int) -> Any:
    """Free-text field in an LLM output schema: cut to `n` characters, never rejected.

    A hard `max_length` turned a chatty model into a ValidationError, one re-ask, then a dropped juror or a failed
    role. The limit exists for the UI, so truncation is the right outcome.
    """
    def clip(v: Any) -> Any:
        return v[:n] if isinstance(v, str) else v

    return Annotated[str, BeforeValidator(clip)]


# Shared instructions go FIRST in every prompt so provider-side prefix caching can reuse them across roles.
HOUSE_RULES = (
    "You are one agent in a team that assesses how original an idea is against retrieved prior art.\n"
    "Rules: use only the evidence you are given; never invent projects, quotes, numbers or URLs; "
    "quotes must be copied verbatim from the provided text; if the evidence is thin, say so. "
    "In anything a person will read, call the collection of projects that was searched \"the dataset\", never \"the corpus\".\n"
)
