# Handover — written Sat 2026-09-19 (code state as of ~16:00 EDT, after Elastic went live; check `date` — the 14:00 EDT prize lock is past, the Sun 08:00 final submission is next)

Paste the block below into a fresh Claude Code session opened in `/Users/enkailiu/Projects/htn-2026`.

---

```text
You are continuing a Hack the North 2026 build called "Whitespace": a multi-agent tool that scores how original a
hackathon/startup idea is (retrieval-grounded, with verified citations) and coaches the author toward a more original
version. Repo: /Users/enkailiu/Projects/htn-2026 (remote github.com/enkai-liu/htn-2026, private, branch main).

READ FIRST, in this order: docs/HANDOVER.md (state + open issues), docs/PLAN.md (approved plan, lanes, schedule, cut
lines), docs/events.md (the SSE contract every lane builds on), docs/scoring.md. Exact Elastic JSON/YAML, the
openjiuwen host design and the demo script are in docs/design-full.md; sponsor research is in docs/research/.

HARD DEADLINES (EDT): Sat Sep 19 14:00 initial Devpost submission + sponsor prizes LOCKED. Sun Sep 20 08:00 final
submission (aim 07:15). Sponsor judging Sun 09:45-11:45; judging is a 5-minute LIVE demo. Team of 4.
Tracks (LOCKED at initial Devpost submission, Sat 14:00): GPTZero, Baseten, Huawei openJiuwen, Rox, Elastic,
GoDaddy domain, Browserbase. RBC: NOT opted in (its challenge is a financial-data Q&A benchmark on RBC's own
MCP server - a different project).

MACHINE QUIRKS: /usr/bin/git and /usr/bin/make are blocked by an unaccepted Xcode licence. Prefix every git/make
command with DEVELOPER_DIR=/Library/Developer/CommandLineTools (or the user runs `sudo xcodebuild -license`).
Python: use backend/.venv (3.12; system python is 3.14 and too new). openjiuwen lives in backend/.venv-jiuwen.
No docker, no uv. Node 23 + pnpm. Do not add attribution lines to commits. Commit small and often; push to origin main.

RULES THAT MUST HOLD: never build anything that defeats bot detection (Devpost's /software/search is behind an AWS WAF
challenge - leave it alone; galleries/project pages are fine at <=1 req/s; a blocked site is reported as blocked).
GPTZero "Voice" stays a separate axis, never folded into the originality score; never show raw probabilities; replay/
fixture GPTZero data must never be presented as a real reading. Mock/simulated data is always labelled. Publish only
aggregated/anonymised investigation results. I cannot create accounts or enter credentials - the user does that.
Dataset downloads need the user's explicit go-ahead (Tier 0 ~15 MB, Tier 1 372 MB from Hugging Face).

FIRST TASKS:
1. Run the checks in docs/HANDOVER.md "Verify the state" and confirm everything is green.
2. Fix OPEN ISSUE #1 (live SSE path in a real browser) - it blocks real runs from showing in the UI.
3. Finish the Swarm Skill (OPEN ISSUE #2) until the official validator passes.
4. Ask me which API keys are now in .env, then follow "Once keys exist" in docs/HANDOVER.md.
```

---

## What is built (all pushed to `origin main`, 305 backend tests + 22 frontend tests passing as of Sat 12:20)

