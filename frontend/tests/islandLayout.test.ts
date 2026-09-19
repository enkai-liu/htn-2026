// The islands map promises two things: distance means similarity, and nothing jumps when something new arrives.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { applyGraphPatch, emptyGraph, type GraphState } from "../lib/graphReducer";
import { emptyLayout, foldLayout, GAP, R_MIN, ringRadius, sectorFor, type LayoutState } from "../lib/islandLayout";
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
    const sims = [1, 0.9, 0.75, 0.5, 0.25, 0];
    const radii = sims.map(ringRadius);
    expect(radii).toEqual([...radii].sort((x, y) => x - y));
    expect(ringRadius(1.6)).toBe(R_MIN); // uncalibrated rerank scores above 1 clamp to the innermost ring
    expect(ringRadius(-0.2)).toBe(ringRadius(0));
  });

  it("never overlaps two ground islands, even in a crowded neighbourhood", () => {
    const { layout } = build(all, true);
    const ground = layout.order.map((id) => layout.byId[id]).filter((p) => p.kind !== "mutation");
    for (let i = 0; i < ground.length; i++) {
      for (let j = i + 1; j < ground.length; j++) {
        const d = Math.hypot(ground[i].x - ground[j].x, ground[i].z - ground[j].z);
        expect(d, `${ground[i].id} vs ${ground[j].id}`).toBeGreaterThanOrEqual(ground[i].size + ground[j].size + GAP - 1e-9);
      }
    }
  });

  it("keeps every source inside its own wedge and never pulls an island inside its ring", () => {
    const { graph, layout } = build(all, true);
    for (const id of layout.order) {
      const p = layout.byId[id];
      if (p.kind !== "entity") continue;
      const { centre, half } = sectorFor("entity", graph.nodes[id].source);
      expect(Math.abs(p.angle - centre)).toBeLessThanOrEqual(half + 1e-9);
      expect(p.nudge).toBeGreaterThanOrEqual(0);
      expect(p.radius).toBeCloseTo(ringRadius(graph.nodes[id].similarity) + p.nudge, 9);
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
