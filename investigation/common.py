"""Shared plumbing for the Slop Index scripts. Run them from the repo root: `python -m investigation.<name>`.

Importing this module puts `backend/` on sys.path so `app.config` and `app.signals` resolve.
"""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import DATA_DIR  # noqa: E402

RESULTS_DIR = REPO_ROOT / "investigation" / "results"
RAW_DIR = RESULTS_DIR / "raw"  # git-ignored
PRIVATE_DIR = DATA_DIR / "investigation_private"  # data/ is git-ignored: the only place a project URL may live
SAMPLE_PATH = RESULTS_DIR / "sample.parquet"  # *.parquet is git-ignored
SAMPLE_MAP_PATH = PRIVATE_DIR / "sample_map.parquet"
SCANS_PATH = RESULTS_DIR / "scans.parquet"
SCANS_LOG_PATH = RAW_DIR / "scans.jsonl"
NEIGHBOURS_PATH = RESULTS_DIR / "neighbours.parquet"  # optional: sample_id, nn_sim (from investigation/neighbours.py)
SLOP_INDEX_PATH = RESULTS_DIR / "slop_index.json"
PUBLIC_CSV_PATH = RESULTS_DIR / "slop_index_public.csv"

SEED = 20260919
MIN_CHARS = 600  # keep write-ups at least this long ...
MAX_CHARS = 1800  # ... and truncate all of them to this, at a sentence boundary (length control)
YEARS_HISTORIC = (2018, 2019, 2021, 2022, 2023, 2024)  # alvanlii/devpost-hackathon-projects
YEARS_RECENT = (2025, 2026)  # twangodev/devpost-hacks
PLACEBO_YEARS = (2018, 2019, 2020, 2021)  # before ChatGPT (2022-11-30): anything flagged here is a false positive
REPLAY_MODEL_VERSION = "replay-fixture"  # mirrors app.signals.gptzero.REPLAY_MODEL_VERSION; marks synthetic scans

# twangodev/devpost-hacks has no date column, only the hackathon's Devpost slug. Years checked against
# devpost.com/api/hackathons on 2026-09-19 (submission period END).
RECENT_HACKATHON_YEARS = {
    "treehacks-2024": 2024, "pennapps-xxv": 2024, "madhacks": 2024,
    "treehacks-2025": 2025, "hackgt-12": 2025, "cal-hacks-12-0": 2025, "madhacks-fall-2025": 2025,
    "treehacks-2026": 2026, "hacktech-by-caltech-2026": 2026,
}


class InvestigationError(SystemExit):
    """A clear, actionable message and a non-zero exit; no traceback for expected problems."""

    def __init__(self, message: str) -> None:
        super().__init__(f"ERROR: {message}")


# ---------------------------------------------------------------------------- dates
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_PART = re.compile(r"(?:(?P<mon>[A-Za-z]{3,9})\.?\s+)?(?P<day>\d{1,2})(?:\s*,\s*(?P<year>(?:19|20)\d{2}))?")


def parse_period(period: str | None) -> tuple[dt.date | None, dt.date | None]:
    """Devpost `submission_period_dates` -> (start, end).

    "Oct 01 - Dec 04, 2024"        -> 2024-10-01, 2024-12-04
    "Feb 27 - 28, 2016"            -> 2016-02-27, 2016-02-28
    "Mar 10, 2018"                 -> 2018-03-10, 2018-03-10
    "Dec 15, 2023 - Jan 20, 2024"  -> 2023-12-15, 2024-01-20   (spans years)
    "Dec 28 - Jan 02, 2024"        -> 2023-12-28, 2024-01-02   (start year implied)
    """
    if not isinstance(period, str) or not period.strip():
        return None, None
    text = period.replace(chr(0x2013), "-").replace(chr(0x2014), "-").strip()
    halves = [h.strip() for h in re.split(r"\s+-\s+|(?<=\d)-(?=\s*[A-Za-z\d])", text, maxsplit=1)]
    parsed = [_PART.search(h) for h in halves]
    if any(p is None for p in parsed):
        return None, None
    last = parsed[-1]
    if last is None or not last.group("year"):
        return None, None
    end_year = int(last.group("year"))
    first = parsed[0]
    assert first is not None
    start_month = _MONTHS.get((first.group("mon") or "")[:3].lower())
    end_month = _MONTHS.get((last.group("mon") or "")[:3].lower()) or start_month
    if start_month is None or end_month is None:
        return None, None
    if first.group("year"):
        start_year = int(first.group("year"))
    else:
        start_year = end_year - 1 if start_month > end_month else end_year
    try:
        return dt.date(start_year, start_month, int(first.group("day"))), dt.date(end_year, end_month, int(last.group("day")))
    except ValueError:
        return None, None


