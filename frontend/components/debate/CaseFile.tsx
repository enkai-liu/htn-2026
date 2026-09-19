"use client";
// One prior-art project on trial: the critic's claim against the advocate's answer, the jury's bench, then the
// verifier, whose ruling decides whether any of it reaches the report.
import clsx from "clsx";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { agentColor } from "@/lib/agents";
import type { DebateCase, Outcome, Stance } from "@/lib/debate";
import { safeHref, shortModel } from "@/lib/format";
import type { ClaimState } from "@/lib/runReducer";
import type { Evidence, ThreadEntry } from "@/lib/types";
import { KIND_LABEL, VerifyChip } from "../DebateThread";
import { Chip, SimulatedTag, SourceMark, type ChipTone } from "../ui";
import { JuryBench } from "./JuryBench";

const STANCE: Record<Stance, { label: string; tone: ChipTone }> = {
  open: { label: "unanswered", tone: "mute" },
  contested: { label: "contested", tone: "amber" },
  conceded: { label: "conceded", tone: "bone" },
};

const OUTCOME: Record<Outcome, { label: string; tone: ChipTone; line: string }> = {
  pending: { label: "awaiting verifier", tone: "mute", line: "The verifier has not ruled yet: nothing here reaches the report until it does." },
  verified: { label: "verified", tone: "teal", line: "Receipts check out: this reaches the report." },
  rejected: { label: "struck", tone: "red", line: "Vetoed by the verifier: this never reaches the report." },
  lead: { label: "unverified lead", tone: "amber", line: "Could not be verified: reported as a lead, not a finding." },
};

const VERB = { CONCEDE: "concedes", REBUTTAL: "rebuts", CHALLENGE: "challenges the evidence" } as const;

/** Consecutive replies by the same speaker making the same move read as one turn (the advocate often rebuts on several facets). */
function turns(thread: ThreadEntry[]): { frm: string; type: ThreadEntry["type"]; texts: string[] }[] {
  const out: { frm: string; type: ThreadEntry["type"]; texts: string[] }[] = [];
  for (const e of thread) {
    const last = out[out.length - 1];
    if (last && last.frm === e.frm && last.type === e.type) last.texts.push(e.text);
    else out.push({ frm: e.frm, type: e.type, texts: [e.text] });
  }
  return out;
}

const roleLabel = "font-mono text-[9.5px] uppercase tracking-[0.16em]";

function Exchange({ claim, evidence, models }: { claim: ClaimState; evidence: Evidence[]; models: Record<string, string | undefined> }) {
  const rejected = claim.status === "rejected";
  return (
    <div className="grid gap-x-5 gap-y-3 sm:grid-cols-2">
      <div className="border-l-2 pl-3" style={{ borderColor: agentColor(claim.by) }}>
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className={roleLabel} style={{ color: agentColor(claim.by) }}>{claim.by}</span>
          <span className="font-mono text-[9.5px] text-faint">{[shortModel(models[claim.by]), KIND_LABEL[claim.kind] ?? claim.kind].filter(Boolean).join(" · ")}</span>
        </div>
        <p className={clsx("mt-1 font-display text-[17px] leading-[1.25]", rejected ? "text-mute line-through decoration-vermilion/80" : "text-bone")}>{claim.text}</p>
        {evidence.map((e) => {
          const href = safeHref(e.url);
          return (
            <blockquote key={e.evid} className="mt-1.5 text-[12px] italic leading-snug text-bone-dim">
              “{e.quote}”
              {href && <a href={href} target="_blank" rel="noopener noreferrer" className="ml-1.5 font-mono text-[9.5px] not-italic text-amber hover:underline">source ↗</a>}
            </blockquote>
          );
        })}
      </div>

      <div className="border-l-2 pl-3" style={{ borderColor: claim.thread.length ? agentColor(claim.thread[0].frm) : "var(--color-line-strong)" }}>
        {claim.thread.length === 0 && (
          <p className="text-[12.5px] italic leading-snug text-faint">{claim.simulated ? "Injected after the debate to test the verifier: nobody argued this one." : "The advocate has not answered yet."}</p>
        )}
        {turns(claim.thread).map((turn, i) => (
          <div key={i} className={clsx("animate-rise", i > 0 && "mt-2")}>
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className={roleLabel} style={{ color: agentColor(turn.frm) }}>{turn.frm}</span>
              <span className="font-mono text-[9.5px] text-faint">{[shortModel(models[turn.frm]), VERB[turn.type]].filter(Boolean).join(" · ")}</span>
            </div>
            {turn.texts.map((text, j) => <p key={j} className="mt-1 text-[13px] leading-snug text-bone-dim">{text}</p>)}
          </div>
        ))}
      </div>
    </div>
  );
}

