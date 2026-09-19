"""Slop Index step 2: scan the sample with GPTZero `/v2/predict/text`, charged to the `investigation` word bucket.

    GPTZERO_MODE=live backend/.venv/bin/python -m investigation.scan --pilot          # 4 years x 50 (~60k words)
    GPTZERO_MODE=live caffeinate -i backend/.venv/bin/python -m investigation.scan    # everything in sample.parquet
    backend/.venv/bin/python -m investigation.scan --allow-replay --limit 20          # offline dry run (SYNTHETIC results)

* Resumable: every finished scan is appended to results/raw/scans.jsonl at once; sample_ids already there are skipped.
  The GPTZero client also caches by sha256(text), so a repeated text is never billed twice.
* Bounded concurrency (default 8). GPTZero allows 30,000 requests/hour; the constraint is WORDS, not requests.
* Stops cleanly when the ledger's investigation cap is reached (raise GPTZERO_INVESTIGATION_WORD_CAP to continue).
* Replay mode produces synthetic fixture verdicts. They are refused unless --allow-replay, are stored with
  model_version "replay-fixture", and make analyze.py stamp its output `sample_data: true`.

Output: investigation/results/scans.parquet
        (sample_id, year, predicted_class, confidence_category, subclass, ai_sentence_share, n_words, is_winner, model_version)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from . import common
from .common import InvestigationError

from app.config import get_settings  # noqa: E402
from app.signals.gptzero import GPTZeroClient, GPTZeroError, GPTZeroQuotaError, TextTooShort, to_scan  # noqa: E402
from app.signals.gptzero_budget import BudgetExceeded  # noqa: E402

COLUMNS = ["sample_id", "year", "predicted_class", "confidence_category", "subclass", "ai_sentence_share", "n_words",
           "is_winner", "model_version"]
PILOT_YEARS = (2019, 2023, 2024, 2026)  # one placebo year, the first ChatGPT year, and the two most recent
PILOT_PER_YEAR = 50


def load_done(log_path: Path, *, include_replay: bool) -> dict[str, dict[str, Any]]:
    done: dict[str, dict[str, Any]] = {}
    if not log_path.exists():
        return done
    for line in log_path.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a torn last line from a killed run
        if not isinstance(row, dict) or "sample_id" not in row:
            continue
        synthetic = row.get("model_version") == common.REPLAY_MODEL_VERSION
        if synthetic and not include_replay:
            continue  # a live run never trusts a synthetic row: it gets re-scanned for real
        prior = done.get(row["sample_id"])
        if prior is not None and synthetic and prior.get("model_version") != common.REPLAY_MODEL_VERSION:
            continue  # keep a real scan over a later synthetic one
        done[row["sample_id"]] = row
    return done


def write_parquet(rows: list[dict[str, Any]], path: Path) -> None:
    pd = common.require_pandas()
    frame = pd.DataFrame([{c: r.get(c) for c in COLUMNS} for r in rows], columns=COLUMNS)
    if len(frame):
        frame = frame.sort_values(["year", "sample_id"]).reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def pick_pilot_years(available: list[int], wanted: tuple[int, ...]) -> list[int]:
    chosen = [y for y in wanted if y in available]
    if len(chosen) < min(4, len(available)):  # fall back to an even spread over what the sample has
        rest = [y for y in available if y not in chosen]
        while rest and len(chosen) < 4:
            chosen.append(rest.pop(len(rest) // 2))
    return sorted(chosen)


async def run(args: argparse.Namespace) -> int:
    pd = common.require_pandas()
    sample_path = Path(args.sample)
    if not sample_path.exists():
        raise InvestigationError(f"{sample_path} not found. Run: backend/.venv/bin/python -m investigation.sample")
    sample = pd.read_parquet(sample_path)
    need = {"sample_id", "year", "text", "n_words", "is_winner"}
    if not need <= set(sample.columns):
        raise InvestigationError(f"{sample_path} is missing columns {sorted(need - set(sample.columns))}")
    if "rank" not in sample.columns:
        sample["rank"] = sample.groupby("year").cumcount()

    settings = get_settings()
    live = settings.gptzero_mode == "live"
    if not live and not args.allow_replay:
        raise InvestigationError(
            "GPTZERO_MODE is 'replay': a scan would produce SYNTHETIC fixture verdicts, not findings.\n"
            "  real scan : set GPTZERO_MODE=live and GPTZERO_API_KEY in .env (spends words from the investigation bucket)\n"
            "  dry run   : add --allow-replay (rows are marked model_version=replay-fixture; analysis is stamped sample_data)")
    if live and not settings.gptzero_api_key:
        raise InvestigationError("GPTZERO_MODE=live but GPTZERO_API_KEY is empty")

    if args.pilot:
        years = pick_pilot_years(sorted(int(y) for y in sample["year"].unique()), PILOT_YEARS)
        sample = sample[sample["year"].isin(years) & (sample["rank"] < PILOT_PER_YEAR)]
        print(f"pilot: years {years}, up to {PILOT_PER_YEAR} each")
    if args.years:
        sample = sample[sample["year"].isin(args.years)]
    if args.per_year:
        sample = sample[sample["rank"] < args.per_year]
    sample = sample.sort_values(["rank", "year"])  # interleave years so a run cut short is still balanced

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(log_path, include_replay=not live)
    todo = sample[~sample["sample_id"].isin(done.keys())]
    if args.limit:
        todo = todo.head(args.limit)

    client = GPTZeroClient(settings=settings)
    ledger = client.ledger
    est_words = int(todo["n_words"].sum())
    print(f"mode={'LIVE' if live else 'replay (synthetic)'}  sample={len(sample)}  already scanned={len(sample) - len(todo) if not args.limit else '-'}  "
          f"to scan={len(todo)}  est. words={est_words:,}  investigation budget left={ledger.remaining('investigation'):,}")
    if live:
        try:
            usage = await client.usage_stats()
            print(f"GPTZero usage-stats: words_left={usage.get('words_left')} words_used={usage.get('words_used')} plan={usage.get('plan')}")
        except Exception as exc:  # noqa: BLE001  informational only
            print(f"(could not read /v3/usage-stats: {exc})")
    if args.dry_run or todo.empty:
        if todo.empty:
            print("nothing to scan.")
            if done:  # rebuild the parquet from the log (e.g. after it was deleted)
                write_parquet(list(done.values()), Path(args.out))
        await client.aclose()
        return 0

    sem = asyncio.Semaphore(max(1, args.concurrency))
    stop = asyncio.Event()
    counts = {"ok": 0, "failed": 0, "skipped": 0}
    started = time.monotonic()
    log_file = log_path.open("a")

    async def one(rec: dict[str, Any]) -> None:
        if stop.is_set():
            counts["skipped"] += 1
            return
        async with sem:
            if stop.is_set():
                counts["skipped"] += 1
                return
            try:
                doc = await client.predict_text(rec["text"], bucket="investigation")
            except BudgetExceeded as exc:
                if not stop.is_set():
                    print(f"\nSTOP: {exc}")
                stop.set()
                counts["skipped"] += 1
                return
            except GPTZeroQuotaError as exc:
                if not stop.is_set():
                    print(f"\nSTOP: GPTZero plan quota reached: {exc}")
                stop.set()
                counts["skipped"] += 1
                return
            except (GPTZeroError, TextTooShort) as exc:
                counts["failed"] += 1
                print(f"  failed {rec['sample_id']}: {exc}")
                return
            scan = to_scan(doc)
            row = {"sample_id": rec["sample_id"], "year": int(rec["year"]), "predicted_class": scan.predicted_class,
                   "confidence_category": scan.confidence_category, "subclass": scan.subclass,
                   "ai_sentence_share": scan.ai_sentence_share, "n_words": int(rec["n_words"]),
                   "is_winner": bool(rec["is_winner"]), "model_version": scan.model_version,
                   "scanned_at": scan.scanned_at.isoformat() if scan.scanned_at else None, "from_cache": doc.cached}
            done[row["sample_id"]] = row
            log_file.write(json.dumps(row) + "\n")
            log_file.flush()
            counts["ok"] += 1
            if counts["ok"] % 25 == 0:
                rate = counts["ok"] / max(1e-6, time.monotonic() - started)
                print(f"  {counts['ok']}/{len(todo)} scanned  ({rate:.1f}/s)  investigation budget left={ledger.remaining('investigation'):,}")
                write_parquet(list(done.values()), Path(args.out))

    try:
        await asyncio.gather(*(one(r) for r in todo.to_dict("records")))
    finally:
        log_file.close()
        write_parquet(list(done.values()), Path(args.out))
        await client.aclose()

    print(f"\nscanned {counts['ok']}  failed {counts['failed']}  not attempted {counts['skipped']}  "
          f"-> {args.out} ({len(done)} rows total)")
    print(f"ledger: {json.dumps(ledger.snapshot()['investigation'])}")
    if not live:
        print("NOTE: these rows are SYNTHETIC (replay fixtures). Do not report them.")
    return 0 if counts["failed"] == 0 else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pilot", action="store_true", help=f"{len(PILOT_YEARS)} years x {PILOT_PER_YEAR} (a subset of the full sample)")
    ap.add_argument("--years", type=int, nargs="*", help="only these years")
    ap.add_argument("--per-year", type=int, help="only the first N of each year (hash order)")
    ap.add_argument("--limit", type=int, help="scan at most N write-ups this run")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--allow-replay", action="store_true", help="permit a synthetic dry run when GPTZERO_MODE=replay")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and the word estimate; scan nothing")
    ap.add_argument("--sample", default=str(common.SAMPLE_PATH))
    ap.add_argument("--out", default=str(common.SCANS_PATH))
    ap.add_argument("--log", default=str(common.SCANS_LOG_PATH))
    return asyncio.run(run(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
