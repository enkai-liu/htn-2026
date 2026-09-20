// Per-event `data` payloads (docs/events.md table). Frontend-only helper types layered on lib/types.ts.
// Every field a reducer reads is treated as optional at runtime: a malformed event must never crash the UI.
import type {
  Claim, ClaimStatus, CoachMessage, CoachPitch, Conflict, Entity, Facets, GraphPatch, JurorVote, MergeVerdict, Mutation, Report, Scores,
  SourceRecord, Voice, Evidence } from "./types";

export interface RunStartedData { idea_text: string; url?: string | null; orchestrator?: "asyncio" | "jiuwen" | string; replay?: boolean; mock?: boolean }
export interface FacetsExtractedData { facets: Facets }
export interface TeamFormedData { team: { agent: string; purpose: string }[]; skipped: { agent: string; why: string }[] }
export interface AgentStartedData { purpose?: string }
export interface AgentFinishedData { ok: boolean; summary?: string }
export interface ToolCallData { tool: string; args_summary?: string }
export interface ToolResultData { tool: string; summary?: string; n_hits?: number | null }
export interface MessageSentData { mid: string; msg_type: string; to: string; summary: string }
export interface SourceFailedData { source: string; error: string; reassigned_to?: string | null }
/** `eid` = the record's entity node before resolution (graph node `ent:<eid>`); the resolver may later absorb it. */
export interface EvidenceFoundData { record: SourceRecord; eid?: string }
export interface EntityMergedData { entity: Entity; rids: string[]; verdict: MergeVerdict }
export interface ConflictDetectedData { eid: string; conflict: Conflict }
/** `evidence` carries the quoted receipts so the debate can show them while it streams, not only in the final report. */
export interface ClaimProposedData { claim: Claim; evidence?: Evidence[]; facets?: string[]; simulated?: boolean }
export interface ClaimChallengedData { cid: string; by: string; challenge_type: "CHALLENGE" | "REBUTTAL" | "CONCEDE"; text: string; evidence?: string[]; simulated?: boolean }
export interface ClaimResolvedData { cid: string; status: ClaimStatus; reason: string; simulated?: boolean }
export interface RequeryIssuedData { reason: string; facet: string; query: string; to: string }
/** `eid` and `facet` are sent by the live judge; the mock fixture and older recordings only have `subject`. */
export interface JuryVoteData { subject: string; eid?: string; facet?: string; votes: JurorVote[]; mean: number; std: number }
export interface VerifyResultData { cid: string; layer: "quote" | "gptzero"; status: string; detail: string; simulated?: boolean }
export interface PriorSampleData { model: string; text: string; similarity: number }
export interface MutationProposedData { mutation: Mutation }
export interface MutationScoredData { mid: string; delta: number; axes?: Record<string, number> | null }
export interface CoachMessageData { message: CoachMessage }
export interface CoachPitchData { pitch: CoachPitch }
export interface ActionProposedData { action: string; label: string; requires_click: boolean }
export interface ActionDoneData { action: string; ok: boolean; detail?: string }
export interface BudgetUpdatedData { calls: number; tokens: number; cost_usd: number; elapsed_s: number; degraded: boolean }
export interface RunFinishedData { report: Report }
export interface ErrorData { message: string; recoverable: boolean }

export interface PayloadMap {
  "run.started": RunStartedData;
  "facets.extracted": FacetsExtractedData;
  "team.formed": TeamFormedData;
  "agent.started": AgentStartedData;
  "agent.finished": AgentFinishedData;
  "run.finished": RunFinishedData;
  error: ErrorData;
  "tool.call": ToolCallData;
  "tool.result": ToolResultData;
  "message.sent": MessageSentData;
  "source.failed": SourceFailedData;
  "evidence.found": EvidenceFoundData;
  "entity.merged": EntityMergedData;
  "conflict.detected": ConflictDetectedData;
  "claim.proposed": ClaimProposedData;
  "claim.challenged": ClaimChallengedData;
  "claim.resolved": ClaimResolvedData;
  "requery.issued": RequeryIssuedData;
  "jury.vote": JuryVoteData;
  "verify.result": VerifyResultData;
  "voice.result": Voice;
  "prior.sample": PriorSampleData;
  "score.updated": Scores;
  "graph.patch": GraphPatch;
  "mutation.proposed": MutationProposedData;
  "mutation.scored": MutationScoredData;
  "coach.message": CoachMessageData;
  "coach.pitch": CoachPitchData;
  "action.proposed": ActionProposedData;
  "action.done": ActionDoneData;
  "budget.updated": BudgetUpdatedData;
}
