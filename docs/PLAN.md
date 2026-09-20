# S.L.O.P. — Similarity Lookup for Originality Prediction — Hack the North 2026 build plan

## Context

**What:** a multi-agent tool that tells you how original a hackathon/startup idea is — with receipts — and coaches you toward a more original version. Repo is greenfield: `/Users/enkailiu/Projects/htn-2026` is empty; remote `github.com/enkai-liu/htn-2026` is private and empty.

**Clock (EDT):** plan written Sat Sep 19 ~02:00. **Sat 14:00** = initial Devpost submission (team, badge IDs, sponsor prizes LOCKED). **Sun 08:00** = final submission. Sun 09:45–11:45 sponsor judging; main judging = 5-min **live demo** + Q&A (no slides). Criteria: originality, technical complexity, design, WOW. All code must be written at the event; public datasets/libraries are allowed.

**Your decisions:** 4 people · hackathon + startup ideas · FastAPI + Next.js · core tracks GPTZero, Baseten, Huawei openJiuwen, Rox, Elastic · add-ons GoDaddy, Browserbase, RBC (two of these changed after verification — see §2).

**Why this can win:** the only direct prior art (HackAnalyzer, HackHarvard 2023; DevSpot, HackPSU 2024) is keyword search over Devpost with an ungrounded LLM score, no advice, no visualization. Nobody has: semantic search over a 262k-project corpus, detection of "median-LLM" ideas, facet-swap coaching that is *re-scored against evidence*, an idea-space graph showing whitespace, or independently verified claims. Research backing to cite: Si et al. 2024 (LLM ideas lack diversity; LLMs are unreliable novelty judges → scores must be retrieval-grounded), Scideator (facet recombination), SciMON (iterative novelty loop).

---

## 1. Product

Input: an idea pitch (any length; Voice abstains under 250; optional Devpost/GitHub URL). Output: a live-streamed investigation, a 4-axis report, coached mutations, and actions.

Your two assessment families map to four axes (plus a confidence score that can abstain):

| Axis | Family | How it is computed | Sponsor tech |
|---|---|---|---|
| **1. Crowding** | similar ideas online | Hybrid retrieval over Devpost (262k) + YC (6.2k) + live HN/GitHub; reranker score of top resolved entities → percentile vs a 300-doc calibration set | Elastic, Jina |
| **2. Facet rarity** | text + corpus | Idea decomposed into facets (purpose, mechanism, audience, data, twist); per-facet and purpose×mechanism document frequency; cliché overlap via `significant_text` (neighbourhood vs whole corpus) | Elastic aggs / ES\|QL |
| **3. LLM-predictability** | text | Give 4 model families only the *problem + audience*, sample 12 ideas at T=1.0; does the crowd of LLMs independently propose your idea? (max cosine + hit-rate). Shown as a grey cloud in the graph | Baseten |
| **4. Voice** (separate, never in the headline) | text | GPTZero sentence-level AI detection on the pitch + "neighbourhood slop share". AI-probability ≠ unoriginality, so it is its own channel | GPTZero |
| **Confidence E** | — | source coverage, jury agreement, verified-claim share, canary queries. Low E → **"Insufficient evidence: <what's missing>"** instead of a number | Rox |

Headline `O = 100·(O1/100)^0.45·(O2/100)^0.35·(O3/100)^0.20`, band `±min(30, 8+40·jury_std)`. Full formulas + abstention rules → `docs/scoring.md`.

**Coaching:** the whitespace finder (tech/tags common globally but absent in your neighbourhood) seeds facet-swap mutations; each mutation is **re-scored by re-running retrieval** (~3–5 s), and its graph node visibly moves away from the cluster.

**Actions:** arm a recurring watch (Elastic Workflow re-searches and Slack-pings when new similar work appears), write the analyzed idea back into the corpus, draft a differentiated pitch.

**Hero demo:** run it on itself ("how original is an originality checker?" → finds DevSpot/HackAnalyzer/Plagia → click the mutation that became our design), then a generic "AI study buddy" pitch, then arm a watch.

---

## 2. Tracks — what each sponsor's judge sees

