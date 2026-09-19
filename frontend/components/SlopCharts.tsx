"use client";
// Charts for the Slop Index investigation. One axis, a fixed (validated) stack order, solid hairline grid,
// a legend plus a table twin, and Wilson intervals drawn as whiskers on the total flagged share.
import { Bar, CartesianGrid, ComposedChart, ErrorBar, LabelList, Line, Rectangle, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CHART, SUBCLASSES } from "@/lib/chartTheme";
import type { SlopIndex, SlopYear } from "@/lib/slop";

interface Row {
  year: string;
  scanned: number;
  flagged: number;
  share: number;
  err: [number, number];
  ci: [number, number];
  pure_ai: number;
  ai_paraphrased: number;
  polished: number;
  concatenated: number;
  raw: SlopYear;
}

const pct = (n: number, d: number) => (d > 0 ? (n / d) * 100 : 0);

export function toRows(years: SlopYear[]): Row[] {
  return [...years].sort((a, b) => a.year - b.year).map((y) => {
    const flagged = y.ai_high + y.mixed_high;
    const share = pct(flagged, y.scanned);
    return {
      year: String(y.year), scanned: y.scanned, flagged, share,
      err: [Math.max(0, share - y.ci_low * 100), Math.max(0, y.ci_high * 100 - share)],
      ci: [y.ci_low * 100, y.ci_high * 100],
      pure_ai: pct(y.by_subclass.pure_ai ?? 0, y.scanned),
      ai_paraphrased: pct(y.by_subclass.ai_paraphrased ?? 0, y.scanned),
      polished: pct(y.by_subclass.polished ?? 0, y.scanned),
      concatenated: pct(y.by_subclass.concatenated ?? 0, y.scanned),
      raw: y,
    };
  });
}

/** Stacked segment: 2px surface gap above every segment that has something stacked on it; 4px rounded cap on the topmost. */
function Segment(props: { x?: number; y?: number; width?: number; height?: number; fill?: string; payload?: Row; dataKey?: string }) {
  const { x = 0, y = 0, width = 0, height = 0, fill, payload, dataKey } = props;
  if (!payload || height <= 0) return null;
  const idx = SUBCLASSES.findIndex((s) => s.key === dataKey);
  const isTop = SUBCLASSES.slice(idx + 1).every((s) => (payload[s.key] ?? 0) <= 0);
  const gap = isTop || height <= 3 ? 0 : 2;
  return <Rectangle x={x} y={y + gap} width={width} height={height - gap} fill={fill} radius={isTop ? [4, 4, 0, 0] : 0} />;
}

