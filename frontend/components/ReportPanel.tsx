"use client";
// The synthesizer's report: only what survived verification. Summary (rendered without innerHTML), citations,
// how crowded the neighbourhood got year by year, and which sources answered.
import clsx from "clsx";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BY_YEAR, CHART } from "@/lib/chartTheme";
import { safeHref } from "@/lib/format";
import type { RunState } from "@/lib/runReducer";
import { selectSourceStatus, type SourceStatusRow } from "@/lib/selectors";
import type { Facets, YearCount } from "@/lib/types";
import { SafeMarkdown } from "./SafeMarkdown";
import { Chip, SourceMark } from "./ui";

const FACET_KEYS = ["purpose", "mechanism", "audience", "data", "twist"] as const;

function FacetList({ facets }: { facets: Facets }) {
  return (
    <section>
      <h4 className="label mb-1.5">How the conductor read your idea</h4>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        {FACET_KEYS.map((k) => (
          <div key={k} className="contents">
            <dt className="pt-[2px] font-mono text-[10px] uppercase tracking-[0.12em] text-accent">{k}</dt>
            <dd className="text-[12.5px] leading-snug text-bone-dim">{facets[k]}</dd>
          </div>
        ))}
      </dl>
      {facets.keywords?.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          <Chip tone="mute">{facets.domain}</Chip>
          {facets.keywords.map((k) => <Chip key={k} tone="mute">{k}</Chip>)}
        </div>
      )}
    </section>
  );
}

function Citation({ text, n }: { text: string; n: number }) {
  // "[1] Org. "Title." Site. Year. https://…" -> link only the URL, and only if it is http(s)
  const m = /(https?:\/\/\S+)\s*$/.exec(text);
  const href = m ? safeHref(m[1]) : null;
  const body = m ? text.slice(0, m.index).trimEnd() : text;
  return (
    <li id={`cite-${n}`} className="scroll-mt-4 text-[11.5px] leading-snug text-bone-dim target:text-bone">
      {body}{" "}
      {href && <a href={href} target="_blank" rel="noopener noreferrer" className="break-all font-mono text-[10px] text-accent hover:underline">{m![1]}</a>}
    </li>
  );
}

function YearTooltip({ active, payload, label }: { active?: boolean; payload?: readonly { payload?: YearCount }[]; label?: string | number }) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  return (
    <div className="border border-line-strong bg-ink-800/95 px-2.5 py-1.5 font-mono text-[10.5px] shadow-[0_8px_24px_rgb(0_0_0/0.16)]">
      <div className="text-bone">{label}</div>
      <div className="mt-0.5 flex items-center gap-1.5 text-bone-dim"><span className="size-2" style={{ background: BY_YEAR.other.color }} />{row.count} similar projects</div>
      <div className="flex items-center gap-1.5 text-bone-dim"><span className="size-2" style={{ background: BY_YEAR.winners.color }} />{row.winners} prize winners</div>
    </div>
  );
}

