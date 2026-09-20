// The debate, regrouped for the Debate page: one case per prior-art project (critic vs advocate, the jury's bench per
// facet, the verifier's ruling) plus the state of each stage in the hand-off. Pure: no React in here.
import type { AgentStatus, ClaimState, JuryVote, Requery, RunState } from "./runReducer";
import type { Evidence } from "./types";

export type Stance = "open" | "contested" | "conceded";
export type Outcome = "pending" | "verified" | "rejected" | "lead";

/** A split's tie-break: the re-query the conductor issued and what the scout came back with. */
export interface TieBreak extends Requery { result?: string }

export interface FacetBench {
  facet: string;
  /** the first vote, then any re-votes, in order */
  votes: JuryVote[];
  tieBreak?: TieBreak;
}

export interface DebateCase {
  eid: string;
  name: string;
  sources: string[];
  simulated: boolean;
  claims: ClaimState[];
  bench: FacetBench[];
  stance: Stance;
  outcome: Outcome;
  firstSeq: number;
  /** seq of the latest thing that happened to this case: the page marks the freshest one while streaming */
  lastSeq: number;
}

export type StageId = "critic" | "advocate" | "judge" | "verifier" | "synthesizer";

export interface Stage {
  id: StageId;
  label: string;
  status: Extract<AgentStatus, "idle" | "active" | "done" | "failed">;
  model?: string;
  stat: string;
}

export interface BackEdge { count: number; lastSeq: number }

export interface DebateBoard {
  cases: DebateCase[];
  /** what the advocate says is new: `differs` claims, which belong to no single project */
  distinctions: ClaimState[];
  /** claims we could not tie to a project */
  loose: ClaimState[];
  /** scouts sent back out by the critic (a jury split's re-query lives inside its case) */
  backEdges: TieBreak[];
  funnel: { proposed: number; struck: number; leads: number; reachReport: number; pending: number };
  stages: Stage[];
  jurors: string[];
  scouts: { status: "idle" | "active" | "done"; fromCritic: BackEdge; fromJury: BackEdge };
}

const stripRevote = (s: string) => s.replace(/\s*\(re-?vote\)\s*/i, "").trim();

/** Which project and facet a vote is about. The live judge says so; the fixture and old recordings only have `subject`. */
export function juryTarget(vote: Pick<JuryVote, "subject" | "eid" | "facet">, state: Pick<RunState, "entities" | "entityOrder">): { eid: string | null; facet: string } {
  const subject = stripRevote(vote.subject ?? "");
  const cut = subject.lastIndexOf(": ");
  const head = cut >= 0 ? subject.slice(0, cut).trim() : subject;
  const facet = vote.facet ?? (cut >= 0 ? subject.slice(cut + 2).trim() : "overlap");
  if (vote.eid) return { eid: vote.eid, facet };
  const vs = /^(\S+)\s+vs\s+idea$/i.exec(head);
  if (vs) return { eid: vs[1], facet };
  const byName = state.entityOrder.find((eid) => state.entities[eid]?.canonical_name === head);
  return { eid: byName ?? null, facet };
}

function caseEvidence(claim: ClaimState, state: RunState): Evidence | undefined {
  for (const id of claim.evidence) if (state.evidence[id]?.eid) return state.evidence[id];
  return undefined;
}

function stanceOf(claims: ClaimState[]): Stance {
  const last = claims.map((c) => c.thread[c.thread.length - 1]?.type).filter(Boolean);
  if (!last.length) return claims.some((c) => c.status === "challenged") ? "contested" : claims.every((c) => c.status === "conceded") ? "conceded" : "open";
  return last.every((t) => t === "CONCEDE") ? "conceded" : "contested";
}

function outcomeOf(claims: ClaimState[]): Outcome {
  if (claims.some((c) => c.status === "verified")) return "verified";
  if (claims.length && claims.every((c) => c.status === "rejected")) return "rejected";
  if (claims.some((c) => c.status === "unverified_lead")) return "lead";
  return "pending";
}

/** What the scout reported after being sent back out: its next tool result. */
function withResult(rq: Requery, state: RunState): TieBreak {
  const row = state.timeline.find((r) => r.seq > rq.seq && r.agent === rq.to && r.type === "tool.result");
  return { ...rq, result: row?.detail };
}

