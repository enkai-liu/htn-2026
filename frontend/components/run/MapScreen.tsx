"use client";
// The home tab: the map and almost nothing else. One line says what the swarm is doing; the rest is on other pages.
import { LocateFixed } from "lucide-react";
import { useMemo, useState } from "react";
import { agentColor } from "@/lib/agents";
import { IdeaGraph } from "../IdeaGraph";
import { IslandMap } from "../islands/IslandMap";
import { SimulatedTag } from "../ui";
import { DetailCard } from "./DetailCard";
import { MapLegend } from "./MapLegend";
import { useRun } from "./RunProvider";

export function MapScreen() {
  const { run, streaming, selectedId, select, seenIslands, cameraMemo, mapMode } = useRun();
  const { state, layout } = run;
  const { graph } = state;
  const [recenterTick, setRecenterTick] = useState(0);

  const stats = useMemo(() => {
    const counts = { entity: 0, prior: 0, mutation: 0 };
    const bySource = new Map<string, number>();
    for (const id of graph.order) {
      const n = graph.nodes[id];
      if (n.kind === "entity") { counts.entity++; if (n.source) bySource.set(n.source, (bySource.get(n.source) ?? 0) + 1); }
      else if (n.kind === "prior") counts.prior++;
      else if (n.kind === "mutation") counts.mutation++;
    }
    const sources = [...bySource].map(([source, count]) => ({ source, count })).sort((a, b) => b.count - a.count);
    return { counts, sources };
  }, [graph]);

  const caption = useMemo(() => {
    for (let i = state.timeline.length - 1; i >= 0; i--) if (!state.timeline[i].sub) return state.timeline[i];
    return null;
  }, [state.timeline]);

  const selected = selectedId ? graph.nodes[selectedId] ?? null : null;
  const empty = layout.order.length === 0;

  const flat = (
    <div className="absolute inset-x-4 bottom-4 top-2 overflow-hidden rounded-[22px] theme-dark">
      <IdeaGraph
        graph={graph} facets={state.facets} mutations={state.mutations} priorSamples={state.priorSamples}
        active={streaming && !state.finished} selectedId={selectedId} onSelect={(n) => select(n?.id ?? null)}
      />
    </div>
  );

  return (
    <div className="absolute inset-0">
      {mapMode === "2d" ? flat : (
        <IslandMap
          graph={graph} layout={layout} selectedId={selectedId} onSelect={select}
          seen={seenIslands.current} cameraMemo={cameraMemo} recenterTick={recenterTick} fallback={flat} pending={empty}
        />
      )}

      {mapMode === "3d" && (
        <>
          <div className="pointer-events-none absolute left-5 top-1 sm:left-7">
            <h1 className="font-display text-[30px] leading-tight text-bone">The idea-space</h1>
            <p className="text-[13.5px] text-mute">
              {empty ? "Waiting for the conductor to place your idea" : `${stats.counts.entity} prior-art ${stats.counts.entity === 1 ? "project" : "projects"}${stats.counts.prior ? ` · ${stats.counts.prior} LLM guesses` : ""}${stats.counts.mutation ? ` · ${stats.counts.mutation} mutations` : ""} · closer means more similar`}
            </p>
          </div>

          {!empty && (
            <div className="absolute bottom-14 left-5 sm:left-7">
              <MapLegend
                sources={stats.sources} priors={stats.counts.prior} mutations={stats.counts.mutation}
                sameAs={graph.links.some((l) => l.kind === "possible_same_as")}
              />
            </div>
          )}

          {!empty && !selected && (
            <button type="button" onClick={() => setRecenterTick((n) => n + 1)} className="absolute right-5 top-2 flex size-9 items-center justify-center rounded-full border border-line bg-ink-900 text-bone-dim transition-colors hover:text-bone sm:right-7" title="Re-centre the map" aria-label="Re-centre the map">
              <LocateFixed size={16} />
            </button>
          )}

        </>
      )}

      {/* one quiet line about the swarm; the whole story is on the Swarm page */}
      {caption && (
        <p key={caption.seq} className="pointer-events-none absolute inset-x-0 bottom-4 mx-auto flex w-fit max-w-[min(620px,calc(100vw-40px))] animate-rise items-center gap-2 truncate rounded-full bg-ink-900/85 px-3.5 py-1 text-[12.5px] text-bone-dim shadow-[0_0_0_1px_var(--color-line)] backdrop-blur" aria-live="off">
          <span className="font-mono text-[11px]" style={{ color: agentColor(caption.agent) }}>{caption.agent}</span>
          <span className="truncate">{caption.title}</span>
          {caption.simulated && <SimulatedTag />}
        </p>
      )}

      {selected && <DetailCard node={selected} />}
    </div>
  );
}
