"""Shared, typed blackboard with per-role write permissions.

Agents coordinate through it instead of passing everything in messages. Permissions are enforced in code:
only the resolver writes entities, only the verifier sets verification results, and so on.
"""
from __future__ import annotations

from typing import Any

from app.schemas import Claim, CoachMessage, CoachPitch, Entity, Evidence, Facets, Mutation, Scores, SourceRecord, SourceStatus, Voice

WRITE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "facets": ("conductor",),
    "records": ("scout.",),  # prefix match: any scout
    "sources": ("scout.", "conductor"),
    "entities": ("resolver",),
    "evidence": ("critic", "advocate", "scout.", "verifier"),
    "claims": ("critic", "advocate", "judge", "verifier"),
    "jury": ("judge",),
    "voice": ("verifier",),
    "priors": ("judge",),
    "scores": ("synthesizer", "mutator"),
    "mutations": ("mutator",),
    "coach": ("mutator",),
    "pitches": ("mutator",),
    "stats": ("scout.", "synthesizer", "mutator", "conductor"),
}


class BlackboardPermissionError(PermissionError):
    pass


class Blackboard:
    def __init__(self, idea_text: str, url: str | None = None) -> None:
        self.idea_text = idea_text
        self.url = url
        self.facets: Facets | None = None
        self.records: dict[str, SourceRecord] = {}
        self.sources: dict[str, SourceStatus] = {}
        self.entities: dict[str, Entity] = {}
        self.evidence: dict[str, Evidence] = {}
        self.claims: dict[str, Claim] = {}
        self.jury: list[dict[str, Any]] = []
        self.voice: Voice | None = None
        self.priors: list[dict[str, Any]] = []
        self.scores: Scores | None = None
        self.mutations: dict[str, Mutation] = {}
        self.coach: list[CoachMessage] = []  # the coaching conversation, oldest first
        self.pitches: list[CoachPitch] = []  # working-idea versions; [0] is the original
        self.stats: dict[str, Any] = {}  # cliches, whitespace, by_year, facet dfs

    def _check(self, section: str, writer: str) -> None:
        allowed = WRITE_PERMISSIONS[section]
        if not any(writer == a or (a.endswith(".") and writer.startswith(a)) for a in allowed):
            raise BlackboardPermissionError(f"{writer!r} may not write {section!r} (allowed: {allowed})")

    def put(self, section: str, writer: str, key: str, value: Any) -> None:
        self._check(section, writer)
        getattr(self, section)[key] = value

    def set(self, section: str, writer: str, value: Any) -> None:
        self._check(section, writer)
        setattr(self, section, value)

    def append(self, section: str, writer: str, value: Any) -> None:
        self._check(section, writer)
        getattr(self, section).append(value)

    def top_entities(self, n: int = 10) -> list[Entity]:
        return sorted(self.entities.values(), key=lambda e: -e.similarity)[:n]
