"use client";
// What the actuator proposes. Anything that reaches outside the app needs the user's click, and in replay
// mode nothing is sent at all: the buttons explain themselves instead of calling the API.
import clsx from "clsx";
import { Check, DatabaseZap, LoaderCircle, PenLine, Radar, TriangleAlert } from "lucide-react";
import type { ActionState } from "@/lib/runReducer";

const ICON: Record<string, React.ReactNode> = {
  arm_watch: <Radar size={13} />,
  draft_pitch: <PenLine size={13} />,
  writeback: <DatabaseZap size={13} />,
};

const SHORT: Record<string, string> = { arm_watch: "Arm watch", draft_pitch: "Draft pitch", writeback: "Write back" };

export function ActionBar({ actions, busy, onAct }: { actions: ActionState[]; busy: string | null; onAct: (action: ActionState) => void }) {
  if (!actions.length) return null;
  return (
    <div className="flex-none animate-rise border-t border-line bg-ink-900/60 px-3 py-2">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="label">Actions</span>
        <span className="truncate font-mono text-[9px] text-faint">nothing leaves the app without your click</span>
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        {actions.map((a) => {
          const done = a.status === "done";
          const failed = a.status === "failed";
          return (
            <button
              key={a.action}
              type="button"
              className={clsx("btn h-auto min-h-[34px] flex-col gap-0.5 px-2 py-1.5 normal-case tracking-normal", done && "btn-teal", failed && "border-vermilion/60 text-vermilion")}
              onClick={() => onAct(a)}
              disabled={busy === a.action}
              title={a.detail ? `${a.label}\n${a.detail}` : a.label}
            >
              <span className="flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.1em]">
                {busy === a.action ? <LoaderCircle size={13} className="animate-spin" /> : done ? <Check size={13} /> : failed ? <TriangleAlert size={13} /> : ICON[a.action]}
                {SHORT[a.action] ?? a.action.replace(/_/g, " ")}
              </span>
              <span className="line-clamp-1 text-[10px] leading-tight text-mute">{done || failed ? a.detail ?? a.status : a.requires_click ? "needs your click" : "safe to run"}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
