"use client";
// One run, many pages. The (tabs) layout renders this once, so the stream (or replay), the selection and the map's
// memory survive moving between tabs: in the App Router a layout keeps its state across sibling navigation, a page
// does not. Everything the old single-page RunView held in local state lives here instead.
import { useSearchParams } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { ApiError, coachSay, rescoreMutation, runAction } from "@/lib/api";
import type { ActionState } from "@/lib/runReducer";
import { selectEvidenceCards, type EvidenceCardModel } from "@/lib/selectors";
import { useRunEvents, type RunEvents } from "@/lib/useRunEvents";
import { ToastProvider, useToast } from "../ui";
import { RunShell } from "./RunShell";

export type RunSegment = "" | "debate" | "coach" | "report";

/** Camera pose of the islands map, remembered while another tab is showing. */
export interface CameraMemo { position: [number, number, number]; target: [number, number, number]; zoom: number; userMoved: boolean }

export interface RunContextValue {
  runId: string;
  run: RunEvents;
  isReplay: boolean;
  streaming: boolean;
  selectedId: string | null;
  select: (id: string | null) => void;
  busyAction: string | null;
  busyMid: string | null;
  onAct: (a: ActionState) => Promise<void>;
  onRescore: (mid: string) => Promise<void>;
  /** One turn of the coaching conversation. `pendingSay` is the author's message until the stream echoes it back. */
  onCoachSay: (text: string, mid?: string | null) => Promise<void>;
  coachBusy: boolean;
  pendingSay: string | null;
  cards: EvidenceCardModel[];
  /** islands that have already popped in, so returning to the Map tab does not replay the animation */
  seenIslands: RefObject<Set<string>>;
  cameraMemo: RefObject<CameraMemo | null>;
  /** Every link inside a run goes through this: dropping ?replay= / ?speed= would remount the provider and restart the run. */
  hrefFor: (segment: RunSegment) => { pathname: string; query: Record<string, string> };
  /** query params a page may read without its own Suspense boundary */
  mapMode: "3d" | "2d";
}

const RunContext = createContext<RunContextValue | null>(null);

export function useRun(): RunContextValue {
  const v = useContext(RunContext);
  if (!v) throw new Error("useRun must be used inside <RunProvider>");
  return v;
}

