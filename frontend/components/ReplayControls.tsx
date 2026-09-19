"use client";
import clsx from "clsx";
import { Pause, Play, RotateCcw, SkipForward, StepForward } from "lucide-react";
import { SPEED_STEPS, type ReplaySnapshot } from "@/lib/replay";
import type { RunControls } from "@/lib/useRunEvents";

export function ReplayControls({ controls, snapshot }: { controls: RunControls; snapshot: ReplaySnapshot | null }) {
  const total = snapshot?.total ?? 0;
  const index = snapshot?.index ?? 0;
  const pct = total ? (index / total) * 100 : 0;
  const speed = snapshot?.speed ?? 1.5;
  const speeds: number[] = (SPEED_STEPS as readonly number[]).includes(speed) ? [...SPEED_STEPS] : [...SPEED_STEPS, speed].sort((a, b) => a - b);

  return (
    <div className="flex items-center gap-1.5">
      <button type="button" className="btn btn-sm btn-icon" onClick={controls.restart} title="Restart (R)" aria-label="Restart replay"><RotateCcw size={12} /></button>
      <button type="button" className={clsx("btn btn-sm btn-icon", snapshot?.playing && "border-amber/60 text-amber")} onClick={controls.toggle} title="Play / pause (Space)" aria-label={snapshot?.playing ? "Pause replay" : "Play replay"}>
        {snapshot?.playing ? <Pause size={12} /> : <Play size={12} />}
      </button>
      <button type="button" className="btn btn-sm btn-icon" onClick={controls.step} title="Step one event (→)" aria-label="Step one event"><StepForward size={12} /></button>
      <button type="button" className="btn btn-sm btn-icon" onClick={controls.skipToEnd} title="Skip to the end (E)" aria-label="Skip to end"><SkipForward size={12} /></button>

      {/* scrubber: click or drag to any event; going backwards re-folds the run from scratch */}
      <label className="relative mx-1 hidden h-[26px] w-[150px] items-center lg:flex" title={`event ${index} of ${total}`}>
        <span className="sr-only">Replay position</span>
        <span className="pointer-events-none absolute inset-x-0 top-1/2 h-[3px] -translate-y-1/2 bg-ink-600" />
        <span className="pointer-events-none absolute left-0 top-1/2 h-[3px] -translate-y-1/2 bg-amber transition-[width] duration-150" style={{ width: `${pct}%` }} />
        <input
          type="range" min={0} max={total} step={1} value={index}
          onChange={(e) => controls.seek(Number(e.target.value))}
          className="relative z-[1] h-full w-full cursor-pointer appearance-none bg-transparent opacity-0"
        />
      </label>
      <span className="hidden w-[52px] font-mono text-[9.5px] tabular-nums text-mute lg:inline">{index}/{total}</span>

      <select
        value={speed}
        onChange={(e) => controls.setSpeed(Number(e.target.value))}
        className="h-[26px] cursor-pointer border border-line-strong bg-ink-850 px-1.5 font-mono text-[10px] text-bone-dim outline-none hover:border-bone-dim"
        aria-label="Replay speed"
        title="Replay speed (also ?speed= in the URL)"
      >
        {speeds.map((s) => <option key={s} value={s}>{s}×</option>)}
      </select>
    </div>
  );
}