| Area | State | Where |
|---|---|---|
| Contracts | Pydantic schemas, event protocol, TS mirror, 125-event fictional mock run (generator + fixture) | `backend/app/schemas/`, `docs/events.md`, `frontend/lib/types.ts`, `backend/fixtures/make_mock_run.py` |
| Backend API | FastAPI: `POST /api/runs`, SSE `/api/runs/{id}/events` with `Last-Event-ID` resume, JSONL persistence = replay format, `/api/replay/{name}/events`, report, rescore, actions, health, slop-index | `backend/app/api/runs.py`, `app/main.py`, `app/core/` |
| Agents | conductor, 4 scouts (devpost, yc via Elasticsearch; github, hn live), resolver, critic, advocate, judge (jury + LLM-predictability), verifier (veto in code), synthesizer, mutator (re-scores), actuator | `backend/app/roles/` |
| Hosts | asyncio host **and** openjiuwen agent-core host (TeamRuntime P2P + session streaming). Same roles, event-parity tested. `ORCHESTRATOR=asyncio\|jiuwen` | `backend/app/orchestration/` |
| Messy-data (Rox) | live-source schema matching with provenance, blocking (URL xref + name trigrams), LLM adjudication with `insufficient_evidence`, union-find merge, field fusion with reliability priors, visible conflicts + imputed fields | `backend/app/wrangle/`, `roles/resolver.py` |
| Scoring | 3 axes + headline (weighted geometric mean), confidence, abstention rules; one similarity scale via the Jina reranker on EIS (lexical fallback labelled uncalibrated) | `backend/app/scoring/`, `docs/scoring.md` |
| LLM router | Baseten → OpenRouter fallback, token bucket, JSON-schema structured output with repair + one re-ask, cost table, `x-session-affinity` | `backend/app/llm/` |
| Elastic | mappings, ingest pipeline, 8 Agent Builder tools + 2 agents, 2 workflows, idempotent `apply.py` (`--check`, `--dry-run`) | `elastic/` |
| Ingest + search | tiered loaders (twangodev, alvanlii, YC), Devpost write-up parser, polite fetcher, EIS throughput measurer; hybrid search with degradation ladder, facet/pair rarity, whitespace finder, calibration CDF | `ingest/`, `backend/app/search/` |
| GPTZero + investigation | client with word ledger/cache/replay, bibliography-scan mapping, quote check, Slop Index pipeline (sample → scan → analyze → export) | `backend/app/signals/`, `investigation/` |
| Scripts | smokes for Elastic/Baseten/GPTZero (`--live` needed to spend GPTZero words), secret scan, benchmark ideas (Spearman), golden-run recorder, Baseten bake-off | `scripts/`, `baseten/bakeoff.py` |
| Frontend | Next.js 16 app, redesigned Sat evening: light minimal theme; landing (ambient islands hero); a run is six pages behind a bottom tab bar, `/runs/<id>` Map (3D floating-islands map in plain three.js: your idea at the centre, distance = 1 - similarity, one wedge per source, pop-in / merge / re-score drift, click for a detail card), `/evidence`, `/debate`, `/coach` (mutations + the three actions), `/report` (+ Voice as its own section), `/swarm` (roster, timeline, cost per model). One `RunProvider` in `app/runs/[id]/(tabs)/layout.tsx` streams the run once for all tabs; every in-run link must go through `hrefFor()` or `?replay=`/`?speed=` is lost and the run restarts. The old one-page dark dashboard is kept as the demo fallback at `/runs/<id>/classic`; `?map=2d` swaps the islands for the old 2D chart. Slop Index page (sample data labelled), About. Static replay works with no backend | `frontend/` (`components/run/`, `components/islands/`, `lib/islandLayout.ts`) |

**Elastic is LIVE (set up Sat ~16:00).** `.env` holds every key. A serverless 9.6.0 project on GCP `us-east4`
(general-purpose Elasticsearch, NOT the new "Vector Database" project type) has all 17 artifacts applied and
8,462 Tier 0 docs indexed; `bash scripts/smoke_elastic.sh` is 9/9 and hybrid retrieval returns HackAnalyzer /
Plagia / DevSpot in the top 5 in ~0.8s. **FORK/FUSE/RERANK works here**, so `originality.hybrid_prior_art` is
live and the `semantic_prior_art` fallback is not needed. **Still not run against a real LLM or GPTZero.**

## Verify the state

```bash
cd backend && .venv/bin/pytest -q -p no:warnings            # expect 305 passed, 3 skipped
cd backend && .venv-jiuwen/bin/pytest -q -p no:warnings tests/test_pipeline_offline.py   # expect 7 passed (openjiuwen host)
cd frontend && pnpm test && pnpm typecheck && pnpm lint      # expect 30 passed, clean
bash scripts/validate_swarm_skill.sh                         # official Swarm Skill validator: [PASS] 0 warning(s), 0 error(s)
backend/.venv/bin/python elastic/apply.py --dry-run          # 17-step plan, sends nothing
bash scripts/smoke_all.sh                                    # SKIPs without keys, exit 0
```
Dev servers: `.claude/launch.json` defines `frontend` (:3000) and `backend` (:8000). Recorded run: http://localhost:3000/runs/mock?speed=3

## Open issues, most important first

