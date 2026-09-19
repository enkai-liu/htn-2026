"use client";
// The hand-off at a glance: critic -> advocate -> jury -> verifier -> report, with the two back-edges that send a scout
// out again (the critic asking for more, and the conductor breaking a jury split).
import clsx from "clsx";
import { Check, ChevronDown, ChevronRight, X } from "lucide-react";
import { ROLE_BLURB, agentColor } from "@/lib/agents";
import type { BackEdge, DebateBoard, Stage } from "@/lib/debate";
import { shortModel } from "@/lib/format";
import { JUROR_COLORS } from "../DebateThread";

// Geometry shared by the nodes (px) and the edge overlay (viewBox units: x in % of the width, y in px).
const NODE_H = 66;
const GAP_H = 34;
const SCOUT_H = 40;
const H = NODE_H + GAP_H + SCOUT_H;
const SCOUT_TOP = NODE_H + GAP_H;
// stage i is centred at 10 + 20·i %; both back-edges land on top of the scouts node, under the advocate
const EDGES = { critic: { from: 10, to: 26 }, jury: { from: 50, to: 34 } };

function StatusDot({ status, color }: { status: Stage["status"]; color: string }) {
  if (status === "done") return <Check size={12} strokeWidth={2.5} style={{ color }} aria-label="done" />;
  if (status === "failed") return <X size={12} strokeWidth={2.5} className="text-vermilion" aria-label="failed" />;
  if (status === "active") return <span className="size-[8px] animate-beacon rounded-full" style={{ background: color, color }} aria-label="working" />;
  return <span className="size-[8px] rounded-full border border-line-strong" aria-label="waiting" />;
}

function StageNode({ stage, next, jurors }: { stage: Stage; next?: Stage; jurors: string[] }) {
  const color = agentColor(stage.id);
  const idle = stage.status === "idle";
  const sub = stage.id === "judge" ? null : stage.id === "verifier" ? "no LLM · veto" : shortModel(stage.model);
  return (
    <div className="px-1 sm:px-3.5">
      <div
        className={clsx("relative flex flex-col items-center justify-center rounded-xl border bg-ink-900 px-0.5 text-center sm:px-1.5 transition-colors duration-500", idle && "border-line")}
        style={{ height: NODE_H, borderColor: idle ? undefined : `color-mix(in srgb, ${color} ${stage.status === "active" ? 80 : 35}%, transparent)` }}
        title={ROLE_BLURB[stage.id]}
      >
        {/* phone width: the mark sits above the name so "Advocate" fits its node */}
        <div className="flex flex-col items-center gap-1 sm:flex-row sm:gap-1.5">
          <StatusDot status={stage.status} color={color} />
          <span className={clsx("text-[11px] font-medium sm:text-[13.5px]", idle && "opacity-55")} style={{ color }}>{stage.label}</span>
        </div>
        {stage.id === "judge" ? (
          <div className="mt-1 hidden items-center gap-1 sm:flex" title={jurors.length ? jurors.map(shortModel).join(" · ") : "one juror per model family"}>
            {(jurors.length ? jurors : [0, 1, 2]).map((j, i) => (
              <span key={i} className="size-[7px] rounded-full" style={{ background: jurors.length ? JUROR_COLORS[i % JUROR_COLORS.length] : "var(--color-ink-600)" }} />
            ))}
            <span className="ml-0.5 font-mono text-[9.5px] text-faint">blind</span>
          </div>
        ) : (
          sub && <div className="mt-0.5 hidden max-w-full truncate font-mono text-[9.5px] text-faint sm:block">{sub}</div>
        )}
        {stage.stat && <div key={stage.stat} className="mt-0.5 hidden max-w-full animate-rise truncate text-[11px] text-bone-dim sm:block">{stage.stat}</div>}

        {next && (
          <span className={clsx("absolute left-full top-1/2 h-px w-2 transition-colors duration-700 sm:w-7", next.status === "idle" ? "bg-line-strong" : "bg-bone-dim")} aria-hidden>
            <ChevronRight size={11} className={clsx("absolute -right-[2px] -top-[5.5px] hidden transition-colors duration-700 sm:block", next.status === "idle" ? "text-ink-500" : "text-bone-dim")} />
          </span>
        )}
      </div>
    </div>
  );
}

