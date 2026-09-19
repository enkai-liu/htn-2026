"""Verification layer 1: a deterministic receipt check. Does the quoted text really appear in the cited source?

No model is involved, so this layer cannot hallucinate and works with every sponsor API down. It is what gates an
"exists" claim (design-full.md 2.6): no local quote match -> the claim is shown as an unverified lead at best.

    quote_in_text(quote, text)                         pure function, normalised + tolerant containment
    await check_evidence(evidence, record_text=...)    uses the indexed description when we have it, else fetches the URL

Matching is on word sequences: case, unicode quotes/dashes, whitespace, punctuation, markdown and HTML remnants are
normalised away on both sides. "Verbatim" means the same words in the same order; "fuzzy" means at least `threshold`
(default 0.9) of the quote's words appear in order inside one window of the source (tolerates a dropped or inserted
word, or an LLM that tidied a typo). Quotes under 4 words are refused: they prove nothing.
"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import logging
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from app.schemas import Evidence, Verification

from .textutil import normalize_chars

log = logging.getLogger(__name__)

FUZZY_THRESHOLD = 0.9
MIN_QUOTE_TOKENS = 4
FETCH_TIMEOUT_S = 8.0
MAX_FETCH_BYTES = 2_000_000
MAX_TEXT_TOKENS = 400_000  # ~ the 2 MB body cap; the sliding window is linear in this
_MAX_WINDOWS = 1500
# An ordinary desktop browser UA. Devpost answers 403 to the bare "Mozilla/5.0" and 200 to a normal one.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")
_TEXT_TYPES = ("text/", "application/xhtml", "application/json", "application/xml")

_TAG = re.compile(r"<[^>]{1,400}>")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_MARKS = re.compile(r"[*`~#_]+")
_ELLIPSIS = re.compile(r"\[\s*\.\.\.\s*\]|\(\s*\.\.\.\s*\)|\.{3,}")


# ============================================================================ pure matching
@dataclass(frozen=True)
class QuoteMatch:
    match: bool
    score: float  # 1.0 = verbatim; otherwise the best in-order word overlap found
    method: Literal["exact", "fuzzy", "none"]
    detail: str

    def __bool__(self) -> bool:
        return self.match


def normalize(text: str) -> str:
    """Lowercase word sequence: HTML entities and tags, markdown marks, unicode punctuation and whitespace removed."""
    text = html.unescape(text or "")
    text = _TAG.sub(" ", text)
    text = _MD_IMAGE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = normalize_chars(text)
    text = _MD_MARKS.sub("", text)
    text = text.replace("'", "")  # don't / dont, team's / teams
    text = "".join(ch if ch.isalnum() else " " for ch in text.casefold())
    return " ".join(text.split())


def _segments(quote: str) -> list[list[str]]:
    """A quote with an elision ("first part ... second part") is checked piece by piece."""
    pieces = [normalize(p).split() for p in _ELLIPSIS.split(normalize_chars(quote or ""))]
    pieces = [p for p in pieces if p]
    long_enough = [p for p in pieces if len(p) >= MIN_QUOTE_TOKENS]
    return long_enough or ([[tok for p in pieces for tok in p]] if pieces else [])


def _find_exact(q: Sequence[str], t_joined: str) -> bool:
    return f" {' '.join(q)} " in t_joined


def _best_window(q: Sequence[str], t: Sequence[str], threshold: float) -> float:
    """Best share of the quote's words found IN ORDER inside one window of the text."""
    n = len(q)
    if n == 0 or not t:
        return 0.0
    width = min(len(t), n + max(2, n // 8))
    need = math.ceil(threshold * n)
    want = Counter(q)
    have: Counter[str] = Counter()
    overlap = 0

    def add(tok: str) -> None:
        nonlocal overlap
        if tok in want:
            have[tok] += 1
            if have[tok] <= want[tok]:
                overlap += 1

    def drop(tok: str) -> None:
        nonlocal overlap
        if tok in want:
            if have[tok] <= want[tok]:
                overlap -= 1
            have[tok] -= 1

    best, evaluated = 0.0, 0
    matcher = SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(list(q))
    for i in range(width):
        add(t[i])
    start = 0
    while True:
        if overlap >= need and evaluated < _MAX_WINDOWS:  # cheap bag-of-words bound before the ordered comparison
            evaluated += 1
            matcher.set_seq1(list(t[start:start + width]))
            score = sum(b.size for b in matcher.get_matching_blocks()) / n
            if score > best:
                best = score
                if best >= 1.0:
                    break
        if start + width >= len(t):
            break
        drop(t[start])
        add(t[start + width])
        start += 1
    return best


def quote_in_text(quote: str, text: str, *, threshold: float = FUZZY_THRESHOLD) -> QuoteMatch:
    """Is `quote` contained in `text`? Truthy result on a match; `.detail` is safe to show in the UI."""
    segments = _segments(quote)
    n_tokens = sum(len(s) for s in segments)
    if n_tokens < MIN_QUOTE_TOKENS:
        return QuoteMatch(False, 0.0, "none", f"quote too short to verify (needs at least {MIN_QUOTE_TOKENS} words)")
    t_tokens = normalize(text).split()[:MAX_TEXT_TOKENS]
    if not t_tokens:
        return QuoteMatch(False, 0.0, "none", "source text is empty")
    t_joined = f" {' '.join(t_tokens)} "

    if all(_find_exact(seg, t_joined) for seg in segments):
        return QuoteMatch(True, 1.0, "exact", _describe(True, 1.0, "exact", "the source", len(segments)))
    scores = [1.0 if _find_exact(seg, t_joined) else _best_window(seg, t_tokens, threshold) for seg in segments]
    score = round(min(scores), 3)
    if score >= threshold:
        return QuoteMatch(True, score, "fuzzy", _describe(True, score, "fuzzy", "the source", len(segments)))
    return QuoteMatch(False, score, "none", _describe(False, score, "none", "the source", len(segments)))


def _describe(match: bool, score: float, method: str, where: str, n_segments: int = 1) -> str:
    """One UI-safe sentence. `where` is "the indexed record" / "the fetched page" / "the source"."""
    if match and method == "exact":
        return f"quote found verbatim in {where}" + (" (each part of the elided quote)" if n_segments > 1 else "")
    if match:
        return f"quote found in {where} with minor differences ({score:.0%} of its words, in order)"
    return f"quote not found in {where}" + (f" (closest passage shares {score:.0%} of its words)" if score >= 0.5 else "")


# ============================================================================ fetching
@dataclass(frozen=True)
class QuoteCheck:
    match: bool
    detail: str
    source: Literal["record", "fetched", "none"] = "none"
    score: float = 0.0
    method: str = "none"
    http_status: int | None = None

    def __bool__(self) -> bool:
        return self.match


def blocked_reason(url: str) -> str | None:
    """URLs we refuse to fetch. Devpost's /software/search sits behind a bot challenge and is off limits by design."""
    try:
        parts = urlparse(url)
    except ValueError:
        return "malformed URL"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "not an http(s) URL"
    host = parts.hostname.lower()
    path = parts.path.rstrip("/").lower()
    if (host == "devpost.com" or host.endswith(".devpost.com")) and (path == "/software/search" or path.startswith("/software/search/")):
        return "Devpost search pages are never fetched"
    if host == "localhost" or host.endswith((".local", ".internal")):
        return "private host"
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return "private address"
    except ValueError:
        pass
    return None


def visible_text(markup: str) -> str:
    """Visible text of an HTML page (title included). Plain text passes through."""
    if "<" not in markup:
        return markup
    from bs4 import BeautifulSoup  # optional dependency ("ingest" extra); only needed when we actually fetch

    soup = BeautifulSoup(markup, "html.parser")
    for tag in soup(["script", "style", "noscript", "template", "svg", "iframe"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


async def fetch_page_text(url: str, *, client: httpx.AsyncClient | None = None) -> tuple[str | None, int | None, str | None]:
    """(text, http_status, error). 8 s timeout, normal UA, body capped at MAX_FETCH_BYTES. Never raises."""
    reason = blocked_reason(url)
    if reason:
        return None, None, reason
    own = client is None
    c = client or httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, follow_redirects=True, max_redirects=5)
    try:
        async with c.stream("GET", url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                                                 "Accept-Language": "en"}, timeout=FETCH_TIMEOUT_S) as resp:
            final = blocked_reason(str(resp.url))
            if final:
                return None, resp.status_code, f"redirected to a blocked URL ({final})"
            if resp.status_code >= 400:
                return None, resp.status_code, f"HTTP {resp.status_code}"
            ctype = resp.headers.get("content-type", "text/html").lower()
            if not ctype.startswith(_TEXT_TYPES):
                return None, resp.status_code, f"unsupported content type {ctype.split(';')[0]}"
            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_FETCH_BYTES:
                    break
            body = b"".join(chunks)[:MAX_FETCH_BYTES].decode(resp.encoding or "utf-8", errors="replace")
            return visible_text(body), resp.status_code, None
    except httpx.TimeoutException:
        return None, None, f"timed out after {FETCH_TIMEOUT_S:.0f}s"
    except (httpx.HTTPError, OSError, ValueError) as exc:
        return None, None, f"fetch failed ({type(exc).__name__})"
    finally:
        if own:
            await c.aclose()


async def check_evidence(evidence: Evidence, *, record_text: str | None = None, client: httpx.AsyncClient | None = None,
                         fetch_fallback: bool = False, threshold: float = FUZZY_THRESHOLD) -> QuoteCheck:
    """Layer-1 verdict for one piece of evidence.

    record_text: the indexed description the agent was shown. When given it is authoritative and nothing is fetched
    (unless fetch_fallback=True and the quote is not in it). Otherwise the cited URL is fetched once."""
    quote = (evidence.quote or "").strip()
    if not quote:
        return QuoteCheck(False, "evidence carries no quote", "none")
    if record_text:
        m = quote_in_text(quote, record_text, threshold=threshold)
        if m.match or not fetch_fallback:
            return QuoteCheck(m.match, _where(m, "the indexed record"), "record", m.score, m.method)
    text, status, error = await fetch_page_text(evidence.url, client=client)
    if text is None:
        gone = status in (404, 410)
        return QuoteCheck(False, "cited page does not exist" if gone else f"cited page could not be checked: {error}",
                          "none", http_status=status)
    m = quote_in_text(quote, text, threshold=threshold)
    return QuoteCheck(m.match, _where(m, "the fetched page"), "fetched", m.score, m.method, status)


def _where(m: QuoteMatch, where: str) -> str:
    """Re-word a QuoteMatch for a specific source; "too short" / "empty" details pass through unchanged."""
    return m.detail.replace("the source", where) if "the source" in m.detail else m.detail


async def check_many(evidence: Sequence[Evidence], *, record_texts: Mapping[str, str] | None = None, concurrency: int = 6,
                     fetch_fallback: bool = False) -> dict[str, QuoteCheck]:
    """{evid: QuoteCheck}. record_texts maps rid -> indexed description. One shared HTTP client, bounded concurrency."""
    record_texts = record_texts or {}
    sem = asyncio.Semaphore(max(1, concurrency))
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, follow_redirects=True, max_redirects=5) as client:

        async def one(ev: Evidence) -> tuple[str, QuoteCheck]:
            async with sem:
                try:
                    return ev.evid, await check_evidence(ev, record_text=record_texts.get(ev.rid), client=client,
                                                         fetch_fallback=fetch_fallback)
                except Exception as exc:  # noqa: BLE001  a verifier must never take the run down
                    log.warning("quote check crashed for %s: %r", ev.evid, exc)
                    return ev.evid, QuoteCheck(False, f"quote check failed ({type(exc).__name__})", "none")

        return dict(await asyncio.gather(*(one(ev) for ev in evidence)))


# ============================================================================ glue for the verifier role
def to_verification(check: QuoteCheck, existing: Verification | None = None) -> Verification:
    """Record the layer-1 result, keeping whatever layer 2 (GPTZero) already wrote."""
    base = existing.model_dump() if existing is not None else {}
    base["local_quote_match"] = check.match
    return Verification(**base)


def verify_event(cid: str, check: QuoteCheck) -> dict[str, Any]:
    """`data` for a verify.result event, layer "quote" (docs/events.md)."""
    return {"cid": cid, "layer": "quote", "status": "match" if check.match else "no_match", "detail": check.detail}
