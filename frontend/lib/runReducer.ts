// Pure reducer: folds AgentEvents (docs/events.md) into the RunState every panel renders from.
//
//   - Idempotent w.r.t. duplicate / replayed events: anything with seq <= lastSeq is ignored, so an SSE
//     reconnect that re-sends the backlog is harmless.
//   - Never throws: a malformed payload becomes a recoverable entry in `errors` and the fold continues.
//   - No React, no DOM: the same code runs in the vitest suite and in `tests/verify-mock.mts`.
import { applyGraphPatch, emptyGraph, type GraphState } from "./graphReducer";
import type {
  ActionDoneData, ActionProposedData, AgentFinishedData, AgentStartedData, BudgetUpdatedData, ClaimChallengedData,
  ClaimProposedData, ClaimResolvedData, ConflictDetectedData, EntityMergedData, ErrorData, EvidenceFoundData,
  CoachMessageData, CoachPitchData, FacetsExtractedData, JuryVoteData, MessageSentData, MutationProposedData, MutationScoredData, PriorSampleData,
  RequeryIssuedData, RunFinishedData, RunStartedData, SiteCheckedData, SourceFailedData, TeamFormedData, ToolCallData, ToolResultData,
  VerifyResultData,
} from "./payloads";
import type {
  AgentEvent, Claim, ClaimStatus, CoachMessage, CoachPitch, Conflict, Entity, EventType, Evidence, Facets, GraphPatch, JurorVote, Mutation, Phase,
  Report, Scores, SiteCheck, SourceRecord, Voice,
} from "./types";

/** A jury whose scores spread at least this much counts as "split" and triggers a re-query. Mirrors SPLIT in backend/app/roles/judge.py. */
export const JURY_SPLIT_STD = 0.25;

export type AgentStatus = "idle" | "active" | "done" | "failed" | "recovered" | "skipped";

export interface AgentInfo {
  agent: string;
  purpose: string;
  status: AgentStatus;
  /** why the conductor left this agent out (status === "skipped") */
  why?: string;
  summary?: string;
  startedT?: number;
  finishedT?: number;
  toolCalls: number;
  events: number;
  /** seq of this agent's latest event: drives the activity ping */
  lastSeq: number;
  /** seq of the latest agent-to-agent message this agent sent or received */
  lastPingSeq: number;
  /** how many times another agent sent this one back out (requery.issued) */
  requeried: number;
  model?: string;
}

export type RowTone = "default" | "muted" | "accent" | "good" | "warn" | "danger" | "teal";
export type RowEmphasis = "message" | "replan" | "requery" | "jury-split" | "failure";

export interface TimelineRow {
  seq: number;
  /** seconds since the first event of the run */
  t: number;
  phase: Phase;
  agent: string;
  to?: string | null;
  type: EventType;
  tag?: string;
  title: string;
  detail?: string;
  tone: RowTone;
  /** indented under the agent's previous row (tool calls and results) */
  sub: boolean;
  emphasis?: RowEmphasis;
  simulated?: boolean;
  count?: number;
  model?: string | null;
  latency_ms?: number | null;
}

export interface AgentMessage {
  seq: number;
  t: number;
  from: string;
  to: string;
  msg_type: string;
  summary: string;
  mid?: string;
}

export interface Requery extends RequeryIssuedData {
  seq: number;
  t: number;
  from: string;
  /** true when the reason names a jury split: the collaboration beat we most want visible */
  fromJurySplit: boolean;
}

export interface JuryVote {
  seq: number;
  t: number;
  subject: string;
  /** which entity and facet the jury rated, when the judge said so (see `juryTarget` in lib/debate.ts for the fallback) */
  eid?: string;
  facet?: string;
  votes: JurorVote[];
  mean: number;
  std: number;
  split: boolean;
  revote: boolean;
}

export interface VerifyBadge {
  layer: "quote" | "gptzero";
  status: string;
  detail: string;
  seq: number;
  /** true = passed, false = failed, null = inconclusive */
  ok: boolean | null;
  simulated: boolean;
}

export interface ClaimState extends Claim {
  simulated: boolean;
  reason?: string;
  verification: { quote?: VerifyBadge; gptzero?: VerifyBadge };
  proposedSeq: number;
  updatedSeq: number;
  history: { seq: number; status: ClaimStatus; reason?: string }[];
}

export type DebateItem = { kind: "claim"; cid: string } | { kind: "jury"; index: number } | { kind: "requery"; index: number };

export interface FailedSource {
  source: string;
  error: string;
  reassigned_to?: string | null;
  seq: number;
  t: number;
  /** evidence (or a successful tool result) arrived from this source after the failure */
  recovered: boolean;
}

export interface ConflictRow { eid: string; conflict: Conflict; seq: number }

export interface MutationState extends Mutation {
  proposedSeq: number;
  scoredSeq?: number;
}

export interface ActionState {
  action: string;
  label: string;
  requires_click: boolean;
  status: "proposed" | "done" | "failed";
  detail?: string;
  proposedSeq: number;
  doneSeq?: number;
}

export interface PriorSample extends PriorSampleData { seq: number }

