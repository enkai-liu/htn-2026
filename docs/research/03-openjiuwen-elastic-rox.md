> Generated during planning (Sat 2026-09-19 ~01:30 EDT). `[V]`/**[VERIFIED]** = checked against a live source; `[T]`/**[INFERRED]** = must be tested by the team.

# Hack the North 2026 — Sponsor Prize Research

**Researched 2026-09-19 (hackathon runs Sept 18–20, 2026).** Everything below is marked **[VERIFIED]** (read directly from the primary source) or **[INFERRED]** (my reasoning, not stated in docs). Where a source contradicted itself I say so.

---

## A. Huawei — openJiuwen Multi-Agent Challenge

### A0. The single most important finding: read the GitHub *issue*, not the README

The prize text points at the repo root, but **all challenge details live in GitHub issue #3067**, not the README. The README never mentions the hackathon at all.

- Challenge issue: https://github.com/openJiuwen-ai/jiuwenswarm/issues/3067 **[VERIFIED]** (title: `[Hack the North 2026] openJiuwen Multi-Agent Challenge`, opened 2026-08-14 by `LeoChen0296`, still OPEN)

### A1. The $40 API credits — it's OpenRouter, and it's first-come-first-served

Verbatim from issue #3067 **[VERIFIED]**:

> To access the sponsored API credits, please apply on **https://luma.com/mc7lijgs**
> 1. We provide API Credit through **OpenRouter**, check out more at OpenRouter docs.
> 2. Each team may apply **only once**.
> 3. A total of **200 API keys** are available, distributed on a **first-come, first-served basis while supplies last**.
> 4. Upon approval, you will receive an email with api key in it. The limit would be **40 USD**.
> 5. Teams that receive the sponsored API credit are **expected to submit their project to the Huawei openJiuwen Multi-Agent Challenge track**.

**Action now:** apply at the Luma link immediately — 200 keys, and you're already ~24h into the event. Note it's an *email-delivered* key, so there may be latency; don't block your build on it.

**Model choice:** OpenRouter is itself an OpenAI-compatible gateway, and JiuwenSwarm ships `OpenRouter` as a first-class `model_provider` value **[VERIFIED]**. So the credits path is frictionless. Your Baseten plan is *also* supported (see A5) but **use the OpenRouter credits for this track** — it's free money and the sponsor expects it.

### A2. Prizes and judging (issue #3067) **[VERIFIED]**

| Place | Prize |
|---|---|
| 1st | Huawei Watch GT 6 (per member) + internship opportunity with the openJiuwen team at **Huawei Toronto Research Center**, subject to interview |
| 2nd | Huawei FreeClip 2 Earbuds (per member) + exclusive Toronto Research Center office tour |

Published weighting (the issue body only explicitly numbers the first criterion before listing the rest):

- **Multi-Agent Collaboration — 30%** — quality of task decomposition, clarity/usefulness of agent roles, whether agents contribute *genuinely different* capabilities, agent communication and information sharing
- Plus: scenario creativity, demo completeness, technical implementation, reusability

Named collaboration patterns the sponsor explicitly calls out as good **[VERIFIED]**:
- Planner → Executor → Reviewer
- **Research → Critique → Synthesis** ← this is literally your product
- Developer → Tester → Debugger
- Debate / Cross-Check
- Dynamic Team Formation

And the framing question they want answered:

> "When AI agents can specialize, communicate, coordinate, and verify each other, what can they accomplish together that a single agent cannot?"

**Read on your idea:** an originality-assessment tool maps *exactly* onto Research → Critique → Synthesis, and "Debate / Cross-Check" is a natural fit for conflicting prior-art evidence. This is one of the best-matched idea/track pairs of the three.

### A3. JiuwenSwarm vs WorkSwarm — the naming is a genuine trap

This cost me several passes; here's the resolved picture.

| Thing | Status | Evidence |
|---|---|---|
| `openJiuwen-ai/jiuwenswarm` GitHub repo | **Exists, very active.** 6,521 stars, 1,105 forks, Apache-2.0, Python, **default branch is `develop` (not `main`)**, last push 2026-09-19, **1,414 open issues** | **[VERIFIED]** via `gh api` |
| `README.md` on **`main`** | Stale — describes **"JiuwenClaw"**, `pip install jiuwenclaw` | **[VERIFIED]** |
| `README.md` on **`develop`** | Current — "JiuwenSwarm", `pip install jiuwenswarm` | **[VERIFIED]** |
| `openJiuwen-ai/WorkSwarm` GitHub repo | **DOES NOT EXIST — 404.** Not in the org's 20 repos either. The issue hyperlinks the text "openJiuwen-ai/WorkSwarm" but the href points at the marketing site | **[VERIFIED]** (`gh api repos/openJiuwen-ai/WorkSwarm` → 404) |
| `workswarm` on PyPI | **Exists and is the actively-maintained line**: v0.2.6, 2026-09-12, 26.4 MB wheel, **96 dependencies**, `>=3.11,<3.14` | **[VERIFIED]** |
| `jiuwenswarm` on PyPI | v0.2.3, 2026-07-14, 20.5 MB wheel, 52 deps — **older than the repo's own v0.2.4.beta3** | **[VERIFIED]** |

**Naming lineage [INFERRED, high confidence]:** `jiuwenclaw` → `jiuwenswarm` → `workswarm`. The GitHub repo has not been renamed to match the newest PyPI package.

**Practical consequence:** if you want *source you can read and modify*, that only exists for JiuwenSwarm (`develop` branch). If you want the *newest* release, that's `pip install workswarm` — but with **no public source repo**, which is bad for a hackathon where you may need to debug internals at 3am. **I'd take `jiuwenswarm` from `develop` for readability.**

### A4. What JiuwenSwarm actually *is* (and why this matters)

**It is not a library like LangGraph or CrewAI. It is a full end-user application.** **[VERIFIED from README + sdks/README.md]**

```bash
pip install jiuwenswarm
jiuwenswarm-init
jiuwenswarm-start          # web UI at http://localhost:5173
pip install jiuwenswarm-tui && jiuwenswarm-tui   # separate terminal
```

It ships a web frontend, a TUI, a Gateway, an AgentServer, browser automation, scheduled tasks, memory subsystems, and **IM channel connectors** (Slack, Discord, Telegram, WhatsApp, Feishu, DingTalk, WeCom, Xiaoyi). It has two execution modes: **Agent mode** (single agent) and **Cluster mode** (Leader + specialized teammates) — `/mode team`.

The org has 20 repos; the relevant siblings:

| Repo | Stars | What it is |
|---|---|---|
| `jiuwenswarm` | 6,521 | The app (this challenge's reference framework) |
| `agent-core` | 429 | **The actual Python SDK** — `pip install openjiuwen`, v0.1.18 |
| `agent-studio` | 170 | Java, zero/low-code visual agent builder |
| `deepsearch` | 125 | Knowledge-enhanced deep search w/ chunk-level citations |
| `agent-protocol` | 86 | C++ SDKs for MCP and A2A |
| `agent-memory` | 61 | Long-term memory module |
| `skillhub` | 30 | Skill hosting/distribution |

(Full list verified via `gh api orgs/openJiuwen-ai/repos`.)

### A5. The programming model

**Model config** — `~/.jiuwenswarm/config/config.yaml`, created by `jiuwenswarm-init`, hot-reloads on save **[VERIFIED]**:

```yaml
model_name: deepseek-v4-flash
api_base: https://api.deepseek.com
api_key: sk-your-api-key
model_provider: OpenAI
```

Field mapping (frontend name → config.yaml name) **[VERIFIED]**: `model` → `model_name`, `model_provider` → `client_provider`.

Supported `model_provider` values: **`OpenAI`, `DeepSeek`, `DashScope`, `SiliconFlow`, `AscendAffinity`, `OpenRouter`** **[VERIFIED]**. Docs note: *"do not include `/chat/completions`; appended automatically"* and *"Most model providers offer OpenAI-compatible APIs. You can adjust `api_base` and `model` parameters based on your actual provider."*

**Baseten [INFERRED, high confidence]** — this should work:

```yaml
model_name: <your-baseten-model-id>
api_base: https://inference.baseten.co/v1
api_key: <baseten-key>
model_provider: OpenAI
```

Caveat **[VERIFIED]**: the default model *"Must support **Function Calling** and multi-turn dialogue."* Pick a Baseten model with solid tool-calling or the whole Cluster mode degrades. There's a **Test button** in the config panel — use it before you build anything. Also note multimodal (video/audio/vision) models support `OpenAI` provider *only*.

**SwarmFlow — the deterministic multi-agent Python API.** This is the closest thing to "define a team in code," and it's what I'd show a judge. From `docs/en/TUISwarmFlowGuide.md` **[VERIFIED]**:

- Scripts live at `scripts/workflow.py`; operators come from `from swarmflow import ...`
- A valid script needs top-level `META={...}` and `async def run(args)`
- The Leader executes it via the `swarmflow()` tool; TUI renders a live Phase/Node tree via `/swarmflows`
- Enable with `/swarmflow on`, plus `modes.team.jiuwen_team.enable_swarmflow: true` in config.yaml

Operators **[VERIFIED — signatures copied from the doc's table]**:

```python
async def agent(prompt, *, label=None, phase=None, schema=None, options=None)
async def parallel(thunks)              # fork-join, waits for all; failures -> None, never raises
async def pipeline(items, *stages)      # no-barrier; each item flows independently
async def map_parallel(items, fn)       # alias: pmap
def phase(title)
def log(message)
def compact(xs)                         # drop falsy
def flatten_filter(xs)
def agent_session(*, label=None, phase=None, instructions=None, options=None) -> AgentSession
def human_session(...) -> HumanSession
async def human(prompt, *, schema=None, label=None, phase=None, options=None)
async def workflow(name_or_path, args=None)   # at most ONE nest level
budget.total / budget.spent() / budget.remaining()
```

`options` keys **[VERIFIED]**: `label`, `phase`, `schema` (Pydantic model or JSON Schema), `model` (per-worker model override), `timeout`, `isolation` (`'worktree'` only), `agent_type` (named expert subagent). **Unknown keys fail fast.**

Smallest realistic example from the docs **[VERIFIED]**:

```python
await agent(
    "Analyze competitors",
    label="analyst",
    phase="research",
    options={"model": "strong-model", "timeout": 120},
)

s = agent_session(label="writer", phase="draft", options={"model": "fast-model"})
await s.send("Draft section 1", options={"timeout": 60})
```

**Sketch for your project [INFERRED — composed from the verified operator signatures above, not copied from docs]:**

```python
META = {"name": "originality-swarm", "phases": ["harvest", "critique", "synthesis"]}

async def run(args):
    idea = args["idea"]

    phase("harvest")
    hits = await parallel([
        lambda: agent(f"Search Devpost for prior art on: {idea}",       label="devpost",  schema=PriorArt),
        lambda: agent(f"Search GitHub for prior art on: {idea}",        label="github",   schema=PriorArt),
        lambda: agent(f"Search HN + Product Hunt for prior art: {idea}",label="social",   schema=PriorArt),
        lambda: agent(f"Search arXiv + YC for prior art on: {idea}",    label="academic", schema=PriorArt),
    ])
    hits = compact(hits)

    phase("critique")
    verdict = await agent(
        f"You are a hostile prior-art critic. Idea: {idea}\nEvidence: {hits}\n"
        "Find the strongest case that this is NOT original. Abstain if evidence is thin.",
        label="critic", schema=Critique)

    phase("synthesis")
    return await agent(f"Reconcile and produce a differentiation plan.\n{hits}\n{verdict}",
                       label="synthesizer", schema=Report)
```

**Streaming events for a live UI** — the SDK's `on_event` async callback receives versioned event records **[VERIFIED]**. The TUI subscribes to run events to render the Phase/Node tree, so the event stream is real and is the right hook for a "watch the agents collaborate" visualization.

**MCP support** — `config.yaml` → `mcp.servers` **[VERIFIED verbatim]**:

```yaml
mcp:
  servers:
    - name: my-local-tool
      enabled: true
      transport: stdio
      command: python
      args: ["path/to/server.py", "--transport", "stdio"]
      cwd: .
      env:
        LOG_LEVEL: INFO

    - name: remote-streamable
      enabled: true
      transport: streamable-http
      url: http://127.0.0.1:8000/mcp
      timeout_s: 60
```

Transports: `stdio`, `sse`, `streamable-http` (recommended). `headers` map supports `Authorization: Bearer ...`. Runtime commands: `/mcp list | reload | enable <name> | disable <name>`.

**This is the key to combining prizes A and B** — see the cross-cutting section at the end.

**Swarm Skills** — the sponsor's preferred "reusable" artifact, which maps directly onto the *reusability* judging criterion. Required directory structure **[VERIFIED]**:

```
your-team-skill/
├── SKILL.md              # YAML frontmatter; kind: team-skill; roles: (>=2 required)
├── roles/
│   ├── coordinator.md
│   ├── researcher.md
│   └── reviewer.md
├── workflow.md           # includes a mermaid flowchart
├── bind.md               # resource limits, constraints, failure/degraded modes
└── dependencies.yaml     # required tools/skills
```

`SKILL.md` frontmatter requires `name` (kebab-case, matching dir, conventionally `-swarm` suffix), `version`, `author`, `description` (WHAT/WHEN/NOT three-line structure, ≤1024 chars hard limit), **`kind: team-skill`** (note: `kind`, *not* `type`), and `roles` with ≥2 entries each having `id`, `purpose` (≤150 chars), `skills`, `tools`.

Each `roles/*.md` needs 5 mandatory sections **[VERIFIED]**: `## Identity` (first line must be a 1-line motto — the docs call this *"the most important anti-convergence mechanism"*), `## Success Criteria`, `## Boundary` (must contain `**Forbidden**` and `**Mandatory**`), `## Output Schema`, `## Inline Persona for Teammate`.

There's a built-in generator: `jiuwenswarm/resources/agent/workspace/skills/swarmskill-creator` **[VERIFIED — linked from issue #3067]**.

**Other integration docs present in `docs/en/`** **[VERIFIED by listing]**: `A2A.md`, `E2A-protocol.md`, `ACP_Client_Config.md`, `DistributedTeam.md`, `AgentTeamHumanInTheTeam.md`, `Memory.md`, `TaskMemory.md`, `ScheduledTasks.md`, `ToolPermissionsSecurity.md`, `AutoHarness.md`, `Symphony.md`, `SkillSelfEvolution.md`.

### A6. Gotchas — read this before you `pip install`

1. **Docs are in English.** `docs/en/` has ~55 English markdown files, well-written. Chinese is the *parallel* set in `docs/zh/`. This is not a Chinese-only-docs situation. **[VERIFIED]**
2. **It is heavy.** 20–26 MB wheel, 52–96 transitive deps. Budget 5–15 minutes for a cold install on conference wifi. **[VERIFIED from PyPI metadata]**
3. **Python `>=3.11,<3.14`.** Strict. `3.11.4` is the recommended pin for `agent-core`. **[VERIFIED]**
4. **Default branch is `develop`.** `git clone` gives you `develop`, but anyone browsing `main` on the web sees stale "JiuwenClaw" docs. Link `develop` in your README.
5. **1,414 open issues.** Expect rough edges. **[VERIFIED]**
6. **Tools require approval by default** — *"tools ask for approval before they run"*. In a live demo this will stall you. Change the policy via `docs/en/ToolPermissionsSecurity.md` **before** you rehearse. **[VERIFIED]**
7. **No REST API for embedding.** The SDKs are explicitly *"thin local child-process clients, not another Agent engine or an app-server… No JSON-RPC endpoint or persistent stdio service is involved."* Each call spawns a `jiuwenswarm-process`, talks over pipes, and exits. **Calls are not retried automatically.** **[VERIFIED verbatim from `sdks/README.md`]**
8. **SDKs are not published to PyPI/npm.** *"these packages are not claimed to be published"* — you install from the checkout: `python -m pip install ./sdks/python`. **[VERIFIED]**
9. **The TUI needs the backend running** — connects to `ws://127.0.0.1:19001/tui`. Two terminals. **[VERIFIED]**
10. **SwarmFlow `workflow()` nests at most one level.** **[VERIFIED]**
11. **Budget cap hit → run fails with no mid-run resume.** **[VERIFIED]** Relevant given you only have $40.
12. **No model vendor lock-in.** Any OpenAI-compatible `api_base` works. **[VERIFIED]**

Python SDK shape, if you do embed it **[VERIFIED verbatim]**:

```python
import asyncio
from jiuwenswarm_sdk import Client

async def main():
    client = Client()
    modes = await client.query("mode.list", deadline_seconds=60)
    result = await client.run({
        "input": "Explain the project without changing files.",
        "agent": {"name": "reviewer", "instructions": "Be concise; do not modify files."},
        "workspace": {"cwd": "/path/to/project"},
        "timeout_seconds": 120,
    }, deadline_seconds=180)
    print(result["status"], result["output"])

asyncio.run(main())
```

### A7. Honest recommendation: build on it, but at the Swarm Skill layer

**Recommendation: adopt JiuwenSwarm, but as a *thin* adoption — package your collaboration pattern as a Swarm Skill + SwarmFlow script, and keep your product's own backend separate.**

Reasoning:

- **"Reusability" is an explicit judging criterion, and the sponsor defined the exact artifact that satisfies it.** A Swarm Skill directory is a checkbox you can literally tick. Writing your own orchestrator means you have to *argue* for reusability; shipping a `originality-swarm/` skill directory means you *demonstrate* it. This is the single highest-leverage move on this track.
- **The sponsor explicitly blesses the "extend/integrate" path.** Issue #3067 lists permitted approaches including *"Integrate either framework with external APIs, applications, databases, services, or models"* and states *"Projects are **not expected to modify the core framework code**."* So you do not need to go deep. **[VERIFIED]**
- **It also explicitly permits another framework entirely**: *"Build using another multi-agent framework while demonstrating the collaboration principles of this challenge."* **[VERIFIED]** But — with two other tracks also awarding prizes to *"another framework"* projects, the differentiated play here is to actually use theirs. Judges from the openJiuwen team will reward it.
- **The risk is real though**: heavy install, an app-shaped (not library-shaped) architecture, a process-spawn SDK with no retries, and 1,414 open issues. Do **not** make JiuwenSwarm the critical path for your *demo UI*.

**Concrete split I'd ship:**
- Your own FastAPI/Next.js app owns the UI, the knowledge-graph viz, and Elasticsearch. This is what you demo. It never breaks.
- JiuwenSwarm Cluster mode + a `scripts/workflow.py` SwarmFlow script runs the actual multi-agent research/critique/synthesis. Stream its events into your UI.
- Package that as `originality-swarm/` Swarm Skill (SKILL.md + 4 roles + workflow.md + bind.md + dependencies.yaml) and say so loudly in your README.
- **Fallback:** keep a plain `asyncio.gather` orchestrator behind the same interface. If JiuwenSwarm wedges during demo, flip a flag. Do not skip this.

---

## B. Elastic — "Find the Signal: Best Use of Elasticsearch"

Prize **[VERIFIED from HTN 2026 Devpost]**: 1st = Meta Quest 3S, 2nd = Bose QuietComfort headphones. (No cash.)

### B1. Getting a cluster — pick Serverless, not start-local

| Option | Agent Builder? | Workflows? | EIS/Jina? | Graph API? | Verdict |
|---|---|---|---|---|---|
| **Elastic Cloud Serverless trial** | **Yes — GA** | **Yes — GA** | **Yes** | **NO** | **Use this** |
| Elastic Cloud Hosted trial | Yes (Enterprise tier) | Yes (9.4+) | Yes | Yes | Fine alternative |
| `start-local` Docker | Enterprise-licensed feature; 1-month trial license nominally covers it — **unverified end-to-end** | 9.3 preview / 9.4 GA | Needs Cloud Connect | Yes | Offline fallback only |

**[VERIFIED]** Trial terms from https://www.elastic.co/cloud/cloud-trial-overview: *"Start your free 14-day trial"*; *"a credit card is not required to sign up for the initial Elastic Cloud trial."* All Elastic Cloud trials have access to the Elastic Inference Service.

**[VERIFIED]** `start-local`:
```bash
curl -fsSL https://elastic.co/start-local | sh
```
Installs ES + Kibana in Docker, `localhost:9200` / `localhost:5601`, **one-month trial license including all features**, then reverts to Basic. Docs shout: *"DO NOT USE THESE INSTRUCTIONS FOR PRODUCTION DEPLOYMENTS."*

**[VERIFIED]** Agent Builder GA status: *"generally available in Elastic Cloud Serverless and the upcoming 9.3 release… for existing customers it's available on the **Enterprise Tier** in Cloud Hosted and self-managed."* Search results also state Agent Builder *"requires an Enterprise subscription."*

**Critical gotcha [VERIFIED]:** the **Graph explore API is "Unavailable" on Elastic Cloud Serverless** (it's "Generally available" on Elastic Stack). If your knowledge-graph viz depends on `_graph/explore`, Serverless will not work — see B6 for the workaround.

**HTN-specific Elastic starter repo / credits: NOT FOUND [UNVERIFIED].** I searched Elastic's community/devrel properties and found Elastic hackathons in Sydney, Singapore, and UNIHACK 2026, but **no Hack the North 2026 starter repo or promo code**. Ask at the Elastic booth — they very likely have a workshop link and possibly extended trial credits that simply aren't indexed.

### B2. Jina on Elastic — three routes, one is clearly best

Elastic acquired Jina AI; the models are now first-class.

**Route 1 (BEST — no API key needed): preconfigured EIS endpoints.** **[VERIFIED]**

```json
POST _inference/text_embedding/.jina-embeddings-v3
{
  "input": ["Rocky Mountain National Park"],
  "input_type": "ingest"
}
```

```json
POST _inference/rerank/.jina-reranker-v2-base-multilingual
{
  "input": ["puddle", "ocean", "cup of tea"],
  "query": "a large body of water"
}
```

Preconfigured endpoint IDs I confirmed: `.jina-embeddings-v3`, `.jina-reranker-v2-base-multilingual`, `.jina-reranker-v3` **[VERIFIED]**, plus `.elser-2-elastic` **[VERIFIED]**. One search result also referenced **`.jina-reranker-v3.5`** as "the recommended option" — **[UNVERIFIED]**, I could not confirm this on a primary docs page; the Search Labs blog lists only v2-base-multilingual and v3. **Enumerate what your cluster actually has with `GET _inference/_all` before you hardcode an ID.**

EIS model catalog **[VERIFIED]**: `jina-embeddings-v5-omni-small`, `jina-embeddings-v5-omni-nano`, `jina-embeddings-v5-text-small` (Preview), `jina-embeddings-v3` (Preview), Elastic Managed LLMs (`chat_completion`), ELSER. Availability: Serverless yes, Cloud Hosted yes, self-managed via **Cloud Connect**. Billing is token-based per million tokens.

**Route 2: bring your own Jina API key** (needed if you want a model EIS doesn't host). **[VERIFIED verbatim]**

```json
PUT _inference/rerank/jina_rerank_v3
{
  "service": "jinaai",
  "service_settings": {
    "api_key": "YOUR_JINA_API_KEY",
    "model_id": "jina-reranker-v3"
  },
  "task_settings": {
    "top_n": 10,
    "return_documents": true
  }
}
```

Embedding equivalent **[VERIFIED from docs description]**: `service: "jinaai"`, `service_settings.model_id: "jina-embeddings-v3"`, task type `text_embedding`.

**Route 3: `semantic_text` mapping** — the zero-effort path. **[VERIFIED verbatim]**

```json
{
  "mappings": {
    "properties": {
      "content": {
        "type": "semantic_text",
        "inference_id": "my-inference-endpoint",
        "search_inference_id": "my-search-inference-endpoint",
        "index_options": {
          "dense_vector": { "type": "bbq_disk" }
        },
        "chunking_settings": {
          "strategy": "word",
          "max_chunk_size": 120,
          "overlap": 40
        }
      }
    }
  }
}
```

Minimal version (uses the cluster default endpoint, auto-chunks, auto-embeds at ingest):
```json
{ "mappings": { "properties": { "content": { "type": "semantic_text" } } } }
```

**[VERIFIED]** Today `semantic_text` defaults to ELSER behind the scenes; Elastic has stated it *"will default to the `jina-embeddings-v3` endpoint on EIS in the near future."* Since the prize text explicitly says *"Jina dense vectors"*, **set `inference_id: ".jina-embeddings-v3"` explicitly** rather than relying on the default — it's one line and it makes your Jina usage legible to the judge.

### B3. Hybrid search query shape (2026)

**[VERIFIED verbatim from the Jina Reranker v3 tutorial]** — this is a real, working query:

```json
POST multilingual-rerank-demo/_search
{
  "retriever": {
    "text_similarity_reranker": {
      "retriever": {
        "rrf": {
          "retrievers": [
            {
              "standard": {
                "query": { "match": { "content": "How does suffering reveal hidden truth?" } }
              }
            },
            {
              "knn": {
                "field": "embedding",
                "query_vector": [0.0123, -0.0456, "...", 0.0089],
                "k": 20,
                "num_candidates": 100
              }
            }
          ],
          "rank_window_size": 50,
          "rank_constant": 20
        }
      },
      "field": "content",
      "inference_id": "jina_rerank_v3",
      "inference_text": "How does suffering reveal hidden truth?",
      "rank_window_size": 20
    }
  },
  "_source": ["id", "lang", "title", "content"]
}
```

**Adaptation for your corpus [INFERRED]:** if you use `semantic_text`, swap the `knn` leg for `{"standard": {"query": {"semantic": {"field": "content_semantic", "query": "..."}}}}` — that removes the need to compute `query_vector` client-side, which is a meaningful hackathon simplification.

**All 9 retriever types [VERIFIED]:** `standard`, `knn`, `rrf`, `linear`, `text_similarity_reranker`, `rescorer`, `rule`, `pinned`, **`diversify`** (*"reduces the results from another retriever by applying a diversification strategy"*). `diversify` is your MMR — directly useful for showing a *spread* of distinct prior-art clusters rather than 10 near-identical Devpost entries.

**Constraint [VERIFIED]:** when using retrievers you cannot use top-level `query`, `knn`, `search_after`, `terminate_after`, `sort`, or `rescore`. `linear` and `rrf` also support a multi-field format with automatic lexical/semantic field grouping at 50/50 normalization weighting.

**ES|QL hybrid equivalent [VERIFIED verbatim]** — worth showing a judge because it's newer and flashier:

```sql
FROM books METADATA _score, _id, _index
| FORK (WHERE KNN(description_vector, ?query_vector) | SORT _score DESC | LIMIT 100)
       (WHERE MATCH(description, ?query) | SORT _score DESC | LIMIT 100)
| FUSE
| SORT _score DESC
| LIMIT 100
| RERANK ?query ON CONCAT(title, "\n", description)
| SORT _score DESC
| LIMIT 10
| COMPLETION CONCAT("Summarize the following:\n", description)
  WITH { "inference_id" : "my_inference_endpoint" }
```

Weighted variant **[VERIFIED verbatim]**:
```sql
| FUSE LINEAR WITH { "weights": { "fork1": 0.7, "fork2": 0.3 }, "normalizer": "minmax" }
```
`FUSE` defaults to RRF with `score(doc) = 1 / (rank_constant + rank(doc))`, `rank_constant` = 60.

### B4. Agent Builder

**Status [VERIFIED]:** GA in Elastic Cloud Serverless and 9.3; Enterprise tier on Hosted/self-managed. Model-agnostic.

**Full API surface [VERIFIED]** (`{KIBANA_URL}` base; add `/s/<space>` prefix for non-default spaces):

```
GET    /api/agent_builder/tools
POST   /api/agent_builder/tools
GET    /api/agent_builder/tools/{id}
PUT    /api/agent_builder/tools/{toolId}
DELETE /api/agent_builder/tools/{id}
POST   /api/agent_builder/tools/_execute
GET|POST|PUT|DELETE /api/agent_builder/skills[/{skillId}]
GET|POST|PUT|DELETE /api/agent_builder/agents[/{id}]
POST   /api/agent_builder/agents/{agent-id}/consumption
POST   /api/agent_builder/converse
POST   /api/agent_builder/converse/async        <- streaming
GET|POST|DELETE /api/agent_builder/conversations[/{id}]
GET    /api/agent_builder/a2a/{agentId}.json    <- A2A agent card
POST   /api/agent_builder/mcp                   <- MCP server
```

**End-to-end worked example [VERIFIED verbatim from the API tutorial]:**

```bash
export KIBANA_URL="your-kibana-url"
export API_KEY="your-api-key"

# 1) Create an ES|QL tool (note the ?param syntax)
curl -X POST "${KIBANA_URL}/api/agent_builder/tools" \
     -H "Authorization: ApiKey ${API_KEY}" \
     -H "kbn-xsrf: true" \
     -H "Content-Type: application/json" \
     -d '{
       "id": "example-books-esql-tool",
       "type": "esql",
       "description": "Query tool for finding longest books before a target year",
       "configuration": {
         "query": "FROM kibana_sample_data_agents | WHERE DATE_EXTRACT(\"year\", release_date) < ?maxYear | SORT page_count DESC | LIMIT ?limit",
         "params": {
           "maxYear": { "type": "integer", "description": "Maximum year (exclusive)" },
           "limit":   { "type": "integer", "description": "Result limit" }
         }
       }
     }'

# 2) Create an agent
curl -X POST "${KIBANA_URL}/api/agent_builder/agents" \
     -H "Authorization: ApiKey ${API_KEY}" -H "kbn-xsrf: true" \
     -H "Content-Type: application/json" \
     -d '{
       "id": "books-search-agent",
       "name": "Books Search Helper",
       "description": "Search and analyze our book collection",
       "labels": ["books","sample-data","search"],
       "avatar_color": "#BFDBFF",
       "avatar_symbol": "B",
       "configuration": {
         "instructions": "Assist users analyzing book data ...",
         "tools": [{ "tool_ids": [
             "example-books-esql-tool",
             "platform.core.search",
             "platform.core.list_indices"
         ]}]
       }
     }'

# 3) Converse
curl -X POST "${KIBANA_URL}/api/agent_builder/converse" \
     -H "Authorization: ApiKey ${API_KEY}" -H "kbn-xsrf: true" \
     -H "Content-Type: application/json" \
     -d '{ "input": "What books do we have?", "agent_id": "books-search-agent" }'
```

Converse response shape **[VERIFIED]** — note `steps[]` contains `reasoning` and `tool_call` entries, which is **exactly the data you need to animate agent collaboration in a UI**:

```json
{
  "conversation_id": "e5b4e3ff-...",
  "round_id": "145aeacf-...",
  "status": "completed",
  "steps": [
    { "type": "reasoning", "reasoning": "..." },
    { "type": "tool_call", "tool_id": "platform.core.search", "params": {}, "results": [] }
  ],
  "model_usage": { "input_tokens": 30345, "output_tokens": 704 },
  "response": { "message": "Your collection contains 6 books..." }
}
```

Built-in tools seen in docs **[VERIFIED]**: `platform.core.search`, `platform.core.list_indices`, `platform.core.get_index_mapping`, `platform.core.get_document_by_id`.

**Tool types [VERIFIED]:**
- **`esql`** — parameterized ES|QL, `?param_name` interpolation. Example from docs: `FROM books | WHERE MATCH(title, ?search_terms) | KEEP title, author, year | LIMIT 10`
- **`index_search`** — natural-language search over an index pattern. Config fields: **`pattern`** (required, e.g. `logs-myapp-*`), `row_limit` (optional), `custom_instructions` (optional). It *"automatically determine[s] optimal search strategy (full-text, semantic)"*. **[VERIFIED — though the docs page does not expose the literal `type` string; confirm via `GET /api/agent_builder/tools`]**
- **workflow tools** — invoke an Elastic Workflow. *"Selecting a workflow automatically pulls its definition into the tool configuration"*; inputs are auto-detected from the workflow YAML; supports **"Require user confirmation."** The docs UI-only page **does not expose the JSON schema** — **[UNVERIFIED]** for programmatic creation. Create it in the Kibana UI, then `GET /api/agent_builder/tools/{id}` to read back the exact shape.

**MCP server [VERIFIED]:**
```
{KIBANA_URL}/api/agent_builder/mcp
{KIBANA_URL}/s/{SPACE_NAME}/api/agent_builder/mcp
```
Auth: `Authorization: ApiKey ${API_KEY}` (API keys for Stack + Serverless; OAuth 2.1 for Serverless only).

**Important limitation [VERIFIED verbatim]:** *"Only the tools are exposed through the MCP server — Elastic's agents are separate from that."*

Client config **[VERIFIED verbatim]**:
```json
{
  "mcpServers": {
    "elastic-agent-builder": {
      "command": "npx",
      "args": ["mcp-remote",
               "https://your-kibana.kb.company.io/api/agent_builder/mcp",
               "--header", "Authorization:${AUTH_HEADER}"],
      "env": { "AUTH_HEADER": "ApiKey <ELASTIC_API_KEY>" }
    }
  }
}
```

**A2A [VERIFIED]:** agent cards at `GET /api/agent_builder/a2a/{agentId}.json`.

**LLM backend [VERIFIED]:** default is the **Elastic Managed LLM on EIS** — zero setup on Serverless/Hosted. Self-managed must configure its own. To use a custom model: create an inference endpoint with the **`chat_completion`** task type, or a Kibana connector — OpenAI connector with provider **"Other (OpenAI Compatible Service)"**. Set the default via **GenAI Settings → Default AI Connector** (9.3+) or **Model management / Feature settings → Default model** (9.4+).

**Baseten answer [VERIFIED]:** yes — the Converse API accepts a per-request **`inference_id`** *or* **`connector_id`** override (mutually exclusive). So you can register Baseten once as an OpenAI-compatible connector and point individual conversations at it. Elastic's own docs recommend Gemini 3.1 Pro / Claude 4.6 Opus (reasoning), GPT-5.2 / Claude 4.6 Sonnet (balanced), Claude 4.5 Haiku / Gemini 3.0 Flash (throughput).

### B5. Elastic Workflows

**Status [VERIFIED]:** **GA in Elastic Stack 9.4+ and all Serverless versions.** Preview in 9.3 (manual enable). Managed workflows 9.5+. Template library is preview.

Enable **[VERIFIED]**: Advanced Settings → **`workflows:ui:enabled`** → toggle on, save, reload. (9.5+/Serverless also has `workflows:ui:showManagedWorkflows`.) Privileges under **Analytics → Workflows** (`All` or `Read`).

**Minimal YAML [VERIFIED]:**
```yaml
name: National Parks Demo
description: Creates an index, loads data, searches it, and displays results
enabled: true
consts:
  indexName: national-parks

triggers:
  - type: manual

steps:
  - name: get_index
    type: elasticsearch.indices.exists
    with:
      index: '{{ consts.indexName }}'

  - name: check_if_index_exists
    type: if
    condition: 'steps.get_index.output: true'
    steps:
      - name: delete_index
        type: elasticsearch.indices.delete
        with:
          index: '{{ consts.indexName }}'

  - name: search_park_data
    type: elasticsearch.search
    with:
      index: '{{ consts.indexName }}'
```

Templating: `{{ steps.<name>.output }}` and `{{ consts.var }}`. Triggers: **manual**, **scheduled** (interval or cron), **alert** (fires on a Kibana alerting rule).

**Step type index [VERIFIED — from the official reference]:**

- **AI:** `ai.prompt`, `ai.classify`, `ai.summarize`, **`ai.agent`** (*"Invoke an Elastic Agent Builder agent as a step"*)
- **Elasticsearch:** `elasticsearch.search`, `elasticsearch.index`, `elasticsearch.bulk`, `elasticsearch.update`, `elasticsearch.esql.query`, `elasticsearch.indices.create|delete|exists`, `elasticsearch.request` (escape hatch)
- **Data:** `data.aggregate`, `data.concat`, **`data.dedupe`**, `data.filter`, `data.find`, `data.map`, `data.parseJson`, `data.regexExtract`, `data.regexReplace`, `data.set`, `data.stringifyJson`
- **Flow control:** `if`, `switch`, `foreach`, `while`, `parallel`, `loop.break`, `loop.continue`, `wait`, **`waitForApproval`**, **`waitForInput`**
- **HTTP/Console:** `http`, `console`
- **Kibana:** `kibana.request`, `kibana.SetAlertsStatus`, `kibana.SetAlertTags`
- **Composition (tech preview):** `workflow.execute`, `workflow.executeAsync`, `workflow.fail`, `workflow.output`
- **Connectors:** dynamic `<connector>.<action>` — e.g. `slack.postMessage`, `jira.createIssue`
- Plus large `cases.*` and `security.*` families

Slack/HTTP examples **[VERIFIED]**:
```yaml
- name: post_message_to_slack
  type: slack_api.postMessage
  connector-id: <connector-id>
  with:
    channelNames: ['#alerts']
    text: 'Workflow finished successfully'

- name: isolate
  type: http
  if: "steps.request_approval.output.response.approved : true"
  connector-id: "edr-connector"
  with:
    method: "POST"
    url: "https://edr.example.com/isolate"
    body:
      host: "{{ event.alerts[0].host.name }}"
```

Note the pattern **[VERIFIED]**: *"the `http` step is the escape hatch: it can securely call any API endpoint, with credentials supplied by a connector rather than written into the YAML."*

**Your "close the loop" idea: feasibility = HIGH.** Every primitive you asked for exists. **[VERIFIED that the primitives exist; [INFERRED] that this exact composition works]**

```yaml
name: originality-watch
enabled: true
triggers:
  - type: manual        # workflow A: run once at analysis time
steps:
  - name: index_analyzed_idea
    type: elasticsearch.index
    with:
      index: ideas
      document:
        text: "{{ inputs.idea }}"
        verdict: "{{ inputs.verdict }}"
        owner_email: "{{ inputs.email }}"
---
name: originality-daily-watch
enabled: true
triggers:
  - type: scheduled
    with: { every: "24h" }
steps:
  - name: find_new_similar
    type: elasticsearch.search
    with:
      index: prior_art
      body: { retriever: { rrf: { retrievers: [ ... ] } } }
  - name: dedupe_hits
    type: data.dedupe
    with: { items: "{{ steps.find_new_similar.output.hits.hits }}" }
  - name: summarize
    type: ai.summarize
    with: { content: "{{ steps.dedupe_hits.output }}" }
  - name: notify
    type: slack_api.postMessage
    connector-id: <connector-id>
    with:
      channelNames: ['#idea-watch']
      text: "New similar project detected: {{ steps.summarize.output }}"
```

Two things make this land with judges: (a) the **scheduled trigger** genuinely closes the loop without a human, and (b) **`data.dedupe`** and **`ai.summarize`** are native steps, so your "action" isn't a thin `http` POST — it's real pipeline logic. Register the first workflow as an Agent Builder **workflow tool** so the agent itself decides to arm the watch. That's the "beyond RAG with a chatbot" story in one sentence.

### B6. Analytics features for originality scoring

**`significant_terms` / `significant_text`** — the single best-matched feature for "what's overused vs. what's rare." **[VERIFIED verbatim]**

```json
{
  "query": { "match": { "content": "elasticsearch" } },
  "aggs": {
    "sample": {
      "sampler": { "shard_size": 100 },
      "aggs": {
        "keywords": {
          "significant_text": { "field": "content", "filter_duplicate_text": true }
        }
      }
    }
  }
}
```

With a custom background set **[VERIFIED]**:
```json
{
  "query": { "match": { "content": "madrid" } },
  "aggs": {
    "tags": {
      "significant_text": {
        "field": "content",
        "background_filter": { "term": { "content": "spain" } }
      }
    }
  }
}
```

`significant_text` vs `significant_terms` **[VERIFIED]**: designed for `text` fields, needs no fielddata/doc-values, and **re-analyzes on the fly so it can filter duplicate sections of noisy text** — ideal for scraped Devpost/HN content. No licensing restriction noted.

**This is your originality metric.** Foreground = the 50 nearest neighbours of the user's idea; background = the whole corpus. Terms that are significant in the neighbourhood are the clichés ("RAG chatbot", "Devpost scraper"); terms *absent* are the whitespace. Frame that as the score and you have a defensible number instead of an LLM vibe.

**Crowding over time [VERIFIED — ES|QL `CATEGORIZE` form]:**
```sql
FROM prior_art
| WHERE MATCH(description, ?idea)
| STATS count = COUNT(*) BY year = DATE_EXTRACT("year", created_at)
| SORT year ASC
```
```sql
FROM logs-*
| WHERE @timestamp > NOW() - 1 hour
| STATS count = COUNT(*) BY category = CATEGORIZE(message)
| SORT count DESC
| LIMIT 20
```

`categorize_text` aggregation **[VERIFIED]**: multi-bucket, uses the `ml_standard` tokenizer built for machine-generated text, only the **first 100 analyzed tokens** are used, supports regex filters to exclude sequences. Best on machine-generated text — so **[INFERRED]** it's a weaker fit for human-written project blurbs than `significant_text`. Use it for the log/scrape-failure side, not the idea side.

**Ingest pipelines for messy scraped HTML [VERIFIED that all three processors exist]:**
- `html_strip` — strip tags from scraped pages
- `fingerprint` — *"generates one or more fingerprints from an incoming document, which could aid in finding duplicates, detecting plagiarism, or clustering similar documents"* — your near-dupe key
- `inference` with `model_id: lang_ident_model_1` — language detection **[VERIFIED example]**:

```json
"processors": [
  { "inference": {
      "model_id": "lang_ident_model_1",
      "target_field": "ml",
      "field_map": { "content": "text" } } },
  { "set": { "field": "detected_language", "value": "{{ml.predicted_value}}" } }
]
```
Note **[VERIFIED]**: accuracy improves with longer text; reasonable on ~50-char samples for some languages. This directly serves the prize's "multilingual text" callout.

**`more_like_this`** — exists, classic "find similar docs by example." I did not pull its exact syntax this pass — **[UNVERIFIED]** for exact params. **[INFERRED]** the `rrf` + `semantic` retriever combo dominates it in 2026; use MLT only as a cheap fallback.

**Graph explore API — the one to be careful about. [VERIFIED]**
- `GET|POST /{index}/_graph/explore`
- **Elastic Stack: Generally available. Elastic Cloud Serverless: Unavailable.**
- Subscription tier not stated on the page I read — **[UNVERIFIED]** (historically Platinum+).
- I could **not** retrieve a verbatim request body (vertices/connections/controls) — **[UNVERIFIED]**.

**Recommendation [INFERRED]:** do **not** build your knowledge-graph viz on `_graph/explore`. If you take the Serverless trial (which you should, for Agent Builder + Workflows GA), the API isn't there. Build the graph from a **`significant_terms` sub-aggregation** instead — nest `significant_terms` under a `terms` agg on technology/theme, and you get co-occurrence edges with relevance-weighted scoring, which is precisely what Graph does under the hood, on any tier, on any deployment.

### B7. Official clients

**Python** — `elasticsearch` 9.x. Bulk helpers **[VERIFIED params]**: `helpers.bulk()` is a wrapper around `streaming_bulk()` that consumes the whole iterable and returns summary info; `streaming_bulk()` params include `chunk_size` (**default 500**), `max_chunk_bytes` (**default 104857600**), `raise_on_error`, `expand_action_callback`, `raise_on_exception`, `max_retries`, `initial_backoff`, `max_backoff`, `yield_ok`, `ignore_status`, `retry_on_status`. Also `parallel_bulk()` and `helpers.scan()`. All accept a generator, so you can stream a scrape straight in without materializing it. `async_bulk` — **[UNVERIFIED]**, not confirmed on a 9.x page; the async helpers live under `elasticsearch.helpers` in the asyncio client.

Docs note: `https://elasticsearch-py.readthedocs.io/en/stable/helpers.html` now **302-redirects** to `https://www.elastic.co/docs/reference/elasticsearch/clients/python/client-helpers`.

**JavaScript** — `@elastic/elasticsearch` with `client.helpers.bulk({ datasource, onDocument })`. **[UNVERIFIED]** this pass — I did not fetch the JS helper page.

---

## C. Rox — Best AI Agent

Prize **[VERIFIED from HTN 2026 Devpost]**: **$10,000 first / $2,000 second.** This is by far the largest cash prize of the three and the only one with meaningful money.

### C1. Who Rox is

**[VERIFIED]** Rox (rox.com) builds AI-native revenue/GTM agents. Founded 2024. **Hit a $1.2B valuation in March 2026** in a General Catalyst–led round (previously ~$39M raised; investors include Sequoia, GV). Customers named publicly: MongoDB, Ramp, New Relic, Confluent, Redis, OpenAI. 35+ revenue teams in private beta.

Product framing **[VERIFIED]**: a "Revenue Operating System" built on **swarms of autonomous AI agents** covering lead-to-cash. Sequoia's thesis post is literally titled *"Every Seller Needs an Agent Swarm."* The **Agent Swarm** is a fleet of always-on agents assigned per account: monitor accounts while reps are offline, generate personalized outreach, update CRM (contact activity, notes, deal progress). They are **warehouse-native** — data stays in the customer's warehouse rather than being copied out. Integrations: Salesforce, HubSpot, Gmail, Outlook, Slack.

**The signal that matters most [VERIFIED]:** co-founder and AI Lead **Avanika Narayan** is a Stanford CS PhD from **Chris Ré's Hazy Research lab**, and her PhD work was *literally on this*: **"Can Foundation Models Wrangle Your Data?"** (Narayan, Chami, Orr, Ré — VLDB 2023, https://www.vldb.org/pvldb/vol16/p738-narayan.pdf; code at https://github.com/HazyResearch/fm_data_tasks).

The five tasks in that paper **[VERIFIED]**:
1. **Entity matching**
2. **Data imputation**
3. **Error detection**
4. **Schema matching**
5. **Information extraction**

**This is not a coincidence — the Rox prize text is a restatement of her thesis.** "Handle unstructured information, incomplete datasets, conflicting sources, or noisy data… data cleaning and validation, multi-source resolution, intelligent error handling, robust decision-making under uncertainty" maps 1:1 onto entity matching / imputation / error detection / schema matching. If you name these tasks explicitly in your README and demo, you are speaking the judge's own vocabulary. I'd go as far as citing the paper.

Rox's own framing, per the OpenAI case study **[VERIFIED via search result]**: the platform *"combines fragmented data into a unified system of record and delivers insights through always-on AI agent swarms."* (The OpenAI page itself returned HTTP 403 to my fetcher — **[UNVERIFIED]** beyond the indexed snippet.)

### C2. Rox hackathon history — and an important warning

| Event | Prize | Amount | Winner found? |
|---|---|---|---|
| **TreeHacks 2025** | **"Best Agents Hack"** | **$7,000 cash** | No |
| **Hack the North 2025** | **"Rox: Best AI Agent"** | (amount not shown on prize list) | **No — see below** |
| Hack the North 2026 | "Rox: Best AI Agent" | $10,000 / $2,000 | N/A (running now) |

**[VERIFIED]** Rox *was* a HTN 2025 sponsor — "Rox: Best AI Agent" appears verbatim in the HTN 2025 Devpost sponsor prize list (alongside Amazon, Cerebras, Cohere, CSE, Cua, Databricks, ETHGlobal, Federato, Genesys, Graphite, Groq, Martian, QNX, RBC, Ripple, Shopify, Snap, Solana, VAPI, Warp, Windsurf, Y Combinator, and four MLH prizes).

**[VERIFIED] But no Devpost project is tagged with it.** I opened **17 of the 24** HTN 2025 winner project pages and read their Winner badges. Every badge resolved to a different sponsor:

- Deepsint → Cohere · Puppeteer → Warp + Finalist · CourseIntelligence → Databricks · RepoStory → Cerebras · Pew Pew → CSE · Network Threat Explorer → CSE · YeetThePacket → CSE · Solshare → Cohere + Solana · Fragments → Amazon + Cohere · Sematic → Amazon · TradeOff → Amazon · TrueCount → ETHGlobal · Tango → Graphite + Finalist · Maatchaa, Sauron, Lattice, SpeakEasy, Stu3dio, DUM-E → Finalists only

The 5 unchecked (ChessMate, ROSS, Coach Bob!, S-KBD67, SOTA Computer Use Agent Challenge) are robotics/AR/hardware/Cua-track projects — implausible Best-AI-Agent winners.

**[INFERRED, moderate-to-high confidence] Rox judges and awards *off* Devpost.** At TreeHacks 2025 their submission instructions were explicit **[VERIFIED verbatim]**: *"Teams must submit a concise write-up description within 2 hours of code submission. Optional system diagrams may also be included. Submissions can be provided via a publicly available URL in the Devpost submission or emailed to **alex@rox.com** with the subject line '[TreeHacks]'."*

**ACTION — do this today:** go to the Rox booth and ask (a) whether there is a separate submission channel or required write-up, and (b) whether there's a deadline *earlier* than the Devpost deadline ("within 2 hours of code submission" at TreeHacks is aggressive). **This is the highest-value 10 minutes available to your team on the $10K track.** Losing a $10K prize on a submission technicality would be the worst possible outcome.

Also note TreeHacks' stated criteria **[VERIFIED]**: technical complexity, creativity, functionality, **and UI/UX design**. HTN 2026's published criteria drop UI/UX for "practical utility," but Rox has historically cared about polish — budget real time for the front end.

### C3. Concrete messy-data techniques your originality agent can demonstrate

Your idea is genuinely well-suited here — prior-art search across Devpost/GitHub/PH/HN/YC/arXiv *is* a multi-source entity resolution problem. Mapped onto the Narayan taxonomy:

**1. Entity resolution / multi-source resolution** — the flagship demo.
The same project appears as a Devpost entry, a GitHub repo, a Product Hunt launch, and an HN thread under four different names. Merge into one canonical prior-art entity.
- Blocking: `fingerprint` ingest processor on normalized title + `significant_terms` keys, to avoid O(n²)
- Candidate generation: `rrf` retriever over `semantic_text` + BM25
- Pairwise decision: LLM adjudication with a structured verdict (`same` / `different` / `insufficient_evidence`)
- Show the merge in the UI: four source cards collapsing into one entity, with provenance links preserved
- **Say the words "entity matching"** — it's task #1 in the judge's own paper

**2. Conflicting-source handling.** GitHub says last commit 2 years ago; Product Hunt says "actively maintained"; launch dates disagree by 8 months. Implement an explicit **source-reliability prior** (e.g. GitHub commit timestamps > self-reported PH copy) plus a recency weight, and **show the conflict in the UI rather than silently picking one.** Surfacing disagreement reads as rigor; hiding it reads as a demo.

**3. Near-duplicate detection.** `fingerprint` processor + the **`diversify` retriever** (MMR) so results show 10 *distinct* prior-art clusters instead of 10 copies of the same template project.

**4. Missing fields / imputation.** Devpost entries routinely lack a tech stack; GitHub repos lack descriptions. Impute from README + commit history, and **mark every imputed field visually as inferred**. Task #2 in the paper.

**5. Error detection.** Scraped HTML junk, truncated blurbs, non-English text, SEO spam listings. Pipeline: `html_strip` → `inference`/`lang_ident` → length/quality heuristics → quarantine index. Task #3.

**6. Schema matching.** Devpost, GitHub, PH, HN, arXiv and YC all have different field names for roughly the same concepts. Write an explicit mapping layer to one canonical schema and *show the mapping table in your demo*. Task #4 — and it's the one most teams will skip, so it differentiates you.

**7. Confidence calibration with abstention.** This is the one judges remember. Make **"insufficient evidence"** a first-class output. An originality verdict backed by 2 weak sources should say so, not emit a confident 73/100. Report a confidence interval, and require N independent sources before asserting "this already exists."

**8. Retry / fallback when a source fails.** GitHub rate-limits, HN Algolia times out, Devpost blocks your scraper. Degrade gracefully, tell the user *which* sources were consulted and which failed, and lower confidence accordingly. **This is also directly worth points on the Huawei track** ("failure handling… degrade gracefully") — one implementation, two prizes.

**9. "Meaningful actions" — not just an answer.** The prize says *take meaningful actions*. Ship at least two of:
- **Arm a watch**: index the analyzed idea + create the scheduled Elastic Workflow that re-runs the search daily and Slacks the user when a new similar project appears (section B5). This is the strongest single action because it's autonomous and recurring.
- **Write back to the corpus**: the analyzed idea becomes prior art for the next user. Self-improving dataset; great demo beat.
- **Draft a differentiated pitch**: don't just score originality — generate the rewritten positioning that moves the idea into the whitespace `significant_terms` identified.
- **Open a GitHub issue / PR** with a differentiation README on the user's repo.
- **Email/Slack digest** of the prior-art landscape.

**A note on scope:** this is 36 hours and you're ~12 in. Six sources done shallowly will lose to **three sources with real entity resolution, visible conflict handling, and a working watch**. Depth on the messy-data story is what the Rox judges are scoring.

---

## Cross-cutting: how to win all three with one build

The three tracks are unusually compatible, and there's one architectural move that makes the overlap real rather than cosmetic:

**JiuwenSwarm supports MCP over `streamable-http` with an `Authorization` header. Elastic Agent Builder *is* an MCP server that exposes its tools at `{KIBANA_URL}/api/agent_builder/mcp` with `Authorization: ApiKey ...`.** **[VERIFIED on both sides independently; the composition is [INFERRED] but the interfaces match exactly.]**

So in `~/.jiuwenswarm/config/config.yaml`:

```yaml
mcp:
  servers:
    - name: elastic-agent-builder
      enabled: true
      transport: streamable-http
      url: https://<your-kibana>.kb.<region>.cloud.es.io/api/agent_builder/mcp
      headers:
        Authorization: ApiKey <ELASTIC_API_KEY>
      timeout_s: 60
```

Now your Huawei-track multi-agent swarm calls your Elastic-track ES|QL and hybrid-search tools natively, and the Elastic Workflow closes the loop with a real action for Rox. One system, three narratives:

- **Huawei** sees: Leader decomposes → 4 specialist researchers in parallel → critic cross-checks → synthesizer; packaged as a reusable Swarm Skill; live Phase/Node event stream in the UI.
- **Elastic** sees: messy scraped multilingual HTML → ingest pipeline (`html_strip` + `lang_ident` + `fingerprint`) → `semantic_text` with `.jina-embeddings-v3` → `rrf` + `text_similarity_reranker` with the Jina reranker → `significant_text` for the originality score → Agent Builder tools exposed over MCP → Workflow that arms a daily watch and Slacks the user.
- **Rox** sees: entity resolution across 4+ sources, explicit conflict handling, calibrated abstention, graceful source failure, and an agent that *takes an action* (arms a recurring watch, writes back to the corpus, drafts the differentiated pitch).

**Sequencing advice given the clock:** build the Elastic layer first (it's the load-bearing data spine and the most demo-able), wire Rox's messy-data story into it as you ingest, and add the JiuwenSwarm orchestration layer last with a plain-asyncio fallback behind the same interface. Do not let the heaviest, least-mature dependency sit on your critical path.

---

## Open questions and unverified items

Flagging these honestly so you don't build on sand:

1. **Rox's HTN 2026 submission channel** — likely a separate write-up, possibly to `alex@rox.com`, possibly on a tighter deadline. **Go ask the booth.** Highest-value unknown by far.
2. **Rox HTN 2025 winner** — not determinable from Devpost badges (17/24 checked, none tagged Rox). Ask Rox directly who won and what they liked.
3. **`.jina-reranker-v3.5`** — appeared in one search snippet as "recommended," not confirmed on a primary docs page. Run `GET _inference/_all` on your actual cluster.
4. **Graph explore API subscription tier** — confirmed Unavailable on Serverless, but the exact tier on Stack is unconfirmed, and I never retrieved a verbatim request body. My advice is to avoid it entirely (use nested `significant_terms`).
5. **Agent Builder on `start-local`** — it's an Enterprise-tier feature and `start-local` grants a 1-month trial license "including all features," but I could not verify end-to-end that Agent Builder actually initializes there. **Do not discover this at 4am — test Serverless first.**
6. **Workflow tool JSON schema** for programmatic creation — not exposed in docs. Create in the Kibana UI, then `GET /api/agent_builder/tools/{id}` to read the real shape.
7. **Elastic HTN 2026 starter repo / credits** — none found in public indexes. Ask at the booth.
8. **Baseten + JiuwenSwarm** — high-confidence inference from the "any OpenAI-compatible `api_base`" docs, not an explicitly documented integration. Verify with the config panel's **Test** button in the first 10 minutes. And remember the sponsor credits are **OpenRouter**, not Baseten, for the Huawei track.
9. **`async_bulk`** in elasticsearch-py 9.x and the **JS client bulk helper** — not verified this pass.
10. **HTN 2025 Rox prize amount** — an early fetch of the 2025 Devpost returned "$10,000/$2,000," but that matched the 2026 figures in my prompt too closely to trust; the verbatim 2025 prize list showed only the title. Treat 2025's amount as unknown.

**Sources:**
- [openJiuwen-ai/jiuwenswarm](https://github.com/openJiuwen-ai/jiuwenswarm) · [Challenge issue #3067](https://github.com/openJiuwen-ai/jiuwenswarm/issues/3067) · [API credits signup](https://luma.com/mc7lijgs) · [openJiuwen WorkSwarm](https://www.openjiuwen.com/en/workswarm) · [agent-core](https://github.com/openJiuwen-ai/agent-core) · [SwarmSkills docs](https://github.com/openJiuwen-ai/jiuwenswarm/blob/develop/docs/en/SwarmSkills.md) · [swarmskill-creator](https://github.com/openJiuwen-ai/jiuwenswarm/tree/develop/jiuwenswarm/resources/agent/workspace/skills/swarmskill-creator)
- [Hack the North 2026 Devpost](https://hackthenorth2026.devpost.com/) · [Hack the North 2025 Devpost](https://hackthenorth2025.devpost.com/) · [TreeHacks 2025 Devpost](https://treehacks-2025.devpost.com/)
- [Agent Builder GA](https://www.elastic.co/search-labs/blog/agent-builder-elastic-ga) · [Agent Builder Kibana APIs](https://www.elastic.co/docs/explore-analyze/ai-features/agent-builder/kibana-api) · [API tutorial](https://www.elastic.co/docs/explore-analyze/ai-features/agent-builder/agent-builder-api-tutorial) · [MCP server](https://www.elastic.co/docs/explore-analyze/ai-features/agent-builder/mcp-server) · [MCP blog](https://www.elastic.co/search-labs/blog/elastic-mcp-server-agent-builder-tools) · [Models](https://www.elastic.co/docs/explore-analyze/ai-features/agent-builder/models) · [ES|QL tools](https://www.elastic.co/docs/explore-analyze/ai-features/agent-builder/tools/esql-tools) · [Index search tools](https://www.elastic.co/docs/explore-analyze/ai-features/agent-builder/tools/index-search-tools) · [Workflow tools](https://www.elastic.co/docs/explore-analyze/ai-features/agent-builder/tools/workflow-tools)
- [Workflows setup](https://www.elastic.co/docs/explore-analyze/workflows/get-started/setup) · [Step type index](https://www.elastic.co/docs/explore-analyze/workflows/reference/step-types) · [Workflows blog](https://www.elastic.co/search-labs/blog/elastic-workflows-automation)
- [Jina Reranker v3 tutorial](https://www.elastic.co/search-labs/tutorials/jina-tutorial/jina-reranker-v3) · [jina-embeddings-v3 on EIS](https://www.elastic.co/search-labs/blog/jina-embeddings-v3-elastic-inference-service) · [jina-rerankers on EIS](https://www.elastic.co/search-labs/blog/jina-rerankers-elastic-inference-service) · [EIS docs](https://www.elastic.co/docs/explore-analyze/elastic-inference/eis) · [semantic_text](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/semantic-text) · [Retrievers](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrievers) · [ES|QL hybrid search](https://www.elastic.co/search-labs/blog/hybrid-search-multi-stage-retrieval-esql) · [significant_text](https://www.elastic.co/docs/reference/aggregations/search-aggregations-bucket-significanttext-aggregation) · [Graph](https://www.elastic.co/docs/explore-analyze/visualize/graph) · [start-local](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/local-development-installation-quickstart) · [Cloud trial](https://www.elastic.co/cloud/cloud-trial-overview) · [Python client helpers](https://www.elastic.co/docs/reference/elasticsearch/clients/python/client-helpers)
- [Rox](https://rox.com) · [Sequoia: Every Seller Needs an Agent Swarm](https://sequoiacap.com/article/partnering-with-rox-every-seller-needs-an-agent-swarm) · [Rox goes all in on OpenAI](https://openai.com/index/rox/) · [TechCrunch: Rox $1.2B](https://techcrunch.com/2026/03/12/sales-automation-startup-rox-ai-hits-1-2b-valuation-sources-say/) · [Can Foundation Models Wrangle Your Data? (VLDB)](https://www.vldb.org/pvldb/vol16/p738-narayan.pdf) · [HazyResearch/fm_data_tasks](https://github.com/HazyResearch/fm_data_tasks)