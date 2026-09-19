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
