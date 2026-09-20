// Pure layout for the islands map. No three.js in here, so it runs under Vitest's node environment.
//
// The law is the same as the 2D chart: distance from your idea = 1 - similarity. The angle is free (the data has
// no embedding coordinates), so it is spent on grouping: every source owns a fixed wedge of the circle and its
// projects form an archipelago there. The fold is incremental and stable: once an island has a bearing it keeps
// it, so a new arrival never makes the others jump, and a re-scored mutation slides along its own bearing.
import type { GraphState } from "./graphReducer";
import { hashString, mulberry32 } from "./seeded";
import type { GraphNode } from "./types";

export const R_MIN = 5.6;
export const R_SPAN = 16;
/** clear water kept between two islands */
export const GAP = 0.62;
const RADIUS_STEP = 1.1;
// The wider rings and clearance above need more room to resolve a crowded neighbourhood: at 14 steps the
// packer ran out of outward nudge and left islands overlapping (caught by the no-overlap test).
const MAX_RADIUS_STEPS = 26;

export type IslandKind = "idea" | "entity" | "prior" | "mutation";

export interface IslandPlacement {
  id: string;
  kind: IslandKind;
  /** bearing in the ground plane, radians */
  angle: number;
  /** distance from the idea: ringRadius(similarity) + nudge */
  radius: number;
  /** how far collision-avoidance pushed it off its ring */
  nudge: number;
  x: number;
  z: number;
  /** how far the turf stands out of the sea: everything sits in the water, so this is a little freeboard, not an altitude */
  y: number;
  /** footprint radius */
  size: number;
  seed: number;
}

export interface LayoutState {
  byId: Record<string, IslandPlacement>;
  order: string[];
  /** the graph revision this layout was folded from */
  graphRev: number;
}

export const emptyLayout: LayoutState = { byId: {}, order: [], graphRev: -1 };

export interface LayoutCtx {
  /** mutation id (without the "mut:" prefix) -> the facet it changes */
  mutationFacet: Record<string, string>;
}

const clamp01 = (n: number) => Math.min(1, Math.max(0, n));
const DEG = Math.PI / 180;
const TAU = Math.PI * 2;

export const FACET_KEYS = ["purpose", "mechanism", "audience", "data", "twist", "domain"] as const;

export function ringRadius(sim: number | null | undefined): number {
  return R_MIN + (1 - clamp01(typeof sim === "number" && Number.isFinite(sim) ? sim : 0.35)) * R_SPAN;
}

// Fixed wedges, clockwise from the front of the map. Unequal on purpose: Devpost and YC dominate the corpus.
const SECTORS: { key: string; width: number }[] = [
  { key: "devpost", width: 110 },
  { key: "yc", width: 55 },
  { key: "github", width: 55 },
  { key: "hn", width: 45 },
  { key: "prior", width: 35 },
  { key: "web", width: 30 },
  { key: "arxiv", width: 30 },
];
const SECTOR_START = 35 * DEG;
const SECTOR_PAD = 4 * DEG;
/** how far off its facet's bearing a boat may berth to find clear water */
const MUTATION_HALF = 40 * DEG;

const SECTOR_BY_KEY: Record<string, { centre: number; half: number }> = (() => {
  const out: Record<string, { centre: number; half: number }> = {};
  let a = SECTOR_START;
  for (const s of SECTORS) {
    const w = s.width * DEG;
    out[s.key] = { centre: a + w / 2, half: w / 2 - SECTOR_PAD };
    a += w;
  }
  return out;
})();

/** The wedge a node belongs to. Unknown sources share the "web" wedge. */
export function sectorFor(kind: string, source: string | null | undefined): { centre: number; half: number } {
  if (kind === "prior") return SECTOR_BY_KEY.prior;
  return SECTOR_BY_KEY[source ?? ""] ?? SECTOR_BY_KEY.web;
}

export function islandSize(n: Pick<GraphNode, "kind" | "val">): number {
  switch (n.kind) {
    case "idea": return 2.2;
    case "prior": return 0.56;
    case "mutation": return 0.82;
    default: return 1.02 + Math.min(8, Math.max(0, n.val)) * 0.07;
  }
}

/** Middle of the widest empty arc among the given bearings (ported from the 2D chart). */
export function widestGap(angles: number[]): number {
  if (!angles.length) return -Math.PI / 5;
  const sorted = [...angles].sort((a, b) => a - b);
  let best = 0;
  let mid = sorted[0] + Math.PI;
  for (let i = 0; i < sorted.length; i++) {
    const a = sorted[i];
    const b = i + 1 < sorted.length ? sorted[i + 1] : sorted[0] + TAU;
    if (b - a > best) { best = b - a; mid = a + (b - a) / 2; }
  }
  return mid;
}

