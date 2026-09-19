// A small, invented archipelago for the landing page. It goes through the same reducer and layout as a real run,
// so the hero is the product, not a drawing of it. The labels are never shown.
import { applyGraphPatch, emptyGraph, type GraphState } from "./graphReducer";
import { emptyLayout, foldLayout, type LayoutState } from "./islandLayout";
import type { GraphNode } from "./types";

const n = (id: string, kind: GraphNode["kind"], similarity: number | null, source: string | null, val: number): GraphNode =>
  ({ id, kind, label: id, source, similarity, year: null, url: null, badges: [], val });

const NODES: GraphNode[] = [
  n("idea", "idea", null, null, 8),
  n("ent:h1", "entity", 0.86, "devpost", 5), n("ent:h2", "entity", 0.78, "devpost", 4), n("ent:h3", "entity", 0.61, "devpost", 3.4),
  n("ent:h4", "entity", 0.52, "devpost", 3), n("ent:h5", "entity", 0.74, "yc", 4.4), n("ent:h6", "entity", 0.48, "yc", 3.2),
  n("ent:h7", "entity", 0.66, "github", 3.8), n("ent:h8", "entity", 0.4, "github", 2.6), n("ent:h9", "entity", 0.57, "hn", 3),
  n("ent:h10", "entity", 0.3, "devpost", 2.4), n("ent:h11", "entity", 0.35, "yc", 2.4),
  n("prior:1", "prior", 0.7, null, 1.2), n("prior:2", "prior", 0.62, null, 1.2), n("prior:3", "prior", 0.55, null, 1.2),
  n("mut:a", "mutation", 0.34, null, 3), n("mut:b", "mutation", 0.22, null, 3),
];

export function heroIslands(): { graph: GraphState; layout: LayoutState } {
  const graph = applyGraphPatch(emptyGraph, {
    add_nodes: NODES,
    add_links: [
      ...NODES.filter((x) => x.kind === "entity").map((x) => ({ source: "idea", target: x.id, kind: "similar" as const, weight: x.similarity ?? 0.5 })),
      { source: "idea", target: "mut:a", kind: "mutation_of", weight: 0.5 },
      { source: "idea", target: "mut:b", kind: "mutation_of", weight: 0.5 },
      { source: "ent:h1", target: "ent:h2", kind: "possible_same_as", weight: 0.7 },
    ],
  });
  return { graph, layout: foldLayout(emptyLayout, graph, { mutationFacet: { a: "audience", b: "twist" } }) };
}