function BackEdgePath({ from, to, edge }: { from: number; to: number; edge: BackEdge }) {
  const fired = edge.count > 0;
  const d = `M ${from} ${NODE_H} C ${from} ${NODE_H + GAP_H * 0.7}, ${to} ${NODE_H + GAP_H * 0.2}, ${to} ${SCOUT_TOP - 7}`;
  return (
    // keyed by the latest re-query so the marching dashes replay every time a scout is sent back out
    <path
      key={edge.lastSeq}
      d={d}
      fill="none"
      vectorEffect="non-scaling-stroke"
      strokeWidth={fired ? 1.5 : 1}
      strokeDasharray="4 4"
      stroke={fired ? "var(--color-amber)" : "var(--color-line-strong)"}
      style={fired ? { animation: "dash 0.7s linear 5" } : undefined}
    />
  );
}

export function OrchestrationStrip({ board }: { board: DebateBoard }) {
  const { stages, scouts, funnel, jurors } = board;
  const sentBack = scouts.fromCritic.count + scouts.fromJury.count;
  const lastSeq = Math.max(scouts.fromCritic.lastSeq, scouts.fromJury.lastSeq);
  return (
    <div className="relative" style={{ height: H }} role="group" aria-label="Who hands what to whom in the debate">
      <svg className="pointer-events-none absolute inset-0 size-full" viewBox={`0 0 100 ${H}`} preserveAspectRatio="none" aria-hidden>
        <BackEdgePath {...EDGES.critic} edge={scouts.fromCritic} />
        <BackEdgePath {...EDGES.jury} edge={scouts.fromJury} />
      </svg>
      {([["critic", scouts.fromCritic], ["jury", scouts.fromJury]] as const).map(([k, edge]) => (
        <ChevronDown key={k} size={12} className={clsx("absolute -translate-x-1/2", edge.count ? "text-amber" : "text-ink-500")} style={{ left: `${EDGES[k].to}%`, top: SCOUT_TOP - 11 }} aria-hidden />
      ))}

      <div className="relative grid grid-cols-5">
        {stages.map((s, i) => <StageNode key={s.id} stage={s} next={stages[i + 1]} jurors={jurors} />)}
      </div>

      <div className="absolute w-[20%] -translate-x-1/2 px-1 sm:px-3.5" style={{ left: "30%", top: SCOUT_TOP }}>
        <div key={lastSeq} className={clsx("rounded-xl", lastSeq > 0 && "animate-flash")} style={{ ["--flash" as string]: "var(--color-amber)" }}>
          <div
            className={clsx("flex flex-col items-center justify-center rounded-xl border px-1.5 text-center transition-colors duration-500", sentBack ? "border-amber/50" : "border-dashed border-line-strong")}
            style={{ height: SCOUT_H }}
            title="Scouts are the only role that retrieves, so every request for more evidence loops back through them."
          >
            <div className="flex items-center gap-1.5">
              {scouts.status === "active" && <span className="size-[7px] animate-beacon rounded-full bg-amber text-amber" />}
              <span className={clsx("text-[12px] font-medium sm:text-[13px]", sentBack ? "text-amber" : "text-mute")}>Scouts</span>
            </div>
            <div className="hidden font-mono text-[9.5px] text-faint sm:block">{sentBack ? `sent back out ×${sentBack}` : "on call"}</div>
          </div>
        </div>
      </div>

      <p className="absolute bottom-0 right-1 max-w-[52%] text-right text-[12px] leading-snug text-mute sm:right-3.5 sm:text-[12.5px]">
        {funnel.proposed === 0 ? "Only verified claims reach the report." : (
          <>
            <span className="text-bone">{funnel.proposed}</span> {funnel.proposed === 1 ? "claim" : "claims"}
            {funnel.struck > 0 && <> · <span className="text-vermilion">{funnel.struck} struck</span></>}
            {funnel.pending > 0 ? <> · {funnel.pending} awaiting the verifier</> : <> · <span className="text-teal">{funnel.reachReport} reach the report</span></>}
          </>
        )}
      </p>
    </div>
  );
}
