#!/usr/bin/env bash
# Smoke test for Elastic Cloud Serverless: cluster, EIS inference endpoints (embed + rerank), the canary query, Kibana.
#   bash scripts/smoke_elastic.sh
# Reads ES_URL, ES_API_KEY, KIBANA_URL, ES_EMBED_INFERENCE_ID, ES_RERANK_INFERENCE_ID, ES_INDEX from the repo-root .env
# (or the environment). Prints PASS / FAIL / SKIP lines; exits non-zero only when something FAILed.
set -euo pipefail
SMOKE_NAME="elastic"
# shellcheck source=scripts/_lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"
load_env
section "Elastic"

if unset_or_placeholder "${ES_URL:-}" || unset_or_placeholder "${ES_API_KEY:-}"; then
  skip "(no key) ES_URL / ES_API_KEY are not set in .env"
  finish
fi
require_tools

ES_URL="${ES_URL%/}"
EMBED_ID="${ES_EMBED_INFERENCE_ID:-.jina-embeddings-v3}"
RERANK_ID="${ES_RERANK_INFERENCE_ID:-.jina-reranker-v3}"
INDEX="${ES_INDEX:-prior-art-v1}"
CANARY="validate hackathon idea originality"
HTTP_HEADERS="Authorization: ApiKey ${ES_API_KEY}
Accept: application/json"

# 1. reachable ---------------------------------------------------------------------------------------------
http GET "$ES_URL/"
if [ "$HTTP_STATUS" = "200" ]; then
  flavor="$(json_get "$HTTP_BODY" '.version.build_flavor // empty' 'g(d,"version","build_flavor")')"
  number="$(json_get "$HTTP_BODY" '.version.number // empty' 'g(d,"version","number")')"
  pass "Elasticsearch reachable (${flavor:-unknown flavor} ${number:-})"
elif [ "$HTTP_STATUS" = "401" ] || [ "$HTTP_STATUS" = "403" ]; then
  fail "Elasticsearch rejected the API key (HTTP $HTTP_STATUS): create an unrestricted key and set ES_API_KEY"
  finish
else
  fail "Elasticsearch not reachable at ES_URL (HTTP $HTTP_STATUS) $(http_error)"
  finish
fi

# 2. inference endpoints -----------------------------------------------------------------------------------
http GET "$ES_URL/_inference/_all"
if [ "$HTTP_STATUS" = "200" ]; then
  endpoints="$(json_get "$HTTP_BODY" '.endpoints[]? | "\(.task_type)\t\(.inference_id)"' \
    '[str(e.get("task_type")) + "\t" + str(e.get("inference_id")) for e in g(d,"endpoints",default=[])]')"
  count="$(printf '%s\n' "$endpoints" | grep -c . || true)"
  pass "GET _inference/_all: $count endpoints"
  printf '%s\n' "$endpoints" | sort | info_lines
  for pair in "text_embedding:$EMBED_ID" "rerank:$RERANK_ID"; do
    kind="${pair%%:*}"
    id="${pair#*:}"
    if printf '%s\n' "$endpoints" | grep -Fqx "$(printf '%s\t%s' "$kind" "$id")"; then
      pass "configured $kind endpoint exists: $id"
    else
      fail "configured $kind endpoint '$id' not found: set ES_$( [ "$kind" = rerank ] && echo RERANK || echo EMBED )_INFERENCE_ID to one of the candidates below"
      # same task type first (Jina ones are what the design expects); if there are none, say so
      candidates="$(printf '%s\n' "$endpoints" | grep "^$kind" || true)"
      if [ -n "$candidates" ]; then
        printf '%s\n' "$candidates" | grep -i jina | sort | info_lines "candidate (Jina): " || true
        printf '%s\n' "$candidates" | grep -iv jina | sort | info_lines "candidate: " || true
      else
        info "no $kind endpoints at all on this project: check that EIS / Jina models are enabled"
      fi
    fi
  done
else
  fail "GET _inference/_all -> HTTP $HTTP_STATUS $(http_error)"
fi

# 3. one embedding call, one rerank call -------------------------------------------------------------------
http POST "$ES_URL/_inference/text_embedding/$EMBED_ID" '{"input":["a tool that checks whether a hackathon idea is original"]}'
if [ "$HTTP_STATUS" = "200" ]; then
  dims="$(json_get "$HTTP_BODY" '((.text_embedding // .embeddings // [])[0].embedding // []) | length' \
    'len(g(d,"text_embedding",0,"embedding",default=None) or g(d,"embeddings",0,"embedding",default=[]))')"
  if [ "${dims:-0}" -gt 0 ] 2>/dev/null; then
    pass "text_embedding/$EMBED_ID returned a ${dims}-dimensional vector"
  else
    warn "text_embedding/$EMBED_ID answered 200 but no float vector was found (byte/bit embeddings?): $(head -c 160 "$HTTP_BODY")"
  fi
else
  fail "text_embedding/$EMBED_ID -> HTTP $HTTP_STATUS $(http_error)"
fi

http POST "$ES_URL/_inference/rerank/$RERANK_ID" \
  '{"query":"check if my hackathon idea already exists","input":["DevSpot validates hackathon ideas against Devpost","A recipe app for leftovers in your fridge"]}'
