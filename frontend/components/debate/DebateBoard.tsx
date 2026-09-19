"use client";
// The Debate page: the hand-off strip on top, then one case file per prior-art project instead of a feed in arrival order.
import { ArrowRight, RotateCcw } from "lucide-react";
import { useMemo } from "react";
import { agentColor } from "@/lib/agents";
import { selectDebateBoard } from "@/lib/debate";
import { fmtT } from "@/lib/format";
import type { RunState } from "@/lib/runReducer";
import { ClaimCard, STATUS } from "../DebateThread";
import { Chip, Empty } from "../ui";
import { CaseFile } from "./CaseFile";
import { OrchestrationStrip } from "./OrchestrationStrip";

const card = "overflow-hidden rounded-2xl border border-line bg-ink-900";

export function DebateBoard({ state, streaming }: { state: RunState; streaming: boolean }) {
  const board = useMemo(() => selectDebateBoard(state), [state]);
  const models = useMemo(() => Object.fromEntries(Object.values(state.roster.agents).map((a) => [a.agent, a.model])), [state.roster]);
  const freshest = streaming ? [...board.cases].sort((a, b) => b.lastSeq - a.lastSeq)[0]?.eid ?? null : null;
  const quiet = !board.cases.length && !board.distinctions.length && !board.loose.length;

  return (
    <div className="flex flex-col gap-3">
      <section className={`${card} px-2.5 py-4 sm:px-3`} aria-label="Orchestration">
        <OrchestrationStrip board={board} />
        {board.backEdges.length > 0 && (
          <ul className="mx-1.5 mt-3.5 flex flex-col gap-2 border-t border-line pt-3 sm:mx-3.5">
            {board.backEdges.map((rq) => (
              <li key={rq.seq} className="animate-rise text-[12.5px] leading-snug">
                <div className="flex flex-wrap items-center gap-x-1.5 font-mono text-[10.5px]">
                  <RotateCcw size={11} className="text-amber" />
                  <span style={{ color: agentColor(rq.from) }}>{rq.from}</span>
                  <ArrowRight size={11} className="text-amber" />
                  <span style={{ color: agentColor(rq.to) }}>{rq.to}</span>
                  {rq.facet && <Chip tone="amber">facet: {rq.facet}</Chip>}
                  <span className="ml-auto text-[9.5px] text-faint">{fmtT(rq.t)}</span>
                </div>
                <p className="mt-0.5 text-bone-dim">{rq.reason}{rq.query && <span className="text-mute"> · “{rq.query}”</span>}</p>
                {rq.result && <p className="mt-0.5 text-[11.5px] text-mute">↳ {rq.result}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>

      {quiet && <div className={card}><Empty>The critic has not made its case yet.</Empty></div>}

      {board.cases.map((c) => <CaseFile key={c.eid} c={c} evidence={state.evidence} models={models} fresh={c.eid === freshest} />)}

      {board.distinctions.length > 0 && (
        <section className={`${card} animate-rise px-4 py-3.5`} aria-labelledby="distinct-h">
          <h2 id="distinct-h" className="flex items-baseline gap-2">
            <span className="font-display text-[21px] text-bone">What holds against all of them</span>
            <span className="font-mono text-[9.5px] uppercase tracking-[0.16em]" style={{ color: agentColor("advocate") }}>advocate</span>
          </h2>
          <ul className="mt-2 flex flex-col gap-2">
            {board.distinctions.map((d) => (
              <li key={d.cid} className="flex items-start gap-3 border-l-2 pl-3" style={{ borderColor: agentColor(d.by) }}>
                <p className="min-w-0 flex-1 text-[13.5px] leading-snug text-bone-dim">{d.text}</p>
                <Chip key={d.status} tone={STATUS[d.status]?.tone} flip title="An absence cannot be quoted, so a difference stays a lead unless the verifier can back it.">{STATUS[d.status]?.label ?? d.status}</Chip>
              </li>
            ))}
          </ul>
        </section>
      )}

      {board.loose.length > 0 && (
        <div className={`${card} flex flex-col gap-2 p-3`}>
          {board.loose.map((claim) => <ClaimCard key={claim.cid} claim={claim} evidence={claim.evidence.map((id) => state.evidence[id]).filter(Boolean)} />)}
        </div>
      )}
    </div>
  );
}
