# Event contract

The one interface every lane builds against. Source of truth: `backend/app/schemas/events.py` (Python) and `frontend/lib/types.ts` (TypeScript). Change both plus this file together; `backend/tests/test_events_contract.py` fails on unknown event types.

## Transport

```
POST /api/runs                 {idea_text, url?}           -> {run_id}
GET  /api/runs/{run_id}/events  text/event-stream           one AgentEvent per SSE message
GET  /api/runs/{run_id}         final Report JSON (404 until run.finished)
POST /api/runs/{run_id}/mutations/{mid}/rescore             -> emits mutation.scored + graph.patch
POST /api/runs/{run_id}/actions/{arm_watch|draft_pitch|writeback}   -> emits action.done
GET  /api/replay/{name}/events?speed=1.5                    streams backend/fixtures/golden/{name}.jsonl
GET  /api/health
```

- Each SSE message is `id: <seq>`, `event: <type>`, `data: <AgentEvent JSON>`. `Last-Event-ID` resumes a dropped stream.
- Every run is appended to `backend/runs/{run_id}.jsonl`, one AgentEvent per line. **That file is the replay format**, so any real run can become a golden demo run (`scripts/record_golden.py`).
- `run_id = "mock"` always works with no API keys: it replays `backend/fixtures/mock_run.jsonl`.

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
| `run.started` | `{idea_text, orchestrator: "asyncio"\|"jiuwen", replay?: bool}` | header |
| `facets.extracted` | `{facets: Facets}` | facet chips; facet nodes in graph |
| `team.formed` | `{team: [{agent, purpose}], skipped: [{agent, why}]}` | SwarmTimeline roster (skipped shown greyed with reason) |
| `agent.started` | `{purpose?}` | timeline row goes active |
| `agent.finished` | `{ok: bool, summary?}` | timeline row done/failed |
| `tool.call` | `{tool, args_summary}` | timeline sub-row |
| `tool.result` | `{tool, summary, n_hits?}` | timeline sub-row |
| `message.sent` | `{mid, msg_type, to, summary}` | arrow between agents (`msg_type` = Message.type) |
| `source.failed` | `{source, error, reassigned_to?}` | red badge; confidence drops |
| `evidence.found` | `{record: SourceRecord}` | EvidenceCard appears |
| `entity.merged` | `{entity: Entity, rids: string[], verdict}` | cards collapse into one entity |
| `conflict.detected` | `{eid, conflict: Conflict}` | conflict badge + ledger row |
| `claim.proposed` | `{claim: Claim}` | DebateThread |
| `claim.challenged` | `{cid, by, challenge_type: "CHALLENGE"\|"REBUTTAL"\|"CONCEDE", text}` | DebateThread |
| `claim.resolved` | `{cid, status: ClaimStatus, reason}` | claim badge |
| `requery.issued` | `{reason, facet, query, to}` | "scout sent back out" |
| `jury.vote` | `{subject, votes: [{model, score, why}], mean, std}` | jury strip; std feeds confidence |
| `verify.result` | `{cid, layer: "quote"\|"gptzero", status, detail}` | claim badge flips live |
| `voice.result` | `Voice` | PitchHighlighter (separate axis) |
| `prior.sample` | `{model, text, similarity}` | grey "LLM prior" cloud nodes |
| `score.updated` | `Scores` | AxisGauges |
| `graph.patch` | `GraphPatch` | IdeaGraph via `graphReducer` |
| `mutation.proposed` | `{mutation: Mutation}` | MutationPanel |
| `mutation.scored` | `{mid, delta, axes}` | mutation node moves outward |
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
3. Simulated or injected items (the fire drill) carry `data.simulated = true` and are labelled in the UI.
