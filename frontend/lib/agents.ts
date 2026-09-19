// How agents are named and coloured across the timeline, roster and debate.
import { sourceColor } from "./format";

// Role colours live in globals.css as --role-* so they follow the theme (light pages vs the dark classic dashboard).
const ROLES = new Set(["conductor", "resolver", "critic", "advocate", "judge", "verifier", "synthesizer", "mutator", "actuator", "fire-drill", "user"]);

export function agentColor(agent: string | null | undefined): string {
  if (!agent) return "var(--role-default)";
  if (agent.startsWith("scout.")) return sourceColor(agent.slice(6));
  return ROLES.has(agent) ? `var(--role-${agent})` : "var(--role-default)";
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
