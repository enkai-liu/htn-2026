// The islands map promises two things: closer means more similar (relative to what the run found), and nothing
// jumps when something new arrives inside the band the rings are already stretched over.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { applyGraphPatch, emptyGraph, type GraphState } from "../lib/graphReducer";
import { emptyLayout, foldLayout, GAP, R_MIN, R_SPAN, ringRadius, sectorFor, simScale, type LayoutState } from "../lib/islandLayout";
import { parseJsonl } from "../lib/replay";
import { initialRunState, runReducer } from "../lib/runReducer";
import type { GraphNode } from "../lib/types";

const node = (id: string, kind: GraphNode["kind"], similarity: number | null, source: string | null = null, val = 3): GraphNode =>
  ({ id, kind, label: id, source, similarity, year: null, url: null, badges: [], val });

const SOURCES = ["devpost", "yc", "github", "hn", "web", "arxiv"];
const ctx = { mutationFacet: { m1: "mechanism", m2: "mechanism" } };

function crowd(n: number): GraphNode[] {
  // mostly very similar, like a real run: the hard case for packing
  return Array.from({ length: n }, (_, i) => node(`ent:e${i}`, "entity", i % 9 === 0 ? 0.3 : 0.9 + ((i * 37) % 10) / 100, SOURCES[i % 3 === 0 ? 0 : i % SOURCES.length]));
}

function build(nodes: GraphNode[], oneByOne: boolean): { graph: GraphState; layout: LayoutState } {
  let graph = emptyGraph;
  let layout = emptyLayout;
  if (oneByOne) {
    for (const n of nodes) { graph = applyGraphPatch(graph, { add_nodes: [n] }); layout = foldLayout(layout, graph, ctx); }
  } else {
    graph = applyGraphPatch(graph, { add_nodes: nodes });
    layout = foldLayout(layout, graph, ctx);
  }
  return { graph, layout };
}

const all = [node("idea", "idea", null), ...crowd(60), node("prior:1", "prior", 0.6), node("prior:2", "prior", 0.5), node("mut:m1", "mutation", 0.6), node("mut:m2", "mutation", 0.5)];

