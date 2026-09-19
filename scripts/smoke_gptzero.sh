#!/usr/bin/env bash
# Smoke test for the GPTZero API. IT SPENDS WORDS, so it only runs with --live.
#   bash scripts/smoke_gptzero.sh                # prints what it would do, calls nothing
#   bash scripts/smoke_gptzero.sh --live         # ~100 words: usage, predict, bibliography-scan, usage, patterns probe
#   bash scripts/smoke_gptzero.sh --usage-only   # free: just GET /v3/usage-stats
# Answers the Hour-0 questions: is the key valid, how many words are left, is bibliography-scan open to our key,
# how is it BILLED (usage delta), does it recognise a Devpost URL, and is /v3/ai/patterns/stream allow-listed (403 = no).
set -euo pipefail
SMOKE_NAME="gptzero"
# shellcheck source=scripts/_lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"
load_env
section "GPTZero"

LIVE=0
USAGE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --live) LIVE=1 ;;
    --usage-only) USAGE_ONLY=1 ;;
    -h | --help) sed -n '2,8p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

BASE="${GPTZERO_BASE_URL:-https://api.gptzero.me}"
BASE="${BASE%/}"
LAG="${SMOKE_USAGE_LAG_S:-2}" # usage counters are not instant; wait this long before re-reading them
# >= 300 characters, deliberately generic prose (about 75 words).
SAMPLE="In today's fast-paced digital landscape, students face unprecedented challenges in managing their academic workload. Our innovative platform leverages cutting-edge artificial intelligence to revolutionize the way learners engage with course material. By seamlessly integrating personalized study plans, real-time feedback, and adaptive quizzes, we empower users to unlock their full potential and foster a lifelong love of learning."
BIBLIO='DevSpot already validates hackathon ideas against Devpost [1].

References
[1] DevSpot team. "DevSpot." Devpost. 2024. https://devpost.com/software/devspot'

if unset_or_placeholder "${GPTZERO_API_KEY:-}"; then
  skip "(no key) GPTZERO_API_KEY is not set in .env"
  finish
fi

if [ "$LIVE" -eq 0 ] && [ "$USAGE_ONLY" -eq 0 ]; then
  skip "dry run: this smoke test spends GPTZero words, so it only runs with --live. It would:"
  info "1. GET  $BASE/v3/usage-stats                 (free)  -> words_left / plan, BEFORE"
  info "2. POST $BASE/v2/predict/text                (~$(printf '%s' "$SAMPLE" | wc -w | tr -d ' ') words) -> predicted_class / confidence_category / subclass"
  info "3. POST $BASE/v2/bibliography-scan/text      (~$(printf '%s' "$BIBLIO" | wc -w | tr -d ' ') words, billing unknown) -> citation statuses + stances"
  info "4. GET  $BASE/v3/usage-stats                 (free)  -> AFTER, and the word delta of steps 2 and 3"
  info "5. POST $BASE/v3/ai/patterns/stream          (403 expected: not allow-listed)"
  info "re-run with: bash scripts/smoke_gptzero.sh --live      (or --usage-only, which is free)"
  finish
fi
require_tools

HTTP_HEADERS="x-api-key: ${GPTZERO_API_KEY}
Accept: application/json"

read_usage() { # read_usage LABEL -> sets USED / LEFT (may be empty), prints one line
  http GET "$BASE/v3/usage-stats"
  USED=""
  LEFT=""
  if [ "$HTTP_STATUS" = "200" ]; then
    USED="$(json_get "$HTTP_BODY" '.words_used // empty' 'g(d,"words_used")')"
    LEFT="$(json_get "$HTTP_BODY" '.words_left // empty' 'g(d,"words_left")')"
    plan="$(json_get "$HTTP_BODY" '.plan // empty' 'g(d,"plan")')"
    cycle="$(json_get "$HTTP_BODY" '"\(.cycle_start // "?") -> \(.cycle_end // "?")"' '"%s -> %s" % (g(d,"cycle_start",default="?"), g(d,"cycle_end",default="?"))')"
    pass "usage-stats $1: words_left=${LEFT:-null (metered plan)} words_used=${USED:-?} plan=${plan:-?} cycle=$cycle"
  else
    fail "GET /v3/usage-stats ($1) -> HTTP $HTTP_STATUS $(http_error)"
    case "$HTTP_STATUS" in
      404) info "404: API key / plan not found or expired. Get a key at https://app.gptzero.me/app/api" ;;
      429) info "429 on a free call usually means the x-api-key header was not accepted (free-tier limits applied)" ;;
    esac
  fi
}

delta() { # delta BEFORE_USED AFTER_USED BEFORE_LEFT AFTER_LEFT -> words billed, or "?"
  if [ -n "$1" ] && [ -n "$2" ]; then
    printf '%s' "$(($2 - $1))"
  elif [ -n "$3" ] && [ -n "$4" ]; then
    printf '%s' "$(($3 - $4))"
  else
    printf '?'
  fi
}

read_usage "BEFORE"
if [ "$HTTP_STATUS" != "200" ] || [ "$USAGE_ONLY" -eq 1 ]; then
  finish
fi
USED0="$USED"
LEFT0="$LEFT"

