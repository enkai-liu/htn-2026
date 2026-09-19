"use client";
import clsx from "clsx";
import { FileText, Lightbulb, Map as MapIcon, MessagesSquare, Users, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useSelectedLayoutSegment } from "next/navigation";
import type { Phase } from "@/lib/types";
import { useRun, type RunSegment } from "./RunProvider";

const TABS: { segment: RunSegment; label: string; icon: LucideIcon }[] = [
  { segment: "", label: "Map", icon: MapIcon },
  { segment: "debate", label: "Debate", icon: MessagesSquare },
  { segment: "coach", label: "Coach", icon: Lightbulb },
  { segment: "report", label: "Report", icon: FileText },
  { segment: "swarm", label: "Swarm", icon: Users },
];

/** Where the swarm is working right now: that tab gets a small pulse instead of the page switching under you. */
function segmentForPhase(phase: Phase | null): RunSegment | null {
  switch (phase) {
    case "scout": case "resolve": return "";
    case "debate": case "verify": case "score": return "debate";
    case "mutate": case "act": return "coach";
    default: return null;
  }
}

export function TabBar() {
  const { run, streaming, hrefFor } = useRun();
  const { state } = run;
  const active = (useSelectedLayoutSegment() ?? "") as RunSegment;
  const busy = streaming && !state.finished ? segmentForPhase(state.phase) : null;
  const counts: Partial<Record<RunSegment, number>> = { debate: state.claimOrder.length, coach: state.mutationOrder.length };

  return (
    <nav className="flex flex-none items-stretch justify-center gap-1 sm:gap-3" aria-label="Run pages">
      {TABS.map(({ segment, label, icon: Icon }) => {
        const on = active === segment;
        const n = counts[segment];
        return (
          <Link
            key={segment}
            href={hrefFor(segment)}
            aria-current={on ? "page" : undefined}
            className={clsx("relative flex w-[64px] flex-col items-center gap-1 rounded-xl py-1.5 text-[11.5px] transition-colors sm:w-[76px]", on ? "text-amber" : "text-mute hover:text-bone")}
          >
            <span className="relative">
              <Icon size={21} strokeWidth={on ? 2 : 1.6} />
              {!!n && <span className="absolute -right-3.5 -top-1.5 min-w-[16px] rounded-full bg-ink-800 px-1 text-center font-mono text-[9px] leading-[14px] text-bone-dim">{n}</span>}
              {segment === "report" && state.report && <span className="absolute -right-1.5 -top-0.5 size-[6px] rounded-full bg-teal" />}
              {busy === segment && !on && <span className="absolute -left-1.5 -top-0.5 size-[6px] animate-beacon rounded-full bg-amber text-amber" />}
              {segment === "swarm" && streaming && !state.finished && <span className="absolute -right-1.5 -top-0.5 size-[6px] animate-beacon rounded-full bg-vermilion text-vermilion" />}
            </span>
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
