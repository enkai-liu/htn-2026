"use client";
// The headline, as small as the reference's "85 pts". Click for the three axes behind it.
// Voice is deliberately not in here: AI-probability is its own axis and lives on the Report page.
import clsx from "clsx";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { headlineParts } from "@/lib/headline";
import type { Scores } from "@/lib/types";
import { AxisGauges } from "../AxisGauges";

export function ScoreChip({ scores }: { scores: Scores | null }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const [openedAt, setOpenedAt] = useState(pathname);
  // a popover left open would otherwise follow you to the next tab
  const visible = open && openedAt === pathname;

  useEffect(() => {
    if (!visible) return;
    const onDown = (e: PointerEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("pointerdown", onDown); window.removeEventListener("keydown", onKey); };
  }, [visible]);

  // one reading of the headline for the whole app: see lib/headline.ts
  const { value: headline, suffix, interval, abstain } = headlineParts(scores);

  return (
    <div ref={ref} className="relative flex-none">
      <button
        type="button"
        onClick={() => { setOpenedAt(pathname); setOpen(!visible); }}
        aria-expanded={visible}
        className={clsx("flex h-9 items-center gap-1.5 rounded-full border bg-ink-900 px-3.5 transition-colors", visible ? "border-line-strong" : "border-line hover:border-line-strong")}
        title="Percentile rank against real hackathon projects scored the same way. Click for the axes behind it."
      >
        <span className={clsx("font-display text-[24px] leading-none tabular-nums", headline == null ? "text-faint" : "text-bone")}>{headline == null ? "–" : `${Math.round(headline)}${suffix}`}</span>
        <span className="text-[12.5px] leading-none text-mute">{abstain ? "abstained" : interval}</span>
      </button>
      {visible && (
        <div className="absolute right-0 top-[calc(100%+8px)] z-40 w-[min(660px,calc(100vw-32px))] animate-rise overflow-hidden rounded-2xl border border-line bg-ink-900 shadow-[0_18px_50px_rgb(0_0_0/0.12)]">
          <div className="h-[150px]"><AxisGauges scores={scores} /></div>
          <p className="border-t border-line px-3 py-2 text-[12px] text-mute">Voice (GPTZero) is scored separately, on the Report page.</p>
        </div>
      )}
    </div>
  );
}
