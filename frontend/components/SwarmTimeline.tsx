"use client";
// The swarm at work: roster with live status, the latest agent-to-agent message, and a chronological log.
// Collaboration beats (critic sends a scout back out, a jury split forces a re-query, a failed source is retried)
// are boxed and flashed so they cannot be missed from the back of a room.
import clsx from "clsx";
import { ArrowRight, CornerDownRight, RotateCcw, Split, TriangleAlert, Wrench } from "lucide-react";
import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { agentColor, ROLE_BLURB } from "@/lib/agents";
import { PHASE_LABEL, PHASES } from "@/lib/eventTypes";
import { fmtT, shortModel } from "@/lib/format";
import type { AgentInfo, RunState, TimelineRow } from "@/lib/runReducer";
import type { Phase } from "@/lib/types";
import { SimulatedTag } from "./ui";

const STATUS_COLOR: Record<AgentInfo["status"], string> = {
  idle: "var(--color-faint)",
  active: "var(--color-amber)",
  done: "var(--color-teal)",
  failed: "var(--color-vermilion)",
  recovered: "var(--color-amber)",
  skipped: "var(--color-faint)",
};

const STATUS_LABEL: Record<AgentInfo["status"], string> = {
  idle: "waiting",
  active: "working",
  done: "done",
  failed: "failed",
  recovered: "failed, then recovered on retry",
  skipped: "skipped",
};

function AgentName({ agent, className }: { agent: string; className?: string }) {
  return <span className={clsx("font-mono", className)} style={{ color: agentColor(agent) }}>{agent}</span>;
}

function RosterChip({ info }: { info: AgentInfo }) {
  const skipped = info.status === "skipped";
  const title = skipped ? `Skipped: ${info.why}` : [info.purpose, ROLE_BLURB[info.agent], info.summary && `→ ${info.summary}`, info.model && `model: ${info.model}`].filter(Boolean).join("\n");
  return (
    <li className={clsx("relative flex min-w-0 items-center gap-1.5 overflow-hidden px-1.5 py-[3px]", skipped && "col-span-2 opacity-60")} title={title}>
      {/* ping overlay: remounts (and so replays) whenever this agent sends or receives a message */}
      {info.lastPingSeq > 0 && <span key={info.lastPingSeq} className="pointer-events-none absolute inset-0 animate-flash" />}
      <span
        className={clsx("relative size-[7px] flex-none rounded-full", info.status === "active" && "animate-beacon", info.status === "idle" || skipped ? "border border-current bg-transparent" : "bg-current")}
        style={{ color: STATUS_COLOR[info.status] }}
        aria-label={STATUS_LABEL[info.status]}
      />
      <span className={clsx("relative truncate font-mono text-[10.5px]", skipped ? "text-mute line-through" : info.status === "idle" ? "text-mute" : "text-bone")}>{info.agent}</span>
      {info.requeried > 0 && (
        <span className="relative flex flex-none items-center gap-0.5 font-mono text-[9px] text-amber" title={`sent back out ${info.requeried}×`}>
          <RotateCcw size={9} />{info.requeried}
        </span>
      )}
      {info.status === "recovered" && <span className="relative flex-none font-mono text-[9px] uppercase tracking-wider text-amber">retried</span>}
      {info.status === "failed" && <span className="relative flex-none font-mono text-[9px] uppercase tracking-wider text-vermilion">failed</span>}
      {skipped && <span className="relative truncate font-display text-[12.5px] italic text-mute">skipped: {info.why}</span>}
    </li>
  );
}

function PhaseRail({ phase, finished }: { phase: Phase | null; finished: boolean }) {
  const current = phase ? PHASES.indexOf(phase) : -1;
  return (
    <ol className="flex items-stretch gap-[3px]" aria-label="Run phases">
      {PHASES.map((p, i) => {
        const state = finished || i < current ? "past" : i === current ? "now" : "next";
        return (
          <li key={p} className="min-w-0 flex-1" title={PHASE_LABEL[p]}>
            <div className={clsx("h-[3px] transition-colors duration-500", state === "past" ? "bg-teal/70" : state === "now" ? "bg-amber" : "bg-ink-600")} />
            <div className={clsx("mt-1 truncate font-mono text-[8.5px] uppercase tracking-[0.08em]", state === "now" ? "text-amber" : state === "past" ? "text-mute" : "text-faint")}>{p}</div>
          </li>
        );
      })}
    </ol>
  );
}

const TONE_TEXT: Record<TimelineRow["tone"], string> = {
  default: "text-bone",
  muted: "text-bone-dim",
  accent: "text-bone",
  good: "text-teal",
  warn: "text-amber",
  danger: "text-vermilion",
  teal: "text-teal",
};

