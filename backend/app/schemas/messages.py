"""Inter-agent envelope. Hosts (asyncio, openjiuwen) move these; roles only ever see dicts of this shape."""
from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

MessageType = Literal[
    "TASK",
    "RESULT",
    "REQUEST_EVIDENCE",
    "EVIDENCE",
    "CHALLENGE",
    "REBUTTAL",
    "VERDICT",
    "VERIFY_RESULT",
    "REPLAN",
    "ABSTAIN",
    "ACTION_PROPOSAL",
    "ACTION_RESULT",
    "ERROR",
]


class Message(BaseModel):
    mid: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    run_id: str
    ts: float = Field(default_factory=time.time)
    frm: str
    to: str | None = None  # P2P recipient
    topic: str | None = None  # pub/sub topic
    in_reply_to: str | None = None
    type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] | None = None
