"""GPTZero parsing and client behaviour, fully offline.

Covers the spec discipline the product is judged on: sentence-level `paraphrased` vs document-level `mixed`,
`should_mask`, the 250-character gate, deprecated fields never required or read, replay never touching the network,
and the live path (retry on 429, ledger, sha256 cache) against an in-process mock transport.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from tenacity import wait_none

from app.schemas import GPTZeroScan, Voice
from app.signals import gptzero as gz
from app.signals.gptzero import (
    DocumentClassProbabilities,
    GPTZeroClient,
    GPTZeroConfigError,
    GPTZeroDocument,
    GPTZeroHTTPError,
    GPTZeroQuotaError,
    GPTZeroSentence,
    GPTZeroUnavailable,
    SentenceClassProbabilities,
    TextTooShort,
    locate_sentences,
    neighbourhood_slop_share,
    parse_predict_response,
    strip_deprecated,
    to_scan,
    to_voice,
    voice_for_pitch,
)
from app.signals.gptzero_budget import BudgetExceeded, WordLedger

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gptzero"
SIGNALS_DIR = Path(gz.__file__).resolve().parent
DEPRECATED = ("completely_generated_prob", "average_generated_prob")

PITCH = ("Whitespace checks how original your hackathon idea is before you build it. You paste a pitch, and a team of "
         "agents searches hundreds of thousands of past hackathon projects, startups and repos for prior art, argues "
         "about whether it is really the same idea, and verifies every claim against its source before you see it.")
assert len(PITCH) >= 250


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def minimal_payload(**doc_overrides) -> dict:
    """The smallest response we accept: NO deprecated fields, no probabilities at all."""
    doc = {"predicted_class": "human", "confidence_category": "medium",
           "result_message": "Our detector is moderately confident that the text is written by a human.",
           "sentences": [{"sentence": "One sentence.", "highlight_sentence_for_ai": False}]}
    doc.update(doc_overrides)
    return {"version": "2025-11-28-base", "documents": [doc]}


class NoNetwork(httpx.AsyncBaseTransport):
    """Any request is a test failure."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"network call attempted: {request.method} {request.url}")


def make_client(tmp_path: Path, *, mode: str, handler=None, api_key: str = "test-key", cap: int = 10_000, attempts: int = 4) -> GPTZeroClient:
    ledger = WordLedger(tmp_path / "ledger.json", caps={"interactive": cap, "investigation": cap})
    transport = httpx.MockTransport(handler) if handler is not None else NoNetwork()
    return GPTZeroClient(mode=mode, api_key=api_key, ledger=ledger, cache_dir=tmp_path / "cache", transport=transport,
                         retry_wait=wait_none(), max_attempts=attempts)


# ---------------------------------------------------------------------------- fixtures parse into the documented subset
@pytest.mark.parametrize(("name", "cls", "subclass", "classification"), [
    ("predict_human", "human", None, "HUMAN_ONLY"),
    ("predict_ai", "ai", "pure_ai", "AI_ONLY"),
    ("predict_mixed", "mixed", "concatenated", "MIXED"),
])
def test_fixtures_parse(name, cls, subclass, classification):
    raw = fixture(name)
    assert raw["_fixture"] == "synthetic, shaped like the documented GPTZero response"
    doc = parse_predict_response(raw)
    assert isinstance(doc, GPTZeroDocument)
    assert doc.predicted_class == cls
    assert doc.confidence_category == "high"
    assert doc.subclass_label == subclass
    assert doc.document_classification == classification
    assert doc.model_version == "2025-11-28-base" and doc.scan_id
    assert doc.result_message and doc.sentences
    assert not doc.replayed and not doc.cached


def test_subclass_follows_predicted_class_only():
    raw = fixture("predict_human")
    raw["documents"][0]["subclass"] = {"ai": {"predicted_class": "pure_ai"}}  # stray subclass on a human verdict
    assert parse_predict_response(raw).subclass_label is None
    mixed = fixture("predict_mixed")
    mixed["documents"][0]["subclass"]["mixed"]["predicted_class"] = "polished"
    assert parse_predict_response(mixed).subclass_label == "polished"


# ---------------------------------------------------------------------------- deprecated fields
def test_payload_without_deprecated_fields_parses():
    for name in ("predict_human", "predict_ai", "predict_mixed"):
        assert not any(d in json.dumps(fixture(name)) for d in DEPRECATED), "fixtures must not carry deprecated fields"
    doc = parse_predict_response(minimal_payload())
    assert doc.predicted_class == "human" and doc.confidence_category == "medium"
    assert doc.class_probabilities is None
    assert to_scan(doc).predicted_class == "human"