export function selectDebateBoard(state: RunState): DebateBoard {
  const byEid = new Map<string, DebateCase>();
  const distinctions: ClaimState[] = [];
  const loose: ClaimState[] = [];

  const open = (eid: string, seq: number, fallbackName: string): DebateCase => {
    let c = byEid.get(eid);
    if (!c) {
      const ent = state.entities[eid];
      c = { eid, name: ent?.canonical_name ?? fallbackName, sources: ent?.sources ?? [], simulated: false, claims: [], bench: [], stance: "open", outcome: "pending", firstSeq: seq, lastSeq: seq };
      byEid.set(eid, c);
    }
    c.lastSeq = Math.max(c.lastSeq, seq);
    return c;
  };

  for (const cid of state.claimOrder) {
    const claim = state.claims[cid];
    if (claim.kind === "differs") { distinctions.push(claim); continue; }
    const ev = caseEvidence(claim, state);
    if (!ev) { loose.push(claim); continue; }
    const rec = state.records[ev.rid];
    const c = open(ev.eid, claim.proposedSeq, rec?.title ?? (claim.simulated ? "Simulated source" : ev.eid));
    if (!c.sources.length && rec?.source) c.sources = [rec.source];
    c.claims.push(claim);
    c.simulated = c.simulated || claim.simulated;
    c.lastSeq = Math.max(c.lastSeq, claim.updatedSeq);
  }

  for (const vote of state.juryVotes) {
    const { eid, facet } = juryTarget(vote, state);
    if (!eid) continue;
    const c = open(eid, vote.seq, eid);
    let bench = c.bench.find((b) => b.facet === facet);
    if (!bench) c.bench.push((bench = { facet, votes: [] }));
    bench.votes.push(vote);
  }

  // A jury split's re-query belongs to the split it answers: the latest split vote before it, on the same facet.
  const backEdges: TieBreak[] = [];
  const benches = [...byEid.values()].flatMap((c) => c.bench.map((b) => ({ c, b })));
  for (const rq of state.requeries) {
    if (!rq.fromJurySplit) { backEdges.push(withResult(rq, state)); continue; }
    const hit = benches
      .filter(({ b }) => b.votes.some((v) => v.split && v.seq < rq.seq) && (!rq.facet || b.facet === rq.facet))
      .sort((x, y) => Math.max(...y.b.votes.filter((v) => v.seq < rq.seq).map((v) => v.seq)) - Math.max(...x.b.votes.filter((v) => v.seq < rq.seq).map((v) => v.seq)))[0];
    if (!hit) { backEdges.push(withResult(rq, state)); continue; }
    hit.b.tieBreak = withResult(rq, state);
    hit.c.lastSeq = Math.max(hit.c.lastSeq, rq.seq);
  }

  const cases = [...byEid.values()].sort((a, b) => a.firstSeq - b.firstSeq);
  for (const c of cases) { c.stance = stanceOf(c.claims); c.outcome = outcomeOf(c.claims); }

  const exists = state.claimOrder.map((cid) => state.claims[cid]).filter((c) => c.kind === "exists");
  const funnel = {
    proposed: exists.length,
    struck: exists.filter((c) => c.status === "rejected").length,
    leads: exists.filter((c) => c.status === "unverified_lead").length,
    reachReport: exists.filter((c) => c.status === "verified").length,
    pending: exists.filter((c) => c.status !== "rejected" && c.status !== "verified" && c.status !== "unverified_lead").length,
  };

  // ---- the hand-off: critic -> advocate -> jury -> verifier -> report --------------------------------------------
  const agents = state.roster.agents;
  const plain = (agent: string): Stage["status"] => {
    const s = agents[agent]?.status;
    return s === "active" ? "active" : s === "done" || s === "recovered" ? "done" : s === "failed" ? "failed" : "idle";
  };
  const replies = exists.flatMap((c) => c.thread).filter((t) => t.frm === "advocate");
  const concedes = replies.filter((t) => t.type === "CONCEDE").length;
  const maxStd = state.juryVotes.reduce((m, v) => Math.max(m, v.std), 0);
  // The verifier also scans the pitch's voice during scouting, and the synthesizer scores before it reports: neither
  // counts as this stage until the debate has reached it.
  const checked = exists.some((c) => c.verification.quote || c.verification.gptzero);
  const criticDone = plain("critic") === "done";
  const verifier: Stage["status"] = plain("verifier") === "active" && (checked || criticDone) ? "active" : checked && funnel.pending === 0 ? "done" : plain("verifier") === "failed" ? "failed" : "idle";
  const report: Stage["status"] = state.report || state.finished ? "done" : verifier === "done" && plain("synthesizer") === "active" ? "active" : "idle";

  const stages: Stage[] = [
    { id: "critic", label: "Critic", status: plain("critic"), model: agents.critic?.model, stat: exists.length ? `${exists.filter((c) => c.by === "critic").length} claims` : "" },
    { id: "advocate", label: "Advocate", status: plain("advocate"), model: agents.advocate?.model, stat: !replies.length ? "" : !concedes ? `${replies.length} rebuttals` : concedes === replies.length ? `${concedes} conceded` : `${replies.length - concedes} rebut · ${concedes} concede` },
    { id: "judge", label: "Jury", status: plain("judge"), stat: state.juryVotes.length ? `${state.juryVotes.length} votes · max σ ${maxStd.toFixed(2)}` : "" },
    { id: "verifier", label: "Verifier", status: verifier, stat: checked ? `${funnel.reachReport} pass · ${funnel.struck} struck` : "" },
    { id: "synthesizer", label: "Report", status: report, model: agents.synthesizer?.model, stat: report === "done" ? `${funnel.reachReport} claims in` : "" },
  ];

  // The hand-off is strictly sequential, so a stage still marked active once a later one has begun is done: not every
  // host (or the fixture) sends agent.finished for every role.
  for (let i = stages.length - 2, later = stages[stages.length - 1].status !== "idle"; i >= 0; i--) {
    if (later && stages[i].status === "active") stages[i].status = "done";
    later = later || stages[i].status !== "idle";
  }

  const jurors = [...new Set(state.juryVotes.flatMap((v) => v.votes.map((j) => j.model)))];
  const edge = (rqs: Requery[]): BackEdge => ({ count: rqs.length, lastSeq: rqs.length ? rqs[rqs.length - 1].seq : 0 });
  // out = the latest scout sent back has not reported yet
  const lastRq = state.requeries[state.requeries.length - 1];
  const scoutStatus = !lastRq ? "idle" : state.phase === "debate" && !state.finished && !withResult(lastRq, state).result ? "active" : "done";

  return {
    cases, distinctions, loose, backEdges, funnel, stages, jurors,
    scouts: { status: scoutStatus, fromCritic: edge(state.requeries.filter((r) => !r.fromJurySplit)), fromJury: edge(state.requeries.filter((r) => r.fromJurySplit)) },
  };
}
