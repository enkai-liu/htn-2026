"use client";
// Spend, as a pill: the figure on the face, the "right-sized model per role" receipt underneath it. This is the
// whole of what the Swarm page used to say about cost, back in the header where the meter has always lived.
import clsx from "clsx";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { fmtTokens, fmtUsd } from "@/lib/format";
import type { RunState } from "@/lib/runReducer";
import { selectSpend } from "@/lib/selectors";
import { CostTable } from "../CostMeter";

export function SpendPill({ state }: { state: RunState }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const [openedAt, setOpenedAt] = useState(pathname);
  // a popover left open would otherwise follow you to the next tab
  const visible = open && openedAt === pathname;
  const spend = selectSpend(state);

  useEffect(() => {
    if (!visible) return;
    const onDown = (e: PointerEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("pointerdown", onDown); window.removeEventListener("keydown", onKey); };
  }, [visible]);

  return (
    <div ref={ref} className="relative hidden flex-none sm:block">
      <button
        type="button"
        onClick={() => { setOpenedAt(pathname); setOpen(!visible); }}
        aria-expanded={visible}
        className={clsx("flex h-9 items-center gap-1.5 rounded-full border bg-ink-900 px-3.5 text-[12.5px] leading-none tabular-nums transition-colors", visible ? "border-line-strong" : "border-line hover:border-line-strong", spend.degraded ? "text-vermilion" : "text-mute")}
        title={spend.degraded ? "Budget pressure: the conductor degraded the run. Which model did what, inside." : "Spend so far. Which model did what, inside."}
      >
        {spend.degraded && <span className="size-[6px] rounded-full bg-vermilion" />}
        <span className={spend.degraded ? undefined : "text-bone"}>{fmtUsd(spend.usd)}</span>
        <span>· {spend.calls} calls</span>
        {spend.degraded && <span>· degraded</span>}
      </button>

      {visible && (
        <div className="absolute right-0 top-[calc(100%+8px)] z-40 w-[min(520px,calc(100vw-32px))] animate-rise overflow-hidden rounded-2xl border border-line bg-ink-900 p-4 shadow-[0_18px_50px_rgb(0_0_0/0.12)]">
          <div className="mb-3 flex items-baseline gap-3">
            <span className="font-display text-[30px] leading-none text-bone">{fmtUsd(spend.usd)}</span>
            <span className="text-[12.5px] text-mute">{spend.calls} calls · {fmtTokens(spend.tokens)} tokens · {Math.round(spend.elapsed)}s</span>
          </div>
          {spend.degraded && <p className="mb-3 rounded-lg bg-vermilion/10 px-2.5 py-1.5 text-[12.5px] text-vermilion">Degraded: the conductor cut scope to stay inside the budget.</p>}
          <CostTable state={state} />
        </div>
      )}
    </div>
  );
}
