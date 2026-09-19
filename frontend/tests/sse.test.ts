// The AgentEvent type `error` shares its name with EventSource's native error event. A server message named
// `error` must reach the reducer and must NOT be counted as a connection failure. Run with `pnpm test`.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { connectRunEvents, isServerMessage, type SseState } from "../lib/sse";
import type { AgentEvent } from "../lib/types";

/** Just enough of EventSource: named listeners plus the on* handlers, dispatched the way a browser does. */
class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static last: FakeEventSource | null = null;

  readyState = FakeEventSource.CONNECTING;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  private listeners = new Map<string, Set<(e: Event) => void>>();

  constructor(public readonly url: string) { FakeEventSource.last = this; }

  addEventListener(type: string, fn: (e: Event) => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(fn);
  }

  close() { this.readyState = FakeEventSource.CLOSED; }

  dispatch(e: Event) {
    if (e.type === "open") this.onopen?.(e);
    if (e.type === "message") this.onmessage?.(e as MessageEvent);
    if (e.type === "error") this.onerror?.(e);
    for (const fn of this.listeners.get(e.type) ?? []) fn(e);
  }

  open() { this.readyState = FakeEventSource.OPEN; this.dispatch(new Event("open")); }
  serverSends(ev: AgentEvent) { this.dispatch(new MessageEvent(ev.type, { data: JSON.stringify(ev), lastEventId: String(ev.seq) })); }
  connectionDrops() { this.readyState = FakeEventSource.CONNECTING; this.dispatch(new Event("error")); }
}

const appError = (seq: number, recoverable = true): AgentEvent =>
  ({ seq, run_id: "r1", ts: 1, agent: "judge", phase: "score", type: "error", data: { message: "jurors dropped", recoverable } }) as AgentEvent;

describe("connectRunEvents", () => {
  beforeEach(() => {
    vi.stubGlobal("window", globalThis);
    vi.stubGlobal("EventSource", FakeEventSource);
  });
  afterEach(() => vi.unstubAllGlobals());

  function connect() {
    const events: AgentEvent[] = [];
    const states: SseState[] = [];
    const fatal: string[] = [];
    const conn = connectRunEvents("r1", { onEvent: (ev) => events.push(ev), onState: (s) => states.push(s), onFatal: (m) => fatal.push(m) });
    return { events, states, fatal, conn, es: FakeEventSource.last! };
  }

  it("tells a server message apart from a connection error", () => {
    expect(isServerMessage(new MessageEvent("error", { data: "{}" }))).toBe(true);
    expect(isServerMessage(new Event("error"))).toBe(false);
  });

  it("delivers server-sent `error` events without treating them as connection failures", () => {
    const { events, states, fatal, es } = connect();
    es.open();
    for (let seq = 1; seq <= 12; seq++) es.serverSends(appError(seq));
    expect(events.map((e) => e.seq)).toEqual(Array.from({ length: 12 }, (_, i) => i + 1));
    expect(states).toEqual(["connecting", "open"]);
    expect(fatal).toEqual([]);
    expect(es.readyState).toBe(FakeEventSource.OPEN);
  });

  it("still reports real connection drops, recovers on reopen, and gives up after repeated failures", () => {
    const { states, fatal, es } = connect();
    es.open();
    es.connectionDrops();
    expect(states.at(-1)).toBe("reconnecting");
    es.open();
    expect(states.at(-1)).toBe("open");
    for (let i = 0; i < 8; i++) es.connectionDrops();
    expect(fatal).toEqual(["Lost the connection to the backend."]);
    expect(states.at(-1)).toBe("closed");
  });
});