if [ "$HTTP_STATUS" = "200" ]; then
  top="$(json_get "$HTTP_BODY" '(.rerank // []) | sort_by(-.relevance_score) | (.[0] // empty) | "\(.index) (score \(.relevance_score))"' \
    '(lambda r: "%s (score %s)" % (r[0].get("index"), r[0].get("relevance_score")) if r else None)(sorted(g(d,"rerank",default=[]), key=lambda x: -x.get("relevance_score", 0)))')"
  case "$top" in
    0*) pass "rerank/$RERANK_ID ranked the relevant passage first: index $top" ;;
    '') warn "rerank/$RERANK_ID answered 200 but no .rerank[] array was found" ;;
    *) warn "rerank/$RERANK_ID works but ranked the irrelevant passage first: index $top" ;;
  esac
else
  fail "rerank/$RERANK_ID -> HTTP $HTTP_STATUS $(http_error)"
fi

# 4. canary query ------------------------------------------------------------------------------------------
http GET "$ES_URL/$INDEX/_count"
if [ "$HTTP_STATUS" = "200" ]; then
  docs="$(json_get "$HTTP_BODY" '.count // empty' 'g(d,"count")')"
  info "index $INDEX holds ${docs:-?} documents"
  q="$(json_str "$CANARY")"
  hybrid='{"size":5,"_source":["title","source","year","url"],"retriever":{"text_similarity_reranker":{"retriever":{"rrf":{"retrievers":[{"standard":{"query":{"multi_match":{"query":'"$q"',"fields":["title^3","tagline^2","pitch"]}}}},{"standard":{"query":{"semantic":{"field":"semantic_pitch","query":'"$q"'}}}}],"rank_window_size":100,"rank_constant":20}},"field":"pitch","inference_id":'"$(json_str "$RERANK_ID")"',"inference_text":'"$q"',"rank_window_size":40}}}'
  http POST "$ES_URL/$INDEX/_search" "$hybrid"
  mode="hybrid (BM25 + semantic, RRF, reranked)"
  if [ "$HTTP_STATUS" != "200" ]; then
    warn "hybrid retriever query failed (HTTP $HTTP_STATUS): $(http_error)"
    http POST "$ES_URL/$INDEX/_search" '{"size":5,"_source":["title","source","year","url"],"query":{"multi_match":{"query":'"$q"',"fields":["title^3","tagline^2","pitch"]}}}'
    mode="BM25 only (fallback)"
  fi
  if [ "$HTTP_STATUS" = "200" ]; then
    titles="$(json_get "$HTTP_BODY" '.hits.hits[]? | "\(._source.title // "?")  [\(._source.source // "?") \(._source.year // "")]"' \
      '["%s  [%s %s]" % (g(h,"_source","title",default="?"), g(h,"_source","source",default="?"), g(h,"_source","year",default="") or "") for h in g(d,"hits","hits",default=[])]')"
    n="$(printf '%s\n' "$titles" | grep -c . || true)"
    if [ "$n" -gt 0 ]; then
      pass "canary query \"$CANARY\" -> $n hits, $mode"
      printf '%s\n' "$titles" | info_lines
      if printf '%s\n' "$titles" | grep -Eqi 'devspot|hackanalyzer'; then
        pass "known prior art (DevSpot / HackAnalyzer) is in the top 5"
      else
        warn "DevSpot / HackAnalyzer not in the top 5: run ingest.seed_known_prior_art, or the corpus is still loading"
      fi
    else
      warn "canary query returned 0 hits: the index is empty or still loading"
    fi
  else
    fail "canary query -> HTTP $HTTP_STATUS $(http_error)"
  fi
elif [ "$HTTP_STATUS" = "404" ]; then
  skip "index $INDEX does not exist yet (run: make apply && make ingest-tier0): canary query not run"
else
  fail "GET $INDEX/_count -> HTTP $HTTP_STATUS $(http_error)"
fi

# 5. Kibana / Agent Builder ---------------------------------------------------------------------------------
if unset_or_placeholder "${KIBANA_URL:-}"; then
  skip "(no key) KIBANA_URL is not set: Agent Builder not checked"
else
  HTTP_HEADERS="Authorization: ApiKey ${ES_API_KEY}
kbn-xsrf: true
Accept: application/json"
  http GET "${KIBANA_URL%/}/api/agent_builder/tools"
  if [ "$HTTP_STATUS" = "200" ]; then
    tools="$(json_get "$HTTP_BODY" 'if type == "array" then length else ((.results // .tools // .data // []) | length) end' \
      'len(d) if isinstance(d, list) else len(g(d,"results",default=None) or g(d,"tools",default=None) or g(d,"data",default=[]))')"
    ours="$(json_get "$HTTP_BODY" '[(if type == "array" then . else (.results // .tools // .data // []) end)[] | .id | select(startswith("originality."))] | length' \
      'len([t for t in (d if isinstance(d, list) else (g(d,"results",default=None) or g(d,"tools",default=None) or g(d,"data",default=[]))) if str(t.get("id","")).startswith("originality.")])')"
    pass "Kibana Agent Builder reachable: ${tools:-?} tools (${ours:-0} of ours, originality.*)"
  elif [ "$HTTP_STATUS" = "404" ]; then
    fail "Kibana answered 404 for /api/agent_builder/tools: check KIBANA_URL and that Agent Builder is enabled"
  else
    fail "Kibana Agent Builder -> HTTP $HTTP_STATUS $(http_error)"
  fi
fi

finish
