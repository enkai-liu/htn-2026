"""GPTZero client: AI detection (`/v2/predict/text`) for the Voice axis, evidence badges and the Slop Index.

Spec discipline (verified against GPTZero's docs backend, see docs/research/02-gptzero-baseten.md A1/A4):
  * We read `predicted_class`, `confidence_category`, `class_probabilities`, `subclass`, `result_message` and the
    sentence-level `highlight_sentence_for_ai` / `should_mask`. The deprecated document/paragraph probability
    fields are never modelled, never read, and are stripped before a response is cached.
  * Document-level class_probabilities is {ai, human, mixed}; sentence-level is {human, ai, paraphrased}. They are
    two different types here (DocumentClassProbabilities / SentenceClassProbabilities) and each rejects the other's key.
  * Masked sentences (`should_mask`: code blocks, tables, reference lists) are never flagged and never scored.
  * Under 250 characters the detector is unreliable: we do not call it, the Voice axis says "too short".
  * Users see `result_message` + `confidence_category`. Raw probabilities never leave this module's models.
  * AI-probability is not unoriginality: everything here feeds the separate Voice channel, never the headline score.

Modes (settings.gptzero_mode):
  replay (default)  never touches the network. Serves the sha256 cache if the text was scanned before, otherwise a
                    deterministic synthetic response built from backend/fixtures/gptzero/, marked `replayed=True`.
  live              cache -> reserve words in the ledger -> POST with retry on 429/5xx -> commit -> cache.
"""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import hashlib
import json
import logging
import os
import re
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.config import DATA_DIR, FIXTURES_DIR, Settings, get_settings
from app.schemas import GPTZeroScan, Voice, VoiceSentence

from .gptzero_budget import BudgetExceeded, WordLedger, get_ledger
from .textutil import NormalizedText, count_words, sentence_spans, truncate_at_sentence

log = logging.getLogger(__name__)

MIN_CHARS = 250  # GPTZero's documented minimum for a trustworthy result
MAX_CHARS = 50_000  # the API silently truncates beyond this; we truncate explicitly so the word count is honest
PREDICT_PATH = "/v2/predict/text"
BIBLIO_PATH = "/v2/bibliography-scan/text"
USAGE_PATH = "/v3/usage-stats"
CACHE_DIRNAME = "gptzero_cache"
FIXTURE_MARK = "_fixture"
REPLAY_MODEL_VERSION = "replay-fixture"  # model_version of every synthetic scan, so it can never pass for a real one
REPLAY_LABEL = "[replay fixture, not a real scan] "
TOO_SHORT_MESSAGE = f"Too short to assess reliably (GPTZero needs at least {MIN_CHARS} characters)."
KNOWN_SUBCLASSES = ("pure_ai", "ai_paraphrased", "concatenated", "polished")

# Deprecated / internal-use-only per the spec. Listed ONLY so they can be deleted from payloads before caching.
_DEPRECATED_KEYS = frozenset({"completely_generated_prob", "average_generated_prob"})
_PREDICT_FIXTURES = ("predict_human", "predict_ai", "predict_mixed")
# A 429 is either the plan's word limit (retrying is pointless; docs example: "Monthy limit of 1 million words has
# been reached. Consider upgrading your plan to Pro") or the hourly request limit (back off and retry).
_QUOTA_429 = re.compile(r"\bwords?\b|month|upgrad|quota", re.I)
_RATE_429 = re.compile(r"hour|per (second|minute)|too many requests|rate.?limit", re.I)


# ============================================================================ errors
class GPTZeroError(RuntimeError):
    """Base class. Callers degrade on this: the Voice axis abstains, the local quote check still gates claims."""


class GPTZeroConfigError(GPTZeroError):
    """Live mode without an API key."""


class TextTooShort(GPTZeroError, ValueError):
    """Under MIN_CHARS. We refuse to call rather than report an unreliable verdict."""


