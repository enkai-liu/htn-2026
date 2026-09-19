// Static replay transport: streams a recorded run (JSONL, one AgentEvent per line) from /public/replay/
// with its original pacing. Needs no backend: this is the demo insurance and the replay-only deploy.
//
// Timing mirrors backend/app/core/eventbus.py::replay so a static replay and a backend replay feel the same:
//     delay = min(max(ts[i] - ts[i-1], 0), MAX_GAP_S) / speed
import type { AgentEvent } from "./types";

export const DEFAULT_SPEED = 1.5;
export const MAX_GAP_S = 2.5;
export const SPEED_STEPS = [1, 1.5, 2, 4, 8] as const;

export interface ReplaySnapshot {
  /** number of events already emitted */
  index: number;
  total: number;
  playing: boolean;
  speed: number;
  done: boolean;
}

export interface ReplaySink {
  /** append these events (already in order) */
  onEvents: (events: AgentEvent[]) => void;
  /** the run state must be rebuilt from scratch from exactly these events (restart / seek backwards) */
  onReplace: (events: AgentEvent[]) => void;
  onSnapshot: (snap: ReplaySnapshot) => void;
}

export function parseSpeed(raw: string | null | undefined, fallback = DEFAULT_SPEED): number {
  if (raw == null || raw === "") return fallback;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) return fallback;
  return Math.min(n, 50);
}

/** Replay names are file names under /public/replay: keep them boring so a query param cannot walk the path. */
export function safeReplayName(raw: string | null | undefined): string | null {
  if (!raw) return null;
  return /^[A-Za-z0-9_-]{1,64}$/.test(raw) ? raw : null;
}

export function parseJsonl(text: string): AgentEvent[] {
  const events: AgentEvent[] = [];
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const ev = JSON.parse(trimmed) as AgentEvent;
      if (ev && typeof ev.seq === "number" && typeof ev.type === "string") events.push(ev);
    } catch {
      // a truncated last line in a run that is still being recorded is not worth failing the replay for
    }
  }
  return events.sort((a, b) => a.seq - b.seq);
}

export async function loadReplay(name: string, signal?: AbortSignal): Promise<AgentEvent[]> {
  const res = await fetch(`/replay/${encodeURIComponent(name)}.jsonl`, { signal, cache: "no-cache" });
  if (!res.ok) throw new Error(`no recorded run named “${name}” (HTTP ${res.status})`);
  const events = parseJsonl(await res.text());
  if (!events.length) throw new Error(`recorded run “${name}” is empty`);
  return events;
}

export function gapMs(prev: AgentEvent | undefined, next: AgentEvent, speed: number): number {
  if (!prev || speed <= 0) return 0;
  const gap = Math.min(Math.max(next.ts - prev.ts, 0), MAX_GAP_S);
  return (gap * 1000) / speed;
}

export class ReplayController {
  private index = 0;
  private playing = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private disposed = false;

  constructor(private readonly events: AgentEvent[], private readonly sink: ReplaySink, private speed: number = DEFAULT_SPEED) {}

  snapshot(): ReplaySnapshot {
    return { index: this.index, total: this.events.length, playing: this.playing, speed: this.speed, done: this.index >= this.events.length };
  }

  play(): void {
    if (this.disposed || this.playing) return;
    if (this.index >= this.events.length) { this.restart(); return; }
    this.playing = true;
    this.publish();
    this.schedule();
  }

  pause(): void {
    this.playing = false;
    this.clear();
    this.publish();
  }

  toggle(): void {
    if (this.playing) this.pause(); else this.play();
  }

  restart(): void {
    this.clear();
    this.index = 0;
    this.sink.onReplace([]);
    this.playing = false;
    this.play();
  }

  /** Emit one event while paused (arrow-key stepping during a demo). */
  step(): void {
    if (this.disposed || this.index >= this.events.length) return;
    this.playing = false;
    this.clear();
    this.sink.onEvents([this.events[this.index++]]);
    this.publish();
  }

  skipToEnd(): void {
    this.seek(this.events.length);
  }

  /** Jump so that exactly `count` events have been applied. */
  seek(count: number): void {
    if (this.disposed) return;
    const target = Math.max(0, Math.min(this.events.length, Math.round(count)));
    this.clear();
    if (target >= this.index) this.sink.onEvents(this.events.slice(this.index, target));
    else this.sink.onReplace(this.events.slice(0, target));
    this.index = target;
    if (this.index >= this.events.length) this.playing = false;
    this.publish();
    if (this.playing) this.schedule();
  }

  setSpeed(speed: number): void {
    this.speed = speed;
    this.publish();
    if (this.playing) { this.clear(); this.schedule(); }
  }

  dispose(): void {
    this.disposed = true;
    this.playing = false;
    this.clear();
  }

  private clear(): void {
    if (this.timer != null) { clearTimeout(this.timer); this.timer = null; }
  }

  private publish(): void {
    if (!this.disposed) this.sink.onSnapshot(this.snapshot());
  }

  private schedule(): void {
    if (this.disposed || !this.playing) return;
    if (this.index >= this.events.length) { this.playing = false; this.publish(); return; }
    const delay = gapMs(this.events[this.index - 1], this.events[this.index], this.speed);
    this.timer = setTimeout(() => this.tick(), delay);
  }

  private tick(): void {
    this.timer = null;
    if (this.disposed || !this.playing) return;
    // Emit the due event plus anything that follows within a frame of it, as one batch (one React render).
    const batch: AgentEvent[] = [this.events[this.index++]];
    while (this.index < this.events.length && gapMs(this.events[this.index - 1], this.events[this.index], this.speed) < 16) {
      batch.push(this.events[this.index++]);
    }
    this.sink.onEvents(batch);
    this.publish();
    this.schedule();
  }
}