# 2. AI detection -------------------------------------------------------------------------------------------------
sent_words="$(printf '%s' "$SAMPLE" | wc -w | tr -d ' ')"
http POST "$BASE/v2/predict/text" '{"document":'"$(json_str "$SAMPLE")"'}'
if [ "$HTTP_STATUS" = "200" ]; then
  cls="$(json_get "$HTTP_BODY" '.documents[0].predicted_class // empty' 'g(d,"documents",0,"predicted_class")')"
  conf="$(json_get "$HTTP_BODY" '.documents[0].confidence_category // empty' 'g(d,"documents",0,"confidence_category")')"
  sub="$(json_get "$HTTP_BODY" '.documents[0] | (.subclass // {}) | (.ai.predicted_class // .mixed.predicted_class // "none")' \
    'g(d,"documents",0,"subclass","ai","predicted_class") or g(d,"documents",0,"subclass","mixed","predicted_class") or "none"')"
  msg="$(json_get "$HTTP_BODY" '.documents[0].result_message // empty' 'g(d,"documents",0,"result_message")')"
  version="$(json_get "$HTTP_BODY" '.version // empty' 'g(d,"version")')"
  nsent="$(json_get "$HTTP_BODY" '(.documents[0].sentences // []) | length' 'len(g(d,"documents",0,"sentences",default=[]))')"
  sentence_keys="$(json_get "$HTTP_BODY" '(.documents[0].sentences[0].class_probabilities // {}) | keys | join(",")' \
    '",".join(sorted(g(d,"documents",0,"sentences",0,"class_probabilities",default={})))')"
  has_mask="$(json_get "$HTTP_BODY" '.documents[0].sentences[0] | has("should_mask")' '"should_mask" in g(d,"documents",0,"sentences",0,default={})')"
  if [ -n "$cls" ] && [ -n "$conf" ]; then
    pass "predict/text: predicted_class=$cls confidence_category=$conf subclass=$sub model=$version"
    info "result_message: $msg"
    info "$nsent sentences; sentence-level class_probabilities keys: ${sentence_keys:-none} (expect ai,human,paraphrased); should_mask present: $has_mask"
  else
    fail "predict/text answered 200 without predicted_class / confidence_category: $(head -c 200 "$HTTP_BODY" | tr '\n' ' ')"
  fi
else
  fail "POST /v2/predict/text -> HTTP $HTTP_STATUS $(http_error)"
fi
sleep "$LAG"
read_usage "after predict"
USED1="$USED"
LEFT1="$LEFT"
info "predict/text billed $(delta "$USED0" "$USED1" "$LEFT0" "$LEFT1") words for $sent_words words sent"

# 3. bibliography scan (the hallucination API) -------------------------------------------------------------------------
sent_words="$(printf '%s' "$BIBLIO" | wc -w | tr -d ' ')"
SMOKE_TIMEOUT=90 http POST "$BASE/v2/bibliography-scan/text" '{"document":'"$(json_str "$BIBLIO")"'}'
if [ "$HTTP_STATUS" = "200" ]; then
  cits="$(json_get "$HTTP_BODY" '.bibliographic_citations[]? | "citation status=\(.citation_exists.status // "?")  \((.text // "")[0:70])"' \
    '["citation status=%s  %s" % (g(c,"citation_exists","status",default="?"), (c.get("text") or "")[:70]) for c in g(d,"bibliographic_citations",default=[])]')"
  claims="$(json_get "$HTTP_BODY" '.claims[]? | "claim stance=\(.agree_with_citation.stance // "null") type=\(.claim_type // "?")  \((.text // "")[0:70])"' \
    '["claim stance=%s type=%s  %s" % (g(c,"agree_with_citation","stance",default="null"), c.get("claim_type") or "?", (c.get("text") or "")[:70]) for c in g(d,"claims",default=[])]')"
  pass "bibliography-scan/text is open to this key: $(printf '%s\n' "$cits" | grep -c . || true) citations, $(printf '%s\n' "$claims" | grep -c . || true) claims"
  printf '%s\n%s\n' "$cits" "$claims" | info_lines
  if printf '%s\n' "$cits" | grep -q 'status=fake'; then
    warn "a REAL Devpost page came back 'fake': do not let 'fake' alone reject claims about non-academic URLs (see biblio.resolve_status trust_local_match_over_fake)"
  elif printf '%s\n' "$cits" | grep -Eq 'status=(unknown|unsure)'; then
    info "a real Devpost URL came back unknown/unsure: as designed, the local quote check decides those"
  fi
elif [ "$HTTP_STATUS" = "403" ]; then
  fail "bibliography-scan/text is GATED for this key (403): ask the GPTZero booth / api@gptzero.me. The local quote check still gates claims."
else
  fail "POST /v2/bibliography-scan/text -> HTTP $HTTP_STATUS $(http_error)"
fi
sleep "$LAG"
read_usage "AFTER"
info "bibliography-scan billed $(delta "$USED1" "$USED" "$LEFT1" "$LEFT") words for $sent_words words sent"
info "total for this smoke run: $(delta "$USED0" "$USED" "$LEFT0" "$LEFT") words (usage counters can lag: re-check with --usage-only)"

# 4. AI patterns (allow-list gated) ------------------------------------------------------------------------------------
HTTP_HEADERS="x-api-key: ${GPTZERO_API_KEY}
Accept: text/event-stream"
SMOKE_TIMEOUT=20 http POST "$BASE/v3/ai/patterns/stream" '{"documents":[{"inputText":'"$(json_str "$SAMPLE")"'}]}'
case "$HTTP_STATUS" in
  403) pass "ai/patterns/stream -> 403: not allow-listed (expected). Ask the GPTZero booth for access." ;;
  200) pass "ai/patterns/stream -> 200: THIS KEY IS ALLOW-LISTED. $(grep -c '^data:' "$HTTP_BODY" || true) pattern events returned." ;;
  *) warn "ai/patterns/stream -> HTTP $HTTP_STATUS (expected 403): $(http_error)" ;;
esac

finish
