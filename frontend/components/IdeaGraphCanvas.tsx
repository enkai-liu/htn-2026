"use client";
// The star chart. Canvas rendering on top of react-force-graph-2d (loaded client-side only, see IdeaGraph.tsx).
//
// Geometry: the idea is pinned at the pole. Every node with a similarity is pulled to the ring
//     r = R_MIN + (1 - similarity) * R_SPAN
// so distance from the idea really is 1 - similarity, and the dashed range rings are true to scale.
// When mutation.scored lowers a mutation's similarity its ring target moves out, the simulation is reheated,
// and the node drifts outward leaving a trail back to where it started.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods, type LinkObject, type NodeObject } from "react-force-graph-2d";
import { fmtSim, sourceColor, sourceLabel, truncate } from "@/lib/format";
import type { GraphState } from "@/lib/graphReducer";
import type { MutationState, PriorSample } from "@/lib/runReducer";
import type { Facets, GraphNode, LinkKind } from "@/lib/types";

const FACET_R = 30;
const R_MIN = 46;
const R_SPAN = 236;
const RINGS = [0.75, 0.5, 0.25];
const INK = "#04060b";
const BONE = "#ece5d3";
const AMBER = "#f4b942";
const TEAL = "#4fd6c0";
const RED = "#ff5d4d";
const CLOUD = "#8891a5";
const GRID = "150,176,230";

type SimNode = NodeObject<GraphNode> & GraphNode & {
  __born: number;
  __angle?: number;
  /** similarity when the node first appeared: the trail starts on that ring */
  __sim0?: number | null;
  __movedAt?: number;
};
type SimLink = LinkObject<SimNode, { kind: LinkKind; weight: number }> & { kind: LinkKind; weight: number };

interface Ghost { x: number; y: number; to: SimNode | null; at: number; color: string; r: number }

export interface IdeaGraphCanvasProps {
  graph: GraphState;
  facets: Facets | null;
  mutations: Record<string, MutationState>;
  priorSamples: PriorSample[];
  active: boolean;
  selectedId: string | null;
  onSelect: (node: GraphNode | null) => void;
}

const ringRadius = (sim: number) => R_MIN + (1 - Math.max(0, Math.min(1, sim))) * R_SPAN;
const nodeRadius = (n: GraphNode) => (n.kind === "idea" ? 11 : n.kind === "facet" ? 3.2 : n.kind === "prior" ? 5 : n.kind === "mutation" ? 7 : n.kind === "theme" ? 4 : 4 + (n.val ?? 2) * 1.7);
const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());

// Canvas `font` strings cannot contain var(): the real family names from next/font are read once on mount.
const FONT = { serif: "Georgia, serif", mono: "ui-monospace, Menlo, monospace" };
function resolveFonts() {
  if (typeof window === "undefined") return;
  const css = getComputedStyle(document.documentElement);
  const serif = css.getPropertyValue("--font-instrument-serif").trim();
  const mono = css.getPropertyValue("--font-dm-mono").trim();
  if (serif) FONT.serif = `${serif}, Georgia, serif`;
  if (mono) FONT.mono = `${mono}, ui-monospace, monospace`;
  // make sure the faces the canvas needs are actually fetched (the DOM may not have used them yet)
  void document.fonts?.load(`italic 14px ${FONT.serif}`);
  void document.fonts?.load(`12px ${FONT.mono}`);
}

function nodeColor(n: GraphNode): string {
  switch (n.kind) {
    case "idea": return AMBER;
    case "facet": return "#c99a3a";
    case "prior": return CLOUD;
    case "mutation": return TEAL;
    case "theme": return "#9cc9d9";
    default: return sourceColor(n.source);
  }
}

/** Pulls every node that has a similarity onto its ring; nodes with an assigned bearing are pulled to that point. */
function ringForce() {
  let nodes: SimNode[] = [];
  const force = (alpha: number) => {
    for (const n of nodes) {
      if (n.fx != null || typeof n.similarity !== "number") continue;
      const r = ringRadius(n.similarity);
      const x = n.x ?? 0;
      const y = n.y ?? 0;
      if (n.__angle != null) {
        const k = (n.kind === "mutation" ? 0.22 : 0.05) * alpha;
        n.vx = (n.vx ?? 0) + (Math.cos(n.__angle) * r - x) * k;
        n.vy = (n.vy ?? 0) + (Math.sin(n.__angle) * r - y) * k;
      }
      const d = Math.hypot(x, y) || 1e-6;
      const k = ((r - d) / d) * 0.55 * alpha;
      n.vx = (n.vx ?? 0) + x * k;
      n.vy = (n.vy ?? 0) + y * k;
    }
  };
  force.initialize = (ns: SimNode[]) => { nodes = ns; };
  return force;
}

