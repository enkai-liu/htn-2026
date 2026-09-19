// Chart colours and chrome. The categorical hues are the validated dark steps of the dataviz reference palette,
// checked with its validator against OUR chart surface (#0a101c), adjacent pairs (stacks / neighbouring bars):
//   "#3987e5,#d95926,#199e70,#c98500"  -> lightness band, chroma floor, CVD >= 8.4, normal-vision >= 19.8, contrast >= 3:1: PASS
//   "#3987e5,#c98500"                  -> PASS
// Order is part of the safety guarantee: keep the stack order below, and never recolour by rank.
export const CHART = {
  surface: "#0a101c",
  grid: "rgba(150,176,230,0.12)",
  axis: "rgba(150,176,230,0.28)",
  text: "#b4b09f",
  textMuted: "#7c8498",
  textStrong: "#ece5d3",
  series: ["#3987e5", "#d95926", "#199e70", "#c98500"] as const,
} as const;

/** Slop Index stack, bottom to top. Colour follows the subclass, never its rank. */
export const SUBCLASSES = [
  { key: "pure_ai", label: "Pure AI", color: CHART.series[0] },
  { key: "ai_paraphrased", label: "AI, then paraphrased", color: CHART.series[1] },
  { key: "polished", label: "Human, AI-polished", color: CHART.series[2] },
  { key: "concatenated", label: "Human + AI spliced", color: CHART.series[3] },
] as const;

export type SubclassKey = (typeof SUBCLASSES)[number]["key"];

export const BY_YEAR = {
  other: { label: "Similar projects", color: CHART.series[0] },
  winners: { label: "of which prize winners", color: CHART.series[3] },
} as const;
