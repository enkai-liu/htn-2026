"use client";
// The landing page's only picture, and its background: a slowly turning archipelago in a sea that fills the
// window, drawn by the same scene as a real run. The islands sit right of centre, clear of the form.
import { useState, useSyncExternalStore } from "react";
import { emptyGraph } from "@/lib/graphReducer";
import { heroIslands } from "@/lib/heroIslands";
import { emptyLayout } from "@/lib/islandLayout";
import { IslandMap } from "./islands/IslandMap";

// the width at which the form stops filling the page and leaves the islands a column of their own
const WIDE = "(min-width: 1024px)";
const subscribe = (cb: () => void) => { const m = window.matchMedia(WIDE); m.addEventListener("change", cb); return () => m.removeEventListener("change", cb); };

export function HeroIslands({ className }: { className?: string }) {
  const [{ graph, layout }] = useState(() => heroIslands());
  const [seen] = useState(() => new Set<string>());
  // on a narrow screen the form covers the middle of the page, so there is only open water and the boats on it
  const wide = useSyncExternalStore(subscribe, () => window.matchMedia(WIDE).matches, () => true);
  return (
    <div className={className} aria-hidden>
      <IslandMap ambient anchorX={0.77} graph={wide ? graph : emptyGraph} layout={wide ? layout : emptyLayout} selectedId={null} onSelect={() => {}} seen={seen} />
    </div>
  );
}
