#!/usr/bin/env bash
# Secret scan: run before the repo goes public (and any time you like). Exits 1 on any hit.
#   bash scripts/secret_scan.sh            # scan tracked + untracked-not-ignored files
#   bash scripts/secret_scan.sh PATH...    # scan specific files or directories instead
#
# Prints file:line and the rule that matched, NEVER the matched text. Rotate any key that shows up here.
# Rules: provider key shapes (sk-..., GitHub gh?_ / github_pat_, Slack webhooks, Elastic ApiKey base64, AWS, Google,
# private-key blocks), long token-like values assigned to *api_key / *token / *secret / *password, and .env files
# that are tracked by git. A line containing `secret-scan: allow` is skipped (for documented fake examples).
#
# git is optional: if `git ls-files` fails (for example an unaccepted Xcode licence makes every git command exit
# non-zero) the scan falls back to `find`, skipping .git, node_modules, .venv, data, .next, and .env* files,
# which .gitignore is then REQUIRED to cover.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 2

LIST="$(mktemp "${TMPDIR:-/tmp}/whitespace-secretscan.XXXXXX")"
HITS="$(mktemp "${TMPDIR:-/tmp}/whitespace-secretscan.XXXXXX")"
trap 'rm -f "$LIST" "$HITS" "$LIST.raw" "$LIST.z"' EXIT
PROBLEMS=0

# ---------------------------------------------------------------------------------------------- which files
MODE="git"
if [ "$#" -gt 0 ]; then
  MODE="paths"
  for target in "$@"; do
    if [ -d "$target" ]; then
      find "$target" -type d \( -name .git -o -name node_modules -o -name '.venv*' -o -name site-packages \) -prune -o -type f -print
    elif [ -f "$target" ]; then
      printf '%s\n' "$target"
    else
      printf 'secret_scan: no such file or directory: %s\n' "$target" >&2
      exit 2
    fi
  done >"$LIST.raw"
elif git ls-files --cached --others --exclude-standard >"$LIST.raw" 2>/dev/null && [ -s "$LIST.raw" ]; then
  # .env files that are TRACKED are a finding on their own, whatever they contain
  tracked_env="$(git ls-files --cached 2>/dev/null | grep -E '(^|/)\.env($|\.)' | grep -Ev '(^|/)\.env\.(example|sample|template)$' || true)"
  if [ -n "$tracked_env" ]; then
    printf '%s\n' "$tracked_env" | while IFS= read -r f; do printf 'HIT   %s: tracked .env file (git rm --cached it, then rotate every key in it)\n' "$f"; done
    PROBLEMS=$((PROBLEMS + $(printf '%s\n' "$tracked_env" | grep -c .)))
  fi
else
  MODE="find"
  # mirrors .gitignore: any virtualenv (.venv, .venv-jiuwen, venv), dependency and build output, caches, data, run logs
  find . -type d \( -name .git -o -name node_modules -o -name '.venv*' -o -name 'venv*' -o -name site-packages \
    -o -name data -o -name .next -o -name out -o -name dist -o -name build -o -name .vercel -o -name .turbo \
    -o -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .mypy_cache -o -name '*.egg-info' \
    -o -name runs -o -name logs -o -name .checkpoints -o -name .idea -o -name .vscode \) -prune \
    -o -type f -not -name '.env' -not -name '.env.*' -not -name '.DS_Store' -not -name '*.tsbuildinfo' -print |
    sed 's|^\./||' >"$LIST.raw"
  if [ -f .env.example ]; then printf '.env.example\n' >>"$LIST.raw"; fi
  printf 'NOTE  git is unavailable here, so ignore rules cannot be evaluated: scanning everything except\n'
  printf '      .git, node_modules, virtualenvs, data, .next, build output, caches and .env files (assumed git-ignored).\n'
  if ! grep -Eq '^\.env$' .gitignore 2>/dev/null; then
    printf 'HIT   .gitignore: has no ".env" line, so the real .env could be committed\n'
    PROBLEMS=$((PROBLEMS + 1))
  fi
fi

# lock files and binaries are noise; this script and the scanner's own docs describe the patterns themselves
grep -Ev '(^|/)(pnpm-lock\.yaml|package-lock\.json|yarn\.lock|uv\.lock|poetry\.lock|Cargo\.lock)$' "$LIST.raw" |
  grep -Ev '\.(png|jpe?g|gif|ico|webp|pdf|woff2?|ttf|otf|eot|zip|gz|tgz|parquet|pyc|so|dylib|mp4|mov|wasm)$' |
  grep -Fvx 'scripts/secret_scan.sh' | sort -u >"$LIST"
N_FILES="$(grep -c . "$LIST" || true)"
if [ "$N_FILES" -eq 0 ]; then
  printf 'secret_scan: nothing to scan\n'
  exit 0
fi
tr '\n' '\0' <"$LIST" >"$LIST.z"

