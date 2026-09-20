# Event contract

The one interface every lane builds against. Source of truth: `backend/app/schemas/events.py` (Python) and `frontend/lib/types.ts` (TypeScript). Change both plus this file together; `backend/tests/test_events_contract.py` fails on unknown event types.

## Transport

```
POST /api/runs                 {idea_text, url?}           -> {run_id}   (429 while MAX_LIVE_RUNS are executing)
GET  /api/runs/{run_id}/events  text/event-stream           one AgentEvent per SSE message
GET  /api/runs/{run_id}         final Report JSON (404 until run.finished)
POST /api/runs/{run_id}/mutations/{mid}/rescore             -> emits mutation.scored + graph.patch
POST /api/runs/{run_id}/coach   {text, mid?}                -> one coaching turn; emits coach.message (author, then coach) + coach.pitch when the idea moved
POST /api/runs/{run_id}/actions/{arm_watch|draft_pitch|writeback}   -> emits action.done
GET  /api/replay/{name}/events?speed=1.5                    streams backend/fixtures/golden/{name}.jsonl
GET  /api/health
```

- Each SSE message is `id: <seq>`, `event: <type>`, `data: <AgentEvent JSON>`. `Last-Event-ID` resumes a dropped stream.
- Every run is appended to `backend/runs/{run_id}.jsonl`, one AgentEvent per line. **That file is the replay format**, so any real run can become a golden demo run (`scripts/record_golden.py`).
- A run stays live for `RUN_RETENTION_S` after it ends (re-scores and actions keep streaming to the same client), then the server closes its stream and forgets it. From then on `/api/runs/{id}/events` and `/api/runs/{id}` serve the JSONL as a recording; `rescore`, `coach` and `actions` answer 409. Every coaching turn restarts the retention window, so a conversation is not evicted mid-way. Clients treat end-of-stream after `run.finished` or a non-recoverable `error` as the normal end, not a dropped connection.
- `run_id = "mock"` always works with no API keys: it replays `backend/fixtures/mock_run.jsonl`.
- **Browser trap:** our event type `error` has the same name as `EventSource`'s own error event, so a server message `event: error` also invokes `es.onerror`. A connection failure is a plain `Event`; a server message carries `data`. Tell them apart (`isServerMessage` in `frontend/lib/sse.ts`) or every recoverable degradation is counted as a dropped connection.
- Observed in Chrome and in the Claude desktop Browser pane: a run page loaded while its tab is hidden (`document.visibilityState === "hidden"`, no animation frames) sits on the server-rendered "Connecting" pill and never opens the stream; the moment the tab is shown it hydrates, connects and receives the full backlog. When debugging "stuck on Connecting", check tab visibility before the code.

## Envelope

```ts
type AgentEvent = {
  seq: number; run_id: string; ts: number;         // ts = unix seconds
  agent: string;                                    // "conductor" | "scout.devpost" | "critic" | ...
  to?: string | null;                               // recipient, for agent-to-agent events
  phase: "plan"|"scout"|"resolve"|"debate"|"verify"|"score"|"mutate"|"act"|"done";
  type: EventType; data: object;
  model?: string; provider?: "baseten"|"openrouter"; latency_ms?: number;
  tokens?: {in: number; out: number}; cost_usd?: number;   // present on LLM-backed events -> CostMeter
}
```

## Event types and `data` payloads

