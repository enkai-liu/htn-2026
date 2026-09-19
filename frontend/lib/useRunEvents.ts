"use client";
// Chooses the transport for a run page and folds its events into RunState.
//
//   runId === "mock"  or  ?replay=<name>   -> static replay from /public/replay/<name>.jsonl (no backend needed)
//   anything else                           -> live SSE from the backend
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { emptyLayout, foldLayout, type LayoutState } from "./islandLayout";
import { DEFAULT_SPEED, loadReplay, parseSpeed, ReplayController, safeReplayName, type ReplaySnapshot } from "./replay";
import { initialRunState, runReducer, type RunState } from "./runReducer";
import { connectRunEvents, type SseConnection } from "./sse";
import type { AgentEvent } from "./types";

export type Transport = "replay" | "live";
export type RunStatus = "loading" | "replaying" | "paused" | "connecting" | "live" | "reconnecting" | "finished" | "failed" | "error";

export interface RunControls {
  play: () => void;
  pause: () => void;
  toggle: () => void;
  restart: () => void;
  step: () => void;
  skipToEnd: () => void;
  seek: (count: number) => void;
  setSpeed: (speed: number) => void;
}

export interface RunEvents {
  state: RunState;
  /** where every island of the map sits: folded with the events, so it is identical for a stream, a seek or a remount */
  layout: LayoutState;
  /** bumps whenever the fold restarts from zero (replay restart / seek back): the map forgets which islands it has shown */
  epoch: number;
  status: RunStatus;
  transport: Transport;
  /** replay name when transport === "replay" */
  replayName: string | null;
  /** present only for static replays */
  controls: RunControls | null;
  replay: ReplaySnapshot | null;
  error: string | null;
  /** live only: re-open the stream to pick up events emitted after the server closed it (rescore, actions) */
  resync: () => void;
}

type Action = { type: "events"; events: AgentEvent[] } | { type: "replace"; events: AgentEvent[] };

interface Folded { run: RunState; layout: LayoutState; epoch: number }
const initialFolded: Folded = { run: initialRunState, layout: emptyLayout, epoch: 0 };

function mutationFacets(run: RunState): Record<string, string> {
  const out: Record<string, string> = {};
  for (const mid of run.mutationOrder) out[mid] = run.mutations[mid].facet;
  return out;
}

function reducer(state: Folded, action: Action): Folded {
  let { run, layout } = action.type === "replace" ? initialFolded : state;
  for (const ev of action.events) {
    const next = runReducer(run, ev);
    if (next.graph !== run.graph) layout = foldLayout(layout, next.graph, { mutationFacet: mutationFacets(next) });
    run = next;
  }
  if (run === state.run && layout === state.layout) return state;
  return { run, layout, epoch: state.epoch + (action.type === "replace" ? 1 : 0) };
}

export interface RunEventsOptions { replay?: string | null; speed?: string | null }

/**
 * The hook never resets itself: mount it under a React `key` made of (runId, replay, speed), as RunView does,
 * so a different run always starts from a fresh reducer instead of clearing state inside an effect.
 */
export function useRunEvents(runId: string, opts: RunEventsOptions = {}): RunEvents {
  const replayName = useMemo(() => (runId === "mock" ? safeReplayName(opts.replay) ?? "mock" : safeReplayName(opts.replay)), [runId, opts.replay]);
  const transport: Transport = replayName ? "replay" : "live";
  const initialSpeed = useMemo(() => parseSpeed(opts.speed, DEFAULT_SPEED), [opts.speed]);
  const explicitSpeed = opts.speed != null && opts.speed !== "";

  const [folded, dispatch] = useReducer(reducer, initialFolded);
  const state = folded.run;
  const [snapshot, setSnapshot] = useState<ReplaySnapshot | null>(null);
  const [conn, setConn] = useState<"loading" | "connecting" | "open" | "reconnecting" | "closed" | "error">(transport === "replay" ? "loading" : "connecting");
  const [error, setError] = useState<string | null>(null);
  const [liveEpoch, setLiveEpoch] = useState(0);

  const controllerRef = useRef<ReplayController | null>(null);
  // Terminal = the server has said its last word (a report, or a non-recoverable error). The backend closes the
  // stream when it evicts the run, and that close is then the normal end rather than a dropped connection.
  const failed = state.errors.some((e) => !e.recoverable);
  const terminalRef = useRef(false);
  useEffect(() => { terminalRef.current = state.finished || failed; }, [state.finished, failed]);

  // --- static replay -------------------------------------------------------------------------------------------
  useEffect(() => {
    if (transport !== "replay" || !replayName) return;
    const abort = new AbortController();
    let controller: ReplayController | null = null;

    loadReplay(replayName, abort.signal)
      .then((events) => {
        if (abort.signal.aborted) return;
        controller = new ReplayController(events, {
          onEvents: (evs) => dispatch({ type: "events", events: evs }),
          onReplace: (evs) => dispatch({ type: "replace", events: evs }),
          onSnapshot: setSnapshot,
        }, initialSpeed);
        controllerRef.current = controller;
        setConn("open");
        if (initialSpeed <= 0) controller.skipToEnd(); else controller.play();
      })
      .catch((err: unknown) => {
        if (abort.signal.aborted) return;
        setConn("error");
        setError(err instanceof Error ? err.message : String(err));
      });

    return () => {
      abort.abort();
      controller?.dispose();
      if (controllerRef.current === controller) controllerRef.current = null;
    };
  }, [transport, replayName, initialSpeed]);

  // --- live SSE ------------------------------------------------------------------------------------------------
  useEffect(() => {
    if (transport !== "live") return;
    const connection: SseConnection = connectRunEvents(runId, {
      onEvent: (ev) => dispatch({ type: "events", events: [ev] }),
      onState: (s) => setConn(s),
      onFatal: (message) => { setConn("error"); setError(message); },
      isFinished: () => terminalRef.current,
    }, { speed: explicitSpeed ? initialSpeed : null });
    return () => connection.close();
    // liveEpoch is a manual "reconnect now" trigger (resync); speed is fixed for the lifetime of the hook
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transport, runId, liveEpoch]);

  const resync = useCallback(() => setLiveEpoch((n) => n + 1), []);

  const controls = useMemo<RunControls | null>(() => {
    if (transport !== "replay") return null;
    const c = () => controllerRef.current;
    return {
      play: () => c()?.play(),
      pause: () => c()?.pause(),
      toggle: () => c()?.toggle(),
      restart: () => c()?.restart(),
      step: () => c()?.step(),
      skipToEnd: () => c()?.skipToEnd(),
      seek: (n) => c()?.seek(n),
      setSpeed: (s) => c()?.setSpeed(s),
    };
  }, [transport]);

  let status: RunStatus;
  if (conn === "error") status = "error";
  else if (transport === "replay") {
    if (conn === "loading" || !snapshot) status = "loading";
    else if (snapshot.done) status = "finished";
    else status = snapshot.playing ? "replaying" : "paused";
  } else if (state.finished) status = "finished";
  // the backend only emits a non-recoverable error when the run has ended without a report
  else if (failed) status = "failed";
  else if (conn === "open") status = "live";
  else if (conn === "reconnecting") status = "reconnecting";
  else status = "connecting";

  return { state, layout: folded.layout, epoch: folded.epoch, status, transport, replayName, controls, replay: transport === "replay" ? snapshot : null, error, resync };
}
