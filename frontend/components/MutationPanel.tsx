"use client";
// Coaching: facet swaps toward whitespace, each one re-scored against the corpus (not guessed),
// plus the two term lists that seed them: what is common globally but missing near you, and what is a cliché here.
import clsx from "clsx";
import { ArrowRight, Crosshair, LoaderCircle, RefreshCw } from "lucide-react";
import { fmtInt } from "@/lib/format";
import type { MutationState, RunState } from "@/lib/runReducer";
import type { TermStat } from "@/lib/types";
import { Chip, Empty } from "./ui";

function DeltaBadge({ m }: { m: MutationState }) {
  if (m.delta == null) {
    return (
      <span className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-mute">
        <LoaderCircle size={11} className="animate-spin" /> re-scoring against the dataset
      </span>
    );
  }
  const up = m.delta > 0;
  return (
    <span key={m.scoredSeq} className={clsx("flex animate-flip items-baseline gap-1 border px-2 py-0.5 font-mono", up ? "border-teal/60 bg-teal/[0.08] text-teal" : "border-line-strong text-bone-dim")} title="Change in the originality headline if you made this swap, measured by re-running retrieval">
      <span className="text-[17px] leading-none">{up ? "+" : ""}{m.delta}</span>
      <span className="text-[8.5px] uppercase tracking-[0.14em] opacity-80">originality</span>
    </span>
  );
}

function MutationCard({ m, base, selected, onFocus, onRescore, busy }: {
  m: MutationState; base: Record<string, number | null>; selected: boolean; onFocus: () => void; onRescore: () => void; busy: boolean;
}) {
  return (
    <article className={clsx("animate-rise border px-3 py-2.5 transition-colors", selected ? "border-teal shadow-[0_0_0_3px_color-mix(in_srgb,var(--color-teal)_14%,transparent)]" : "border-line")}>
      <div className="flex items-center gap-2">
        <Chip tone="teal">swap the {m.facet}</Chip>
        <span className="font-mono text-[10px] text-faint">{m.mid}</span>
        <span className="ml-auto"><DeltaBadge m={m} /></span>
      </div>

      <div className="mt-2 flex flex-col gap-0.5">
        <span className="text-[12px] leading-snug text-mute line-through decoration-faint">{m.frm}</span>
        <span className="flex items-start gap-1.5 font-display text-[18px] leading-[1.2] text-bone">
          <ArrowRight size={14} className="mt-[5px] flex-none text-teal" />
          {m.to}
        </span>
      </div>

      <p className="mt-1.5 text-[12px] leading-snug text-bone-dim">{m.rationale}</p>
      {m.pitch && <p className="mt-1.5 border-l-2 border-teal/50 pl-2 font-display text-[14.5px] italic leading-snug text-bone-dim">“{m.pitch}”</p>}

      <div className="mt-2 flex flex-wrap items-center gap-1">
        {m.grounded_in.length > 0 && <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-faint">grounded in</span>}
        {m.grounded_in.map((g) => <Chip key={g} tone="mute" title="A whitespace term: common across the dataset, absent from your neighbourhood">{g}</Chip>)}
        {m.axes && Object.entries(m.axes).map(([axis, to]) => (
          <Chip key={axis} tone="teal" title="Axis score after the swap">
            {axis.replace(/_/g, " ")} {base[axis] != null ? `${base[axis]} → ` : "→ "}{to}
          </Chip>
        ))}
      </div>

      <div className="mt-2 flex gap-1.5">
        <button type="button" className="btn btn-sm" onClick={onFocus}><Crosshair size={11} /> Show on chart</button>
        <button type="button" className="btn btn-sm btn-teal" onClick={onRescore} disabled={busy}>
          {busy ? <LoaderCircle size={11} className="animate-spin" /> : <RefreshCw size={11} />} Re-score
        </button>
      </div>
    </article>
  );
}

function TermList({ title, blurb, terms, kind }: { title: string; blurb: string; terms: TermStat[]; kind: "whitespace" | "cliche" }) {
  const max = Math.max(1, ...terms.map((t) => (kind === "cliche" ? t.score ?? 0 : t.global_count ?? 0)));
  return (
    <section>
      <h4 className={clsx("font-mono text-[10px] uppercase tracking-[0.18em]", kind === "whitespace" ? "text-teal" : "text-bone-dim")}>{title}</h4>
      <p className="mt-0.5 text-[11px] leading-snug text-mute">{blurb}</p>
      <ul className="mt-1.5 flex flex-col gap-1">
        {terms.map((t) => {
          const v = kind === "cliche" ? t.score ?? 0 : t.global_count ?? 0;
          return (
            <li key={t.term} className="text-[12px]">
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate text-bone">{t.term}</span>
                <span className="flex-none font-mono text-[9.5px] text-mute">
                  {kind === "cliche" ? `significance ${t.score?.toFixed(1) ?? "–"}` : `${fmtInt(t.global_count)} in the dataset · ${fmtInt(t.neighbourhood_count)} near you`}
                </span>
              </div>
              <div className="mt-[3px] h-[2px] bg-ink-700"><div className={clsx("h-full", kind === "whitespace" ? "bg-teal/80" : "bg-bone-dim/60")} style={{ width: `${(v / max) * 100}%` }} /></div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function MutationPanel({ state, selectedId, onFocus, onRescore, busyMid }: {
  state: RunState; selectedId: string | null; onFocus: (mid: string) => void; onRescore: (mid: string) => void; busyMid: string | null;
}) {
  const base: Record<string, number | null> = {
    crowding: state.scores?.crowding?.score ?? null,
    facet_rarity: state.scores?.facet_rarity?.score ?? null,
    llm_predictability: state.scores?.llm_predictability?.score ?? null,
  };
  const whitespace = state.report?.whitespace ?? [];
  const cliches = state.report?.cliches ?? [];

  if (!state.mutationOrder.length && !whitespace.length) return <Empty>The mutator waits for the scores, then looks for open sky.</Empty>;

  return (
    <div className="flex flex-col gap-2 p-3">
      {state.mutationOrder.map((mid) => (
        <MutationCard
          key={mid} m={state.mutations[mid]} base={base} selected={selectedId === `mut:${mid}`}
          onFocus={() => onFocus(mid)} onRescore={() => onRescore(mid)} busy={busyMid === mid}
        />
      ))}

      {(whitespace.length > 0 || cliches.length > 0) && (
        <div className="mt-1 grid animate-rise gap-4 border-t border-line pt-3 sm:grid-cols-2">
          {whitespace.length > 0 && <TermList kind="whitespace" title="Whitespace terms" blurb="Common across the dataset, (almost) absent among your neighbours." terms={whitespace} />}
          {cliches.length > 0 && <TermList kind="cliche" title="Cliché terms" blurb="Over-represented among your neighbours (Elasticsearch significant_text)." terms={cliches} />}
        </div>
      )}
    </div>
  );
}
