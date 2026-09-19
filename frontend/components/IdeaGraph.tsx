"use client";
// Wrapper around the canvas chart: client-only import (react-force-graph touches `window` at module load),
// plus the legend and the counts that sit on top of it.
import dynamic from "next/dynamic";
import { useMemo } from "react";
import { sourceColor, sourceLabel } from "@/lib/format";
import type { IdeaGraphCanvasProps } from "./IdeaGraphCanvas";

const Canvas = dynamic(() => import("./IdeaGraphCanvas"), {
  ssr: false,
  loading: () => <div className="absolute inset-0 flex items-center justify-center font-mono text-[10.5px] uppercase tracking-[0.2em] text-faint">Unrolling the chart…</div>,
});

export function IdeaGraph(props: IdeaGraphCanvasProps) {
  const { graph } = props;
  const stats = useMemo(() => {
    const counts = { entity: 0, prior: 0, mutation: 0 };
    const sources = new Set<string>();
    for (const id of graph.order) {
      const n = graph.nodes[id];
      if (n.kind === "entity") { counts.entity++; if (n.source) sources.add(n.source); }
      else if (n.kind === "prior") counts.prior++;
      else if (n.kind === "mutation") counts.mutation++;
    }
    return { counts, sources: [...sources] };
  }, [graph]);

  const empty = graph.order.length === 0;

  return (
    <div
      className="relative h-full min-h-[240px] w-full overflow-hidden"
      role="img"
      aria-label={empty ? "Chart of the idea-space: empty so far" : `Chart of the idea-space: your idea at the centre, ${stats.counts.entity} prior-art entities placed by similarity, ${stats.counts.prior} LLM-prior samples, ${stats.counts.mutation} mutations. The same information is listed in the Evidence and Coach panels.`}
    >
      <Canvas {...props} />

      {empty && (
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-1 text-center">
          <span className="font-display text-[26px] italic text-bone-dim">An empty sky, for now.</span>
          <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-faint">Waiting for the conductor to place your idea</span>
        </div>
      )}

      <div className="pointer-events-none absolute left-3 top-2.5 font-mono text-[9.5px] uppercase tracking-[0.14em] text-mute">distance = 1 − similarity</div>
      {!empty && (
        <ul className="pointer-events-none absolute right-3 top-2.5 flex flex-col items-end gap-0.5 font-mono text-[9.5px] tracking-[0.06em] text-faint">
          <li>{stats.counts.entity} prior-art {stats.counts.entity === 1 ? "entity" : "entities"}</li>
          {stats.counts.prior > 0 && <li>{stats.counts.prior} LLM-prior samples</li>}
          {stats.counts.mutation > 0 && <li className="text-teal/80">{stats.counts.mutation} mutations</li>}
        </ul>
      )}

      {/* vertical legend in the left margin: the chart is a circle in a wide plate, so the corners are free */}
      <ul className="pointer-events-none absolute bottom-2.5 left-3 flex flex-col gap-1 font-mono text-[9.5px] tracking-[0.04em] text-mute">
        <li className="flex items-center gap-1.5"><span className="w-[9px] text-center text-[11px] leading-none text-amber">✦</span>your idea</li>
        {stats.sources.map((s) => (
          <li key={s} className="flex items-center gap-1.5">
            <span className="mx-[1px] size-[7px] rounded-full" style={{ background: sourceColor(s) }} />
            {sourceLabel(s)}
          </li>
        ))}
        {stats.counts.prior > 0 && (
          <li className="flex items-center gap-1.5" title="What model families propose when given only the problem and the audience"><span className="size-[9px] rounded-full bg-cloud/60 blur-[1.5px]" />LLM prior</li>
        )}
        {stats.counts.mutation > 0 && (
          <li className="flex items-center gap-1.5 text-teal"><span className="w-[9px] text-center text-[9px] leading-none">▲</span>mutation</li>
        )}
        {graph.links.some((l) => l.kind === "possible_same_as") && (
          <li className="flex items-center gap-1.5 text-amber"><span className="w-[9px] border-t border-dotted border-amber" />same? left open</li>
        )}
      </ul>
    </div>
  );
}
