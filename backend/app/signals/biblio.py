"""Verification layer 2: GPTZero Bibliography Scan (`/v2/bibliography-scan/text`, their hallucination API) run over
OUR OWN agents' claims before they are shown. The verifier holds a veto.

The scanner needs real, formatted citations to have anything to check, so the pipeline is:
    format_citation()  ->  '[n] Org. "Title." Site. Year. URL'          (one per piece of evidence)
    build_document()   ->  numbered claims carrying [n] markers + a "References" section
    bibliography_scan()->  same replay / sha256 cache / word-ledger mechanics as predict_text
    map_results()      ->  {cid: Verification}

Decision rule (design-full.md 2.6 / 2.9), implemented in resolve_status():
    citation status "fake"           -> claim REJECTED and logged as a caught hallucination
    stance containing "contradict"   -> claim NOT verified (shown as an unverified lead)
    "unknown" / "unsure" / no result -> GPTZero has no opinion; the local quote check (layer 1) decides.
      The scanner is tuned for academic citations and may not recognise a Devpost URL. That must never reject a claim.
GPTZero does not fact-check; it reports whether a citation exists and whether sources support the claim. Say it that way.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import Field, ValidationError, field_validator

from app.schemas import Claim, Evidence, SourceRecord, Verification

from .gptzero import BIBLIO_PATH, FIXTURE_MARK, GPTZeroClient, GPTZeroParseError, _Lenient, get_client, prepare_text, text_sha256
from .textutil import NormalizedText

CitationStatus = Literal["exist", "exist_with_issues", "fake", "unsure", "unknown"]
CITATION_STATUSES: tuple[str, ...] = ("exist", "exist_with_issues", "fake", "unsure", "unknown")
# When a claim has several citations: one fabricated source taints it; otherwise report the best-established one.
_STATUS_PRIORITY = ("fake", "exist", "exist_with_issues", "unsure", "unknown")
# Most adverse first. The rule only acts on "contradict", but the UI shows the stance we report.
_STANCE_PRIORITY = ("strongly contradict", "contradict", "partial contradict", "slightly disagree", "strongly support",
                    "support", "partial support", "slightly agree", "mixed", "neutral", "stance_unknown")
REFERENCES_HEADING = "References"
# Replay mode only: a citation containing one of these is reported "fake", so the Fire Drill demo works offline.
REPLAY_FAKE_MARKERS = ("fire-drill", "firedrill", "fire_drill", "fire drill", ".invalid", "simulated")

_LEADING_NUMBER = re.compile(r"^\s*\[(\d+)\]\s*")
_MARKER = re.compile(r"\[(\d+)\]")
_SITE_NAMES = {"devpost": "Devpost", "yc": "Y Combinator", "github": "GitHub", "hn": "Hacker News", "arxiv": "arXiv"}


# ============================================================================ citations and the scan document
def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip() if value is not None else ""


def _with_period(s: str) -> str:
    return s if s.endswith((".", "?", "!")) else s + "."


def format_citation(n: int, org: str | None, title: str | None, site: str | None, year: int | str | None,
                    url: str | None, *, trailing_period: bool = False) -> str:
    """'[n] Org. "Title." Site. Year. URL' -- the shape GPTZero's citation parser needs.

    Empty parts are dropped (no org -> '[n] "Title." Site. Year. URL'); a missing year becomes 'n.d.'.
    No period is placed after the URL by default: a parser may otherwise read 'https://x.y/z.' as the address,
    fail to resolve it, and call a real source fake. Pass trailing_period=True for the strict bibliographic form."""
    parts: list[str] = []
    org_s, title_s, site_s, url_s = _clean(org), _clean(title), _clean(site), _clean(url)
    if org_s:
        parts.append(_with_period(org_s))
    title_s = title_s.strip('"' + chr(0x201C) + chr(0x201D) + " ").replace('"', "'")
    if title_s:
        parts.append(f'"{_with_period(title_s)}"')
    if site_s:
        parts.append(_with_period(site_s))
    year_s = _clean(year)
    parts.append(_with_period(year_s if year_s else "n.d"))
    if url_s:
        parts.append(url_s.rstrip(".") + ("." if trailing_period else ""))
    return f"[{int(n)}] " + " ".join(parts)


def citation_for_record(n: int, record: SourceRecord) -> str:
    """Citation for a retrieved record, e.g. '[3] DevSpot team. "DevSpot." Devpost. 2024. https://devpost.com/software/devspot'."""
    site = _SITE_NAMES.get(record.source) or (urlparse(record.url).netloc.removeprefix("www.") or "Web")
    if record.source == "devpost":
        org = f"{record.title} team"
    elif record.source == "github":
        path = urlparse(record.url).path.strip("/").split("/")
        org = path[0] if path and path[0] else ""
    elif record.source == "hn":
        org = ""
    else:
        org = record.title if record.source == "yc" else ""
    year = record.year or (record.date.year if record.date else None)
    return format_citation(n, org, record.title, site, year, record.url)


@dataclass
class DocumentLayout:
    """The scan document plus everything needed to map GPTZero's answer back onto our claims."""

    text: str
    claim_spans: dict[str, tuple[int, int]] = field(default_factory=dict)  # cid -> span of its line
    claim_refs: dict[str, list[int]] = field(default_factory=dict)  # cid -> reference numbers it cites
    ref_spans: dict[int, tuple[int, int]] = field(default_factory=dict)  # n -> span of its reference line
    ref_evids: dict[int, list[str]] = field(default_factory=dict)  # n -> evids sharing that citation
    numbering: dict[str, int] = field(default_factory=dict)  # evid -> n


