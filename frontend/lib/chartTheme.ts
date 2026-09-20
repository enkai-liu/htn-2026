// Chart colours and chrome. The chrome follows the CSS theme (light pages, dark classic dashboard): SVG presentation
// attributes accept var(). The categorical hues are the dataviz reference palette's validated steps; they were checked
// with its validator against the dark surface (#0a101c: CVD >= 8.4, contrast >= 3:1) and sit at 3.0-3.9:1 on white,
// which clears the 3:1 bar for graphical marks. Order is part of the safety guarantee: colour follows the series,
// never its rank.
export const CHART = {
  surface: "var(--chart-surface)",
  grid: "var(--color-line)",
  axis: "var(--color-line-strong)",
  text: "var(--color-bone-dim)",
  textMuted: "var(--color-mute)",
  textStrong: "var(--color-bone)",
  series: ["#3987e5", "#d95926", "#199e70", "#c98500"] as const,
} as const;

export const BY_YEAR = {
  other: { label: "Similar projects", color: CHART.series[0] },
  winners: { label: "of which prize winners", color: CHART.series[3] },
} as const;
