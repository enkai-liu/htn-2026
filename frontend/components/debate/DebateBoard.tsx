"use client";
// Lead with compact case previews; keep the investigation mechanics available on demand.
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
import styles from "./debate.module.css";

const card = styles.card;

export function DebateBoard({ state, streaming }: { state: RunState; streaming: boolean }) {
  const board = useMemo(() => selectDebateBoard(state), [state]);
  const models = useMemo(() => Object.fromEntries(Object.values(state.roster.agents).map((a) => [a.agent, a.model])), [state.roster]);
  const freshest = streaming ? [...board.cases].sort((a, b) => b.lastSeq - a.lastSeq)[0]?.eid ?? null : null;
  const quiet = !board.cases.length && !board.distinctions.length && !board.loose.length;

  return (
    <div className={styles.board}>
      <div className={styles.cases}>
        <details className={styles.processDetails}>
          <summary>How the debate was run</summary>
          <div className={styles.processBody}>
            <OrchestrationStrip board={board} />
            {board.backEdges.length > 0 && (
              <details className={styles.research}>
                <summary>Research follow-ups <span>{board.backEdges.length}</span></summary>
                <ul className="mt-4 flex flex-col gap-5">
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
            </details>
          )}
          </div>
        </details>

        <div className={styles.sectionHeader}>
          <h2>{board.cases.length} {board.cases.length === 1 ? "comparison" : "comparisons"}</h2>
          {streaming && <span>Debate in progress</span>}
        </div>

        {quiet && <div className={card}><Empty>The critic has not made its case yet.</Empty></div>}

        {board.cases.map((c) => <CaseFile key={c.eid} c={c} evidence={state.evidence} models={models} fresh={c.eid === freshest} />)}

        {board.distinctions.length > 0 && (
          <details className={styles.processDetails}>
            <summary>What sets the idea apart <span>({board.distinctions.length})</span></summary>
            <ul className="mt-2 flex flex-col gap-2">
              {board.distinctions.map((d) => (
                <li key={d.cid} className="flex flex-wrap items-start gap-3">
                  <p className="min-w-[180px] flex-1 text-[14px] leading-relaxed text-bone-dim">{d.text}</p>
                  <Chip key={d.status} tone={STATUS[d.status]?.tone} flip title="An absence cannot be quoted, so a difference stays a lead unless the verifier can back it.">{STATUS[d.status]?.label ?? d.status}</Chip>
                </li>
              ))}
            </ul>
          </details>
        )}

        {board.loose.length > 0 && (
          <details className={styles.processDetails}>
            <summary>Other claims <span>({board.loose.length})</span></summary>
            {board.loose.map((claim) => <ClaimCard key={claim.cid} claim={claim} evidence={claim.evidence.map((id) => state.evidence[id]).filter(Boolean)} />)}
          </details>
        )}


      </div>
    </div>
  );
}