# ---------------------------------------------------------------------------------------------- rules
# scan RULE_NAME ERE [i]  -> appends "file:line:rule" to $HITS. -I skips binaries, -o keeps the match out of our output.
scan() {
  local rule="$1" pattern="$2" flags="-nIoE"
  if [ "${3:-}" = "i" ]; then flags="-nIoiE"; fi
  # shellcheck disable=SC2086
  xargs -0 grep $flags -e "$pattern" /dev/null <"$LIST.z" 2>/dev/null |
    awk -v rule="$rule" -F: 'NF >= 3 { print $1 ":" $2 ":" rule }' >>"$HITS" || true
}

B='(^|[^A-Za-z0-9_-])' # a key does not start in the middle of a word ("task-...", "mask-image-...")
scan "openai-style secret key (sk-...)"        "${B}sk-(proj-|or-v1-|ant-)?[A-Za-z0-9_-]{20,}"
scan "github token (gh?_...)"                  "${B}gh[opsur]_[A-Za-z0-9]{30,}"
scan "github fine-grained token"               "${B}github_pat_[A-Za-z0-9_]{22,}"
scan "slack webhook"                           "hooks\.slack\.com/services/T[A-Za-z0-9]+/B[A-Za-z0-9]+/[A-Za-z0-9]{16,}"
scan "slack token"                             "${B}xox[abprs]-[A-Za-z0-9-]{10,}"
scan "elastic ApiKey (base64 id:key)"          "ApiKey[[:space:]]+[A-Za-z0-9+/_-]{40,}={0,2}"
scan "elastic serverless key (essu_...)"       "${B}essu_[A-Za-z0-9+/=_-]{30,}"
scan "aws access key id"                       "${B}(AKIA|ASIA)[A-Z0-9]{16}"
scan "google api key"                          "${B}AIza[A-Za-z0-9_-]{35}"
scan "hugging face token"                      "${B}hf_[A-Za-z0-9]{30,}"
scan "private key block"                       "-----BEGIN [A-Z ]*PRIVATE KEY-----"

# Generic: <something>api_key / token / secret / password  = or :  a long value. Post-filtered below so that code such
# as `api_key=settings.baseten_api_key` is not a hit: a real key has digits AND letters and is not a placeholder.
GENERIC="(api[_-]?key|apikey|token|secret|passwd|password|webhook_url)[\"']?[[:space:]]*[:=][[:space:]]*[\"']?[A-Za-z0-9_+/=.-]{20,}"
xargs -0 grep -nIoiE -e "$GENERIC" /dev/null <"$LIST.z" 2>/dev/null |
  awk -F: 'NF >= 3 {
    m = $0; sub(/^[^:]*:[0-9]+:/, "", m)            # the matched text only (never printed)
    v = m; sub(/^[^:=]*[:=][ \t]*["\047]?/, "", v)   # the value part
    if (v !~ /[0-9]/ || v !~ /[A-Za-z]/) next        # identifiers and words have no digits; numbers have no letters
    lv = tolower(v)
    if (lv ~ /your|example|placeholder|changeme|redacted|dummy|xxxx|test-key|fake|sample|\.\.\./) next
    if (v ~ /^[a-z_]+(\.[a-z_0-9]+)+$/) next         # dotted attribute path, e.g. settings.es_api_key_v2
    if (v ~ /^[A-Za-z_][A-Za-z0-9_]*\.[a-z_]+$/) next
    if (v ~ /^https?:/) next
    print $1 ":" $2 ":generic long value assigned to a key/token/secret/password name"
  }' >>"$HITS" || true

# ---------------------------------------------------------------------------------------------- report
# drop lines that opt out with the pragma, de-duplicate, print without the secret
if [ -s "$HITS" ]; then
  sort -u "$HITS" | while IFS= read -r hit; do
    file="${hit%%:*}"
    rest="${hit#*:}"
    line="${rest%%:*}"
    rule="${rest#*:}"
    if sed -n "${line}p" "$file" 2>/dev/null | grep -q 'secret-scan: allow'; then continue; fi
    printf 'HIT   %s:%s  %s\n' "$file" "$line" "$rule"
  done >"$HITS.out"
  if [ -s "$HITS.out" ]; then
    cat "$HITS.out"
    PROBLEMS=$((PROBLEMS + $(grep -c . "$HITS.out")))
  fi
  rm -f "$HITS.out"
fi

printf '\nsecret_scan: %s files scanned (file list from: %s)\n' "$N_FILES" "$MODE"
if [ "$PROBLEMS" -gt 0 ]; then
  printf 'FAIL  %s potential secret(s). The values are deliberately not shown: open the file:line above.\n' "$PROBLEMS"
  printf '      If a real key was ever committed or pushed, ROTATE it; deleting the line is not enough.\n'
  exit 1
fi
printf 'PASS  no secrets found\n'
exit 0