const EMPHASIS_STYLE: Record<NonNullable<TimelineRow["emphasis"]>, { border: string; flash: string; icon: React.ReactNode }> = {
  message: { border: "border-line-strong", flash: "var(--color-src-devpost)", icon: <ArrowRight size={11} /> },
  replan: { border: "border-amber/50", flash: "var(--color-amber)", icon: <RotateCcw size={11} /> },
  requery: { border: "border-amber/70", flash: "var(--color-amber)", icon: <RotateCcw size={12} /> },
  "jury-split": { border: "border-amber/70", flash: "var(--color-amber)", icon: <Split size={12} /> },
  failure: { border: "border-vermilion/60", flash: "var(--color-vermilion)", icon: <TriangleAlert size={12} /> },
};

const Row = memo(function Row({ row }: { row: TimelineRow }) {
  if (row.sub) {
    const isResult = row.tag === "result";
    return (
      <li className="flex animate-rise items-baseline gap-1.5 py-[2px] pl-[46px] pr-2 font-mono text-[10.5px] leading-snug text-mute">
        {isResult ? <CornerDownRight size={10} className="flex-none translate-y-[1px] text-faint" /> : <Wrench size={9} className="flex-none translate-y-[1px] text-faint" />}
        <span className="min-w-0">
          <span className={isResult ? "text-bone-dim" : "text-mute"}>{isResult ? row.detail || row.title : row.title}</span>
          {!isResult && row.detail && <span className="text-faint"> ({row.detail})</span>}
          {isResult && typeof row.count === "number" && (
            <span className={clsx("ml-1.5", row.count === 0 ? "text-teal" : "text-amber")}>{row.count === 0 ? "0 hits: empty" : `${row.count} hit${row.count === 1 ? "" : "s"}`}</span>
          )}
        </span>
      </li>
    );
  }

  const emph = row.emphasis ? EMPHASIS_STYLE[row.emphasis] : null;
  const big = row.emphasis === "requery" || row.emphasis === "jury-split";
  const body = (
    <>
      {big && (
        <div className={clsx("mb-1.5 flex items-center gap-1.5 font-mono text-[9.5px] font-medium uppercase leading-none tracking-[0.14em]", TONE_TEXT[row.tone])}>
          {emph?.icon}
          {row.tag}
        </div>
      )}
      <div className="flex min-w-0 items-center gap-1.5 text-[10.5px] leading-none">
        <AgentName agent={row.agent} className="truncate" />
        {row.to && (
          <>
            <ArrowRight size={10} className="flex-none text-mute" />
            <AgentName agent={row.to} className="truncate" />
          </>
        )}
        {row.tag && !big && (
          <span className={clsx("ml-auto flex flex-none items-center gap-1 font-mono text-[9px] uppercase tracking-[0.12em]", row.emphasis === "failure" || row.emphasis === "replan" ? TONE_TEXT[row.tone] : "text-mute")}>
            {emph && (row.emphasis === "failure" || row.emphasis === "replan") ? emph.icon : null}
            {row.tag}
          </span>
        )}
      </div>
      <div className={clsx("mt-[3px] text-[12.5px] leading-snug", big ? "font-display text-[15px] italic text-bone" : TONE_TEXT[row.tone], row.simulated && row.type === "claim.proposed" && "line-through decoration-vermilion/70")}>
        {row.title}
      </div>
      {row.detail && <div className={clsx("mt-0.5 text-[11px] leading-snug", big ? "font-mono text-amber/90" : "text-mute")}>{row.detail}</div>}
      {row.simulated && <SimulatedTag className="mt-1" />}
      {row.model && <div className="mt-0.5 font-mono text-[9px] text-faint">{shortModel(row.model)}{row.latency_ms ? ` · ${(row.latency_ms / 1000).toFixed(1)}s` : ""}</div>}
    </>
  );

  return (
    <li className="flex animate-rise gap-1.5 py-[5px] pr-2">
      <span className="w-[40px] flex-none pt-[1px] text-right font-mono text-[9px] leading-[14px] text-faint">{fmtT(row.t)}</span>
      {emph ? (
        <div className={clsx("min-w-0 flex-1 animate-flash border-l-2 border-y border-r px-2 py-1.5", emph.border, big && "bg-amber/[0.06]", row.emphasis === "failure" && "bg-vermilion/[0.06]")} style={{ ["--flash" as string]: emph.flash }}>
          {body}
        </div>
      ) : (
        <div className="min-w-0 flex-1 border-l border-line pl-2">{body}</div>
      )}
    </li>
  );
});