| Track | What we show (in their vocabulary) | Must-land by M2 (Sat 18:00) | Fallback |
|---|---|---|---|
| **Elastic** | ES is the context layer for every agent: messy write-ups → ingest pipeline (`html_strip`, `fingerprint`, `lang_ident`, quarantine index) → `semantic_text` with **Jina v3 on EIS** → BM25 + semantic via **RRF** → **Jina reranker**; originality maths native (`significant_text`, agg whitespace finder); **ES\|QL tools in Agent Builder served over MCP**; scheduled **Workflow** with `ai.agent` closes the loop | hybrid+rerank, significant_text, ≥3 Agent Builder tools | MCP flaky → scouts hit ES directly, tools stay for Kibana chat + workflow |
| **Rox** ($10k) | Data-wrangling agent in the taxonomy of their cofounder's paper (*Can Foundation Models Wrangle Your Data?*): **schema matching** (6 sources → 1 schema, mapping table shown), **entity matching** (Devpost↔GitHub↔HN↔YC → one entity; verdict `same/different/insufficient_evidence`), **error detection** (quarantine), **imputation** (visibly marked), conflicts resolved with source-reliability priors *and shown*, calibrated abstention, kill-a-source degradation, confidence-gated **actions**. Report ER precision/recall using `twangodev` Devpost→GitHub links as free ground truth | resolver + conflicts + abstention + 1 action | resolver = URL-xref + name rules, LLM only for top-5 pairs |
| **GPTZero** | Three integrations in the product — sentence-level Voice, neighbourhood slop share, and **bibliography-scan with veto power over our own agents' claims** (+ "fire drill": inject a labelled fake competitor, watch it get struck). Spec discipline: no deprecated fields, honour `should_mask`, 250-char gate, show `result_message` not raw probabilities | pitch scan + verifier layer 1 | bibliography-scan gated → local quote-in-source check gates claims; ask booth |
| **Baseten** | Inference as a **measurement instrument**: LLM-predictability across 4 model families; **jury whose disagreement drives re-planning**; committed **bake-off table** right-sizing a model per role; cost/latency meter; prefix caching + `x-session-affinity`; (P2) true surprisal from a base model we deploy with **Truss + vLLM** because shared Model APIs don't expose prompt logprobs | all LLM calls via Baseten router, bake-off, jury | 429s → token bucket + OpenRouter overflow |
| **Huawei openJiuwen** | Roles run on **`openjiuwen` agent-core** (their SDK under JiuwenSwarm): `TeamRuntime` P2P + pub/sub, `BaseTeam` streaming, MCP tools. Genuine collaboration: critic sends scouts back out, cross-family critic vs advocate, verifier veto enforced in code, jury split → targeted re-query, dynamic team formation (UI shows skipped scouts + why), failure reassignment. Reusability: validated **Swarm Skill** `prior-art-swarm/` | asyncio host running all roles; openjiuwen spike decided | jiuwen host not at parity by Sat 21:00 → demo on asyncio, show jiuwen on golden idea/recording |

Weights (Huawei issue #3067): collaboration 30 · scenario 25 · demo completeness 20 · implementation 15 · reusability 10.

### Add-ons (two corrections to what I told you earlier)
- **GoDaddy (MLH)** — keep. ~30 min: you register the domain with the MLH code; point it at the replay-only Vercel build. Do it after M3.
- **Browserbase ($2k)** — keep, **but reframed**. I verified Devpost's search endpoint sits behind an AWS WAF JS challenge (HTTP 202 even with a full browser UA). I don't recommend building a feature whose purpose is to defeat that bot-detection. Fresh 2025–26 projects come instead from pages Devpost serves normally (hackathon galleries + project pages return 200; `robots.txt` allows; `devpost.com/api/hackathons` is JSON). Browserbase's real job: an **evidence-browser agent** that renders the *live demo/product sites* of top prior-art entities (many are JS SPAs that plain HTTP can't read) → screenshot + extracted "what it does now" + status `alive/parked/dead/pivoted`. Feeds Rox conflict handling ("Devpost says live, site is dead") and puts screenshots on evidence cards. If a site shows a bot challenge → mark `blocked`, never evade. P2, 2.5 h hard cap.
- **RBC — recommend NOT opting in.** I probed their MCP server (`http://3.143.20.160/mcp`): it exposes one tool, `financialDataRetrieval`, and the challenge is a two-phase Q&A accuracy benchmark on RBC's financial research data (Phase 2 = surprise datasets). That is a different project, not a near-free add-on. If you still want it: P2 "second-corpus adapter" reusing our cite-or-abstain + verifier engine (doubles as a Huawei reusability demo), 3 h cap, start only if M2 is green. **Decide at 13:30.**

