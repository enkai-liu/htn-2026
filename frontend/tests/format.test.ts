// Enumerated facets are typeset as lists; prose facets must survive intact.
import { describe, expect, it } from "vitest";
import { splitEnumerated } from "../lib/format";

describe("splitEnumerated", () => {
  it("splits a mechanism pipeline into its steps", () => {
    expect(
      splitEnumerated(
        "Extract key figures from paper, generate narration script from abstract and results, synthesize voiceover, assemble animated video with real figures in sequence",
      ),
    ).toEqual([
      "Extract key figures from paper",
      "generate narration script from abstract and results",
      "synthesize voiceover",
      "assemble animated video with real figures in sequence",
    ]);
  });

  it("keeps parenthesised asides whole", () => {
    expect(splitEnumerated("arXiv papers (link input, or upload), paper figures, abstract and results text")).toEqual([
      "arXiv papers (link input, or upload)",
      "paper figures",
      "abstract and results text",
    ]);
  });

  it("leaves a single item alone, so prose renders as one span", () => {
    expect(splitEnumerated("Students deciding whether to read a paper")).toHaveLength(1);
  });

  it("drops empty segments from trailing or doubled commas", () => {
    expect(splitEnumerated("a, b,, c,")).toEqual(["a", "b", "c"]);
  });

  it("handles unbalanced brackets without dropping the tail", () => {
    expect(splitEnumerated("a (b, c")).toEqual(["a (b, c"]);
    expect(splitEnumerated("a), b")).toEqual(["a)", "b"]);
  });

  it("is empty for empty input", () => {
    expect(splitEnumerated("")).toEqual([]);
    expect(splitEnumerated(null)).toEqual([]);
    expect(splitEnumerated(undefined)).toEqual([]);
  });
});