def parse_period_year(period: str | None) -> int | None:
    """The year a hackathon's write-ups were finalised: the END of its submission period.
    "Dec 15, 2023 - Jan 20, 2024" -> 2024. Falls back to the last year mentioned when the format is unfamiliar."""
    _start, end = parse_period(period)
    if end is not None:
        return end.year
    years = _YEAR.findall(period) if isinstance(period, str) else []
    return int(years[-1]) if years else None


def recent_hackathon_year(slug: str | None) -> int | None:
    """Year for a twangodev/devpost-hacks hackathon slug: the verified table first, then a year in the slug itself."""
    if not isinstance(slug, str):
        return None
    slug = slug.strip().lower()
    if slug in RECENT_HACKATHON_YEARS:
        return RECENT_HACKATHON_YEARS[slug]
    m = _YEAR.search(slug)
    return int(m.group(0)) if m else None


# ---------------------------------------------------------------------------- text
_STOPWORDS = frozenset(
    "the of and to a in is that it for on with as was we our this are be by an at from or have has not but can "
    "which will their you your they i were been its also more one all would there what about when so how up out if "
    "into than then them these us using used use which while during after because".split())
_WORD = re.compile(r"[A-Za-z']+")


def clean_writeup(text: Any) -> str:
    """Normalise whitespace but keep paragraph breaks (GPTZero treats newlines as paragraph boundaries)."""
    if not isinstance(text, str):
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(chr(0x00A0), " ")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def looks_english(text: str, *, min_ascii: float = 0.9, min_stopword_share: float = 0.2) -> bool:
    """Cheap language gate (no langdetect dependency): mostly ASCII letters AND enough common English function words.
    Spanish/French/Portuguese text passes the ASCII test but scores well under 0.1 on the stopword share."""
    if not text:
        return False
    sample = text[:4000]
    visible = [ch for ch in sample if not ch.isspace()]
    if not visible:
        return False
    if sum(ch.isascii() for ch in visible) / len(visible) < min_ascii:
        return False
    words = [w.lower() for w in _WORD.findall(sample)]
    if len(words) < 30:
        return False
    return sum(w in _STOPWORDS for w in words) / len(words) >= min_stopword_share


def is_winner_from_prize(prize: Any) -> bool:
    """alvanlii stores `prize` as the repr of a list: "['1st Place']" or "[]"."""
    if prize is None:
        return False
    if hasattr(prize, "tolist") and not isinstance(prize, str):
        prize = prize.tolist()
    if isinstance(prize, (list, tuple)):
        return any(str(p).strip() for p in prize)
    text = str(prize).strip()
    if text in ("", "[]", "nan", "None", "<NA>"):
        return False
    if text.startswith("["):
        try:
            parsed = ast.literal_eval(text)
            return bool(parsed) and any(str(p).strip() for p in parsed)
        except (ValueError, SyntaxError):
            return len(text) > 2
    return True


def stable_hash(*parts: Any) -> str:
    return hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def sample_id_for(url: str, seed: int = SEED) -> str:
    """Opaque id used in every results file. Deterministic so a re-run never orphans scans we already paid for.
    It is a hash of the project URL, so it is NOT published: export_public.py drops it."""
    return stable_hash("whitespace-slop-index", seed, url.strip().lower())[:16]


def sample_rank(url: str, seed: int = SEED) -> str:
    """Sort key for sampling. Taking the N smallest per year is a uniform sample that is stable under N:
    the 50-per-year pilot is a subset of the 150-per-year run, so pilot scans are never wasted."""
    return stable_hash("rank", seed, url.strip().lower())


def require_pandas():
    try:
        import pandas as pd  # noqa: F401
        import pyarrow  # noqa: F401
    except ImportError as exc:  # the "ingest" extra
        raise InvestigationError("pandas and pyarrow are required: backend/.venv/bin/pip install -e 'backend[ingest]'") from exc
    import pandas as pd

    return pd