def layout_document(claims: Sequence[Claim], evidence: Sequence[Evidence]) -> DocumentLayout:
    """Deterministic: the same (claims, evidence) always yield the same text and numbering, so map_results() can
    rebuild the layout instead of being handed it."""
    by_evid = {e.evid: e for e in evidence}
    bodies: dict[str, int] = {}  # citation body (without its old [k]) -> n ; identical citations share a number
    layout = DocumentLayout(text="")
    refs: list[str] = []
    for c in claims:
        nums: list[int] = []
        for evid in c.evidence:
            ev = by_evid.get(evid)
            if ev is None:
                continue
            body = _LEADING_NUMBER.sub("", _clean(ev.citation)) or _clean(ev.url)
            if not body:
                continue
            n = bodies.get(body)
            if n is None:
                n = bodies[body] = len(bodies) + 1
                refs.append(f"[{n}] {body}")
            layout.numbering[evid] = n
            layout.ref_evids.setdefault(n, [])
            if evid not in layout.ref_evids[n]:
                layout.ref_evids[n].append(evid)
            if n not in nums:
                nums.append(n)
        layout.claim_refs[c.cid] = nums

    lines: list[str] = []
    pos = 0
    for i, c in enumerate(claims, start=1):
        body = _clean(c.text).rstrip(". ")
        markers = "".join(f"[{n}]" for n in layout.claim_refs[c.cid])
        line = f"{i}. {body}{' ' + markers if markers else ''}."
        layout.claim_spans[c.cid] = (pos, pos + len(line))
        lines.append(line)
        pos += len(line) + 1
    text = "\n".join(lines)
    if refs:
        text += f"\n\n{REFERENCES_HEADING}\n"
        pos = len(text)
        for n, ref in enumerate(refs, start=1):
            layout.ref_spans[n] = (pos, pos + len(ref))
            pos += len(ref) + 1
        text += "\n".join(refs)
    layout.text = text
    return layout


def build_document(claims: Sequence[Claim], evidence: Sequence[Evidence]) -> str:
    """Numbered claims with [n] markers, a blank line, 'References', then one '[n] ...' citation per line."""
    return layout_document(claims, evidence).text


# ============================================================================ response models (documented subset)
class Indices(_Lenient):
    start: int
    end: int


