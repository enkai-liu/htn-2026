#!/usr/bin/env bash
# Run every smoke test, then `elastic/apply.py --check` if it exists, and summarise. Run it before every demo.
#   bash scripts/smoke_all.sh            # GPTZero stays a dry run (it costs words)
#   bash scripts/smoke_all.sh --live     # also runs the GPTZero calls (~100 words)
# With no .env everything prints SKIP and the exit code is 0. Exit code 1 only if some check FAILed.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"

GPTZERO_ARGS=""
for arg in "$@"; do
  case "$arg" in
    --live) GPTZERO_ARGS="--live" ;;
    -h | --help) sed -n '2,5p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

LOG="$(mktemp "${TMPDIR:-/tmp}/whitespace-smoke-all.XXXXXX")"
trap 'rm -f "$LOG"' EXIT
FAILED=""

run() { # run NAME command...
  local name="$1" status
  shift
  "$@" 2>&1 | tee -a "$LOG"
  status="${PIPESTATUS[0]}"
  if [ "$status" -ne 0 ]; then FAILED="$FAILED $name"; fi
}

run elastic bash "$HERE/smoke_elastic.sh"
run baseten bash "$HERE/smoke_baseten.sh"
# shellcheck disable=SC2086
run gptzero bash "$HERE/smoke_gptzero.sh" $GPTZERO_ARGS

printf '\n== elastic/apply.py --check\n' | tee -a "$LOG"
APPLY="$REPO_ROOT/elastic/apply.py"
PY="$REPO_ROOT/backend/.venv/bin/python"
if [ ! -f "$APPLY" ]; then
  printf 'SKIP  elastic/apply.py does not exist yet\n' | tee -a "$LOG"
elif [ ! -x "$PY" ]; then
  printf 'SKIP  backend/.venv is missing: run make setup\n' | tee -a "$LOG"
else
  # apply.py needs Elastic credentials; without them this is a skip, not a failure
  has_es="$(cd "$REPO_ROOT/backend" && "$PY" -c 'from app.config import get_settings; print("yes" if get_settings().has_elastic else "no")' 2>/dev/null || echo no)"
  if [ "$has_es" != "yes" ]; then
    printf 'SKIP  (no key) ES_URL / ES_API_KEY are not set: apply.py --check not run\n' | tee -a "$LOG"
  else
    "$PY" "$APPLY" --check 2>&1 | tee -a "$LOG"
    if [ "${PIPESTATUS[0]}" -eq 0 ]; then
      printf 'PASS  elastic/apply.py --check\n' | tee -a "$LOG"
    else
      printf 'FAIL  elastic/apply.py --check exited non-zero\n' | tee -a "$LOG"
      FAILED="$FAILED apply-check"
    fi
  fi
fi

count() { grep -c "^$1 " "$LOG" || true; }
printf '\n==================== smoke summary ====================\n'
printf 'PASS %s   FAIL %s   SKIP %s   WARN %s\n' "$(count PASS)" "$(count FAIL)" "$(count SKIP)" "$(count WARN)"
if [ "$(count FAIL)" -gt 0 ]; then
  grep '^FAIL ' "$LOG" | sed 's/^/  /'
fi
if [ -z "$GPTZERO_ARGS" ]; then
  printf 'GPTZero calls were not made (they cost words): add --live to include them.\n'
fi
if [ -n "$FAILED" ] || [ "$(count FAIL)" -gt 0 ]; then
  printf 'RESULT: FAIL (%s )\n' "${FAILED:- see above}"
  exit 1
fi
printf 'RESULT: OK\n'
exit 0
