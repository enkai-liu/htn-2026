"use client";
// The list pages. Each one is an existing panel in a quiet reading column: the panels only ever needed `state`.
import clsx from "clsx";
import { fmtTokens, fmtUsd } from "@/lib/format";
import { selectSpend } from "@/lib/selectors";
import { ActionBar } from "../ActionBar";
import { CoachPanel } from "../coach/CoachPanel";
import { CostTable } from "../CostMeter";
import { DebateBoard } from "../debate/DebateBoard";
import { EvidenceLedger } from "../EvidenceLedger";
import { PitchHighlighter } from "../PitchHighlighter";
import { ReportPanel } from "../ReportPanel";
import { SwarmTimeline } from "../SwarmTimeline";
import { Chip, SourceMark } from "../ui";
import { useRun } from "./RunProvider";
import { PageColumn } from "./RunShell";

const card = "overflow-hidden rounded-2xl border border-line bg-ink-900";

/** What each scout brought back, and which ones limped. */
function SourceStatus() {
  const { sourceStatus } = useRun();
  if (!sourceStatus.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {sourceStatus.map((s) => (
        <span key={s.source} className={clsx("flex items-center gap-1.5", s.status === "skipped" && "opacity-50")} title={s.error ?? s.status}>
          <SourceMark source={s.source} />
          {s.status === "failed" ? <Chip tone="red">failed</Chip> : s.status === "degraded" ? <Chip tone="amber">retried</Chip> : s.status === "skipped" ? <Chip tone="mute">skipped</Chip> : <span className="font-mono text-[10.5px] text-mute">{s.n_records}</span>}
        </span>
      ))}
    </div>
  );
}

export function DebateScreen() {
  const { run, streaming } = useRun();
  return (
    <PageColumn title="Debate">
      <DebateBoard state={run.state} streaming={streaming} />
    </PageColumn>
  );
}

export function CoachScreen() {
  const { run, busyAction, onAct } = useRun();
  const { state } = run;
  return (
    <PageColumn wide title="Coach" hint="Talk the idea through. Everything you say is checked against the corpus before the coach answers.">
      <CoachPanel
        state={state}
        footer={state.actions.length > 0 ? <div className={card}><ActionBar actions={state.actions} busy={busyAction} onAct={onAct} /></div> : null}
      />
    </PageColumn>
  );
}

export function ReportScreen() {
  const { run } = useRun();
  const { state } = run;
  return (
    <PageColumn title="Report">
      <div className={card}><ReportPanel state={state} /></div>
      <section className="mt-6" aria-labelledby="voice-h">
        <h2 id="voice-h" className="mb-2 font-display text-[22px] text-bone">Voice <span className="text-[13px] text-mute">· GPTZero</span></h2>
        <div className={clsx(card, "min-h-[128px]")}><PitchHighlighter ideaText={state.ideaText} voice={state.voice} /></div>
      </section>
    </PageColumn>
  );
}

export function SwarmScreen() {
  const { run, streaming, ledger } = useRun();
  const { state } = run;
  const spend = selectSpend(state);
  return (
    <PageColumn wide title="Swarm" hint={`${state.eventCount} events${state.orchestrator ? ` · orchestrated by ${state.orchestrator}` : ""}`}>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_400px]">
        <div className={clsx(card, "h-[min(680px,calc(100dvh-260px))] min-h-[420px]")}><SwarmTimeline state={state} streaming={streaming} /></div>
        <div className={clsx(card, "h-fit p-4")}>
          <div className="mb-3 flex items-baseline gap-3">
            <span className="font-display text-[30px] leading-none text-bone">{fmtUsd(spend.usd)}</span>
            <span className="text-[12.5px] text-mute">{spend.calls} calls · {fmtTokens(spend.tokens)} tokens · {Math.round(spend.elapsed)}s</span>
          </div>
          {spend.degraded && <p className="mb-3 rounded-lg bg-vermilion/10 px-2.5 py-1.5 text-[12.5px] text-vermilion">Degraded: the conductor cut scope to stay inside the budget.</p>}
          <CostTable state={state} />
        </div>
      </div>

      {/* the data-wrangling receipts: what the resolver merged, inferred or declined to decide */}
      <section className="mt-6" aria-labelledby="ledger-h">
        <div className="mb-2 flex flex-wrap items-end gap-x-4 gap-y-2">
          <div className="min-w-0 flex-1">
            <h2 id="ledger-h" className="font-display text-[22px] text-bone">Ledger {!!ledger.length && <span className="text-[13px] text-mute">· {ledger.length}</span>}</h2>
            <p className="mt-0.5 text-[13px] text-mute">Every merge, conflict, inference and source failure, with how it was settled.</p>
          </div>
          <SourceStatus />
        </div>
        <div className={card}><EvidenceLedger rows={ledger} /></div>
      </section>
    </PageColumn>
  );
}
