#!/usr/bin/env bash
# Runs the OFFICIAL Swarm Skill validator (openJiuwen-ai/jiuwenswarm, Apache-2.0) on swarm-skill/prior-art-swarm.
#
#   bash scripts/validate_swarm_skill.sh            # exit 0 = PASS, 1 = FAIL, 2 = usage/setup problem
#
# The validator is not vendored. It is fetched once into data/ (git-ignored), pinned to a commit and checked
# against a SHA-256, so a changed upstream file is refused instead of silently run. It is stdlib + PyYAML, only
# reads files, and analyses scripts/workflow.py with `ast` without executing it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_DIR="${1:-$ROOT/swarm-skill/prior-art-swarm}"
PIN="a1241d0c191974f658b6076dc1054fc9b86f0df6"   # develop, 2026-09-01
SHA256="95c14c436ce6641a2bddb4cc0ef150e86abf13b84f1f50329a92d6b11ca3efa4"
SRC="https://raw.githubusercontent.com/openJiuwen-ai/jiuwenswarm/$PIN/jiuwenswarm/resources/agent/workspace/skills/swarmskill-creator/scripts/validate_swarmskill.py"
CACHE="$ROOT/data/swarmskill-validator"
VALIDATOR="$CACHE/validate_swarmskill.py"
PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

if [ ! -f "$VALIDATOR" ]; then
  mkdir -p "$CACHE"
  echo "Fetching the official validator (pinned to ${PIN:0:12})…"
  curl -fsSL "$SRC" -o "$VALIDATOR.tmp" || { echo "Could not download the validator from GitHub." >&2; rm -f "$VALIDATOR.tmp"; exit 2; }
  mv "$VALIDATOR.tmp" "$VALIDATOR"
fi

GOT="$(shasum -a 256 "$VALIDATOR" | cut -d' ' -f1)"
if [ "$GOT" != "$SHA256" ]; then
  echo "Checksum mismatch for $VALIDATOR" >&2
  echo "  expected $SHA256" >&2
  echo "  got      $GOT" >&2
  echo "Refusing to run it. Delete the file to re-download, or review the new version and update PIN/SHA256." >&2
  exit 2
fi

"$PY" -c "import yaml" 2>/dev/null || { echo "PyYAML is missing: $PY -m pip install pyyaml" >&2; exit 2; }
exec "$PY" "$VALIDATOR" "$SKILL_DIR"
