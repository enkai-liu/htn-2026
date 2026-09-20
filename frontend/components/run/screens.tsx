"use client";
// The list pages. Each one is an existing panel in a quiet reading column: the panels only ever needed `state`.
import { ActionBar } from "../ActionBar";
import { CoachPanel } from "../coach/CoachPanel";
import { DebateBoard } from "../debate/DebateBoard";
import debateStyles from "../debate/debate.module.css";
import { PitchHighlighter } from "../PitchHighlighter";
import { ReportDetail, ReportPanel } from "../ReportPanel";
import reportStyles from "../report/report.module.css";
import { useRun } from "./RunProvider";
import { PageColumn } from "./RunShell";

const card = "overflow-hidden rounded-2xl border border-line bg-ink-900";

export function DebateScreen() {
  const { run, streaming } = useRun();
  return (
    <div className={debateStyles.page}>
      <div className={debateStyles.container}>
        <header className={debateStyles.pageHeader}>
          <h1>Debate</h1>
          <p>See what overlaps with your idea, and what’s different.</p>
        </header>
        <DebateBoard state={run.state} streaming={streaming} />
      </div>
    </div>
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
    <div className={debateStyles.page}>
      <div className={debateStyles.container}>
        <header className={debateStyles.pageHeader}>
          <h1>Report</h1>
          <p>What the investigation found, and what it means for your idea.</p>
        </header>
        <ReportPanel state={state} />
        <ReportDetail title="Pitch writing analysis · GPTZero">
          <div className={reportStyles.voice}>
            <p className={reportStyles.voiceNote}>This checks how the pitch is written. It does not affect the originality score.</p>
            <PitchHighlighter ideaText={state.ideaText} voice={state.voice} layout="reading" />
          </div>
        </ReportDetail>
      </div>
    </div>
  );
}