const isIsland = (k: string): k is IslandKind => k === "idea" || k === "entity" || k === "prior" || k === "mutation";

function withPosition(p: Omit<IslandPlacement, "x" | "z">): IslandPlacement {
  return { ...p, x: Math.cos(p.angle) * p.radius, z: Math.sin(p.angle) * p.radius };
}

function collides(x: number, z: number, size: number, placed: IslandPlacement[]): boolean {
  for (const o of placed) {
    const min = size + o.size + GAP;
    const dx = x - o.x;
    const dz = z - o.z;
    if (dx * dx + dz * dz < min * min) return true;
  }
  return false;
}

/** Find a free spot: sweep the wedge at the target ring, then step the ring outward and sweep again. */
function place(target: number, size: number, start: number, centre: number, half: number, placed: IslandPlacement[]): { angle: number; nudge: number } {
  for (let step = 0; step <= MAX_RADIUS_STEPS; step++) {
    const r = target + step * RADIUS_STEP;
    const dA = (2 * size + GAP) / r / 2;
    const max = Math.ceil((2 * half) / dA) + 1;
    for (let k = 0; k <= max; k++) {
      const a = start + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * dA;
      if (Math.abs(a - centre) > half) continue;
      if (!collides(Math.cos(a) * r, Math.sin(a) * r, size, placed)) return { angle: a, nudge: r - target };
    }
  }
  // the wedge is full at every ring we are willing to try: accept an overlap rather than loop forever
  return { angle: start, nudge: 0 };
}

export function foldLayout(prev: LayoutState, graph: GraphState, ctx: LayoutCtx): LayoutState {
  if (graph.rev === prev.graphRev) return prev;

  const byId: Record<string, IslandPlacement> = {};
  const order: string[] = [];
  let changed = false;

  // 1. islands we already know: keep bearing, height and seed; only the ring follows similarity
  for (const id of prev.order) {
    const node = graph.nodes[id];
    if (!node || !isIsland(node.kind)) { changed = true; continue; }
    const old = prev.byId[id];
    const size = islandSize(node);
    const radius = node.kind === "idea" ? 0 : ringRadius(node.similarity) + old.nudge;
    if (radius === old.radius && size === old.size) byId[id] = old;
    else { byId[id] = withPosition({ ...old, radius, size }); changed = true; }
    order.push(id);
  }

  // 2. new arrivals, in the order the graph received them
  const placed = order.map((id) => byId[id]);
  for (const id of graph.order) {
    if (byId[id]) continue;
    const node = graph.nodes[id];
    if (!node || !isIsland(node.kind)) continue;
    const seed = hashString(id);
    const rnd = mulberry32(seed);
    const size = islandSize(node);
    let p: IslandPlacement;

    if (node.kind === "idea") {
      p = { id, kind: "idea", angle: 0, radius: 0, nudge: 0, x: 0, z: 0, y: 0.06, size, seed };
    } else if (node.kind === "mutation") {
      // a mutation is a boat on the bearing of the facet it changes. It shares the water with the islands now,
      // so it looks for a free berth the same way they do instead of hovering over them.
      const facet = ctx.mutationFacet[id.slice("mut:".length)];
      const fi = FACET_KEYS.indexOf(facet as (typeof FACET_KEYS)[number]);
      const base = fi >= 0 ? -Math.PI / 2 + (fi * TAU) / FACET_KEYS.length : rnd() * TAU;
      const siblings = placed.filter((o) => o.kind === "mutation" && Math.abs(o.angle - base) < 0.5).length;
      const target = ringRadius(node.similarity);
      const berth = place(target, size, base + siblings * 0.34, base, MUTATION_HALF, placed);
      p = withPosition({ id, kind: "mutation", angle: berth.angle, radius: target + berth.nudge, nudge: berth.nudge, y: 0, size, seed });
    } else {
      const { centre, half } = sectorFor(node.kind, node.source);
      const start = centre + (rnd() * 2 - 1) * half * 0.8;
      const target = ringRadius(node.similarity);
      const spot = place(target, size, start, centre, half, placed);
      p = withPosition({ id, kind: node.kind, angle: spot.angle, radius: target + spot.nudge, nudge: spot.nudge, y: rnd() * 0.05, size, seed });
    }
    byId[id] = p;
    order.push(id);
    placed.push(p);
    changed = true;
  }

  if (!changed) return { ...prev, graphRev: graph.rev };
  return { byId, order, graphRev: graph.rev };
}

/** The farthest any island reaches, for camera fitting. */
export function layoutExtent(layout: LayoutState): number {
  let max = R_MIN;
  for (const id of layout.order) {
    const p = layout.byId[id];
    max = Math.max(max, p.radius + p.size);
  }
  return max;
}
