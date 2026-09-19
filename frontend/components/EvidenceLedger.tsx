"use client";
// The data-wrangling receipts: every merge decision (including the ones the resolver declined),
// every conflict with how it was settled, every inferred field, every source that failed.
import clsx from "clsx";
import { fmtSim, fmtValue, shortModel, sourceColor } from "@/lib/format";
import type { LedgerRow } from "@/lib/selectors";
import { Chip, Empty, InferredTag, SourceMark } from "./ui";

const KIND_LABEL: Record<LedgerRow["kind"], string> = { merge: "Entity match", conflict: "Conflict", imputed: "Imputation", source_failed: "Source failure" };
const KIND_COLOR: Record<LedgerRow["kind"], string> = { merge: "var(--color-bone-dim)", conflict: "var(--color-vermilion)", imputed: "var(--color-amber)", source_failed: "var(--color-vermilion)" };

function Signals({ signals }: { signals: Record<string, unknown> }) {
  const entries = Object.entries(signals ?? {});
  if (!entries.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {entries.map(([k, v]) => (
        <Chip key={k} tone={v === true ? "teal" : "mute"}>
          {k.replace(/_/g, " ")} {typeof v === "boolean" ? (v ? "✓" : "✗") : typeof v === "number" ? fmtSim(v) : fmtValue(v)}
        </Chip>
      ))}
    </div>
  );
}

function RowBody({ row }: { row: LedgerRow }) {
  switch (row.kind) {
    case "merge": {
      const v = row.decision.verdict;
      return (
        <>
          <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-bone">
            <span className="truncate">{row.aTitle}</span>
            <span className="font-mono text-[10px] text-mute">{v === "same" ? "=" : v === "different" ? "≠" : "≟"}</span>
            <span className="truncate">{row.bTitle}</span>
            <Chip tone={v === "same" ? "teal" : v === "different" ? "mute" : "amber"} className="ml-auto">
              {v === "same" ? "same project" : v === "different" ? "different" : "insufficient evidence: left open"}
            </Chip>
          </div>
          <p className="mt-1 text-[11.5px] leading-snug text-bone-dim">{row.decision.rationale}</p>
          <Signals signals={row.decision.signals} />
          <div className="mt-1 font-mono text-[9.5px] text-faint">adjudicated by {row.decision.model ? shortModel(row.decision.model) : "deterministic rules (no LLM needed)"}</div>
        </>
      );
    }
    case "conflict":
      return (
        <>
          <div className="text-[12px] text-bone">
            <span className="text-bone-dim">{row.entity} ·</span> <span className="font-mono text-[11px]">{row.field}</span>
          </div>
          <ul className="mt-1.5 flex flex-col gap-1">
            {row.values.map((v, i) => {
              const won = fmtValue(v.value).toLowerCase().startsWith(fmtValue(row.resolution).toLowerCase());
              return (
                <li key={i} className="flex items-center gap-2 text-[11.5px]">
                  <SourceMark source={v.source} />
                  <span className={clsx("min-w-0 flex-1 truncate", won ? "text-bone" : "text-mute line-through decoration-faint")}>{fmtValue(v.value)}</span>
                  <span className="flex w-[74px] flex-none items-center gap-1" title={`source reliability prior: ${v.reliability}`}>
                    <span className="h-[3px] flex-1 bg-ink-700"><span className="block h-full" style={{ width: `${Math.round(v.reliability * 100)}%`, background: sourceColor(v.source) }} /></span>
                    <span className="font-mono text-[9.5px] text-mute">{v.reliability.toFixed(2)}</span>
                  </span>
                </li>
              );
            })}
          </ul>
          <div className="mt-1.5 text-[11.5px] text-bone-dim">
            Settled as <span className="font-mono text-teal">{fmtValue(row.resolution)}</span> <span className="text-mute">because {row.rule}</span>
          </div>
        </>
      );
    case "imputed":
      return (
        <div className="text-[12px] text-bone">
          <span className="text-bone-dim">{row.entity} ·</span> <span className="font-mono text-[11px]">{row.field}</span>{" "}
          <span className="text-amber">= {fmtValue(row.value)}</span>
          <InferredTag />
          <div className="mt-0.5 font-mono text-[9.5px] text-faint">no source states this; inferred from {row.provenance.join(", ") || "context"}</div>
        </div>
      );
    case "source_failed":
      return (
        <div className="text-[12px] text-bone">
          <SourceMark source={row.source} /> <span className="ml-1 text-vermilion">{row.error}</span>
          <div className="mt-0.5 text-[11.5px] text-bone-dim">
            {row.recovered ? "Recovered on a broadened retry. Coverage still counts as degraded, so confidence is reduced." : row.reassigned_to ? `Reassigned to ${row.reassigned_to}.` : "Not recovered: confidence is reduced."}
          </div>
        </div>
      );
  }
}

export function EvidenceLedger({ rows }: { rows: LedgerRow[] }) {
  if (!rows.length) return <Empty>Nothing to reconcile yet.</Empty>;
  return (
    <ol className="flex flex-col">
      {rows.map((row) => (
        <li key={row.key} className="animate-rise border-b border-line px-3 py-2.5">
          <div className="mb-1 flex items-center gap-2">
            <span className="size-[5px]" style={{ background: KIND_COLOR[row.kind] }} />
            <span className="font-mono text-[9px] uppercase tracking-[0.18em]" style={{ color: KIND_COLOR[row.kind] }}>{KIND_LABEL[row.kind]}</span>
          </div>
          <RowBody row={row} />
        </li>
      ))}
    </ol>
  );
}
