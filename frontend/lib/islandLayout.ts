// Pure layout for the islands map. No three.js in here, so it runs under Vitest's node environment.
//
// The law: closer to your idea = more similar. The rings are relative, not absolute: the band of similarities this
// run actually found is stretched over the whole map, so a run where everything scored low still fills the inner
// orbits instead of huddling at the rim. The angle is free (the data has no embedding coordinates), so it is spent
// on grouping: every source owns a fixed wedge of the circle and its projects form an archipelago there.
// The fold is incremental and stable: while the band holds, an island keeps its bearing, a new arrival never makes
// the others jump, and a re-scored mutation slides along its own bearing. When the band itself widens, the map is
// laid out afresh from the same seeds, so the result never depends on the order the patches were folded in.
import type { GraphState } from "./graphReducer";
import { hashString, mulberry32 } from "./seeded";
import type { GraphNode } from "./types";

export const R_MIN = 5.6;
export const R_SPAN = 16;
/** clear water kept between two shores */
export const GAP = 0.45;
/** How far an island's beach can reach from its middle at the waterline, in island sizes: the beach's width there
 *  (between 1.03 and 1.2) at the furthest the coast is roughened out (1.16). Boats keep outside this. */
export const SHORE_REACH = 1.12 * 1.16;
/** how far a moored boat reaches from its middle, in boat sizes: the half length of the hull */
export const BOAT_REACH = 0.85;
const RADIUS_STEP = 1.1;
/** Rings an island may be pushed out inside its own wedge before the wedge starts to give way. */
const SPILL_AFTER = 6;
/** How much wider the wedge gets with every ring after that. A source that outgrows its wedge (live web search
 *  brings 40 islands to a run) takes its neighbours' water rather than drifting rings away from its similarity. */
const SPILL_RATE = 7 * (Math.PI / 180);

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

/** The band of similarities the rings are stretched over: `hi` sits on the innermost ring, `lo` on the rim. */
export interface SimScale { lo: number; hi: number }

export interface LayoutState {
  byId: Record<string, IslandPlacement>;
  order: string[];
  /** the graph revision this layout was folded from */
  graphRev: number;
  /** the band the radii were computed against; null until a project with a similarity has arrived */
  scale: SimScale | null;
}

export const emptyLayout: LayoutState = { byId: {}, order: [], graphRev: -1, scale: null };

export interface LayoutCtx {
  /** mutation id (without the "mut:" prefix) -> the facet it changes */
  mutationFacet: Record<string, string>;
}

const clamp01 = (n: number) => Math.min(1, Math.max(0, n));
const DEG = Math.PI / 180;
const TAU = Math.PI * 2;

export const FACET_KEYS = ["purpose", "mechanism", "audience", "data", "twist", "domain"] as const;

/** A project this close to zero reads as "0.00": it has nothing to do with the idea and is left off the map. */
const ZERO_SIM = 0.005;
/** The band snaps outward to this step, so it only moves (and the map only re-lays) when a new extreme really is one. */
const SCALE_STEP = 0.05;

/** Whether a node gets an island at all. Mutations stay whatever they score: a boat that reached 0 is the best one. */
export function isShown(n: Pick<GraphNode, "kind" | "similarity">): boolean {
  if (!isIsland(n.kind)) return false;
  if (n.kind === "idea" || n.kind === "mutation") return true;
  return !(typeof n.similarity === "number" && n.similarity < ZERO_SIM);
}

/** The band of similarities among the projects on the map. Mutations are measured against it, they do not stretch it. */
export function simScale(graph: GraphState): SimScale | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const id of graph.order) {
    const n = graph.nodes[id];
    if (!n || (n.kind !== "entity" && n.kind !== "prior") || !isShown(n)) continue;
    if (typeof n.similarity !== "number" || !Number.isFinite(n.similarity)) continue;
    const s = clamp01(n.similarity);
    if (s < lo) lo = s;
    if (s > hi) hi = s;
  }
  if (lo > hi) return null;
  return { lo: Math.floor(lo / SCALE_STEP + 1e-9) * SCALE_STEP, hi: Math.ceil(hi / SCALE_STEP - 1e-9) * SCALE_STEP };
}

/** Ring for a similarity, relative to the band: the most similar project hugs the idea, the least similar sits at the rim. */
export function ringRadius(sim: number | null | undefined, scale: SimScale | null = null): number {
  const s = clamp01(typeof sim === "number" && Number.isFinite(sim) ? sim : 0.35);
  const span = scale ? scale.hi - scale.lo : 0;
  const closeness = scale && span > 1e-9 ? clamp01((s - scale.lo) / span) : 0.5;
  return R_MIN + (1 - closeness) * R_SPAN;
}

