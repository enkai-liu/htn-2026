"""Canonical prior-art entities: several SourceRecords resolved into one thing, with provenance."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

MergeVerdict = Literal["same", "different", "insufficient_evidence"]


class MergeDecision(BaseModel):
    a: str  # rid
    b: str  # rid
    verdict: MergeVerdict
    signals: dict[str, Any] = Field(default_factory=dict)  # url_xref, name_sim, desc_sim
    model: str | None = None  # None when decided by a deterministic rule
    rationale: str = ""


class ConflictValue(BaseModel):
    value: Any
    rid: str
    reliability: float


class Conflict(BaseModel):
    field: str
    values: list[ConflictValue]
    resolution: Any = None
    rule: str = ""  # which reliability rule picked the resolution


class FusedField(BaseModel):
    value: Any
    provenance: list[str] = Field(default_factory=list)  # rids
    imputed: bool = False


class SiteCheck(BaseModel):
    """What a cloud browser found at a prior-art product's own site, today. Deterministic: no model judged it."""
    eid: str
    rid: str  # the record whose link was followed
    url: str
    final_url: str = ""
    status: Literal["alive", "dead", "parked", "blocked"]
    why: str = ""
    http_status: int | None = None
    title: str = ""
    excerpt: str = ""  # visible text, as rendered
    screenshot: str | None = None  # path under the API, e.g. /api/runs/r1/shots/e1.jpg
    elapsed_ms: int = 0
    conflict: Conflict | None = None  # set when the render contradicts what a listing says about the project


class JurorVote(BaseModel):
    model: str
    score: float  # 0..1 overlap on this facet
    why: str = ""


class FacetOverlap(BaseModel):
    mean: float
    std: float
    votes: list[JurorVote] = Field(default_factory=list)


class Entity(BaseModel):
    eid: str
    canonical_name: str
    summary: str = ""
    records: list[str] = Field(default_factory=list)  # rids
    sources: list[str] = Field(default_factory=list)
    merges: list[MergeDecision] = Field(default_factory=list)
    possible_same_as: list[str] = Field(default_factory=list)  # eids left unmerged on insufficient evidence
    conflicts: list[Conflict] = Field(default_factory=list)
    fields: dict[str, FusedField] = Field(default_factory=dict)
    similarity: float = 0.0  # reranker score vs the full idea
    facet_overlap: dict[str, FacetOverlap] = Field(default_factory=dict)


class Verification(BaseModel):
    local_quote_match: bool | None = None
    gptzero_status: Literal["exist", "exist_with_issues", "fake", "unsure", "unknown"] | None = None
    stance: str | None = None
    justification: str | None = None


class Evidence(BaseModel):
    evid: str
    eid: str
    rid: str
    quote: str
    url: str
    citation: str  # '[3] DevSpot team. "DevSpot." Devpost. 2024. https://...'
    verification: Verification | None = None
