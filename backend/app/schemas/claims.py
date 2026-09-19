"""Claims are what agents argue about; only verified or clearly-labelled leads reach the report."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ClaimKind = Literal["exists", "differs", "trend", "gap"]
ClaimStatus = Literal["proposed", "challenged", "conceded", "verified", "unverified_lead", "rejected"]


class ThreadEntry(BaseModel):
    frm: str
    type: Literal["CHALLENGE", "REBUTTAL", "CONCEDE"]
    text: str
    evidence: list[str] = Field(default_factory=list)  # evids


class Claim(BaseModel):
    cid: str
    kind: ClaimKind
    text: str
    by: str  # agent id
    evidence: list[str] = Field(default_factory=list)  # evids
    status: ClaimStatus = "proposed"
    thread: list[ThreadEntry] = Field(default_factory=list)
