"""Signals lane: GPTZero (Voice axis, evidence badges, claim verification) and the deterministic quote check.

Typical use from a role:

    from app.signals import voice_for_pitch, scan_texts, neighbourhood_slop_share        # Voice axis (own channel)
    voice = await voice_for_pitch(idea_text)                                             # never raises; abstains

    from app.signals import check_many, build_document, bibliography_scan, map_results, resolve_status
    checks = await check_many(evidence, record_texts={rid: description})                 # layer 1, deterministic
    scan   = await bibliography_scan(build_document(claims, evidence))                   # layer 2, GPTZero
    for cid, v in map_results(scan, claims, evidence).items():
        status = resolve_status(v)                                                       # verified | unverified_lead | rejected

GPTZERO_MODE=replay (the default) never touches the network; see gptzero.py.
"""
from .biblio import (
    BiblioScan,
    bibliography_scan,
    build_document,
    citation_for_record,
    format_citation,
    is_contradicted,
    is_fake,
    map_evidence_results,
    map_results,
    resolve_status,
)
from .gptzero import (
    MIN_CHARS,
    REPLAY_MODEL_VERSION,
    DocumentClassProbabilities,
    GPTZeroClient,
    GPTZeroConfigError,
    GPTZeroDocument,
    GPTZeroError,
    GPTZeroHTTPError,
    GPTZeroParseError,
    GPTZeroQuotaError,
    GPTZeroSentence,
    GPTZeroUnavailable,
    SentenceClassProbabilities,
    TextTooShort,
    get_client,
    is_slop,
    neighbourhood_slop_share,
    parse_predict_response,
    predict_text,
    scan_texts,
    set_client,
    to_scan,
    to_voice,
    voice_for_pitch,
)
from .gptzero_budget import BudgetExceeded, Reservation, WordLedger, count_words, get_ledger
from .quote_check import QuoteCheck, QuoteMatch, check_evidence, check_many, quote_in_text, to_verification

__all__ = [
    "MIN_CHARS",
    "REPLAY_MODEL_VERSION",
    "BiblioScan",
    "BudgetExceeded",
    "DocumentClassProbabilities",
    "GPTZeroClient",
    "GPTZeroConfigError",
    "GPTZeroDocument",
    "GPTZeroError",
    "GPTZeroHTTPError",
    "GPTZeroParseError",
    "GPTZeroQuotaError",
    "GPTZeroSentence",
    "GPTZeroUnavailable",
    "QuoteCheck",
    "QuoteMatch",
    "Reservation",
    "SentenceClassProbabilities",
    "TextTooShort",
    "WordLedger",
    "bibliography_scan",
    "build_document",
    "check_evidence",
    "check_many",
    "citation_for_record",
    "count_words",
    "format_citation",
    "get_client",
    "get_ledger",
    "is_contradicted",
    "is_fake",
    "is_slop",
    "map_evidence_results",
    "map_results",
    "neighbourhood_slop_share",
    "parse_predict_response",
    "predict_text",
    "quote_in_text",
    "resolve_status",
    "scan_texts",
    "set_client",
    "to_scan",
    "to_verification",
    "to_voice",
    "voice_for_pitch",
]
