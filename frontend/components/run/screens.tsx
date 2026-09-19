"use client";
// The list pages. Each one is an existing panel in a quiet reading column: the panels only ever needed `state`.
import clsx from "clsx";
import { useEffect } from "react";
import { fmtTokens, fmtUsd } from "@/lib/format";
import { selectSpend } from "@/lib/selectors";
import { ActionBar } from "../ActionBar";
import { CostTable } from "../CostMeter";
import { DebateThread } from "../DebateThread";
import { EvidenceCard } from "../EvidenceCard";
import { EvidenceLedger } from "../EvidenceLedger";
import { MutationPanel } from "../MutationPanel";
import { PitchHighlighter } from "../PitchHighlighter";
import { ReportPanel } from "../ReportPanel";
import { SwarmTimeline } from "../SwarmTimeline";
import { Chip, Empty, SourceMark } from "../ui";
import { useRun } from "./RunProvider";
import { PageColumn } from "./RunShell";

const card = "overflow-hidden rounded-2xl border border-line bg-ink-900";

export function EvidenceScreen() {
  const { cards, ledger, sourceStatus, evidenceView, setEvidenceView, selectedId, select } = useRun();

  // arriving from the map with an island selected: bring its card into view
  useEffect(() => {
    if (!selectedId) return;
    document.querySelector(`[data-node-id="${CSS.escape(selectedId)}"]`)?.scrollIntoView({ block: "center" });
    // only on arrival: following the selection while you browse the list would fight your scrolling
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <PageColumn
      title="Evidence"
      hint="Every project the scouts brought back, resolved into entities. The ledger shows what was merged, inferred or left open."
      right={
        <div className="flex rounded-full border border-line-strong p-0.5 text-[12.5px]">
          {(["cards", "ledger"] as const).map((v) => (
            <button key={v} type="button" onClick={() => setEvidenceView(v)} className={clsx("rounded-full px-3 py-1 transition-colors", evidenceView === v ? "bg-bone text-ink-900" : "text-mute hover:text-bone")}>
              {v === "cards" ? `Cards ${cards.length || ""}` : `Ledger ${ledger.length || ""}`}
            </button>
          ))}
        </div>
      }
    >
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1">
        {sourceStatus.map((s) => (
          <span key={s.source} className={clsx("flex items-center gap-1.5", s.status === "skipped" && "opacity-50")} title={s.error ?? s.status}>
            <SourceMark source={s.source} />
            {s.status === "failed" ? <Chip tone="red">failed</Chip> : s.status === "degraded" ? <Chip tone="amber">retried</Chip> : s.status === "skipped" ? <Chip tone="mute">skipped</Chip> : <span className="font-mono text-[10.5px] text-mute">{s.n_records}</span>}
          </span>
        ))}
      </div>
      {evidenceView === "cards" ? (
        cards.length ? (
          <div className="flex flex-col gap-2.5">
            {cards.map((c) => (
              <div key={c.key} data-node-id={c.nodeId ?? undefined}>
                <EvidenceCard card={c} selected={!!c.nodeId && c.nodeId === selectedId} onSelect={(picked) => select(picked?.nodeId ?? null)} />
              </div>
            ))}
          </div>
        ) : <Empty>No prior art yet. The scouts are still out.</Empty>
      ) : (
        <div className={card}><EvidenceLedger rows={ledger} /></div>
      )}
    </PageColumn>
  );
}

export function DebateScreen() {
  const { run } = useRun();
  return (
    <PageColumn title="Debate" hint="The critic argues it has been done, the advocate distinguishes, a cross-family jury votes, and the verifier checks every quote.">
      <div className={card}><DebateThread state={run.state} /></div>
    </PageColumn>
  );
}

export function CoachScreen() {
  const { run, selectedId, select, onRescore, busyMid, busyAction, onAct } = useRun();
  const { state } = run;
  return (
    <PageColumn title="Coach" hint="One facet swapped at a time, toward the emptier parts of the map. Re-score one and watch it drift on the Map.">
      <div className={card}>
        <MutationPanel state={state} selectedId={selectedId} onFocus={(mid) => select(`mut:${mid}`)} onRescore={onRescore} busyMid={busyMid} />
      </div>
      {state.actions.length > 0 && (
        <div className={clsx(card, "sticky bottom-3 mt-4 shadow-[0_10px_40px_rgb(0_0_0/0.08)]")}>
          <ActionBar actions={state.actions} busy={busyAction} onAct={onAct} />
        </div>
      )}
    </PageColumn>
  );
}

export function ReportScreen() {
  const { run } = useRun();
  const { state } = run;
  return (
    <PageColumn title="Report" hint="Written from verified claims only.">
      <div className={card}><ReportPanel state={state} /></div>
      <section className="mt-6" aria-labelledby="voice-h">
        <h2 id="voice-h" className="font-display text-[22px] text-bone">Voice</h2>
        <p className="mb-2 text-[13px] text-mute">GPTZero&rsquo;s read of how your pitch is written. It is a separate axis and never moves the originality score.</p>
        <div className={clsx(card, "min-h-[128px]")}><PitchHighlighter ideaText={state.ideaText} voice={state.voice} /></div>
      </section>
    </PageColumn>
  );
}

export function SwarmScreen() {
  const { run, streaming } = useRun();
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
    </PageColumn>
  );
}
