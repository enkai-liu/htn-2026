"""Promote a finished live run to a golden replay (demo insurance).

    backend/.venv/bin/python scripts/record_golden.py <run_id> <name>

Copies backend/runs/<run_id>.jsonl to backend/fixtures/golden/<name>.jsonl and frontend/public/replay/<name>.jsonl after
validating every event against the contract. Replay it at /runs/<name>?replay=<name>&speed=1.5 with no backend and no wifi.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas import AgentEvent  # noqa: E402


def main() -> int:
    if len(sys.argv) != 3 or not sys.argv[2].replace("-", "").replace("_", "").isalnum():
        print(__doc__)
        return 2
    run_id, name = sys.argv[1], sys.argv[2]
    src = ROOT / "backend" / "runs" / f"{run_id}.jsonl"
    if not src.exists():
        print(f"no such run: {src}")
        return 1
    events = [AgentEvent(**json.loads(line)) for line in src.read_text().splitlines() if line.strip()]
    if not events or events[-1].type != "run.finished":
        last = events[-1].type if events else "nothing"
        print(f"run {run_id} did not finish cleanly (last event: {last}); not promoting it")
        return 1
    body = "\n".join(json.dumps(e.model_dump(mode="json", exclude_none=True) | {"run_id": name}) for e in events) + "\n"
    for dest in (ROOT / "backend" / "fixtures" / "golden" / f"{name}.jsonl", ROOT / "frontend" / "public" / "replay" / f"{name}.jsonl"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body)
        print(f"wrote {dest.relative_to(ROOT)} ({len(events)} events, {events[-1].ts - events[0].ts:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