/** Middle of the widest empty arc among the given bearings. */
function widestGap(angles: number[]): number {
  if (!angles.length) return -Math.PI / 5;
  const sorted = [...angles].sort((a, b) => a - b);
  let best = 0;
  let mid = sorted[0] + Math.PI;
  for (let i = 0; i < sorted.length; i++) {
    const a = sorted[i];
    const b = i + 1 < sorted.length ? sorted[i + 1] : sorted[0] + Math.PI * 2;
    if (b - a > best) { best = b - a; mid = a + (b - a) / 2; }
  }
  return mid;
}

function starPath(ctx: CanvasRenderingContext2D, x: number, y: number, r: number) {
  const w = r * 0.13;
  ctx.beginPath();
  ctx.moveTo(x, y - r);
  ctx.quadraticCurveTo(x + w, y - w, x + r, y);
  ctx.quadraticCurveTo(x + w, y + w, x, y + r);
  ctx.quadraticCurveTo(x - w, y + w, x - r, y);
  ctx.quadraticCurveTo(x - w, y - w, x, y - r);
  ctx.closePath();
}

export default function IdeaGraphCanvas({ graph, facets, mutations, priorSamples, active, selectedId, onSelect }: IdeaGraphCanvasProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const fg = useRef<ForceGraphMethods<SimNode, SimLink> | undefined>(undefined);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [data, setData] = useState<{ nodes: SimNode[]; links: SimLink[] }>({ nodes: [], links: [] });
  const [hover, setHover] = useState<{ node: SimNode; x: number; y: number } | null>(null);

  const sim = useRef(new Map<string, SimNode>());
  const ghosts = useRef<Ghost[]>([]);
  const lastTopo = useRef(-1);
  const userMoved = useRef(false);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const fitting = useRef(false);
  const fitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const live = useRef({ selectedId, hoverId: null as string | null, active, mutations });
  useEffect(() => { live.current = { ...live.current, selectedId, active, mutations }; }, [selectedId, active, mutations]);

  // --- container size ---------------------------------------------------------------------------------------------
  useEffect(() => {
    resolveFonts();
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize((s) => (Math.abs(s.w - width) < 1 && Math.abs(s.h - height) < 1 ? s : { w: Math.floor(width), h: Math.floor(height) }));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // --- camera: keep the pole centred and the farthest ring in view, until the user takes over ---------------------
  const fit = useCallback((ms = 700) => {
    const g = fg.current;
    if (!g || !size.w || !size.h) return;
    let far = ringRadius(0.45);
    for (const n of sim.current.values()) if (typeof n.similarity === "number") far = Math.max(far, ringRadius(n.similarity));
    const k = Math.min(size.w, size.h) / (2 * (far + 46));
    fitting.current = true;
    g.centerAt(0, 0, ms);
    g.zoom(Math.max(0.35, Math.min(2.4, k)), ms);
    setTimeout(() => { fitting.current = false; }, ms + 80);
  }, [size.w, size.h]);

  const scheduleFit = useCallback((delay = 250) => {
    if (userMoved.current) return;
    if (fitTimer.current) clearTimeout(fitTimer.current);
    fitTimer.current = setTimeout(() => fit(), delay);
  }, [fit]);

  useEffect(() => { if (size.w && size.h) scheduleFit(60); }, [size.w, size.h, scheduleFit]);
  useEffect(() => () => { if (fitTimer.current) clearTimeout(fitTimer.current); }, []);

  // --- forces -----------------------------------------------------------------------------------------------------
  const applyForces = useCallback(() => {
    const g = fg.current;
    if (!g) return;
    const link = g.d3Force("link") as unknown as { distance: (f: (l: SimLink) => number) => unknown; strength: (f: (l: SimLink) => number) => unknown } | undefined;
    link?.distance((l) => {
      const target = l.target as SimNode;
      if (l.kind === "has_facet") return FACET_R;
      if (l.kind === "similar" || l.kind === "mutation_of") return ringRadius(typeof target?.similarity === "number" ? target.similarity : l.weight);
      if (l.kind === "same_as" || l.kind === "possible_same_as") return 46;
      return 70;
    });
    link?.strength((l) => (l.kind === "similar" || l.kind === "mutation_of" ? 0.12 : l.kind === "shares_facet" || l.kind === "tagged" ? 0.06 : l.kind === "has_facet" ? 0.8 : 0.03));
    const charge = g.d3Force("charge") as unknown as { strength: (n: number | ((n: SimNode) => number)) => unknown; distanceMax: (n: number) => unknown } | undefined;
    charge?.strength((n: SimNode) => (n.kind === "prior" ? -55 : n.kind === "facet" || n.kind === "idea" ? -10 : -190));
    charge?.distanceMax(280);
    g.d3Force("center", null);
    g.d3Force("ring", ringForce() as never);
  }, []);

  // --- fold GraphState into the mutable simulation objects --------------------------------------------------------
  useEffect(() => {
    const map = sim.current;
    const t = now();
    let attrChanged = false;

    // removed nodes leave a ghost that flies into whatever just absorbed them
    const newlyMerged: SimNode[] = [];
    for (const id of graph.order) {
      const cur = map.get(id);
      const next = graph.nodes[id];
      if (cur && next.badges.includes("merged") && !cur.badges.includes("merged")) newlyMerged.push(cur);
    }
    for (const [id, n] of map) {
      if (graph.nodes[id]) continue;
      if (n.x != null && n.y != null) {
        let to: SimNode | null = null;
        let best = Infinity;
        for (const m of newlyMerged) {
          const d = Math.hypot((m.x ?? 0) - n.x, (m.y ?? 0) - n.y);
          if (d < best) { best = d; to = m; }
        }
        ghosts.current.push({ x: n.x, y: n.y, to, at: t, color: nodeColor(n), r: nodeRadius(n) });
      }
      map.delete(id);
    }

    const facetIds = graph.order.filter((id) => graph.nodes[id].kind === "facet");
    const facetAngle = (key: string) => {
      const i = facetIds.indexOf(`facet:${key}`);
      return i < 0 ? null : -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(1, facetIds.length);
    };
    const bearings = () => [...map.values()].filter((n) => (n.kind === "entity" || n.kind === "mutation") && n.x != null).map((n) => Math.atan2(n.y ?? 0, n.x ?? 0));

    let priorBase: number | null = null;
    let priorCount = 0;
    for (const id of graph.order) {
      const src = graph.nodes[id];
      const cur = map.get(id);
      if (cur) {
        if (typeof src.similarity === "number" && src.similarity !== cur.similarity) { cur.__movedAt = t; attrChanged = true; }
        Object.assign(cur, src);
        continue;
      }
      const node = { ...src, __born: t, __sim0: src.similarity } as SimNode;
      if (src.kind === "idea") {
        node.fx = 0; node.fy = 0; node.x = 0; node.y = 0;
      } else if (src.kind === "facet") {
        const a = facetAngle(id.slice("facet:".length)) ?? 0;
        node.fx = Math.cos(a) * FACET_R; node.fy = Math.sin(a) * FACET_R;
        node.x = 0; node.y = 0;
      } else {
        let a: number;
        if (src.kind === "mutation") {
          // a mutation sits on the bearing of the facet it changes
          const m = live.current.mutations[id.slice("mut:".length)];
          const onFacet = m ? facetAngle(m.facet) : null;
          const sameBearing = [...map.values()].filter((n) => n.kind === "mutation" && onFacet != null && n.__angle != null && Math.abs(n.__angle - onFacet) < 0.5).length;
          a = (onFacet ?? widestGap(bearings())) + sameBearing * 0.34;
          node.__angle = a;
        } else if (src.kind === "prior") {
          if (priorBase == null) {
            const existing = [...map.values()].filter((n) => n.kind === "prior" && n.__angle != null);
            priorBase = existing.length ? existing[0].__angle! : widestGap(bearings());
            priorCount = existing.length;
          }
          const k = priorCount++;
          a = priorBase + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 0.2;
          node.__angle = a;
        } else {
          a = widestGap(bearings());
        }
        // born close to the pole, then eased out to its ring by the simulation
        const r0 = typeof src.similarity === "number" ? ringRadius(src.similarity) * 0.55 : 60;
        node.x = Math.cos(a) * r0;
        node.y = Math.sin(a) * r0;
      }
      map.set(id, node);
    }

    if (graph.topoRev !== lastTopo.current) {
      lastTopo.current = graph.topoRev;
      const nodes = graph.order.map((id) => map.get(id)!).filter(Boolean);
      const links = graph.links.filter((l) => map.has(l.source) && map.has(l.target)).map((l) => ({ source: l.source, target: l.target, kind: l.kind, weight: l.weight })) as SimLink[];
      setData({ nodes, links });
      scheduleFit(500);
    } else if (attrChanged) {
      applyForces();
      fg.current?.d3ReheatSimulation();
      scheduleFit(900);
    }
  }, [graph, applyForces, scheduleFit]);

  // The canvas only mounts once the container has a size, which can be AFTER every event has been folded
  // (skip-to-end, ?speed=0), so forces are (re)applied on mount as well as on every data change.
  const mounted = size.w > 0 && size.h > 0;
  useEffect(() => {
    if (!mounted) return;
    applyForces();
    fg.current?.d3ReheatSimulation();
  }, [applyForces, data, mounted]);

  // --- painting ---------------------------------------------------------------------------------------------------
  const paintBackdrop = useCallback((ctx: CanvasRenderingContext2D, scale: number) => {
    const px = 1 / scale;
    ctx.save();
    // bearings
    ctx.lineWidth = px;
    for (let i = 0; i < 12; i++) {
      const a = (i * Math.PI) / 6;
      ctx.strokeStyle = `rgba(${GRID},0.055)`;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * R_MIN * 0.8, Math.sin(a) * R_MIN * 0.8);
      ctx.lineTo(Math.cos(a) * (R_MIN + R_SPAN), Math.sin(a) * (R_MIN + R_SPAN));
      ctx.stroke();
    }
    // range rings, true to scale
    ctx.font = `${9.5 * px}px ${FONT.mono}`;
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";
    for (const s of RINGS) {
      const r = ringRadius(s);
      ctx.strokeStyle = `rgba(${GRID},0.2)`;
      ctx.setLineDash([2 * px, 5 * px]);
      ctx.beginPath();
      ctx.arc(0, 0, r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(124,132,152,0.85)";
      ctx.fillText(`sim ${s.toFixed(2)}`, 4 * px, -r - 3 * px);
    }
    const rim = ringRadius(0);
    ctx.strokeStyle = `rgba(${GRID},0.3)`;
    ctx.beginPath();
    ctx.arc(0, 0, rim, 0, Math.PI * 2);
    ctx.stroke();
    for (let i = 0; i < 72; i++) {
      const a = (i * Math.PI) / 36;
      const long = i % 6 === 0;
      ctx.strokeStyle = `rgba(${GRID},${long ? 0.5 : 0.24})`;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * rim, Math.sin(a) * rim);
      ctx.lineTo(Math.cos(a) * (rim - (long ? 9 : 4)), Math.sin(a) * (rim - (long ? 9 : 4)));
      ctx.stroke();
    }
    // the outer band is the whitespace: nothing out there resembles the idea
    ctx.fillStyle = "rgba(79,214,192,0.6)";
    ctx.font = `italic ${15 * px}px ${FONT.serif}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const label = "w h i t e s p a c e";
    const lr = (ringRadius(0.25) + rim) / 2;
    const step = (8.2 * px) / lr;
    let a = -Math.PI / 9 - (label.length * step) / 2;
    for (const ch of label) {
      ctx.save();
      ctx.translate(Math.cos(a) * lr, Math.sin(a) * lr);
      ctx.rotate(a + Math.PI / 2);
      ctx.fillText(ch, 0, 0);
      ctx.restore();
      a += step;
    }

    // radar sweep while agents are working
    if (live.current.active) {
      const theta = ((now() / 1000) * 0.55) % (Math.PI * 2);
      const conic = (ctx as CanvasRenderingContext2D & { createConicGradient?: (a: number, x: number, y: number) => CanvasGradient }).createConicGradient;
      if (typeof conic === "function") {
        const g = conic.call(ctx, theta - 0.7, 0, 0);
        g.addColorStop(0, "rgba(244,185,66,0)");
        g.addColorStop(0.11, "rgba(244,185,66,0.13)");
        g.addColorStop(0.1101, "rgba(244,185,66,0)");
        g.addColorStop(1, "rgba(244,185,66,0)");
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(0, 0, rim, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.strokeStyle = "rgba(244,185,66,0.4)";
      ctx.lineWidth = px;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(Math.cos(theta) * rim, Math.sin(theta) * rim);
      ctx.stroke();
    }
    ctx.restore();
  }, []);

  const paintNode = useCallback((raw: NodeObject<SimNode>, ctx: CanvasRenderingContext2D, scale: number) => {
    const n = raw as SimNode;
    const x = n.x ?? 0;
    const y = n.y ?? 0;
    const px = 1 / scale;
    const t = now();
    const age = t - n.__born;
    const grow = Math.min(1, age / 500);
    const r = nodeRadius(n) * (0.3 + 0.7 * grow);
    const color = nodeColor(n);
    const { selectedId: sel, hoverId } = live.current;
    const isSel = sel === n.id;
    const isHover = hoverId === n.id;
    ctx.save();

    if (age < 1100 && n.kind !== "prior" && n.kind !== "facet") {
      const p = age / 1100;
      ctx.strokeStyle = color;
      ctx.globalAlpha = (1 - p) * 0.7;
      ctx.lineWidth = 1.2 * px;
      ctx.beginPath();
      ctx.arc(x, y, r + p * 26, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    if (n.kind === "idea") {
      const glow = ctx.createRadialGradient(x, y, 0, x, y, 44);
      glow.addColorStop(0, "rgba(244,185,66,0.5)");
      glow.addColorStop(1, "rgba(244,185,66,0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(x, y, 44, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = AMBER;
      starPath(ctx, x, y, 13 + Math.sin(t / 900) * 0.8);
      ctx.fill();
    } else if (n.kind === "facet") {
      ctx.strokeStyle = color;
      ctx.fillStyle = INK;
      ctx.lineWidth = 1.2 * px;
      ctx.beginPath();
      ctx.moveTo(x, y - r - 1); ctx.lineTo(x + r + 1, y); ctx.lineTo(x, y + r + 1); ctx.lineTo(x - r - 1, y);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      if (scale > 1.25 || isHover) {
        ctx.fillStyle = "rgba(201,154,58,0.95)";
        ctx.font = `${8.5 * px}px ${FONT.mono}`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const a = Math.atan2(y, x);
        ctx.fillText(String(n.id).replace("facet:", "").toUpperCase(), x + Math.cos(a) * 22 * px, y + Math.sin(a) * 13 * px);
      }
    } else if (n.kind === "prior") {
      const R = 15;
      const haze = ctx.createRadialGradient(x, y, 0, x, y, R);
      haze.addColorStop(0, `rgba(136,145,165,${isHover ? 0.75 : 0.42 * grow})`);
      haze.addColorStop(1, "rgba(136,145,165,0)");
      ctx.fillStyle = haze;
      ctx.beginPath();
      ctx.arc(x, y, R, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = `rgba(136,145,165,${isHover ? 1 : 0.75})`;
      ctx.beginPath();
      ctx.arc(x, y, 1.6, 0, Math.PI * 2);
      ctx.fill();
    } else if (n.kind === "mutation") {
      const a = Math.atan2(y, x);
      // trail from the ring it started on
      if (typeof n.__sim0 === "number" && typeof n.similarity === "number" && n.__sim0 !== n.similarity) {
        const r0 = ringRadius(n.__sim0);
        const ox = Math.cos(a) * r0;
        const oy = Math.sin(a) * r0;
        ctx.strokeStyle = "rgba(79,214,192,0.65)";
        ctx.lineWidth = 1.3 * px;
        ctx.setLineDash([3 * px, 4 * px]);
        ctx.lineDashOffset = -(t / 60) * px;
        ctx.beginPath();
        ctx.moveTo(ox, oy);
        ctx.lineTo(x, y);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.arc(ox, oy, 3, 0, Math.PI * 2);
        ctx.stroke();
      }
      if (n.__movedAt && t - n.__movedAt < 1600) {
        const p = (t - n.__movedAt) / 1600;
        ctx.strokeStyle = TEAL;
        ctx.globalAlpha = 1 - p;
        ctx.lineWidth = 1.5 * px;
        ctx.beginPath();
        ctx.arc(x, y, r + p * 34, 0, Math.PI * 2);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      ctx.shadowColor = TEAL;
      ctx.shadowBlur = 12;
      ctx.fillStyle = TEAL;
      ctx.beginPath();
      ctx.moveTo(x + Math.cos(a) * (r + 2), y + Math.sin(a) * (r + 2));
      ctx.lineTo(x + Math.cos(a + 2.45) * r, y + Math.sin(a + 2.45) * r);
      ctx.lineTo(x + Math.cos(a - 2.45) * r, y + Math.sin(a - 2.45) * r);
      ctx.closePath();
      ctx.fill();
      ctx.shadowBlur = 0;
      const m = live.current.mutations[String(n.id).slice(4)];
      ctx.font = `500 ${11 * px}px ${FONT.mono}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = TEAL;
      ctx.fillText(m?.delta != null ? `${m.delta > 0 ? "+" : ""}${m.delta}` : "re-scoring…", x, y + r + 4 * px);
    } else {
      // entity (and theme): a star coloured by its source
      ctx.shadowColor = color;
      ctx.shadowBlur = isSel || isHover ? 22 : 10;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.fillStyle = "rgba(4,6,11,0.28)";
      ctx.beginPath();
      ctx.arc(x, y, r * 0.45, 0, Math.PI * 2);
      ctx.fill();
      if (n.badges.includes("merged")) {
        ctx.strokeStyle = BONE;
        ctx.lineWidth = 1.2 * px;
        ctx.beginPath();
        ctx.arc(x, y, r + 3.5, 0, Math.PI * 2);
        ctx.stroke();
      }
      if (n.badges.includes("imputed")) {
        ctx.strokeStyle = AMBER;
        ctx.lineWidth = px;
        ctx.setLineDash([2 * px, 3 * px]);
        ctx.beginPath();
        ctx.arc(x, y, r + 6.5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      if (n.badges.includes("conflict")) {
        ctx.fillStyle = RED;
        ctx.beginPath();
        ctx.arc(x + r * 0.78, y - r * 0.78, 3, 0, Math.PI * 2);
        ctx.fill();
      }
      if (n.badges.includes("winner")) {
        ctx.fillStyle = AMBER;
        starPath(ctx, x - r * 0.85, y - r * 0.85, 4.5);
        ctx.fill();
      }
      if (n.badges.includes("ai_written")) {
        ctx.fillStyle = CLOUD;
        ctx.fillRect(x + r * 0.6, y + r * 0.6, 4, 4);
      }
      ctx.font = `italic ${(isSel || isHover ? 14 : 12.5) * px}px ${FONT.serif}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.lineWidth = 3 * px;
      ctx.strokeStyle = "rgba(4,6,11,0.85)";
      const text = truncate(n.label, 24);
      ctx.strokeText(text, x, y + r + 8 * px);
      ctx.fillStyle = isSel || isHover ? "#fff" : `rgba(236,229,211,${0.55 + 0.45 * grow})`;
      ctx.fillText(text, x, y + r + 8 * px);
    }

    if (isSel) {
      const R = nodeRadius(n) + 9;
      ctx.strokeStyle = AMBER;
      ctx.lineWidth = 1.2 * px;
      ctx.beginPath();
      ctx.arc(x, y, R, 0, Math.PI * 2);
      ctx.stroke();
      for (const a of [0, Math.PI / 2, Math.PI, (3 * Math.PI) / 2]) {
        ctx.beginPath();
        ctx.moveTo(x + Math.cos(a) * (R - 3), y + Math.sin(a) * (R - 3));
        ctx.lineTo(x + Math.cos(a) * (R + 6), y + Math.sin(a) * (R + 6));
        ctx.stroke();
      }
    }
    ctx.restore();
  }, []);

  const paintPointer = useCallback((raw: NodeObject<SimNode>, color: string, ctx: CanvasRenderingContext2D) => {
    const n = raw as SimNode;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(n.x ?? 0, n.y ?? 0, Math.max(9, nodeRadius(n) + 4), 0, Math.PI * 2);
    ctx.fill();
  }, []);

  const paintOverlay = useCallback((ctx: CanvasRenderingContext2D, scale: number) => {
    const t = now();
    const px = 1 / scale;
    ghosts.current = ghosts.current.filter((g) => t - g.at < 1000);
    for (const g of ghosts.current) {
      const p = Math.min(1, (t - g.at) / 850);
      const e = 1 - Math.pow(1 - p, 3);
      const tx = g.to?.x ?? g.x;
      const ty = g.to?.y ?? g.y;
      const x = g.x + (tx - g.x) * e;
      const y = g.y + (ty - g.y) * e;
      ctx.save();
      ctx.globalAlpha = 1 - p;
      ctx.strokeStyle = BONE;
      ctx.lineWidth = px;
      ctx.setLineDash([2 * px, 3 * px]);
      ctx.beginPath();
      ctx.moveTo(g.x, g.y);
      ctx.lineTo(tx, ty);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = g.color;
      ctx.beginPath();
      ctx.arc(x, y, g.r * (1 - 0.6 * e), 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
  }, []);

  const linkColor = useCallback((l: LinkObject<SimNode, SimLink>) => {
    const link = l as SimLink;
    const target = link.target as SimNode;
    switch (link.kind) {
      case "has_facet": return "rgba(201,154,58,0.5)";
      case "possible_same_as": return "rgba(244,185,66,0.9)";
      case "same_as": return "rgba(236,229,211,0.8)";
      case "mutation_of": return "rgba(79,214,192,0.22)";
      case "shares_facet":
      case "tagged": return "rgba(150,176,230,0.16)";
      default:
        if (target?.kind === "prior") return "rgba(136,145,165,0.13)";
        return `${sourceColor(target?.source)}${Math.round((0.14 + 0.3 * (link.weight ?? 0.5)) * 255).toString(16).padStart(2, "0")}`;
    }
  }, []);
  const linkDash = useCallback((l: LinkObject<SimNode, SimLink>) => {
    const k = (l as SimLink).kind;
    return k === "possible_same_as" ? [2, 3] : k === "mutation_of" ? [1, 4] : null;
  }, []);
  const linkWidth = useCallback((l: LinkObject<SimNode, SimLink>) => {
    const link = l as SimLink;
    return link.kind === "possible_same_as" || link.kind === "same_as" ? 1.4 : link.kind === "similar" ? 0.5 + (link.weight ?? 0.5) : 0.7;
  }, []);

  const paintLinkLabel = useCallback((l: LinkObject<SimNode, SimLink>, ctx: CanvasRenderingContext2D, scale: number) => {
    const link = l as SimLink;
    if (link.kind !== "possible_same_as") return;
    const s = link.source as SimNode;
    const t = link.target as SimNode;
    if (s?.x == null || t?.x == null) return;
    const px = 1 / scale;
    ctx.save();
    ctx.font = `${9 * px}px ${FONT.mono}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const mx = (s.x + t.x) / 2;
    const my = ((s.y ?? 0) + (t.y ?? 0)) / 2;
    const w = ctx.measureText("same? left open").width + 8 * px;
    ctx.fillStyle = "rgba(4,6,11,0.9)";
    ctx.fillRect(mx - w / 2, my - 7 * px, w, 14 * px);
    ctx.fillStyle = AMBER;
    ctx.fillText("same? left open", mx, my);
    ctx.restore();
  }, []);

  // --- interaction ------------------------------------------------------------------------------------------------
  const onHover = useCallback((raw: NodeObject<SimNode> | null) => {
    const n = raw as SimNode | null;
    live.current.hoverId = n ? String(n.id) : null;
    if (!n || !fg.current) { setHover(null); return; }
    const p = fg.current.graph2ScreenCoords(n.x ?? 0, n.y ?? 0);
    setHover({ node: n, x: p.x, y: p.y });
  }, []);

  const onClick = useCallback((raw: NodeObject<SimNode>) => {
    const n = raw as SimNode;
    const clean = graph.nodes[String(n.id)];
    if (clean) onSelect(clean);
  }, [graph.nodes, onSelect]);

  const tooltip = useMemo(() => {
    if (!hover) return null;
    const n = hover.node;
    let kicker = "";
    let body: string | null = null;
    if (n.kind === "idea") { kicker = "Your idea"; body = "Pinned at the pole. Everything else is placed by how similar it is to this."; }
    else if (n.kind === "facet") { const key = String(n.id).slice(6); kicker = `Facet · ${key}`; body = (facets as unknown as Record<string, string> | null)?.[key] ?? n.label; }
    else if (n.kind === "prior") { const s = priorSamples[Number(String(n.id).slice(6)) - 1]; kicker = "LLM prior: what a model suggests unprompted"; body = s ? `“${s.text}”` : n.label; }
    else if (n.kind === "mutation") { const m = mutations[String(n.id).slice(4)]; kicker = `Mutation · ${m?.facet ?? ""}`; body = m ? `${m.frm} → ${m.to}` : n.label; }
    else if (n.kind === "theme") { kicker = "Theme"; body = n.label; }
    else { kicker = `${sourceLabel(n.source)}${n.year ? ` · ${n.year}` : ""}`; body = null; }
    const flip = hover.x > size.w - 250;
    return (
      <div
        className="pointer-events-none absolute z-10 w-[232px] border border-line-strong bg-ink-800/95 px-2.5 py-2 shadow-[0_10px_30px_rgb(0_0_0/0.6)] backdrop-blur"
        style={{ left: flip ? undefined : hover.x + 16, right: flip ? size.w - hover.x + 16 : undefined, top: Math.max(6, Math.min(size.h - 120, hover.y - 18)) }}
      >
        <div className="font-mono text-[9px] uppercase tracking-[0.16em] text-mute">{kicker}</div>
        {n.kind === "entity" && <div className="mt-0.5 font-display text-[17px] italic leading-tight text-bone">{n.label}</div>}
        {body && <div className="mt-1 text-[12px] leading-snug text-bone-dim">{body}</div>}
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {typeof n.similarity === "number" && <span className="chip" data-tone="bone">sim {fmtSim(n.similarity)}</span>}
          {n.kind === "prior" && priorSamples[Number(String(n.id).slice(6)) - 1] && <span className="chip" data-tone="mute">{priorSamples[Number(String(n.id).slice(6)) - 1].model.split("/").pop()}</span>}
          {n.badges.map((b) => (
            <span key={b} className="chip" data-tone={b === "conflict" ? "red" : b === "winner" || b === "imputed" ? "amber" : "mute"}>{b === "imputed" ? "inferred field" : b.replace("_", " ")}</span>
          ))}
        </div>
        {n.kind === "entity" && <div className="mt-1.5 font-mono text-[9px] text-faint">click to open its evidence</div>}
      </div>
    );
  }, [hover, facets, mutations, priorSamples, size.w, size.h]);

  return (
    <div
      ref={wrap}
      className="absolute inset-0 overflow-hidden"
      onWheelCapture={() => { userMoved.current = true; }}
      onPointerDownCapture={(e) => { drag.current = { x: e.clientX, y: e.clientY }; }}
      onPointerMoveCapture={(e) => { if (drag.current && e.buttons === 1 && Math.hypot(e.clientX - drag.current.x, e.clientY - drag.current.y) > 6) userMoved.current = true; }}
      onPointerUpCapture={() => { drag.current = null; }}
    >
      {size.w > 0 && size.h > 0 && (
        <ForceGraph2D<SimNode, SimLink>
          ref={fg}
          width={size.w}
          height={size.h}
          graphData={data}
          backgroundColor="rgba(0,0,0,0)"
          nodeRelSize={4}
          nodeLabel={() => ""}
          nodeCanvasObject={paintNode}
          nodeCanvasObjectMode={() => "replace"}
          nodePointerAreaPaint={paintPointer}
          linkColor={linkColor}
          linkLineDash={linkDash}
          linkWidth={linkWidth}
          linkCanvasObjectMode={() => "after"}
          linkCanvasObject={paintLinkLabel}
          onRenderFramePre={paintBackdrop}
          onRenderFramePost={paintOverlay}
          autoPauseRedraw={false}
          d3VelocityDecay={0.42}
          d3AlphaDecay={0.028}
          cooldownTime={9000}
          minZoom={0.3}
          maxZoom={6}
          onNodeHover={onHover}
          onNodeClick={onClick}
          onNodeDragEnd={(n) => { const node = n as SimNode; if (node.kind !== "idea" && node.kind !== "facet") { node.fx = undefined; node.fy = undefined; } }}
          onBackgroundClick={() => onSelect(null)}
          onZoom={() => { if (!fitting.current) setHover(null); }}
        />
      )}
      {tooltip}
      <button
        type="button"
        className="btn btn-sm absolute bottom-2 right-2 bg-ink-900/80"
        onClick={() => { userMoved.current = false; fit(500); }}
        title="Centre the chart on your idea"
      >
        Re-centre
      </button>
    </div>
  );
}
