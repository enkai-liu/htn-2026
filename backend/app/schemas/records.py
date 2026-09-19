"""One SourceRecord per retrieved hit, after schema matching into the canonical shape."""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

Source = Literal["devpost", "yc", "github", "hn", "arxiv", "web"]
Provenance = Literal["source", "normalized", "imputed"]
Status = Literal["active", "dormant", "dead", "acquired", "unknown"]


class GPTZeroScan(BaseModel):
    """Subset of GPTZero /v2/predict/text we persist. Never store the deprecated *_generated_prob fields."""

    predicted_class: Literal["human", "ai", "mixed"]
    confidence_category: Literal["high", "medium", "low"]
    subclass: str | None = None  # pure_ai | ai_paraphrased | concatenated | polished
    ai_sentence_share: float | None = None
    result_message: str | None = None
    model_version: str | None = None
    scanned_at: dt.datetime | None = None


class SourceRecord(BaseModel):
    rid: str  # "<source>:<native id>", e.g. "devpost:devspot"
    source: Source
    url: str
    title: str
    tagline: str | None = None
    description: str = ""
    pitch: str = ""  # title + tagline + "What it does", <= 1500 chars; the field we search, rerank and embed
    year: int | None = None
    date: dt.date | None = None
    date_precision: Literal["day", "year", "inferred"] | None = None
    tags: list[str] = Field(default_factory=list)
    tech: list[str] = Field(default_factory=list)
    status: Status = "unknown"
    traction: dict[str, Any] = Field(default_factory=dict)  # stars, points, is_winner, batch, team_size
    links: list[str] = Field(default_factory=list)  # outbound URLs (repo, website) used for blocking
    lang: str = "und"
    quality_flags: list[str] = Field(default_factory=list)
    field_provenance: dict[str, Provenance] = Field(default_factory=dict)
    retrieval: dict[str, Any] = Field(default_factory=dict)  # {query, leg, rank, rerank_score}
    gptzero: GPTZeroScan | None = None