// Fixed wedges, clockwise from the front of the map. Unequal on purpose, after what real runs bring back: live web
// search finds 35 to 45 projects a run, Devpost up to 30, the others 10 to 17 each.
const SECTORS: { key: string; width: number }[] = [
  { key: "devpost", width: 75 },
  { key: "yc", width: 50 },
  { key: "github", width: 45 },
  { key: "hn", width: 40 },
  { key: "prior", width: 30 },
  { key: "web", width: 105 },
  { key: "arxiv", width: 15 },
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

/** What an island keeps clear around its middle: the shore as it is drawn, which is wider than the turf. */
export const footprint = (p: Pick<IslandPlacement, "kind" | "size">) => p.size * (p.kind === "mutation" ? BOAT_REACH : SHORE_REACH);

function withPosition(p: Omit<IslandPlacement, "x" | "z">): IslandPlacement {
  return { ...p, x: Math.cos(p.angle) * p.radius, z: Math.sin(p.angle) * p.radius };
}

/** Half-width of a wedge for an island pushed `nudge` off its ring: its own until the near rings are full, then wider. */
export const wedgeAt = (half: number, nudge: number) => Math.min(Math.PI, half + Math.max(0, Math.round(nudge / RADIUS_STEP) - SPILL_AFTER) * SPILL_RATE);

function collides(x: number, z: number, reach: number, placed: IslandPlacement[]): boolean {
  for (const o of placed) {
    const min = reach + footprint(o) + GAP;
    const dx = x - o.x;
    const dz = z - o.z;
    if (dx * dx + dz * dz < min * min) return true;
  }
  return false;
}

/** Find a free spot: sweep the wedge at the target ring, then step the ring outward and sweep again. It always finds
 *  one: the wedge widens once the rings near the target are full, and beyond the outermost island all water is clear. */
function place(target: number, reach: number, start: number, centre: number, half: number, placed: IslandPlacement[]): { angle: number; nudge: number } {
  for (let step = 0; ; step++) {
    const r = target + step * RADIUS_STEP;
    const open = wedgeAt(half, r - target);
    const dA = (2 * reach + GAP) / r / 2;
    const max = Math.ceil((2 * open) / dA) + 1;
    for (let k = 0; k <= max; k++) {
      const a = start + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * dA;
      if (Math.abs(a - centre) > open) continue;
      if (!collides(Math.cos(a) * r, Math.sin(a) * r, reach, placed)) return { angle: a, nudge: r - target };
    }
  }
}

export function foldLayout(prev: LayoutState, graph: GraphState, ctx: LayoutCtx): LayoutState {
  if (graph.rev === prev.graphRev) return prev;

  const scale = simScale(graph);
  // The band moved, so every ring did: lay the map out afresh rather than patch it. Bearings start from the same
  // per-island seed, so islands land close to where they were and the scene glides them over.
  if (scale?.lo !== prev.scale?.lo || scale?.hi !== prev.scale?.hi) prev = { ...emptyLayout, scale };

  const byId: Record<string, IslandPlacement> = {};
  const order: string[] = [];
  let changed = false;

  // 1. islands we already know: keep bearing, height and seed; only the ring follows similarity
  const resized: string[] = [];
  for (const id of prev.order) {
    const node = graph.nodes[id];
    if (!node || !isShown(node)) { changed = true; continue; }
    const old = prev.byId[id];
    const size = islandSize(node);
    const radius = node.kind === "idea" ? 0 : ringRadius(node.similarity, scale) + old.nudge;
    if (radius === old.radius && size === old.size) byId[id] = old;
    else { byId[id] = withPosition({ ...old, radius, size }); resized.push(id); changed = true; }
    order.push(id);
  }
  // A re-scored or grown island keeps its bearing, but its new ring may already be taken: a boat must not come to
  // rest inside a rock. It steps outward along its own bearing until it has clear water, like a new arrival would.
  for (const id of resized) {
    const p = byId[id];
    if (p.kind === "idea") continue;
    const others = order.filter((o) => o !== id).map((o) => byId[o]);
    const reach = footprint(p);
    if (!collides(p.x, p.z, reach, others)) continue;
    const target = p.radius - p.nudge;
    for (let step = 0; ; step++) {
      const r = target + step * RADIUS_STEP;
      if (collides(Math.cos(p.angle) * r, Math.sin(p.angle) * r, reach, others)) continue;
      byId[id] = withPosition({ ...p, radius: r, nudge: r - target });
      break;
    }
  }

  // 2. new arrivals, in the order the graph received them
  const placed = order.map((id) => byId[id]);
  for (const id of graph.order) {
    if (byId[id]) continue;
    const node = graph.nodes[id];
    if (!node || !isShown(node) || !isIsland(node.kind)) continue;
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
      const target = ringRadius(node.similarity, scale);
      const berth = place(target, footprint({ kind: "mutation", size }), base + siblings * 0.34, base, MUTATION_HALF, placed);
      p = withPosition({ id, kind: "mutation", angle: berth.angle, radius: target + berth.nudge, nudge: berth.nudge, y: 0, size, seed });
    } else {
      const { centre, half } = sectorFor(node.kind, node.source);
      const start = centre + (rnd() * 2 - 1) * half * 0.8;
      const target = ringRadius(node.similarity, scale);
      const spot = place(target, footprint({ kind: node.kind, size }), start, centre, half, placed);
      p = withPosition({ id, kind: node.kind, angle: spot.angle, radius: target + spot.nudge, nudge: spot.nudge, y: rnd() * 0.05, size, seed });
    }
    byId[id] = p;
    order.push(id);
    placed.push(p);
    changed = true;
  }

  if (!changed) return { ...prev, graphRev: graph.rev };
  return { byId, order, graphRev: graph.rev, scale };
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
