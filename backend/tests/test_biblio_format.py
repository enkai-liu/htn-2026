"""Layer-2 verification: citation formatting, the scan document, and mapping GPTZero's Bibliography Scan back onto
our claims with the veto rule (fake -> reject; contradict -> not verified; unknown/unsure -> the local check decides)."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from tenacity import wait_none

from app.schemas import Claim, Evidence, SourceRecord, Verification
from app.signals.biblio import (
    BiblioScan,
    bibliography_scan,
    build_document,
    citation_for_record,
    format_citation,
    is_contradicted,
    is_fake,
    layout_document,
    map_evidence_results,
    map_results,
    parse_biblio_response,
    resolve_status,
    verify_event,
)
from app.signals.gptzero import GPTZeroClient
from app.signals.gptzero_budget import WordLedger

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gptzero" / "biblio_example.json"


def load_fixture() -> tuple[dict, list[Claim], list[Evidence]]:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    inputs = raw["_inputs"]
    return raw, [Claim(**c) for c in inputs["claims"]], [Evidence(**e) for e in inputs["evidence"]]


class NoNetwork(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"network call attempted: {request.url}")


def make_client(tmp_path, *, mode: str, handler=None) -> GPTZeroClient:
    ledger = WordLedger(tmp_path / "ledger.json", caps={"interactive": 5_000, "investigation": 5_000})
    transport = httpx.MockTransport(handler) if handler is not None else NoNetwork()
    return GPTZeroClient(mode=mode, api_key="test-key", ledger=ledger, cache_dir=tmp_path / "cache", transport=transport,
                         retry_wait=wait_none())


# ---------------------------------------------------------------------------- format_citation
def test_format_citation_canonical_shape():
    assert format_citation(1, "DevSpot team", "DevSpot", "Devpost", 2024, "https://devpost.com/software/devspot") == \
        '[1] DevSpot team. "DevSpot." Devpost. 2024. https://devpost.com/software/devspot'
    # the exact probe from the design doc's Hour-0 checklist
    assert format_citation(3, "DevSpot team", "DevSpot", "Devpost", "2024", "https://devpost.com/software/devspot").startswith('[3] DevSpot team. "DevSpot." Devpost. 2024. ')


def test_format_citation_edge_cases():
    assert format_citation(3, None, "Show HN: PitchProbe", "Hacker News", 2025, "https://example.org/hn/1") == \
        '[3] "Show HN: PitchProbe." Hacker News. 2025. https://example.org/hn/1'
    assert format_citation(2, "Acme Inc.", "Is this original?", "Y Combinator", None, "https://x.y/z") == \
        '[2] Acme Inc. "Is this original?" Y Combinator. n.d. https://x.y/z'
    assert format_citation(4, "  Team\n Rocket ", ' The "Best"   Idea ', "Devpost", 2023, " https://x.y/a. ") == \
        "[4] Team Rocket. \"The 'Best' Idea.\" Devpost. 2023. https://x.y/a"
    assert format_citation(5, "Org", "Title", "Site", 2020, "https://x.y/z", trailing_period=True).endswith("https://x.y/z.")
    assert format_citation(6, "Org", "Title", "Site", 2020, None) == '[6] Org. "Title." Site. 2020.'


def test_citation_for_record():
    rec = SourceRecord(rid="devpost:devspot", source="devpost", url="https://devpost.com/software/devspot", title="DevSpot", year=2024)
    assert citation_for_record(1, rec) == '[1] DevSpot team. "DevSpot." Devpost. 2024. https://devpost.com/software/devspot'
    gh = SourceRecord(rid="github:a/b", source="github", url="https://github.com/Ayon-Bhowmick/HackathonProjectSearch", title="HackathonProjectSearch", year=2023)
    assert citation_for_record(2, gh) == '[2] Ayon-Bhowmick. "HackathonProjectSearch." GitHub. 2023. https://github.com/Ayon-Bhowmick/HackathonProjectSearch'
    hn = SourceRecord(rid="hn:1", source="hn", url="https://news.ycombinator.com/item?id=1", title="Show HN: X")
    assert citation_for_record(3, hn) == '[3] "Show HN: X." Hacker News. n.d. https://news.ycombinator.com/item?id=1'


# ---------------------------------------------------------------------------- build_document
def test_build_document_matches_the_fixture_input():
    raw, claims, evidence = load_fixture()
    doc = build_document(claims, evidence)
    assert doc == raw["inputText"], "document format changed: regenerate fixtures/gptzero/biblio_example.json"
    lines = doc.split("\n")
    assert lines[0] == "1. DevSpot already validates hackathon ideas against Devpost [1]."
    assert lines[4:6] == ["", "References"]
    assert lines[6] == '[1] DevSpot team. "DevSpot." Devpost. 2024. https://devpost.com/software/devspot'
    assert lines[9] == '[4] "Show HN: PitchProbe." Hacker News. 2025. https://example.org/hn/40000001'
    assert build_document(claims, evidence) == doc, "must be deterministic"


def test_build_document_renumbers_dedupes_and_tolerates_gaps():
    ev = [Evidence(evid="a", eid="x", rid="r1", quote="q", url="https://a.example/1", citation='[7] A team. "A." Devpost. 2022. https://a.example/1'),
          Evidence(evid="b", eid="x", rid="r1", quote="another quote, same source", url="https://a.example/1",
                   citation='[9] A team. "A." Devpost. 2022. https://a.example/1'),
          Evidence(evid="c", eid="y", rid="r2", quote="q", url="https://b.example/2", citation='[2] B team. "B." Devpost. 2023. https://b.example/2'),
          Evidence(evid="unused", eid="z", rid="r3", quote="q", url="https://c.example/3", citation='[1] C. "C." Web. 2020. https://c.example/3')]
    claims = [Claim(cid="c1", kind="exists", text="B did it first.  ", by="critic", evidence=["c", "a"]),
              Claim(cid="c2", kind="exists", text="A also\ndid it", by="critic", evidence=["b", "a", "missing-evid"]),
              Claim(cid="c3", kind="gap", text="Nobody targets librarians", by="advocate", evidence=[])]
    layout = layout_document(claims, ev)
    assert layout.text == (
        "1. B did it first [1][2].\n"
        "2. A also did it [2].\n"
        "3. Nobody targets librarians.\n"
        "\n"
        "References\n"
        '[1] B team. "B." Devpost. 2023. https://b.example/2\n'
        '[2] A team. "A." Devpost. 2022. https://a.example/1')
    assert layout.numbering == {"c": 1, "a": 2, "b": 2} and "unused" not in layout.numbering
    assert layout.claim_refs == {"c1": [1, 2], "c2": [2], "c3": []}
    for cid, (s, e) in layout.claim_spans.items():
        assert layout.text[s:e].startswith(("1.", "2.", "3.")) and layout.text[s:e].endswith(".")
    for n, (s, e) in layout.ref_spans.items():
        assert layout.text[s:e].startswith(f"[{n}] ")


def test_document_without_evidence_has_no_references_section():
    doc = build_document([Claim(cid="c1", kind="trend", text="Study buddies spiked after 2023", by="critic")], [])
    assert doc == "1. Study buddies spiked after 2023." and "References" not in doc


# ---------------------------------------------------------------------------- map_results + the veto
def test_fixture_is_shaped_like_the_documented_response():
    raw, _, _ = load_fixture()
    assert raw["_fixture"] == "synthetic, shaped like the documented GPTZero response"
    assert {"id", "version", "inputText", "bibliographic_citations", "claims", "sources"} <= set(raw)
    scan = parse_biblio_response(raw)
    assert isinstance(scan, BiblioScan) and len(scan.bibliographic_citations) == 4 and len(scan.claims) == 4
    assert [c.citation_exists.status for c in scan.bibliographic_citations] == ["exist", "unknown", "fake", "exist_with_issues"]
    assert scan.claims[0].agree_with_citation.stance == "support" and scan.claims[0].is_cited_in_bibliography.is_cited


def test_map_results_and_the_decision_rule():
    raw, claims, evidence = load_fixture()
    for e in evidence:  # layer 1 already ran: every quote was found, except in the fabricated source
        e.verification = Verification(local_quote_match=e.evid != "e3")
    out = map_results(parse_biblio_response(raw), claims, evidence)
    assert set(out) == {"c1", "c2", "c3", "c4"} and all(isinstance(v, Verification) for v in out.values())

    assert out["c1"] == Verification(local_quote_match=True, gptzero_status="exist", stance="support",
                                     justification="The cited page describes checking hackathon ideas against Devpost projects.")
    assert resolve_status(out["c1"]) == "verified"

    # GPTZero does not recognise the Devpost URL: that must NOT reject the claim; the local quote check decides
    assert out["c2"].gptzero_status == "unknown" and out["c2"].stance == "stance_unknown"
    assert not is_fake(out["c2"]) and not is_contradicted(out["c2"])
    assert resolve_status(out["c2"]) == "verified"

    # fabricated citation -> rejected, with GPTZero's explanation kept for the UI
    assert is_fake(out["c3"]) and out["c3"].local_quote_match is False
    assert out["c3"].justification == "The cited article and its domain do not exist."
    assert resolve_status(out["c3"]) == "rejected"

    # the source exists and even contains the quote, but does not support the claim -> never "verified"
    assert out["c4"].gptzero_status == "exist_with_issues" and out["c4"].stance == "partial contradict"
    assert is_contradicted(out["c4"]) and out["c4"].local_quote_match is True
    assert resolve_status(out["c4"]) == "unverified_lead"
    assert "pitch-deck wording" in out["c4"].justification


def test_unknown_and_unsure_defer_to_the_local_check():
    for status in ("unknown", "unsure", None):
        for stance in ("stance_unknown", "neutral", None):
            assert resolve_status(Verification(local_quote_match=True, gptzero_status=status, stance=stance)) == "verified"
            assert resolve_status(Verification(local_quote_match=False, gptzero_status=status, stance=stance)) == "unverified_lead"
            assert resolve_status(Verification(local_quote_match=None, gptzero_status=status, stance=stance)) == "unverified_lead"
    assert resolve_status(None) == "unverified_lead"
    assert resolve_status(Verification(local_quote_match=True, gptzero_status="exist", stance="strongly support")) == "verified"
    assert resolve_status(Verification(local_quote_match=False, gptzero_status="exist", stance="support")) == "unverified_lead", \
        "GPTZero alone never verifies: an 'exists' claim needs the local quote match"
    for stance in ("contradict", "strongly contradict", "partial contradict", "Partial Contradict"):
        assert resolve_status(Verification(local_quote_match=True, gptzero_status="exist", stance=stance)) == "unverified_lead"
    assert resolve_status(Verification(local_quote_match=True, gptzero_status="fake", stance="support")) == "rejected"
    assert resolve_status(Verification(local_quote_match=True, gptzero_status="fake"), trust_local_match_over_fake=True) == "unverified_lead"


def test_mapping_survives_missing_offsets_and_numbers():
    """If GPTZero returns no indices, echoes a different inputText, or drops the [n], we still map by text and URL."""
    raw, claims, evidence = load_fixture()
    raw["inputText"] = "something else entirely"
    for c in raw["claims"]:
        c["indices"] = None
        c["text"] = c["text"].split(". ", 1)[1]  # GPTZero strips our list numbering
    for c in raw["bibliographic_citations"]:
        c["indices"] = None
        c["text"] = c["text"].split("] ", 1)[1]
    out = map_results(parse_biblio_response(raw), claims, evidence)
    assert [out[c].gptzero_status for c in ("c1", "c2", "c3", "c4")] == ["exist", "unknown", "fake", "exist_with_issues"]
    assert [out[c].stance for c in ("c1", "c2", "c3", "c4")] == ["support", "stance_unknown", "stance_unknown", "partial contradict"]


def test_silence_from_gptzero_is_not_a_verdict():
    _, claims, evidence = load_fixture()
    out = map_results(BiblioScan(), claims, evidence)
    assert all(v.gptzero_status is None and v.stance is None for v in out.values())
    assert all(resolve_status(v) == "unverified_lead" for v in out.values())  # no local match recorded either


def test_a_fake_among_several_citations_taints_the_claim_and_adverse_stance_wins():
    ev = [Evidence(evid="a", eid="x", rid="r1", quote="q", url="https://a.example/1", citation='[1] A. "A." Devpost. 2022. https://a.example/1'),
          Evidence(evid="b", eid="y", rid="r2", quote="q", url="https://b.invalid/2", citation='[2] B. "B." Blog. 2026. https://b.invalid/2')]
    claims = [Claim(cid="c1", kind="exists", text="Both A and B already do this", by="critic", evidence=["a", "b"])]
    layout = layout_document(claims, ev)
    scan = parse_biblio_response({
        "bibliographic_citations": [
            {"id": 10, "text": '[1] A. "A." Devpost. 2022. https://a.example/1', "citation_exists": {"status": "exist"}},
            {"id": 11, "text": '[2] B. "B." Blog. 2026. https://b.invalid/2', "citation_exists": {"status": "fake", "justification": "no such page"}}],
        "claims": [{"id": 0, "text": "1. Both A and B", "indices": {"start": 0, "end": 15}, "bibliographic_citation_ids": [10],
                    "agree_with_citation": {"stance": "support"}},
                   {"id": 1, "text": "already do this [1][2].", "indices": {"start": 16, "end": len(layout.text.split(chr(10))[0])},
                    "bibliographic_citation_ids": [11], "agree_with_citation": {"stance": "contradict", "justification": "B is a blog post about cats"}}]})
    v = map_results(scan, claims, ev)["c1"]
    assert v.gptzero_status == "fake" and v.stance == "contradict" and v.justification == "no such page"
    per_ev = map_evidence_results(scan, claims, ev)
    assert per_ev["a"].gptzero_status == "exist" and per_ev["b"].gptzero_status == "fake"


def test_unrecognised_status_becomes_unknown_and_files_style_list_is_accepted():
    scan = parse_biblio_response([{"bibliographic_citations": [{"id": 1, "text": "[1] x", "citation_exists": {"status": "Likely_Real"}}],
                                   "claims": None, "sources": None}])
    assert scan.bibliographic_citations[0].citation_exists.status == "unknown" and scan.claims == []


def test_verify_event_matches_the_events_contract():
    assert verify_event("c9", Verification(gptzero_status="fake", stance=None)) == {
        "cid": "c9", "layer": "gptzero", "status": "fake", "detail": "GPTZero bibliography scan: citation could not be found"}
    assert verify_event("c1", Verification(gptzero_status="exist", stance="support")) == {
        "cid": "c1", "layer": "gptzero", "status": "exist", "detail": "citation exists; source stance: support"}
    unknown = verify_event("c2", Verification(gptzero_status="unknown"))
    assert unknown["status"] == "unknown" and "local quote check decides" in unknown["detail"]
    assert verify_event("c3", Verification())["status"] == "not_checked"


# ---------------------------------------------------------------------------- bibliography_scan: replay / cache / ledger
async def test_replay_scan_is_offline_and_strikes_the_fire_drill(tmp_path):
    _, claims, evidence = load_fixture()
    evidence.append(Evidence(evid="e9", eid="sim", rid="web:fire-drill", quote="q", url="https://fire-drill.example.invalid/slopcheck",
                             citation=format_citation(9, "SlopCheck Labs", "SlopCheck raises Series A", "TechWire", 2026,
                                                      "https://fire-drill.example.invalid/slopcheck")))
    claims.append(Claim(cid="c9", kind="exists", by="critic", evidence=["e9"], text="SlopCheck already sells this exact product"))
    doc = build_document(claims, evidence)
    client = make_client(tmp_path, mode="replay")
    scan = await bibliography_scan(doc, client=client)
    assert scan.replayed and not scan.cached and scan.inputText == doc
    assert not (tmp_path / "cache").exists() and client.ledger.used("interactive") == 0
    out = map_results(scan, claims, evidence)
    assert out["c9"].gptzero_status == "fake" and resolve_status(out["c9"]) == "rejected"
    assert "[replay fixture]" in out["c9"].justification
    assert out["c1"].gptzero_status == "exist" and out["c1"].stance == "support"
    again = await bibliography_scan(doc, client=client)
    assert again.model_dump() == scan.model_dump(), "replay must be deterministic"


async def test_live_scan_charges_the_bucket_and_caches(tmp_path):
    raw, claims, evidence = load_fixture()
    doc = build_document(claims, evidence)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = {k: v for k, v in raw.items() if not k.startswith("_")}
        return httpx.Response(200, json=body)

    client = make_client(tmp_path, mode="live", handler=handler)
    scan = await bibliography_scan(doc, client=client)
    assert calls[0].url.path == "/v2/bibliography-scan/text" and json.loads(calls[0].content) == {"document": doc}
    assert calls[0].headers["x-api-key"] == "test-key"
    assert not scan.replayed and not scan.cached
    assert client.ledger.used("interactive") == len(doc.split())
    cached = await bibliography_scan(doc, client=client)
    assert len(calls) == 1 and cached.cached and client.ledger.used("interactive") == len(doc.split())
    assert resolve_status(map_results(cached, claims, evidence)["c3"]) == "rejected"


async def test_a_gated_endpoint_surfaces_as_an_error_the_verifier_can_catch(tmp_path):
    from app.signals.gptzero import GPTZeroError, GPTZeroHTTPError

    client = make_client(tmp_path, mode="live", handler=lambda req: httpx.Response(403, json={"error": "not allow-listed"}))
    with pytest.raises(GPTZeroHTTPError) as err:
        await bibliography_scan("1. A claim [1].\n\nReferences\n[1] A. \"A.\" Site. 2024. https://a.example", client=client)
    assert isinstance(err.value, GPTZeroError) and err.value.status == 403
    assert client.ledger.used("interactive") == 0