function SlopTooltip({ active, payload }: { active?: boolean; payload?: readonly { payload?: Row }[] }) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  return (
    <div className="w-[230px] border border-line-strong bg-ink-800/[0.97] px-3 py-2 font-mono text-[10.5px] shadow-[0_10px_30px_rgb(0_0_0/0.6)]">
      <div className="flex items-baseline justify-between text-bone"><span className="text-[12px]">{row.year}</span><span className="text-mute">n = {row.scanned}</span></div>
      <div className="mt-1 text-bone">{row.share.toFixed(1)}% flagged <span className="text-mute">(95% CI {row.ci[0].toFixed(1)}–{row.ci[1].toFixed(1)}%)</span></div>
      <ul className="mt-1.5 flex flex-col gap-0.5 border-t border-line pt-1.5">
        {[...SUBCLASSES].reverse().map((s) => (
          <li key={s.key} className="flex items-center gap-1.5 text-bone-dim">
            <span className="size-2 flex-none" style={{ background: s.color }} />
            <span className="flex-1">{s.label}</span>
            <span className="tabular-nums text-bone">{row[s.key].toFixed(1)}%</span>
            <span className="w-[22px] text-right tabular-nums text-faint">{row.raw.by_subclass[s.key] ?? 0}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SlopShareChart({ data }: { data: SlopIndex }) {
  const rows = toRows(data.years);
  const placeboYears = (data.placebo?.years ?? rows.filter((r) => Number(r.year) <= 2021).map((r) => Number(r.year))).map(String).filter((y) => rows.some((r) => r.year === y));
  const yMax = Math.min(100, Math.ceil((Math.max(...rows.map((r) => r.ci[1])) + 4) / 10) * 10);

  return (
    <figure className="flex min-h-0 flex-1 flex-col">
      <ul className="flex flex-none flex-wrap gap-x-4 gap-y-1 font-mono text-[10.5px] text-bone-dim" aria-label="Legend">
        {SUBCLASSES.map((s) => (
          <li key={s.key} className="flex items-center gap-1.5"><span className="size-[9px]" style={{ background: s.color }} />{s.label}</li>
        ))}
        <li className="flex items-center gap-1.5">
          <svg width="12" height="14" aria-hidden><path d="M2 1.5h8M6 1.5v11M2 12.5h8" stroke={CHART.textStrong} strokeWidth="1.2" fill="none" /><circle cx="6" cy="7" r="2.5" fill={CHART.textStrong} /></svg>
          total flagged, 95% Wilson interval
        </li>
        {placeboYears.length > 0 && <li className="flex items-center gap-1.5"><span className="h-[9px] w-[14px] border border-dashed border-mute bg-bone/[0.05]" />placebo years (pre-ChatGPT)</li>}
      </ul>

      <div className="mt-3 min-h-[340px] flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 18, right: 40, bottom: 4, left: 0 }} barCategoryGap="38%">
            <CartesianGrid vertical={false} stroke={CHART.grid} />
            {placeboYears.length > 0 && (
              <ReferenceArea x1={placeboYears[0]} x2={placeboYears[placeboYears.length - 1]} fill="rgba(236,229,211,0.045)" stroke="rgba(124,132,152,0.5)" strokeDasharray="3 4" ifOverflow="extendDomain" />
            )}
            <XAxis dataKey="year" tickLine={false} axisLine={{ stroke: CHART.axis }} tick={{ fill: CHART.text, fontSize: 11 }} />
            <YAxis domain={[0, yMax]} tickLine={false} axisLine={false} width={44} tick={{ fill: CHART.textMuted, fontSize: 10.5 }} tickFormatter={(v: number) => `${v}%`} />
            <Tooltip cursor={{ fill: "rgba(150,176,230,0.06)" }} content={<SlopTooltip />} isAnimationActive={false} />
            {SUBCLASSES.map((s) => (
              <Bar key={s.key} dataKey={s.key} stackId="share" fill={s.color} maxBarSize={24} shape={<Segment />} isAnimationActive animationDuration={700} />
            ))}
            <Line dataKey="share" stroke="none" isAnimationActive={false} activeDot={false} dot={{ r: 4, fill: CHART.textStrong, stroke: CHART.surface, strokeWidth: 2 }}>
              <ErrorBar dataKey="err" direction="y" width={5} stroke={CHART.textStrong} strokeWidth={1.2} />
              <LabelList
                dataKey="share"
                content={(p) => {
                  const { x, y, index, value } = p as { x?: number; y?: number; index?: number; value?: number };
                  // direct-label the endpoint only; the axis, tooltip and table carry the rest
                  if (index !== rows.length - 1 || x == null || y == null || value == null) return null;
                  return <text x={x + 11} y={y + 4} textAnchor="start" fill={CHART.textStrong} fontSize={12}>{Number(value).toFixed(0)}%</text>;
                }}
              />
            </Line>
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-1 flex-none font-mono text-[10px] leading-snug text-mute">
        Share of scanned pitches that GPTZero classes as AI or mixed <em>with high confidence</em>, split by subclass. Years without a bar were not sampled.
      </figcaption>
    </figure>
  );
}

export function SlopTable({ data }: { data: SlopIndex }) {
  const rows = toRows(data.years);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] font-mono text-[11px] tabular-nums text-bone-dim">
        <thead>
          <tr className="text-left text-[9.5px] uppercase tracking-[0.12em] text-faint">
            <th className="py-1.5 font-normal">year</th>
            <th className="py-1.5 text-right font-normal">scanned</th>
            <th className="py-1.5 text-right font-normal">AI · high</th>
            <th className="py-1.5 text-right font-normal">mixed · high</th>
            <th className="py-1.5 text-right font-normal">flagged share</th>
            <th className="py-1.5 text-right font-normal">95% CI</th>
            {SUBCLASSES.map((s) => (
              <th key={s.key} className="py-1.5 text-right font-normal"><span className="mr-1 inline-block size-[7px]" style={{ background: s.color }} />{s.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.year} className="border-t border-line">
              <td className="py-1.5 text-bone">{r.year}</td>
              <td className="py-1.5 text-right">{r.scanned}</td>
              <td className="py-1.5 text-right">{r.raw.ai_high}</td>
              <td className="py-1.5 text-right">{r.raw.mixed_high}</td>
              <td className="py-1.5 text-right text-bone">{r.share.toFixed(1)}%</td>
              <td className="py-1.5 text-right">{r.ci[0].toFixed(1)}–{r.ci[1].toFixed(1)}%</td>
              {SUBCLASSES.map((s) => <td key={s.key} className="py-1.5 text-right">{r.raw.by_subclass[s.key] ?? 0}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
