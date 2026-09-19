"use client";
// The jury's bench for one project: a dot plot per facet, and when the jurors split, the scout that was sent after
// exactly that facet and the re-vote that followed, in place.
import clsx from "clsx";
import { Split } from "lucide-react";
import { useState } from "react";
import { agentColor } from "@/lib/agents";
import type { FacetBench } from "@/lib/debate";
import { shortModel } from "@/lib/format";
import { JURY_SPLIT_STD, type JuryVote } from "@/lib/runReducer";
import { JUROR_COLORS } from "../DebateThread";

const ROW = "grid grid-cols-[76px_minmax(0,1fr)_88px] items-center gap-x-3";

function VoteRow({ label, vote }: { label: string; vote: JuryVote }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="animate-rise">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className={clsx(ROW, "w-full rounded-md py-1 text-left hover:bg-ink-850")} title="Show each juror's reasoning">
        <span className={clsx("truncate text-[12.5px]", vote.revote ? "text-mute" : "text-bone")}>{label}</span>
        {/* one dot per juror on a 0..1 overlap scale, over the ±σ band */}
        <span className="relative block h-[18px]">
          <span className="ticks absolute inset-x-0 top-[8px] h-[3px] border-x border-line-strong bg-ink-700" />
          <span className="absolute top-[5px] h-[9px] border-x border-bone-dim/60 bg-bone-dim/10" style={{ left: `${Math.max(0, vote.mean - vote.std) * 100}%`, width: `${Math.min(1, vote.std * 2) * 100}%` }} />
          {vote.votes.map((v, i) => (
            <span
              key={i}
              className="absolute top-[3px] size-[13px] -translate-x-1/2 animate-rise rounded-full border-2 border-ink-900"
              style={{ left: `${Math.max(0, Math.min(1, v.score)) * 100}%`, background: JUROR_COLORS[i % JUROR_COLORS.length], animationDelay: `${i * 140}ms` }}
            />
          ))}
        </span>
        <span className="flex justify-end gap-2 font-mono text-[10px]">
          <span className="text-bone-dim">μ {vote.mean.toFixed(2)}</span>
          <span className={vote.split ? "text-amber" : "text-teal"} title={`A spread of σ ≥ ${JURY_SPLIT_STD} counts as a split`}>σ {vote.std.toFixed(2)}</span>
        </span>
      </button>
      {open && (
        <ul className={clsx(ROW, "mb-1")}>
          {vote.votes.map((v, i) => (
            <li key={i} className="col-span-2 col-start-2 flex items-baseline gap-1.5 text-[11.5px] leading-snug">
              <span className="size-[6px] flex-none -translate-y-px rounded-full" style={{ background: JUROR_COLORS[i % JUROR_COLORS.length] }} />
              <span className="w-[112px] flex-none truncate font-mono text-[9.5px] text-mute" title={v.model}>{shortModel(v.model)}</span>
              <span className="w-[28px] flex-none font-mono text-[10px] text-bone">{v.score.toFixed(2)}</span>
              <span className="min-w-0 text-bone-dim">{v.why}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function JuryBench({ bench }: { bench: FacetBench[] }) {
  const n = bench[0]?.votes[0]?.votes.length ?? 0;
  return (
    <div>
      <div className="mb-1 flex items-baseline gap-2">
        <span className="font-mono text-[9.5px] uppercase tracking-[0.16em]" style={{ color: agentColor("judge") }}>Jury</span>
        <span className="text-[11.5px] text-mute">{n} jurors from different model families, blind to the debate and to each other</span>
        <span className="ml-auto hidden font-mono text-[8.5px] uppercase tracking-[0.1em] text-faint sm:inline">0 different · same 1</span>
      </div>
      {bench.map((b) => (
        <div key={b.facet}>
          {b.votes.map((v, i) => (
            <div key={v.seq}>
              {/* the tie-break sits between the split and the re-vote it caused */}
              {i === 1 && b.tieBreak && <TieBreakRow bench={b} />}
              <VoteRow label={v.revote ? "re-vote" : b.facet} vote={v} />
            </div>
          ))}
          {b.votes.length === 1 && b.tieBreak && <TieBreakRow bench={b} />}
        </div>
      ))}
    </div>
  );
}

function TieBreakRow({ bench }: { bench: FacetBench }) {
  const rq = bench.tieBreak!;
  return (
    <div className={clsx(ROW, "animate-rise py-1")}>
      <div className="col-span-2 col-start-2 animate-flash border-l-2 border-amber/70 py-0.5 pl-2.5" style={{ ["--flash" as string]: "var(--color-amber)" }}>
        <div className="flex flex-wrap items-center gap-x-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-amber">
          <Split size={11} /> split, not averaged:
          <span style={{ color: agentColor(rq.from) }}>{rq.from}</span> sends <span style={{ color: agentColor(rq.to) }}>{rq.to}</span> back out
        </div>
        {rq.query && <p className="mt-0.5 text-[12px] leading-snug text-bone-dim">“{rq.query}”</p>}
        {rq.result && <p className="mt-0.5 text-[11.5px] leading-snug text-mute">↳ {rq.result}</p>}
      </div>
    </div>
  );
}
