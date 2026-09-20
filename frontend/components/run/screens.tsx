"use client";
// The list pages. Each one is an existing panel in a quiet reading column: the panels only ever needed `state`.
import clsx from "clsx";
import { ActionBar } from "../ActionBar";
import { CoachPanel } from "../coach/CoachPanel";
import { DebateBoard } from "../debate/DebateBoard";
import { PitchHighlighter } from "../PitchHighlighter";
import { ReportPanel } from "../ReportPanel";
import { useRun } from "./RunProvider";
import { PageColumn } from "./RunShell";

const card = "overflow-hidden rounded-2xl border border-line bg-ink-900";

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
        <h2 id="voice-h" className="mb-2 font-display text-[22px] text-bone">Voice <span className="text-[13px] text-on-sea">· GPTZero</span></h2>
        <div className={clsx(card, "min-h-[128px]")}><PitchHighlighter ideaText={state.ideaText} voice={state.voice} /></div>
      </section>
    </PageColumn>
  );
}
