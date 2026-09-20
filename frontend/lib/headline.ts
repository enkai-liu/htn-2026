// One reading of the headline, shared by the header chip and the report. They used to phrase it separately,
// which is how a chip and a report end up disagreeing about the same run.
import type { Scores } from "./types";

export interface HeadlineParts {
  /** the number to show, or null when the run abstained or has not scored yet */
  value: number | null;
  /** "%" when the number is a percentile rank against real projects, "" when it is the raw composite */
  suffix: string;
  /** what the number means, in words */
  interval: string;
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

  // Intervals are asymmetric -- a weighted geometric mean near the floor is -- so show both ends rather than
  // a ± that claims a symmetry the estimator does not have.
  const interval =
    abstain || value == null ? ""
    : rank != null && scores?.rank_low != null && scores?.rank_high != null
      ? `more original than ${Math.round(scores.rank_low)}–${Math.round(scores.rank_high)}% of hackathon projects`
    : rank != null ? "more original than typical"
    : scores?.low != null && scores?.high != null ? `somewhere between ${Math.round(scores.low)} and ${Math.round(scores.high)}`
    : scores?.band != null ? `give or take ${scores.band}`
    : "";

  return {
    value,
    suffix: rank != null ? "%" : "",
    interval,
    abstain,
    reason: scores?.abstain?.reason ?? "",
    confidence,
    confidenceLabel: confidence == null ? null : confidence >= 0.7 ? "high" : confidence >= 0.45 ? "moderate" : "low",
  };
}