def test_deprecated_fields_are_ignored_even_when_present_and_contradictory():
    clean = fixture("predict_ai")
    dirty = copy.deepcopy(clean)
    d = dirty["documents"][0]
    d["completely_generated_prob"] = 0.0  # says "human" while the documented fields say "ai"
    d["average_generated_prob"] = 0.0
    for p in d["paragraphs"]:
        p["completely_generated_prob"] = 0.0
    a, b = parse_predict_response(clean), parse_predict_response(dirty)
    assert a.model_dump() == b.model_dump()
    text = " ".join(s.sentence for s in a.sentences)
    assert to_voice(text, a) == to_voice(text, b)
    for name in DEPRECATED:
        assert name not in GPTZeroDocument.model_fields and name not in GPTZeroSentence.model_fields
        assert not hasattr(b, name)
        assert name not in json.dumps(b.model_dump(mode="json"))


def test_strip_deprecated_is_recursive():
    raw = {"documents": [{"completely_generated_prob": 0.9, "average_generated_prob": 0.8, "predicted_class": "ai",
                          "paragraphs": [{"start_sentence_index": 0, "num_sentences": 1, "completely_generated_prob": 0.9}],
                          "sentences": [{"sentence": "x", "generated_prob": 0.9}]}]}
    out = strip_deprecated(raw)
    assert not any(d in json.dumps(out) for d in DEPRECATED)
    assert out["documents"][0]["paragraphs"] == [{"start_sentence_index": 0, "num_sentences": 1}]
    assert out["documents"][0]["sentences"][0]["generated_prob"] == 0.9  # the sentence-level field is documented, kept


def test_source_never_reads_deprecated_fields():
    """The names may appear exactly once: in the constant used to DELETE them from payloads before caching."""
    for path in SIGNALS_DIR.glob("*.py"):
        lines = [ln for ln in path.read_text().splitlines() if any(d in ln for d in DEPRECATED)]
        if path.name == "gptzero.py":
            assert len(lines) == 1 and lines[0].startswith("_DEPRECATED_KEYS"), lines
        else:
            assert lines == [], f"{path.name} mentions a deprecated field: {lines}"


# ---------------------------------------------------------------------------- paraphrased (sentence) vs mixed (document)
def test_the_two_probability_types_are_distinct():
    assert set(DocumentClassProbabilities.model_fields) == {"ai", "human", "mixed"}
    assert set(SentenceClassProbabilities.model_fields) == {"human", "ai", "paraphrased"}
    doc = parse_predict_response(fixture("predict_mixed"))
    assert isinstance(doc.class_probabilities, DocumentClassProbabilities)
    assert doc.class_probabilities.mixed == pytest.approx(0.9418)
    assert not hasattr(doc.class_probabilities, "paraphrased")
    s0 = doc.sentences[0].class_probabilities
    assert isinstance(s0, SentenceClassProbabilities)
    assert s0.paraphrased == pytest.approx(0.0075)
    assert not hasattr(s0, "mixed")


def test_each_type_rejects_the_other_levels_shape():
    doc_shape = {"ai": 0.1, "human": 0.2, "mixed": 0.7}
    sent_shape = {"ai": 0.1, "human": 0.2, "paraphrased": 0.7}
    DocumentClassProbabilities.model_validate(doc_shape)
    SentenceClassProbabilities.model_validate(sent_shape)
    with pytest.raises(ValidationError, match="paraphrased"):
        DocumentClassProbabilities.model_validate(sent_shape)
    with pytest.raises(ValidationError, match="mixed"):
        SentenceClassProbabilities.model_validate(doc_shape)
    with pytest.raises(ValidationError):
        DocumentClassProbabilities.model_validate({"ai": 0.1, "human": 0.9})  # `mixed` is required at document level
    with pytest.raises(ValidationError):
        SentenceClassProbabilities.model_validate({"ai": 0.1, "human": 0.9})  # `paraphrased` is required per sentence


def test_swapped_shapes_are_dropped_never_coerced():
    raw = fixture("predict_mixed")
    d = raw["documents"][0]
    d["class_probabilities"], d["sentences"][0]["class_probabilities"] = (
        d["sentences"][0]["class_probabilities"], d["class_probabilities"])
    doc = parse_predict_response(raw)
    assert doc.class_probabilities is None
    assert doc.sentences[0].class_probabilities is None
    assert isinstance(doc.sentences[1].class_probabilities, SentenceClassProbabilities)
    assert doc.predicted_class == "mixed" and doc.sentences[0].flagged  # the verdict never depended on them


