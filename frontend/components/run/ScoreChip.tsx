"use client";
// The headline, as small as the reference's "85 pts". Click for the three axes behind it.
// Voice is deliberately not in here: AI-probability is its own axis and lives on the Report page.
import clsx from "clsx";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
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

  const abstain = !!scores?.abstain?.active;
  const headline = abstain ? null : scores?.headline ?? null;

  return (
    <div ref={ref} className="relative flex-none">
      <button
        type="button"
        onClick={() => { setOpenedAt(pathname); setOpen(!visible); }}
        aria-expanded={visible}
        className={clsx("flex items-baseline gap-1.5 rounded-full border px-3.5 py-1 transition-colors", visible ? "border-line-strong bg-ink-900" : "border-transparent hover:border-line")}
        title="Originality: crowding, facet rarity and LLM-predictability"
      >
        <span className={clsx("font-display text-[24px] leading-none tabular-nums", headline == null ? "text-faint" : "text-bone")}>{headline == null ? "–" : Math.round(headline)}</span>
        <span className="text-[12.5px] text-mute">{abstain ? "abstained" : headline != null && scores?.band != null ? `± ${scores.band} original` : "original"}</span>
      </button>
      {visible && (
        <div className="absolute right-0 top-[calc(100%+8px)] z-40 w-[min(660px,calc(100vw-32px))] animate-rise overflow-hidden rounded-2xl border border-line bg-ink-900 shadow-[0_18px_50px_rgb(0_0_0/0.12)]">
          <div className="h-[150px]"><AxisGauges scores={scores} /></div>
          <p className="border-t border-line px-3 py-2 text-[12px] text-mute">Voice (GPTZero) is scored separately and never moves this number. See the Report page.</p>
        </div>
      )}
    </div>
  );
}
