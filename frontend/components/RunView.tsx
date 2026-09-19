"use client";
// The live investigation view: swarm on the left, the chart in the middle (with scores above and Voice below),
// evidence / debate / coach / report on the right. Works identically for a live SSE run and a static replay.
import clsx from "clsx";
import { TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, rescoreMutation, runAction } from "@/lib/api";
import { truncate } from "@/lib/format";
import type { ActionState } from "@/lib/runReducer";
import { selectEvidenceCards, selectLedger, selectSourceStatus, type EvidenceCardModel } from "@/lib/selectors";
import type { GraphNode, Phase } from "@/lib/types";
import { useRunEvents, type RunStatus } from "@/lib/useRunEvents";
import { ActionBar } from "./ActionBar";
import { AxisGauges } from "./AxisGauges";
import { CostMeter } from "./CostMeter";
import { DebateThread } from "./DebateThread";
import { EvidenceCard } from "./EvidenceCard";
import { EvidenceLedger } from "./EvidenceLedger";
import { IdeaGraph } from "./IdeaGraph";
import { MutationPanel } from "./MutationPanel";
import { PitchHighlighter } from "./PitchHighlighter";
import { ReplayControls } from "./ReplayControls";
import { ReportPanel } from "./ReportPanel";
import { Wordmark } from "./SiteNav";
import { SwarmTimeline } from "./SwarmTimeline";
import { Chip, Empty, Plate, SourceMark, ToastProvider, useToast } from "./ui";

type Tab = "evidence" | "debate" | "coach" | "report";
const TABS: { id: Tab; label: string }[] = [
  { id: "evidence", label: "Evidence" },
  { id: "debate", label: "Debate" },
  { id: "coach", label: "Coach" },
  { id: "report", label: "Report" },
];

/** While "follow" is on, the right-hand tab tracks what the swarm is doing: a hands-free demo. */
function tabForPhase(phase: Phase | null, finished: boolean): Tab {
  if (finished || phase === "done") return "report";
  switch (phase) {
    case "debate": case "verify": case "score": return "debate";
    case "mutate": case "act": return "coach";
    default: return "evidence";
  }
}

const STATUS_PILL: Record<RunStatus, { label: string; color: string; pulse?: boolean }> = {
  loading: { label: "Loading recording", color: "var(--color-mute)" },
  connecting: { label: "Connecting", color: "var(--color-mute)", pulse: true },
  live: { label: "Live", color: "var(--color-vermilion)", pulse: true },
  reconnecting: { label: "Reconnecting", color: "var(--color-amber)", pulse: true },
  replaying: { label: "Replay", color: "var(--color-amber)", pulse: true },
  paused: { label: "Replay · paused", color: "var(--color-amber)" },
  finished: { label: "Finished", color: "var(--color-teal)" },
  failed: { label: "Run failed", color: "var(--color-vermilion)" },
  error: { label: "Offline", color: "var(--color-vermilion)" },
};

function StatusPill({ status, replay }: { status: RunStatus; replay: boolean }) {
  const s = STATUS_PILL[status];
  const label = status === "finished" && replay ? "Replay · finished" : s.label;
  return (
    <span className="flex h-[28px] flex-none items-center gap-2 border px-2.5 font-mono text-[10px] uppercase tracking-[0.16em]" style={{ color: s.color, borderColor: `color-mix(in srgb, ${s.color} 55%, transparent)` }}>
      <span className={clsx("size-[7px] rounded-full bg-current", s.pulse && "animate-beacon")} />
      {label}
    </span>
  );
}