# ---------------------------------------------------------------------------- should_mask
def test_masked_sentences_are_never_flagged_and_never_scored():
    doc = parse_predict_response(fixture("predict_mixed"))
    masked = [s for s in doc.sentences if s.should_mask]
    assert len(masked) == 1 and masked[0].highlight_sentence_for_ai and masked[0].masking_reason == "references"
    assert masked[0].flagged is False
    unmasked = [s for s in doc.sentences if not s.should_mask]
    expected = sum(len(s.sentence) for s in unmasked if s.highlight_sentence_for_ai) / sum(len(s.sentence) for s in unmasked)
    assert doc.ai_sentence_share == pytest.approx(expected, abs=1e-4)
    with_mask = sum(len(s.sentence) for s in doc.sentences if s.highlight_sentence_for_ai) / sum(len(s.sentence) for s in doc.sentences)
    assert doc.ai_sentence_share != pytest.approx(with_mask, abs=1e-3)

    text = " ".join(s.sentence for s in doc.sentences)
    voice = to_voice(text, doc)
    assert [v.flagged for v in voice.sentences] == [True, True, False, False, False]
    assert voice.ai_sentence_share == doc.ai_sentence_share


def test_share_is_none_when_everything_is_masked():
    raw = minimal_payload(sentences=[{"sentence": "print('hi')", "highlight_sentence_for_ai": True, "should_mask": True,
                                      "masking_reason": "code_block"}])
    assert parse_predict_response(raw).ai_sentence_share is None


def test_missing_mask_and_highlight_default_to_false():
    s = GPTZeroSentence.model_validate({"sentence": "Hello there.", "should_mask": None, "highlight_sentence_for_ai": None})
    assert s.should_mask is False and s.flagged is False


# ---------------------------------------------------------------------------- sentence offsets
def test_offsets_index_into_the_original_text():
    text = "  First   sentence here.\n\nSecond “quoted” sentence — with a dash.  Third one!  "
    returned = ["First sentence here.", 'Second "quoted" sentence - with a dash.', "Third one!"]  # re-spaced, ASCII-fied
    spans = locate_sentences(text, returned)
    assert all(s is not None for s in spans)
    assert text[spans[0][0]:spans[0][1]] == "First   sentence here."
    assert text[spans[1][0]:spans[1][1]] == "Second “quoted” sentence — with a dash."
    assert text[spans[2][0]:spans[2][1]] == "Third one!"
    assert spans[0][1] <= spans[1][0] <= spans[1][1] <= spans[2][0]


def test_repeated_sentences_map_to_successive_positions():
    text = "Same line. Same line. Different line."
    spans = locate_sentences(text, ["Same line.", "Same line.", "Different line."])
    assert spans == [(0, 10), (11, 21), (22, 37)]


def test_to_voice_offsets_and_flags():
    body = PITCH + " Our innovative platform leverages cutting-edge AI to revolutionize ideation."
    raw = minimal_payload(predicted_class="mixed", confidence_category="high", sentences=[
        {"sentence": s, "highlight_sentence_for_ai": i == 2}
        for i, s in enumerate(re.split(r"(?<=\.)\s+", body))])
    voice = to_voice(body, parse_predict_response(raw))
    assert isinstance(voice, Voice) and not voice.too_short
    assert [v.flagged for v in voice.sentences] == [False, False, True]
    for v in voice.sentences:
        assert body[v.start:v.end] == v.text
    assert voice.sentences[-1].end == len(body)
    flagged_chars = len(voice.sentences[2].text)
    assert voice.ai_sentence_share == pytest.approx(flagged_chars / sum(len(v.text) for v in voice.sentences), abs=1e-4)


def test_unlocatable_sentence_is_skipped_but_still_counted():
    raw = minimal_payload(sentences=[{"sentence": PITCH[:74], "highlight_sentence_for_ai": False},
                                     {"sentence": "This sentence is not in the text at all.", "highlight_sentence_for_ai": True}])
    voice = to_voice(PITCH, parse_predict_response(raw))
    assert len(voice.sentences) == 1
    assert voice.ai_sentence_share == pytest.approx(40 / (74 + 40), abs=1e-4)


# ---------------------------------------------------------------------------- the 250-character gate
def test_to_voice_gate():
    short = "Uber for dogs."
    v = to_voice(short, None)
    assert v.too_short and v.predicted_class is None and v.sentences == [] and "250" in (v.result_message or "")
    # even if a document is supplied, a short pitch is not assessed
    assert to_voice(short, parse_predict_response(fixture("predict_ai"))).too_short