---

## 3. Architecture

```
Next.js ──POST /api/runs──▶ FastAPI ──▶ Host (jiuwen | asyncio) ──▶ Roles
   ▲── SSE /api/runs/{id}/events ◀── EventBus (+ runs/{id}.jsonl = replay source)
Roles ─▶ search/   ES client: retrievers + aggs      ─▶ Elastic Cloud Serverless (prior-art-v1; EIS Jina embed + rerank)
      ─▶ MCP       openjiuwen McpServerConfig         ─▶ Agent Builder tools (ES|QL, index_search, workflow tool)
      ─▶ sources/  HN Algolia · GitHub · arXiv · Devpost pages · (Browserbase evidence browser)
      ─▶ llm/router  Baseten ─fallback▶ OpenRouter (Huawei credits)
      ─▶ signals/  GPTZero · prior-collision · jury · (Truss surprisal)
      ─▶ actions/  Kibana Workflows API · ES write-back · pitch draft
Workflow (scheduled) ─▶ idea-alerts-v1 ─▶ backend poller ─▶ SSE toast ; ─▶ Slack webhook
```

**Design rules**
1. **Roles are host-agnostic.** They implement `Role.handle(msg, ctx)` against a `Ctx` protocol (`send`, `publish`, `emit`, `board`, `budget`) and never import openjiuwen. Two hosts implement `Ctx`: `asyncio_host.py` (built first, always works) and `jiuwen_host.py` (`CommunicableAgent` + `BaseTeam` + `Runner.run_agent_team_streaming`). One env flag `ORCHESTRATOR=asyncio|jiuwen`.
2. **The event contract comes first.** `AgentEvent` (seq, run_id, agent, phase, type, data, model, latency, tokens, cost) is the single SSE payload and the JSONL replay format. Frontend builds against `fixtures/mock_run.jsonl` from hour 1. Replay mode = demo insurance.
3. **Deterministic scoring path hits ES directly; agentic exploration goes through Agent Builder MCP tools** (critic follow-ups, analytics, arm-watch).
4. **Verification is async and two-layer:** (1) deterministic quote-appears-in-fetched-page; (2) GPTZero bibliography-scan on claims + formatted citations `[n] Org. "Title." Site. Year. URL.` Badges flip live; the report never waits. Only status `fake` hard-rejects.
5. **AI-written Devpost evidence is badged, not discarded** (it's still a real project). Only open-web pages that are `AI_ONLY` + `high` confidence are dropped.
6. **A watch is one document** in `idea-watches-v1`; a single scheduled workflow iterates all watches and writes `idea-alerts-v1` (no tunnel to localhost needed).
7. **Every degradation is a visible event** (`source.failed`, budget exceeded, juror dropped, reranker down → "uncalibrated").

**Agents** (model = starting point; the bake-off decides)

| Role | Authority | Model |
|---|---|---|
| `conductor` | extracts facets, forms team dynamically, budget (≤70 calls/150k tok/90 s), reassigns on failure | GLM-5.3-Flash |
| `scout.devpost`, `scout.yc` | ES hybrid (up to 5 concurrent queries: full idea · purpose+mechanism · twist · problem only · hypothetical write-up), MCP tools | DeepSeek-V4-Flash |
| `scout.github`, `scout.hn`, `scout.web` (Exa; needs `EXA_API_KEY`) (+arXiv: P2) | live APIs, broaden-and-retry on 0 hits | same |
| `resolver` | **only role that writes entities**: schema match → blocking (URL xref, `dedupe_key`, name trigram ≥0.6) → LLM adjudication → union-find → field fusion with reliability priors → conflicts, imputation | DeepSeek-V4-Flash, 8 pairs/call |
| `critic` | "exists" claims with quotes; **may send scouts back out** (≤2 `REQUEST_EVIDENCE`) | DeepSeek-V4-Pro |
| `advocate` | must concede, distinguish by facet, or challenge evidence; different model family | GLM-5.3 |
| `judge` | 3–4 family jury (N separate requests; `n` is capped at 1); split → `REPLAN` on that pair only | Flash models + gpt-oss-120b |
| `verifier` | quote check + GPTZero; **holds a veto** | — |
| `synthesizer` | input restricted in code to `verified` / `unverified_lead` claims | GLM-5.3 |
| `mutator` | swaps seeded by whitespace candidates; triggers re-score | Kimi-K2.6, T=1.0 |
| `actuator` | picks actions by confidence; outside-world actions need a user click | GLM-5.3-Flash |

**Elastic spine** (exact JSON/YAML for mapping, pipeline, tools, workflows is in the full design doc — §7)
- Index `prior-art-v1`: `rid, source, url, title, tagline, description, pitch, semantic_pitch(semantic_text → .jina-embeddings-v3), year, date, hackathon, tags, tech, is_winner, status, traction, field_provenance, lang, dedupe_key, quality_flags, gptzero.*, nn_sim, first_seen_at`. `pitch` = title + tagline + "What it does" (Devpost's standard headings parsed client-side), capped 1,500 chars — one short field bounds EIS cost and feeds BM25, rerank, `significant_text`, and the embedding.
- Hybrid query: `text_similarity_reranker(.jina-reranker-v3, field=pitch, inference_text=<full idea>, window 40)` ⟵ `rrf(window 100, k=20)` ⟵ [`multi_match(title^3, tagline^2, pitch)`, `semantic(semantic_pitch)`], filter out `too_short`/`non_english`.
- Two-step `significant_text`: collect top-50 neighbour `_id`s → `ids` query + `significant_text(pitch, filter_duplicate_text)` + `significant_terms(tags)` + `terms(year)`; background = whole index.
- Agent Builder ES|QL tools: `hybrid_prior_art` (FORK/FUSE/RERANK, with plain-semantic fallback), `crowding_by_year`, `cliche_tags`, `combination_rarity`; `index_search` tool; workflow tool `arm_watch`. Agents: `prior-art-analyst`, `watch-analyst`. All applied idempotently by `elastic/apply.py`.
- **Corpus tiers** (EIS throughput unknown → measure first): Tier 0 by ~03:30 = `twangodev/devpost-hacks` (2.2k, 2024–26, with READMEs) + YC 6.2k + seeded DevSpot/HackAnalyzer/Plagia. Measure EIS on 1k docs. Tier 1 overnight = ≤40k `alvanlii` rows with semantic (winners first, newest first; `_id=rid`, checkpointed, `caffeinate`). Tier 2 = remaining ~215k BM25-only (minutes), then semantic backfill. Ladder if slow: shorter pitch → own Jina key → BM25 + rerank only.

**GPTZero word budget** (~500k assumed; read `/v3/usage-stats` in hour 0): interactive 120k. Ledger enforces the cap; `GPTZERO_MODE=replay` by default so dev burns nothing; results cached by sha256 and written back to ES docs as `gptzero.*`.

---

## 4. Repo layout

```
README.md  Makefile  .env.example  .gitignore  .python-version (3.12)
backend/pyproject.toml            # fastapi uvicorn sse-starlette httpx openai elasticsearch>=9 pydantic>=2 tenacity json-repair numpy pyarrow openjiuwen==0.1.18
backend/app/{main,config}.py
backend/app/api/{runs,replay,admin}.py
backend/app/schemas/{records,entities,claims,messages,events,report}.py
backend/app/core/{blackboard,eventbus,budget,runstore}.py
backend/app/llm/{router,models,structured,cost}.py  + prompts/*.md
backend/app/orchestration/{host,asyncio_host,jiuwen_host,registry}.py
backend/app/roles/{conductor,resolver,critic,advocate,judge,verifier,synthesizer,mutator,actuator}.py + scouts/{base,devpost,yc,github,hn,arxiv,browser}.py
backend/app/search/{es,hybrid,rarity,whitespace,calibration,mcp_tools}.py
backend/app/sources/{hn,github,arxiv,devpost_page,browserbase}.py
backend/app/wrangle/{schema_map,blocking,adjudicate,fuse,reliability,impute}.py
backend/app/signals/{gptzero,gptzero_budget,biblio,quote_check,prior_collision,jury,surprisal}.py
backend/app/{scoring,actions,graph}/…     backend/tests/…     backend/fixtures/{mock_run.jsonl,golden/,gptzero/,calibration/}
frontend/app/{page,runs/[id]/page,about/page}.tsx
frontend/components/{IdeaInput,SwarmTimeline,DebateThread,EvidenceCard,EvidenceLedger,AxisGauges,PitchHighlighter,IdeaGraph,MutationPanel,ActionBar,CostMeter}.tsx
frontend/lib/{sse,types,graphReducer,replay}.ts
ingest/{download_hf,parse_sections,load_devpost_hf,load_devpost_recent,load_yc,scrape_galleries,seed_known_prior_art,measure_eis,backfill_semantic}.py
elastic/{mappings/,pipelines/,queries/,agent-builder/{tools,agents}/,workflows/{arm-watch,watch-recheck}.yaml,apply.py}
swarm-skill/prior-art-swarm/{SKILL.md (kind: swarm-skill, per the official validator),roles/*.md,workflow.md,bind.md,dependencies.yaml,scripts/workflow.py}
baseten/{bakeoff.py,reference_distribution.py,surprisal-truss/config.yaml}
scripts/{smoke_all,smoke_elastic,smoke_baseten,smoke_gptzero,secret_scan}.sh  scripts/{bench_ideas,record_golden}.py
docs/{PLAN,design-full,architecture,events,scoring,benchmarks,demo-script,devpost}.md  docs/sponsors/*.md  docs/research/*.md
```
Frontend: Next.js App Router + Tailwind + shadcn/ui + `react-force-graph-2d` + Recharts. Backend venv: `/usr/local/bin/python3.12 -m venv backend/.venv` (verified present; system 3.14 is too new for openjiuwen `<3.14`).

---

## 5. Lanes, schedule, cut lines

**Lanes:** **P1 Spine** (Elastic, ingest, search, Agent Builder, Workflows) · **P2 Swarm** (hosts, roles, resolver, debate, Huawei) · **P3 Face** (all UI, replay, deploy, domain) · **P4 Signals** (GPTZero, Baseten instruments, booths, Devpost text, Browserbase).

| Time (EDT) | P1 Spine | P2 Swarm | P3 Face | P4 Signals |
|---|---|---|---|---|
| 02:00–02:45 | **Hour 0, all hands** — accounts/keys/credits (§6), scaffold pushed, HF dataset download started | | | |
| 02:45–05:00 | mapping + pipeline, Tier 0, `measure_eis`, launch Tier 1/2, `hybrid.py` CLI | openjiuwen spike G1–G3 (**decide 03:30**), LLM router, asyncio host, eventbus | `docs/events.md` + `mock_run.jsonl`, Next skeleton, SSE hook, timeline from mock | GPTZero client + ledger + replay, `sample.py`, pilot scan 4 yrs × 50 |
| **05:00 M0** | ≥8k docs searchable · smokes green · mock stream renders | | | |
| 05:00–08:45 | **Sleep.** Ingest + capped scan run under `caffeinate` | | | |
| 09:00–13:30 | seeds, devpost/yc scouts, calibration, `significant_text`, **Elastic booth** | planner, HN/GitHub scouts, minimal synthesizer with citations, `/api/runs` SSE, **Huawei booth** | evidence cards, gauges, highlighter on the real stream | **GPTZero, Baseten, Rox, Browserbase booths**, bake-off, scan phase 1 |
| **13:30 M1** | one real end-to-end run on 2 ideas → **13:30–14:00 Devpost initial submission, lock prizes** | | | |
| 14:00–18:00 | ES\|QL tools + agents, MCP G4 by 16:00, whitespace finder, `apply.py` | resolver, critic/advocate + re-query, judge, blackboard perms, jiuwen host parity | IdeaGraph + `graphReducer`, DebateThread, EvidenceLedger | two-layer verifier, slop share + write-back |
| **18:00 M2** | dinner → run the benchmark ideas, fix ordering | | | |
| 19:00–23:00 | Workflows + Slack + poller, gallery scraper, combination rarity | mutator + re-score, actuator, budget degradation, **jiuwen parity check 21:00** | MutationPanel + graph animation, ActionBar, CostMeter | prior-collision + cloud nodes, fire drill, Browserbase evidence browser (2.5 h cap), Devpost draft |
| **23:00 M3** | **FEATURE FREEZE** | | | |
| 23:00–02:00 | latency/caching, `/about` with live corpus count, README | Swarm Skill + official validator, JiuwenSwarm recording (90 min cap) | replay mode + golden runs, polish, replay-only Vercel build + GoDaddy domain | Truss surprisal (cut at 01:00), public CSV, sponsor docs |
| **02:00 M4** | record backup video 02:00–03:00 while everything works | | | |
| 03:00–06:30 | staggered sleep; awake pair writes Devpost text, runs `secret_scan.sh`, makes repo public | | | |
| 06:30–07:15 | final checks · **SUBMIT by 07:15** (buffer to 08:00) | | | |
| 08:00–09:45 | rehearse ×3, sponsor 60-second pitches, second laptop, hotspot | | | |

**Cut lines**

| Checkpoint | If behind |
|---|---|
| M0 | EIS <20 docs/s → cap Tier 1 at 25k. Spike red → asyncio primary; one 45-min retry at 09:00, final call 10:30 |
| M1 | drop arXiv, Browserbase, RBC; defer MCP |
| M2 | cut advocate; 2-model jury; resolver = URL-xref + name rules (LLM for top-5 pairs); static graph |
| M3 | cut chaos toggle, cloud nodes, Truss, JiuwenSwarm recording, write-back |
| M4 | jiuwen host not at parity → asyncio for every live demo |

**Cut outright:** Baseten Training/distillation (booth-gated, weak label, 3 h+) — still ask the booth to enable access, asking is free.

---

## 6. Hour 0 checklist, booths, before 14:00

**Hour 0 (you/teammates — I can't create accounts or enter credentials; I'll provide `.env.example` + smoke scripts):**
1. **Huawei credits first** (200 keys, first-come): luma.com/mc7lijgs → $40 OpenRouter key by email.
2. **Baseten:** account → **verify it** (15 → 120 RPM) → redeem code from Slack `#spons-baseten-2026` (workspace owner redeems once) → API key. Probe `/v1/models` and the `logprobs`/`prompt_logprobs` passthrough.
3. **GPTZero:** API key (app.gptzero.me/app/api) → `/v3/usage-stats` → one `/v2/predict/text` → one `/v2/bibliography-scan/text` → re-read usage to learn the billing delta.
4. **Elastic:** Cloud **Serverless** Elasticsearch trial (no card) → API key → `GET _inference/_all` (real Jina endpoint IDs) → enable `workflows:ui:enabled` → confirm Agent Builder visible.
5. OpenRouter account (fallback), `GITHUB_TOKEN` from `gh auth token`, Slack incoming webhook, Browserbase key.

**Booths Sat 09:00–10:30** — **Rox:** separate write-up/submission channel and deadline? (TreeHacks required an emailed write-up within 2 h.) **Huawei:** does "openjiuwen agent-core + validated Swarm Skill" count as "on top of JiuwenSwarm/WorkSwarm"? **GPTZero:** bibliography-scan entitlement/billing, AI-patterns allow-listing, does it verify non-academic URLs? **Baseten:** training access, `prompt_logprobs`, rate-limit form. **Elastic:** workshop/starter, EIS limits on trial, recommended reranker ID, FORK/FUSE/RERANK on Serverless, workflow-tool JSON. **Browserbase:** hackathon credits.

**Before 14:00:** smokes green · orchestration decision settled · Rox + Huawei answers written down · Devpost draft with all badge IDs · opt into: Rox, GPTZero, Elastic, Huawei, Baseten, Browserbase, GoDaddy (+RBC only if you decide so at 13:30).

---

## 7. Execution order for this Claude session (on approval)

1. `git init -b main`, add remote, `.gitignore` (`.env`, venvs, data/), `.env.example`, `Makefile`, README stub. Save this plan → `docs/PLAN.md`, the full design (exact mapping/pipeline/tool/workflow JSON+YAML, openjiuwen host sketch, scoring, demo script) → `docs/design-full.md`, and the three research reports → `docs/research/`. First commit; **push to `origin main`** (your private repo) so teammates can pull and start their lanes.
2. **Contracts:** `backend/app/schemas/*.py`, `docs/events.md`, `backend/fixtures/mock_run.jsonl`, `frontend/lib/types.ts`.
3. **Smoke scripts** for Elastic, Baseten, GPTZero (`scripts/smoke_*.sh`) so Hour-0 keys are validated the moment they land in `.env`.
4. **Backend skeleton:** py3.12 venv, FastAPI + SSE + JSONL replay, eventbus, blackboard, budget, asyncio host, LLM router (Baseten → OpenRouter), stub conductor that emits the mock flow.
5. **Elastic + ingest:** mappings, pipeline, `elastic/apply.py`; `download_hf`, `parse_sections`, `load_devpost_recent` (Tier 0), `load_yc`, `seed_known_prior_art`, `measure_eis`, tiered `load_devpost_hf`; `search/hybrid.py` with a CLI.
6. **Frontend skeleton:** Next.js app, SSE hook, SwarmTimeline + IdeaGraph rendering the mock stream.
7. Then continue down **P1 Spine** by default (it unblocks everyone), or whichever lane you assign me. Independent scaffolds get parallelized with subagents. Small, frequent commits (history proves the code was written at the event).

Source material already on disk: full design → session scratchpad `design_part{1,2,3}.md` and `~/.claude/projects/-Users-enkailiu-Projects-htn-2026/2946e537-…/tool-results/toolu_01VY2Ag1sVDTsomsbao7UQ1k.json`; research → `toolu_01MdDx4rcW6BDgE2wCRbd8N8.json` (GPTZero/Baseten), `toolu_01Wqw8rkqKs4aFGod912TmJE.json` (openJiuwen/Elastic/Rox).

---

## 8. Top risks → fallbacks

| Risk | Fallback |
|---|---|
| EIS embedding slow/expensive | tiering; shorter `pitch`; own Jina key via `jinaai` service; BM25 + rerank only |
| Jina endpoint IDs differ | IDs live in config, read from `_inference/_all`; reranker v2-multilingual or RRF-only |
| Agent Builder MCP / Workflow step-schema quirks | direct ES on the critical path; validate YAML via `POST /api/workflows/test`; actuator chain: MCP tool → Workflows run API → direct index |
| openjiuwen re-entrancy/timeouts/dep conflicts (86 deps) | explicit timeouts (`configure_timeout(300)`); separate venv/process; asyncio host |
| GPTZero bibliography-scan gated, or `unknown` on non-academic URLs | local quote check gates claims; only `fake` rejects; booth |
| GPTZero quota | ledger caps, replay mode, smaller sample, booth bump |
| No prompt logprobs on Baseten Model APIs (docs: `echo` ≠ prompt logprobs) | LLM-predictability is the headline instrument; Truss surprisal stays P2 |
| Baseten 429s / reasoning-model latency | token bucket at 100 RPM, low-reasoning slugs from bake-off, OpenRouter overflow |
| Conference wifi / live demo failure | hotspot; `?replay=self` golden runs at 1.5×; replay-only Vercel site; backup video |
| Secrets leak when repo goes public | `.env` ignored; `secret_scan.sh` before flipping visibility; rotate on any hit |
| Judge honesty challenges | Voice is a separate axis; report placebo FPR; aggregates only; simulated items labelled; dataset licences attributed in README |

---

## 9. Verification

- **Smokes:** `scripts/smoke_all.sh` = Hour-0 curls + `apply.py --check` + a hybrid query for "validate hackathon idea originality" that must return **DevSpot** in the top 5. Run before every demo.
- **Pytest:** scoring monotonicity + abstention rules; schema maps (3 fixtures/source); blocking recall on `twangodev` Devpost→GitHub pairs; every event in `mock_run.jsonl`/golden files validates as `AgentEvent`; hybrid body shape; GPTZero parsing never mixes sentence-level `paraphrased` with document-level `mixed`.
- **Benchmark ideas** (`scripts/bench_ideas.py`): 8 pitches from cliché (RAG study buddy, fridge→recipes, AI journaling therapist) to novel (tactile display of forecast uncertainty for blind users). Pass = Spearman ρ ≥ 0.8 vs expected order; plus "Uber for dogs" (<250 chars → Voice abstains) and a Spanish pitch (language flagged).
- **Behavioural checks each run:** mutations raise Crowding score on the cliché ideas; killing GitHub lowers confidence without crashing; the fire-drill fake citation is rejected; 3 concurrent runs stay under 120 RPM with zero unhandled 429s.
- **Host parity:** same idea under `ORCHESTRATOR=asyncio|jiuwen` → same event-type multiset, axis scores within tolerance.
- **UI:** drive the frontend in the browser pane against `mock_run.jsonl`, then a live run; verify replay URLs offline.
- **Swarm Skill:** official `validate_swarmskill.py swarm-skill/prior-art-swarm` passes; output committed to `docs/sponsors/huawei.md`.
