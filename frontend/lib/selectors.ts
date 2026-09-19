// Derived views over RunState. Pure functions, memoised by the components with useMemo.
import type { RunState } from "./runReducer";
import type { Entity, GraphNode, MergeDecision, SourceRecord } from "./types";

export type EvidenceBadge = "winner" | "merged" | "conflict" | "imputed" | "ai_written" | "source_failed" | "left_open";

export interface EvidenceCardModel {
  key: string;
  eid: string | null;
  /** graph node this card corresponds to, when one exists */
  nodeId: string | null;
  title: string;
  summary: string;
  similarity: number | null;
  year: number | null;
  sources: string[];
  records: SourceRecord[];
  entity: Entity | null;
  badges: EvidenceBadge[];
  /** names of entities the resolver declined to merge with this one */
  possibleSameAs: string[];
}

const isAiWritten = (r: SourceRecord) => !!r.gptzero && r.gptzero.predicted_class === "ai" && r.gptzero.confidence_category === "high";

function nodeForRecord(state: RunState, rec: SourceRecord): GraphNode | null {
  const eid = state.recordEntity[rec.rid];
  const direct = eid ? state.graph.nodes[`ent:${eid}`] : undefined;
  if (direct) return direct;
  for (const id of state.graph.order) {
    const n = state.graph.nodes[id];
    if (n.kind === "entity" && n.url && n.url === rec.url) return n;
  }
  return null;
}

export function entityName(state: RunState, eid: string): string {
  return state.entities[eid]?.canonical_name ?? state.graph.nodes[`ent:${eid}`]?.label ?? eid;
}

export function selectEvidenceCards(state: RunState): EvidenceCardModel[] {
  const cards: EvidenceCardModel[] = [];
  const claimed = new Set<string>();

  for (const eid of state.entityOrder) {
    const ent = state.entities[eid];
    if (!ent) continue;
    const records = (ent.records ?? []).map((rid) => state.records[rid]).filter(Boolean);
    for (const rid of ent.records ?? []) claimed.add(rid);
    const node = state.graph.nodes[`ent:${eid}`] ?? null;
    const badges: EvidenceBadge[] = [];
    if (records.some((r) => r.traction?.is_winner === true) || node?.badges?.includes("winner")) badges.push("winner");
    if ((ent.records ?? []).length > 1) badges.push("merged");
    if ((ent.conflicts ?? []).length > 0 || state.conflicts.some((c) => c.eid === eid)) badges.push("conflict");
    if (Object.values(ent.fields ?? {}).some((f) => f?.imputed) || records.some(hasImputed)) badges.push("imputed");
    if (records.some(isAiWritten) || node?.badges?.includes("ai_written")) badges.push("ai_written");
    if ((ent.possible_same_as ?? []).length > 0) badges.push("left_open");
    if (records.some((r) => state.failedSources[r.source])) badges.push("source_failed");
    cards.push({
      key: `e:${eid}`,
      eid,
      nodeId: node ? node.id : null,
      title: ent.canonical_name,
      summary: ent.summary || records[0]?.tagline || records[0]?.description || "",
      similarity: typeof ent.similarity === "number" ? ent.similarity : node?.similarity ?? null,
      year: node?.year ?? records[0]?.year ?? null,
      sources: ent.sources?.length ? ent.sources : [...new Set(records.map((r) => r.source))],
      records,
      entity: ent,
      badges,
      possibleSameAs: (ent.possible_same_as ?? []).map((other) => entityName(state, other)),
    });
  }

  for (const rid of state.recordOrder) {
    if (claimed.has(rid)) continue;
    const rec = state.records[rid];
    const node = nodeForRecord(state, rec);
    const badges: EvidenceBadge[] = [];
    if (rec.traction?.is_winner === true || node?.badges?.includes("winner")) badges.push("winner");
    if (hasImputed(rec)) badges.push("imputed");
    if (isAiWritten(rec) || node?.badges?.includes("ai_written")) badges.push("ai_written");
    if (state.failedSources[rec.source]) badges.push("source_failed");
    cards.push({
      key: `r:${rid}`,
      eid: node ? node.id.replace(/^ent:/, "") : null,
      nodeId: node?.id ?? null,
      title: rec.title,
      summary: rec.tagline || rec.description || "",
      similarity: node?.similarity ?? rec.retrieval?.rerank_score ?? null,
      year: rec.year ?? null,
      sources: [rec.source],
      records: [rec],
      entity: null,
      badges,
      possibleSameAs: [],
    });
  }

  return cards.sort((a, b) => (b.similarity ?? -1) - (a.similarity ?? -1));
}

function hasImputed(r: SourceRecord): boolean {
  return Object.values(r.field_provenance ?? {}).some((p) => p === "imputed") || r.date_precision === "inferred";
}

// ---------------------------------------------------------------------------------------------------------------------