describe("islandLayout", () => {
  it("is deterministic, and folding one patch at a time equals folding them all at once", () => {
    const a = build(all, true).layout;
    const b = build(all, true).layout;
    const c = build(all, false).layout;
    expect(a.byId).toEqual(b.byId);
    expect(a.byId).toEqual(c.byId);
  });

  it("puts more similar islands closer", () => {
    const scale = { lo: 0, hi: 1 };
    const sims = [1, 0.9, 0.75, 0.5, 0.25, 0];
    const radii = sims.map((s) => ringRadius(s, scale));
    expect(radii).toEqual([...radii].sort((x, y) => x - y));
    expect(ringRadius(1.6, scale)).toBe(R_MIN); // uncalibrated rerank scores above 1 clamp to the innermost ring
    expect(ringRadius(-0.2, scale)).toBe(ringRadius(0, scale));
  });

  it("spreads a run of low scores over all the orbits instead of parking it at the rim", () => {
    const low = [node("idea", "idea", null), ...[0.04, 0.07, 0.1, 0.13, 0.16, 0.19].map((s, i) => node(`ent:l${i}`, "entity", s, SOURCES[i]))];
    const { graph, layout } = build(low, true);
    expect(simScale(graph)).toEqual(layout.scale);
    const rings = low.slice(1).map((n) => layout.byId[n.id].radius - layout.byId[n.id].nudge);
    expect(Math.min(...rings)).toBeLessThan(R_MIN + R_SPAN * 0.1);
    expect(Math.max(...rings)).toBeGreaterThan(R_MIN + R_SPAN * 0.7);
    expect(rings).toEqual([...rings].sort((x, y) => y - x)); // still ordered: the most similar is the closest
    // the same scores shifted up the scale land on the same rings: only the relative position counts
    const high = low.map((n) => (n.kind === "idea" ? n : { ...n, similarity: n.similarity! + 0.8 }));
    const shifted = build(high, true).layout;
    for (const n of low.slice(1)) expect(shifted.byId[n.id].radius).toBeCloseTo(layout.byId[n.id].radius, 9);
  });

  it("leaves projects with no similarity at all off the map, and brings one back if it is re-scored", () => {
    const { graph, layout } = build([...all, node("ent:zero", "entity", 0, "devpost"), node("prior:zero", "prior", 0.001), node("mut:zero", "mutation", 0)], true);
    expect(layout.byId["ent:zero"]).toBeUndefined();
    expect(layout.byId["prior:zero"]).toBeUndefined();
    expect(layout.byId["mut:zero"]).toBeDefined(); // a mutation that got all the way to 0 is the point of the exercise
    expect(layout.scale).toEqual(build(all, true).layout.scale); // and they do not stretch the band either
    const rescored = applyGraphPatch(graph, { update_nodes: [{ id: "ent:zero", similarity: 0.5 }] });
    const back = foldLayout(layout, rescored, ctx);
    expect(back.byId["ent:zero"]).toBeDefined();
    const gone = foldLayout(back, applyGraphPatch(rescored, { update_nodes: [{ id: "ent:e5", similarity: 0 }] }), ctx);
    expect(gone.byId["ent:e5"]).toBeUndefined();
  });

  it("re-lays the map when a new extreme widens the band, to the same layout a fresh fold would give", () => {
    const { graph, layout } = build(all, true);
    const next = applyGraphPatch(graph, { add_nodes: [node("ent:far", "entity", 0.1, "yc")] });
    const widened = foldLayout(layout, next, ctx);
    expect(widened.scale).not.toEqual(layout.scale);
    expect(widened.byId).toEqual(foldLayout(emptyLayout, next, ctx).byId);
    expect(widened.byId["ent:e0"].radius).toBeLessThan(layout.byId["ent:e0"].radius); // 0.3 is no longer the far end
    expectClearWater(widened);
  });

  const expectClearWater = (layout: LayoutState) => {
    const ps = layout.order.map((id) => layout.byId[id]);
    for (let i = 0; i < ps.length; i++) {
      for (let j = i + 1; j < ps.length; j++) {
        const d = Math.hypot(ps[i].x - ps[j].x, ps[i].z - ps[j].z);
        expect(d, `${ps[i].id} vs ${ps[j].id}`).toBeGreaterThanOrEqual(ps[i].size + ps[j].size + GAP - 1e-9);
      }
    }
  };

  it("never overlaps two islands, or an island and a boat, even in a crowded neighbourhood", () => {
    expectClearWater(build(all, true).layout);
  });

  it("never berths a re-scored boat inside an island: it steps out along its bearing to clear water", () => {
    const { graph, layout } = build(all, true);
    const a = layout.byId["mut:m1"];
    // an island sitting exactly where m1 would land at similarity 0.3
    const r = ringRadius(0.3, layout.scale);
    const rock = { ...layout.byId["ent:e1"], id: "ent:rock", angle: a.angle, radius: r, nudge: 0, x: Math.cos(a.angle) * r, z: Math.sin(a.angle) * r };
    const withRock: LayoutState = { ...layout, byId: { ...layout.byId, "ent:rock": rock }, order: [...layout.order, "ent:rock"] };
    let next = applyGraphPatch(graph, { add_nodes: [node("ent:rock", "entity", 0.3, "devpost")] });
    next = applyGraphPatch(next, { update_nodes: [{ id: "mut:m1", similarity: 0.3 }] });
    const moved = foldLayout(withRock, next, ctx);
    expect(moved.byId["mut:m1"].angle).toBe(a.angle);
    expect(moved.byId["mut:m1"].nudge).toBeGreaterThan(0);
    expectClearWater(moved);
  });

  it("keeps every source inside its own wedge and never pulls an island inside its ring", () => {
    const { graph, layout } = build(all, true);
    for (const id of layout.order) {
      const p = layout.byId[id];
      if (p.kind !== "entity") continue;
      const { centre, half } = sectorFor("entity", graph.nodes[id].source);
      expect(Math.abs(p.angle - centre)).toBeLessThanOrEqual(half + 1e-9);
      expect(p.nudge).toBeGreaterThanOrEqual(0);
      expect(p.radius).toBeCloseTo(ringRadius(graph.nodes[id].similarity, layout.scale) + p.nudge, 9);
    }
  });

  it("does not move anything that is already placed when islands arrive or leave", () => {
    const before = build(all.slice(0, 30), true);
    let graph = applyGraphPatch(before.graph, { add_nodes: all.slice(30) });
    let layout = foldLayout(before.layout, graph, ctx);
    for (const id of before.layout.order) expect(layout.byId[id]).toEqual(before.layout.byId[id]);

    graph = applyGraphPatch(graph, { remove_nodes: ["ent:e3", "ent:e4"] });
    const after = foldLayout(layout, graph, ctx);
    expect(after.byId["ent:e3"]).toBeUndefined();
    for (const id of after.order) expect(after.byId[id]).toEqual(layout.byId[id]);
    layout = after;
    expect(layout.order).not.toContain("ent:e4");
  });

  it("slides a re-scored mutation along its own bearing and leaves the rest alone", () => {
    const { graph, layout } = build(all, true);
    const next = applyGraphPatch(graph, { update_nodes: [{ id: "mut:m1", similarity: 0.2 }] });
    const moved = foldLayout(layout, next, ctx);
    const a = layout.byId["mut:m1"];
    const b = moved.byId["mut:m1"];
    expect(b.angle).toBe(a.angle);
    expect(b.y).toBe(a.y);
    expect(b.radius).toBeGreaterThan(a.radius);
    for (const id of layout.order) if (id !== "mut:m1") expect(moved.byId[id]).toBe(layout.byId[id]);
    // two mutations of the same facet fan out instead of stacking
    expect(layout.byId["mut:m2"].angle).not.toBe(a.angle);
  });

  it("returns the same object when the graph has not changed", () => {
    const { graph, layout } = build(all, true);
    expect(foldLayout(layout, graph, ctx)).toBe(layout);
  });

  it("lays out the recorded mock run without a NaN, skipping facet nodes", () => {
    const path = fileURLToPath(new URL("../public/replay/mock.jsonl", import.meta.url));
    let run = initialRunState;
    let layout = emptyLayout;
    for (const ev of parseJsonl(readFileSync(path, "utf8"))) {
      run = runReducer(run, ev);
      const mutationFacet = Object.fromEntries(run.mutationOrder.map((mid) => [mid, run.mutations[mid].facet]));
      layout = foldLayout(layout, run.graph, { mutationFacet });
    }
    expect(layout.order).toContain("idea");
    expect(layout.order.some((id) => id.startsWith("facet:"))).toBe(false);
    expect(layout.order.filter((id) => id.startsWith("ent:")).length).toBe(7);
    expect(layout.order.filter((id) => id.startsWith("mut:")).length).toBe(3);
    for (const id of layout.order) for (const v of Object.values(layout.byId[id])) if (typeof v === "number") expect(Number.isFinite(v)).toBe(true);
  });
});
