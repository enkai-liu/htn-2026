"use client";
// The floating-islands map: shapes the graph + layout into what the scene draws, and owns everything that is not
// WebGL: the text alternative, the loading state, and the fallback to the 2D chart when WebGL is not available.
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { sourceHex } from "@/lib/format";
import type { GraphState } from "@/lib/graphReducer";
import type { LayoutState } from "@/lib/islandLayout";
import { IslandLoader } from "./IslandLoader";
import type { IslandMapCanvasProps } from "./IslandMapCanvas";
import type { IslandDatum, SceneLink } from "./IslandScene";

// no `loading` here: IslandLoader sits over the canvas and outlives the chunk download, until the first frame is drawn
const Canvas = dynamic(() => import("./IslandMapCanvas"), { ssr: false });

const IDEA_TINT = "#f4b942";
const PRIOR_TINT = "#a9adb5";
const MUTATION_TINT = "#0f9488";

export function hasWebGL(): boolean {
  if (typeof document === "undefined") return true;
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") ?? c.getContext("webgl"));
  } catch {
    return false;
  }
}

export function shapeIslands(graph: GraphState, layout: LayoutState): { islands: IslandDatum[]; links: SceneLink[] } {
  const islands: IslandDatum[] = [];
  for (const id of layout.order) {
    const n = graph.nodes[id];
    const p = layout.byId[id];
    if (!n || !p) continue;
    const tint = p.kind === "idea" ? IDEA_TINT : p.kind === "prior" ? PRIOR_TINT : p.kind === "mutation" ? MUTATION_TINT : sourceHex(n.source);
    islands.push({ id, label: n.label, tint, badges: n.badges, similarity: n.similarity ?? null, p });
  }
  const links: SceneLink[] = [];
  for (const l of graph.links) {
    if (l.kind !== "similar" && l.kind !== "possible_same_as" && l.kind !== "mutation_of") continue;
    if (!layout.byId[l.source] || !layout.byId[l.target]) continue;
    links.push({ a: l.source, b: l.target, kind: l.kind });
  }
  return { islands, links };
}

export interface IslandMapProps extends Pick<IslandMapCanvasProps, "selectedId" | "onSelect" | "onHover" | "seen" | "cameraMemo" | "recenterTick" | "ambient"> {
  graph: GraphState;
  layout: LayoutState;
  /** rendered instead of the islands when WebGL is missing or its context is lost */
  fallback?: React.ReactNode;
  /** the data is still on its way: keep the loader up even though the scene itself is ready */
  pending?: boolean;
}

export function IslandMap({ graph, layout, fallback, pending, ...rest }: IslandMapProps) {
  const [lost, setLost] = useState(false);
  const [ready, setReady] = useState(false);
  const [supported] = useState(hasWebGL);
  const { islands, links } = useMemo(() => shapeIslands(graph, layout), [graph, layout]);
  const listed = useMemo(() => islands.filter((i) => i.p.kind !== "idea").sort((a, b) => (b.similarity ?? 0) - (a.similarity ?? 0)), [islands]);
  const entities = islands.filter((i) => i.p.kind === "entity").length;

  if (!supported || lost) return <>{fallback ?? null}</>;

  const canvas = <Canvas islands={islands} links={links} layout={layout} onContextLost={() => setLost(true)} onReady={() => setReady(true)} {...rest} />;
  const loader = <IslandLoader gone={ready && !pending} quiet={rest.ambient} />;

  if (rest.ambient) return <div className="absolute inset-0" aria-hidden>{canvas}{loader}</div>;

  return (
    <figure className="absolute inset-0 m-0" aria-label={`Map of the idea-space: your idea at the centre, ${entities} prior-art projects placed by similarity, closer means more similar.`}>
      {canvas}
      {loader}
      {/* the same islands as a list: the keyboard and screen-reader path into the map */}
      <ul className="sr-only">
        {listed.map((i) => (
          <li key={i.id}>
            <button type="button" onClick={() => rest.onSelect(i.id)}>
              {i.label}{i.similarity != null ? `, similarity ${i.similarity.toFixed(2)}` : ""}
            </button>
          </li>
        ))}
      </ul>
    </figure>
  );
}