export type LedgerRow =
  | { kind: "merge"; key: string; eid: string; entity: string; decision: MergeDecision; aTitle: string; bTitle: string }
  | { kind: "conflict"; key: string; eid: string; entity: string; field: string; values: { value: unknown; rid: string; reliability: number; source: string }[]; resolution: unknown; rule: string }
  | { kind: "imputed"; key: string; eid: string | null; entity: string; field: string; value: unknown; provenance: string[] }
  | { kind: "source_failed"; key: string; source: string; error: string; reassigned_to?: string | null; recovered: boolean };

const sourceOfRid = (state: RunState, rid: string) => state.records[rid]?.source ?? rid.split(":")[0] ?? "?";
const titleOfRid = (state: RunState, rid: string) => state.records[rid]?.title ?? rid;

export function selectLedger(state: RunState): LedgerRow[] {
  const rows: LedgerRow[] = [];
  const seenConflicts = new Set<string>();

  for (const eid of state.entityOrder) {
    const ent = state.entities[eid];
    if (!ent) continue;
    for (const [i, m] of (ent.merges ?? []).entries()) {
      rows.push({ kind: "merge", key: `m:${eid}:${i}`, eid, entity: ent.canonical_name, decision: m, aTitle: titleOfRid(state, m.a), bTitle: titleOfRid(state, m.b) });
    }
    for (const c of ent.conflicts ?? []) {
      const key = `c:${eid}:${c.field}`;
      if (seenConflicts.has(key)) continue;
      seenConflicts.add(key);
      rows.push({ kind: "conflict", key, eid, entity: ent.canonical_name, field: c.field, values: (c.values ?? []).map((v) => ({ ...v, source: sourceOfRid(state, v.rid) })), resolution: c.resolution, rule: c.rule });
    }
    for (const [field, f] of Object.entries(ent.fields ?? {})) {
      if (f?.imputed) rows.push({ kind: "imputed", key: `i:${eid}:${field}`, eid, entity: ent.canonical_name, field, value: f.value, provenance: f.provenance ?? [] });
    }
  }

  for (const c of state.conflicts) {
    const key = `c:${c.eid}:${c.conflict.field}`;
    if (seenConflicts.has(key)) continue;
    seenConflicts.add(key);
    rows.push({ kind: "conflict", key, eid: c.eid, entity: entityName(state, c.eid), field: c.conflict.field, values: (c.conflict.values ?? []).map((v) => ({ ...v, source: sourceOfRid(state, v.rid) })), resolution: c.conflict.resolution, rule: c.conflict.rule });
  }

  for (const rid of state.recordOrder) {
    const rec = state.records[rid];
    for (const [field, prov] of Object.entries(rec.field_provenance ?? {})) {
      if (prov === "imputed") rows.push({ kind: "imputed", key: `i:${rid}:${field}`, eid: state.recordEntity[rid] ?? null, entity: rec.title, field, value: (rec as unknown as Record<string, unknown>)[field], provenance: [rid] });
    }
    if (rec.date_precision === "inferred") rows.push({ kind: "imputed", key: `i:${rid}:date`, eid: state.recordEntity[rid] ?? null, entity: rec.title, field: "date", value: rec.date ?? rec.year, provenance: [rid] });
  }

  for (const f of Object.values(state.failedSources)) {
    rows.push({ kind: "source_failed", key: `f:${f.source}`, source: f.source, error: f.error, reassigned_to: f.reassigned_to, recovered: f.recovered });
  }
  return rows;
}

// ---------------------------------------------------------------------------------------------------------------------

export interface SourceStatusRow { source: string; status: "ok" | "failed" | "degraded" | "skipped" | "searching"; n_records: number; error?: string | null }

export function selectSourceStatus(state: RunState): SourceStatusRow[] {
  if (state.report?.sources?.length) return state.report.sources.map((s) => ({ ...s }));
  const rows: SourceStatusRow[] = [];
  for (const agent of state.roster.order) {
    if (!agent.startsWith("scout.")) continue;
    const source = agent.slice("scout.".length);
    const info = state.roster.agents[agent];
    const n = state.recordOrder.filter((rid) => state.records[rid].source === source).length;
    const failed = state.failedSources[source];
    const status: SourceStatusRow["status"] =
      info.status === "skipped" ? "skipped" : failed ? (failed.recovered ? "degraded" : "failed") : info.status === "done" ? "ok" : "searching";
    rows.push({ source, status, n_records: n, error: failed?.error ?? (info.status === "skipped" ? info.why : null) });
  }
  return rows;
}

/** Best available spend figure: the conductor's budget snapshot lags the per-event costs, so take the larger. */
export function selectSpend(state: RunState): { usd: number; calls: number; tokens: number; elapsed: number; degraded: boolean } {
  const b = state.budget;
  return {
    usd: Math.max(b?.cost_usd ?? 0, state.cost.usd),
    calls: Math.max(b?.calls ?? 0, state.cost.llmEvents),
    tokens: Math.max(b?.tokens ?? 0, state.cost.tokensIn + state.cost.tokensOut),
    elapsed: state.startedTs != null && state.lastTs != null ? state.lastTs - state.startedTs : b?.elapsed_s ?? 0,
    degraded: !!b?.degraded,
  };
}
