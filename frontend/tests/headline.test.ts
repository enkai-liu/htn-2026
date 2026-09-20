// The header chip and the report read the headline through headlineParts, so what it returns is what a judge reads.
// The rule this file holds: the number and the words beside it are ONE sentence, and only one percentage is on show.
import { describe, expect, it } from "vitest";
import { headlineParts } from "../lib/headline";
import type { Scores } from "../lib/types";

const scores = (over: Partial<Scores>): Scores => ({ headline: 49, band: 6, axes: {}, ...over } as Scores);

describe("headlineParts", () => {
  it("reads as one sentence with the rank, and states the uncertainty apart from it", () => {
    const h = headlineParts(scores({ rank: 63, rank_low: 55, rank_high: 71 }));
    expect(`${h.value}${h.suffix} ${h.interval}`).toBe("63% of hackathon projects score lower");
    expect(h.range).toBe("55–71% allowing for uncertainty");
    // the old phrasing put a second, different percentage beside the number: "63%" + "more original than 55-71%"
    expect(h.interval).not.toMatch(/%/);
    expect(h.interval).not.toMatch(/more original/);
  });

  it("carries no range when the estimator gave no bounds", () => {
    const h = headlineParts(scores({ rank: 63 }));
    expect(h.interval).toBe("of hackathon projects score lower");
    expect(h.range).toBe("");
  });

  it("falls back to the raw composite, which is only meaningful against itself", () => {
    const h = headlineParts(scores({ rank: null, headline: 49, low: 43, high: 55 }));
    expect(h.value).toBe(49);
    expect(h.suffix).toBe("");
    expect(h.interval).toBe("somewhere between 43 and 55");
    expect(h.range).toBe("");
  });

  it("says nothing about a population when the run abstained", () => {
    const h = headlineParts(scores({ rank: 63, rank_low: 55, rank_high: 71, abstain: { active: true, reason: "thin evidence" } }));
    expect(h.value).toBeNull();
    expect(h.interval).toBe("");
    expect(h.range).toBe("");
    expect(h.reason).toBe("thin evidence");
  });
});
