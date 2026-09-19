"""Slop Index step 4: the public artifact. An anonymised CSV that lets anyone re-derive every number we report.

    backend/.venv/bin/python -m investigation.export_public

Columns: year, predicted_class, confidence_category, subclass, nn_sim, is_winner      -- and nothing else.
No URL, no title, no text, no hackathon, no sample_id (it is a hash of the URL and could be re-derived from the public
dataset). Rows are shuffled so their order carries no information, and nn_sim is rounded so it cannot act as a
fingerprint. No student project can be identified from this file; that is the point.
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path

from . import common
from .common import REPLAY_MODEL_VERSION, SEED, InvestigationError

PUBLIC_COLUMNS = ["year", "predicted_class", "confidence_category", "subclass", "nn_sim", "is_winner"]
FORBIDDEN = ("url", "link", "title", "text", "sample_id", "project", "hackathon", "team", "name")


def public_rows(frame, *, seed: int = SEED) -> list[dict]:
    rows = []
    for r in frame.to_dict("records"):
        nn = r.get("nn_sim")
        try:
            nn = None if nn is None or math.isnan(float(nn)) else round(float(nn), 3)
        except (TypeError, ValueError):
            nn = None
        sub = r.get("subclass")
        rows.append({"year": int(r["year"]), "predicted_class": str(r["predicted_class"]),
                     "confidence_category": str(r["confidence_category"]),
                     "subclass": sub if isinstance(sub, str) and sub else "",
                     "nn_sim": "" if nn is None else nn,
                     "is_winner": bool(r.get("is_winner")) if r.get("is_winner") is not None else False})
    random.Random(seed).shuffle(rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scans", default=str(common.SCANS_PATH))
    ap.add_argument("--neighbours", default=str(common.NEIGHBOURS_PATH))
    ap.add_argument("--out", default=str(common.PUBLIC_CSV_PATH))
    ap.add_argument("--allow-synthetic", action="store_true", help="export even if replay-fixture rows are present")
    args = ap.parse_args(argv)

    pd = common.require_pandas()
    scans = Path(args.scans)
    if not scans.exists():
        raise InvestigationError(f"{scans} not found. Run investigation.scan first.")
    frame = pd.read_parquet(scans)
    nb = Path(args.neighbours)
    if "nn_sim" not in frame.columns and nb.exists():
        frame = frame.merge(pd.read_parquet(nb)[["sample_id", "nn_sim"]].drop_duplicates("sample_id"), on="sample_id", how="left")
    if "model_version" in frame.columns and (frame["model_version"] == REPLAY_MODEL_VERSION).any() and not args.allow_synthetic:
        raise InvestigationError("scans contain synthetic replay-fixture rows; refusing to publish them "
                                 "(re-scan with GPTZERO_MODE=live, or pass --allow-synthetic for a dry run)")

    rows = public_rows(frame)
    assert all(set(r) == set(PUBLIC_COLUMNS) for r in rows)
    assert not any(bad in col for col in PUBLIC_COLUMNS for bad in FORBIDDEN)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PUBLIC_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} anonymised rows -> {out}")
    print("columns:", ", ".join(PUBLIC_COLUMNS), "(no URLs, titles, text or ids)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
