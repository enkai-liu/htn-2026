#!/usr/bin/env bash
# Smoke test for Baseten Model APIs (OpenAI-compatible) and, if configured, the OpenRouter fallback.
#   bash scripts/smoke_baseten.sh
# Answers the Hour-0 questions: which slugs exist, does a chat call work, do completion logprobs and PROMPT logprobs
# come back (surprisal needs the latter; if ABSENT we deploy the Truss), and does response_format json_schema work.
# Costs a few dozen tokens. Override the probe models with SMOKE_BASETEN_CHAT_MODEL / SMOKE_BASETEN_LOGPROBS_MODEL.
set -euo pipefail
SMOKE_NAME="baseten"
# shellcheck source=scripts/_lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"
load_env
section "Baseten"

chat_probe() { # chat_probe LABEL BASE_URL MODEL  -> PASS/FAIL line for a 4-token completion
  local label="$1" base="$2" model="$3" content finish_reason
  http POST "$base/chat/completions" '{"model":'"$(json_str "$model")"',"messages":[{"role":"user","content":"Say hi."}],"max_tokens":4}'
  if [ "$HTTP_STATUS" = "200" ]; then
    content="$(json_get "$HTTP_BODY" '.choices[0].message.content // empty' 'g(d,"choices",0,"message","content")' | tr '\n' ' ' | cut -c1-60)"
    finish_reason="$(json_get "$HTTP_BODY" '.choices[0].finish_reason // empty' 'g(d,"choices",0,"finish_reason")')"
    tokens="$(json_get "$HTTP_BODY" '"\(.usage.prompt_tokens // "?") in / \(.usage.completion_tokens // "?") out"' \
      '"%s in / %s out" % (g(d,"usage","prompt_tokens",default="?"), g(d,"usage","completion_tokens",default="?"))')"
    pass "$label chat completion on $model ($tokens, finish=$finish_reason) -> \"${content}\""
    if [ -z "$content" ]; then
      info "empty content with max_tokens=4 usually means the model spent them reasoning: it reasons by default"
    fi
  else
    fail "$label chat completion on $model -> HTTP $HTTP_STATUS $(http_error)"
    case "$HTTP_STATUS" in
      401) info "401: the key must be sent as a bearer token; check the key" ;;
      402) info "402: payment required. Redeem the event credits: Billing and usage -> Redeem promo credits (workspace owner)" ;;
      404) info "404: model slug not found; pick one from the list above" ;;
      429) info "429: rate limited. Unverified accounts get 15 RPM: verify the account, or use the event rate-limit form" ;;
    esac
  fi
}

if unset_or_placeholder "${BASETEN_API_KEY:-}"; then
  skip "(no key) BASETEN_API_KEY is not set in .env"
else
  require_tools
  BASE="${BASETEN_BASE_URL:-https://inference.baseten.co/v1}"
  BASE="${BASE%/}"
  HTTP_HEADERS="Authorization: Bearer ${BASETEN_API_KEY}
