"use client";
// The landing page's only picture: a slowly turning archipelago, drawn by the same scene as a real run.
import { useState } from "react";
import { heroIslands } from "@/lib/heroIslands";
import { IslandMap } from "./islands/IslandMap";

export function HeroIslands({ className }: { className?: string }) {
  const [{ graph, layout }] = useState(() => heroIslands());
  const [seen] = useState(() => new Set<string>());
  return (
    <div className={className} aria-hidden>
      <IslandMap ambient graph={graph} layout={layout} selectedId={null} onSelect={() => {}} seen={seen} />
    </div>
  );
}
