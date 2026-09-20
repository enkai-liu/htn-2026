"use client";
// The home tab: the map and almost nothing else. One line says what the swarm is doing; the rest is on other pages.
import { LocateFixed, Play, Square } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { agentColor } from "@/lib/agents";
import { IdeaGraph } from "../IdeaGraph";
import { IslandMap } from "../islands/IslandMap";
import { SimulatedTag } from "../ui";
import { DetailCard } from "./DetailCard";
import { MapLegend } from "./MapLegend";
import { useRun } from "./RunProvider";

/** Demo mode: how many islands the tour visits, and how long it lingers on each. */
const TOUR_STOPS = 3;
const TOUR_MS = 5000;

export function MapScreen() {
  const { run, streaming, selectedId, select, seenIslands, cameraMemo, mapMode } = useRun();
  const { state, layout } = run;
  const { graph } = state;
  const [recenterTick, setRecenterTick] = useState(0);
  const [touring, setTouring] = useState(false);
  const [at, setAt] = useState(0);

  // The nearest neighbours, as the map draws them: only islands that have actually been placed, best match first.
  const tour = useMemo(() => {
    const ranked = layout.order
      .map((id) => graph.nodes[id])
      .filter((n) => n && n.kind === "entity" && n.similarity != null)
      .sort((a, b) => (b.similarity ?? 0) - (a.similarity ?? 0));
    return ranked.slice(0, TOUR_STOPS).map((n) => n.id);
  }, [graph, layout]);

  // read at each step rather than closed over, so islands arriving mid-run join the tour without restarting it
  const tourRef = useRef(tour);
  useEffect(() => { tourRef.current = tour; }, [tour]);
  /** the island the tour last asked for: anything else in `selectedId` is the author taking the wheel */
  const drivingTo = useRef<string | null>(null);

  useEffect(() => {
    if (!touring) return;
    let i = 0;
    const go = () => {
      const stops = tourRef.current;
      if (stops.length === 0) return; // nothing placed yet: wait for the next beat
      const n = i++ % stops.length;
      setAt(n);
      drivingTo.current = stops[n];
      select(stops[n]);
    };
    go();
    const t = setInterval(go, TOUR_MS);
    return () => clearInterval(t);
  }, [touring, select]);

  // Touching the map yourself ends the tour, wherever the camera happens to be. It is the *change* that ends it,
  // not the mismatch: on the beat the tour asks for an island, `selectedId` is still the one before it.
  const lastSeen = useRef<string | null>(null);
  useEffect(() => {
    const changed = selectedId !== lastSeen.current;
    lastSeen.current = selectedId;
    if (touring && changed && selectedId !== drivingTo.current) setTouring(false);
  }, [touring, selectedId]);

  const toggleTour = () => {
    if (!touring) { setTouring(true); return; }
    setTouring(false);
    drivingTo.current = null;
    select(null); // back out to the whole archipelago
  };

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
      <h1 className="sr-only">Map of the idea-space</h1>
      {/* fixed, not absolute: the sea fills the window and runs under the header and the tab bar, which sit over it */}
      {mapMode === "2d" ? flat : (
        <IslandMap
          graph={graph} layout={layout} selectedId={selectedId} onSelect={select} frameClassName="fixed inset-0 bg-sea"
          seen={seenIslands.current} cameraMemo={cameraMemo} recenterTick={recenterTick} fallback={flat} pending={empty}
        />
      )}

      {mapMode === "3d" && (
        <>
          {!empty && (
            <div className="absolute bottom-14 left-5 sm:left-7">
              <MapLegend
                sources={stats.sources} priors={stats.counts.prior} mutations={stats.counts.mutation}
                sameAs={graph.links.some((l) => l.kind === "possible_same_as")}
              />
            </div>
          )}

          {tour.length > 0 && (
            <button
              type="button" onClick={toggleTour} aria-pressed={touring}
              className="absolute left-5 top-1 flex h-9 items-center gap-2 rounded-full border border-line bg-ink-900 px-3.5 text-[12.5px] text-bone-dim transition-colors hover:text-bone sm:left-7"
              title={touring ? "Stop the tour" : `Fly the ${tour.length} nearest islands, five seconds each`}
            >
              {touring ? <Square size={11} className="fill-current" /> : <Play size={11} className="fill-current" />}
              <span>{touring ? "Stop tour" : `Tour the top ${tour.length}`}</span>
              {touring && (
                <span className="flex items-center gap-1" aria-hidden>
                  {tour.map((id, i) => <span key={id} className={`size-[5px] rounded-full ${i === at ? "bg-amber" : "bg-line"}`} />)}
                </span>
              )}
            </button>
          )}

          {!empty && !selected && (
            <button type="button" onClick={() => setRecenterTick((n) => n + 1)} className="absolute right-5 top-1 flex size-9 items-center justify-center rounded-full border border-line bg-ink-900 text-bone-dim transition-colors hover:text-bone sm:right-7" title="Re-centre the map" aria-label="Re-centre the map">
              <LocateFixed size={16} />
            </button>
          )}

        </>
      )}

      {/* one quiet line about the swarm: the latest thing an agent did */}
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
