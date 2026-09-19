// How agents are named and coloured across the timeline, roster and debate.
import { sourceColor } from "./format";

const ROLE_COLOR: Record<string, string> = {
  conductor: "#f4b942",
  resolver: "#d9c9a3",
  critic: "#ff8a7a",
  advocate: "#4fd6c0",
  judge: "#c4bdf0",
  verifier: "#78b4ff",
  synthesizer: "#ece5d3",
  mutator: "#7fe0d0",
  actuator: "#e0a94a",
  "fire-drill": "#f4b942",
  user: "#ece5d3",
};

export function agentColor(agent: string | null | undefined): string {
  if (!agent) return "#b4b09f";
  if (agent.startsWith("scout.")) return sourceColor(agent.slice(6));
  return ROLE_COLOR[agent] ?? "#b4b09f";
}

export const ROLE_BLURB: Record<string, string> = {
  conductor: "extracts facets, staffs the team, holds the budget, replans on failure",
  resolver: "the only role that writes entities: matches, merges, fuses, flags conflicts",
  critic: "argues the idea exists; may send scouts back out",
  advocate: "must concede, distinguish by facet, or challenge the evidence",
  judge: "runs the cross-family jury; a split triggers a targeted re-query",
  verifier: "quote check + GPTZero citation check; holds a veto",
  synthesizer: "writes the report from verified claims only",
  mutator: "swaps one facet toward whitespace, then re-scores it",
  actuator: "proposes actions; anything outside the app needs your click",
};