function RunProviderInner({ runId, replay, speed, mapMode, children }: { runId: string; replay: string | null; speed: string | null; mapMode: "3d" | "2d"; children: ReactNode }) {
  const run = useRunEvents(runId, { replay, speed });
  const { state, status, transport, controls, epoch } = run;
  const toast = useToast();
  const isReplay = transport === "replay";

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [busyMid, setBusyMid] = useState<string | null>(null);
  const [pendingSay, setPendingSay] = useState<{ text: string; at: number } | null>(null);
  const [coachBusy, setCoachBusy] = useState(false);
  const seenIslands = useRef<Set<string>>(new Set());
  const cameraMemo = useRef<CameraMemo | null>(null);

  // a restart or a seek backwards re-folds the run from zero: the islands should pop in again
  useEffect(() => { seenIslands.current.clear(); }, [epoch]);

  const cards = useMemo(() => selectEvidenceCards(state), [state]);
  const streaming = status === "live" || status === "replaying" || status === "reconnecting";

  const replayNotice = useCallback(() => toast({ title: "Replay mode: actions are disabled", body: "This is a recording, so nothing is sent to the backend. Start a live investigation to arm a watch, draft a pitch or write back.", tone: "amber" }), [toast]);

  const resync = run.resync;
  const onAct = useCallback(async (a: ActionState) => {
    if (isReplay) { replayNotice(); return; }
    setBusyAction(a.action);
    try {
      const res = await runAction(runId, a.action as Parameters<typeof runAction>[1]);
      if (!res.ok) toast({ title: `${a.action.replace(/_/g, " ")}: not completed`, body: typeof res.detail === "string" ? res.detail : undefined, tone: "red" });
      resync();
    } catch (err) {
      toast({ title: "Action failed", body: err instanceof ApiError ? err.message : "Could not reach the backend.", tone: "red" });
    } finally {
      setBusyAction(null);
    }
  }, [isReplay, replayNotice, resync, runId, toast]);

  const onRescore = useCallback(async (mid: string) => {
    if (isReplay) { replayNotice(); return; }
    setBusyMid(mid);
    setSelectedId(`mut:${mid}`);
    try {
      await rescoreMutation(runId, mid);
      resync();
    } catch (err) {
      toast({ title: "Re-score failed", body: err instanceof ApiError ? err.message : "Could not reach the backend.", tone: "red" });
    } finally {
      setBusyMid(null);
    }
  }, [isReplay, replayNotice, resync, runId, toast]);

  const coachCount = state.coach.length;
  const onCoachSay = useCallback(async (text: string, mid?: string | null) => {
    const said = text.trim();
    if (!said) return;
    if (isReplay) { toast({ title: "This conversation is a recording", body: "Start a live investigation to talk your own idea through with the coach.", tone: "amber" }); return; }
    setCoachBusy(true);
    setPendingSay({ text: said, at: coachCount });
    try {
      const res = await coachSay(runId, said, mid);
      if (!res.ok) toast({ title: "The coach could not answer", body: typeof res.message === "string" ? res.message : undefined, tone: "red" });
      resync();
    } catch (err) {
      toast({ title: "Message not sent", body: err instanceof ApiError ? err.message : "Could not reach the backend.", tone: "red" });
    } finally {
      setCoachBusy(false);
      setPendingSay(null);
    }
  }, [coachCount, isReplay, resync, runId, toast]);
  // the stream echoes the author's message back within a beat; from then on the real one is shown
  const pendingText = pendingSay && coachCount === pendingSay.at ? pendingSay.text : null;

  // action.done -> toast
  const lastDone = state.lastActionDone;
  useEffect(() => {
    if (!lastDone) return;
    toast({ title: `${lastDone.action.replace(/_/g, " ")}: ${lastDone.ok ? "done" : "failed"}`, body: lastDone.detail, tone: lastDone.ok ? "teal" : "red" });
  }, [lastDone, toast]);

  // keyboard: space play/pause, → step, E end, R restart (replay only).
  // Focus rests on a tab link after every navigation, so links must not swallow the shortcuts; a focused button
  // only keeps Space (its own activation key).
  useEffect(() => {
    if (!controls) return;
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === " ") {
        if (el && ["BUTTON", "SUMMARY"].includes(el.tagName)) return;
        e.preventDefault();
        controls.toggle();
      } else if (e.key === "ArrowRight") controls.step();
      else if (e.key.toLowerCase() === "e") controls.skipToEnd();
      else if (e.key.toLowerCase() === "r") controls.restart();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [controls]);

  const hrefFor = useCallback((segment: RunSegment) => {
    const query: Record<string, string> = {};
    if (replay) query.replay = replay;
    if (speed) query.speed = speed;
    if (mapMode === "2d") query.map = "2d";
    return { pathname: `/runs/${encodeURIComponent(runId)}${segment ? `/${segment}` : ""}`, query };
  }, [mapMode, replay, runId, speed]);

  const value = useMemo<RunContextValue>(() => ({
    runId, run, isReplay, streaming, selectedId, select: setSelectedId,
    busyAction, busyMid, onAct, onRescore, onCoachSay, coachBusy, pendingSay: pendingText, cards, seenIslands, cameraMemo, hrefFor, mapMode,
  }), [runId, run, isReplay, streaming, selectedId, busyAction, busyMid, onAct, onRescore, onCoachSay, coachBusy, pendingText, cards, hrefFor, mapMode]);

  return (
    <RunContext.Provider value={value}>
      <RunShell>{children}</RunShell>
    </RunContext.Provider>
  );
}

export function RunProvider({ runId, children }: { runId: string; children: ReactNode }) {
  const params = useSearchParams();
  const replay = params.get("replay");
  const speed = params.get("speed");
  const mapMode = params.get("map") === "2d" ? "2d" : "3d";
  return (
    <ToastProvider>
      {/* keyed by everything that identifies a stream: a different run (or replay, or speed) remounts with fresh state */}
      <RunProviderInner key={`${runId}|${replay ?? ""}|${speed ?? ""}`} runId={runId} replay={replay} speed={speed} mapMode={mapMode}>
        {children}
      </RunProviderInner>
    </ToastProvider>
  );
}