function RunViewInner({ runId, replay, speed }: { runId: string; replay: string | null; speed: string | null }) {
  const run = useRunEvents(runId, { replay, speed });
  const { state, status, transport, controls } = run;
  const toast = useToast();
  const isReplay = transport === "replay";

  const [follow, setFollow] = useState(true);
  const [manualTab, setManualTab] = useState<Tab>("evidence");
  const [manualEvidenceView, setManualEvidenceView] = useState<"cards" | "ledger" | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [busyMid, setBusyMid] = useState<string | null>(null);

  const tab = follow ? tabForPhase(state.phase, state.finished) : manualTab;
  const evidenceView = manualEvidenceView ?? (follow && state.phase === "resolve" ? "ledger" : "cards");

  const cards = useMemo(() => selectEvidenceCards(state), [state]);
  const ledger = useMemo(() => selectLedger(state), [state]);
  const sourceStatus = useMemo(() => selectSourceStatus(state), [state]);
  const streaming = status === "live" || status === "replaying" || status === "reconnecting";

  const pickTab = useCallback((t: Tab) => { setFollow(false); setManualTab(t); }, []);

  const onSelectNode = useCallback((node: GraphNode | null) => {
    setSelectedId(node?.id ?? null);
    if (!node) return;
    if (node.kind === "entity") { setFollow(false); setManualTab("evidence"); setManualEvidenceView("cards"); }
    else if (node.kind === "mutation") { setFollow(false); setManualTab("coach"); }
  }, []);

  const onSelectCard = useCallback((card: EvidenceCardModel | null) => setSelectedId(card?.nodeId ?? null), []);

  const replayNotice = useCallback(() => toast({ title: "Replay mode — actions are disabled", body: "This is a recording, so nothing is sent to the backend. Start a live investigation to arm a watch, draft a pitch or write back.", tone: "amber" }), [toast]);

  const onAct = useCallback(async (a: ActionState) => {
    if (isReplay) { replayNotice(); return; }
    setBusyAction(a.action);
    try {
      const res = await runAction(runId, a.action);
      if (!res.ok) toast({ title: `${a.action.replace(/_/g, " ")}: not completed`, body: typeof res.detail === "string" ? res.detail : undefined, tone: "red" });
      run.resync();
    } catch (err) {
      toast({ title: "Action failed", body: err instanceof ApiError ? err.message : "Could not reach the backend.", tone: "red" });
    } finally {
      setBusyAction(null);
    }
  }, [isReplay, replayNotice, run, runId, toast]);

  const onRescore = useCallback(async (mid: string) => {
    if (isReplay) { replayNotice(); return; }
    setBusyMid(mid);
    setSelectedId(`mut:${mid}`);
    try {
      await rescoreMutation(runId, mid);
      run.resync();
    } catch (err) {
      toast({ title: "Re-score failed", body: err instanceof ApiError ? err.message : "Could not reach the backend.", tone: "red" });
    } finally {
      setBusyMid(null);
    }
  }, [isReplay, replayNotice, run, runId, toast]);

  // action.done -> toast
  const lastDone = state.lastActionDone;
  useEffect(() => {
    if (!lastDone) return;
    toast({ title: `${lastDone.action.replace(/_/g, " ")}: ${lastDone.ok ? "done" : "failed"}`, body: lastDone.detail, tone: lastDone.ok ? "teal" : "red" });
  }, [lastDone, toast]);

  // keyboard: space play/pause, → step, E end, R restart (replay only)
  useEffect(() => {
    if (!controls) return;
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT", "BUTTON", "A", "SUMMARY"].includes(el.tagName))) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === " ") { e.preventDefault(); controls.toggle(); }
      else if (e.key === "ArrowRight") controls.step();
      else if (e.key.toLowerCase() === "e") controls.skipToEnd();
      else if (e.key.toLowerCase() === "r") controls.restart();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [controls]);

  const fatalErrors = state.errors.filter((e) => !e.recoverable);
  const simulatedCount = state.claimOrder.filter((c) => state.claims[c].simulated).length;
  const counts: Record<Tab, number | null> = { evidence: cards.length || null, debate: state.claimOrder.length || null, coach: state.mutationOrder.length || null, report: null };

  return (
    <div className="flex min-h-dvh flex-col lg:h-dvh lg:overflow-hidden">
      {/* top bar */}
      <header className="relative z-30 flex h-[46px] flex-none items-center gap-3 border-b border-line bg-ink-900/80 px-3 backdrop-blur">
        <Wordmark className="flex-none" />
        <span className="hidden h-5 w-px flex-none bg-line-strong sm:block" />
        <p className="hidden min-w-0 flex-1 truncate font-display text-[16px] italic text-bone-dim sm:block" title={state.ideaText}>
          {state.ideaText ? `“${truncate(state.ideaText, 150)}”` : "Waiting for the run to start…"}
        </p>
        <span className="flex-1 sm:hidden" />
        {isReplay && controls && <ReplayControls controls={controls} snapshot={run.replay} />}
        <CostMeter state={state} />
        <StatusPill status={status} replay={isReplay} />
      </header>

      {/* honesty banners */}
      {state.mock && (
        <div className="hazard flex h-[24px] flex-none items-center justify-center gap-3 border-x-0 border-t-0 px-3 font-mono text-[10px] uppercase tracking-[0.2em]" role="note">
          Recorded mock run — fictional fixture data
          {simulatedCount > 0 && <span className="hidden text-amber/80 md:inline">· includes {simulatedCount} simulated fire-drill claim{simulatedCount === 1 ? "" : "s"}, labelled where shown</span>}
        </div>
      )}
      {!state.mock && isReplay && (
        <div className="flex h-[22px] flex-none items-center justify-center border-b border-line bg-ink-800/60 px-3 font-mono text-[9.5px] uppercase tracking-[0.2em] text-mute" role="note">
          Replay of recorded run “{run.replayName}” · actions are disabled
        </div>
      )}
      {fatalErrors.length > 0 && (
        <div className="flex flex-none items-center gap-2 border-b border-vermilion/50 bg-vermilion/10 px-3 py-1.5 text-[12px] text-bone" role="alert">
          <TriangleAlert size={13} className="flex-none text-vermilion" /> {fatalErrors[fatalErrors.length - 1].message}
        </div>
      )}

      {status === "error" ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <div className="plate max-w-[520px] p-6 text-center">
            <p className="label text-vermilion">No signal</p>
            <h1 className="mt-2 font-display text-[30px] leading-tight text-bone">{isReplay ? "That recording could not be loaded." : "The investigation backend is not answering."}</h1>
            <p className="mt-2 text-[13.5px] leading-relaxed text-bone-dim">{run.error}</p>
            <div className="mt-5 flex justify-center gap-2">
              <Link href="/runs/mock" className="btn btn-primary">Watch a recorded run</Link>
              <Link href="/" className="btn">Back to start</Link>
            </div>
          </div>
        </div>
      ) : (
        // below lg the plates stack at their own heights and the page scrolls; from lg up it is a fixed app shell
        <main className="grid flex-none gap-2.5 p-2.5 lg:min-h-0 lg:flex-1 lg:grid-cols-[292px_minmax(0,1fr)_404px]">
          <Plate index="01" title="The swarm" className="h-[520px] lg:h-auto" right={<span className="font-mono text-[9.5px] text-faint">{state.eventCount} events{state.orchestrator ? ` · ${state.orchestrator}` : ""}</span>}>
            <SwarmTimeline state={state} streaming={streaming} />
          </Plate>

          <div className="flex min-w-0 flex-col gap-2.5 lg:min-h-0">
            <Plate index="02" title="Originality" className="h-[146px] flex-none" right={<span className="font-mono text-[9.5px] text-faint">3 axes → headline · Voice is separate</span>}>
              <AxisGauges scores={state.scores} />
            </Plate>
            <Plate index="03" title="Chart of the idea-space" className="h-[460px] lg:h-auto lg:flex-1" bodyClassName="relative">
              <IdeaGraph
                graph={state.graph} facets={state.facets} mutations={state.mutations} priorSamples={state.priorSamples}
                active={streaming && !state.finished} selectedId={selectedId} onSelect={onSelectNode}
              />
            </Plate>
            <Plate index="04" title="Voice" className="h-[128px] flex-none" right={<span className="font-mono text-[9.5px] text-faint">GPTZero · its own axis, never in the headline</span>}>
              <PitchHighlighter ideaText={state.ideaText} voice={state.voice} />
            </Plate>
          </div>

          <section className="plate flex h-[640px] flex-col lg:h-auto lg:min-h-0">
            <div className="flex h-[34px] flex-none items-stretch border-b border-line" role="tablist" aria-label="Investigation panels">
              {TABS.map((t, i) => (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={tab === t.id}
                  onClick={() => pickTab(t.id)}
                  className={clsx("relative flex items-center gap-1.5 px-3 font-mono text-[10.5px] uppercase tracking-[0.16em] transition-colors", tab === t.id ? "text-bone" : "text-mute hover:text-bone-dim")}
                >
                  <span className="text-[9px] text-amber/80">{String(i + 5).padStart(2, "0")}</span>
                  {t.label}
                  {counts[t.id] != null && <span className="text-[9px] text-faint">{counts[t.id]}</span>}
                  {t.id === "report" && state.report && <span className="size-[5px] rounded-full bg-teal" />}
                  {tab === t.id && <span className="absolute inset-x-2 bottom-0 h-[2px] bg-amber" />}
                </button>
              ))}
              <button
                type="button"
                onClick={() => { setFollow((f) => !f); setManualTab(tab); setManualEvidenceView(null); }}
                className={clsx("ml-auto flex items-center gap-1.5 px-3 font-mono text-[9px] uppercase tracking-[0.14em]", follow ? "text-teal" : "text-faint hover:text-bone-dim")}
                title="Follow the swarm: switch panels automatically as the run moves through its phases"
                aria-pressed={follow}
              >
                <span className={clsx("size-[6px] rounded-full", follow ? "bg-teal" : "border border-current")} /> follow
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain" role="tabpanel">
              {tab === "evidence" && (
                <div className="flex min-h-full flex-col">
                  <div className="sticky top-0 z-[2] flex flex-none flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-ink-850/95 px-3 py-1.5 backdrop-blur">
                    <div className="flex border border-line-strong font-mono text-[9.5px] uppercase tracking-[0.14em]">
                      {(["cards", "ledger"] as const).map((v) => (
                        <button key={v} type="button" onClick={() => setManualEvidenceView(v)} className={clsx("px-2 py-1", evidenceView === v ? "bg-bone text-ink-950" : "text-mute hover:text-bone")}>
                          {v === "cards" ? `Cards ${cards.length || ""}` : `Ledger ${ledger.length || ""}`}
                        </button>
                      ))}
                    </div>
                    {sourceStatus.map((s) => (
                      <span key={s.source} className={clsx("flex items-center gap-1", s.status === "skipped" && "opacity-50")} title={s.error ?? s.status}>
                        <SourceMark source={s.source} />
                        {s.status === "failed" ? <Chip tone="red">failed</Chip> : s.status === "degraded" ? <Chip tone="amber">retried</Chip> : s.status === "skipped" ? <Chip tone="mute">skipped</Chip> : <span className="font-mono text-[10px] text-mute">{s.n_records}</span>}
                      </span>
                    ))}
                  </div>
                  {evidenceView === "cards" ? (
                    cards.length ? (
                      <div className="flex flex-col gap-2 p-3">
                        {cards.map((c) => <EvidenceCard key={c.key} card={c} selected={!!c.nodeId && c.nodeId === selectedId} onSelect={onSelectCard} />)}
                      </div>
                    ) : <Empty>No prior art on the chart yet. The scouts are still out.</Empty>
                  ) : (
                    <EvidenceLedger rows={ledger} />
                  )}
                </div>
              )}
              {tab === "debate" && <DebateThread state={state} />}
              {tab === "coach" && <MutationPanel state={state} selectedId={selectedId} onFocus={(mid) => setSelectedId(`mut:${mid}`)} onRescore={onRescore} busyMid={busyMid} />}
              {tab === "report" && <ReportPanel state={state} />}
            </div>

            <ActionBar actions={state.actions} busy={busyAction} onAct={onAct} />
          </section>
        </main>
      )}
    </div>
  );
}

export function RunView({ runId }: { runId: string }) {
  const params = useSearchParams();
  const replay = params.get("replay");
  const speed = params.get("speed");
  return (
    <ToastProvider>
      {/* keyed by everything that identifies a stream: a different run (or replay, or speed) remounts with fresh state */}
      <RunViewInner key={`${runId}|${replay ?? ""}|${speed ?? ""}`} runId={runId} replay={replay} speed={speed} />
    </ToastProvider>
  );
}
