"use client";
// The chrome around every run page: a quiet header (idea, spend, score, status), the honesty banners, and the
// bottom bar with the tabs. Pages render in between and own nothing but their content.
import clsx from "clsx";
import { TriangleAlert } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { fmtUsd } from "@/lib/format";
import { selectSpend } from "@/lib/selectors";
import type { RunStatus } from "@/lib/useRunEvents";
import { ReplayControls } from "../ReplayControls";
import { Wordmark } from "../SiteNav";
import { PitchDisclosure } from "./PitchDisclosure";
import { useRun } from "./RunProvider";
import { ScoreChip } from "./ScoreChip";
import { TabBar } from "./TabBar";

const STATUS: Record<RunStatus, { label: string; color: string; pulse?: boolean }> = {
  loading: { label: "Loading recording", color: "var(--color-mute)" },
  connecting: { label: "Connecting", color: "var(--color-mute)", pulse: true },
  live: { label: "Live", color: "var(--color-vermilion)", pulse: true },
  reconnecting: { label: "Reconnecting", color: "var(--color-amber)", pulse: true },
  replaying: { label: "Replay", color: "var(--color-amber)", pulse: true },
  paused: { label: "Paused", color: "var(--color-amber)" },
  finished: { label: "Finished", color: "var(--color-teal)" },
  failed: { label: "Run failed", color: "var(--color-vermilion)" },
  error: { label: "Offline", color: "var(--color-vermilion)" },
};

function StatusDot({ status, replay }: { status: RunStatus; replay: boolean }) {
  const s = STATUS[status];
  const label = status === "finished" && replay ? "Replay finished" : s.label;
  return (
    <span className="flex flex-none items-center gap-2 text-[12.5px]" style={{ color: s.color }}>
      <span className={clsx("size-[7px] rounded-full bg-current", s.pulse && "animate-beacon")} />
      {label}
    </span>
  );
}

export function RunShell({ children }: { children: ReactNode }) {
  const { run, isReplay, hrefFor } = useRun();
  const { state, status, controls } = run;
  const spend = selectSpend(state);
  const fatalErrors = state.errors.filter((e) => !e.recoverable);
  const simulatedCount = state.claimOrder.filter((c) => state.claims[c].simulated).length;

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      {/* honesty banners */}
      {state.mock && (
        <div className="hazard flex h-[24px] flex-none items-center justify-center gap-3 border-x-0 border-t-0 px-3 font-mono text-[10px] uppercase tracking-[0.18em]" role="note">
          Recorded mock run: fictional fixture data
          {simulatedCount > 0 && <span className="hidden md:inline">· includes {simulatedCount} simulated fire-drill claim{simulatedCount === 1 ? "" : "s"}, labelled where shown</span>}
        </div>
      )}
      {!state.mock && isReplay && (
        <div className="flex h-[22px] flex-none items-center justify-center border-b border-line bg-ink-800 px-3 font-mono text-[9.5px] uppercase tracking-[0.18em] text-mute" role="note">
          Replay of recorded run “{run.replayName}” · actions are disabled
        </div>
      )}
      {fatalErrors.length > 0 && (
        <div className="flex flex-none items-center gap-2 border-b border-vermilion/40 bg-vermilion/10 px-4 py-1.5 text-[12.5px] text-bone" role="alert">
          <TriangleAlert size={13} className="flex-none text-vermilion" /> {fatalErrors[fatalErrors.length - 1].message}
        </div>
      )}

      <header className="relative z-30 flex h-[60px] flex-none items-center gap-4 px-5 sm:px-7">
        <Wordmark className="flex-none" />
        <PitchDisclosure text={state.ideaText} url={state.ideaUrl} />
        <Link
          href={hrefFor("swarm")}
          className="hidden flex-none items-center gap-1.5 text-[12.5px] tabular-nums text-mute transition-colors hover:text-bone sm:flex"
          title={spend.degraded ? "Budget pressure: the conductor degraded the run. Details on the Swarm page." : "Spend so far. Per-model detail on the Swarm page."}
        >
          {spend.degraded && <span className="size-[6px] rounded-full bg-vermilion" />}
          {fmtUsd(spend.usd)} · {spend.calls} calls
          {spend.degraded && <span className="text-vermilion">· degraded</span>}
        </Link>
        <ScoreChip scores={state.scores} />
        <StatusDot status={status} replay={isReplay} />
      </header>

      {status === "error" ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <div className="max-w-[520px] text-center">
            <p className="label text-vermilion">No signal</p>
            <h1 className="mt-2 font-display text-[32px] leading-tight text-bone">{isReplay ? "That recording could not be loaded." : "The investigation backend is not answering."}</h1>
            <p className="mt-2 text-[14px] leading-relaxed text-bone-dim">{run.error}</p>
            <div className="mt-6 flex justify-center gap-2">
              <Link href="/" className="btn btn-primary">Back to start</Link>
            </div>
          </div>
        </div>
      ) : (
        <>
          <main className="relative min-h-0 flex-1">{children}</main>
          <footer className="relative z-30 flex h-[68px] flex-none items-center border-t border-line bg-ink-900 px-4">
            <div className="hidden min-w-0 flex-1 lg:block">{isReplay && controls && <ReplayControls controls={controls} snapshot={run.replay} />}</div>
            <TabBar />
            <div className="hidden flex-1 lg:block" />
          </footer>
        </>
      )}
    </div>
  );
}

/** A centred reading column for the list pages. */
export function PageColumn({ title, hint, right, children, wide }: { title: string; hint?: string; right?: ReactNode; children: ReactNode; wide?: boolean }) {
  return (
    <div className="h-full overflow-y-auto overscroll-contain">
      <div className={clsx("mx-auto px-5 pb-10 pt-2", wide ? "max-w-[980px]" : "max-w-[760px]")}>
        <div className="mb-4 flex flex-wrap items-end gap-x-4 gap-y-2">
          <div className="min-w-0 flex-1">
            <h1 className="font-display text-[30px] leading-tight text-bone">{title}</h1>
            {hint && <p className="mt-0.5 text-[13.5px] text-mute">{hint}</p>}
          </div>
          {right}
        </div>
        {children}
      </div>
    </div>
  );
}
