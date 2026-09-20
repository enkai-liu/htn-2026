"use client";
// Headline (with its uncertainty band, or an abstention) + the three axes that feed it + Confidence.
// Voice is deliberately NOT here: AI-probability is not unoriginality, so it has its own panel.
import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { fmtSim } from "@/lib/format";
import type { AxisScore, Scores } from "@/lib/types";

function useTween(target: number | null, ms = 900): number | null {
  const [value, setValue] = useState<number | null>(target);
  const from = useRef<number>(0);
  useEffect(() => {
    if (target == null) return;
    const start = performance.now();
    const origin = from.current;
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / ms);
      const eased = 1 - Math.pow(1 - p, 3);
      const v = origin + (target - origin) * eased;
      from.current = v;
      setValue(v);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return target == null ? null : value;
}

function ScaleBar({ value, band, color, dim }: { value: number | null; band?: number | null; color: string; dim?: boolean }) {
  const v = value == null ? null : Math.max(0, Math.min(100, value));
  const lo = v != null && band ? Math.max(0, v - band) : null;
  const hi = v != null && band ? Math.min(100, v + band) : null;
  return (
    <div className={clsx("relative h-[14px]", dim && "opacity-40")}>
      <div className="ticks absolute inset-x-0 top-[5px] h-[4px] border-x border-line-strong bg-ink-700" />
      {lo != null && hi != null && (
        <div className="absolute top-[2px] h-[10px] border-x transition-all duration-700" style={{ left: `${lo}%`, width: `${hi - lo}%`, background: `color-mix(in srgb, ${color} 20%, transparent)`, borderColor: color }} />
      )}
      {v != null && (
        <>
          <div className="absolute top-[5px] h-[4px] transition-[width] duration-700" style={{ width: `${v}%`, background: `color-mix(in srgb, ${color} 55%, transparent)` }} />
          <div className="absolute top-0 h-[14px] w-[2px] -translate-x-1/2 transition-[left] duration-700" style={{ left: `${v}%`, background: color, boxShadow: `0 0 8px ${color}` }} />
        </>
      )}
    </div>
  );
}

function FacetBars({ rarity }: { rarity: Record<string, number> }) {
  const entries = Object.entries(rarity).slice(0, 6);
  return (
    <div className="flex flex-none items-end gap-[2px]" title={`rarity per facet\n${entries.map(([k, v]) => `${k}: ${fmtSim(v)}`).join("\n")}`}>
      {entries.map(([k, v]) => (
        <div key={k} className="flex h-[14px] w-[7px] items-end bg-ink-700">
          <div className={clsx("w-full transition-[height] duration-700", v >= 0.75 ? "bg-teal" : "bg-bone-dim/70")} style={{ height: `${Math.max(8, v * 100)}%` }} />
        </div>
      ))}
    </div>
  );
}

function Axis({ label, low, high, axis, extra, color }: { label: string; low: string; high: string; axis: AxisScore | null; extra?: React.ReactNode; color: string }) {
  const shown = useTween(axis?.score ?? null);
  return (
    <div className="flex min-w-0 flex-1 flex-col justify-center border-t border-line px-3 first:border-t-0" title={axis?.note}>
      <div className="flex items-center gap-2.5">
        <span className="label w-[142px] flex-none truncate !tracking-[0.14em]">{label}</span>
        <div className="min-w-0 flex-1" title={`${low} ← → ${high}`}><ScaleBar value={axis?.score ?? null} color={color} /></div>
        {extra}
        <span className={clsx("w-[28px] flex-none text-right font-display text-[22px] leading-none", shown == null ? "text-faint" : "text-bone")}>{shown == null ? "–" : Math.round(shown)}</span>
      </div>
      <div className="flex items-baseline gap-2.5">
        <span className="w-[142px] flex-none font-mono text-[8px] uppercase tracking-[0.1em] text-faint">{low} → {high}</span>
        <p className="min-w-0 flex-1 truncate text-[10.5px] leading-[1.35] text-mute">{axis?.note ?? "\u00a0"}</p>
      </div>
    </div>
  );
}

/** `headline=false` renders only the three axes: the report states the number itself, far bigger. */
export function AxisGauges({ scores, headline: showHeadline = true }: { scores: Scores | null; headline?: boolean }) {
  const abstain = !!scores?.abstain?.active;
  const headline = useTween(abstain ? null : scores?.headline ?? null);
  const confidence = scores?.confidence ?? null;
  const lowConfidence = confidence != null && confidence < 0.45;
  const rarity = scores?.facet_rarity?.detail?.rarity as Record<string, number> | undefined;
  const pred = scores?.llm_predictability?.detail as { n_samples?: number; max_similarity?: number } | undefined;

  return (
    <div className={clsx("grid h-full", showHeadline ? "grid-cols-[200px_minmax(0,1fr)]" : "grid-cols-[minmax(0,1fr)]")}>
      {showHeadline && (
      <div className="flex min-w-0 flex-col justify-center border-r border-line px-3 py-1.5">
        <span className="label">Originality</span>

        {abstain ? (
          <div className="hazard mt-1.5 flex flex-1 animate-rise flex-col justify-center px-2.5 py-1.5">
            <span className="font-mono text-[9.5px] uppercase tracking-[0.16em]">No headline: abstained{confidence != null ? ` · confidence ${Math.round(confidence * 100)}%` : ""}</span>
            <span className="mt-0.5 font-display text-[17px] italic leading-tight text-bone">Insufficient evidence: {scores?.abstain.reason || "not enough sources answered"}</span>
          </div>
        ) : (
          <>
            <div className="mt-0.5 flex items-baseline gap-2">
              <span className={clsx("font-display text-[44px] leading-[0.9]", headline == null ? "text-faint" : lowConfidence ? "text-bone-dim" : "text-accent")}>{headline == null ? "–" : Math.round(headline)}</span>
              {scores?.band != null && headline != null && <span className="font-mono text-[13px] text-bone-dim" title="Uncertainty band: widens when the jury disagrees">± {scores.band}</span>}
              {headline == null && <span className="text-[10.5px] leading-tight text-faint">scored once the debate<br />and verification settle</span>}
              {headline != null && (
                <span className="ml-auto flex flex-col items-end font-mono leading-none" title="Confidence: source coverage, jury agreement, share of verified claims, canary queries. Too low and the headline is withheld.">
                  <span className={clsx("text-[15px]", lowConfidence ? "text-vermilion" : "text-bone")}>{confidence == null ? "–" : `${Math.round(confidence * 100)}%`}</span>
                  <span className="mt-1 text-[8px] uppercase tracking-[0.14em] text-faint">confidence</span>
                </span>
              )}
            </div>
            <div className="mt-1"><ScaleBar value={scores?.headline ?? null} band={scores?.band} color="var(--color-accent)" dim={lowConfidence} /></div>
            <div className="flex justify-between font-mono text-[8px] uppercase tracking-[0.1em] text-faint"><span>done to death</span><span>open sky</span></div>
            {lowConfidence && <p className="mt-0.5 text-[10.5px] leading-tight text-vermilion">Low confidence: treat the number as a hint.</p>}
          </>
        )}
      </div>
      )}

      <div className="flex min-w-0 flex-col">
        <Axis label="Crowding" low="crowded" high="open" axis={scores?.crowding ?? null} color="var(--color-src-devpost)" />
        <Axis label="Facet rarity" low="common" high="rare" axis={scores?.facet_rarity ?? null} color="var(--color-teal)" extra={rarity ? <FacetBars rarity={rarity} /> : undefined} />
        <Axis
          label="LLM-predictability" low="obvious" high="surprising" axis={scores?.llm_predictability ?? null} color="var(--color-cloud)"
          extra={pred?.n_samples ? <span className="flex-none font-mono text-[8.5px] text-faint" title={`closest sample: ${fmtSim(pred.max_similarity)}`}>{pred.n_samples} samples</span> : undefined}
        />
      </div>
    </div>
  );
}
