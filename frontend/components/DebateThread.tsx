"use client";
// The argument, in the order it happened: claims (updated in place as they are challenged, resolved and
// verified), jury votes as dot plots so a split is visible at a glance, and the re-queries a split provokes.
import clsx from "clsx";
import { ArrowRight, Check, RotateCcw, Split, X } from "lucide-react";
import { memo } from "react";
import { agentColor } from "@/lib/agents";
import { fmtT, safeHref, shortModel } from "@/lib/format";
import { JURY_SPLIT_STD, type ClaimState, type JuryVote, type Requery, type RunState, type VerifyBadge } from "@/lib/runReducer";
import type { ClaimStatus, Evidence } from "@/lib/types";
import { Chip, Empty, SimulatedTag } from "./ui";

const STATUS: Record<ClaimStatus, { label: string; tone: "amber" | "teal" | "red" | "mute" | "bone" }> = {
  proposed: { label: "proposed", tone: "mute" },
  challenged: { label: "challenged", tone: "amber" },
  conceded: { label: "conceded", tone: "bone" },
  verified: { label: "verified", tone: "teal" },
  unverified_lead: { label: "unverified lead", tone: "amber" },
  rejected: { label: "rejected", tone: "red" },
};

const KIND_LABEL: Record<string, string> = { exists: "it exists", differs: "it differs", trend: "trend", gap: "gap" };

function VerifyChip({ layer, badge }: { layer: "quote" | "gptzero"; badge?: VerifyBadge }) {
  const name = layer === "quote" ? "quote" : "GPTZero";
  if (!badge) return <Chip tone="mute" title={layer === "quote" ? "Does the quoted text appear verbatim in the fetched page?" : "GPTZero bibliography scan: does the cited source exist?"}>{name} · pending</Chip>;
  const tone = badge.ok === true ? "teal" : badge.ok === false ? "red" : "amber";
  return (
    // keyed by seq so the chip remounts, and the flip replays, every time the verifier reports
    <Chip key={badge.seq} tone={tone} title={badge.detail} flip>
      {badge.ok === true ? <Check size={10} /> : badge.ok === false ? <X size={10} /> : null}
      {name}{badge.ok == null ? " ?" : ""} <span className="opacity-70">{badge.status.replace(/_/g, " ")}</span>
    </Chip>
  );
}

const ClaimCard = memo(function ClaimCard({ claim, evidence }: { claim: ClaimState; evidence: Evidence[] }) {
  const status = STATUS[claim.status] ?? STATUS.proposed;
  const rejected = claim.status === "rejected";
  return (
    <article className={clsx("animate-rise border px-3 py-2.5", claim.simulated ? "border-dashed border-amber/60" : rejected ? "border-vermilion/50" : "border-line", rejected && "bg-vermilion/[0.04]")}>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-[10px] text-mute">{claim.cid}</span>
        <Chip tone="mute">{KIND_LABEL[claim.kind] ?? claim.kind}</Chip>
        <span className="font-mono text-[10px]" style={{ color: agentColor(claim.by) }}>{claim.by}</span>
        <Chip key={claim.status} tone={status.tone} className="ml-auto" flip>{status.label}</Chip>
      </div>
      {claim.simulated && <SimulatedTag className="mt-1.5" />}

      <p className={clsx("mt-1.5 font-display text-[17px] leading-[1.25]", rejected ? "text-mute line-through decoration-vermilion/80" : "text-bone")}>{claim.text}</p>

      {evidence.map((e) => {
        const href = safeHref(e.url);
        return (
          <blockquote key={e.evid} className="mt-1.5 border-l-2 border-line-strong pl-2 text-[11.5px] leading-snug text-bone-dim">
            “{e.quote}”
            {href && <a href={href} target="_blank" rel="noopener noreferrer" className="ml-1.5 font-mono text-[9.5px] text-amber hover:underline">source ↗</a>}
          </blockquote>
        );
      })}

      {claim.thread.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1.5">
          {claim.thread.map((entry, i) => (
            <li key={i} className="animate-rise border-l-2 pl-2" style={{ borderColor: agentColor(entry.frm) }}>
              <div className="flex items-center gap-1.5 font-mono text-[9.5px] uppercase tracking-[0.12em]">
                <span style={{ color: agentColor(entry.frm) }}>{entry.frm}</span>
                <span className={entry.type === "CONCEDE" ? "text-bone-dim" : "text-amber"}>{entry.type === "CONCEDE" ? "concedes" : entry.type === "REBUTTAL" ? "rebuts" : "challenges"}</span>
              </div>
              <p className="mt-0.5 text-[12px] leading-snug text-bone-dim">{entry.text}</p>
            </li>
          ))}
        </ul>
      )}

      {(claim.kind === "exists" || claim.verification.quote || claim.verification.gptzero) && (
        <div className="mt-2 flex flex-wrap items-center gap-1">
          <span className="mr-0.5 font-mono text-[9px] uppercase tracking-[0.14em] text-faint">verifier</span>
          <VerifyChip layer="quote" badge={claim.verification.quote} />
          <VerifyChip layer="gptzero" badge={claim.verification.gptzero} />
        </div>
      )}
      {claim.reason && <p className={clsx("mt-1.5 text-[11px] leading-snug", rejected ? "text-vermilion" : "text-mute")}>{rejected ? "Struck: " : "Ruling: "}{claim.reason}</p>}
    </article>
  );
});

