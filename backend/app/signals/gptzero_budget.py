"""Word ledger for GPTZero. Billing is per WORD, not per request, so every live call reserves words first.

Two buckets with separate caps (settings: GPTZERO_INTERACTIVE_WORD_CAP / GPTZERO_INVESTIGATION_WORD_CAP):
  interactive    pitch voice, evidence badges, report verification (the live product)
  investigation  the Slop Index corpus scan

Persisted at RUNS_DIR/gptzero_ledger.json so the cap survives restarts and is shared by the backend and the
investigation scripts. Safe across threads, asyncio tasks and processes: a process-local RLock plus an exclusive
flock (a bounded msvcrt lock on Windows) on a sidecar lock file around every read-modify-write, and atomic
replace on write. Calls are sub-millisecond file operations, so they are fine to make directly from async code.

    r = ledger.reserve("interactive", n_words)     # raises BudgetExceeded before any network call
    try:    ...call GPTZero...; ledger.commit(r)
    except: ledger.release(r); raise
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]
try:  # Windows: without this, two handles (or processes) on one ledger lose updates and os.replace hits sharing errors
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None  # type: ignore[assignment]


from app.config import RUNS_DIR, get_settings

from .textutil import count_words

log = logging.getLogger(__name__)

# The ledger is called synchronously on the server's event loop, so waiting for the Windows lock must be bounded: a
# lock that is never released (stale handle, another process) would otherwise freeze every run in the server.
WINDOWS_LOCK_WAIT_S = 2.0


def _lock_file(f: Any) -> bool:
    """Exclusive cross-process lock on the sidecar file. False = not acquired (Windows only, after WINDOWS_LOCK_WAIT_S);
    the in-process RLock still serialises this process."""
    if fcntl is not None:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        return True
    if msvcrt is None:  # pragma: no cover
        return False
    deadline = time.monotonic() + WINDOWS_LOCK_WAIT_S  # pragma: no cover - Windows only
    while True:  # pragma: no cover - Windows only
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                log.warning("GPTZero ledger lock busy for %.0fs; continuing with the in-process lock only", WINDOWS_LOCK_WAIT_S)
                return False
            time.sleep(0.005)


def _unlock_file(f: Any) -> None:
    if fcntl is not None:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    elif msvcrt is not None:  # pragma: no cover - Windows only
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError as exc:
            log.warning("GPTZero ledger unlock failed (%s); the lock is released when the handle closes", exc)


BUCKETS = ("interactive", "investigation")
LEDGER_FILENAME = "gptzero_ledger.json"
# A reservation whose process died before commit/release is dropped after this long.
STALE_RESERVATION_S = 15 * 60

__all__ = ["BUCKETS", "BudgetExceeded", "Reservation", "WordLedger", "count_words", "get_ledger"]


class BudgetExceeded(RuntimeError):
    """The bucket's word cap would be exceeded. Nothing was reserved and nothing should be sent."""

    def __init__(self, bucket: str, requested: int, remaining: int, cap: int) -> None:
        self.bucket, self.requested, self.remaining, self.cap = bucket, requested, remaining, cap
        super().__init__(
            f"GPTZero '{bucket}' word budget exceeded: need {requested}, {remaining} of {cap} left. "
            "Raise the cap in .env, use GPTZERO_MODE=replay, or scan a smaller sample."
        )


@dataclass(frozen=True)
class Reservation:
    rid: str
    bucket: str
    words: int