class CitationExists(_Lenient):
    status: CitationStatus = "unknown"
    score: float | None = None
    justification: str | None = None
    hallucination_label: str | None = None
    hallucination_explanation: str | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _known_status(cls, v: Any) -> Any:
        v = v.strip().lower() if isinstance(v, str) else v
        return v if v in CITATION_STATUSES else "unknown"


class CitationAiScan(_Lenient):
    """GPTZero's AI detection on the citation text itself ("second-hand hallucinations")."""

    predicted_class: str | None = None
    score: float | None = None


class BiblioCitation(_Lenient):
    id: int | str | None = None
    text: str = ""
    indices: Indices | None = None
    citation_type: str | None = None
    citation_exists: CitationExists | None = None
    ai_scan: CitationAiScan | None = None


class AgreeWithCitation(_Lenient):
    stance: str | None = None
    justification: str | None = None


class IsCited(_Lenient):
    is_cited: bool | None = None
    check_worthy: bool | None = None
    score: float | None = None
    justification: str | None = None


class BiblioClaim(_Lenient):
    id: int | str | None = None
    text: str = ""
    indices: Indices | None = None
    claim_type: str | None = None  # cited | uncited
    bibliographic_citation_ids: list[int | str] = Field(default_factory=list)
    agree_with_citation: AgreeWithCitation | None = None
    is_cited_in_bibliography: IsCited | None = None

    @field_validator("bibliographic_citation_ids", mode="before")
    @classmethod
    def _none_is_empty(cls, v: Any) -> Any:
        return [] if v is None else v


class BiblioSource(_Lenient):
    id: int | str | None = None
    claim_id: int | str | None = None
    citation_id: int | str | None = None
    url: str | None = None
    title: str | None = None
    stance: str | None = None
    justification: str | None = None
    sourcerer_name: str | None = None


class BiblioScan(_Lenient):
    id: str | None = None
    version: int | str | None = None
    inputText: str | None = None
    bibliographic_citations: list[BiblioCitation] = Field(default_factory=list)
    claims: list[BiblioClaim] = Field(default_factory=list)
    sources: list[BiblioSource] = Field(default_factory=list)
    replayed: bool = False  # synthetic (replay mode, nothing cached)
    cached: bool = False

    @field_validator("bibliographic_citations", "claims", "sources", mode="before")
    @classmethod
    def _none_is_empty(cls, v: Any) -> Any:
        return [] if v is None else v


def parse_biblio_response(raw: dict[str, Any], *, replayed: bool = False, cached: bool = False) -> BiblioScan:
    if isinstance(raw, list):  # the /files variant returns an array, one scan per file
        raw = raw[0] if raw else {}
    try:
        scan = BiblioScan.model_validate(raw)
    except ValidationError as exc:
        raise GPTZeroParseError(f"unexpected /v2/bibliography-scan/text response: {exc.errors()[:3]}") from exc
    return scan.model_copy(update={"replayed": replayed, "cached": cached})


async def bibliography_scan(document: str, *, bucket: str = "interactive", client: GPTZeroClient | None = None) -> BiblioScan:
    """Scan one document. Raises GPTZeroError / BudgetExceeded; the caller falls back to the local quote check alone.
    Billing for this endpoint is unconfirmed: we reserve the document's word count (see scripts/smoke_gptzero.sh)."""
    c = client or get_client()
    document = prepare_text(document)
    raw, source, _meta = await c.fetch("biblio", BIBLIO_PATH, {"document": document}, document, bucket=bucket,
                                       replay=lambda text: replay_biblio(text, c))
    return parse_biblio_response(raw, replayed=source == "fixture", cached=source == "cache")


