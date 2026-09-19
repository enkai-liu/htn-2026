# shellcheck shell=bash
# Shared helpers for scripts/smoke_*.sh. Source it, do not execute it.
# Written for the bash 3.2 that ships with macOS: no associative arrays, no mapfile, no ${var,,}.
#
#   load_env                      read REPO_ROOT/.env without echoing anything; variables already set in the shell win
#   pass/fail/skip/warn/info      one line each; only `fail` makes the script exit non-zero (via `finish`)
#   http METHOD URL [JSON_BODY]   curl wrapper -> $HTTP_STATUS, $HTTP_BODY (a temp file); auth headers come from
#                                 $HTTP_HEADERS (one per line) and are passed on stdin, never on the command line
#   json_get FILE JQ PY           extract text from a JSON file: jq when installed, else python (SMOKE_NO_JQ=1 forces python)

LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$LIB_DIR/.." && pwd)"
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
WARN_COUNT=0
HTTP_STATUS=""
HTTP_BODY=""
HTTP_HEADERS=""
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-30}"

SMOKE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/whitespace-smoke.XXXXXX")"
trap 'rm -rf "$SMOKE_TMP"' EXIT

if [ -x "$REPO_ROOT/backend/.venv/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/backend/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  PYTHON_BIN=""
fi

section() { printf '\n== %s\n' "$*"; }
pass() { PASS_COUNT=$((PASS_COUNT + 1)); printf 'PASS  %s\n' "$*"; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); printf 'FAIL  %s\n' "$*"; }
skip() { SKIP_COUNT=$((SKIP_COUNT + 1)); printf 'SKIP  %s\n' "$*"; }
warn() { WARN_COUNT=$((WARN_COUNT + 1)); printf 'WARN  %s\n' "$*"; }
info() { printf '      %s\n' "$*"; }
# info_lines [PREFIX] : print every non-empty stdin line as an info line. Always succeeds (safe under set -e / pipefail).
info_lines() {
  local line
  while IFS= read -r line || [ -n "$line" ]; do
    if [ -n "$line" ]; then info "${1:-}$line"; fi
  done
  return 0
}

have_jq() { [ -z "${SMOKE_NO_JQ:-}" ] && command -v jq >/dev/null 2>&1; }

require_tools() {
  if ! command -v curl >/dev/null 2>&1; then
    fail "curl is not installed"
    finish
  fi
  if ! have_jq && [ -z "$PYTHON_BIN" ]; then
    fail "need python3 (or jq) to read JSON responses: run 'make setup' or install python3"
    finish
  fi
}

# Parse KEY=VALUE lines ourselves instead of sourcing the file: nothing in .env is ever executed or printed.
load_env() {
  local file="${1:-$REPO_ROOT/.env}" line key val
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in
      '' | '#'* | [[:space:]]*'#'*) continue ;;
    esac
    case "$line" in
      'export '*) line="${line#export }" ;;
    esac
    case "$line" in
      *=*) ;;
      *) continue ;;
    esac
    key="${line%%=*}"
    val="${line#*=}"
    key="$(printf '%s' "$key" | tr -d '[:space:]')"
    case "$key" in
      '' | [0-9]* | *[!A-Za-z0-9_]*) continue ;;
    esac
    # trim surrounding whitespace
    val="${val#"${val%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    case "$val" in
      \"*\") val="${val#\"}"; val="${val%\"}" ;;
      \'*\') val="${val#\'}"; val="${val%\'}" ;;
      *) val="${val%%[[:space:]]#*}" ;;  # unquoted: drop a trailing " # comment"
    esac
    if [ -z "${!key+x}" ]; then
      export "$key=$val"
    fi
  done <"$file"
}

# True when a value is empty or still the .env.example placeholder.
unset_or_placeholder() {
  case "${1:-}" in
    '' | *YOUR-PROJECT* | *your-api-key* | *CHANGEME* | *changeme* | '<'*'>') return 0 ;;
  esac
  return 1
}

# http METHOD URL [JSON_BODY] [extra curl args...]
http() {
  local method="$1" url="$2" body="${3-}" cfg="" h
  if [ "$#" -ge 3 ]; then shift 3; else shift 2; fi
  HTTP_BODY="$(mktemp "$SMOKE_TMP/body.XXXXXX")"
  while IFS= read -r h; do
    [ -n "$h" ] || continue
    h="${h//\\/\\\\}"
    h="${h//\"/\\\"}"
    cfg="${cfg}header = \"${h}\"
"
  done <<EOF
$HTTP_HEADERS
EOF
  if [ -n "$body" ]; then
    printf '%s' "$body" >"$HTTP_BODY.req"
    set -- "$@" --data-binary "@$HTTP_BODY.req"
    cfg="${cfg}header = \"Content-Type: application/json\"
"
  fi
  HTTP_STATUS="$(printf '%s' "$cfg" | curl -sS -K - -o "$HTTP_BODY" -w '%{http_code}' --max-time "$SMOKE_TIMEOUT" \
    -X "$method" "$@" "$url" 2>"$HTTP_BODY.err")" || HTTP_STATUS="000"
  [ -n "$HTTP_STATUS" ] || HTTP_STATUS="000"
}

# Why a request failed, without ever printing request headers.
http_error() {
  if [ "$HTTP_STATUS" = "000" ]; then
    head -c 200 "$HTTP_BODY.err" 2>/dev/null | tr '\n' ' '
  else
    head -c 240 "$HTTP_BODY" 2>/dev/null | tr '\n' ' '
  fi
}

# json_get FILE JQ_FILTER PY_EXPR
#   JQ_FILTER  jq program run with -r (write `// empty` so null prints nothing)
#   PY_EXPR    python expression over `d` (the parsed document) and `g(obj, *path)` (safe getter);
#              may return a string, a number, a list of lines, or None
json_get() {
  local file="$1" jq_filter="$2" py_expr="$3"
  if have_jq; then
    jq -r "$jq_filter" "$file" 2>/dev/null || true
  else
    "$PYTHON_BIN" - "$file" "$py_expr" <<'PY' || true
import json, sys

try:
    with open(sys.argv[1]) as fh:
        d = json.load(fh)
except Exception:
    sys.exit(0)


def g(obj, *path, default=None):
    for p in path:
        try:
            obj = obj[p]
        except (KeyError, IndexError, TypeError):
            return default
    return obj


try:
    out = eval(sys.argv[2], {"d": d, "g": g, "json": json})
except Exception:
    out = None
if out is None:
    pass
elif isinstance(out, (list, tuple)):
    print("\n".join("" if x is None else str(x) for x in out))
elif isinstance(out, bool):
    print("true" if out else "false")
else:
    print(out)
PY
  fi
}

# JSON string literal for a shell value (for building request bodies without python).
json_str() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\t'/\\t}"
  printf '"%s"' "$s"
}

finish() {
  printf '\n-- %s: %d passed, %d failed, %d skipped, %d warnings\n' "${SMOKE_NAME:-smoke}" "$PASS_COUNT" "$FAIL_COUNT" "$SKIP_COUNT" "$WARN_COUNT"
  if [ "$FAIL_COUNT" -gt 0 ]; then exit 1; fi
  exit 0
}
