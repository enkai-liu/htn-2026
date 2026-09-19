"""Slop Index step 1: draw the year-stratified, length-controlled sample of Devpost write-ups.

    backend/.venv/bin/python -m investigation.sample                 # 150 per year, seed 20260919
    backend/.venv/bin/python -m investigation.sample --per-year 200
    backend/.venv/bin/python -m investigation.sample --download      # fetch the two datasets first (~380 MB)

Inputs (looked up under data/, or pass explicit paths):
  alvanlii/devpost-hackathon-projects  combined_hackathons.parquet + hackathons.json  -> 2018 2019 2021 2022 2023 2024
  twangodev/devpost-hacks (config all) all/train/0000.parquet                           -> 2025 2026
The historic parquet has no date column: the year is the END of the hackathon's `submission_period_dates`.

Rules: English write-ups of at least 600 characters, every one truncated to 1,800 characters at a sentence boundary
(so the detector sees comparable lengths in every year), N per year by hash rank with a fixed seed.

Outputs:
  investigation/results/sample.parquet              sample_id, year, source_dataset, text, n_chars, n_words, is_winner, rank
  data/investigation_private/sample_map.parquet     sample_id -> project URL / title / hackathon   (PRIVATE, git-ignored)
  investigation/results/sample_summary.json         eligible counts and length medians per year (for the method section)
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import common
from .common import (
    DATA_DIR,
    MAX_CHARS,
    MIN_CHARS,
    SEED,
    YEARS_HISTORIC,
    YEARS_RECENT,
    InvestigationError,
    clean_writeup,
    is_winner_from_prize,
    looks_english,
    parse_period_year,
    recent_hackathon_year,
    sample_id_for,
    sample_rank,
)

from app.signals.textutil import count_words, truncate_at_sentence  # noqa: E402  (common fixed sys.path)

HISTORIC_REPO = "alvanlii/devpost-hackathon-projects"
RECENT_REPO = "twangodev/devpost-hacks"
DOWNLOAD_HINT = (
    "Download them (about 390 MB, mind the wifi) with the ingest lane's downloader:\n"
    "    backend/.venv/bin/python -m ingest.download_hf --yes\n"
    "  which writes data/alvanlii/combined_hackathons.parquet, data/alvanlii/hackathons.json and\n"
    "  data/twangodev/all/train/0000.parquet.  (`python -m investigation.sample --download` does the same.)\n"
    "  Files elsewhere? Pass --projects / --hackathons / --recent explicitly."
)
# Where ingest/download_hf.py puts things; checked first, then data/ is searched recursively.
KNOWN_PATHS = {"projects": "alvanlii/combined_hackathons.parquet", "hackathons": "alvanlii/hackathons.json",
               "recent": "twangodev/all/train/0000.parquet"}


# ---------------------------------------------------------------------------- locating inputs
def _first(paths: list[Path]) -> Path | None:
    return sorted(paths, key=lambda p: (-p.stat().st_size, str(p)))[0] if paths else None


def find_inputs(data_dir: Path, projects: str | None, hackathons: str | None, recent: list[str] | None) -> dict[str, Any]:
    found: dict[str, Any] = {
        "projects": Path(projects) if projects else None,
        "hackathons": Path(hackathons) if hackathons else None,
        "recent": [Path(p) for p in recent] if recent else [],
    }
    if data_dir.exists():
        def search(pattern: str, *needles: str) -> list[Path]:
            hits = [p for p in data_dir.rglob(pattern) if not needles or any(n in str(p).lower() for n in needles)]
            settled = [p for p in hits if "_hf" not in p.parts]  # data/_hf/ is the downloader's staging copy
            return settled or hits

        if found["projects"] is None:
            known = data_dir / KNOWN_PATHS["projects"]
            found["projects"] = known if known.exists() else (
                _first(search("combined_hackathons.parquet")) or _first(search("*.parquet", "alvanlii", "devpost-hackathon-projects")))
        if found["hackathons"] is None:
            known = data_dir / KNOWN_PATHS["hackathons"]
            found["hackathons"] = known if known.exists() else _first(search("hackathons.json"))
        if not found["recent"]:
            known = data_dir / KNOWN_PATHS["recent"]
            if known.exists():
                found["recent"] = [known]
            else:
                cands = search("*.parquet", "twangodev", "devpost-hacks")
                in_all = [p for p in cands if "all" in {part.lower() for part in p.parts}]
                found["recent"] = sorted(in_all or cands)
    for key in ("projects", "hackathons"):
        if found[key] is not None and not found[key].exists():
            raise InvestigationError(f"{key} file not found: {found[key]}")
    return found


def download(data_dir: Path) -> None:
    """One download layout for the whole repo: delegate to ingest/download_hf.py when it is there."""
    if data_dir.resolve() == DATA_DIR.resolve():
        try:
            if str(common.REPO_ROOT) not in sys.path:
                sys.path.insert(0, str(common.REPO_ROOT))
            from ingest import download_hf

            if download_hf.main(["--yes"]) != 0:
                raise InvestigationError("ingest.download_hf failed")
            return
        except ImportError:
            pass
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise InvestigationError("huggingface_hub is not installed (backend[ingest] extra)") from exc
    for repo, name, revision, key in ((HISTORIC_REPO, "hackathons.json", "main", "hackathons"),
                                      (HISTORIC_REPO, "combined_hackathons.parquet", "main", "projects"),
                                      (RECENT_REPO, "all/train/0000.parquet", "refs/convert/parquet", "recent")):
        target = data_dir / KNOWN_PATHS[key]
        if target.exists():
            continue
        print(f"downloading {repo}@{revision}:{name} -> {target}")
        got = hf_hub_download(repo, name, repo_type="dataset", revision=revision, local_dir=data_dir / "_hf" / key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(got, target)


# ---------------------------------------------------------------------------- candidates
def _pick(columns: list[str], *names: str) -> str | None:
    lowered = {c.lower(): c for c in columns}
    for n in names:
        if n in lowered:
            return lowered[n]
    return None


def load_hackathon_years(path: Path) -> dict[int, int]:
    items = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(items, dict):
        items = items.get("hackathons") or list(items.values())
    years: dict[int, int] = {}
    for h in items:
        if not isinstance(h, dict) or "id" not in h:
            continue
        year = parse_period_year(h.get("submission_period_dates"))
        if year is not None:
            years[int(h["id"])] = year
    if not years:
        raise InvestigationError(f"{path} has no entries with both `id` and a parseable `submission_period_dates`")
    return years


class Collector:
    """Eligibility filter + per-year bookkeeping. Keeps only what a sample row needs (truncated text)."""

    def __init__(self, years: set[int], min_chars: int, max_chars: int, seed: int) -> None:
        self.years, self.min_chars, self.max_chars, self.seed = years, min_chars, max_chars, seed
        self.rows: dict[str, dict[str, Any]] = {}  # url -> row (deduplicated; earliest year wins)
        self.text_seen: set[str] = set()
        self.stats: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.lengths: dict[int, list[int]] = defaultdict(list)

    def offer(self, *, year: int | None, url: Any, text: Any, is_winner: bool, dataset: str, title: Any = None, hackathon: Any = None) -> None:
        if year is None or year not in self.years:
            return
        st = self.stats[year]
        st["seen"] += 1
        if not isinstance(url, str) or not url.strip():
            st["no_url"] += 1
            return
        body = clean_writeup(text)
        if len(body) < self.min_chars:
            st["too_short"] += 1
            return
        if not looks_english(body):
            st["not_english"] += 1
            return
        key = url.strip().lower().rstrip("/")
        prior = self.rows.get(key)
        if prior is not None and prior["year"] <= year:
            st["duplicate_url"] += 1
            return
        cut = truncate_at_sentence(body, self.max_chars)
        if len(cut) < self.min_chars:  # no usable boundary left a stub
            st["too_short"] += 1
            return
        fingerprint = common.stable_hash(cut[:400].lower())
        if prior is None and fingerprint in self.text_seen:
            st["duplicate_text"] += 1
            return
        self.text_seen.add(fingerprint)
        st["eligible"] += 1
        self.lengths[year].append(len(body))
        self.rows[key] = {
            "sample_id": sample_id_for(key, self.seed), "year": int(year), "source_dataset": dataset, "text": cut,
            "n_chars": len(cut), "n_words": count_words(cut), "n_chars_original": len(body), "is_winner": bool(is_winner),
            "rank": sample_rank(key, self.seed), "_url": url.strip(), "_title": title if isinstance(title, str) else None,
            "_hackathon": None if hackathon is None else str(hackathon),
        }


def collect_historic(col: Collector, projects: Path, hackathon_years: dict[int, int]) -> None:
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(projects)
    names = pf.schema_arrow.names
    c_h, c_url, c_text = _pick(names, "hackathon_id"), _pick(names, "project_link", "url"), _pick(names, "full_desc", "description")
    c_prize, c_title = _pick(names, "prize", "prizes"), _pick(names, "title")
    if not (c_h and c_url and c_text):
        raise InvestigationError(f"{projects} lacks hackathon_id / project_link / full_desc; columns are {names}")
    wanted = [c for c in (c_h, c_url, c_text, c_prize, c_title) if c]
    for batch in pf.iter_batches(batch_size=20_000, columns=wanted):
        data = batch.to_pydict()
        n = len(data[c_h])
        for i in range(n):
            hid = data[c_h][i]
            year = hackathon_years.get(int(hid)) if hid is not None else None
            col.offer(year=year, url=data[c_url][i], text=data[c_text][i], dataset=HISTORIC_REPO, hackathon=hid,
                      is_winner=is_winner_from_prize(data[c_prize][i]) if c_prize else False,
                      title=data[c_title][i] if c_title else None)


def collect_recent(col: Collector, paths: list[Path]) -> None:
    import pyarrow.parquet as pq

    for path in paths:
        pf = pq.ParquetFile(path)
        names = pf.schema_arrow.names
        c_url, c_text, c_hack = _pick(names, "url", "project_link"), _pick(names, "description", "full_desc"), _pick(names, "hackathon")
        c_win, c_title, c_results = _pick(names, "is_winner"), _pick(names, "title"), _pick(names, "results")
        if not (c_url and c_text and c_hack):
            raise InvestigationError(f"{path} lacks url / description / hackathon; columns are {names}")
        wanted = [c for c in (c_url, c_text, c_hack, c_win, c_title, c_results) if c]
        unknown: set[str] = set()
        for batch in pf.iter_batches(batch_size=5_000, columns=wanted):
            data = batch.to_pydict()
            for i in range(len(data[c_url])):
                slug = data[c_hack][i]
                year = recent_hackathon_year(slug)
                if year is None and slug:
                    unknown.add(str(slug))
                winner = bool(data[c_win][i]) if c_win else False
                col.offer(year=year, url=data[c_url][i], text=data[c_text][i], is_winner=winner, dataset=RECENT_REPO,
                          title=data[c_title][i] if c_title else None, hackathon=slug)
        if unknown:
            print(f"  note: no year known for hackathon slug(s) {sorted(unknown)}; add them to common.RECENT_HACKATHON_YEARS")


# ---------------------------------------------------------------------------- main
def draw(col: Collector, per_year: int) -> list[dict[str, Any]]:
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in col.rows.values():
        by_year[row["year"]].append(row)
    picked: list[dict[str, Any]] = []
    for year in sorted(by_year):
        rows = sorted(by_year[year], key=lambda r: r["rank"])[:per_year]
        for i, r in enumerate(rows):
            r["rank"] = i  # 0-based position in the hash order: the pilot takes rank < 50
        picked.extend(rows)
    return picked


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-year", type=int, default=150)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--years-historic", type=int, nargs="*", default=list(YEARS_HISTORIC))
    ap.add_argument("--years-recent", type=int, nargs="*", default=list(YEARS_RECENT))
    ap.add_argument("--min-chars", type=int, default=MIN_CHARS)
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS)
    ap.add_argument("--projects", help="alvanlii parquet (default: found under data/)")
    ap.add_argument("--hackathons", help="alvanlii hackathons.json (default: found under data/)")
    ap.add_argument("--recent", nargs="*", help="twangodev parquet file(s) (default: found under data/)")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--download", action="store_true", help="download both datasets into data/ first")
    ap.add_argument("--out", default=str(common.SAMPLE_PATH))
    args = ap.parse_args(argv)

    pd = common.require_pandas()
    data_dir = Path(args.data_dir)
    if args.download:
        download(data_dir)
    inputs = find_inputs(data_dir, args.projects, args.hackathons, args.recent)
    missing = [k for k in ("projects", "hackathons") if inputs[k] is None and args.years_historic]
    if args.years_recent and not inputs["recent"]:
        missing.append("recent")
    if missing:
        raise InvestigationError(f"input data not found under {data_dir} (missing: {', '.join(missing)}).\n{DOWNLOAD_HINT}")

    historic = Collector(set(args.years_historic), args.min_chars, args.max_chars, args.seed)
    if args.years_historic:
        print(f"reading {inputs['hackathons']}")
        years = load_hackathon_years(inputs["hackathons"])
        print(f"  {len(years):,} hackathons with a parseable year")
        print(f"reading {inputs['projects']} (streamed)")
        collect_historic(historic, inputs["projects"], years)
    recent = Collector(set(args.years_recent), args.min_chars, args.max_chars, args.seed)
    if args.years_recent:
        print(f"reading {', '.join(str(p) for p in inputs['recent'])}")
        collect_recent(recent, inputs["recent"])

    rows = draw(historic, args.per_year) + draw(recent, args.per_year)
    if not rows:
        raise InvestigationError("no eligible write-ups found: check the input files and the year lists")
    rows.sort(key=lambda r: (r["year"], r["rank"]))

    summary: dict[str, Any] = {"seed": args.seed, "per_year": args.per_year, "min_chars": args.min_chars,
                               "max_chars": args.max_chars, "years": []}
    print(f"\n{'year':>6} {'seen':>8} {'eligible':>9} {'sampled':>8} {'median chars (before cut)':>26}")
    for col in (historic, recent):
        for year in sorted(col.years):
            st = col.stats.get(year, {})
            sampled = sum(1 for r in rows if r["year"] == year)
            med = int(statistics.median(col.lengths[year])) if col.lengths.get(year) else 0
            flag = "" if sampled >= args.per_year else "   <- fewer than requested"
            print(f"{year:>6} {st.get('seen', 0):>8,} {st.get('eligible', 0):>9,} {sampled:>8} {med:>26,}{flag}")
            summary["years"].append({"year": year, **{k: int(v) for k, v in st.items()}, "sampled": sampled,
                                     "median_chars_before_truncation": med})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    public_cols = ["sample_id", "year", "source_dataset", "text", "n_chars", "n_words", "n_chars_original", "is_winner", "rank"]
    pd.DataFrame([{k: r[k] for k in public_cols} for r in rows]).to_parquet(out, index=False)
    map_path = data_dir / common.PRIVATE_DIR.name / common.SAMPLE_MAP_PATH.name  # data/ is git-ignored
    map_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"sample_id": r["sample_id"], "project_url": r["_url"], "title": r["_title"], "hackathon": r["_hackathon"],
                   "year": r["year"]} for r in rows]).to_parquet(map_path, index=False)
    (out.parent / "sample_summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    words = sum(r["n_words"] for r in rows)
    print(f"\nwrote {len(rows):,} rows -> {out}")
    print(f"private URL map     -> {map_path}  (git-ignored; never publish)")
    print(f"estimated GPTZero words for a full scan: {words:,}  (pilot 4 x 50: ~{int(words / max(1, len(rows)) * 200):,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