def replay_biblio(document: str, client: GPTZeroClient | None = None) -> dict[str, Any]:
    """Replay mode: a synthetic scan rebuilt from the document itself so ids and offsets line up. Every well-formed
    citation "exists" and every cited claim is "support"ed, except citations carrying a REPLAY_FAKE_MARKERS token,
    which come back "fake". The envelope is taken from fixtures/gptzero/biblio_example.json."""
    envelope = (client or get_client()).load_fixture("biblio_example")
    out: dict[str, Any] = {FIXTURE_MARK: envelope.get(FIXTURE_MARK, "synthetic, shaped like the documented GPTZero response"),
                           "id": f"replay-{text_sha256(document)[:12]}", "version": envelope.get("version", 1),
                           "inputText": document, "bibliographic_citations": [], "claims": [], "sources": []}
    heading = re.search(rf"(?im)^[ \t]*(?:{REFERENCES_HEADING}|Works Cited|Bibliography)[ \t]*$", document)
    body_end = heading.start() if heading else len(document)
    number_to_id: dict[int, int] = {}
    if heading:
        for m in re.finditer(r"(?m)^[ \t]*\[(\d+)\][^\n]*$", document[heading.end():]):
            start = heading.end() + m.start()
            line = m.group(0)
            fake = any(tok in line.lower() for tok in REPLAY_FAKE_MARKERS)
            has_url = re.search(r"https?://\S+", line) is not None
            status = "fake" if fake else ("exist" if has_url else "unknown")
            cid = len(out["bibliographic_citations"])
            number_to_id[int(m.group(1))] = cid
            out["bibliographic_citations"].append({
                "id": cid, "text": line.strip(), "indices": {"start": start, "end": start + len(line)},
                "citation_type": "webpage" if has_url else None, "citation_object": None,
                "citation_exists": {
                    "status": status, "score": None,
                    "justification": "[replay fixture] " + ("No matching source could be found for this citation." if fake
                                                           else "Synthetic result; no lookup was performed."),
                    "hallucination_label": "fabricated_source" if fake else None,
                    "hallucination_explanation": "[replay fixture] marked as fabricated for the offline fire drill" if fake else None},
                "ai_scan": None, "claim_reference": {"has_reference": True}})
    for m in re.finditer(r"(?m)^[^\n]*\S[^\n]*$", document[:body_end]):
        line = m.group(0)
        ids = [number_to_id[int(k)] for k in _MARKER.findall(line) if int(k) in number_to_id]
        cites_fake = any(out["bibliographic_citations"][i]["citation_exists"]["status"] == "fake" for i in ids)
        out["claims"].append({
            "id": len(out["claims"]), "text": line.strip(), "indices": {"start": m.start(), "end": m.end()},
            "claim_type": "cited" if ids else "uncited", "bibliographic_citation_ids": ids,
            "agree_with_citation": {"stance": ("stance_unknown" if cites_fake else "support") if ids else None,
                                    "justification": "[replay fixture] synthetic stance"},
            "is_cited_in_bibliography": {"is_cited": bool(ids), "check_worthy": True, "score": None, "justification": None}})
    return out


# ============================================================================ mapping the scan back onto our claims
def _overlap(a: tuple[int, int], b: Indices | None) -> int:
    return 0 if b is None else max(0, min(a[1], b.end) - max(a[0], b.start))


def _pick(values: Sequence[str | None], priority: Sequence[str]) -> str | None:
    present = [v for v in values if v]
    if not present:
        return None
    lowered = {v.strip().lower(): v for v in present}
    for p in priority:
        if p in lowered:
            return p
    return present[0].strip().lower()


def _local_match(evids: Sequence[str], by_evid: dict[str, Evidence]) -> bool | None:
    """Carry layer 1 forward: True if any cited source matched, False if all were checked and none did, else None."""
    results = [by_evid[e].verification.local_quote_match for e in evids
               if e in by_evid and by_evid[e].verification is not None]
    results = [r for r in results if r is not None]
    if any(results):
        return True
    return False if results and len(results) == len([e for e in evids if e in by_evid]) else None


@dataclass
class _Mapped:
    layout: DocumentLayout
    citation_by_number: dict[int, BiblioCitation]
    claims_by_cid: dict[str, list[BiblioClaim]]
    citation_by_id: dict[str, BiblioCitation]