function ByYear({ rows }: { rows: YearCount[] }) {
  const data = rows.map((r) => ({ ...r, other: Math.max(0, r.count - r.winners) }));
  const peak = rows.reduce((a, b) => (b.count > a.count ? b : a), rows[0]);
  return (
    <section>
      <h4 className="label">Similar projects per year</h4>
      <p className="mt-0.5 text-[11px] leading-snug text-mute">The neighbourhood peaked in {peak.year} with {peak.count} projects.</p>
      <ul className="mt-1.5 flex gap-3 font-mono text-[9.5px] text-bone-dim">
        <li className="flex items-center gap-1.5"><span className="size-2" style={{ background: BY_YEAR.other.color }} />{BY_YEAR.other.label}</li>
        <li className="flex items-center gap-1.5"><span className="size-2" style={{ background: BY_YEAR.winners.color }} />{BY_YEAR.winners.label}</li>
      </ul>
      <div className="mt-1 h-[150px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: -22 }} barCategoryGap="28%">
            <CartesianGrid vertical={false} stroke={CHART.grid} />
            <XAxis dataKey="year" tickLine={false} axisLine={{ stroke: CHART.axis }} tick={{ fill: CHART.textMuted, fontSize: 10 }} />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: CHART.textMuted, fontSize: 10 }} width={48} />
            <Tooltip cursor={{ fill: "rgba(150,176,230,0.07)" }} content={<YearTooltip />} isAnimationActive={false} />
            <Bar dataKey="winners" stackId="y" fill={BY_YEAR.winners.color} stroke={CHART.surface} strokeWidth={2} maxBarSize={24} isAnimationActive animationDuration={600} />
            <Bar dataKey="other" stackId="y" fill={BY_YEAR.other.color} stroke={CHART.surface} strokeWidth={2} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive animationDuration={600} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <details className="mt-1">
        <summary className="cursor-pointer font-mono text-[9.5px] uppercase tracking-[0.14em] text-faint hover:text-bone-dim">Table view</summary>
        <table className="mt-1 w-full font-mono text-[10.5px] tabular-nums text-bone-dim">
          <thead><tr className="text-left text-faint"><th className="font-normal">year</th><th className="text-right font-normal">projects</th><th className="text-right font-normal">winners</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.year} className="border-t border-line"><td>{r.year}</td><td className="text-right">{r.count}</td><td className="text-right">{r.winners}</td></tr>)}</tbody>
        </table>
      </details>
    </section>
  );
}

const STATUS_TONE: Record<SourceStatusRow["status"], "teal" | "red" | "amber" | "mute"> = { ok: "teal", failed: "red", degraded: "amber", skipped: "mute", searching: "mute" };

function Sources({ rows }: { rows: SourceStatusRow[] }) {
  return (
    <section>
      <h4 className="label mb-1.5">Sources</h4>
      <ul className="flex flex-col">
        {rows.map((s) => (
          <li key={s.source} className="flex items-center gap-2 border-t border-line py-1.5 first:border-t-0">
            <span className="w-[104px] flex-none"><SourceMark source={s.source} /></span>
            <Chip tone={STATUS_TONE[s.status]}>{s.status}</Chip>
            <span className="font-mono text-[10px] text-mute">{s.n_records} record{s.n_records === 1 ? "" : "s"}</span>
            {s.error && <span className={clsx("min-w-0 truncate text-[11px]", s.status === "skipped" ? "text-mute" : "text-vermilion/90")} title={s.error}>{s.error}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ReportPanel({ state }: { state: RunState }) {
  const report = state.report;
  const sources = selectSourceStatus(state);
  return (
    <div className="flex flex-col gap-4 p-3">
      {report ? (
        <section className="animate-rise">
          <h4 className="label mb-1.5">Verdict</h4>
          <SafeMarkdown source={report.summary_md} className="prose-atlas font-display text-[17.5px] leading-[1.35] text-bone-dim" />
          {report.citations?.length > 0 && (
            <ol className="mt-2 flex flex-col gap-1 border-l border-line pl-2.5">
              {report.citations.map((c, i) => <Citation key={i} text={c} n={i + 1} />)}
            </ol>
          )}
          <p className="mt-2 font-mono text-[9.5px] leading-snug text-faint">
            Written from {state.claimOrder.filter((c) => state.claims[c].status === "verified").length} verified claims.
          </p>
        </section>
      ) : (
        <section>
          <h4 className="label mb-1.5">Verdict</h4>
          <p className="font-display text-[17px] italic leading-snug text-faint">Nothing to say yet.</p>
        </section>
      )}

      {report && report.by_year?.length > 0 && <ByYear rows={report.by_year} />}
      {state.facets && <FacetList facets={state.facets} />}
      {sources.length > 0 && <Sources rows={sources} />}
    </div>
  );
}
