"use client";
import { Check, RotateCcw, X } from "lucide-react";
import { ROLE_BLURB } from "@/lib/agents";
import type { DebateBoard } from "@/lib/debate";
import { shortModel } from "@/lib/format";
import styles from "./debate.module.css";

export function OrchestrationStrip({ board }: { board: DebateBoard }) {
  const { stages, scouts, funnel, jurors } = board;
  const sentBack = scouts.fromCritic.count + scouts.fromJury.count;
  return (
    <section aria-label="Debate progress">
      <h2 className={styles.eyebrow}>How the case is built</h2>
      <ol className={styles.stages}>
        {stages.map((stage, i) => (
          <li key={stage.id} className={styles.stage} data-status={stage.status} title={ROLE_BLURB[stage.id]}>
            <span className={styles.stageNumber} aria-label={stage.status}>
              {stage.status === "done" ? <Check size={13} /> : stage.status === "failed" ? <X size={13} /> : String(i + 1).padStart(2, "0")}
            </span>
            <div>
              <h3>{stage.label}{stage.status === "active" && <span className={styles.liveDot} />}</h3>
              <p>{stage.stat || (stage.status === "active" ? "Working…" : "Waiting")}</p>
              <span className={styles.stageModel}>{stage.id === "judge" ? `${jurors.length || "Independent"} jurors · blind review` : stage.id === "verifier" ? "Source verification" : shortModel(stage.model)}</span>
            </div>
          </li>
        ))}
      </ol>
      {sentBack > 0 && <p className={styles.scoutNote}><RotateCcw size={13} />{sentBack} follow-up {sentBack === 1 ? "search" : "searches"}{scouts.status === "active" ? " · searching" : ""}</p>}
      <div className={styles.summary}>
        <p className={styles.eyebrow}>Evidence check</p>
        <dl>
          <div><dt>Claims reviewed</dt><dd>{funnel.proposed}</dd></div>
          <div><dt>Verified for report</dt><dd>{funnel.reachReport}</dd></div>
          {funnel.struck > 0 && <div><dt>Struck</dt><dd>{funnel.struck}</dd></div>}
          {funnel.leads > 0 && <div><dt>Unverified leads</dt><dd>{funnel.leads}</dd></div>}
          {funnel.pending > 0 && <div><dt>Awaiting verification</dt><dd>{funnel.pending}</dd></div>}
        </dl>
        <p className={styles.summaryNote}>Verification checks the evidence, not whether your idea is original.</p>
      </div>
    </section>
  );
}
