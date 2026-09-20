// Runtime list of every EventType in lib/types.ts. EventSource only delivers named SSE events to
// listeners registered for that exact name, so lib/sse.ts registers one listener per entry.
// The compile-time check below fails the build if types.ts gains a type that is missing here.
import type { EventType, Phase } from "./types";

export const EVENT_TYPES = [
  "run.started", "facets.extracted", "team.formed", "agent.started", "agent.finished", "run.finished", "error",
  "tool.call", "tool.result", "message.sent",
  "source.failed", "evidence.found",
  "entity.merged", "conflict.detected", "site.checked",
  "claim.proposed", "claim.challenged", "claim.resolved", "requery.issued", "jury.vote", "verify.result",
  "voice.result", "prior.sample",
  "score.updated", "graph.patch",
  "mutation.proposed", "mutation.scored", "coach.message", "coach.pitch", "action.proposed", "action.done", "budget.updated",
] as const satisfies readonly EventType[];

type Missing = Exclude<EventType, (typeof EVENT_TYPES)[number]>;
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const _exhaustive: [Missing] extends [never] ? true : never = true;

export const PHASES = ["plan", "scout", "resolve", "debate", "verify", "score", "mutate", "act", "done"] as const satisfies readonly Phase[];

export const PHASE_LABEL: Record<Phase, string> = {
  plan: "Plan",
  scout: "Scout",
  resolve: "Resolve",
  debate: "Debate",
  verify: "Verify",
  score: "Score",
  mutate: "Mutate",
  act: "Act",
  done: "Done",
};