class WordLedger:
    def __init__(self, path: Path | str | None = None, caps: dict[str, int] | None = None,
                 *, stale_after_s: float = STALE_RESERVATION_S) -> None:
        self.path = Path(path) if path is not None else RUNS_DIR / LEDGER_FILENAME
        if caps is None:
            s = get_settings()
            caps = {"interactive": s.gptzero_interactive_word_cap, "investigation": s.gptzero_investigation_word_cap}
        unknown = set(caps) - set(BUCKETS)
        if unknown:
            raise ValueError(f"unknown bucket(s) {sorted(unknown)}; expected {BUCKETS}")
        self.caps = {b: int(caps.get(b, 0)) for b in BUCKETS}
        self.stale_after_s = stale_after_s
        self._tlock = threading.RLock()

    # ------------------------------------------------------------------ public API
    def reserve(self, bucket: str, n_words: int) -> Reservation:
        """Hold n_words against the bucket, or raise BudgetExceeded. Always pair with commit() or release()."""
        self._check(bucket)
        n_words = int(n_words)
        if n_words < 0:
            raise ValueError("n_words must be >= 0")
        with self._locked() as state:
            remaining = self._remaining(state, bucket)
            if n_words > remaining:
                raise BudgetExceeded(bucket, n_words, remaining, self.caps[bucket])
            res = Reservation(rid=uuid.uuid4().hex, bucket=bucket, words=n_words)
            state["pending"][res.rid] = {"bucket": bucket, "words": n_words, "ts": time.time()}
            return res

    def commit(self, reservation: Reservation, actual_words: int | None = None) -> None:
        """The call succeeded: turn the hold into spend. `actual_words` overrides the estimate if the API told us."""
        with self._locked() as state:
            state["pending"].pop(reservation.rid, None)
            b = state["buckets"][reservation.bucket]
            b["committed"] += int(reservation.words if actual_words is None else actual_words)
            b["calls"] += 1

    def release(self, reservation: Reservation) -> None:
        """The call failed before GPTZero billed it: give the words back."""
        with self._locked() as state:
            state["pending"].pop(reservation.rid, None)

    def remaining(self, bucket: str) -> int:
        self._check(bucket)
        with self._locked(write=False) as state:
            return self._remaining(state, bucket)

    def used(self, bucket: str) -> int:
        self._check(bucket)
        with self._locked(write=False) as state:
            return int(state["buckets"][bucket]["committed"])

    def snapshot(self) -> dict[str, Any]:
        """For /api/admin and the scan progress line."""
        with self._locked(write=False) as state:
            out: dict[str, Any] = {}
            for b in BUCKETS:
                held = sum(p["words"] for p in state["pending"].values() if p["bucket"] == b)
                out[b] = {"cap": self.caps[b], "committed": state["buckets"][b]["committed"], "reserved": held,
                          "remaining": self._remaining(state, b), "calls": state["buckets"][b]["calls"]}
            return out

    def reset(self, bucket: str | None = None) -> None:
        """Start a new billing cycle (or fix the ledger after reading /v3/usage-stats). Not used by the app itself."""
        with self._locked() as state:
            for b in BUCKETS if bucket is None else (self._check(bucket),):
                state["buckets"][b] = {"committed": 0, "calls": 0}
                state["pending"] = {k: v for k, v in state["pending"].items() if v["bucket"] != b}

    # ------------------------------------------------------------------ internals
    def _check(self, bucket: str) -> str:
        if bucket not in BUCKETS:
            raise ValueError(f"unknown GPTZero budget bucket {bucket!r}; expected one of {BUCKETS}")
        return bucket

    def _remaining(self, state: dict[str, Any], bucket: str) -> int:
        held = sum(p["words"] for p in state["pending"].values() if p["bucket"] == bucket)
        return max(0, self.caps[bucket] - int(state["buckets"][bucket]["committed"]) - held)

    @contextmanager
    def _locked(self, *, write: bool = True) -> Iterator[dict[str, Any]]:
        with self._tlock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.path.with_name(self.path.name + ".lock")
            with open(lock_path, "a+") as lock_file:
                locked = _lock_file(lock_file)
                try:
                    state = self._load()
                    before = json.dumps(state, sort_keys=True)
                    yield state
                    if write or json.dumps(state, sort_keys=True) != before:
                        self._save(state)
                finally:
                    if locked:
                        _unlock_file(lock_file)

    def _load(self) -> dict[str, Any]:
        state: dict[str, Any] = {}
        if self.path.exists():
            try:
                state = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            except (json.JSONDecodeError, OSError) as exc:
                backup = self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}")
                log.warning("GPTZero ledger unreadable (%s); moved to %s and starting from zero. "
                            "Check /v3/usage-stats before a big scan.", exc, backup.name)
                try:
                    os.replace(self.path, backup)
                except OSError:
                    pass
                state = {}
        if not isinstance(state, dict):
            state = {}
        buckets = state.get("buckets") if isinstance(state.get("buckets"), dict) else {}
        state["buckets"] = {
            b: {"committed": int((buckets.get(b) or {}).get("committed", 0)), "calls": int((buckets.get(b) or {}).get("calls", 0))}
            for b in BUCKETS
        }
        pending = state.get("pending") if isinstance(state.get("pending"), dict) else {}
        cutoff = time.time() - self.stale_after_s
        state["pending"] = {k: v for k, v in pending.items()
                            if isinstance(v, dict) and v.get("bucket") in BUCKETS and float(v.get("ts", 0)) >= cutoff}
        state["version"] = 1
        return state

    def _save(self, state: dict[str, Any]) -> None:
        state["caps"] = dict(self.caps)  # informational; the authoritative caps come from settings
        state["updated_at"] = time.time()
        tmp = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(10):
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:  # Windows: a scanner (e.g. Defender) briefly holds the file we just rewrote
                if attempt == 9:
                    raise
                time.sleep(0.025)


@lru_cache
def get_ledger() -> WordLedger:
    """The shared ledger at RUNS_DIR/gptzero_ledger.json with caps from settings."""
    return WordLedger()
