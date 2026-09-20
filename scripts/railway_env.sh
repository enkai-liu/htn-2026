#!/usr/bin/env bash
# Copy the API's keys from .env to the Railway service, one at a time over stdin, so no value appears in a process
# argument, the shell history or this script's output. Run it yourself, from the repo root, after `railway link`.
#   bash scripts/railway_env.sh [service]      (default: slop-api)
# Only the names below are sent; anything blank in .env is skipped, which leaves that feature off.
set -euo pipefail

SERVICE="${1:-slop-api}"
ENV_FILE="${ENV_FILE:-.env}"
KEYS=(
  ES_URL ES_API_KEY KIBANA_URL ES_INDEX ES_EMBED_INFERENCE_ID ES_RERANK_INFERENCE_ID
  BASETEN_API_KEY BASETEN_BASE_URL OPENROUTER_API_KEY OPENROUTER_BASE_URL LLM_RPM_LIMIT
  GPTZERO_API_KEY GPTZERO_MODE GPTZERO_INTERACTIVE_WORD_CAP GPTZERO_INVESTIGATION_WORD_CAP
  SURPRISAL_BASE_URL SURPRISAL_API_KEY SURPRISAL_MODEL
  GITHUB_TOKEN EXA_API_KEY BROWSERBASE_API_KEY BROWSERBASE_PROJECT_ID SLACK_WEBHOOK_URL
)

[ -f "$ENV_FILE" ] || { echo "no $ENV_FILE here: run this from the repo root" >&2; exit 1; }
command -v railway >/dev/null || { echo "railway CLI not found: brew install railway" >&2; exit 1; }

sent=0
for key in "${KEYS[@]}"; do
  # last assignment wins, as dotenv reads it; strip one pair of surrounding quotes and a trailing CR
  line="$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" | tail -n 1 || true)"
  value="${line#*=}"
  value="${value%$'\r'}"
  value="${value%\"}"; value="${value#\"}"
  value="${value%\'}"; value="${value#\'}"
  if [ -z "$line" ] || [ -z "$value" ]; then
    echo "  skip  $key (blank)"
    continue
  fi
  printf '%s' "$value" | railway variable set "$key" --stdin --service "$SERVICE" --skip-deploys >/dev/null
  echo "  set   $key"
  sent=$((sent + 1))
done

# Not secrets, and not in .env: what a public deploy needs that a laptop does not.
railway variable set MAX_RUNS_PER_DAY=40 MAX_LIVE_RUNS=3 ORCHESTRATOR=asyncio --service "$SERVICE" --skip-deploys >/dev/null
echo "  set   MAX_RUNS_PER_DAY=40 MAX_LIVE_RUNS=3 ORCHESTRATOR=asyncio"
echo "$sent keys copied to '$SERVICE'. Nothing redeploys until the next \`railway up\`."
