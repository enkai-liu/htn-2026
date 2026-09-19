> Generated during planning (Sat 2026-09-19 ~01:30 EDT). `[V]`/**[VERIFIED]** = checked against a live source; `[T]`/**[INFERRED]** = must be tested by the team.

# Hack the North 2026 Build Plan: Multi-Agent Idea-Originality Checker

Working title: **Whitespace**. Three interfaces are verified and the rest is a plan. `[V]` marks what I checked tonight against a live source. `[T]` marks what your team must test, with the hour to do it.

## 0. Corrections to your brief

| # | Finding | Consequence |
|---|---|---|
| 1 | `[V]` The machine already has `/opt/homebrew/bin/python3.11` (3.11.15), `/usr/local/bin/python3.12` (3.12.8) and `/opt/homebrew/bin/python3.13`, all arm64. `uv` is missing. | Skip the interpreter install. Run `/usr/local/bin/python3.12 -m venv backend/.venv`. |
| 2 | `[V]` Baseten's `echo` means "prepends that message to the output". It does not return prompt-token logprobs, and `prompt_logprobs` is undocumented for Model APIs. | Surprisal needs a Truss + vLLM deployment, unless a 2-minute passthrough probe works. The primary Baseten instrument becomes LLM-prior collision (section 2.9), which needs no logprobs. |
| 3 | `[V]` `openjiuwen` (agent-core) is an embeddable library with real multi-agent primitives. JiuwenSwarm `develop` is already renamed `workswarm 0.2.5.beta1` and pins `openjiuwen @ git+…agent-core@d0bd833…`. | Option (a) is viable. It is building on the engine under JiuwenSwarm. |
| 4 | `[V]` Swarm Skill `kind` must be `team-skill` for JiuwenSwarm. agent-core's own spec says `swarm-skill`. `validate_swarmskill.py` imports only the standard library, so it runs standalone. | Use `team-skill`. Run the validator without installing JiuwenSwarm. |
| 5 | `[V]` Full Huawei weights: Collaboration 30%, Scenario Value and Creativity 25%, Demo Completeness 20%, Technical Implementation 15%, Reusability 10%. | Demo completeness outweighs reusability. |
| 6 | `[V]` The eligibility text says "on top of JiuwenSwarm or WorkSwarm" or a Swarm Skill "with a working demonstration". Elsewhere it allows "another multi-agent framework". | This is ambiguous. Ask the booth and ship the Swarm Skill as insurance. |
| 7 | `[V]` Devpost returns 403 only for the bare UA `Mozilla/5.0`. A full Chrome UA or the default UA returns 200 for galleries and project pages. `devpost.com/api/hackathons` returns JSON. | Fresh 2025-26 data is scrapeable without Browserbase. |
| 8 | `[V]` `hackathons.json` (9 MB) in the HF repo has `submission_period_dates` such as "Oct 01 - Dec 04, 2024". | This gives the year join for the Slop Index. |
| 9 | `[V]` `twangodev/devpost-hacks` needs config `all`. It covers 2024-2026 (TreeHacks 2024/25/26, CalHacks 12, HackGT 12, PennApps XXV, Hacktech 2026, MadHacks) and includes `other_links` and `readmes`. | It doubles as Devpost-to-GitHub entity-resolution ground truth. |
| 10 | `[V]` Elastic Workflows have a Kibana API: `POST /api/workflows/workflow` with `{id?, yaml}`, `POST /api/workflows/workflow/{id}/run` with `{inputs}`, `GET …/executions`, and `POST /api/workflows/test`. | Workflows can be deployed from the repo. |
| 11 | `[V]` DevSpot is in the HF dataset (hackathon_id 20679). The same search surfaced "Plagia: A plagiarism detector for hackers". `devpost.com/software/hackanalyzer` and `/devspot` both return 200. | Seed the hero-demo prior art explicitly. |
| 12 | EIS rate limits are undocumented. | Measure them in hour 1 (section 2.4). |

### Four changes to your concept
- **LLM-predictability becomes a first-class axis.** Given only your problem statement, do models independently propose your idea? This axis is about the idea, not the phrasing. It operationalizes Si et al., draws well as a grey cloud in the graph, and survives the `echo` finding.
- **Do not discard AI-written Devpost evidence.** An AI-written write-up is still a real project. Badge it and compute a **neighbourhood slop share** (how much of your competition is AI-written). Discard only open-web pages that are `AI_ONLY` with `high` confidence.
- **"Arm a watch" means indexing one document into `idea-watches-v1`.** A single static scheduled workflow iterates over all watches. Alerts are pulled from `idea-alerts-v1`, so no tunnel to localhost is needed.
- **Verification runs asynchronously in two layers.** Layer 1 is a deterministic check that the quote appears in the fetched page. Layer 2 is GPTZero bibliography-scan. Claims change badge state live, and the report never waits on the scan.

## 1. Orchestration decision

| | (a) embed `openjiuwen` | (b) JiuwenSwarm app + SwarmFlow via SDK | (c) own asyncio + Swarm Skill |
|---|---|---|---|
| Shape | Library. 7 MB wheel, 86 deps, in-process. | App. 20-26 MB, child-process SDK with no retries, config in `~`, tool-approval prompts. | No dependencies. |
| Primitives `[V]` | `TeamRuntime` (P2P `send`, pub/sub with `*` and `?` wildcards). `BaseTeam`. `CommunicableAgent`. `HierarchicalTeam` plus `SupervisorAgent.create(max_parallel_sub_agents=…)`. `HandoffTeam` (`transfer_to_*`). Agent-as-Tool. `ReActAgent`. `@tool`. `McpServerConfig(client_type="streamable-http", auth_headers=…)`. | LLM Leader plus isolated `agent()` calls. "Communication" is Python variables. | Homemade. |
| Streaming | `session.write_stream(dict)` feeds `Runner.run_agent_team_streaming(..., base=True)`. Chunks carry `source_agent_id`. | `on_event` over pipes. | Native. |
| Demo reliability | Good. | Poor. | Best. |
| Huawei optics | Strong, because it is their SDK. | Strongest on paper. | Weakest. |

**Recommendation: build (a), with roles written host-agnostically.**
- Roles share code between an openjiuwen host and an asyncio host, selected by one environment flag.
- Ship the Swarm Skill from (c), validated by the official script.
- Add a 90-minute mini-(b): run the skill inside JiuwenSwarm once and screen-record it.

Driving (b) live is ruled out because it puts the least mature dependency on the demo path. Its collaboration story is also weaker than a real message bus.

### Spike for P2 (75 minutes, start 01:45)
- **G1, 15 min:** the `examples/multi_agent/runtime_hybrid.py` pattern runs with no LLM.
- **G2, 20 min:** `Runner.run_agent_team_streaming(..., base=True)` plus `write_stream` feeds an `asyncio.Queue` and then SSE.
  - Test two concurrent `send`s to one recipient (re-entrancy).
  - Test a 60-second handler. Default `message_timeout` is 30 s, so set `.configure_timeout(300)` and pass `timeout=` explicitly.
- **G3, 20 min:** a `ReActAgent` makes one tool round-trip against Baseten.
  - Use `ModelClientConfig(client_provider="OpenAI", api_base="https://inference.baseten.co/v1", …)`.
  - Add one `@tool`.
  - Repeat with provider `"OpenRouter"`.
- **G4, 20 min, can slip to Sat 16:00:** connect to Agent Builder over MCP.
  - Use `McpServerConfig(client_type="streamable-http", server_path=f"{KIBANA_URL}/api/agent_builder/mcp", auth_headers={"Authorization": f"ApiKey {KEY}"})`.
  - Then call `Runner.resource_mgr.add_mcp_server(...)` and `agent.ability_manager.add(cfg)`.

### Fallback triggers
- **G1-G3 not green by 03:15:** asyncio becomes primary. Make one 45-minute retry at 09:00. Final call is 10:30 Sat.
- **G4 not green by 16:00:** scouts query Elasticsearch directly. The tools stay registered for Kibana chat and the workflow.
- **Parity at 21:00:** `ORCHESTRATOR=jiuwen` must complete 3 benchmark ideas without hangs.
  - Otherwise the demo defaults to asyncio.
  - Show the jiuwen host to Huawei only on the golden idea, or as a recording.
- **Dependency conflict with openjiuwen's heavy dependencies:** move the jiuwen host into its own venv and process. Cap this at 45 minutes.

### Sketch
Names are taken from the v0.1.18 tag, which matches PyPI 0.1.18.

```python
# backend/app/orchestration/host.py: roles never import openjiuwen
class Ctx(Protocol):
    run_id: str; board: "Blackboard"; budget: "Budget"
    async def send(self, to: str, msg: dict, timeout: float = 120) -> dict: ...
    async def publish(self, topic: str, msg: dict) -> None: ...
    async def emit(self, type: str, **data) -> None: ...   # AgentEvent -> SSE + JSONL
class Role(Protocol):
    id: str; purpose: str; subscriptions: list[str]
    async def handle(self, msg: dict, ctx: Ctx) -> dict: ...

# backend/app/orchestration/jiuwen_host.py
from openjiuwen.core.multi_agent import BaseTeam, TeamCard, TeamConfig
from openjiuwen.core.multi_agent.team_runtime import CommunicableAgent
from openjiuwen.core.single_agent.base import BaseAgent
from openjiuwen.core.single_agent.schema.agent_card import AgentCard
from openjiuwen.core.runner import Runner

class RoleAgent(CommunicableAgent, BaseAgent):
    def __init__(self, card, role, board):
        super().__init__(card=card); self.role, self.board = role, board
    def configure(self, config): return self
    async def invoke(self, inputs, session=None):
        return await self.role.handle(inputs, JiuwenCtx(self, session, self.board))
    async def stream(self, inputs, session=None):
        await self.invoke(inputs, session)
        if False: yield None

class JiuwenCtx:
    def __init__(s, agent, session, board):
        s.a, s.sess, s.board = agent, session, board
        s.sid = session.get_session_id() if session else None
    async def send(s, to, msg, timeout=120):
        return await s.a.send(message=msg, recipient=to, session_id=s.sid, timeout=timeout)
    async def publish(s, topic, msg):
        await s.a.publish(message=msg, topic_id=topic, session_id=s.sid)
    async def emit(s, type, **d):
        await s.sess.write_stream({"type": type, "agent": s.a.agent_id, **d})

class OriginalityTeam(BaseTeam):
    def __init__(self, card, config, roles, board):
        super().__init__(card=card, config=config); self.roles = roles
        for rid, role in roles.items():        # Card + Provider is lazy, which gives dynamic team formation
            c = AgentCard(id=rid, name=rid, description=role.purpose)
            self.add_agent(c, (lambda c=c, r=role: RoleAgent(c, r, board)))
    async def _run(self, message, session):
        await self.runtime.start()
        try:
            for rid, r in self.roles.items():
                for t in r.subscriptions: await self.subscribe(rid, t)
            return await self.runtime.send(message=message, recipient="conductor", sender="user",
                                           session_id=session.get_session_id(), timeout=300)
        finally: await self.runtime.stop()
    async def invoke(self, message, session=None): return await self._run(message, session)
    async def stream(self, message, session=None):
        async def go():
            try: await self._run(message, session)
            finally: await session.close_stream()
        t = asyncio.create_task(go())
        try:
            async for chunk in session.stream_iterator(): yield chunk
        finally: await t

# FastAPI: lifespan calls Runner.start() / Runner.stop(). Per run:
team = OriginalityTeam(TeamCard(id=f"orig-{run_id}", name="originality_team", description="prior-art swarm"),
                       TeamConfig().configure_max_agents(16).configure_timeout(300.0).configure_concurrency(200),
                       roles, board)
await Runner.resource_mgr.add_agent_team(team.card, lambda: team)
async for chunk in Runner.run_agent_team_streaming(agent_team=team.card.id, inputs={"idea": text}, base=True):
    yield sse(getattr(chunk, "payload", chunk))
await Runner.resource_mgr.remove_agent_team(team_id=team.card.id)
```

The asyncio host implements the same `Ctx` with a dictionary of roles. `send` awaits `role.handle` under `wait_for`.

## 2. Architecture

```
Next.js --POST /api/runs--> FastAPI --> Host(jiuwen|asyncio) --> Roles
   ^-- SSE /api/runs/{id}/events <-- EventBus (+ runs/{id}.jsonl, also the replay source)
Roles -> search/    ES client: retrievers + aggs        -> Elastic Serverless (prior-art-v1, EIS Jina embed + rerank)
      -> MCP        openjiuwen McpServerConfig          -> Agent Builder tools (ES|QL, index_search, workflow tool)
      -> sources/   HN Algolia, GitHub, arXiv, Exa(optional)
      -> llm/router Baseten, falling back to OpenRouter
      -> signals/   GPTZero, prior-collision, Truss surprisal
      -> actions/   Kibana Workflows API, ES write-back
Workflow(scheduled) -> idea-alerts-v1 -> backend poller -> SSE toast ; -> Slack webhook (outbound from Elastic)
ingest/ -> pipeline prior-art-clean -> prior-art-v1 | prior-art-quarantine
investigation/ -> GPTZero batch -> parquet + write-back gptzero.* -> /slop-index
```

### 2.1 Priorities
- **P0:** corpus with hybrid search and rerank. Planner, 4 scouts and synthesizer with citations. SSE UI. Crowding percentile. GPTZero pitch scan. Replay mode.
- **P1:** resolver. Critic, advocate and judge with re-query. jiuwen host and Swarm Skill. `significant_text` and the whitespace finder. Agent Builder and MCP. Workflows. Bibliography verification. The investigation. Mutations with re-score and graph. Prior-collision. Cost meter.
- **P2:** Truss surprisal. Chaos toggle. JiuwenSwarm recording. arXiv and Exa scouts. Baseten as the Agent Builder connector. A public domain.
- **Cut outright:** Baseten Training and distillation. The label is weak, it is booth-gated, and it costs 3+ hours. Ask the booth to enable access anyway, because asking is free.

### 2.2 Schemas (`backend/app/schemas/`)

```python
class SourceRecord(BaseModel):   # one per hit, after schema matching
    rid: str                     # "devpost:crazy-cows-game"
    source: Literal["devpost","yc","github","hn","arxiv","web"]
    url: str; title: str; tagline: str|None; description: str; pitch: str
    year: int|None; date: date|None; date_precision: Literal["day","year","inferred"]|None
    tags: list[str]; tech: list[str]; status: Literal["active","dormant","dead","acquired","unknown"]
    traction: dict               # stars, points, is_winner, batch, team_size
    lang: str; quality_flags: list[str]
    field_provenance: dict[str, Literal["source","normalized","imputed"]]
    retrieval: dict              # {query, leg, rank, rerank_score}
    gptzero: dict|None           # {class, confidence, subclass, ai_sentence_share, model_version}

class MergeDecision(BaseModel):
    a: str; b: str; verdict: Literal["same","different","insufficient_evidence"]
    signals: dict; model: str|None; rationale: str          # signals: url_xref, name_sim, desc_sim
class Conflict(BaseModel):
    field: str; values: list[dict]; resolution: Any; rule: str   # values: {value, rid, reliability}
class Entity(BaseModel):
    eid: str; canonical_name: str; summary: str; records: list[str]
    merges: list[MergeDecision]; possible_same_as: list[str]; conflicts: list[Conflict]
    fields: dict[str, dict]      # {value, provenance:[rid], imputed: bool}
    similarity: float
    facet_overlap: dict[str, dict]   # facet -> {mean, std, votes:[{model,score,why}]}
class Evidence(BaseModel):
    evid: str; eid: str; rid: str; quote: str; url: str; citation: str  # '[3] DevSpot team. "DevSpot." Devpost. 2024. https://…'
    verification: dict|None      # {local_quote_match, gptzero_status, stance, justification}
class Claim(BaseModel):
    cid: str; kind: Literal["exists","differs","trend","gap"]; text: str; by: str; evidence: list[str]
    status: Literal["proposed","challenged","conceded","verified","unverified_lead","rejected"]
    thread: list[dict]           # {from, type: CHALLENGE|REBUTTAL|CONCEDE, text, evidence}
class Message(BaseModel):        # inter-agent envelope
    mid: str; run_id: str; ts: float; frm: str; to: str|None; topic: str|None; in_reply_to: str|None
    type: Literal["TASK","RESULT","REQUEST_EVIDENCE","EVIDENCE","CHALLENGE","REBUTTAL","VERDICT",
                  "VERIFY_RESULT","REPLAN","ABSTAIN","ACTION_PROPOSAL","ACTION_RESULT","ERROR"]
    payload: dict; budget: dict|None
class AgentEvent(BaseModel):     # SSE payload = one JSONL line
    seq: int; run_id: str; ts: float; agent: str; to: str|None
    phase: Literal["plan","scout","resolve","debate","verify","score","mutate","act","done"]
    type: str; data: dict; model: str|None; latency_ms: int|None; tokens: dict|None; cost_usd: float|None
```

**SSE event types:**
- Run and agent lifecycle: `run.started`, `team.formed{team,skipped,why}`, `agent.started|finished`, `run.finished{report}`, `error`.
- Tools and messages: `tool.call|result`, `message.sent{type,to,summary}`.
- Sources and evidence: `source.failed{source,error,reassigned_to}`, `evidence.found{record}`.
- Resolution: `entity.merged{eid,rids,verdict}`, `conflict.detected`.
- Claims and debate: `claim.proposed|challenged|resolved`, `requery.issued{reason,facet,query}`, `verify.result{cid,status}`.
- Scoring and graph: `score.updated{axes,confidence,abstain}`, `graph.patch{add_nodes,add_links,update_nodes,remove_nodes}`.
- Coaching and actions: `mutation.proposed|scored{mid,delta}`, `action.proposed|done`.
- The stream sends `id: seq`, so `Last-Event-ID` resume works. Replay streams the saved JSONL with its original timing multiplied by a speed factor.

### 2.3 Elastic

**Mapping** (`elastic/mappings/prior-art-v1.json`). Run `GET _inference/_all` first and substitute the real endpoint IDs.
```json
{"settings":{"index":{"default_pipeline":"prior-art-clean","refresh_interval":"30s"}},
 "mappings":{"dynamic":"strict","properties":{
  "rid":{"type":"keyword"},"source":{"type":"keyword"},"url":{"type":"keyword"},
  "title":{"type":"text","fields":{"kw":{"type":"keyword","ignore_above":256}}},
  "tagline":{"type":"text"},"description":{"type":"text","analyzer":"english"},
  "pitch":{"type":"text","analyzer":"english"},
  "semantic_pitch":{"type":"semantic_text","inference_id":".jina-embeddings-v3",
     "chunking_settings":{"strategy":"sentence","max_chunk_size":250,"sentence_overlap":1}},
  "sections":{"type":"object","enabled":false},
  "year":{"type":"short"},"date":{"type":"date"},"date_precision":{"type":"keyword"},
  "hackathon":{"type":"keyword"},"hackathon_id":{"type":"keyword"},
  "tags":{"type":"keyword"},"tech":{"type":"keyword"},"is_winner":{"type":"boolean"},"prize":{"type":"text"},
  "status":{"type":"keyword"},"traction":{"type":"flattened"},"field_provenance":{"type":"flattened"},
  "lang":{"type":"keyword"},"dedupe_key":{"type":"keyword"},"quality_flags":{"type":"keyword"},
  "gptzero":{"properties":{"class":{"type":"keyword"},"confidence":{"type":"keyword"},"subclass":{"type":"keyword"},
     "ai_sentence_share":{"type":"float"},"model_version":{"type":"keyword"},"scanned_at":{"type":"date"}}},
  "nn_sim":{"type":"float"},"first_seen_at":{"type":"date"},"ingested_at":{"type":"date"},"ingest_error":{"type":"text"}}}}
```
- `pitch` holds title, tagline and "What it does", capped at 1,500 characters and built client-side.
- `pitch` feeds the BM25 leg, the rerank field, the `significant_text` field and the embedding source. One short field bounds EIS token cost.
- Historical loads set `first_seen_at` to the project date. Only live-scraped documents get `now`, otherwise the watch fires on backfill.

**Pipeline** (`elastic/pipelines/prior-art-clean.json`)
```json
{"processors":[
 {"html_strip":{"field":"description","ignore_missing":true}},
 {"html_strip":{"field":"pitch","ignore_missing":true}},
 {"trim":{"field":"title"}},
 {"set":{"field":"_k","value":"{{{title}}}"}},{"lowercase":{"field":"_k"}},
 {"gsub":{"field":"_k","pattern":"[^a-z0-9]+","replacement":""}},
 {"fingerprint":{"fields":["_k"],"target_field":"dedupe_key","method":"SHA-1"}},{"remove":{"field":"_k"}},
 {"inference":{"model_id":"lang_ident_model_1","target_field":"_lang","field_map":{"pitch":"text"},
    "on_failure":[{"set":{"field":"lang","value":"und"}}]}},
 {"set":{"field":"lang","value":"{{{_lang.predicted_value}}}","if":"ctx._lang != null"}},
 {"remove":{"field":"_lang","ignore_missing":true}},
 {"script":{"source":"if(ctx.quality_flags==null)ctx.quality_flags=new ArrayList(); int n=ctx.pitch==null?0:ctx.pitch.length(); if(n<250)ctx.quality_flags.add('too_short'); if(ctx.lang!=null&&ctx.lang!='en'&&ctx.lang!='und')ctx.quality_flags.add('non_english');"}},
 {"set":{"field":"ingested_at","value":"{{{_ingest.timestamp}}}"}}],
 "on_failure":[{"set":{"field":"_index","value":"prior-art-quarantine"}},
               {"set":{"field":"ingest_error","value":"{{{_ingest.on_failure_message}}}"}}]}
```
`[T]` Test `lang_ident_model_1` on Serverless in hour 1. If it fails, detect language in Python.

**Hybrid query** (`elastic/queries/hybrid.json.j2`)
```json
{"retriever":{"text_similarity_reranker":{
   "retriever":{"rrf":{"retrievers":[
      {"standard":{"query":{"multi_match":{"query":"{{q}}","fields":["title^3","tagline^2","pitch"]}}}},
      {"standard":{"query":{"semantic":{"field":"semantic_pitch","query":"{{q}}"}}}}],
      "filter":{"bool":{"must_not":[{"terms":{"quality_flags":["too_short","non_english"]}},{"ids":{"values":{{exclude_ids}}}}]}},
      "rank_window_size":100,"rank_constant":20}},
   "field":"pitch","inference_id":".jina-reranker-v3","inference_text":"{{idea_full}}","rank_window_size":40}},
 "size":25,"_source":["rid","source","title","tagline","url","year","tags","tech","is_winner","status","dedupe_key","gptzero","hackathon","pitch"]}
```
- The Devpost scout runs three queries: the full idea, purpose plus mechanism, and the twist.
- It unions the results and de-duplicates on `dedupe_key`.
- Every query reranks against the full idea.
- `[T]` Test `highlight` with retrievers. If it fails, build the snippet client-side.

**Two-step `significant_text`.** Step 1 collects the `_id`s of the top-50 neighbours. Step 2 is:
```json
{"size":0,"query":{"ids":{"values":["…50 ids…"]}},
 "aggs":{"cliches":{"significant_text":{"field":"pitch","size":20,"min_doc_count":3,"filter_duplicate_text":true}},
         "tag_cliches":{"significant_terms":{"field":"tags","size":15,"min_doc_count":3}},
         "by_year":{"terms":{"field":"year","size":12,"order":{"_key":"asc"}}},
         "winners":{"filter":{"term":{"is_winner":true}}}}}
```
The background is the whole index.

**Whitespace finder** (`search/whitespace.py`):
- Take a `terms` aggregation on `tech` and `tags` over the top-200 purpose-only neighbourhood.
- Compare it with a cached global top-150.
- Candidates have a global count of at least 500 and a neighbourhood count of at most 1.
- An LLM filter drops candidates that make no sense.
- The result seeds mutations that are grounded in data.

**Agent Builder ES|QL tools** (`elastic/agent-builder/tools/*.json`).
- Each file has the shape `{"id","type":"esql","description","configuration":{"query","params"}}`.
- `[T]` String parameter type may be `keyword` or `text`.
- `[T]` Check FORK, FUSE and RERANK availability on Serverless, and whether the MCP server rewrites dotted tool IDs.
```
originality.hybrid_prior_art:
  FROM prior-art-v1 METADATA _score,_id
  | FORK (WHERE MATCH(pitch, ?q) | SORT _score DESC | LIMIT 60)
         (WHERE MATCH(semantic_pitch, ?q) | SORT _score DESC | LIMIT 60)
  | FUSE | SORT _score DESC | LIMIT 40
  | RERANK ?q ON pitch WITH {"inference_id":".jina-reranker-v3"}
  | SORT _score DESC | LIMIT ?k | KEEP _id,source,title,tagline,url,year,tags,is_winner,_score
  fallback if FORK fails: FROM prior-art-v1 METADATA _score | WHERE MATCH(semantic_pitch, ?q) | SORT _score DESC | LIMIT ?k | KEEP …
originality.crowding_by_year:
  FROM prior-art-v1 | WHERE MATCH(pitch, ?keywords, {"operator":"AND"})
  | STATS projects=COUNT(*), winners=COUNT(*) WHERE is_winner==true BY year | SORT year
originality.cliche_tags:
  FROM prior-art-v1 | WHERE MATCH(pitch, ?keywords) | MV_EXPAND tags | STATS n=COUNT(*) BY tags | SORT n DESC | LIMIT 15
originality.combination_rarity:
  FROM prior-art-v1 | WHERE MATCH(pitch, ?facet_a, {"operator":"AND"}) AND MATCH(pitch, ?facet_b, {"operator":"AND"})
  | STATS both=COUNT(*), latest=MAX(year)
originality.slop_by_year:
  FROM prior-art-v1 | WHERE gptzero.confidence=="high"
  | STATS scanned=COUNT(*), ai=COUNT(*) WHERE gptzero.class!="human" BY year
  | EVAL ai_share=ROUND(100.0*ai/scanned,1) | SORT year
```
- Also register `originality.search_nl` as an `index_search` tool over `prior-art-*`.
- Create the workflow tool `originality.arm_watch` in the UI, then `GET /api/agent_builder/tools/{id}` and commit the JSON it returns.
- Agents:
  - `prior-art-analyst` holds all tools and powers the Kibana chat demo.
  - `watch-analyst` is called from the workflow's `ai.agent` step.
- Division of labour:
  - Direct Elasticsearch carries the deterministic scoring path.
  - MCP tools carry agentic exploration: critic follow-ups, analytics and the arm-watch action.

**Workflows.** Trigger, `inputs:`, template and `if` syntax are verified. `[T]` Validate every step's `with:` keys via `POST /api/workflows/test` and the editor.
```yaml
# elastic/workflows/arm-watch.yaml
name: originality-arm-watch
enabled: true
triggers: [{ type: manual }]
inputs:
  - { name: run_id, type: string, required: true }
  - { name: idea_text, type: string, required: true }
  - { name: facets_query, type: string, required: true }
  - { name: threshold, type: number, default: 0.55 }
steps:
  - name: store_watch
    type: elasticsearch.index
    with:
      index: idea-watches-v1
      id: "{{ inputs.run_id }}"
      document: { run_id: "{{ inputs.run_id }}", idea_text: "{{ inputs.idea_text }}", facets_query: "{{ inputs.facets_query }}",
                  threshold: "{{ inputs.threshold }}", active: true, armed_at: "{{ now }}", last_checked_at: "{{ now }}" }
---
# elastic/workflows/watch-recheck.yaml
name: originality-watch-recheck
enabled: true
consts: { slack_webhook: "https://hooks.slack.com/services/XXX" }
triggers:
  - { type: scheduled, with: { every: 30m } }
  - { type: manual }
steps:
  - name: find_watches
    type: elasticsearch.search
    with: { index: idea-watches-v1, body: { size: 50, query: { term: { active: true } } } }
  - name: each_watch
    type: foreach
    foreach: "{{ steps.find_watches.output.hits.hits }}"
    steps:
      - name: search_new
        type: elasticsearch.search
        with:
          index: prior-art-v1
          body:
            size: 5
            retriever:
              text_similarity_reranker:
                retriever:
                  rrf:
                    retrievers:
                      - standard: { query: { match: { pitch: "{{ foreach.item._source.facets_query }}" } } }
                      - standard: { query: { semantic: { field: semantic_pitch, query: "{{ foreach.item._source.idea_text }}" } } }
                    filter: { range: { first_seen_at: { gt: "{{ foreach.item._source.last_checked_at }}" } } }
                    rank_window_size: 50
                field: pitch
                inference_id: .jina-reranker-v3
                inference_text: "{{ foreach.item._source.idea_text }}"
                min_score: 0.55
      - name: has_new
        type: if
        condition: "steps.search_new.output.hits.total.value > 0"
        steps:
          - name: triage
            type: ai.agent
            with: { agent_id: watch-analyst, message: "Idea: {{ foreach.item._source.idea_text }}\nCandidates: {{ steps.search_new.output.hits.hits | json }}\nWhich are genuinely the same idea? Answer with a 2-sentence alert or NONE." }
          - name: record_alert
            type: elasticsearch.index
            with: { index: idea-alerts-v1, document: { run_id: "{{ foreach.item._source.run_id }}", created_at: "{{ now }}", summary: "{{ steps.triage.output }}" } }
          - name: notify_slack
            type: http
            with: { method: POST, url: "{{ consts.slack_webhook }}", body: { text: "New prior art for a watched idea: {{ steps.triage.output }}" } }
      - name: advance_cursor
        type: elasticsearch.update
        with: { index: idea-watches-v1, id: "{{ foreach.item._id }}", doc: { last_checked_at: "{{ now }}" } }
```
- `elastic/apply.py` applies mappings, pipeline, tools, agents and workflows idempotently.
- **Actuator chain:**
  - Try the workflow tool over MCP.
  - Then try `POST /api/workflows/workflow/{id}/run`.
  - Then index directly into `idea-watches-v1`.
- **Demo beat:**
  - The live gallery scraper indexes a new HTN 2026 submission. Failing that, index a clearly labelled simulated one.
  - Run the recheck manually, and Slack pings.

### 2.4 Corpus sizing
EIS throughput and cost are unknown, so ingest in tiers.
- **Tier 0, by 02:45:** `twangodev/devpost-hacks` config `all` (2,222 rows), YC (6,237 rows), and seeds for HackAnalyzer, DevSpot and Plagia. All get `semantic_pitch`. This proves the whole path works end to end.
- **Measure, 02:45-03:15:** run `ingest/measure_eis.py` on 1,000 documents.
  - Vary `chunk_size` over {25, 50, 100} and threads over {1, 4, 8}.
  - Record docs/s, 429 counts, and the billing delta in the Cloud console.
  - Size Tier 1 so it finishes in 3 hours or less.
- **Tier 1, overnight:** up to 40k `alvanlii` rows with semantic. Winners first, then descending year.
  ```
  caffeinate -i nohup python -m ingest.load_devpost_hf --tier 1 --resume >> logs/ingest.log &
  ```
  - Use `_id=rid` so reruns are idempotent.
  - Keep a checkpoint file.
  - Use `parallel_bulk` with backoff on 429.
- **Tier 2:** the remaining ~215k rows, BM25-only, which takes minutes.
  - This gives full-corpus `significant_text` backgrounds and the lexical leg immediately.
  - `backfill_semantic.py` then adds `semantic_pitch` through bulk `update`, recent years first.
- **Fallback ladder:**
  - Shorter `semantic_pitch`.
  - Your own Jina API key through the `jinaai` service.
  - BM25 plus Jina rerank only, which always works.
- **Calibration, after Tier 1:**
  - Run 300 random documents as queries with self excluded.
  - Compute `crowding_lite` for each.
  - Save the sorted array as the percentile reference.

### 2.5 Agents

| Role | Motto | Capability and authority | Model (starting point, to be set by the bake-off) |
|---|---|---|---|
| `conductor` | "Decompose, staff, replan." | Extracts facets, forms the team, keeps the budget, reassigns on failure. | `zai-org/GLM-5.3-Flash` |
| `scout.devpost`, `scout.yc` | "If it was built, I find it." | Elasticsearch through MCP tools and direct hybrid search. | `deepseek-ai/DeepSeek-V4-Flash-0731` |
| `scout.github`, `scout.hn`, plus optional arXiv and Exa | same | Lexical APIs. Adaptive broaden-and-retry when a query returns 0 hits. | same |
| `resolver` | "Four listings, one project." | Schema match, blocking, adjudication, fusion, conflicts, imputation. **The only role that writes entities.** | DeepSeek-V4-Flash, 8 pairs per call |
| `critic` | "This has been done. Prove me wrong." | Makes `exists` claims with quotes. **Can send scouts back out** with up to 2 `REQUEST_EVIDENCE` messages. | `deepseek-ai/DeepSeek-V4-Pro` |
| `advocate` | "Same words are not the same idea." | Must concede, distinguish by facet, or challenge the evidence. Uses a different model family from the critic. | `zai-org/GLM-5.3` |
| `judge` | "Count the votes, measure the split." | Panel of 3-4 model families. Disagreement triggers `REPLAN`. | GLM-5.3-Flash, DeepSeek-V4.1-Flash, gpt-oss-120b, plus Kimi-K2.6 |
| `verifier` | "No receipt, no claim." | Quote-in-source check plus GPTZero. **Holds a veto.** | none |
| `synthesizer` | "Only what survived." | Code restricts its input to `verified` and `unverified_lead` claims. | `zai-org/GLM-5.3` |
| `mutator` | "Move one facet into the whitespace." | Swaps come from whitespace candidates. Triggers re-scores. | `moonshotai/Kimi-K2.6`, temperature 1.0 |
| `actuator` | "An answer that doesn't act is a report." | Picks actions by confidence. Actions that reach outside the system need a user click. | GLM-5.3-Flash |

**What makes the collaboration genuine:**
- A typed blackboard with per-role write permissions.
- Critic re-queries to scouts.
- A jury split triggers a targeted re-query and a re-vote on that pair only.
- The verifier's veto is enforced in code.
- The team is formed dynamically by domain, and the UI shows which scouts were skipped and why.
- Failure leads to reassignment. If GitHub fails, the web scout takes over with `site:github.com`. Otherwise the source is marked failed and confidence drops.
- The per-run budget degrades visibly.
  - Limits: at most 70 calls, 150k tokens and 90 s.
  - When over budget: skip round 2 and propose fewer mutations.
- The critical path uses P2P with stage barriers. Pub/sub carries `source.status` and `evidence.raw`, which lets the resolver pre-block incrementally.

```python
# roles/conductor.py
plan = await self.plan(idea); await ctx.emit("team.formed", team=plan.team, skipped=plan.skipped)
res  = await gather_safe(*[ctx.send(f"scout.{s}", TASK(plan, s), timeout=40) for s in plan.team])
for s, err in res.failed: await self.reassign_or_degrade(s, err, ctx)
ents = await ctx.send("resolver", TASK(records=res.ok))
for rnd in range(2):
    claims  = await ctx.send("critic",   TASK(entities=ents))     # may itself send REQUEST_EVIDENCE to scouts
    rebut   = await ctx.send("advocate", TASK(claims=claims))
    verdict = await ctx.send("judge",    TASK(claims=claims, rebuttals=rebut))
    if verdict["max_disagreement"] < 0.25 or ctx.budget.low(): break
    await ctx.emit("requery.issued", reason="jury split", facet=verdict["disputed_facet"])
    more = await ctx.send(best_scout(verdict["disputed_facet"]), TASK(query=verdict["tiebreak_query"]))
    ents = await ctx.send("resolver", TASK(records=more, merge_into=ents))
verify = asyncio.create_task(ctx.send("verifier", TASK(claims=claims)))   # badges flip asynchronously
report = await ctx.send("synthesizer", TASK(...)); muts = await ctx.send("mutator", TASK(...)); await ctx.send("actuator", TASK(...))
```

**Resolver, which carries the Rox story:**
- **Blocking.**
  - URL cross-references: Devpost `other_links` to GitHub, HN `url` to a domain, YC `website` to a domain.
  - `dedupe_key`.
  - Name trigram Jaccard of at least 0.6.
- **Deciding.** A URL cross-reference auto-accepts as `same`. Everything else gets batched LLM adjudication into `same`, `different` or `insufficient_evidence`.
- **Merging.** Union-find performs the merges. `insufficient_evidence` becomes a dotted `possible_same_as` edge in the graph.
- **Field fusion** uses the priors in `wrangle/reliability.py`.
  - Last activity: `github.pushed_at` 0.95, HN 0.8, YC batch 0.7, Devpost year 0.6.
  - Status: YC 0.9, GitHub archived or no push for over 18 months counts as dormant at 0.8.
- **Conflicts.** A date gap over 12 months or an active-versus-dead disagreement produces a visible `Conflict`.
- **Imputation.** Imputed `tech` is marked as imputed.
- **UI.** The Evidence Ledger shows badges for merged, conflict, imputed, quarantined and source-failed.

### 2.6 Scoring (`docs/scoring.md`, `scoring/axes.py`)
```
r_i = reranker score of entity i vs full idea (top 10 after resolution)
crowding_lite = 0.6*max(r) + 0.4*mean(top5 r)              -> pct via the 300-doc calibration CDF
AXIS 1  Crowding         O1 = 100*(1 - pct)
AXIS 2  Facet rarity     rarity_f = 1 - log(1+df_f)/log(1+2000)          (df_f = facet-only hits above the rerank threshold)
                         pair = 1 - log(1+df(purpose AND mechanism))/log(1+200)
                         cliche = |idea_terms ∩ significant_text(neighbours)| / |idea_terms|
                         O2 = 100*(0.5*mean_f rarity_f + 0.3*pair + 0.2*(1-cliche))
AXIS 3  LLM-predictability   12 samples (4 model families x 3, T=1.0) from {purpose, audience} ONLY
                         collision = max_j cos(idea, s_j);  hit_rate = share with cos > 0.80
                         O3 = 100*(1 - 0.6*pct(collision) - 0.4*hit_rate)  [+ surprisal percentile if the Truss is live]
AXIS 4  Voice (GPTZero)  SEPARATE, never in the headline: result_message + confidence_category, highlighted sentences,
                         ai_sentence_share = flagged chars / unmasked chars, percentile vs this year's scanned pitches,
                         neighbourhood slop share
HEADLINE   O = 100*(O1/100)^0.45*(O2/100)^0.35*(O3/100)^0.20 ;  band = +-min(30, 8 + 40*mean_jury_std)
CONFIDENCE E = 0.35*coverage + 0.25*(1-jury_std_norm) + 0.25*verified_share + 0.15*canary_pass
  coverage = weighted share of planned sources that succeeded
  canary   = a purpose-only broad query must return >= N hits per source, else that source counts as failed
ABSTAIN  pitch < 250 chars          -> Voice axis says "too short to assess reliably"
         devpost failed OR coverage < 0.5 -> headline replaced by "Insufficient evidence: <what is missing>"
         E < 0.45                   -> axes shown, headline greyed with the reason
         per claim: "exists" needs >= 1 source with a local quote match AND GPTZero stance not "contradict", else unverified_lead
         GPTZero citation status "fake" -> rejected and logged as a caught hallucination
```
- A mutation re-score recomputes only `crowding_lite` and `pair`, which takes about 3-5 s.
- The graph plots a node's distance from the idea as 1 minus similarity.
- When the user picks a mutation, its node moves outward.

### 2.7 GPTZero integration and word budget
Assume about 500k words. `[T]` Read `/v3/usage-stats` in hour 1 and ask the booth for a higher cap.

| Use | Endpoint | Words | Cache |
|---|---|---|---|
| Pitch voice, 250 characters or more | `/v2/predict/text` | up to 400 per run | sha256 of the text |
| Evidence badges and slop share | `/v2/predict/text` on the top-8 pitches, 1,500 characters each | about 1,850 cold, approaching 0 warm | written back to the Elasticsearch document as `gptzero.*` |
| Report verification | `/v2/bibliography-scan/text` on the claims plus `[n] Org. "Title." Site. Year. URL.` | up to 600 `[T]` billing unknown, so read the usage delta after the first call | sha256 of the report |
| Patterns, only if allow-listed | `/v3/ai/patterns/stream` | up to 400 | same |
| Investigation phase 1 | batch predict | 7 years × 150 × about 200 = **210k** | parquet |

- **Caps:** 120k interactive, 230k investigation, 50k reserve.
- **Ledger:** `signals/gptzero_budget.py` enforces the caps. `GPTZERO_MODE` defaults to `replay`, so development burns nothing.
- **Spec discipline:**
  - Use `class_probabilities`, `confidence_category` and `subclass`. Never use the deprecated probability fields.
  - Honour `should_mask`.
  - Sentence-level keys use `paraphrased`.
  - Show `result_message`, never raw probabilities.
- **"Fire drill" button:** it injects a clearly labelled fabricated competitor with a fake citation. The verifier strikes it live, which makes the hallucination catch demoable on demand.

**Investigation (`investigation/`):**
- Join `hackathons.json` to get years.
  - Sample years 2018, 2019, 2021, 2022, 2023, 2024 from `alvanlii`.
  - Sample 2025 and 2026 from `twangodev`.
- **Keep:** pitches that are in English and at least 600 characters long.
- **Length control:** truncate to 1,800 characters at a sentence boundary.
- **Headline metric:** share of pitches classed `ai` or `mixed` with `high` confidence, reported with Wilson confidence intervals and split by `subclass`.
- **Placebo years (2018-2021):** they give the detector's empirical false-positive rate on this genre. Report it.
- **Tie-in test:** compare `nn_sim`, the mean similarity to the top-5 semantic neighbours, for flagged versus human pitches within each year. Use Mann-Whitney and Cliff's delta.
- **Winner share by class.**
- **Public artifact:** an anonymized CSV with year, class, confidence, subclass, `nn_sim` and `is_winner`. It carries no project URLs, so no student is named.

### 2.8 Baseten integration
1. **Bake-off** (`baseten/bakeoff.py`, 30 min, Saturday AM).
   - Measure, per slug: latency, JSON-schema validity, tool-call success and reasoning overhead.
   - Commit the resulting table.
   - The table sets the role-to-model assignment and becomes a pitch artifact.
   - `[T]` Models that reason by default may blow the latency budget. Find the switch that lowers reasoning, or choose other slugs.
2. **Prior-collision:**
   - 12 samples at temperature 1.0 from 4 cheap model families.
   - Embed them through `_inference/text_embedding/.jina-embeddings-v3`.
   - Compute cosine similarity against the idea.
   - The samples appear as grey graph nodes.
3. **Jury:** N separate requests, because `n` is capped at 1. The standard deviation across jurors feeds both confidence and re-planning.
4. **Surprisal.**
   - First run the passthrough probe from section 4.
   - If `prompt_logprobs` is absent, deploy a Truss (P2, capped at 2 hours):
   ```yaml
   # baseten/surprisal-truss/config.yaml, adapted from docs.baseten.co/examples/vllm
   model_name: surprisal-qwen3-base
   base_image: { image: vllm/vllm-openai:v0.29.0 }
   docker_server:
     start_command: vllm serve /models/m --served-model-name surprisal --host 0.0.0.0 --port 8000 --max-logprobs 5
     readiness_endpoint: /health
     liveness_endpoint: /health
     predict_endpoint: /v1/completions
     server_port: 8000
   weights: [{ source: "hf://Qwen/Qwen3-1.7B-Base", mount_location: "/models/m" }]   # [T] the docs example pins @<sha> and sets an auth secret
   resources: { accelerator: L4, use_gpu: true }
   ```
   - Deploy with `baseten model push --dir baseten/surprisal-truss`.
   - Call it like this:
     ```
     POST https://model-<id>.api.baseten.co/environments/production/sync/v1/completions
     {"model":"surprisal","prompt":<pitch>,"max_tokens":1,"temperature":0,"echo":true,"logprobs":1}
     ```
   - `[T]` Check that the path proxies through.
   - Compute per-token surprisal, take per-sentence means through `text_offset`, and rank against a 300-pitch reference.
   - An L4 costs $0.85 per hour and scales to zero.
5. **Hygiene:**
   - Put the shared prompt prefix first.
   - Set `x-session-affinity: <run_id>:<role>`.
   - Use a global token bucket at 100 RPM.
   - Verify the account, which raises the limit to 120 RPM.
   - The UI shows a cost and latency meter per role.
6. **Router:**
   - Order: Baseten with a 25 s timeout, then one retry on 429 or 5xx, then the OpenRouter equivalent.
   - Every call logs which provider served it.

### 2.9 Error handling
- Each source gets an 8 s timeout, 2 `tenacity` retries, then a circuit breaker and `source.failed`.
- LLM JSON failures go through `json_repair`, then one schema-error re-ask, then a role-level fallback:
  - The resolver falls back to deterministic rules only.
  - The judge drops that juror.
- If GPTZero is down, the local quote-check still gates claims and the Voice axis abstains.
- If the rerank endpoint fails, use RRF only. Mark the score "uncalibrated" and lower confidence.
- Every degradation is an event the user sees.

## 3. Repo layout (root `/Users/enkailiu/Projects/htn-2026`)
```
README.md  Makefile  .env.example  .gitignore  .python-version(3.12)
backend/pyproject.toml   # fastapi uvicorn sse-starlette httpx openai elasticsearch>=9 pydantic>=2 tenacity json-repair numpy pyarrow feedparser openjiuwen==0.1.18
backend/app/main.py  config.py
backend/app/api/{runs.py,investigation.py,replay.py,admin.py}
backend/app/schemas/{records.py,entities.py,claims.py,messages.py,events.py,report.py}
backend/app/core/{blackboard.py,eventbus.py,budget.py,runstore.py}
backend/app/llm/{router.py,models.py,structured.py,cost.py,prompts/*.md}
backend/app/orchestration/{host.py,asyncio_host.py,jiuwen_host.py,registry.py}
backend/app/roles/{conductor.py,resolver.py,critic.py,advocate.py,judge.py,verifier.py,synthesizer.py,mutator.py,actuator.py}
backend/app/roles/scouts/{base.py,devpost.py,yc.py,github.py,hn.py,arxiv.py,web.py}
backend/app/search/{es.py,hybrid.py,rarity.py,whitespace.py,calibration.py,mcp_tools.py}
backend/app/sources/{hn.py,github.py,arxiv.py,exa.py,devpost_page.py}
backend/app/wrangle/{schema_map.py,blocking.py,adjudicate.py,fuse.py,reliability.py,impute.py}
backend/app/signals/{gptzero.py,gptzero_budget.py,biblio.py,quote_check.py,prior_collision.py,surprisal.py,jury.py}
backend/app/scoring/{axes.py,confidence.py,abstain.py}  backend/app/actions/{watch.py,writeback.py,pitch_draft.py}  backend/app/graph/build.py
backend/tests/{test_scoring.py,test_abstain.py,test_schema_map.py,test_blocking.py,test_events_contract.py,test_hybrid_query_shape.py}
backend/fixtures/{mock_run.jsonl,gptzero/,golden/,calibration/}
frontend/app/{page.tsx,runs/[id]/page.tsx,slop-index/page.tsx,about/page.tsx}
frontend/components/{IdeaInput,SwarmTimeline,DebateThread,EvidenceCard,EvidenceLedger,AxisGauges,PitchHighlighter,IdeaGraph,MutationPanel,ActionBar,CostMeter,SlopCharts}.tsx
frontend/lib/{sse.ts,types.ts,graphReducer.ts,replay.ts}   frontend/public/replay/*.jsonl
ingest/{download_hf.py,parse_sections.py,load_devpost_hf.py,load_devpost_recent.py,load_yc.py,scrape_galleries.py,seed_known_prior_art.py,measure_eis.py,backfill_semantic.py}
elastic/mappings/*.json  elastic/pipelines/prior-art-clean.json  elastic/queries/*.json.j2
elastic/agent-builder/{tools/*.json,agents/*.json}  elastic/workflows/{arm-watch.yaml,watch-recheck.yaml}  elastic/apply.py
swarm-skill/prior-art-swarm/{SKILL.md,roles/*.md,workflow.md,bind.md,dependencies.yaml,scripts/workflow.py}
investigation/{sample.py,scan.py,neighbours.py,analyze.py,export_public.py,results/}
baseten/{bakeoff.py,reference_distribution.py,surprisal-truss/config.yaml}
scripts/{smoke_all.sh,smoke_gptzero.sh,smoke_baseten.sh,smoke_elastic.sh,bench_ideas.py,record_golden.py,secret_scan.sh}
docs/{architecture.md,events.md,scoring.md,benchmarks.md,demo-script.md,devpost.md,sponsors/{gptzero,baseten,huawei,rox,elastic}.md}
```

**`SKILL.md` frontmatter**, in JiuwenSwarm's format:
- `name: prior-art-swarm`, `version: 1.0.0`, an `author`, and `kind: team-skill`.
- `description` in the three-line WHAT / WHEN / NOT form.
- `roles:`, at least 2, each with `id`, `purpose` (150 characters or fewer), `skills: []` and `tools: [...]`.
- Every role file has these sections: Identity (first line is the motto), Success Criteria, Boundary (with **Forbidden** and **Mandatory**), Output Schema, and Inline Persona for Teammate.
- Every tool listed must also appear in `dependencies.yaml`.
- Fetch `validate_swarmskill.py` and run `python validate_swarmskill.py swarm-skill/prior-art-swarm`.
- Commit its output to `docs/sponsors/huawei.md`.

## 4. Schedule (EDT)

### Hour 0, 01:30-02:15, all hands
1. **Huawei.** Apply at luma.com/mc7lijgs first, because it is first-come, first-served.
2. **Baseten.**
   - Create the account, **verify it**, and redeem the code from `#spons-baseten-2026`. The workspace owner redeems.
   - Get a key, then probe:
   ```bash
   curl -s https://inference.baseten.co/v1/models -H "Authorization: Bearer $BASETEN_API_KEY" | jq -r '.data[].id'
   curl -s https://inference.baseten.co/v1/chat/completions -H "Authorization: Bearer $BASETEN_API_KEY" -H 'Content-Type: application/json' \
    -d '{"model":"openai/gpt-oss-120b","messages":[{"role":"user","content":"hi"}],"max_tokens":4,"logprobs":true,"top_logprobs":3,"prompt_logprobs":1}' \
    | jq '{lp:.choices[0].logprobs.content[0], plp:(.prompt_logprobs // .choices[0].prompt_logprobs // "ABSENT")}'
   ```
3. **GPTZero.** Get a key, then:
   ```bash
   curl -s https://api.gptzero.me/v3/usage-stats -H "x-api-key: $GPTZERO_API_KEY"
   curl -s https://api.gptzero.me/v2/predict/text -H "x-api-key: $GPTZERO_API_KEY" -H 'Content-Type: application/json' -d '{"document":"<300+ chars>"}' \
    | jq '.documents[0]|{predicted_class,confidence_category,class_probabilities,subclass}'
   curl -s https://api.gptzero.me/v2/bibliography-scan/text -H "x-api-key: $GPTZERO_API_KEY" -H 'Content-Type: application/json' \
    -d '{"document":"DevSpot already validates hackathon ideas against Devpost [1].\n\nReferences\n[1] DevSpot team. \"DevSpot.\" Devpost. 2024. https://devpost.com/software/devspot"}' \
    | jq '{cit:[.bibliographic_citations[]|{text,s:.citation_exists.status}],claims:[.claims[]|{text,st:.agree_with_citation.stance}]}'
   ```
   - Re-read usage afterwards to learn the billing delta.
   - Also hit `/v3/ai/patterns/stream`, which should return 403.
4. **Elastic.**
   - Start a Serverless Elasticsearch trial.
   - Create an unrestricted API key.
   - Run `curl -s "$ES_URL/_inference/_all" -H "Authorization: ApiKey $ES_API_KEY" | jq -r '.endpoints[]|"\(.task_type)\t\(.inference_id)"'`.
   - Turn on `workflows:ui:enabled`.
   - Confirm Agent Builder is visible.
5. **Everything else.**
   - Open an OpenRouter account for the fallback.
   - Run `gh auth token` and store it as `GITHUB_TOKEN`.
   - Optionally get an Exa key and set up a Slack incoming webhook.
6. **Scaffold.**
   - Create the 3.12 venv.
   - Run `pnpm create next-app frontend`.
   - Write `.env.example`.
   - Make the first commit on `main`.
   - Commit small and often, because the history proves the code was written at the event.

### Hour-by-hour

| Time | P1 Spine (Elastic, data) | P2 Swarm | P3 Face | P4 Signals |
|---|---|---|---|---|
| 02:15-04:30 | Mapping and pipeline. Tier 0. `measure_eis`. Launch Tier 1 and Tier 2. `hybrid.py` with a CLI. | Spike G1-G3, **decide at 03:15**. Router. Facet schema. Asyncio host. Eventbus. | `docs/events.md` and `mock_run.jsonl`. Next skeleton. SSE hook. Timeline from the mock. | GPTZero client with ledger and replay. Download the parquet (372 MB) and `hackathons.json`. `sample.py`. Pilot scan of 4 years × 50. |
| **04:30 M0** | | | | |
| 04:30-08:30 | **Sleep, everyone.** Ingest and the capped scan run under `caffeinate`. | | | |
| 08:30-09:00 | Standup and check overnight jobs. | | | |
| 09:00-13:30 | Seeds. Devpost and YC scouts direct. Calibration. `significant_text`. **Elastic booth.** | Planner. HN and GitHub scouts. Minimal synthesizer with citations. `/api/runs` with SSE. **Huawei booth.** | Evidence cards, gauges, highlighter, wired to the real stream. | **GPTZero, Baseten, Rox booths.** Bake-off. Scan phase 1. |
| **13:30 M1** | A real end-to-end run exists. | | | |
| 13:30-14:00 | **Devpost initial submission**: team, badge IDs, lock prizes. | | | |
| 14:00-18:00 | ES\|QL tools, agents, G4 over MCP by 16:00, whitespace, `apply.py`. | Resolver. Critic and advocate with re-query. Judge. Blackboard permissions. Jiuwen host parity. | IdeaGraph v1 and `graphReducer`. DebateThread. EvidenceLedger. | Two-layer verifier. Slop share and write-back. `neighbours.py` and `analyze.py`. |
| **18:00 M2** | Dinner, then run the 8 benchmarks and fix the ordering. | | | |
| 19:00-23:00 | Workflows, Slack, poller. Live gallery scraper. Combination rarity. | Mutator with re-score. Actuator. Budget degradation. Chaos toggle. **Jiuwen parity check at 21:00.** | MutationPanel with graph animation. ActionBar. CostMeter. `/slop-index`. | Prior-collision with cloud nodes. Fire drill. Reference distributions. Start the Devpost draft. |
| **23:00 M3** | **FEATURE FREEZE.** | | | |
| 23:00-02:00 | Latency and caching. `/about` with the live corpus count. README setup. | Swarm Skill and validator. JiuwenSwarm recording (90 min cap). | Replay mode and golden runs. Polish. Replay-only Vercel build. | Truss surprisal (cut if not done by 01:00). Public CSV. Sponsor docs. |
| **02:00 M4** | Record the backup video while everything works, 02:00-03:00. | | | |
| 03:00-06:30 | Staggered sleep: P1 and P3 sleep 03:00-06:00, P2 and P4 sleep 03:30-06:30. The awake pair writes the Devpost text, runs the secret scan and makes the repo public. | | | |
| 06:30-07:15 | Final checks. **Submit by 07:15.** Leave buffer until 08:00. | | | |
| 08:00-09:45 | Rehearse 3 times. Practise the sponsor 60-second pitches. Set up a second laptop. Prepare a hotspot and chargers. | | | |

### Cut lines

| Checkpoint | Go criterion | If behind |
|---|---|---|
| M0 04:30 | At least 8k documents searchable. Smokes green. The mock stream renders. | EIS under 20 docs/s: cap Tier 1 at 25k. Gates red: switch to the asyncio primary. |
| M1 13:30 | A real end-to-end run on 2 ideas. | Drop arXiv, Exa and the add-on prizes. Defer MCP. |
| M2 18:00 | Debate, resolver, rarity and verification work on at least 1 idea. | Cut the advocate. Drop to a 2-model jury. Make the resolver URL-xref-and-name only, with an LLM for the top 5 pairs. Use a static graph. |
| M3 23:00 | Mutations with re-score, watch, and slop page all work. | Cut chaos, cloud nodes, the Truss, the recording and write-back. |
| M4 02:00 | Golden runs and the video are recorded. | If the jiuwen host is not at parity, use asyncio for every demo. |

### Booth list, Sat 09:00-10:30
- **Rox.** Is there a separate submission or write-up, which email, and which deadline? TreeHacks required a write-up within 2 hours. What did the 2025 winner do? Is UI weighted?
- **Huawei.** "Our app runs on openjiuwen agent-core (TeamRuntime, BaseTeam), and we ship a validated Swarm Skill. Does that count as 'on top of JiuwenSwarm or WorkSwarm'? Do you want the skill running inside the app, live?" Also ask about credit status and a judging slot.
- **GPTZero.**
  - Patterns allow-listing.
  - A word bump: "NeurIPS-style investigation, about 600k words".
  - Bibliography-scan entitlement and billing.
  - Whether it verifies non-academic URLs.
- **Baseten.** Enable training access as a free option. Ask about `prompt_logprobs` on Model APIs, the rate-limit form, and which slugs return logprobs.
- **Elastic.** Ask about a starter repo or workshop, EIS limits and cost on trial, which reranker ID they recommend, FORK/FUSE/RERANK on Serverless, workflow-tool JSON, and MCP tips.

### Before 14:00
- Finish smokes 2-4.
- Settle the G1-G3 decision.
- Record Rox's requirements in writing.
- Record the Huawei answer.
- Draft the Devpost entry with every teammate and badge ID.
- Read the form for any opt-in cap. If capped, prioritise Rox, then GPTZero, Elastic, Huawei, Baseten.
- Add GoDaddy only if the replay-only Vercel build exists.
- Add Browserbase only with 4 people and if its sponsor track turns out to require it.
- Skip RBC unless the booth confirms no mandated corpus. Even then it is P2.
- Keep opt-ins to 6-7 at most. Every opt-in costs a slot in the 2-hour sponsor window.

### Team size

| Size | Split | Cuts |
|---|---|---|
| 4 | As scheduled above. | None. |
| 3 | P4 dissolves. GPTZero and the investigation go to P1. Baseten instruments and the bake-off go to P2. Booths go to P3. | Truss, recording (keep the skill and validator), arXiv, Exa, chaos, write-back. Investigation drops to 6 years × 120. |
| 2 | A does the whole backend. B does the frontend, GPTZero, the investigation, booths and Devpost. | One host only: jiuwen if G1-G3 pass in 60 min, else asyncio. 2-model jury. No advocate. MCP registered but scouts direct. Static graph. Investigation at 5 years × 100. |
| 1 | Asyncio with 6 roles: conductor, 3 scouts, critic, verifier-and-synthesizer. | The priority prizes are GPTZero, Elastic and Baseten. Rox and Huawei are opportunistic. Still opt in, and still ship the skill markdown and the evidence-ledger table. Investigation at 5 × 80. Replay mode is mandatory. |

## 5. Risk register

| Risk | Signal | Fallback |
|---|---|---|
| EIS slow or expensive | `measure_eis` | Tiering. Short `semantic_pitch`. Own Jina key. BM25 plus rerank. |
| Reranker or endpoint ID differs | `_inference/_all` | Put the ID in config. Fall back to v2 multilingual or RRF only. |
| Agent Builder MCP quirks | G4 | Direct Elasticsearch for the critical path. Actuator chain from section 2.3. |
| Workflow step schema mismatch | `/api/workflows/test` | Validate in the editor. Simplify by dropping `ai.agent` for `ai.summarize`, or Slack for the alert index. Worst case is a manual run during the demo. |
| openjiuwen re-entrancy, timeouts or dependency conflict | G2 and the 21:00 parity check | Explicit timeouts. N scout instances. Separate process. Asyncio host. |
| JiuwenSwarm install or run fails | 90 minutes elapsed | Ship the skill, the validator output and `scripts/workflow.py` anyway. |
| Bibliography-scan is gated, slow, or returns `unknown` for non-academic URLs | Hour-1 smoke | Booth. The local quote-check gates claims. Run the scan asynchronously. Only `fake` rejects a claim. |
| GPTZero quota | Ledger | Replay mode. Caps. Smaller sample. Ask for a bump. |
| No prompt logprobs | Probe | Prior-collision as the headline. Truss at P2. |
| Baseten 429s or reasoning latency | Bake-off | Token bucket. Low-reasoning slugs. OpenRouter overflow. Fast mode. |
| GitHub or arXiv rate limits | 403 or 429 | Query cache. At most 6 GitHub queries per run. Circuit breaker leading to `source.failed`. |
| HF or Devpost fetch trouble | Ingest log | Full UA. `r.jina.ai` returned 200. `twangodev` already covers 2024-26. |
| Conference wifi | Whenever it drops | Phone hotspot. **Golden-run replay.** Replay-only Vercel site. Backup video. |
| Live demo fails | Whenever it happens | `?replay=self` and `?replay=studybuddy` at 1.5×. Both Fire Drills work offline. |
| Secrets in a repo that goes public | 06:00 | Keep `.env` git-ignored. Run `scripts/secret_scan.sh`. Rotate any leaked key. |
| Honesty challenges from judges | Q&A | Voice is a separate axis. Report the placebo false-positive rate. Release anonymized data only. Label simulated items. |

## 6. Demo (5 minutes)
- **0:00 Hook.** "Every hackathon, a thousand hackers ask an LLM for an idea and get the same one. Whitespace tells you how original yours is, with receipts, then coaches you somewhere emptier."
- **0:20 Run it on itself.**
  - The team forms and shows which scouts it skipped.
  - Cards arrive for DevSpot, HackAnalyzer and Plagia.
  - The resolver merges a Devpost record with its GitHub repo.
  - The critic argues the idea has been done. The advocate distinguishes by facet.
  - The jury splits, and a scout goes back out.
  - Claims turn green, and the fire drill gets struck.
  - Crowding is high. Click the mutation that matches our actual design. The neighbourhood thins and the node moves: "that's how we designed this."
- **1:40 Study buddy.**
  - The year histogram spikes after 2023.
  - Cliché terms come from `significant_text`.
  - "9 of 12 samples from 4 model families proposed this exact idea."
  - Sentences are highlighted, with Voice shown as its own axis.
  - The ledger shows its badges.
  - Click a whitespace mutation and the scores move.
- **2:50 Act.** Arm the watch, run the recheck, Slack pings. Then draft the differentiated pitch.
- **3:30 Slop Index.**
  - The placebo-year false-positive rate.
  - The rise in AI-flagged pitches by subclass.
  - Flagged pitches sit closer to their neighbours.
  - Your own percentile.
- **4:30 `/about`.** Agents on openJiuwen. Elasticsearch as the context layer over MCP. Baseten right-sized with a cost meter. GPTZero as an independent verifier. Ends with Q&A.

### 60-second sponsor angles
- **GPTZero.**
  - Both prize bullets are covered.
  - The investigation is in your NeurIPS and ICLR format, on a corpus you haven't scanned. It has a placebo false-positive rate, a subclass split and the neighbour tie-in.
  - The product has three integrations: sentence-level voice, neighbourhood slop share, and bibliography-scan with a veto over our own agents.
  - It follows the spec: no deprecated fields, `should_mask`, and the 250-character gate.
- **Baseten.**
  - Inference is used as a measurement instrument.
  - Prior-collision across 4 families.
  - True surprisal from a base model we deployed with Truss and vLLM, because shared APIs don't expose prompt logprobs.
  - Jury disagreement feeds re-planning.
  - The bake-off right-sizes each role. The meter shows cost and seconds per analysis.
  - Prefix caching and session affinity.
- **Huawei.**
  - Roles run on openJiuwen agent-core: TeamRuntime with P2P and pub/sub, BaseTeam streaming, ReAct scouts over MCP.
  - What they do together that one agent cannot:
    - Parallel breadth.
    - A cross-family adversarial check.
    - Independent verification with a veto.
    - Re-planning driven by disagreement.
    - Dynamic team formation.
    - A live kill-a-scout degradation.
  - The `prior-art-swarm` skill passes your validator and generalizes to patents, research and features.
- **Rox.**
  - A data-wrangling agent in the "Can Foundation Models Wrangle Your Data?" taxonomy.
  - Schema matching across six sources into one schema, with the mapping table shown.
  - Entity matching with `insufficient_evidence` as an outcome.
  - Error detection through the quarantine index.
  - Visibly marked imputation.
  - Conflicts resolved with source-reliability priors.
  - Calibrated abstention and graceful degradation.
  - It also acts: arms a recurring watch, writes back, and drafts the pitch, choosing actions by confidence.
- **Elastic.**
  - Elasticsearch is the context layer for every agent.
  - Messy write-ups go through an ingest pipeline (`html_strip`, `fingerprint`, `lang_ident`, quarantine) into `semantic_text` with Jina on EIS.
  - Retrieval is BM25 plus semantic, fused with RRF and reranked by Jina.
  - The originality maths is native: `significant_text`, the aggregation whitespace finder, and ES|QL tools in Agent Builder served over MCP.
  - A scheduled Workflow with `ai.agent` closes the loop.

### Devpost outline
- Inspiration: Si et al., and the median-LLM-idea problem.
- What it does: the 4 axes, confidence, mutations and actions.
- Investigation findings, with a chart and the CSV.
- How we built it: a diagram and one subsection per sponsor.
- What's different from HackAnalyzer and DevSpot.
- Honesty notes.
- Challenges: `echo` is not prompt-logprobs, EIS tiering, and message-bus timeouts.
- What's next.
- Links: repo, video, replay site, skill directory, CSV.

## 7. Verification
- **Layer smokes:** `scripts/smoke_all.sh` covers the Hour-0 curls, `apply.py --check`, and a hybrid query that returns DevSpot for "validate hackathon idea originality". Run it before every demo.
- **Pytest:**
  - Scoring monotonicity and abstention rules.
  - Schema maps on 3 fixtures per source.
  - Blocking recall on the `twangodev` `other_links` pairs.
  - The SSE contract: every event in `mock_run.jsonl` and the golden files validates as `AgentEvent`.
  - The hybrid body shape.
  - No mixing of `paraphrased` and `mixed` keys in GPTZero parsing.
- **Entity-resolution evaluation:** the Devpost-to-GitHub links in `twangodev` are free ground truth. Report precision and recall in the Rox pitch.
- **Benchmarks** (`scripts/bench_ideas.py`, `docs/benchmarks.md`), with expected originality:
  1. RAG study-buddy flashcards, 20 or lower.
  2. Fridge photo to recipes, 25 or lower.
  3. Journaling with an AI therapist, 25 or lower.
  4. Webcam sign-language-to-text, 25-40.
  5. Devpost originality checker by keywords, 25-45. **DevSpot or HackAnalyzer must appear in the top 5.**
  6. Carbon-aware CI scheduler, 45-65.
  7. A git-blame murder-mystery party game, 60-80.
  8. A shape-changing tactile display of forecast uncertainty for blind users, 70 or higher.
  9. "Uber for dogs": Voice abstains and crowding is still computed.
  10. A Spanish pitch: flagged for language.
  - Pass criterion: Spearman ρ of at least 0.8 on items 1-8.
- **Also check on every run:**
  - Mutations raise O1 on items 1-3.
  - Killing GitHub lowers E without crashing.
  - The fire drill is rejected.
- **Host parity:** run the same idea under both `ORCHESTRATOR` values. Event-type multisets and axis scores should match within tolerance.
- **Load:** 3 concurrent runs stay under 120 RPM with zero unhandled 429s.
- **Pre-demo checklist:**
  - Hotspot and a second laptop.
  - Replay URLs open.
  - Usage-stats headroom.
  - The Truss warmed past its scale-to-zero cold start.
  - The Slack channel visible.
  - `GPTZERO_MODE=live`.

## Sources
- agent-core ([repo](https://github.com/openJiuwen-ai/agent-core), tag v0.1.18: README, `pyproject.toml`, `docs/en/2.Development Guide/Multi-Agent/*`, `Advanced Usage/MCP Tool.md`, `Basic Functions/Connect to LLM.md`, `Session/Streaming Output.md`, `examples/multi_agent/*`), [PyPI openjiuwen](https://pypi.org/project/openjiuwen/)
- [Challenge issue #3067](https://github.com/openJiuwen-ai/jiuwenswarm/issues/3067), [SwarmSkills.md](https://github.com/openJiuwen-ai/jiuwenswarm/blob/develop/docs/en/SwarmSkills.md), [swarmskill-creator](https://github.com/openJiuwen-ai/jiuwenswarm/tree/develop/jiuwenswarm/resources/agent/workspace/skills/swarmskill-creator), jiuwenswarm `develop` `pyproject.toml`
- Baseten: [chat completions reference](https://docs.baseten.co/reference/inference-api/chat-completions), [vLLM example](https://docs.baseten.co/examples/vllm)
- Elastic: [workflow triggers](https://www.elastic.co/docs/explore-analyze/workflows/triggers), [templating](https://www.elastic.co/docs/explore-analyze/workflows/data/templating), [create workflow API](https://www.elastic.co/docs/api/doc/serverless/operation/operation-post-workflows-workflow), [run workflow API](https://www.elastic.co/docs/api/doc/kibana/operation/operation-post-workflows-workflow-id-run), [EIS](https://www.elastic.co/docs/explore-analyze/elastic-inference/eis), [Agent Builder MCP server](https://www.elastic.co/docs/explore-analyze/ai-features/agent-builder/mcp-server)
- Data: [alvanlii/devpost-hackathon-projects](https://huggingface.co/datasets/alvanlii/devpost-hackathon-projects), [twangodev/devpost-hacks](https://huggingface.co/datasets/twangodev/devpost-hacks), live probes of devpost.com, yc-oss.github.io and hn.algolia.com

### Critical Files for Implementation
- /Users/enkailiu/Projects/htn-2026/backend/app/orchestration/host.py
- /Users/enkailiu/Projects/htn-2026/backend/app/roles/conductor.py
- /Users/enkailiu/Projects/htn-2026/backend/app/search/hybrid.py
- /Users/enkailiu/Projects/htn-2026/backend/app/schemas/events.py
- /Users/enkailiu/Projects/htn-2026/elastic/apply.py