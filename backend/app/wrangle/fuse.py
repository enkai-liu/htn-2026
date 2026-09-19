"""Field fusion: merge several SourceRecords into one Entity, keeping provenance and surfacing conflicts."""
from __future__ import annotations

import datetime as dt

from app.schemas import Conflict, ConflictValue, Entity, FusedField, MergeDecision, SourceRecord

from .reliability import RULES, reliability

_LIVE = {"active"}
_GONE = {"dead", "dormant"}


def _last_activity(r: SourceRecord) -> str | None:
    pushed = r.traction.get("pushed_at")
    if pushed:
        return str(pushed)[:10]
    if r.date:
        return r.date.isoformat()
    return f"{r.year}-01-01" if r.year else None


def fuse(eid: str, records: list[SourceRecord], merges: list[MergeDecision]) -> Entity:
    records = sorted(records, key=lambda r: -float(r.retrieval.get("rerank_score") or 0))
    best = records[0]
    fields: dict[str, FusedField] = {}
    conflicts: list[Conflict] = []

    def pick(field: str, values: list[tuple[object, SourceRecord]], *, conflicting) -> None:
        values = [(v, r) for v, r in values if v not in (None, "", [], "unknown")]
        if not values:
            return
        ranked = sorted(values, key=lambda vr: -reliability(field, vr[1].source))
        winner, src = ranked[0]
        imputed = src.field_provenance.get(field) == "imputed"
        fields[field] = FusedField(value=winner, provenance=[src.rid], imputed=imputed)
        distinct = {str(v) for v, _ in values}
        if len(distinct) > 1 and conflicting([v for v, _ in values]):
            conflicts.append(Conflict(
                field=field, resolution=winner, rule=RULES.get(field, "highest source reliability wins"),
                values=[ConflictValue(value=v, rid=r.rid, reliability=reliability(field, r.source)) for v, r in ranked]))

    pick("status", [(r.status, r) for r in records],
         conflicting=lambda vs: bool(set(vs) & _LIVE) and bool(set(vs) & _GONE))
    pick("last_activity", [(_last_activity(r), r) for r in records], conflicting=_dates_disagree)
    pick("year", [(r.year, r) for r in records], conflicting=lambda vs: max(vs) - min(vs) > 1)

    tech_sources = [r for r in records if r.tech]
    if tech_sources:
        src = max(tech_sources, key=lambda r: reliability("tech", r.source))
        fields["tech"] = FusedField(value=sorted({t for r in tech_sources for t in r.tech}),
                                    provenance=[r.rid for r in tech_sources],
                                    imputed=all(r.field_provenance.get("tech") == "imputed" for r in tech_sources) or
                                    src.field_provenance.get("tech") == "imputed")
    return Entity(
        eid=eid, canonical_name=_canonical_name(records), summary=(best.tagline or best.pitch or best.title)[:280],
        records=[r.rid for r in records], sources=sorted({r.source for r in records}), merges=merges,
        conflicts=conflicts, fields=fields, similarity=float(best.retrieval.get("rerank_score") or 0),
    )


def _canonical_name(records: list[SourceRecord]) -> str:
    """Prefer a human product name (Devpost / YC) over 'owner/repo' or a Show HN headline."""
    for source in ("yc", "devpost", "github", "hn", "web", "arxiv"):
        for r in records:
            if r.source == source:
                return r.title.split("/")[-1] if source == "github" else r.title
    return records[0].title


def _dates_disagree(values: list[str]) -> bool:
    parsed = []
    for v in values:
        try:
            parsed.append(dt.date.fromisoformat(str(v)[:10]))
        except ValueError:
            continue
    return len(parsed) > 1 and (max(parsed) - min(parsed)).days > 365
