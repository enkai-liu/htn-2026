// Mirror of backend/app/schemas/*. Change both together with docs/events.md.

export type Phase = "plan" | "scout" | "resolve" | "debate" | "verify" | "score" | "mutate" | "act" | "done";

export type EventType =
  | "run.started" | "facets.extracted" | "team.formed" | "agent.started" | "agent.finished" | "run.finished" | "error"
  | "tool.call" | "tool.result" | "message.sent"
  | "source.failed" | "evidence.found"
  | "entity.merged" | "conflict.detected"
  | "claim.proposed" | "claim.challenged" | "claim.resolved" | "requery.issued" | "jury.vote" | "verify.result"
  | "voice.result" | "prior.sample"
  | "score.updated" | "graph.patch"
  | "mutation.proposed" | "mutation.scored" | "coach.message" | "coach.pitch" | "action.proposed" | "action.done" | "budget.updated";

export interface AgentEvent<T = Record<string, unknown>> {
  seq: number;
  run_id: string;
  ts: number;
  agent: string;
  to?: string | null;
  phase: Phase;
  type: EventType;
  data: T;
  model?: string | null;
  provider?: "baseten" | "openrouter" | null;
  latency_ms?: number | null;
  tokens?: { in: number; out: number } | null;
  cost_usd?: number | null;
}

export type Source = "devpost" | "yc" | "github" | "hn" | "arxiv" | "web";
export type Provenance = "source" | "normalized" | "imputed";
export type Status = "active" | "dormant" | "dead" | "acquired" | "unknown";

export interface GPTZeroScan {
  predicted_class: "human" | "ai" | "mixed";
  confidence_category: "high" | "medium" | "low";
  subclass?: string | null;
  ai_sentence_share?: number | null;
  result_message?: string | null;
  model_version?: string | null;
}

export interface SourceRecord {
  rid: string;
  source: Source;
  url: string;
  title: string;
  tagline?: string | null;
  description: string;
  pitch: string;
  year?: number | null;
  date?: string | null;
  date_precision?: "day" | "year" | "inferred" | null;
  tags: string[];
  tech: string[];
  status: Status;
  traction: Record<string, unknown>;
  links: string[];
  lang: string;
  quality_flags: string[];
  field_provenance: Record<string, Provenance>;
  retrieval: { query?: string; leg?: string; rank?: number; rerank_score?: number };
  gptzero?: GPTZeroScan | null;
}

export type MergeVerdict = "same" | "different" | "insufficient_evidence";

export interface MergeDecision {
  a: string;
  b: string;
  verdict: MergeVerdict;
  signals: Record<string, unknown>;
  model?: string | null;
  rationale: string;
}

export interface Conflict {
  field: string;
  values: { value: unknown; rid: string; reliability: number }[];
  resolution: unknown;
  rule: string;
}

export interface FusedField {
  value: unknown;
  provenance: string[];
  imputed: boolean;
}

export interface JurorVote { model: string; score: number; why: string }
export interface FacetOverlap { mean: number; std: number; votes: JurorVote[] }

export interface Entity {
  eid: string;
  canonical_name: string;
  summary: string;
  records: string[];
  sources: string[];
  merges: MergeDecision[];
  possible_same_as: string[];
  conflicts: Conflict[];
  fields: Record<string, FusedField>;
  similarity: number;
  facet_overlap: Record<string, FacetOverlap>;
}

export interface Verification {
  local_quote_match?: boolean | null;
  gptzero_status?: "exist" | "exist_with_issues" | "fake" | "unsure" | "unknown" | null;
  stance?: string | null;
  justification?: string | null;
}

export interface Evidence {
  evid: string;
  eid: string;
  rid: string;
  quote: string;
  url: string;
  citation: string;
  verification?: Verification | null;
}

export type ClaimKind = "exists" | "differs" | "trend" | "gap";
export type ClaimStatus = "proposed" | "challenged" | "conceded" | "verified" | "unverified_lead" | "rejected";

export interface ThreadEntry {
  frm: string;
  type: "CHALLENGE" | "REBUTTAL" | "CONCEDE";
  text: string;
  evidence: string[];
}

export interface Claim {
  cid: string;
  kind: ClaimKind;
  text: string;
  by: string;
  evidence: string[];
  status: ClaimStatus;
  thread: ThreadEntry[];
  simulated?: boolean;
}