def _map(scan: BiblioScan, claims: Sequence[Claim], evidence: Sequence[Evidence]) -> _Mapped:
    layout = layout_document(claims, evidence)
    offsets_valid = scan.inputText is None or scan.inputText == layout.text
    by_evid = {e.evid: e for e in evidence}

    citation_by_number: dict[int, BiblioCitation] = {}
    for cit in scan.bibliographic_citations:
        n: int | None = None
        m = _LEADING_NUMBER.match(cit.text or "")
        if m and int(m.group(1)) in layout.ref_spans:
            n = int(m.group(1))
        if n is None and offsets_valid and cit.indices is not None:
            best = max(layout.ref_spans.items(), key=lambda kv: _overlap(kv[1], cit.indices), default=None)
            if best is not None and _overlap(best[1], cit.indices) > 0:
                n = best[0]
        if n is None:  # last resort: the citation text contains one of our evidence URLs
            for num, evids in layout.ref_evids.items():
                if any(by_evid[e].url and by_evid[e].url in (cit.text or "") for e in evids if e in by_evid):
                    n = num
                    break
        if n is not None and n not in citation_by_number:
            citation_by_number[n] = cit

    claims_by_cid: dict[str, list[BiblioClaim]] = {c.cid: [] for c in claims}
    normalized = {c.cid: NormalizedText(c.text).text for c in claims}
    for gc in scan.claims:
        target: str | None = None
        if offsets_valid and gc.indices is not None:
            best_c = max(layout.claim_spans.items(), key=lambda kv: _overlap(kv[1], gc.indices), default=None)
            if best_c is not None and _overlap(best_c[1], gc.indices) > 0:
                target = best_c[0]
        if target is None:
            g = NormalizedText(_MARKER.sub("", re.sub(r"^\s*\d+\.\s*", "", gc.text or ""))).text.rstrip(". ")
            if len(g) >= 12:
                for cid, ours in normalized.items():
                    if g in ours or ours.rstrip(". ") in g:
                        target = cid
                        break
        if target is not None:
            claims_by_cid[target].append(gc)
    return _Mapped(layout, citation_by_number, claims_by_cid,
                   {str(c.id): c for c in scan.bibliographic_citations if c.id is not None})


def _justification(status: str | None, stance: str | None, cits: Sequence[BiblioCitation], gclaims: Sequence[BiblioClaim]) -> str | None:
    if status == "fake":
        for c in cits:
            ce = c.citation_exists
            if ce is not None and ce.status == "fake":
                return ce.hallucination_explanation or ce.justification or "GPTZero could not find this source."
    if stance and "contradict" in stance:
        for g in gclaims:
            a = g.agree_with_citation
            if a is not None and a.stance and "contradict" in a.stance.lower() and a.justification:
                return a.justification
    for g in gclaims:
        if g.agree_with_citation is not None and g.agree_with_citation.justification:
            return g.agree_with_citation.justification
    for c in cits:
        if c.citation_exists is not None and c.citation_exists.justification:
            return c.citation_exists.justification
    return None


def map_results(scan: BiblioScan, claims: Sequence[Claim], evidence: Sequence[Evidence]) -> dict[str, Verification]:
    """{cid: Verification} for every claim passed in. Pass the SAME claims and evidence that built the document.
    A claim GPTZero said nothing about gets gptzero_status=None / stance=None, which resolve_status() leaves to layer 1."""
    mapped = _map(scan, claims, evidence)
    by_evid = {e.evid: e for e in evidence}
    out: dict[str, Verification] = {}
    for c in claims:
        gclaims = mapped.claims_by_cid.get(c.cid, [])
        claim_nums = mapped.layout.claim_refs.get(c.cid, [])
        cits = [mapped.citation_by_number[n] for n in claim_nums if n in mapped.citation_by_number]
        number_of = {id(cit): n for n, cit in mapped.citation_by_number.items()}
        for g in gclaims:
            # GPTZero's own claim -> citation links: follow them unless they point at a reference this claim does not cite
            for ref in g.bibliographic_citation_ids:
                linked = mapped.citation_by_id.get(str(ref))
                if linked is None or any(linked is x for x in cits):
                    continue
                n = number_of.get(id(linked))
                if n is None or n in claim_nums:
                    cits.append(linked)
        status = _pick([x.citation_exists.status if x.citation_exists else None for x in cits], _STATUS_PRIORITY)
        stance = _pick([g.agree_with_citation.stance if g.agree_with_citation else None for g in gclaims], _STANCE_PRIORITY)
        out[c.cid] = Verification(
            local_quote_match=_local_match(c.evidence, by_evid),
            gptzero_status=status if status in CITATION_STATUSES else None,  # type: ignore[arg-type]
            stance=stance, justification=_justification(status, stance, cits, gclaims))
    return out