1. **Live SSE path — RESOLVED Sat 12:05.** Two separate things were tangled together. (i) *Real bug, fixed:* our event type `error` shares its name with `EventSource`'s native error event, so every server-sent `error` (the no-keys failure, the jiuwen-fallback warning, every recoverable degradation a role emits) also fired `es.onerror`; the client counted it as a dropped connection, stuck on "Reconnecting", and hung up for good after 8 of them. The mock fixture has no `error` events, which is why replays never showed it. Fix: `isServerMessage()` in `frontend/lib/sse.ts`; a run that ends without a report now shows a "Run failed" pill. (ii) *Not a bug:* "stays on Connecting" is what a page loaded in a **hidden** tab looks like — it does not hydrate until shown (reproduced in both the desktop Browser pane and real Chrome; zero requests reach the backend while hidden, and it streams normally the moment the tab is visible). The server was never at fault: `backend/tests/test_sse_stream.py` consumes the endpoint over a real socket (across sleeps, mid-stream hang-up, `Last-Event-ID` resume, live run). Verified in real Chrome: a 135-event recorded run containing 10 injected `error` events streamed to "Finished".
2. **Swarm Skill — DONE Sat 12:15.** `swarm-skill/prior-art-swarm/` is complete (SKILL.md, workflow.md, bind.md, dependencies.yaml, 8 role files, README, `scripts/workflow.py`) and the **official validator passes with 0 errors and 0 warnings**: `bash scripts/validate_swarm_skill.sh` (fetches the validator pinned to a commit + SHA-256 into git-ignored `data/`; exit 0 = PASS). Output is committed in `docs/sponsors/huawei.md`. bind.md numbers mirror the constants at the top of `scripts/workflow.py`: change both together. Not done: the skill has never been executed inside a JiuwenSwarm workspace.
3. **Frontend contract notes already fixed on the backend side** (eid on `evidence.found`, quotes on `claim.proposed`, `agent.finished` after retries); the mock fixture was regenerated — run `pnpm sync-replay` after any future fixture change.
4. `docs/PLAN.md` GPTZero budget: a 1,800-char write-up is ~290 words, so the full 8×150 scan (~350k words) exceeds the 230k cap → ask the booth for a bump or `scan --per-year 95`.
5. Not started: Browserbase evidence-browser agent (`backend/app/sources/browserbase.py`, `roles/scouts/browser.py`), alerts poller (`idea-alerts-v1` → SSE toast), fire-drill trigger endpoint, MCP tool use by scouts (design-full §1 "G4"), Truss surprisal (P2), `docs/sponsors/*.md` (huawei.md done), Devpost write-up (draft in `docs/devpost.md`; every TODO needs a real measurement), replay-only Vercel deploy + GoDaddy domain.
6. **`elastic/apply.py` had two bugs that reported success while deploying nothing — fixed Sat ~16:00, worth checking for the same shape elsewhere.** (i) The Kibana Workflows paths were stale: 9.6 serves `GET /api/workflows` (400s on unknown query params) and `POST /api/workflows` with `{"workflows":[{yaml}]}`, and that bulk create answers **200 with a `failed` array** rather than an error status, so the old code would have claimed success having deployed nothing; `/api/workflows/workflow` and `/api/workflows/search` now 404. (ii) Agent Builder ES|QL param `type` must be `string|integer|float|boolean|date|array` — `keyword`/`text` are mapping types and are rejected, so 6 of 8 tools failed and both agents were created with those tools silently stripped out. Default is now `string` and the retry tries every candidate. `workflows:ui:enabled` is ON by default on 9.6, so a 404 there means a wrong path, not a disabled feature.
7. **Transient network flakiness on this machine:** two consecutive `smoke_elastic.sh` runs failed with curl timeouts and `Could not resolve host`, then a third passed untouched with no changes. Re-run before debugging a failure, especially mid-demo.

## Once keys exist (user fills `.env` from `.env.example`)

1. ~~smoke → `apply.py --check` → `apply.py`~~ **DONE Sat ~16:00.** `.jina-embeddings-v3` (1024-dim) and `.jina-reranker-v3` both exist as assumed, so no `.env` change was needed. Two real bugs in `elastic/apply.py` were found and fixed on the way — see "Open issues" 6.
2. ~~`make ingest-tier0`~~ **DONE.** 8,462 docs (6,237 YC + 2,222 Devpost + 3 seeds), 0 failed / 0 quarantined / 0 429s, EIS at 97-145 docs/s. Canary returns DevSpot/HackAnalyzer/Plagia in the top 5. Still to do: `make measure` (EIS docs/s decides Tier 1 size) and `make search Q="..."` through the backend's own search path.
3. Start the backend, run a real idea end to end, fix prompt/latency issues, then `python scripts/bench_ideas.py --out docs/benchmarks.md` (pass = Spearman ≥ 0.8).
4. Overnight: `make ingest-tier1` (372 MB download, resumable, `caffeinate`), then `make ingest-tier2`, then `make calibrate`.
5. GPTZero: `bash scripts/smoke_gptzero.sh --live` (learn bibliography-scan entitlement + billing) → investigation pilot.
6. Baseten: verify the account (15 → 120 RPM), `python baseten/bakeoff.py`, then edit `backend/app/llm/models.py` from the results. OpenRouter slugs in `models.py` are a guess (`openai/gpt-oss-120b` for everything) — confirm.
7. Record golden runs early: `python scripts/record_golden.py <run_id> self` → replay at `/runs/self?replay=self`.

## Things only the user can do (unchanged)

Huawei credits (luma.com/mc7lijgs, first-come) · Baseten account + verification + promo code from Slack `#spons-baseten-2026` · ~~Elastic Cloud **Serverless** trial~~ (DONE) · GPTZero key · OpenRouter key · Browserbase key · Slack webhook · booth visits Sat 09:00–10:30 (Rox: separate write-up/deadline? Huawei: does agent-core + Swarm Skill count? GPTZero: word bump, bibliography-scan access; Baseten: training access, prompt logprobs; Elastic: EIS limits, reranker ID) · Devpost initial submission by 14:00 with all badge IDs.
