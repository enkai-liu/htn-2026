// One reading of the headline, shared by the header chip and the report. They used to phrase it separately,
// which is how a chip and a report end up disagreeing about the same run.
import type { Scores } from "./types";

export interface HeadlineParts {
  /** the number to show, or null when the run abstained or has not scored yet */
  value: number | null;
  /** "%" when the number is a percentile rank against real projects, "" when it is the raw composite */
  suffix: string;
  /** what the number means, in words: finishes the sentence the number starts, and never repeats it */
  interval: string;
  /** the uncertainty on that number, kept out of `interval` so two percentages never sit side by side */
  range: string;
  abstain: boolean;
  reason: string;
  /** 0-1, and a word for it */
  confidence: number | null;
  confidenceLabel: "high" | "moderate" | "low" | null;
}

export function headlineParts(scores: Scores | null): HeadlineParts {
  const abstain = !!scores?.abstain?.active;
  // Prefer the percentile rank: "63%" is a statement about a named population (reference hackathon projects),
  // where the raw composite is only meaningful against itself.
  const rank = abstain ? null : scores?.rank ?? null;
  const value = abstain ? null : rank ?? scores?.headline ?? null;
  const confidence = scores?.confidence ?? null;

  // The number and the words are ONE sentence: "63%" + "of hackathon projects score lower". They used to be two
  // claims -- "63%" beside "more original than 55-71% of hackathon projects" -- which reads as "63% more original
  // than..." and leaves the reader comparing two percentages that measure different things.
  const interval =
    abstain || value == null ? ""
    : rank != null ? "of hackathon projects score lower"
    : scores?.low != null && scores?.high != null ? `somewhere between ${Math.round(scores.low)} and ${Math.round(scores.high)}`
    : scores?.band != null ? `give or take ${scores.band}`
    : "";

  // Intervals are asymmetric -- a weighted geometric mean near the floor is -- so show both ends rather than
  // a ± that claims a symmetry the estimator does not have.
  const range =
    abstain || value == null || rank == null || scores?.rank_low == null || scores?.rank_high == null ? ""
    : `${Math.round(scores.rank_low)}–${Math.round(scores.rank_high)}% allowing for uncertainty`;

  return {
    value,
    suffix: rank != null ? "%" : "",
    interval,
    range,
    abstain,
    reason: scores?.abstain?.reason ?? "",
    confidence,
    confidenceLabel: confidence == null ? null : confidence >= 0.7 ? "high" : confidence >= 0.45 ? "moderate" : "low",
  };
}