def map_evidence_results(scan: BiblioScan, claims: Sequence[Claim], evidence: Sequence[Evidence]) -> dict[str, Verification]:
    """{evid: Verification}: the citation status of each source plus the stance of the claims that cite it.
    Keeps any local_quote_match already recorded on the evidence."""
    mapped = _map(scan, claims, evidence)
    out: dict[str, Verification] = {}
    for ev in evidence:
        n = mapped.layout.numbering.get(ev.evid)
        if n is None:
            continue
        cit = mapped.citation_by_number.get(n)
        citing = [g for c in claims if n in mapped.layout.claim_refs.get(c.cid, []) for g in mapped.claims_by_cid.get(c.cid, [])]
        status = cit.citation_exists.status if cit is not None and cit.citation_exists is not None else None
        stance = _pick([g.agree_with_citation.stance if g.agree_with_citation else None for g in citing], _STANCE_PRIORITY)
        out[ev.evid] = Verification(
            local_quote_match=ev.verification.local_quote_match if ev.verification else None,
            gptzero_status=status, stance=stance,
            justification=_justification(status, stance, [cit] if cit is not None else [], citing))
    return out


# ============================================================================ the veto
def is_fake(v: Verification | None) -> bool:
    return v is not None and v.gptzero_status == "fake"


def is_contradicted(v: Verification | None) -> bool:
    return v is not None and bool(v.stance) and "contradict" in v.stance.lower()


def resolve_status(v: Verification | None, *, trust_local_match_over_fake: bool = False) -> Literal["verified", "unverified_lead", "rejected"]:
    """Both layers -> the claim's final status.
        fake citation                   -> rejected
        stance contains "contradict"    -> unverified_lead
        local quote match               -> verified   (GPTZero unknown / unsure / silent never blocks this)
        otherwise                       -> unverified_lead
    trust_local_match_over_fake: if GPTZero calls a source fake but we found the quote in that very source, the
    detector is wrong about a non-academic URL; downgrade to unverified_lead instead of rejecting. Off by default."""
    if v is None:
        return "unverified_lead"
    if is_fake(v):
        return "unverified_lead" if (trust_local_match_over_fake and v.local_quote_match) else "rejected"
    if is_contradicted(v):
        return "unverified_lead"
    return "verified" if v.local_quote_match else "unverified_lead"


def verify_event(cid: str, v: Verification) -> dict[str, Any]:
    """`data` for a verify.result event, layer "gptzero" (docs/events.md). Wording follows GPTZero's own framing:
    it reports whether the citation exists and whether sources support the claim; it does not fact-check."""
    status = v.gptzero_status or "not_checked"
    if status == "fake":
        detail = "GPTZero bibliography scan: citation could not be found"
    elif status == "not_checked":
        detail = "GPTZero returned no result for this citation; the local quote check decides"
    elif status in ("unknown", "unsure"):
        detail = f"GPTZero could not establish this citation ({status}); the local quote check decides"
    else:
        detail = "citation exists" + (" (with issues)" if status == "exist_with_issues" else "")
    if v.stance:
        detail += f"; source stance: {v.stance}"
    if v.justification and status == "fake":
        detail += f" ({v.justification[:160]})"
    return {"cid": cid, "layer": "gptzero", "status": status, "detail": detail}