function JuryStrip({ vote }: { vote: JuryVote }) {
  return (
    <div className={clsx("animate-rise border px-3 py-2", vote.split ? "border-amber/70 bg-amber/[0.05]" : "border-line")}>
      <div className="flex items-center gap-2">
        <span className="font-mono text-[9px] uppercase tracking-[0.18em]" style={{ color: agentColor("judge") }}>jury{vote.revote ? " · re-vote" : ""}</span>
        <span className="min-w-0 truncate text-[12px] text-bone">{vote.subject}</span>
        <span className="ml-auto flex-none font-mono text-[10px] text-bone-dim">μ {vote.mean.toFixed(2)}</span>
        <span className={clsx("flex-none font-mono text-[10px]", vote.split ? "text-amber" : "text-teal")} title={`A spread of σ ≥ ${JURY_SPLIT_STD} counts as a split`}>σ {vote.std.toFixed(2)}</span>
      </div>

      {/* dot plot: one dot per juror on a 0..1 overlap scale */}
      <div className="relative mt-2.5 h-[18px]">
        <div className="ticks absolute inset-x-0 top-[8px] h-[3px] border-x border-line-strong bg-ink-700" />
        <div className="absolute top-[5px] h-[9px] border-x border-bone-dim/60 bg-bone-dim/10" style={{ left: `${Math.max(0, vote.mean - vote.std) * 100}%`, width: `${Math.min(1, vote.std * 2) * 100}%` }} />
        {vote.votes.map((v, i) => (
          <span
            key={i}
            className="absolute top-[3px] size-[13px] -translate-x-1/2 rounded-full border-2 border-ink-900"
            style={{ left: `${Math.max(0, Math.min(1, v.score)) * 100}%`, background: ["#78b4ff", "#ff9466", "#c4bdf0", "#9ad17f", "#e87fa6"][i % 5] }}
            title={`${v.model}: ${v.score.toFixed(2)}: ${v.why}`}
          />
        ))}
      </div>
      <div className="flex justify-between font-mono text-[8px] uppercase tracking-[0.1em] text-faint"><span>0 · different</span><span>same · 1</span></div>

      <ul className="mt-1.5 flex flex-col gap-0.5">
        {vote.votes.map((v, i) => (
          <li key={i} className="flex items-baseline gap-1.5 text-[11px] leading-snug">
            <span className="size-[6px] flex-none translate-y-[-1px] rounded-full" style={{ background: ["#78b4ff", "#ff9466", "#c4bdf0", "#9ad17f", "#e87fa6"][i % 5] }} />
            <span className="w-[116px] flex-none truncate font-mono text-[9.5px] text-mute" title={v.model}>{shortModel(v.model)}</span>
            <span className="w-[28px] flex-none font-mono text-[10px] text-bone">{v.score.toFixed(2)}</span>
            <span className="min-w-0 truncate text-bone-dim" title={v.why}>{v.why}</span>
          </li>
        ))}
      </ul>

      {vote.split && (
        <div className="mt-2 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-amber">
          <Split size={12} /> Jury split: the judge does not average it away, it sends a scout back out
        </div>
      )}
    </div>
  );
}

function RequeryCard({ rq }: { rq: Requery }) {
  return (
    // two animations cannot share one element (both set `animation`), so rise wraps flash
    <div className="animate-rise">
    <div className="animate-flash border-y border-l-2 border-r border-amber/70 bg-amber/[0.06] px-3 py-2" style={{ ["--flash" as string]: "var(--color-amber)" }}>
      <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-amber">
        {rq.fromJurySplit ? <Split size={12} /> : <RotateCcw size={12} />}
        {rq.fromJurySplit ? "Jury split → targeted re-query" : "Scout sent back out"}
        <span className="ml-auto text-[9px] text-faint">{fmtT(rq.t)}</span>
      </div>
      <div className="mt-1 flex items-center gap-1.5 font-mono text-[11px]">
        <span style={{ color: agentColor(rq.from) }}>{rq.from}</span>
        <ArrowRight size={11} className="text-amber" />
        <span style={{ color: agentColor(rq.to) }}>{rq.to}</span>
        {rq.facet && <Chip tone="amber" className="ml-1">facet: {rq.facet}</Chip>}
      </div>
      <p className="mt-1 font-display text-[15.5px] italic leading-snug text-bone">{rq.reason}</p>
      {rq.query && <p className="mt-0.5 font-mono text-[10.5px] text-bone-dim">query: “{rq.query}”</p>}
    </div>
    </div>
  );
}

export function DebateThread({ state }: { state: RunState }) {
  if (!state.debateFeed.length) return <Empty>The critic has not made its case yet.</Empty>;
  const counts = state.claimOrder.reduce<Record<string, number>>((acc, cid) => { const s = state.claims[cid].status; acc[s] = (acc[s] ?? 0) + 1; return acc; }, {});
  return (
    <div className="flex flex-col gap-2 p-3">
      <div className="flex flex-wrap items-center gap-1">
        {(Object.keys(STATUS) as ClaimStatus[]).filter((s) => counts[s]).map((s) => <Chip key={s} tone={STATUS[s].tone}>{counts[s]} {STATUS[s].label}</Chip>)}
        <span className="ml-auto font-mono text-[9.5px] text-faint">only verified claims reach the report</span>
      </div>
      {state.debateFeed.map((item, i) => {
        if (item.kind === "claim") {
          const claim = state.claims[item.cid];
          if (!claim) return null;
          const evidence = claim.evidence.map((id) => state.evidence[id]).filter(Boolean);
          return <ClaimCard key={`c:${item.cid}`} claim={claim} evidence={evidence} />;
        }
        if (item.kind === "jury") return <JuryStrip key={`j:${i}`} vote={state.juryVotes[item.index]} />;
        return <RequeryCard key={`q:${i}`} rq={state.requeries[item.index]} />;
      })}
    </div>
  );
}