async def test_short_text_never_reaches_the_api(tmp_path):
    client = make_client(tmp_path, mode="live")  # NoNetwork transport: a call would fail the test
    with pytest.raises(TextTooShort):
        await client.predict_text("x" * 249)
    voice = await voice_for_pitch("Uber for dogs.", client=client)
    assert voice.too_short
    assert client.ledger.used("interactive") == 0


async def test_the_gate_is_exactly_250_characters(tmp_path):
    client = make_client(tmp_path, mode="replay")
    base = ("word " * 50).strip()  # 249 characters; surrounding whitespace does not count
    assert len(base) == 249
    with pytest.raises(TextTooShort):
        await client.predict_text("   " + base + "   ")
    assert to_voice(base, None).too_short
    doc = await client.predict_text(base + "s")
    assert doc.replayed and not to_voice(base + "s", doc).too_short


# ---------------------------------------------------------------------------- replay mode
async def test_replay_is_offline_deterministic_and_labelled(tmp_path):
    client = make_client(tmp_path, mode="replay", api_key="")
    a = await client.predict_text(PITCH)
    b = await client.predict_text(PITCH)
    assert a.model_dump(exclude={"scanned_at"}) == b.model_dump(exclude={"scanned_at"})
    assert a.replayed and not a.cached and a.model_version == gz.REPLAY_MODEL_VERSION
    assert not (tmp_path / "cache").exists(), "replay must not write synthetic responses into the cache"
    assert client.ledger.used("interactive") == 0

    voice = to_voice(PITCH, a)
    assert voice.result_message.startswith("[replay fixture")
    assert "".join(PITCH[v.start:v.end] for v in voice.sentences).replace(" ", "") == PITCH.replace(" ", "")
    scan = to_scan(a)
    assert isinstance(scan, GPTZeroScan) and scan.model_version == gz.REPLAY_MODEL_VERSION
    assert scan.result_message.startswith("[replay fixture")


async def test_replay_covers_all_three_fixtures(tmp_path):
    client = make_client(tmp_path, mode="replay")
    seen = set()
    for i in range(40):
        doc = await client.predict_text(f"{PITCH} Variant number {i}.")
        seen.add(doc.predicted_class)
        if doc.predicted_class == "ai":
            assert all(s.flagged for s in doc.sentences)
        if doc.predicted_class == "human":
            assert not any(s.flagged for s in doc.sentences)
    assert seen == {"human", "ai", "mixed"}


async def test_replay_prefers_a_real_cached_response(tmp_path):
    live = make_client(tmp_path, mode="live", handler=lambda req: httpx.Response(200, json=_live_payload()))
    await live.predict_text(PITCH)
    replay = make_client(tmp_path, mode="replay")
    doc = await replay.predict_text(PITCH)
    assert doc.cached and not doc.replayed and doc.model_version == "2026-01-01-live"
    assert to_voice(PITCH, doc).result_message == "Our detector is highly confident that the text is written by AI."


# ---------------------------------------------------------------------------- live path (mock transport)
def _live_payload() -> dict:
    raw = fixture("predict_ai")
    raw.pop("_fixture")
    raw["version"] = "2026-01-01-live"
    raw["documents"][0]["completely_generated_prob"] = 0.99
    raw["documents"][0]["average_generated_prob"] = 0.98
    raw["documents"][0]["sentences"] = [{"sentence": PITCH[:74], "highlight_sentence_for_ai": True,
                                         "class_probabilities": {"human": 0.01, "ai": 0.98, "paraphrased": 0.01}}]
    return raw


