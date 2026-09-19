"""Download the Hugging Face dataset files into data/ (git-ignored). Prints names + sizes first and only
downloads with --yes.  DO NOT run casually on conference wifi: the alvanlii parquet is ~372 MB.

    backend/.venv/bin/python -m ingest.download_hf                 # list what would be downloaded
    backend/.venv/bin/python -m ingest.download_hf --yes           # everything (~390 MB)
    backend/.venv/bin/python -m ingest.download_hf --only twangodev hackathons --yes    # Tier 0 needs only these (~15 MB)

File names verified via https://datasets-server.huggingface.co/parquet and the HF tree API (2026-09-19):
  alvanlii/devpost-hackathon-projects  main: combined_hackathons.parquet (372,053,511 B), hackathons.json (9,122,175 B)
  twangodev/devpost-hacks              refs/convert/parquet: all/train/0000.parquet (6,064,862 B)
"""
from __future__ import annotations

import argparse
import sys

from ingest.common import DATA_DIR

FILES = {
    "alvanlii": dict(repo_id="alvanlii/devpost-hackathon-projects", filename="combined_hackathons.parquet", revision="main",
                     approx_bytes=372_053_511, local="alvanlii/combined_hackathons.parquet"),
    "hackathons": dict(repo_id="alvanlii/devpost-hackathon-projects", filename="hackathons.json", revision="main",
                       approx_bytes=9_122_175, local="alvanlii/hackathons.json"),
    "twangodev": dict(repo_id="twangodev/devpost-hacks", filename="all/train/0000.parquet", revision="refs/convert/parquet",
                      approx_bytes=6_064_862, local="twangodev/all/train/0000.parquet"),
}


def local_path(key: str):
    return DATA_DIR / FILES[key]["local"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", choices=sorted(FILES), default=sorted(FILES))
    ap.add_argument("--yes", action="store_true", help="actually download (otherwise just list)")
    args = ap.parse_args(argv)

    total = 0
    print(f"Target directory: {DATA_DIR}")
    for key in args.only:
        f = FILES[key]
        path = local_path(key)
        have = f"already present ({path.stat().st_size:,} B)" if path.exists() else "missing"
        total += 0 if path.exists() else f["approx_bytes"]
        print(f"  {key:<11} {f['repo_id']}@{f['revision']}:{f['filename']}  ~{f['approx_bytes'] / 1e6:,.1f} MB  -> {path}  [{have}]")
    print(f"To download: ~{total / 1e6:,.1f} MB")
    if not args.yes:
        print("Nothing downloaded. Re-run with --yes to proceed.")
        return 0

    from huggingface_hub import hf_hub_download

    for key in args.only:
        f = FILES[key]
        path = local_path(key)
        if path.exists():
            continue
        print(f"downloading {key} …", flush=True)
        got = hf_hub_download(repo_id=f["repo_id"], filename=f["filename"], repo_type="dataset", revision=f["revision"],
                              local_dir=DATA_DIR / "_hf" / key)
        path.parent.mkdir(parents=True, exist_ok=True)
        from pathlib import Path
        import shutil

        shutil.copyfile(Path(got), path)
        print(f"  -> {path} ({path.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