class GPTZeroHTTPError(GPTZeroError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(f"GPTZero HTTP {status}: {message}")


class GPTZeroQuotaError(GPTZeroHTTPError):
    """429 caused by the plan's word limit. Retrying cannot help."""


class GPTZeroUnavailable(GPTZeroError):
    """Retryable: hourly rate limit (429), 5xx, or a transport failure. Raised once the retries are exhausted."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(message)


class GPTZeroParseError(GPTZeroError):
    """The response did not carry the documented fields we need."""


# ============================================================================ response models (documented subset)
class _Lenient(BaseModel):
    """Unknown keys are ignored, so new API fields never break us and deprecated ones cannot be reached."""

    model_config = ConfigDict(extra="ignore")


def _reject_key(v: Any, forbidden: str, hint: str) -> Any:
    if isinstance(v, dict) and forbidden in v:
        raise ValueError(f"`{forbidden}` does not belong here: {hint}")
    return v


class DocumentClassProbabilities(_Lenient):
    """DOCUMENT level: {ai, human, mixed}. There is no `paraphrased` at this level."""

    ai: float
    human: float
    mixed: float

    @model_validator(mode="before")
    @classmethod
    def _not_sentence_shaped(cls, v: Any) -> Any:
        return _reject_key(v, "paraphrased", "document-level class_probabilities uses `mixed`; `paraphrased` is sentence-level")


class SentenceClassProbabilities(_Lenient):
    """SENTENCE level: {human, ai, paraphrased}. There is no `mixed` at this level."""

    human: float
    ai: float
    paraphrased: float

    @model_validator(mode="before")
    @classmethod
    def _not_document_shaped(cls, v: Any) -> Any:
        return _reject_key(v, "mixed", "sentence-level class_probabilities uses `paraphrased`; `mixed` is document-level")


def _or_none(model: type[BaseModel], what: str) -> Callable[[Any], Any]:
    """Optional sub-objects we never need for a verdict: if the API sends an unexpected shape, drop it (loudly)
    instead of failing the whole scan or, worse, coercing it into the wrong type."""

    def validate(v: Any) -> Any:
        if v is None or isinstance(v, model):
            return v
        try:
            return model.model_validate(v)
        except ValidationError as exc:
            log.warning("GPTZero %s had an unexpected shape and was dropped: %s", what, exc.errors()[0].get("msg"))
            return None

    return validate


class GPTZeroSentence(_Lenient):
    sentence: str
    generated_prob: float | None = None  # documented sentence-level field; internal only, never shown to users
    perplexity: float | None = None
    highlight_sentence_for_ai: bool = False
    class_probabilities: SentenceClassProbabilities | None = None
    should_mask: bool = False
    masking_reason: str | None = None
    special_highlight_type: str | None = None

    _v_probs = field_validator("class_probabilities", mode="before")(
        _or_none(SentenceClassProbabilities, "sentence class_probabilities"))

    @field_validator("highlight_sentence_for_ai", "should_mask", mode="before")
    @classmethod
    def _none_is_false(cls, v: Any) -> Any:
        return False if v is None else v

    @property
    def flagged(self) -> bool:
        """What the UI may highlight: GPTZero's own highlight decision, unless the sentence is masked."""
        return bool(self.highlight_sentence_for_ai) and not self.should_mask


class SubclassPrediction(_Lenient):
    predicted_class: str
    confidence_category: str | None = None
    confidence_score: float | None = None
    class_probabilities: dict[str, float] | None = None


class GPTZeroSubclass(_Lenient):
    """Only present when predicted_class is ai (pure_ai | ai_paraphrased) or mixed (concatenated | polished)."""

    ai: SubclassPrediction | None = None
    mixed: SubclassPrediction | None = None

    _v_ai = field_validator("ai", mode="before")(_or_none(SubclassPrediction, "subclass.ai"))
    _v_mixed = field_validator("mixed", mode="before")(_or_none(SubclassPrediction, "subclass.mixed"))


class ExcludedSpan(_Lenient):
    start: int
    end: int
    text: str | None = None
    reason: str | None = None


class GPTZeroDocument(_Lenient):
    """documents[0] of /v2/predict/text, plus the envelope fields and our own bookkeeping."""

    predicted_class: Literal["human", "ai", "mixed"]
    confidence_category: Literal["high", "medium", "low"]
    class_probabilities: DocumentClassProbabilities | None = None
    document_classification: str | None = None  # HUMAN_ONLY | MIXED | AI_ONLY
    result_message: str | None = None
    result_sub_message: str | None = None
    subclass: GPTZeroSubclass | None = None
    sentences: list[GPTZeroSentence] = Field(default_factory=list)
    excluded_spans: list[ExcludedSpan] = Field(default_factory=list)
    language: str | None = None
    document_id: str | None = None
    # envelope (top level of the response)
    model_version: str | None = None
    neat_version: str | None = None
    scan_id: str | None = None
    # bookkeeping
    replayed: bool = False  # True = synthetic fixture response (replay mode, nothing cached for this text)
    cached: bool = False  # True = a real response served from DATA_DIR/gptzero_cache
    n_words: int | None = None
    scanned_at: dt.datetime | None = None

    _v_probs = field_validator("class_probabilities", mode="before")(
        _or_none(DocumentClassProbabilities, "document class_probabilities"))
    _v_subclass = field_validator("subclass", mode="before")(_or_none(GPTZeroSubclass, "subclass"))

    @field_validator("predicted_class", "confidence_category", mode="before")
    @classmethod
    def _lower(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("sentences", "excluded_spans", mode="before")
    @classmethod
    def _none_is_empty(cls, v: Any) -> Any:
        return [] if v is None else v

    @property
    def subclass_label(self) -> str | None:
        """pure_ai | ai_paraphrased for `ai`, concatenated | polished for `mixed`, None for `human`."""
        if self.subclass is None or self.predicted_class == "human":
            return None
        pred = self.subclass.ai if self.predicted_class == "ai" else self.subclass.mixed
        return pred.predicted_class if pred is not None else None

    @property
    def ai_sentence_share(self) -> float | None:
        """Flagged characters / unmasked characters. None when nothing is scoreable."""
        unmasked = [s for s in self.sentences if not s.should_mask and s.sentence.strip()]
        total = sum(len(s.sentence.strip()) for s in unmasked)
        if total == 0:
            return None
        return round(sum(len(s.sentence.strip()) for s in unmasked if s.flagged) / total, 4)


class GPTZeroPredictResponse(_Lenient):
    version: str | None = None
    neatVersion: str | None = None
    scanId: str | None = None
    documents: list[GPTZeroDocument] = Field(default_factory=list)


def parse_predict_response(raw: dict[str, Any], *, replayed: bool = False, cached: bool = False,
                           n_words: int | None = None, scanned_at: dt.datetime | None = None) -> GPTZeroDocument:
    """Raw /v2/predict/text JSON -> GPTZeroDocument. Raises GPTZeroParseError, never a bare ValidationError."""
    try:
        resp = GPTZeroPredictResponse.model_validate(raw)
    except ValidationError as exc:
        raise GPTZeroParseError(f"unexpected /v2/predict/text response: {exc.errors()[:3]}") from exc
    if not resp.documents:
        raise GPTZeroParseError("response has no documents[]" + (f": {raw.get('error')}" if isinstance(raw, dict) and raw.get("error") else ""))
    return resp.documents[0].model_copy(update={
        "model_version": REPLAY_MODEL_VERSION if replayed else resp.version, "neat_version": resp.neatVersion,
        "scan_id": resp.scanId, "replayed": replayed, "cached": cached, "n_words": n_words, "scanned_at": scanned_at,
    })


# ============================================================================ client
def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strip_deprecated(obj: Any) -> Any:
    """Recursively delete the deprecated probability fields so they are never persisted."""
    if isinstance(obj, dict):
        return {k: strip_deprecated(v) for k, v in obj.items() if k not in _DEPRECATED_KEYS}
    if isinstance(obj, list):
        return [strip_deprecated(v) for v in obj]
    return obj


def _default_wait(retry_state: RetryCallState) -> float:
    base = wait_exponential_jitter(initial=1.0, max=20.0)(retry_state)
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    retry_after = getattr(exc, "retry_after", None)
    return max(base, min(float(retry_after), 60.0)) if retry_after else base


class GPTZeroClient:
    """One shared instance per process (see get_client()). `transport` exists so tests can run the live path offline."""

    def __init__(self, *, settings: Settings | None = None, ledger: WordLedger | None = None,
                 cache_dir: Path | str | None = None, fixtures_dir: Path | str | None = None,
                 mode: Literal["replay", "live"] | None = None, api_key: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, max_attempts: int = 4,
                 retry_wait: Callable[[RetryCallState], float] | None = None, timeout_s: float = 30.0) -> None:
        s = settings or get_settings()
        self.mode: str = mode or s.gptzero_mode
        self.api_key = s.gptzero_api_key if api_key is None else api_key
        self.base_url = s.gptzero_base_url.rstrip("/")
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DATA_DIR / CACHE_DIRNAME
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir is not None else FIXTURES_DIR / "gptzero"
        self._ledger = ledger
        self._transport = transport
        self._timeout = timeout_s
        self._max_attempts = max_attempts
        self._retry_wait = retry_wait or _default_wait
        self._http: httpx.AsyncClient | None = None
        self._inflight: dict[str, asyncio.Lock] = {}

    @property
    def ledger(self) -> WordLedger:
        if self._ledger is None:
            self._ledger = get_ledger()
        return self._ledger

    # ------------------------------------------------------------------ endpoints
    async def predict_text(self, text: str, *, bucket: str = "interactive", multilingual: bool = False) -> GPTZeroDocument:
        """AI detection on one string. Raises TextTooShort under 250 chars, BudgetExceeded at the cap, GPTZeroError otherwise."""
        text = prepare_text(text)
        if len(text) < MIN_CHARS:
            raise TextTooShort(f"{len(text)} characters; GPTZero needs at least {MIN_CHARS} for a reliable result")
        body: dict[str, Any] = {"document": text}
        if multilingual:
            body["multilingual"] = True  # French/Spanish only per the API docs; never combine with modelVersion
        raw, source, meta = await self.fetch("predict", PREDICT_PATH, body, text, bucket=bucket,
                                             replay=self._replay_predict, variant="ml" if multilingual else "")
        return parse_predict_response(raw, replayed=source == "fixture", cached=source == "cache",
                                      n_words=count_words(text), scanned_at=meta.get("scanned_at"))

    async def usage_stats(self) -> dict[str, Any] | None:
        """GET /v3/usage-stats -> {words_left, words_used, cycle_start, cycle_end, plan}. None in replay mode.
        `words_left` is null on the metered API (Enterprise) plan."""
        if self.mode != "live":
            return None
        self._require_key()
        resp = await self._client().get(self.base_url + USAGE_PATH, headers=self._headers())
        if resp.status_code != 200:
            raise GPTZeroHTTPError(resp.status_code, _error_message(resp))
        return resp.json()

    # ------------------------------------------------------------------ shared machinery (also used by biblio.py)
    async def fetch(self, kind: str, path: str, body: dict[str, Any], text: str, *, bucket: str,
                    replay: Callable[[str], dict[str, Any]], variant: str = "") -> tuple[dict[str, Any], str, dict[str, Any]]:
        """Returns (raw_response, source, meta) with source in {"cache", "fixture", "live"}."""
        key = text_sha256(text) + (f"-{variant}" if variant else "")
        cache_path = self.cache_dir / kind / f"{key}.json"
        lock = self._inflight.setdefault(f"{kind}:{key}", asyncio.Lock())
        try:
            async with lock:  # identical concurrent requests collapse into one billed call
                hit = self._cache_read(cache_path)
                if hit is not None:
                    return hit["response"], "cache", {"scanned_at": _parse_ts(hit.get("cached_at"))}
                if self.mode != "live":
                    return replay(text), "fixture", {}
                self._require_key()
                n_words = count_words(text)
                reservation = self.ledger.reserve(bucket, n_words)  # BudgetExceeded propagates; nothing is sent
                try:
                    raw = await self._post(path, body)
                except BaseException:
                    self.ledger.release(reservation)
                    raise
                self.ledger.commit(reservation)
                raw = strip_deprecated(raw)
                now = dt.datetime.now(dt.timezone.utc)
                self._cache_write(cache_path, {"endpoint": path, "cached_at": now.isoformat(), "n_words": n_words,
                                               "bucket": bucket, "response": raw})
                return raw, "live", {"scanned_at": now}
        finally:
            if not lock.locked():
                self._inflight.pop(f"{kind}:{key}", None)

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        async for attempt in AsyncRetrying(stop=stop_after_attempt(self._max_attempts), wait=self._retry_wait,
                                           retry=retry_if_exception_type(GPTZeroUnavailable), reraise=True):
            with attempt:
                try:
                    resp = await self._client().post(self.base_url + path, json=body, headers=self._headers())
                except httpx.TransportError as exc:
                    raise GPTZeroUnavailable(f"transport error: {exc!r}") from exc
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except ValueError as exc:
                        raise GPTZeroUnavailable("200 with a non-JSON body") from exc
                    if not isinstance(data, dict):
                        raise GPTZeroParseError(f"expected a JSON object, got {type(data).__name__}")
                    return data
                message = _error_message(resp)
                if resp.status_code == 429:
                    if _QUOTA_429.search(message) and not _RATE_429.search(message):
                        raise GPTZeroQuotaError(429, message)
                    # The docs warn a 429 can also mean the x-api-key header was malformed (free-tier limits applied).
                    raise GPTZeroUnavailable(f"429 rate limited: {message}", retry_after=_retry_after(resp))
                if resp.status_code >= 500:
                    raise GPTZeroUnavailable(f"{resp.status_code}: {message}", retry_after=_retry_after(resp))
                raise GPTZeroHTTPError(resp.status_code, message)
        raise GPTZeroUnavailable("retries exhausted")  # pragma: no cover  (reraise=True raises above)

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=self._timeout, transport=self._transport)
        return self._http

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key, "Accept": "application/json", "Content-Type": "application/json"}

    def _require_key(self) -> None:
        if not self.api_key:
            raise GPTZeroConfigError("GPTZERO_MODE=live but GPTZERO_API_KEY is empty. Set the key or use GPTZERO_MODE=replay.")

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()

    # ------------------------------------------------------------------ cache
    @staticmethod
    def _cache_read(path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("response"), dict):
            return None
        if FIXTURE_MARK in data["response"]:  # a synthetic payload must never be served as a real scan
            return None
        return data

    @staticmethod
    def _cache_write(path: Path, payload: dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
            tmp.write_text(json.dumps(payload))
            os.replace(tmp, path)
        except OSError as exc:  # a read-only disk must not lose a scan we already paid for
            log.warning("could not write GPTZero cache %s: %s", path, exc)

    # ------------------------------------------------------------------ replay
    def load_fixture(self, name: str) -> dict[str, Any]:
        path = self.fixtures_dir / f"{name}.json"
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise GPTZeroError(f"replay fixture missing or unreadable: {path}") from exc

    def _replay_predict(self, text: str) -> dict[str, Any]:
        """Deterministic synthetic response: the fixture is picked by the text's hash, and its sentences[] are rebuilt
        from the caller's own text so highlights and offsets line up in the UI. Marked via `_fixture` -> replayed=True."""
        name = _PREDICT_FIXTURES[int(text_sha256(text)[:8], 16) % len(_PREDICT_FIXTURES)]
        raw = copy.deepcopy(self.load_fixture(name))
        raw.setdefault(FIXTURE_MARK, "synthetic, shaped like the documented GPTZero response")
        doc = raw["documents"][0]
        spans = sentence_spans(text)
        n = len(spans)
        if doc.get("predicted_class") == "ai":
            flags = [True] * n
        elif doc.get("predicted_class") == "mixed":
            flags = [i < (n + 1) // 2 for i in range(n)]  # "concatenated": an AI-written opening, human remainder
        else:
            flags = [False] * n
        doc["sentences"] = [{"sentence": text[a:b], "highlight_sentence_for_ai": f, "should_mask": False,
                             "masking_reason": None, **copy.deepcopy(_REPLAY_SENTENCE[f])}
                            for (a, b), f in zip(spans, flags)]
        doc["paragraphs"] = [{"start_sentence_index": 0, "num_sentences": n}]
        doc["excluded_spans"] = []
        return raw


_REPLAY_SENTENCE: dict[bool, dict[str, Any]] = {
    True: {"generated_prob": 0.97, "perplexity": 9, "class_probabilities": {"human": 0.02, "ai": 0.97, "paraphrased": 0.01}},
    False: {"generated_prob": 0.03, "perplexity": 84, "class_probabilities": {"human": 0.96, "ai": 0.03, "paraphrased": 0.01}},
}


def prepare_text(text: str) -> str:
    """What we actually send (and hash): stripped, capped at the API's 50,000-character truncation point."""
    text = (text or "").strip()
    return text[:MAX_CHARS] if len(text) > MAX_CHARS else text


def _error_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            return str(data.get("error") or data.get("message") or data)[:300]
    except ValueError:
        pass
    return (resp.text or "")[:300]


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return float(resp.headers.get("retry-after", ""))
    except ValueError:
        return None


def _parse_ts(value: Any) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


_client: GPTZeroClient | None = None


def get_client() -> GPTZeroClient:
    global _client
    if _client is None:
        _client = GPTZeroClient()
    return _client


def set_client(client: GPTZeroClient | None) -> None:
    """Swap the process-wide client (tests, or after settings change)."""
    global _client
    _client = client


async def predict_text(text: str, *, bucket: str = "interactive") -> GPTZeroDocument:
    return await get_client().predict_text(text, bucket=bucket)


# ============================================================================ conversions to the app's schemas
def locate_sentences(text: str, sentences: Sequence[str]) -> list[tuple[int, int] | None]:
    """(start, end) offsets into `text` for each returned sentence, in order; None when a sentence cannot be found.
    Exact search first, then a normalised search (whitespace, unicode quotes/dashes, case) mapped back to real offsets."""
    out: list[tuple[int, int] | None] = []
    norm: NormalizedText | None = None
    cursor = 0
    for sent in sentences:
        needle = sent.strip()
        span: tuple[int, int] | None = None
        if needle:
            idx = text.find(needle, cursor)
            if idx >= 0:
                span = (idx, idx + len(needle))
            else:
                norm = norm or NormalizedText(text)
                span = norm.find(needle, cursor) or norm.find(needle, 0)
        if span is not None and span[0] >= cursor:
            cursor = span[1]
        out.append(span)
    return out


def to_voice(text: str, doc: GPTZeroDocument | None, *, neighbourhood_slop_share: float | None = None) -> Voice:
    """The Voice axis payload. Under 250 characters it abstains without looking at `doc` (and no call should be made)."""
    if len((text or "").strip()) < MIN_CHARS:
        return Voice(too_short=True, result_message=TOO_SHORT_MESSAGE, neighbourhood_slop_share=neighbourhood_slop_share)
    if doc is None:
        return Voice(result_message="Voice unavailable: GPTZero could not be reached, so this axis abstains.",
                     neighbourhood_slop_share=neighbourhood_slop_share)
    spans = locate_sentences(text, [s.sentence for s in doc.sentences])
    sentences = [VoiceSentence(text=text[span[0]:span[1]], start=span[0], end=span[1], flagged=s.flagged)
                 for s, span in zip(doc.sentences, spans) if span is not None]
    sentences.sort(key=lambda v: v.start)
    return Voice(
        too_short=False, predicted_class=doc.predicted_class, confidence_category=doc.confidence_category,
        result_message=_display_message(doc), ai_sentence_share=doc.ai_sentence_share, sentences=sentences,
        neighbourhood_slop_share=neighbourhood_slop_share,
    )


def to_scan(doc: GPTZeroDocument) -> GPTZeroScan:
    """What we persist on a record (and write back to Elasticsearch as gptzero.*). No probabilities of any kind."""
    return GPTZeroScan(
        predicted_class=doc.predicted_class, confidence_category=doc.confidence_category, subclass=doc.subclass_label,
        ai_sentence_share=doc.ai_sentence_share, result_message=_display_message(doc),
        model_version=REPLAY_MODEL_VERSION if doc.replayed else doc.model_version,
        scanned_at=doc.scanned_at or dt.datetime.now(dt.timezone.utc),
    )


def _display_message(doc: GPTZeroDocument) -> str | None:
    if doc.replayed:
        return REPLAY_LABEL + (doc.result_message or "")
    return doc.result_message


def is_slop(scan: GPTZeroScan) -> bool:
    """Our one flagging rule, used everywhere: not human AND high confidence (GPTZero's <1% error band)."""
    return scan.predicted_class != "human" and scan.confidence_category == "high"


def neighbourhood_slop_share(scans: Iterable[GPTZeroScan | dict[str, Any] | None]) -> float | None:
    """Share of the neighbourhood's write-ups that are AI-written or mixed with HIGH confidence.
    None with fewer than 3 scans: too few to call a share. AI-written projects are badged, never discarded."""
    valid = [s if isinstance(s, GPTZeroScan) else GPTZeroScan.model_validate(s) for s in scans if s is not None]
    if len(valid) < 3:
        return None
    return round(sum(1 for s in valid if is_slop(s)) / len(valid), 4)


# ============================================================================ convenience for the roles
async def voice_for_pitch(text: str, *, bucket: str = "interactive", max_chars: int = 3000,
                          neighbourhood_slop_share: float | None = None, client: GPTZeroClient | None = None) -> Voice:
    """Gate -> scan -> Voice. Never raises: if GPTZero is down or the budget is spent, the Voice axis abstains visibly."""
    text = (text or "").strip()
    if len(text) < MIN_CHARS:
        return to_voice(text, None, neighbourhood_slop_share=neighbourhood_slop_share)
    scanned = truncate_at_sentence(text, max_chars) if len(text) > max_chars else text  # bounds words per run
    try:
        doc = await (client or get_client()).predict_text(scanned, bucket=bucket)
    except (GPTZeroError, BudgetExceeded) as exc:
        log.warning("voice axis abstains: %s", exc)
        return Voice(result_message=f"Voice unavailable, this axis abstains ({type(exc).__name__}).",
                     neighbourhood_slop_share=neighbourhood_slop_share)
    return to_voice(text, doc, neighbourhood_slop_share=neighbourhood_slop_share)


async def scan_texts(texts: Sequence[str], *, bucket: str = "interactive", max_chars: int = 1500, concurrency: int = 4,
                     client: GPTZeroClient | None = None) -> list[GPTZeroScan | None]:
    """Evidence badges: scan the top-k pitches (truncated to `max_chars`). None = too short, failed, or over budget."""
    c = client or get_client()
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(t: str) -> GPTZeroScan | None:
        t = truncate_at_sentence((t or "").strip(), max_chars)
        if len(t) < MIN_CHARS:
            return None
        async with sem:
            try:
                return to_scan(await c.predict_text(t, bucket=bucket))
            except (GPTZeroError, BudgetExceeded) as exc:
                log.warning("evidence scan skipped: %s", exc)
                return None

    return list(await asyncio.gather(*(one(t) for t in texts)))