export interface ModelUsage {
  model: string;
  provider?: string | null;
  events: number;
  usd: number;
  tokensIn: number;
  tokensOut: number;
  latencyMs: number;
  latencyN: number;
  roles: string[];
}

export interface CostState {
  usd: number;
  tokensIn: number;
  tokensOut: number;
  llmEvents: number;
  byModel: Record<string, ModelUsage>;
}

export interface RunError { seq: number; t: number; message: string; recoverable: boolean }

export interface RunState {
  lastSeq: number;
  eventCount: number;
  runId: string | null;
  startedTs: number | null;
  lastTs: number | null;
  phase: Phase | null;
  ideaText: string;
  /** the author's own link, if they gave one: read for context and excluded from the prior art */
  ideaUrl: string | null;
  orchestrator: string | null;
  /** run.started.data.replay: the backend itself is replaying a recording */
  recorded: boolean;
  /** run.started.data.mock: fictional fixture data. Only the classic dashboard still banners it */
  mock: boolean;
  facets: Facets | null;
  roster: { order: string[]; agents: Record<string, AgentInfo> };
  timeline: TimelineRow[];
  messages: AgentMessage[];
  requeries: Requery[];
  records: Record<string, SourceRecord>;
  recordOrder: string[];
  entities: Record<string, Entity>;
  entityOrder: string[];
  /** rid -> eid, filled by entity.merged and by the final report */
  recordEntity: Record<string, string>;
  conflicts: ConflictRow[];
  /** eid -> what the inspector's cloud browser found at the product's own site */
  sites: Record<string, SiteCheck>;
  failedSources: Record<string, FailedSource>;
  claims: Record<string, ClaimState>;
  claimOrder: string[];
  juryVotes: JuryVote[];
  debateFeed: DebateItem[];
  /** evid -> Evidence; only the final report carries quotes */
  evidence: Record<string, Evidence>;
  voice: Voice | null;
  priorSamples: PriorSample[];
  scores: Scores | null;
  scoresSeq: number;
  mutations: Record<string, MutationState>;
  mutationOrder: string[];
  /** the coaching conversation, oldest first */
  coach: (CoachMessage & { seq: number })[];
  /** working-idea versions by version number; [0] is the original pitch */
  pitches: (CoachPitch & { seq: number })[];
  actions: ActionState[];
  lastActionDone: { seq: number; action: string; ok: boolean; detail?: string } | null;
  budget: (BudgetUpdatedData & { seq: number }) | null;
  cost: CostState;
  errors: RunError[];
  report: Report | null;
  finished: boolean;
  graph: GraphState;
}

export const initialRunState: RunState = {
  lastSeq: 0,
  eventCount: 0,
  runId: null,
  startedTs: null,
  lastTs: null,
  phase: null,
  ideaText: "",
  ideaUrl: null,
  orchestrator: null,
  recorded: false,
  mock: false,
  facets: null,
  roster: { order: [], agents: {} },
  timeline: [],
  messages: [],
  requeries: [],
  records: {},
  recordOrder: [],
  entities: {},
  entityOrder: [],
  recordEntity: {},
  conflicts: [],
  sites: {},
  failedSources: {},
  claims: {},
  claimOrder: [],
  juryVotes: [],
  debateFeed: [],
  evidence: {},
  voice: null,
  priorSamples: [],
  scores: null,
  scoresSeq: 0,
  mutations: {},
  mutationOrder: [],
  coach: [],
  pitches: [],
  actions: [],
  lastActionDone: null,
  budget: null,
  cost: { usd: 0, tokensIn: 0, tokensOut: 0, llmEvents: 0, byModel: {} },
  errors: [],
  report: null,
  finished: false,
  graph: emptyGraph,
};

// ---------------------------------------------------------------------------------------------------------------------

const blankAgent = (agent: string, purpose = ""): AgentInfo => ({
  agent, purpose, status: "idle", toolCalls: 0, events: 0, lastSeq: 0, lastPingSeq: 0, requeried: 0,
});

function withAgent(state: RunState, agent: string, patch: (a: AgentInfo) => AgentInfo, atFront = false): RunState["roster"] {
  const existing = state.roster.agents[agent];
  const next = patch(existing ?? blankAgent(agent));
  const order = existing ? state.roster.order : atFront ? [agent, ...state.roster.order] : [...state.roster.order, agent];
  return { order, agents: { ...state.roster.agents, [agent]: next } };
}

const sourceOfAgent = (agent: string): string | null => (agent.startsWith("scout.") ? agent.slice("scout.".length) : null);

function verifyOk(layer: string, status: string): boolean | null {
  const s = status.toLowerCase();
  if (layer === "quote") return s === "match" ? true : s === "no_match" ? false : null;
  if (s === "exist" || s === "exist_with_issues") return true;
  if (s === "fake") return false;
  return null;
}

const short = (s: string | null | undefined, n: number) => (!s ? "" : s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);

