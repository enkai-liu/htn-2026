// Pure reducer for the idea-space graph. Folds GraphPatch objects (docs/events.md, "Graph conventions").
//
// Guarantees:
//   - `links` never references a node that is not in `nodes` (removing a node drops its links;
//     a link that arrives before one of its endpoints waits in `pending` until the endpoint exists).
//   - Applying the same patch twice gives the same state (adds are upserts, links are keyed).
import type { GraphLink, GraphNode, GraphPatch } from "./types";

export interface GraphState {
  nodes: Record<string, GraphNode>;
  /** insertion order of node ids, so rendering is stable */
  order: string[];
  links: GraphLink[];
  /** links whose endpoints have not both arrived yet */
  pending: GraphLink[];
  /** bumps on every applied patch */
  rev: number;
  /** bumps only when nodes/links are added or removed (the simulation needs new graphData) */
  topoRev: number;
}

export const emptyGraph: GraphState = { nodes: {}, order: [], links: [], pending: [], rev: 0, topoRev: 0 };

export const linkKey = (l: Pick<GraphLink, "source" | "target" | "kind">) => `${l.source}→${l.target}·${l.kind}`;

function normaliseNode(n: Partial<GraphNode> & { id: string }): GraphNode {
  return {
    id: n.id,
    kind: n.kind ?? "entity",
    label: n.label ?? n.id,
    source: n.source ?? null,
    similarity: n.similarity ?? null,
    year: n.year ?? null,
    url: n.url ?? null,
    badges: Array.isArray(n.badges) ? n.badges : [],
    val: typeof n.val === "number" && Number.isFinite(n.val) ? n.val : 2,
  };
}

export function applyGraphPatch(state: GraphState, patch: Partial<GraphPatch> | null | undefined): GraphState {
  if (!patch) return state;
  const addNodes = patch.add_nodes ?? [];
  const addLinks = patch.add_links ?? [];
  const updateNodes = patch.update_nodes ?? [];
  const removeNodes = patch.remove_nodes ?? [];
  if (!addNodes.length && !addLinks.length && !updateNodes.length && !removeNodes.length) return state;

  let nodes = state.nodes;
  let order = state.order;
  let links = state.links;
  let pending = state.pending;
  let topoChanged = false;

  if (addNodes.length) {
    nodes = { ...nodes };
    order = [...order];
    for (const raw of addNodes) {
      if (!raw || typeof raw.id !== "string") continue;
      if (nodes[raw.id]) {
        // duplicate add = upsert (keeps the reducer idempotent)
        nodes[raw.id] = normaliseNode({ ...nodes[raw.id], ...raw });
      } else {
        nodes[raw.id] = normaliseNode(raw);
        order.push(raw.id);
        topoChanged = true;
      }
    }
  }

  if (updateNodes.length) {
    if (nodes === state.nodes) nodes = { ...nodes };
    for (const upd of updateNodes) {
      if (!upd || typeof upd.id !== "string") continue;
      const cur = nodes[upd.id];
      if (!cur) continue; // update for a node we never saw (or already absorbed): nothing to do
      const next: GraphNode = { ...cur };
      for (const [k, v] of Object.entries(upd)) {
        if (k === "id" || v === undefined) continue;
        (next as unknown as Record<string, unknown>)[k] = v;
      }
      nodes[upd.id] = next;
    }
  }

  if (removeNodes.length) {
    const gone = new Set(removeNodes.filter((id) => nodes[id]));
    const goneAny = new Set(removeNodes);
    if (gone.size) {
      if (nodes === state.nodes) nodes = { ...nodes };
      for (const id of gone) delete nodes[id];
      order = order.filter((id) => !gone.has(id));
      topoChanged = true;
    }
    const keep = (l: GraphLink) => !goneAny.has(l.source) && !goneAny.has(l.target);
    if (links.some((l) => !keep(l))) { links = links.filter(keep); topoChanged = true; }
    if (pending.some((l) => !keep(l))) pending = pending.filter(keep);
  }

  if (addLinks.length || pending.length) {
    const byKey = new Map(links.map((l) => [linkKey(l), l] as const));
    const stillPending: GraphLink[] = [];
    let linksChanged = false;
    for (const raw of [...pending, ...addLinks]) {
      if (!raw || typeof raw.source !== "string" || typeof raw.target !== "string") continue;
      const link: GraphLink = { source: raw.source, target: raw.target, kind: raw.kind ?? "similar", weight: typeof raw.weight === "number" ? raw.weight : 0.5 };
      if (!nodes[link.source] || !nodes[link.target]) {
        if (!stillPending.some((p) => linkKey(p) === linkKey(link))) stillPending.push(link);
        continue;
      }
      const key = linkKey(link);
      const existing = byKey.get(key);
      if (!existing) { byKey.set(key, link); linksChanged = true; topoChanged = true; }
      else if (existing.weight !== link.weight) { byKey.set(key, link); linksChanged = true; }
    }
    if (linksChanged) links = [...byKey.values()];
    pending = stillPending;
  }

  return { nodes, order, links, pending, rev: state.rev + 1, topoRev: state.topoRev + (topoChanged ? 1 : 0) };
}

/** Sanity check used by tests and by the dev overlay: every link endpoint must exist. */
export function danglingLinks(g: GraphState): GraphLink[] {
  return g.links.filter((l) => !g.nodes[l.source] || !g.nodes[l.target]);
}
