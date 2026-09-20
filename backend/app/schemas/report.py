"""Facets, scores, graph patches, mutations and the final report."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .claims import Claim
from .entities import Entity, Evidence

FACET_KEYS = ("purpose", "mechanism", "audience", "data", "twist")


class Facets(BaseModel):
    purpose: str
    mechanism: str
    audience: str = ""
    data: str = ""
    twist: str = ""
    domain: str = ""  # drives dynamic team formation
    keywords: list[str] = Field(default_factory=list)


class AxisScore(BaseModel):
    score: float | None  # 0..100, higher = more original; None when the axis abstains
    detail: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


class Abstain(BaseModel):
    active: bool = False
    reason: str = ""


class Scores(BaseModel):
    crowding: AxisScore
    facet_rarity: AxisScore
    llm_predictability: AxisScore
    headline: float | None = None
    band: float | None = None
    confidence: float = 0.0
    abstain: Abstain = Field(default_factory=Abstain)


class VoiceSentence(BaseModel):
    text: str
    start: int
    end: int
    flagged: bool


class Voice(BaseModel):
    """Two detectors on the pitch. A separate channel: never folded into the headline score.

    GPTZero is the primary read. `curvature` is Fast-DetectGPT on our own base model, whose only job is to be
    able to disagree: one detector can never tell you it is wrong. `agreement == "disagree"` means the panel
    reports both and calls neither, per docs/scoring.md rule 3."""

    too_short: bool = False
    predicted_class: Literal["human", "ai", "mixed"] | None = None
    confidence_category: Literal["high", "medium", "low"] | None = None
    result_message: str | None = None
    ai_sentence_share: float | None = None
    sentences: list[VoiceSentence] = Field(default_factory=list)
    neighbourhood_slop_share: float | None = None
    # Second opinion (signals/surprisal.py); all None when no base model is deployed.
    curvature: float | None = None
    curvature_percentile: float | None = None  # against pre-ChatGPT human pitches: 0.95 = a 5% false-positive point
    curvature_class: Literal["human", "ai"] | None = None
    agreement: Literal["agree", "disagree", "unknown"] = "unknown"


NodeKind = Literal["idea", "facet", "entity", "theme", "prior", "mutation"]
LinkKind = Literal["similar", "has_facet", "shares_facet", "same_as", "possible_same_as", "mutation_of", "tagged"]


class GraphNode(BaseModel):
    id: str
    kind: NodeKind
    label: str
    source: str | None = None
    similarity: float | None = None
    year: int | None = None
    url: str | None = None
    badges: list[str] = Field(default_factory=list)  # merged, conflict, imputed, ai_written, winner, source_failed
    val: float = 1.0


class GraphLink(BaseModel):
    source: str
    target: str
    kind: LinkKind
    weight: float = 1.0


class GraphPatch(BaseModel):
    add_nodes: list[GraphNode] = Field(default_factory=list)
    add_links: list[GraphLink] = Field(default_factory=list)
    update_nodes: list[dict[str, Any]] = Field(default_factory=list)  # {id, ...changed fields}
    remove_nodes: list[str] = Field(default_factory=list)


class Mutation(BaseModel):
    mid: str
    facet: str
    frm: str
    to: str
    rationale: str
    pitch: str  # the rewritten one-paragraph idea
    grounded_in: list[str] = Field(default_factory=list)  # whitespace terms that seeded it
    delta: float | None = None  # change in crowding score after re-scoring
    axes: dict[str, float] | None = None


class CoachCite(BaseModel):
    """A project the coach points at: either a neighbour already on the map (`eid`) or a fresh corpus hit."""

    title: str
    url: str = ""
    source: str = ""
    year: int | None = None
    similarity: float | None = None
    eid: str | None = None


class CoachMessage(BaseModel):
    """One turn of the coaching conversation. `suggestions` are tap-to-send replies offered to the author."""

    id: str
    role: Literal["coach", "user"]
    text: str
    question: str | None = None  # the one thing the coach wants answered next
    suggestions: list[str] = Field(default_factory=list)
    cites: list[CoachCite] = Field(default_factory=list)
    mid: str | None = None  # the mutation this turn explores, if any
    pitch_version: int | None = None  # the working-idea version this turn produced


class CoachPitch(BaseModel):
    """A version of the working idea. v0 is the original pitch; later versions come out of the conversation and are
    re-measured against the corpus (crowding only: the other axes are held at the run's values)."""

    version: int
    text: str
    note: str = ""  # what changed from the previous version
    crowding: float | None = None  # None while the corpus check is running
    delta: float | None = None  # crowding change vs the original idea
    headline: float | None = None
    nearest: list[CoachCite] = Field(default_factory=list)
    calibrated: bool = True


class SourceStatus(BaseModel):
    source: str
    status: Literal["ok", "failed", "skipped", "degraded"]
    n_records: int = 0
    error: str | None = None


class TermStat(BaseModel):
    term: str
    score: float | None = None
    global_count: int | None = None
    neighbourhood_count: int | None = None


class YearCount(BaseModel):
    year: int
    count: int
    winners: int = 0


class Report(BaseModel):
    run_id: str
    idea_text: str
    facets: Facets
    scores: Scores
    voice: Voice | None = None
    entities: list[Entity] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    cliches: list[TermStat] = Field(default_factory=list)
    whitespace: list[TermStat] = Field(default_factory=list)
    by_year: list[YearCount] = Field(default_factory=list)
    mutations: list[Mutation] = Field(default_factory=list)
    sources: list[SourceStatus] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    summary_md: str = ""