Accept: application/json"

  # 1. catalog ---------------------------------------------------------------------------------------------
  http GET "$BASE/models"
  slugs=""
  if [ "$HTTP_STATUS" = "200" ]; then
    slugs="$(json_get "$HTTP_BODY" '.data[]?.id' '[m.get("id") for m in g(d,"data",default=[])]')"
    pass "GET /models: $(printf '%s\n' "$slugs" | grep -c . || true) slugs"
    printf '%s\n' "$slugs" | sort | info_lines
  else
    fail "GET /models -> HTTP $HTTP_STATUS $(http_error)"
  fi

  pick_model() { # pick_model PREFERRED FALLBACK_PATTERN -> a slug that exists in the catalog
    local preferred="$1" pattern="$2" found
    if [ -z "$slugs" ] || printf '%s\n' "$slugs" | grep -Fqx "$preferred"; then printf '%s' "$preferred"; return; fi
    found="$(printf '%s\n' "$slugs" | grep -i -- "$pattern" | head -n 1 || true)"
    [ -n "$found" ] || found="$(printf '%s\n' "$slugs" | head -n 1)"
    printf '%s' "$found"
  }
  CHAT_MODEL="$(pick_model "${SMOKE_BASETEN_CHAT_MODEL:-deepseek-ai/DeepSeek-V4-Flash-0731}" "flash")"
  LOGPROBS_MODEL="$(pick_model "${SMOKE_BASETEN_LOGPROBS_MODEL:-openai/gpt-oss-120b}" "gpt-oss")"

  # 2. a 4-token chat completion on a cheap slug -----------------------------------------------------------------
  chat_probe "Baseten" "$BASE" "$CHAT_MODEL"

  # 3. logprobs / top_logprobs / prompt_logprobs -------------------------------------------------------------
  probe='{"model":'"$(json_str "$LOGPROBS_MODEL")"',"messages":[{"role":"user","content":"hi"}],"max_tokens":4,"logprobs":true,"top_logprobs":3'
  http POST "$BASE/chat/completions" "$probe"',"prompt_logprobs":1}'
  prompt_note=""
  if [ "$HTTP_STATUS" = "400" ] || [ "$HTTP_STATUS" = "422" ]; then
    prompt_note="REJECTED (HTTP $HTTP_STATUS when prompt_logprobs is sent)"
    http POST "$BASE/chat/completions" "$probe"'}'
  fi
  if [ "$HTTP_STATUS" = "200" ]; then
    lp="$(json_get "$HTTP_BODY" '.choices[0].logprobs.content[0] | "token=\(.token|tojson) logprob=\(.logprob) top_logprobs=\((.top_logprobs // [])|length)"' \
      '(lambda t: "token=%s logprob=%s top_logprobs=%d" % (json.dumps(t.get("token")), t.get("logprob"), len(t.get("top_logprobs") or [])) if isinstance(t, dict) else None)(g(d,"choices",0,"logprobs","content",0))')"
    plp="$(json_get "$HTTP_BODY" '(.prompt_logprobs // .choices[0].prompt_logprobs // empty) | length' \
      '(lambda p: len(p) if p else None)(g(d,"prompt_logprobs") or g(d,"choices",0,"prompt_logprobs"))')"
    pass "logprobs probe on $LOGPROBS_MODEL answered"
    if [ -n "$lp" ] && [ "$lp" != "null" ]; then
      info "completion logprobs: PRESENT  ($lp)"
    else
      info "completion logprobs: ABSENT   (try another slug: support varies by model)"
    fi
    if [ -n "$prompt_note" ]; then
      info "prompt logprobs:     $prompt_note -> surprisal needs the Truss + vLLM deployment (baseten/surprisal-truss)"
    elif [ -n "$plp" ] && [ "$plp" != "0" ]; then
      info "prompt logprobs:     PRESENT  ($plp prompt positions) -> true surprisal works on the shared API"
    else
      info "prompt logprobs:     ABSENT   -> surprisal needs the Truss + vLLM deployment (baseten/surprisal-truss)"
    fi
  else
    fail "logprobs probe on $LOGPROBS_MODEL -> HTTP $HTTP_STATUS $(http_error)"
  fi

  # 4. structured output ------------------------------------------------------------------------------------------
  http POST "$BASE/chat/completions" '{"model":'"$(json_str "$CHAT_MODEL")"',"messages":[{"role":"user","content":"Name one primary colour. Reply as JSON."}],"max_tokens":300,"response_format":{"type":"json_schema","json_schema":{"name":"colour","strict":true,"schema":{"type":"object","additionalProperties":false,"required":["colour"],"properties":{"colour":{"type":"string"}}}}}}'
  if [ "$HTTP_STATUS" = "200" ]; then
    json_get "$HTTP_BODY" '.choices[0].message.content // empty' 'g(d,"choices",0,"message","content")' >"$SMOKE_TMP/structured.json"
    colour="$(json_get "$SMOKE_TMP/structured.json" '.colour // empty' 'g(d,"colour")')"
    if [ -n "$colour" ]; then
      pass "response_format json_schema on $CHAT_MODEL returned schema-valid JSON (colour=$colour)"
    else
      fail "response_format json_schema on $CHAT_MODEL: content is not the requested JSON: $(head -c 160 "$SMOKE_TMP/structured.json" | tr '\n' ' ')"
    fi
  else
    fail "response_format json_schema on $CHAT_MODEL -> HTTP $HTTP_STATUS $(http_error)"
  fi
fi

# 5. OpenRouter fallback -------------------------------------------------------------------------------------------
section "OpenRouter (fallback provider)"
if unset_or_placeholder "${OPENROUTER_API_KEY:-}"; then
  skip "(no key) OPENROUTER_API_KEY is not set: the fallback provider is not checked"
else
  require_tools
  HTTP_HEADERS="Authorization: Bearer ${OPENROUTER_API_KEY}
Accept: application/json"
  OR_BASE="${OPENROUTER_BASE_URL:-https://openrouter.ai/api/v1}"
  chat_probe "OpenRouter" "${OR_BASE%/}" "${SMOKE_OPENROUTER_MODEL:-openai/gpt-oss-120b}"
fi

finish
