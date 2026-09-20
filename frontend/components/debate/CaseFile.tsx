"use client";
// One prior-art project on trial: the critic's claim against the advocate's answer, the jury's bench, then the
// verifier, whose ruling decides whether any of it reaches the report.
import clsx from "clsx";
import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";
import { agentColor } from "@/lib/agents";
import type { DebateCase, Outcome, Stance } from "@/lib/debate";
import { safeHref, shortModel } from "@/lib/format";
import type { ClaimState } from "@/lib/runReducer";
import type { Evidence, ThreadEntry } from "@/lib/types";
import { KIND_LABEL, VerifyChip } from "../DebateThread";
import { Chip, SimulatedTag, SourceMark, type ChipTone } from "../ui";
import { JuryBench } from "./JuryBench";
import styles from "./debate.module.css";

const STANCE: Record<Stance, { label: string; tone: ChipTone }> = {
  open: { label: "Awaiting response", tone: "mute" },
  contested: { label: "Overlap disputed", tone: "amber" },
  conceded: { label: "Overlap accepted", tone: "bone" },
};

const OUTCOME: Record<Outcome, { label: string; tone: ChipTone; line: string }> = {
  pending: { label: "awaiting verifier", tone: "mute", line: "The verifier has not ruled yet: nothing here reaches the report until it does." },
  verified: { label: "verified", tone: "teal", line: "Evidence verified and included in the report." },
  rejected: { label: "struck", tone: "red", line: "Evidence rejected and excluded from the report." },
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

const roleLabel = styles.roleLabel;

function Exchange({ claim, evidence, models }: { claim: ClaimState; evidence: Evidence[]; models: Record<string, string | undefined> }) {
  const rejected = claim.status === "rejected";
  return (
    <div className={styles.exchange}>
      <div className={styles.argument}>
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className={roleLabel} style={{ color: agentColor(claim.by) }}>{claim.by}</span>
          <span className="font-mono text-[11px] text-mute">{[shortModel(models[claim.by]), KIND_LABEL[claim.kind] ?? claim.kind].filter(Boolean).join(" · ")}</span>
        </div>
        <p className={clsx(styles.argumentText, rejected && styles.rejectedText)}>{claim.text}</p>
        {evidence.length > 0 && <details className={styles.evidence}>
          <summary>Source evidence <span>{evidence.length}</span></summary>
          {evidence.map((e) => {
            const href = safeHref(e.url);
            return (
              <blockquote key={e.evid} className="mt-3 text-[13px] leading-relaxed text-bone-dim">
                “{e.quote}”
                {href && <a href={href} target="_blank" rel="noopener noreferrer" className="ml-1.5 text-[12px] text-accent hover:underline">source ↗</a>}
              </blockquote>
            );
          })}
        </details>}
      </div>

      <div className={styles.response}>
        {claim.thread.length === 0 && (
          <p className="text-[12.5px] italic leading-snug text-faint">{claim.simulated ? "Injected after the debate to test the verifier: nobody argued this one." : "The advocate has not answered yet."}</p>
        )}
        {turns(claim.thread).map((turn, i) => (
          <div key={i} className={clsx("animate-rise", i > 0 && "mt-2")}>
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className={roleLabel} style={{ color: agentColor(turn.frm) }}>{turn.frm}</span>
              <span className="font-mono text-[11px] text-mute">{[shortModel(models[turn.frm]), VERB[turn.type]].filter(Boolean).join(" · ")}</span>
            </div>
            {turn.texts.map((text, j) => <p key={j} className={styles.argumentText}>{text}</p>)}
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
      {claim.reason && <span className={clsx("ml-1 text-[12px] leading-relaxed", rejected ? "text-vermilion" : "text-mute")}>{rejected ? "Struck: " : "Ruling: "}{claim.reason}</span>}
    </div>
  );
}

export function CaseFile({ c, evidence, models, fresh }: {
  c: DebateCase;
  evidence: Record<string, Evidence>;
  models: Record<string, string | undefined>;
  /** Mark the case currently being updated without opening it automatically. */
  fresh: boolean;
}) {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const firstClaim = c.claims[0];
  const response = firstClaim?.thread.filter((turn) => turn.frm === "advocate").at(-1);
  const stance = STANCE[c.stance];
  const outcome = OUTCOME[c.outcome];
  const rejected = c.outcome === "rejected";
  return (
    <article className={styles.card} data-simulated={c.simulated} data-rejected={rejected}>
      <div className={styles.caseOverview}>
        <div className={styles.caseHeading}>
          <h3 className={styles.caseName}>{c.name}</h3>
          <Chip tone={rejected ? "red" : c.simulated ? "amber" : stance.tone}>
            {c.simulated ? "Simulated test" : rejected ? "Evidence rejected" : stance.label}
          </Chip>
        </div>
        <dl className={styles.casePreview}>
          {firstClaim && <div><dt>The claim</dt><dd>{firstClaim.text}</dd></div>}
          <div><dt>The response</dt><dd>{response?.text ?? (c.simulated ? "A simulated claim used to test verification." : firstClaim ? "Waiting for the advocate’s response." : "Jury assessment available; no claim has been made yet.")}</dd></div>
        </dl>
        <div className={styles.caseActions}>
          <span className={styles.evidenceStatus}>
            {fresh ? "Updating…" : c.outcome === "verified" ? "Evidence checked" : c.outcome === "rejected" ? "Excluded from report" : c.outcome === "lead" ? "Unverified evidence" : "Evidence check pending"}
            {c.claims.length > 1 && ` · ${c.claims.length} claims`}
          </span>
          <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-controls={detailId} aria-label={`${open ? "Hide" : "Read"} debate: ${c.name}`} className={styles.detailButton}>
            {open ? "Hide debate" : "Read debate"}
            <ChevronDown size={14} className={clsx("transition-transform", open && "rotate-180")} />
          </button>
        </div>
      </div>

      {open && (
        <div id={detailId} className={styles.caseBody}>
          <div className="flex flex-wrap items-center gap-3">{c.sources.map((source) => <SourceMark key={source} source={source} />)}</div>
          {c.simulated && <SimulatedTag className="self-start" />}
          {c.claims.map((claim) => <Exchange key={claim.cid} claim={claim} models={models} evidence={claim.evidence.map((id) => evidence[id]).filter(Boolean)} />)}
          {c.bench.length > 0 && <div className={styles.jury}><JuryBench bench={c.bench} /></div>}
          {c.claims.length > 0 && (
            <div className={styles.ruling}>
              {c.claims.map((claim) => <Ruling key={claim.cid} claim={claim} showCid={c.claims.length > 1} />)}
            </div>
          )}
          {c.claims.length > 0 && <p className={clsx("-mt-3 text-[12px]", rejected ? "text-vermilion" : c.outcome === "verified" ? "text-teal" : "text-mute")}>{outcome.line}</p>}
        </div>
      )}
    </article>
  );
}
