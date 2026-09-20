"use client";
// The chrome around every run page: a quiet header (status, spend, score), the replay and error banners, and the
// bottom bar with the tabs. Pages render in between and own nothing but their content.
import clsx from "clsx";
import { TriangleAlert } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import type { RunStatus } from "@/lib/useRunEvents";
import { ReplayControls } from "../ReplayControls";
import { Wordmark } from "../SiteNav";
import { useRun } from "./RunProvider";
import { ScoreChip } from "./ScoreChip";
import { SpendPill } from "./SpendPill";
import { TabBar } from "./TabBar";

const STATUS: Record<RunStatus, { label: string; color: string; pulse?: boolean }> = {
  loading: { label: "Loading recording", color: "var(--color-on-sea)" },
  connecting: { label: "Connecting", color: "var(--color-on-sea)", pulse: true },
  live: { label: "Live", color: "var(--color-vermilion)", pulse: true },
  reconnecting: { label: "Reconnecting", color: "var(--color-amber)", pulse: true },
  replaying: { label: "Replay", color: "var(--color-accent)", pulse: true },
  paused: { label: "Paused", color: "var(--color-accent)" },
  finished: { label: "Finished", color: "var(--color-teal)" },
  failed: { label: "Run failed", color: "var(--color-vermilion)" },
  error: { label: "Offline", color: "var(--color-vermilion)" },
};

function StatusDot({ status }: { status: RunStatus }) {
  const s = STATUS[status];
  return (
    <span className="flex flex-none items-center gap-2 text-[12.5px] leading-none" style={{ color: s.color }}>
      <span className={clsx("size-[7px] rounded-full bg-current", s.pulse && "animate-beacon")} />
      {s.label}
    </span>
  );
}

export function RunShell({ children }: { children: ReactNode }) {
  const { run, isReplay } = useRun();
  const { state, status, controls } = run;
  const fatalErrors = state.errors.filter((e) => !e.recoverable);

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      {/* banners. A mock run is not bannered here any more; simulated claims are still labelled where they are shown */}
      {!state.mock && isReplay && (
        <div className="flex h-[22px] flex-none items-center justify-center border-b border-line bg-ink-900/55 px-3 font-mono text-[9.5px] uppercase tracking-[0.18em] text-on-sea backdrop-blur-md" role="note">
          Replay of recorded run “{run.replayName}” · actions are disabled
        </div>
      )}
      {fatalErrors.length > 0 && (
        <div className="flex flex-none items-center gap-2 border-b border-vermilion/40 bg-vermilion/10 px-4 py-1.5 text-[12.5px] text-bone" role="alert">
          <TriangleAlert size={13} className="flex-none text-vermilion" /> {fatalErrors[fatalErrors.length - 1].message}
        </div>
      )}

      <header className="relative z-30 flex h-[60px] flex-none items-center justify-between gap-4 px-5 sm:px-7">
        <Wordmark pill className="flex-none" />
        {/* one cluster, one centre line: status, then the two pills — spend and score — whose edge the map's own button sits under */}
        <div className="flex flex-none items-center gap-2.5 sm:gap-3">
          {/* a recording's state is already on the transport in the bottom bar */}
          {!isReplay && <StatusDot status={status} />}
          <SpendPill state={state} />
          <ScoreChip scores={state.scores} />
        </div>
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
          {/* see-through: on the map tab the sea runs on underneath it */}
          <footer className="relative z-30 flex h-[68px] flex-none items-center border-t border-line bg-ink-900/70 px-5 backdrop-blur-md sm:px-7">
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
            {hint && <p className="mt-0.5 text-[13.5px] text-on-sea">{hint}</p>}
          </div>
          {right}
        </div>
        {children}
      </div>
    </div>
  );
}