| type | data | UI |
|---|---|---|
| `run.started` | `{idea_text, url?: string\|null, orchestrator: "asyncio"\|"jiuwen", replay?: bool, mock?: bool}` | header; `url` = the author's own link (read for context, excluded from prior art); `mock` = fictional fixture data → persistent banner |
| `facets.extracted` | `{facets: Facets}` | facet chips; facet nodes in graph |
| `team.formed` | `{team: [{agent, purpose}], skipped: [{agent, why}]}` | SwarmTimeline roster (skipped shown greyed with reason) |
| `agent.started` | `{purpose?}` | timeline row goes active |
| `agent.finished` | `{ok: bool, summary?}` | timeline row done/failed. Emitted after every handled request (`TASK`, `REPLAN`, `REQUEST_EVIDENCE`), so an agent can finish more than once; failed → ok reads as *recovered* |
| `tool.call` | `{tool, args_summary}` | timeline sub-row |
| `tool.result` | `{tool, summary, n_hits?}` | timeline sub-row |
| `message.sent` | `{mid, msg_type, to, summary}` | arrow between agents (`msg_type` = Message.type) |
| `source.failed` | `{source, error, reassigned_to?}` | red badge; confidence drops |
| `evidence.found` | `{record: SourceRecord, eid}` | EvidenceCard appears. `eid` = the record's graph node `ent:<eid>` before resolution (the resolver may absorb it later) |
| `entity.merged` | `{entity: Entity, rids: string[], verdict}` | cards collapse into one entity |
| `conflict.detected` | `{eid, conflict: Conflict}` | conflict badge + ledger row |
| `site.checked` | `{eid, site: SiteCheck}` | the inspector rendered the entity's own site in a Browserbase cloud browser: `status` alive/dead/parked/blocked (deterministic), `why`, `http_status`, `title`, `excerpt`, `screenshot` (a path under the API, `GET /api/runs/{id}/shots/{eid}.jpg`; never set for `blocked`). Shown as a chip on the evidence card and a "Live site" block in its detail. A render that contradicts a listing's status is followed by `conflict.detected` |
| `claim.proposed` | `{claim: Claim, evidence?: Evidence[], facets?: string[]}` | DebateThread. `evidence` carries the quoted receipts so quotes show while the debate streams |
| `claim.challenged` | `{cid, by, challenge_type: "CHALLENGE"\|"REBUTTAL"\|"CONCEDE", text}` | DebateThread |
| `claim.resolved` | `{cid, status: ClaimStatus, reason}` | claim badge |
| `requery.issued` | `{reason, facet, query, to}` | "scout sent back out" |
| `jury.vote` | `{subject, votes: [{model, score, why}], mean, std}` | jury strip; std feeds confidence |
| `verify.result` | `{cid, layer: "quote"\|"gptzero", status, detail}` | claim badge flips live |
| `voice.result` | `Voice` | PitchHighlighter (separate axis) |
| `prior.sample` | `{model, text, similarity}` | grey "LLM prior" cloud nodes |
| `surprisal.measured` | `{rcs_nats_per_token, n_tokens, cold_surprisal, primed_surprisal, n_neighbours, explained_spans[]}` | pitch highlighting: `explained_spans` are the sentences prior art predicts |
| `score.updated` | `Scores` | AxisGauges |
| `graph.patch` | `GraphPatch` | IdeaGraph via `graphReducer` |
| `mutation.proposed` | `{mutation: Mutation}` | MutationPanel |
| `mutation.scored` | `{mid, delta, axes}` | mutation node moves outward |
| `coach.message` | `{message: CoachMessage}` (`role: "coach"\|"user"`, `text`, `question?`, `suggestions[]`, `cites[]`, `mid?`, `pitch_version?`) | Coach thread. The run itself emits only the coach's opening turn; author turns arrive through `POST /coach` (the mock fixture scripts three so a replay shows the back-and-forth). The author's message is echoed first, so clients can drop their optimistic copy |
| `coach.pitch` | `{pitch: CoachPitch}` (`version`, `text`, `note`, `crowding?`, `delta?`, `headline?`, `nearest[]`, `calibrated`) | Working-idea card. v0 = the original pitch. Each later version is sent twice, like `mutation.proposed`/`scored`: first with `crowding: null` (checking), then measured. Upsert by `version`. `headline` re-measures crowding only; the other axes are held at the run's values |
| `action.proposed` | `{action, label, requires_click: bool}` | ActionBar |
| `action.done` | `{action, ok: bool, detail}` | toast |
| `budget.updated` | `{calls, tokens, cost_usd, elapsed_s, degraded: bool}` | CostMeter |
| `run.finished` | `{report: Report}` | report view |
| `error` | `{message, recoverable: bool}` | banner |

Shapes of `Facets`, `Scores`, `Voice`, `GraphPatch`, `Mutation`, `Report`, `SourceRecord`, `Entity`, `Conflict`, `Claim` are in `backend/app/schemas/` and mirrored in `frontend/lib/types.ts`.

## Graph conventions

- Node ids: `idea`, `facet:<key>`, `ent:<eid>`, `theme:<term>`, `prior:<n>`, `mut:<mid>`.
- Link kinds: `similar` (weight = similarity), `has_facet`, `shares_facet`, `same_as`, `possible_same_as` (dotted), `mutation_of`, `tagged`.
- Distance from the idea node is `1 - similarity`. When a mutation is scored its node moves outward.

## Rules for emitters

1. Every degradation is an event (`source.failed`, `budget.updated{degraded:true}`, `error{recoverable:true}`). Nothing fails silently.
2. Never put raw GPTZero probabilities in events meant for display: send `result_message` + `confidence_category`.
3. Simulated or injected items (the fire drill) carry `data.simulated = true` (on `claim.proposed`, its `evidence[]`, `verify.result`, `claim.resolved`) and are labelled in the UI.
4. The final `Report` is a summary, not a replacement: clients merge it into what already streamed (longer debate threads, simulated claims and merge decisions may exist only in the stream).