async def test_live_retries_429_then_caches_and_charges_once(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": "Too many requests, hourly rate limit reached"})
        return httpx.Response(200, json=_live_payload())

    client = make_client(tmp_path, mode="live", handler=handler)
    doc = await client.predict_text(PITCH, bucket="investigation")
    assert len(calls) == 2
    req = calls[-1]
    assert req.url.path == "/v2/predict/text" and req.headers["x-api-key"] == "test-key"
    assert json.loads(req.content) == {"document": PITCH}
    assert doc.predicted_class == "ai" and not doc.cached and not doc.replayed
    assert client.ledger.used("investigation") == len(PITCH.split()) and client.ledger.used("interactive") == 0
    assert client.ledger.snapshot()["investigation"]["reserved"] == 0

    again = await client.predict_text(PITCH, bucket="investigation")
    assert len(calls) == 2 and again.cached
    assert client.ledger.used("investigation") == len(PITCH.split()), "a cache hit must not be charged"

    cached_files = list((tmp_path / "cache" / "predict").glob("*.json"))
    assert len(cached_files) == 1 and cached_files[0].stem == gz.text_sha256(PITCH)
    assert not any(d in cached_files[0].read_text() for d in DEPRECATED), "deprecated fields must not be persisted"


async def test_word_limit_429_is_not_retried_and_releases_the_reservation(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, json={"error": "Monthy limit of 1 million words has been reached. Consider upgrading your plan to Pro"})

    client = make_client(tmp_path, mode="live", handler=handler)
    with pytest.raises(GPTZeroQuotaError):
        await client.predict_text(PITCH)
    assert len(calls) == 1
    assert client.ledger.snapshot()["interactive"] == {"cap": 10_000, "committed": 0, "reserved": 0, "remaining": 10_000, "calls": 0}


async def test_5xx_exhausts_retries_then_voice_abstains(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, json={"error": "upstream failure"})

    client = make_client(tmp_path, mode="live", handler=handler, attempts=3)
    with pytest.raises(GPTZeroUnavailable):
        await client.predict_text(PITCH)
    assert len(calls) == 3 and client.ledger.used("interactive") == 0
    voice = await voice_for_pitch(PITCH, client=client)
    assert not voice.too_short and voice.predicted_class is None and "abstains" in voice.result_message


async def test_client_errors_are_not_retried(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404, json={"error": "API key not found"})

    client = make_client(tmp_path, mode="live", handler=handler)
    with pytest.raises(GPTZeroHTTPError) as err:
        await client.predict_text(PITCH)
    assert err.value.status == 404 and len(calls) == 1


async def test_budget_cap_blocks_the_call(tmp_path):
    client = make_client(tmp_path, mode="live", cap=10)  # NoNetwork: nothing may be sent
    with pytest.raises(BudgetExceeded):
        await client.predict_text(PITCH)
    assert client.ledger.used("interactive") == 0


async def test_live_mode_without_a_key_is_a_clear_error(tmp_path):
    client = make_client(tmp_path, mode="live", api_key="")
    with pytest.raises(GPTZeroConfigError, match="GPTZERO_API_KEY"):
        await client.predict_text(PITCH)


async def test_concurrent_identical_requests_are_billed_once(tmp_path):
    import asyncio

    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=_live_payload())

    client = make_client(tmp_path, mode="live", handler=handler)
    docs = await asyncio.gather(*(client.predict_text(PITCH) for _ in range(5)))
    assert len(calls) == 1 and sum(d.cached for d in docs) == 4
    assert client.ledger.used("interactive") == len(PITCH.split())


async def test_documents_missing_is_a_parse_error():
    with pytest.raises(gz.GPTZeroParseError):
        parse_predict_response({"error": "something"})
    with pytest.raises(gz.GPTZeroParseError):
        parse_predict_response(minimal_payload(predicted_class="robot"))


# ---------------------------------------------------------------------------- app schema outputs
def test_to_scan_carries_no_probabilities():
    scan = to_scan(parse_predict_response(fixture("predict_mixed")))
    assert scan.model_dump(mode="json", exclude={"scanned_at"}) == {
        "predicted_class": "mixed", "confidence_category": "high", "subclass": "concatenated", "ai_sentence_share": 0.4946,
        "result_message": "Our detector is highly confident that the text may include parts written by AI.",
        "model_version": "2025-11-28-base"}
    assert scan.scanned_at is not None


def test_voice_never_exposes_raw_probabilities():
    doc = parse_predict_response(fixture("predict_ai"))
    dumped = json.dumps(to_voice(" ".join(s.sentence for s in doc.sentences), doc).model_dump(mode="json"))
    for leak in ("generated_prob", "class_probabilities", "confidence_score", "perplexity", "0.9875", "0.9712"):
        assert leak not in dumped


def test_case_is_normalised():
    doc = parse_predict_response(minimal_payload(predicted_class="AI", confidence_category="HIGH"))
    assert doc.predicted_class == "ai" and doc.confidence_category == "high"


def test_neighbourhood_slop_share():
    def scan(cls, conf):
        return GPTZeroScan(predicted_class=cls, confidence_category=conf)

    assert neighbourhood_slop_share([]) is None
    assert neighbourhood_slop_share([scan("ai", "high"), scan("ai", "high")]) is None  # fewer than 3 scans
    assert neighbourhood_slop_share([scan("ai", "high"), None, scan("ai", "high")]) is None  # unscanned records don't count
    scans = [scan("ai", "high"), scan("mixed", "high"), scan("ai", "medium"), scan("human", "high"),
             {"predicted_class": "mixed", "confidence_category": "low"}, None]
    assert neighbourhood_slop_share(scans) == pytest.approx(2 / 5)
    assert neighbourhood_slop_share([scan("human", "high")] * 3) == 0.0
