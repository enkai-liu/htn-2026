"use client";
// Spend so far. budget.updated is the conductor's own ledger; between those snapshots the meter keeps moving
// from the per-event cost fields. The popover is the "right-sized model per role" receipt.
import clsx from "clsx";
import { useState } from "react";
import { agentColor } from "@/lib/agents";
import { fmtTokens, fmtUsd, modelFamily, shortModel } from "@/lib/format";
import type { RunState } from "@/lib/runReducer";
import { selectSpend } from "@/lib/selectors";

export function CostMeter({ state }: { state: RunState }) {
  const [open, setOpen] = useState(false);
  const spend = selectSpend(state);

  return (
    <div className="relative" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className={clsx("flex h-[28px] items-center gap-2.5 border px-2.5 font-mono text-[10.5px] transition-colors", spend.degraded ? "border-vermilion/60 text-vermilion" : "border-line text-bone-dim hover:border-line-strong")}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label="Cost and model usage"
      >
        <span className="text-accent">{fmtUsd(spend.usd)}</span>
        <span className="hidden text-mute xl:inline">{spend.calls} calls</span>
        <span className="text-mute">{fmtTokens(spend.tokens)} tok</span>
        <span className="text-mute">{Math.round(spend.elapsed)}s</span>
        {spend.degraded && <span className="uppercase tracking-[0.12em]">degraded</span>}
      </button>

      {open && (
        <div className="absolute right-0 top-[calc(100%+6px)] z-40 w-[430px] animate-rise border border-line-strong bg-ink-800/[0.98] p-3 shadow-[0_18px_50px_rgb(0_0_0/0.65)]">
          <CostTable state={state} />
        </div>
      )}
    </div>
  );
}

/** The "right-sized model per role" receipt: used by the header popover (classic) and by the Swarm page. */
export function CostTable({ state }: { state: RunState }) {
  const models = Object.values(state.cost.byModel).filter((m) => m.model !== "unattributed").sort((a, b) => b.usd - a.usd);
  return (
    <>
    <div className="label mb-2">A model per role</div>
    {models.length === 0 ? (
      <p className="text-[12px] text-mute">No LLM-backed events yet.</p>
    ) : (
      <table className="w-full text-left font-mono text-[10px] tabular-nums">
        <thead>
          <tr className="text-faint">
            <th className="pb-1 font-normal">model</th>
            <th className="pb-1 font-normal">roles</th>
            <th className="pb-1 text-right font-normal">events</th>
            <th className="pb-1 text-right font-normal">tokens</th>
            <th className="pb-1 text-right font-normal">avg</th>
            <th className="pb-1 text-right font-normal">cost</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.model} className="border-t border-line align-top">
              <td className="py-1 pr-2 text-bone" title={m.model}>
                {shortModel(m.model)}
                <div className="text-[8.5px] text-faint">{modelFamily(m.model)}{m.provider ? ` · ${m.provider}` : ""}</div>
              </td>
              <td className="py-1 pr-2">
                {m.roles.map((r) => <div key={r} style={{ color: agentColor(r) }}>{r}</div>)}
              </td>
              <td className="py-1 text-right text-bone-dim">{m.events}</td>
              <td className="py-1 text-right text-bone-dim">{fmtTokens(m.tokensIn + m.tokensOut)}</td>
              <td className="py-1 text-right text-bone-dim">{m.latencyN ? `${(m.latencyMs / m.latencyN / 1000).toFixed(1)}s` : "–"}</td>
              <td className="py-1 text-right text-accent">{fmtUsd(m.usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    )}
    <p className="mt-2 text-[10.5px] leading-snug text-mute">
      {state.budget
        ? `Conductor's ledger: ${state.budget.calls} calls · ${fmtTokens(state.budget.tokens)} tokens · ${fmtUsd(state.budget.cost_usd)} after ${state.budget.elapsed_s}s. The table counts only events that carried their own model and cost.`
        : "The conductor has not posted a budget snapshot yet; the figure above sums per-event costs."}
    </p>
    </>
  );
}