function trackCost(cost: CostState, ev: AgentEvent): CostState {
  const usd = typeof ev.cost_usd === "number" ? ev.cost_usd : 0;
  const tin = ev.tokens?.in ?? 0;
  const tout = ev.tokens?.out ?? 0;
  if (!ev.model && !usd && !tin && !tout) return cost;
  const model = ev.model ?? "unattributed";
  const prev = cost.byModel[model] ?? { model, provider: ev.provider ?? null, events: 0, usd: 0, tokensIn: 0, tokensOut: 0, latencyMs: 0, latencyN: 0, roles: [] };
  const usage: ModelUsage = {
    ...prev,
    provider: ev.provider ?? prev.provider,
    events: prev.events + 1,
    usd: prev.usd + usd,
    tokensIn: prev.tokensIn + tin,
    tokensOut: prev.tokensOut + tout,
    latencyMs: prev.latencyMs + (typeof ev.latency_ms === "number" ? ev.latency_ms : 0),
    latencyN: prev.latencyN + (typeof ev.latency_ms === "number" ? 1 : 0),
    roles: prev.roles.includes(ev.agent) ? prev.roles : [...prev.roles, ev.agent],
  };
  return {
    usd: cost.usd + usd,
    tokensIn: cost.tokensIn + tin,
    tokensOut: cost.tokensOut + tout,
    llmEvents: cost.llmEvents + 1,
    byModel: { ...cost.byModel, [model]: usage },
  };
}

const longer = <T,>(a: T[] | undefined, b: T[] | undefined): T[] => ((b?.length ?? 0) > (a?.length ?? 0) ? b ?? [] : a ?? []);

/** The report's entity is the final word on fused values, but it drops detail the resolver streamed
 *  (e.g. the "insufficient_evidence" merge decision), so keep whichever side knows more. */
function mergeEntity(live: Entity | undefined, fromReport: Entity): Entity {
  if (!live) return fromReport;
  return {
    ...live,
    ...fromReport,
    summary: fromReport.summary || live.summary,
    records: longer(live.records, fromReport.records),
    sources: longer(live.sources, fromReport.sources),
    merges: longer(live.merges, fromReport.merges),
    conflicts: longer(live.conflicts, fromReport.conflicts),
    possible_same_as: longer(live.possible_same_as, fromReport.possible_same_as),
    fields: { ...(live.fields ?? {}), ...(fromReport.fields ?? {}) },
    facet_overlap: Object.keys(fromReport.facet_overlap ?? {}).length ? fromReport.facet_overlap : live.facet_overlap ?? {},
  };
}

function mergeReport(state: RunState, report: Report, seq: number): RunState {
  // Live state is richer than the report for anything that streamed (threads, verification badges, the
  // simulated fire-drill claim the synthesizer never sees), so the report only fills gaps and sets final statuses.
  const claims = { ...state.claims };
  const claimOrder = [...state.claimOrder];
  const debateFeed = [...state.debateFeed];
  for (const rc of report.claims ?? []) {
    const live = claims[rc.cid];
    if (live) {
      claims[rc.cid] = {
        ...live,
        status: rc.status ?? live.status,
        thread: (rc.thread?.length ?? 0) > live.thread.length ? rc.thread : live.thread,
        evidence: live.evidence.length ? live.evidence : rc.evidence ?? [],
        updatedSeq: rc.status && rc.status !== live.status ? seq : live.updatedSeq,
        history: rc.status && rc.status !== live.status ? [...live.history, { seq, status: rc.status, reason: "final report" }] : live.history,
      };
    } else {
      claims[rc.cid] = {
        ...rc, thread: rc.thread ?? [], evidence: rc.evidence ?? [], simulated: !!rc.simulated, verification: {},
        proposedSeq: seq, updatedSeq: seq, history: [{ seq, status: rc.status }],
      };
      claimOrder.push(rc.cid);
      debateFeed.push({ kind: "claim", cid: rc.cid });
    }
  }

  const evidence = { ...state.evidence };
  for (const e of report.evidence ?? []) evidence[e.evid] = e;

  const entities = { ...state.entities };
  const entityOrder = [...state.entityOrder];
  const recordEntity = { ...state.recordEntity };
  for (const ent of report.entities ?? []) {
    if (!entities[ent.eid]) entityOrder.push(ent.eid);
    entities[ent.eid] = mergeEntity(entities[ent.eid], ent);
    for (const rid of ent.records ?? []) recordEntity[rid] = ent.eid;
  }

  const sites = { ...state.sites };
  for (const s of report.sites ?? []) sites[s.eid] ??= s;

  const mutations = { ...state.mutations };
  const mutationOrder = [...state.mutationOrder];
  for (const m of report.mutations ?? []) {
    const live = mutations[m.mid];
    if (!live) { mutations[m.mid] = { ...m, grounded_in: m.grounded_in ?? [], proposedSeq: seq, scoredSeq: m.delta != null ? seq : undefined }; mutationOrder.push(m.mid); }
    else if (live.delta == null && m.delta != null) mutations[m.mid] = { ...live, delta: m.delta, axes: m.axes ?? live.axes, scoredSeq: seq };
  }

  return {
    ...state,
    claims, claimOrder, debateFeed, evidence, entities, entityOrder, recordEntity, sites, mutations, mutationOrder,
    report,
    finished: true,
    ideaText: state.ideaText || report.idea_text || "",
    facets: state.facets ?? report.facets ?? null,
    scores: report.scores ?? state.scores,
    scoresSeq: report.scores ? seq : state.scoresSeq,
    voice: state.voice ?? report.voice ?? null,
  };
}

