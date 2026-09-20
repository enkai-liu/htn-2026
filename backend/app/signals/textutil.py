"""Small text helpers shared by the GPTZero client and the quote check."""
from __future__ import annotations

import re
import unicodedata

# Unicode punctuation that writers, scrapers and LLMs use interchangeably with the ASCII form.
# Written as code points on purpose: several of these are invisible and would not survive an editor.
_CHAR_MAP: dict[str, str] = {
    chr(cp): repl
    for cps, repl in (
        ((0x2018, 0x2019, 0x201A, 0x201B, 0x2032, 0x0060, 0x00B4), "'"),  # single quotes, prime, backtick, acute
        ((0x201C, 0x201D, 0x201E, 0x201F, 0x2033, 0x00AB, 0x00BB), '"'),  # double quotes, double prime, guillemets
        ((0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212), "-"),  # hyphens, en/em dashes, minus
        ((0x2026,), "..."),  # ellipsis
        ((0x00A0, 0x2009, 0x202F), " "),  # no-break and thin spaces
        ((0x200B, 0x200C, 0x200D, 0xFEFF, 0x00AD), ""),  # zero-width characters, BOM, soft hyphen
    )
    for cp in cps
}

# Sentence end: terminator(s), optional closing quotes/brackets (incl. right double/single curly quotes), then space or end.
_SENT_END = re.compile(r"[.!?]+[\"')\]" + chr(0x201D) + chr(0x2019) + r"]*(?=\s|$)")


def count_words(text: str) -> int:
    """Whitespace word count. GPTZero bills per word; this is the estimate the ledger reserves."""
    return len(text.split())


def normalize_chars(text: str) -> str:
    """NFKC + ASCII quotes/dashes. Length is NOT preserved; use NormalizedText when offsets matter."""
    text = unicodedata.normalize("NFKC", text)
    return "".join(_CHAR_MAP.get(ch, ch) for ch in text)


class NormalizedText:
    """A normalised view of a string (NFKC, ASCII quotes/dashes, casefold, whitespace runs -> one space)
    that remembers, for every normalised character, the index of the original character it came from.
    Lets us find a sentence that was re-spaced or re-quoted upstream and still report offsets into the original."""

    __slots__ = ("original", "text", "_origin")

    def __init__(self, original: str) -> None:
        self.original = original
        out: list[str] = []
        origin: list[int] = []
        prev_space = True  # swallow leading whitespace
        for i, raw in enumerate(original):
            for ch in normalize_chars(raw):
                if ch.isspace():
                    if prev_space:
                        continue
                    out.append(" ")
                    origin.append(i)
                    prev_space = True
                else:
                    out.append(ch.casefold())
                    # casefold can expand one char into several (e.g. the German sharp s)
                    origin.extend([i] * (len(out[-1]) - 1))
                    origin.append(i)
                    prev_space = False
        text = "".join(out)
        # "".join may be longer than len(out) when casefold expanded; origin was extended to match.
        if text.endswith(" "):
            text = text[:-1]
            origin = origin[: len(text)]
        self.text = text
        self._origin = origin

    def norm_index(self, original_index: int) -> int:
        """First normalised position whose source index is >= original_index."""
        lo, hi = 0, len(self._origin)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._origin[mid] < original_index:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def find(self, needle: str, original_start: int = 0) -> tuple[int, int] | None:
        """Locate `needle` (normalised the same way) at or after `original_start`. Returns ORIGINAL (start, end)."""
        n = NormalizedText(needle).text
        if not n:
            return None
        pos = self.text.find(n, self.norm_index(original_start))
        if pos < 0:
            return None
        start = self._origin[pos]
        end = self._origin[pos + len(n) - 1] + 1
        return start, end


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Split into sentence spans (start, end) over the ORIGINAL string. Newlines are hard boundaries.
    Deliberately simple: good enough for replay fixtures and for cutting a write-up at a sentence boundary."""
    spans: list[tuple[int, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        cursor = 0
        for m in _SENT_END.finditer(body):
            _push(spans, body, offset, cursor, m.end())
            cursor = m.end()
        _push(spans, body, offset, cursor, len(body))
        offset += len(line)
    return spans


def _push(spans: list[tuple[int, int]], body: str, offset: int, start: int, end: int) -> None:
    chunk = body[start:end]
    stripped = chunk.strip()
    if not stripped:
        return
    lead = len(chunk) - len(chunk.lstrip())
    s = offset + start + lead
    spans.append((s, s + len(stripped)))


def truncate_at_sentence(text: str, max_chars: int, *, min_keep: float = 0.5) -> str:
    """Cut to <= max_chars at the last sentence boundary (length control for evidence scans).
    Falls back to the last whitespace when no boundary lies beyond `min_keep * max_chars`."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    best = 0
    for _start, end in sentence_spans(text):
        if end <= max_chars:
            best = end
        else:
            break
    if best >= max_chars * min_keep:
        return text[:best].rstrip()
    cut = text.rfind(" ", 0, max_chars)
    return text[: cut if cut > 0 else max_chars].rstrip()