export function SwarmTimeline({ state, streaming }: { state: RunState; streaming: boolean }) {
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const [detached, setDetached] = useState(false);

  // forward-only phase dividers: async side-channels (the early voice scan) must not reshuffle the story
  const items = useMemo(() => {
    const out: ({ kind: "phase"; phase: Phase; t: number } | { kind: "row"; row: TimelineRow })[] = [];
    let maxPhase = -1;
    for (const row of state.timeline) {
      const idx = PHASES.indexOf(row.phase);
      if (idx > maxPhase && row.type !== "voice.result") {
        maxPhase = idx;
        out.push({ kind: "phase", phase: row.phase, t: row.t });
      }
      out.push({ kind: "row", row });
    }
    return out;
  }, [state.timeline]);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [items.length, state.lastSeq]);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const onScroll = () => {
      const near = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
      stick.current = near;
      setDetached(!near);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  const lastMessage = state.messages[state.messages.length - 1];
  const lastRequery = state.requeries[state.requeries.length - 1];
  const ticker = lastRequery && (!lastMessage || lastRequery.seq >= lastMessage.seq - 1)
    ? { seq: lastRequery.seq, from: lastRequery.from, to: lastRequery.to, type: lastRequery.fromJurySplit ? "JURY SPLIT → RE-QUERY" : "SENT BACK OUT", text: lastRequery.reason, hot: true }
    : lastMessage ? { seq: lastMessage.seq, from: lastMessage.from, to: lastMessage.to, type: lastMessage.msg_type, text: lastMessage.summary, hot: lastMessage.msg_type === "REPLAN" } : null;

  const working = state.roster.order.filter((a) => state.roster.agents[a].status === "active").length;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex-none border-b border-line px-3 pb-2 pt-2.5">
        <PhaseRail phase={state.phase} finished={state.finished} />
      </div>

      <div className="flex-none border-b border-line px-1.5 py-1.5">
        {state.roster.order.length === 0 ? (
          <div className="px-1.5 py-1 font-mono text-[10.5px] text-faint">The conductor has not formed a team yet.</div>
        ) : (
          <ul className="grid grid-cols-2 gap-x-1">
            {state.roster.order.map((a) => <RosterChip key={a} info={state.roster.agents[a]} />)}
          </ul>
        )}
      </div>

      <div className="flex h-[46px] flex-none items-center border-b border-line px-3">
        {ticker ? (
          <div key={ticker.seq} className="min-w-0 animate-rise">
            <div className="flex items-center gap-1.5 text-[10.5px] leading-none">
              <AgentName agent={ticker.from} />
              <ArrowRight size={11} className={ticker.hot ? "text-amber" : "text-mute"} />
              <AgentName agent={ticker.to} />
              <span className={clsx("ml-1 font-mono text-[9px] uppercase tracking-[0.12em]", ticker.hot ? "text-amber" : "text-mute")}>{ticker.type}</span>
            </div>
            <div className="mt-1 truncate text-[11.5px] leading-none text-bone-dim">{ticker.text}</div>
          </div>
        ) : (
          <span className="font-mono text-[10.5px] text-faint">No agent-to-agent messages yet.</span>
        )}
      </div>

      <div className="relative min-h-0 flex-1">
        <div ref={scroller} className="h-full overflow-y-auto overscroll-contain pb-3 pl-1">
          <ol>
            {items.map((it) =>
              it.kind === "phase" ? (
                <li key={`p:${it.phase}`} className="sticky top-0 z-[1] flex items-center gap-2 bg-ink-850/95 py-1.5 pl-[46px] pr-2 backdrop-blur-sm">
                  <span className="font-mono text-[9.5px] uppercase tracking-[0.24em] text-amber">{PHASE_LABEL[it.phase]}</span>
                  <span className="h-px flex-1 bg-line-strong" />
                  <span className="font-mono text-[9px] text-faint">{fmtT(it.t)}</span>
                </li>
              ) : (
                <Row key={`${it.row.seq}:${it.row.type}`} row={it.row} />
              ),
            )}
          </ol>
          {streaming && state.timeline.length > 0 && (
            <div className="flex items-center gap-2 py-2 pl-[46px] font-mono text-[10px] text-faint">
              <span className="size-1.5 animate-pulse rounded-full bg-amber" />
              {working > 0 ? `${working} agent${working === 1 ? "" : "s"} working` : "listening"}
            </div>
          )}
        </div>
        {detached && (
          <button
            type="button"
            className="btn btn-sm absolute bottom-2 right-3 bg-ink-800"
            onClick={() => { const el = scroller.current; if (el) { stick.current = true; el.scrollTo({ top: el.scrollHeight, behavior: "smooth" }); } }}
          >
            Jump to latest
          </button>
        )}
      </div>
    </div>
  );
}
