"use client";
// The map key. Each swatch is the island itself, mixed the same way `islandGeometry` mixes it — a washed-out source
// tint for the turf, the full-strength tint on the flag — so a colour can be read straight off the map.
import type { ReactNode } from "react";
import { sourceHex, sourceLabel } from "@/lib/format";

// kept in step with islandGeometry.ts: turf is `tint.lerp(PAPER, 0.68)` (0.45 for your idea), bare rock is fixed
const PAPER = "#ece9e2";
const IDEA_TINT = "#f4b942";
const MUTATION_TINT = "#0f9488";
const ROCK = "#d5d2ca";
const turf = (hex: string, strength = 32) => `color-mix(in srgb, ${hex} ${strength}%, ${PAPER})`;
const keel = (hex: string, strength = 32) => `color-mix(in srgb, ${turf(hex, strength)} 76%, #8f887c)`;

const GLYPH = "size-[18px] shrink-0";

/** The island: a hex slab seen from above, on its shadowed keel. */
function Island({ hex, strength, children }: { hex: string; strength?: number; children?: ReactNode }) {
  return (
    <svg viewBox="1 1 17 17" className={GLYPH} aria-hidden>
      <path d="M9.5 15.1 2.9 11.9 9.5 13.6 16.1 11.9Z" fill={keel(hex, strength)} />
      <path d="M9.5 8.4 16.1 11 9.5 13.6 2.9 11Z" fill={turf(hex, strength)} stroke={keel(hex, strength)} strokeWidth="0.5" />
      {children}
    </svg>
  );
}

/** Prior art: a hill with a flag flying the full-strength colour of where the project was found. */
function Flag({ hex }: { hex: string }) {
  return (
    <Island hex={hex}>
      <path d="M8.1 9.2V3.4" stroke="#5d564b" strokeWidth="1.1" strokeLinecap="round" />
      <path d="M8.7 3.5 13 5.1 8.7 6.7Z" fill={hex} />
    </Island>
  );
}

/** Your idea: a gold island with the lighthouse on it, lantern lit. */
function Lighthouse() {
  return (
    <Island hex={IDEA_TINT} strength={55}>
      <circle cx="9.5" cy="3.7" r="2.5" fill={IDEA_TINT} opacity="0.3" />
      <path d="M8 10.2 8.7 4.8h1.6l.7 5.4Z" fill="#faf6ec" stroke="#c9791f" strokeWidth="0.55" strokeLinejoin="round" />
      <path d="M8.35 7.4h2.3" stroke="#e9a23b" strokeWidth="1.1" />
      <circle cx="9.5" cy="3.8" r="1.1" fill="#ffd76a" stroke="#c9791f" strokeWidth="0.45" />
    </Island>
  );
}

/** An LLM prior: unclaimed bare rock, no flag on it. */
function Rock() {
  return (
    <Island hex={ROCK} strength={100}>
      <path d="M6.8 10.4 8.6 7.6l1.3 1.6 1.4-2.3 1.7 3.5Z" fill="#8f887c" opacity="0.8" />
    </Island>
  );
}

/** A mutation: a boat leaving your island — no land under it. */
function Boat() {
  return (
    <svg viewBox="1 1 17 17" className={GLYPH} aria-hidden>
      <path d="M9.8 3.4v7.2" stroke="#5d564b" strokeWidth="1.1" strokeLinecap="round" />
      <path d="M9.1 4 5 10.6h4.1Z" fill={MUTATION_TINT} />
      <path d="M3.4 11.6h12.2l-2 3H5.4Z" fill="#b98f63" />
    </svg>
  );
}

/** An unresolved "is this the same project?" link. */
function SameAs() {
  return (
    <svg viewBox="1 1 17 17" className={GLYPH} aria-hidden>
      <path d="M2 9.5h15" stroke="var(--color-amber)" strokeWidth="1.6" strokeLinecap="round" strokeDasharray="3 2.6" />
    </svg>
  );
}

function Row({ glyph, label, note, count }: { glyph: ReactNode; label: string; note?: string; count?: number }) {
  return (
    <li className="flex items-center gap-2" title={note}>
      {glyph}
      <span className="text-bone">{label}</span>
      {count !== undefined && <span className="ml-auto pl-2.5 font-mono text-[10.5px] tabular-nums text-faint">{count}</span>}
    </li>
  );
}

export interface MapLegendProps {
  sources: { source: string; count: number }[];
  priors: number;
  mutations: number;
  sameAs: boolean;
}

export function MapLegend({ sources, priors, mutations, sameAs }: MapLegendProps) {
  return (
    <div className="pointer-events-auto w-fit cursor-default select-none rounded-[12px] border border-line bg-ink-900/85 px-3 py-2 shadow-[0_6px_22px_rgb(20_22_28/0.08)] backdrop-blur-sm">
      <ul className="flex flex-col gap-1 text-[12.5px] leading-tight">
        <Row glyph={<Lighthouse />} label="Your idea" note="The lighthouse at the centre of the map" />
        {sources.length > 0 && <li className="my-[3px] h-px bg-line" />}
        {sources.map(({ source, count }) => (
          <Row key={source} glyph={<Flag hex={sourceHex(source)} />} label={sourceLabel(source)} count={count} note={`${sourceLabel(source)}: the island's turf and its flag both fly this colour`} />
        ))}
        {(priors > 0 || mutations > 0 || sameAs) && <li className="my-[3px] h-px bg-line" />}
        {priors > 0 && <Row glyph={<Rock />} label="LLM prior" count={priors} note="Bare rock, unclaimed: what model families propose when given only the problem and the audience" />}
        {mutations > 0 && <Row glyph={<Boat />} label="Mutation" count={mutations} note="A boat leaving your island: a facet swapped out and re-scored" />}
        {sameAs && <Row glyph={<SameAs />} label="Same project?" note="A dashed link the swarm left open: these two may be one project" />}
      </ul>
    </div>
  );
}
