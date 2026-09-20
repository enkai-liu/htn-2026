"""Shared, typed blackboard with per-role write permissions.

Agents coordinate through it instead of passing everything in messages. Permissions are enforced in code:
only the resolver writes entities, only the verifier sets verification results, and so on.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.schemas import (
    Claim,
    CoachMessage,
    CoachPitch,
    Entity,
    Evidence,
    Facets,
    Mutation,
    Scores,
    SiteCheck,
    SourceRecord,
    SourceStatus,
    Voice,
)

if TYPE_CHECKING:  # annotation only: nothing in core should pull the HTML parser in at import time
    from app.sources.idea_url import IdeaPage

WRITE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "facets": ("conductor",),
    "self_page": ("conductor",),
    "scored_as": ("conductor",),
    "records": ("scout.",),  # prefix match: any scout
    "sources": ("scout.", "conductor"),
    "entities": ("resolver",),
    "sites": ("inspector",),
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
        self.scored_as: str | None = None  # a few-word pitch is scored as the planner's description of it: see similarity_text
        self.self_page: IdeaPage | None = None  # the author's own link, read once: context to plan with, and the one hit that is never prior art
        self.records: dict[str, SourceRecord] = {}
        self.sources: dict[str, SourceStatus] = {}
        self.entities: dict[str, Entity] = {}
        self.sites: dict[str, SiteCheck] = {}  # eid -> what a browser found at the product's own site
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

    @property
    def similarity_text(self) -> str:
        """What every record is reranked against: the pitch, unless the conductor replaced a few-word one."""
        return self.scored_as or self.idea_text

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
