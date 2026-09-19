"""The GPTZero word ledger: caps, persistence, and safety under threads, asyncio tasks and a second process-like handle."""
from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest

from app.config import RUNS_DIR, get_settings
from app.signals.gptzero_budget import BUCKETS, BudgetExceeded, Reservation, WordLedger, count_words, get_ledger

CAPS = {"interactive": 1_000, "investigation": 5_000}


def ledger_at(tmp_path, **kw) -> WordLedger:
    return WordLedger(tmp_path / "runs" / "gptzero_ledger.json", caps=dict(CAPS), **kw)


def test_count_words():
    assert count_words("") == 0
    assert count_words("  one two\n\nthree\tfour  ") == 4


def test_reserve_commit_remaining(tmp_path):
    led = ledger_at(tmp_path)
    assert led.remaining("interactive") == 1_000 and led.remaining("investigation") == 5_000
    r = led.reserve("interactive", 300)
    assert isinstance(r, Reservation) and r.bucket == "interactive" and r.words == 300
    assert led.remaining("interactive") == 700, "a reservation holds words before they are spent"
    assert led.used("interactive") == 0
    led.commit(r)
    assert led.used("interactive") == 300 and led.remaining("interactive") == 700
    assert led.remaining("investigation") == 5_000, "buckets are independent"
    snap = led.snapshot()
    assert snap["interactive"] == {"cap": 1_000, "committed": 300, "reserved": 0, "remaining": 700, "calls": 1}


def test_budget_exceeded_reserves_nothing(tmp_path):
    led = ledger_at(tmp_path)
    led.commit(led.reserve("interactive", 900))
    with pytest.raises(BudgetExceeded) as err:
        led.reserve("interactive", 101)
    assert err.value.bucket == "interactive" and err.value.requested == 101 and err.value.remaining == 100
    assert "interactive" in str(err.value) and "100" in str(err.value)
    assert led.remaining("interactive") == 100
    led.commit(led.reserve("interactive", 100))  # exactly the remainder is fine
    assert led.remaining("interactive") == 0
    with pytest.raises(BudgetExceeded):
        led.reserve("interactive", 1)
    led.reserve("interactive", 0)  # empty text costs nothing


def test_release_gives_the_words_back(tmp_path):
    led = ledger_at(tmp_path)
    r = led.reserve("investigation", 4_000)
    with pytest.raises(BudgetExceeded):
        led.reserve("investigation", 2_000)
    led.release(r)
    assert led.remaining("investigation") == 5_000 and led.used("investigation") == 0
    led.release(r)  # idempotent
    led.commit(led.reserve("investigation", 2_000), actual_words=1_500)  # the API's own count wins when we have it
    assert led.used("investigation") == 1_500


def test_persists_across_instances_and_is_valid_json(tmp_path):
    a = ledger_at(tmp_path)
    a.commit(a.reserve("interactive", 250))
    held = a.reserve("interactive", 50)
    b = ledger_at(tmp_path)  # e.g. the investigation script next to the running backend
    assert b.used("interactive") == 250 and b.remaining("interactive") == 700
    b.commit(held)
    assert a.used("interactive") == 300
    data = json.loads(a.path.read_text())
    assert data["buckets"]["interactive"] == {"committed": 300, "calls": 2} and data["pending"] == {}
    assert not list(a.path.parent.glob("*.tmp-*")), "atomic write must not leave temp files behind"


def test_unknown_bucket_and_bad_input(tmp_path):
    led = ledger_at(tmp_path)
    with pytest.raises(ValueError, match="unknown"):
        led.reserve("marketing", 10)
    with pytest.raises(ValueError):
        led.remaining("marketing")
    with pytest.raises(ValueError):
        led.reserve("interactive", -1)
    with pytest.raises(ValueError):
        WordLedger(tmp_path / "x.json", caps={"nope": 1})


def test_stale_reservations_expire(tmp_path):
    led = ledger_at(tmp_path, stale_after_s=0.05)
    led.reserve("interactive", 1_000)  # a process that died before commit/release
    assert led.remaining("interactive") == 0
    time.sleep(0.08)
    assert led.remaining("interactive") == 1_000


def test_corrupt_file_is_set_aside_not_fatal(tmp_path):
    led = ledger_at(tmp_path)
    led.commit(led.reserve("interactive", 10))
    led.path.write_text("{not json")
    assert led.remaining("interactive") == 1_000
    assert list(led.path.parent.glob("gptzero_ledger.json.corrupt-*"))
    led.commit(led.reserve("interactive", 5))
    assert json.loads(led.path.read_text())["buckets"]["interactive"]["committed"] == 5


def test_reset(tmp_path):
    led = ledger_at(tmp_path)
    led.commit(led.reserve("interactive", 10))
    led.commit(led.reserve("investigation", 20))
    led.reset("interactive")
    assert led.used("interactive") == 0 and led.used("investigation") == 20
    led.reset()
    assert led.used("investigation") == 0


def test_threads_never_overspend(tmp_path):
    led = WordLedger(tmp_path / "ledger.json", caps={"interactive": 8 * 25 * 10, "investigation": 0})
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(25):
                led.commit(led.reserve("interactive", 10))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert led.used("interactive") == 2_000 and led.remaining("interactive") == 0
    with pytest.raises(BudgetExceeded):
        led.reserve("interactive", 1)


def test_two_handles_on_one_file_contend_safely(tmp_path):
    """Separate WordLedger objects share no in-process lock: only the file lock keeps them consistent."""
    path = tmp_path / "ledger.json"
    cap = 600
    refused = []

    def worker() -> None:
        led = WordLedger(path, caps={"interactive": cap, "investigation": 0})
        for _ in range(40):
            try:
                led.commit(led.reserve("interactive", 5))
            except BudgetExceeded:
                refused.append(1)

    threads = [threading.Thread(target=worker) for _ in range(4)]  # 4 * 40 * 5 = 800 words wanted, 600 allowed
    [t.start() for t in threads]
    [t.join() for t in threads]
    final = WordLedger(path, caps={"interactive": cap, "investigation": 0})
    assert final.used("interactive") == cap, "lost updates or overspend"
    assert len(refused) == (800 - cap) // 5


async def test_safe_from_asyncio_tasks(tmp_path):
    led = WordLedger(tmp_path / "ledger.json", caps={"interactive": 500, "investigation": 0})
    refused = 0

    async def task() -> None:
        nonlocal refused
        try:
            r = led.reserve("interactive", 10)
        except BudgetExceeded:
            refused += 1
            return
        await asyncio.sleep(0)  # the network call would happen here
        led.commit(r)

    await asyncio.gather(*(task() for _ in range(80)))
    assert led.used("interactive") == 500 and refused == 30
    await asyncio.gather(*(asyncio.to_thread(led.remaining, "interactive") for _ in range(10)))


def test_default_ledger_uses_settings_and_runs_dir():
    led = get_ledger()
    s = get_settings()
    assert led.path == RUNS_DIR / "gptzero_ledger.json"
    assert led.caps == {"interactive": s.gptzero_interactive_word_cap, "investigation": s.gptzero_investigation_word_cap}
    assert set(led.caps) == set(BUCKETS)
