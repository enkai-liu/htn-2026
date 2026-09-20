// Display helpers shared by the panels. No React in here.

export const fmtT = (t: number) => `+${t < 100 ? t.toFixed(1) : Math.round(t)}s`;

export function fmtUsd(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "$0.000";
  return n < 1 ? `$${n.toFixed(3)}` : `$${n.toFixed(2)}`;
}

export function fmtTokens(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return String(Math.round(n));
}

export const fmtInt = (n: number | null | undefined) => (typeof n === "number" ? n.toLocaleString("en-US") : "–");

export const fmtSim = (n: number | null | undefined) => (typeof n === "number" ? n.toFixed(2) : "–");

// A reranker score is not a share of anything: across 300 corpus projects the nearest neighbour sits at 0.16 on
// the median and at 0.37 on the 95th percentile, so a direct competitor at "0.36" reads as a miss when it is about
// as close as things get. The match scale is that score against those two landmarks: 50% is as close as a typical
// project's nearest neighbour, 90% is closer than 95% of them. Monotone, so nothing is reordered; the raw score
// stays in the tooltip. Only for project similarities: an LLM prior's cosine is on another scale and keeps fmtSim.
const MATCH_MID = 0.156;
const MATCH_SCALE = (0.365 - MATCH_MID) / Math.log(9);

export function matchOf(similarity: number | null | undefined): number | null {
  if (typeof similarity !== "number" || !Number.isFinite(similarity)) return null;
  return 1 / (1 + Math.exp(-(similarity - MATCH_MID) / MATCH_SCALE));
}

export const fmtMatch = (similarity: number | null | undefined) => {
  const m = matchOf(similarity);
  return m == null ? "–" : `${Math.round(m * 100)}%`;
};

export const fmtPct = (n: number | null | undefined, digits = 0) => (typeof n === "number" ? `${(n * 100).toFixed(digits)}%` : "–");

export function shortModel(model: string | null | undefined): string {
  if (!model) return "";
  const i = model.lastIndexOf("/");
  return i >= 0 ? model.slice(i + 1) : model;
}

export function modelFamily(model: string | null | undefined): string {
  if (!model) return "";
  const i = model.indexOf("/");
  return i >= 0 ? model.slice(0, i) : model;
}

export function truncate(s: string | null | undefined, n: number): string {
  if (!s) return "";
  return s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s;
}

/**
 * Split an enumerated facet ("a, b (x, y), c") into its items.
 *
 * Only commas at bracket depth 0 separate items, so parenthesised asides stay whole. This is applied
 * per facet key rather than by sniffing the text: `mechanism`/`data`/`domain` are enumerations, while
 * `twist` is prose that often carries a contrastive ", rather than …" clause that must not be cut.
 */
export function splitEnumerated(s: string | null | undefined): string[] {
  if (!s) return [];
  const out: string[] = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (ch === "(" || ch === "[") depth++;
    else if (ch === ")" || ch === "]") depth = Math.max(0, depth - 1);
    else if (ch === "," && depth === 0) {
      out.push(s.slice(start, i));
      start = i + 1;
    }
  }
  out.push(s.slice(start));
  return out.map((p) => p.trim()).filter(Boolean);
}

/** Values in fused fields and conflicts are `unknown`: render them without ever producing "[object Object]". */
export function fmtValue(v: unknown): string {
  if (v == null) return "–";
  if (Array.isArray(v)) return v.map(fmtValue).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Only http(s) links from run data are ever rendered as anchors. */
export function safeHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}

export const SOURCE_LABEL: Record<string, string> = {
  devpost: "Devpost",
  yc: "YC",
  github: "GitHub",
  hn: "Hacker News",
  arxiv: "arXiv",
  web: "Web",
};

/** Hex values for the WebGL islands (light theme). DOM code uses `sourceColor`, which follows the CSS theme. */
export const SOURCE_COLOR: Record<string, string> = {
  devpost: "#2563eb",
  yc: "#ea580c",
  github: "#7c3aed",
  hn: "#be185d",
  arxiv: "#15803d",
  web: "#0e7490",
};

/** Hex values for the 2D canvas chart, which always paints on the dark atlas surface. */
export const SOURCE_COLOR_DARK: Record<string, string> = {
  devpost: "#78b4ff",
  yc: "#ff9466",
  github: "#c4bdf0",
  hn: "#e87fa6",
  arxiv: "#9ad17f",
  web: "#9cc9d9",
};

/** A CSS colour for inline styles: resolves per theme (`.theme-dark` swaps the variables). Not usable on a canvas. */
export const sourceColor = (s: string | null | undefined) => (s && SOURCE_COLOR[s] ? `var(--color-src-${s})` : "var(--color-bone-dim)");
export const sourceHex = (s: string | null | undefined) => (s && SOURCE_COLOR[s]) || "#8d929c";
export const sourceHexDark = (s: string | null | undefined) => (s && SOURCE_COLOR_DARK[s]) || "#b4b09f";
export const sourceLabel = (s: string | null | undefined) => (s && SOURCE_LABEL[s]) || s || "source";