// ---------------------------------------------------------------------------------------------------------------------

function fold(state: RunState, ev: AgentEvent, t: number): RunState {
  const d = (ev.data ?? {}) as unknown;
  const rows: TimelineRow[] = [];
  const row = (r: Partial<TimelineRow> & { title: string }) =>
    rows.push({ seq: ev.seq, t, phase: ev.phase, agent: ev.agent, to: ev.to ?? null, type: ev.type, tone: "default", sub: false, model: ev.model, latency_ms: ev.latency_ms, ...r });

  let next: RunState = state;
  const set = (patch: Partial<RunState>) => { next = { ...next, ...patch }; };

  // Any event from an agent that had failed means it is working again (the broadened retry in the mock run).
  const touch = (agent: string, extra?: (a: AgentInfo) => AgentInfo) => {
    set({
      roster: withAgent(next, agent, (a) => {
        const base: AgentInfo = { ...a, events: a.events + 1, lastSeq: ev.seq, model: ev.model ?? a.model };
        return extra ? extra(base) : base;
      }, agent === "conductor"),
    });
  };

  switch (ev.type) {
    case "run.started": {
      const data = d as RunStartedData;
      set({ ideaText: data.idea_text ?? next.ideaText, ideaUrl: data.url ?? next.ideaUrl, orchestrator: data.orchestrator ?? null, recorded: !!data.replay, mock: !!data.mock });
      touch(ev.agent);
      row({ title: "Run started", detail: data.orchestrator ? `orchestrator: ${data.orchestrator}` : undefined, tone: "muted" });
      break;
    }
    case "facets.extracted": {
      const data = d as FacetsExtractedData;
      set({ facets: data.facets ?? null });
      touch(ev.agent);
      row({ title: "Facets extracted", detail: data.facets ? ["purpose", "mechanism", "audience", "data", "twist"].join(" · ") : undefined, tone: "accent" });
      break;
    }
    case "team.formed": {
      const data = d as TeamFormedData;
      const agents = { ...next.roster.agents };
      const order: string[] = next.roster.order.filter((a) => a === "conductor");
      for (const m of data.team ?? []) {
        agents[m.agent] = { ...(agents[m.agent] ?? blankAgent(m.agent)), purpose: m.purpose };
        if (!order.includes(m.agent)) order.push(m.agent);
      }
      for (const s of data.skipped ?? []) {
        agents[s.agent] = { ...(agents[s.agent] ?? blankAgent(s.agent)), status: "skipped", why: s.why };
        if (!order.includes(s.agent)) order.push(s.agent);
      }
      for (const a of next.roster.order) if (!order.includes(a)) order.push(a);
      set({ roster: { order, agents } });
      touch(ev.agent);
      const skipped = (data.skipped ?? []).map((s) => s.agent).join(", ");
      row({ title: `Team formed: ${(data.team ?? []).length} agents`, detail: skipped ? `skipped ${skipped}` : undefined, tone: "accent" });
      break;
    }
    case "agent.started": {
      const data = d as AgentStartedData;
      touch(ev.agent, (a) => ({ ...a, status: "active", startedT: a.startedT ?? t, purpose: a.purpose || data.purpose || "" }));
      row({ title: "started", detail: data.purpose, tone: "accent" });
      break;
    }
    case "agent.finished": {
      const data = d as AgentFinishedData;
      const ok = data.ok !== false;
      // An agent that failed and then finished cleanly (a retry, a re-query) stays visibly "recovered", not plain "done".
      touch(ev.agent, (a) => ({ ...a, status: !ok ? "failed" : a.status === "recovered" || a.status === "failed" ? "recovered" : "done", finishedT: t, summary: data.summary }));
      row({ title: ok ? "finished" : "failed", detail: data.summary, tone: ok ? "good" : "danger", emphasis: ok ? undefined : "failure" });
      break;
    }
    case "tool.call": {
      const data = d as ToolCallData;
      touch(ev.agent, (a) => ({ ...a, toolCalls: a.toolCalls + 1, status: a.status === "failed" ? "recovered" : a.status }));
      row({ title: data.tool ?? "tool", detail: data.args_summary, sub: true, tone: "muted", tag: "call" });
      break;
    }
    case "tool.result": {
      const data = d as ToolResultData;
      touch(ev.agent, (a) => ({ ...a, status: a.status === "failed" ? "recovered" : a.status }));
      const src = sourceOfAgent(ev.agent);
      if (src && next.failedSources[src] && !next.failedSources[src].recovered && (data.n_hits ?? 0) > 0) {
        set({ failedSources: { ...next.failedSources, [src]: { ...next.failedSources[src], recovered: true } } });
      }
      row({
        title: data.tool ?? "tool", detail: data.summary, sub: true, tag: "result",
        tone: data.n_hits === 0 ? "teal" : "muted", count: typeof data.n_hits === "number" ? data.n_hits : undefined,
      });
      break;
    }
    case "message.sent": {
      const data = d as MessageSentData;
      const to = data.to ?? ev.to ?? "";
      set({ messages: [...next.messages, { seq: ev.seq, t, from: ev.agent, to, msg_type: data.msg_type ?? "MESSAGE", summary: data.summary ?? "", mid: data.mid }] });
      touch(ev.agent, (a) => ({ ...a, lastPingSeq: ev.seq }));
      if (to) set({ roster: withAgent(next, to, (a) => ({ ...a, lastPingSeq: ev.seq })) });
      // A REQUEST_EVIDENCE right after the matching requery.issued is the same beat: fold it into that row.
      const prev = next.timeline[next.timeline.length - 1];
      const duplicateOfRequery = prev && prev.type === "requery.issued" && prev.agent === ev.agent && prev.to === to && data.msg_type === "REQUEST_EVIDENCE";
      if (!duplicateOfRequery) {
        const replan = data.msg_type === "REPLAN";
        row({ title: data.summary ?? "", tag: data.msg_type, to, tone: replan ? "warn" : "accent", emphasis: replan ? "replan" : "message" });
      }
      break;
    }
    case "requery.issued": {
      const data = d as RequeryIssuedData;
      const to = data.to ?? ev.to ?? "";
      const fromJurySplit = /jury\s+split/i.test(data.reason ?? "");
      const requeries = [...next.requeries, { ...data, to, seq: ev.seq, t, from: ev.agent, fromJurySplit }];
      set({ requeries, debateFeed: [...next.debateFeed, { kind: "requery", index: requeries.length - 1 }] });
      touch(ev.agent, (a) => ({ ...a, lastPingSeq: ev.seq }));
      if (to) set({ roster: withAgent(next, to, (a) => ({ ...a, lastPingSeq: ev.seq, requeried: a.requeried + 1 })) });
      row({
        title: data.reason ?? "re-query", detail: data.query ? `${data.facet ? `${data.facet}: ` : ""}“${data.query}”` : undefined, to,
        tag: fromJurySplit ? "JURY SPLIT → RE-QUERY" : "SENT BACK OUT", tone: "warn", emphasis: fromJurySplit ? "jury-split" : "requery",
      });
      break;
    }
    case "source.failed": {
      const data = d as SourceFailedData;
      set({ failedSources: { ...next.failedSources, [data.source]: { source: data.source, error: data.error ?? "failed", reassigned_to: data.reassigned_to ?? null, seq: ev.seq, t, recovered: false } } });
      touch(ev.agent);
      row({ title: `${data.source}: ${data.error ?? "failed"}`, detail: data.reassigned_to ? `reassigned to ${data.reassigned_to}` : "confidence will drop", tag: "SOURCE FAILED", tone: "danger", emphasis: "failure" });
      break;
    }
    case "evidence.found": {
      const data = d as EvidenceFoundData;
      const rec = data.record;
      if (rec?.rid) {
        const isNew = !next.records[rec.rid];
        set({ records: { ...next.records, [rec.rid]: rec }, recordOrder: isNew ? [...next.recordOrder, rec.rid] : next.recordOrder });
        if (data.eid && !next.recordEntity[rec.rid]) set({ recordEntity: { ...next.recordEntity, [rec.rid]: data.eid } });
        const failed = next.failedSources[rec.source];
        if (failed && !failed.recovered) set({ failedSources: { ...next.failedSources, [rec.source]: { ...failed, recovered: true } } });
        row({ title: rec.title, detail: [rec.source, rec.year].filter(Boolean).join(" · "), tag: "evidence", tone: "default" });
      }
      touch(ev.agent, (a) => ({ ...a, status: a.status === "failed" ? "recovered" : a.status }));
      break;
    }
    case "entity.merged": {
      const data = d as EntityMergedData;
      const ent = data.entity;
      if (ent?.eid) {
        const recordEntity = { ...next.recordEntity };
        for (const rid of [...(ent.records ?? []), ...(data.rids ?? [])]) recordEntity[rid] = ent.eid;
        set({
          entities: { ...next.entities, [ent.eid]: ent },
          entityOrder: next.entities[ent.eid] ? next.entityOrder : [...next.entityOrder, ent.eid],
          recordEntity,
        });
        const n = (ent.records ?? []).length;
        const verdict = data.verdict ?? ent.merges?.[0]?.verdict;
        row(verdict === "same"
          ? { title: `${ent.canonical_name}: ${n} listings → 1 entity`, detail: ent.merges?.[0]?.rationale, tag: "merged", tone: "good" }
          : { title: `${ent.canonical_name}: left open`, detail: ent.merges?.[0]?.rationale, tag: verdict === "different" ? "different" : "insufficient evidence", tone: "warn" });
      }
      touch(ev.agent);
      break;
    }
    case "conflict.detected": {
      const data = d as ConflictDetectedData;
      if (data.conflict) {
        set({ conflicts: [...next.conflicts, { eid: data.eid, conflict: data.conflict, seq: ev.seq }] });
        row({ title: `${data.conflict.field}: sources disagree → ${String(data.conflict.resolution)}`, detail: data.conflict.rule, tag: "conflict", tone: "warn" });
      }
      touch(ev.agent);
      break;
    }
    case "site.checked": {
      const data = d as SiteCheckedData;
      if (data.site?.eid) {
        const s = data.site;
        set({ sites: { ...next.sites, [s.eid]: s } });
        const host = s.url.replace(/^https?:\/\/(www\.)?/, "").split("/")[0];
        row({ title: `${host}: ${s.status}`, detail: s.why, tag: "live site", tone: s.status === "alive" ? "good" : "warn" });
      }
      touch(ev.agent);
      break;
    }
    case "claim.proposed": {
      const data = d as ClaimProposedData;
      const c = data.claim;
      if (c?.cid) {
        const simulated = !!(c.simulated || data.simulated);
        const isNew = !next.claims[c.cid];
        const claim: ClaimState = {
          ...c, thread: c.thread ?? [], evidence: c.evidence ?? [], status: c.status ?? "proposed", simulated,
          verification: next.claims[c.cid]?.verification ?? {}, proposedSeq: ev.seq, updatedSeq: ev.seq,
          history: [{ seq: ev.seq, status: c.status ?? "proposed" }],
        };
        set({
          claims: { ...next.claims, [c.cid]: claim },
          claimOrder: isNew ? [...next.claimOrder, c.cid] : next.claimOrder,
          debateFeed: isNew ? [...next.debateFeed, { kind: "claim", cid: c.cid }] : next.debateFeed,
        });
        if (data.evidence?.length) {
          const evidence = { ...next.evidence };
          for (const e of data.evidence) if (e?.evid) evidence[e.evid] = { ...evidence[e.evid], ...e };
          set({ evidence });
        }
        row({ title: short(c.text, 120), tag: `claim ${c.cid} · ${c.kind}`, tone: simulated ? "warn" : "default", simulated });
      }
      touch(ev.agent);
      break;
    }
    case "claim.challenged": {
      const data = d as ClaimChallengedData;
      const cur = next.claims[data.cid];
      if (cur) {
        const inferred: ClaimStatus =
          data.challenge_type === "CONCEDE" ? (cur.status === "proposed" || cur.status === "challenged" ? "conceded" : cur.status)
            : cur.status === "proposed" ? "challenged" : cur.status;
        set({
          claims: {
            ...next.claims,
            [data.cid]: {
              ...cur, status: inferred, updatedSeq: ev.seq,
              thread: [...cur.thread, { frm: data.by ?? ev.agent, type: data.challenge_type, text: data.text ?? "", evidence: data.evidence ?? [] }],
              history: inferred !== cur.status ? [...cur.history, { seq: ev.seq, status: inferred }] : cur.history,
            },
          },
        });
      }
      row({ title: short(data.text, 120), tag: `${(data.challenge_type ?? "CHALLENGE").toLowerCase()} ${data.cid}`, tone: data.challenge_type === "CONCEDE" ? "muted" : "accent", simulated: !!data.simulated });
      touch(ev.agent);
      break;
    }
    case "claim.resolved": {
      const data = d as ClaimResolvedData;
      const cur = next.claims[data.cid];
      if (cur) {
        set({
          claims: {
            ...next.claims,
            [data.cid]: {
              ...cur, status: data.status, reason: data.reason, updatedSeq: ev.seq, simulated: cur.simulated || !!data.simulated,
              history: [...cur.history, { seq: ev.seq, status: data.status, reason: data.reason }],
            },
          },
        });
      }
      const tone: RowTone = data.status === "verified" ? "good" : data.status === "rejected" ? "danger" : "default";
      row({ title: `${data.cid} → ${String(data.status).replace("_", " ")}`, detail: data.reason, tag: "resolved", tone, simulated: !!data.simulated });
      touch(ev.agent);
      break;
    }
    case "jury.vote": {
      const data = d as JuryVoteData;
      const base = (s: string) => s.replace(/\s*\(re-?vote\)\s*/i, "").trim();
      const revote = /re-?vote/i.test(data.subject ?? "") || next.juryVotes.some((v) => base(v.subject) === base(data.subject ?? ""));
      const split = (data.std ?? 0) >= JURY_SPLIT_STD;
      const juryVotes = [...next.juryVotes, { seq: ev.seq, t, subject: data.subject ?? "", eid: data.eid, facet: data.facet, votes: data.votes ?? [], mean: data.mean ?? 0, std: data.std ?? 0, split, revote }];
      set({ juryVotes, debateFeed: [...next.debateFeed, { kind: "jury", index: juryVotes.length - 1 }] });
      row({
        title: data.subject ?? "jury vote", detail: `mean ${(data.mean ?? 0).toFixed(2)} · σ ${(data.std ?? 0).toFixed(2)} · ${(data.votes ?? []).length} jurors`,
        tag: split ? "JURY SPLIT" : revote ? "re-vote" : "jury", tone: split ? "warn" : "default", emphasis: split ? "jury-split" : undefined,
      });
      touch(ev.agent);
      break;
    }
    case "verify.result": {
      const data = d as VerifyResultData;
      const cur = next.claims[data.cid];
      const ok = verifyOk(data.layer, data.status ?? "");
      if (cur) {
        const badge: VerifyBadge = { layer: data.layer, status: data.status, detail: data.detail ?? "", seq: ev.seq, ok, simulated: !!data.simulated };
        set({ claims: { ...next.claims, [data.cid]: { ...cur, updatedSeq: ev.seq, simulated: cur.simulated || !!data.simulated, verification: { ...cur.verification, [data.layer]: badge } } } });
      }
      row({
        title: `${data.cid} · ${data.layer === "gptzero" ? "GPTZero citation check" : "quote check"}: ${data.status}`, detail: data.detail,
        tag: "verify", tone: ok === true ? "good" : ok === false ? "danger" : "muted", simulated: !!data.simulated,
      });
      touch(ev.agent);
      break;
    }
    case "voice.result": {
      const v = d as Voice;
      set({ voice: { ...v, sentences: v.sentences ?? [] } });
      row({ title: v.too_short ? "pitch too short to assess reliably" : v.result_message ?? "voice scanned", tag: "voice", tone: "muted" });
      touch(ev.agent);
      break;
    }
    case "prior.sample": {
      const data = d as PriorSampleData;
      set({ priorSamples: [...next.priorSamples, { ...data, seq: ev.seq }] });
      const prev = next.timeline[next.timeline.length - 1];
      if (prev && prev.type === "prior.sample" && prev.agent === ev.agent) {
        // collapse the burst of samples into one live-updating row
        const n = (prev.count ?? 1) + 1;
        const maxSim = Math.max(...next.priorSamples.map((p) => p.similarity ?? 0));
        // (the row keeps the seq of the first sample so its React key stays stable)
        set({ timeline: [...next.timeline.slice(0, -1), { ...prev, count: n, title: `asked ${n} times: “what would an LLM build here?”`, detail: `closest sample ${maxSim.toFixed(2)} similar` }] });
      } else {
        row({ title: "asked once: “what would an LLM build here?”", detail: `${short(data.text, 80)}`, tag: "LLM prior", tone: "muted", count: 1 });
      }
      touch(ev.agent);
      break;
    }
    case "score.updated": {
      const s = d as Scores;
      set({ scores: s, scoresSeq: ev.seq });
      row(s.abstain?.active
        ? { title: `Abstained: ${s.abstain.reason}`, tag: "score", tone: "warn" }
        : { title: `Headline ${s.headline ?? "–"} ± ${s.band ?? "–"}`, detail: `crowding ${s.crowding?.score ?? "–"} · rarity ${s.facet_rarity?.score ?? "–"} · predictability ${s.llm_predictability?.score ?? "–"} · confidence ${Math.round((s.confidence ?? 0) * 100)}%`, tag: "score", tone: "accent" });
      touch(ev.agent);
      break;
    }
    case "graph.patch": {
      set({ graph: applyGraphPatch(next.graph, d as GraphPatch) });
      touch(ev.agent);
      break;
    }
    case "mutation.proposed": {
      const data = d as MutationProposedData;
      const m = data.mutation;
      if (m?.mid) {
        const isNew = !next.mutations[m.mid];
        set({
          mutations: { ...next.mutations, [m.mid]: { ...m, grounded_in: m.grounded_in ?? [], proposedSeq: ev.seq, scoredSeq: m.delta != null ? ev.seq : undefined } },
          mutationOrder: isNew ? [...next.mutationOrder, m.mid] : next.mutationOrder,
        });
        row({ title: `${m.facet}: ${short(m.frm, 40)} → ${short(m.to, 70)}`, tag: "mutation", tone: "teal" });
      }
      touch(ev.agent);
      break;
    }
    case "mutation.scored": {
      const data = d as MutationScoredData;
      const cur = next.mutations[data.mid];
      if (cur) set({ mutations: { ...next.mutations, [data.mid]: { ...cur, delta: data.delta, axes: data.axes ?? cur.axes, scoredSeq: ev.seq } } });
      const sign = data.delta > 0 ? "+" : "";
      row({ title: `${data.mid} re-scored against the corpus: ${sign}${data.delta}`, detail: data.axes ? Object.entries(data.axes).map(([k, v]) => `${k} → ${v}`).join(" · ") : undefined, tag: "re-scored", tone: data.delta > 0 ? "teal" : "muted" });
      touch(ev.agent);
      break;
    }
    case "coach.message": {
      const m = (d as CoachMessageData).message;
      if (m?.id && m.text && !next.coach.some((x) => x.id === m.id)) {
        set({ coach: [...next.coach, { ...m, seq: ev.seq }] });
        if (m.role === "coach") row({ title: `coach: ${short(m.question || m.text, 90)}`, tag: "coaching", tone: "teal" });
      }
      touch(ev.agent);
      break;
    }
    case "coach.pitch": {
      const p = (d as CoachPitchData).pitch;
      if (p && typeof p.version === "number" && p.text) {
        const i = next.pitches.findIndex((x) => x.version === p.version);
        const pitches = i >= 0 ? next.pitches.map((x, j) => (j === i ? { ...x, ...p, seq: ev.seq } : x)) : [...next.pitches, { ...p, seq: ev.seq }].sort((a, b) => a.version - b.version);
        set({ pitches });
        if (p.version > 0 && p.crowding != null) row({ title: `working idea v${p.version} checked against the corpus${p.delta != null ? `: ${p.delta > 0 ? "+" : ""}${p.delta} crowding` : ""}`, tag: "re-scored", tone: (p.delta ?? 0) > 0 ? "teal" : "muted" });
      }
      touch(ev.agent);
      break;
    }
    case "action.proposed": {
      const data = d as ActionProposedData;
      if (!next.actions.some((a) => a.action === data.action)) {
        set({ actions: [...next.actions, { action: data.action, label: data.label ?? data.action, requires_click: !!data.requires_click, status: "proposed", proposedSeq: ev.seq }] });
      }
      row({ title: data.label ?? data.action, tag: data.requires_click ? "action · needs your click" : "action", tone: "default" });
      touch(ev.agent);
      break;
    }
    case "action.done": {
      const data = d as ActionDoneData;
      const ok = data.ok !== false;
      const exists = next.actions.some((a) => a.action === data.action);
      const actions = exists
        ? next.actions.map((a) => (a.action === data.action ? { ...a, status: ok ? "done" as const : "failed" as const, detail: data.detail, doneSeq: ev.seq } : a))
        : [...next.actions, { action: data.action, label: data.action, requires_click: false, status: ok ? "done" as const : "failed" as const, detail: data.detail, proposedSeq: ev.seq, doneSeq: ev.seq }];
      set({ actions, lastActionDone: { seq: ev.seq, action: data.action, ok, detail: data.detail } });
      row({ title: `${data.action}: ${ok ? "done" : "failed"}`, detail: data.detail, tag: "action", tone: ok ? "good" : "danger" });
      touch(ev.agent);
      break;
    }
    case "budget.updated": {
      const data = d as BudgetUpdatedData;
      set({ budget: { ...data, seq: ev.seq } });
      if (data.degraded) row({ title: "Budget exceeded: running degraded", detail: `${data.calls} calls · ${data.tokens} tokens`, tag: "degraded", tone: "warn", emphasis: "failure" });
      touch(ev.agent);
      break;
    }
    case "run.finished": {
      const data = d as RunFinishedData;
      next = data.report ? mergeReport(next, data.report, ev.seq) : { ...next, finished: true };
      // whoever is still marked active is done now
      const agents = { ...next.roster.agents };
      for (const [k, a] of Object.entries(agents)) if (a.status === "active") agents[k] = { ...a, status: "done", finishedT: a.finishedT ?? t };
      set({ roster: { order: next.roster.order, agents } });
      touch(ev.agent, (a) => ({ ...a, status: "done" }));
      row({ title: "Run finished: report ready", tone: "good" });
      break;
    }
    case "error": {
      const data = d as ErrorData;
      set({ errors: [...next.errors, { seq: ev.seq, t, message: data.message ?? "unknown error", recoverable: data.recoverable !== false }] });
      // Recoverable = a designed degradation (a layer timed out, a juror dropped): the run carries on and confidence
      // accounts for it, so it reads as amber like other degradations. Red is kept for errors that end the run.
      if (data.recoverable === false) row({ title: data.message ?? "error", tag: "error", tone: "danger", emphasis: "failure" });
      else row({ title: data.message ?? "degraded", tag: "degraded", tone: "warn" });
      touch(ev.agent);
      break;
    }
    default: {
      // Unknown type (the contract moved ahead of this build): keep it visible rather than dropping it.
      row({ title: String((ev as AgentEvent).type), tone: "muted" });
    }
  }

  if (rows.length) next = { ...next, timeline: [...next.timeline, ...rows] };
  return next;
}