/** The last word: both receipt checks and the ruling they led to. */
function Ruling({ claim, showCid }: { claim: ClaimState; showCid: boolean }) {
  const rejected = claim.status === "rejected";
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className={clsx(roleLabel, "mr-1")} style={{ color: agentColor("verifier") }}>Verifier</span>
      {showCid && <span className="mr-0.5 font-mono text-[10px] text-mute">{claim.cid}</span>}
      <VerifyChip layer="quote" badge={claim.verification.quote} />
      <VerifyChip layer="gptzero" badge={claim.verification.gptzero} />
      {claim.reason && <span className={clsx("ml-1 text-[11.5px] leading-snug", rejected ? "text-vermilion" : "text-mute")}>{rejected ? "Struck: " : "Ruling: "}{claim.reason}</span>}
    </div>
  );
}

export function CaseFile({ c, evidence, models, fresh }: {
  c: DebateCase;
  evidence: Record<string, Evidence>;
  models: Record<string, string | undefined>;
  /** the case the swarm touched last while the run is streaming: held open so the action is never hidden */
  fresh: boolean;
}) {
  const [override, setOverride] = useState<boolean | null>(null);
  const quiet = c.stance === "conceded" && c.bench.length === 0;
  const open = override ?? (fresh || !quiet);
  const stance = STANCE[c.stance];
  const outcome = OUTCOME[c.outcome];
  const rejected = c.outcome === "rejected";
  return (
    <article className={clsx("animate-rise overflow-hidden rounded-2xl border bg-ink-900", c.simulated ? "border-dashed border-amber/60" : rejected ? "border-vermilion/40" : "border-line")}>
      <button type="button" onClick={() => setOverride(!open)} aria-expanded={open} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-left hover:bg-ink-850">
        <h2 className={clsx("min-w-0 truncate font-display text-[21px] leading-tight", rejected ? "text-mute" : "text-bone")}>{c.name}</h2>
        <span className="flex items-center gap-2.5">{c.sources.map((s) => <SourceMark key={s} source={s} />)}</span>
        <span className="ml-auto flex items-center gap-1.5">
          {!c.simulated && c.claims.length > 0 && <Chip key={c.stance} tone={stance.tone} flip>{stance.label}</Chip>}
          <Chip key={c.outcome} tone={outcome.tone} flip>{outcome.label}</Chip>
          <ChevronDown size={15} className={clsx("text-mute transition-transform duration-300", open && "rotate-180")} />
        </span>
      </button>

      {open && (
        <div className="flex flex-col gap-4 border-t border-line px-4 pb-4 pt-3.5">
          {c.simulated && <SimulatedTag className="self-start" />}
          {c.claims.map((claim) => <Exchange key={claim.cid} claim={claim} models={models} evidence={claim.evidence.map((id) => evidence[id]).filter(Boolean)} />)}
          {c.bench.length > 0 && <div className="border-t border-line pt-3"><JuryBench bench={c.bench} /></div>}
          {c.claims.length > 0 && (
            <div className="flex flex-col gap-1.5 border-t border-line pt-3">
              {c.claims.map((claim) => <Ruling key={claim.cid} claim={claim} showCid={c.claims.length > 1} />)}
            </div>
          )}
          {c.claims.length > 0 && <p className={clsx("-mt-2 text-[12px]", rejected ? "text-vermilion" : c.outcome === "verified" ? "text-teal" : "text-mute")}>{outcome.line}</p>}
        </div>
      )}
    </article>
  );
}