export interface Facets {
  purpose: string;
  mechanism: string;
  audience: string;
  data: string;
  twist: string;
  domain: string;
  keywords: string[];
}

export interface AxisScore { score: number | null; detail: Record<string, unknown>; note: string }

export interface Scores {
  crowding: AxisScore;
  facet_rarity: AxisScore;
  llm_predictability: AxisScore;
  headline: number | null;
  band: number | null;            // symmetric half-width; kept for callers that want one number
  // Bootstrap interval. Asymmetric on purpose: a weighted geometric mean near the floor is not symmetric,
  // so `headline ± band` overstates the low end and understates the high one.
  low?: number | null;
  high?: number | null;
  // The headline the chip shows: % of reference hackathon projects scoring lower, over `rank_axes`.
  rank?: number | null;
  rank_low?: number | null;
  rank_high?: number | null;
  rank_axes?: string[];
  confidence: number;
  abstain: { active: boolean; reason: string };
}

export interface VoiceSentence { text: string; start: number; end: number; flagged: boolean }

export interface Voice {
  too_short: boolean;
  predicted_class?: "human" | "ai" | "mixed" | null;
  confidence_category?: "high" | "medium" | "low" | null;
  result_message?: string | null;
  ai_sentence_share?: number | null;
  sentences: VoiceSentence[];
  neighbourhood_slop_share?: number | null;
  // Second opinion: Fast-DetectGPT on our own base model. All null when no surprisal deployment.
  // agreement === "disagree" means the panel reports both readings and calls neither.
  curvature?: number | null;
  curvature_percentile?: number | null;
  curvature_class?: "human" | "ai" | null;
  agreement?: "agree" | "disagree" | "unknown";
}

export type NodeKind = "idea" | "facet" | "entity" | "theme" | "prior" | "mutation";
export type LinkKind = "similar" | "has_facet" | "shares_facet" | "same_as" | "possible_same_as" | "mutation_of" | "tagged";

export interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  source?: string | null;
  similarity?: number | null;
  year?: number | null;
  url?: string | null;
  badges: string[];
  val: number;
}

export interface GraphLink { source: string; target: string; kind: LinkKind; weight: number }

export interface GraphPatch {
  add_nodes: GraphNode[];
  add_links: GraphLink[];
  update_nodes: (Partial<GraphNode> & { id: string })[];
  remove_nodes: string[];
}

export interface Mutation {
  mid: string;
  facet: string;
  frm: string;
  to: string;
  rationale: string;
  pitch: string;
  grounded_in: string[];
  delta?: number | null;
  axes?: Record<string, number> | null;
}

/** A project the coach points at: a neighbour already on the map (`eid`) or a fresh corpus hit. */
export interface CoachCite { title: string; url?: string; source?: string; year?: number | null; similarity?: number | null; eid?: string | null }

/** One turn of the coaching conversation. `suggestions` are tap-to-send replies. */
export interface CoachMessage {
  id: string;
  role: "coach" | "user";
  text: string;
  question?: string | null;
  suggestions?: string[];
  cites?: CoachCite[];
  mid?: string | null;
  pitch_version?: number | null;
}

/** A version of the working idea. v0 is the original pitch; `crowding` is null while the corpus check runs. */
export interface CoachPitch {
  version: number;
  text: string;
  note?: string;
  crowding?: number | null;
  delta?: number | null;
  headline?: number | null;
  nearest?: CoachCite[];
  calibrated?: boolean;
}

export interface SourceStatus { source: string; status: "ok" | "failed" | "skipped" | "degraded"; n_records: number; error?: string | null }
export interface TermStat { term: string; score?: number | null; global_count?: number | null; neighbourhood_count?: number | null }
export interface YearCount { year: number; count: number; winners: number }

export interface Report {
  run_id: string;
  idea_text: string;
  facets: Facets;
  scores: Scores;
  voice?: Voice | null;
  entities: Entity[];
  claims: Claim[];
  evidence: Evidence[];
  cliches: TermStat[];
  whitespace: TermStat[];
  by_year: YearCount[];
  mutations: Mutation[];
  sources: SourceStatus[];
  citations: string[];
  summary_md: string;
}