export function runReducer(state: RunState, ev: AgentEvent): RunState {
  if (!ev || typeof ev !== "object" || typeof ev.type !== "string") return state;
  if (typeof ev.seq !== "number" || !Number.isFinite(ev.seq)) return state;
  if (ev.seq <= state.lastSeq) return state; // duplicate or replayed event

  const ts = typeof ev.ts === "number" ? ev.ts : state.lastTs ?? 0;
  const startedTs = state.startedTs ?? ts;
  const t = Math.max(0, ts - startedTs);
  const base: RunState = {
    ...state,
    lastSeq: ev.seq,
    eventCount: state.eventCount + 1,
    runId: state.runId ?? ev.run_id ?? null,
    startedTs,
    lastTs: ts,
    phase: ev.phase ?? state.phase,
    cost: trackCost(state.cost, ev),
  };
  try {
    return fold(base, ev, t);
  } catch (err) {
    const message = `could not apply event #${ev.seq} (${ev.type}): ${err instanceof Error ? err.message : String(err)}`;
    return { ...base, errors: [...base.errors, { seq: ev.seq, t, message, recoverable: true }] };
  }
}

export function foldEvents(events: readonly AgentEvent[], from: RunState = initialRunState): RunState {
  let s = from;
  for (const ev of events) s = runReducer(s, ev);
  return s;
}
