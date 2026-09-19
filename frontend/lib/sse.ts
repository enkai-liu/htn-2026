// Live transport: EventSource client for GET {API}/api/runs/{id}/events.
//
// The server names every SSE message (`event: <type>`), and EventSource only delivers a named message to a
// listener registered for that exact name, so we register one listener per EventType plus `onmessage` for
// any unnamed message. Reconnects are the browser's: it re-sends Last-Event-ID and the server resumes after it.
// The reducer ignores seq <= lastSeq, so a server that re-sends the whole backlog is harmless too.
import { API_BASE } from "./api";
import { EVENT_TYPES } from "./eventTypes";
import type { AgentEvent } from "./types";

export type SseState = "connecting" | "open" | "reconnecting" | "closed";

export interface SseHandlers {
  onEvent: (ev: AgentEvent) => void;
  onState?: (state: SseState) => void;
  /** Called once, when we give up (the stream never opened, or kept failing). */
  onFatal?: (message: string) => void;
  /** Return true once run.finished has been seen: a closed stream is then the normal end, not an error. */
  isFinished?: () => boolean;
}

export interface SseConnection { close: () => void }

const MAX_FAILURES_BEFORE_OPEN = 3;
const MAX_FAILURES_AFTER_OPEN = 8;

export function runEventsUrl(runId: string, speed?: number | null): string {
  const qs = speed != null ? `?speed=${encodeURIComponent(String(speed))}` : "";
  return `${API_BASE}/api/runs/${encodeURIComponent(runId)}/events${qs}`;
}

export function connectRunEvents(runId: string, handlers: SseHandlers, opts: { speed?: number | null } = {}): SseConnection {
  if (typeof window === "undefined" || typeof EventSource === "undefined") {
    handlers.onFatal?.("This browser does not support Server-Sent Events.");
    return { close: () => {} };
  }

  let closed = false;
  let everOpened = false;
  let failures = 0;
  const es = new EventSource(runEventsUrl(runId, opts.speed));
  handlers.onState?.("connecting");

  const close = () => {
    if (closed) return;
    closed = true;
    es.close();
    handlers.onState?.("closed");
  };

  const deliver = (msg: MessageEvent) => {
    if (closed) return;
    try {
      const ev = JSON.parse(String(msg.data)) as AgentEvent;
      if (ev && typeof ev.type === "string") handlers.onEvent(ev);
    } catch {
      // keep-alive comments and partial frames are not events
    }
  };

  es.onopen = () => {
    everOpened = true;
    failures = 0;
    handlers.onState?.("open");
  };
  es.onmessage = deliver;
  for (const type of EVENT_TYPES) es.addEventListener(type, deliver as EventListener);

  es.onerror = () => {
    if (closed) return;
    if (handlers.isFinished?.()) { close(); return; } // server closed the stream after run.finished
    failures += 1;
    const limit = everOpened ? MAX_FAILURES_AFTER_OPEN : MAX_FAILURES_BEFORE_OPEN;
    if (es.readyState === EventSource.CLOSED || failures >= limit) {
      close();
      handlers.onFatal?.(everOpened ? "Lost the connection to the backend." : "Could not reach the backend, or this run does not exist.");
      return;
    }
    handlers.onState?.("reconnecting");
  };

  return { close };
}
