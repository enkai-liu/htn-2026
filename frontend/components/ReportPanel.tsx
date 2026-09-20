"use client";
// The synthesizer's report: only what survived verification.
//
// Ordered for someone reading it for the first time, in front of an audience: the answer, then the sentence that
// explains it, then the three axes it came from, then the receipts. Everything that is process rather than
// finding -- how the idea was decomposed, which sources answered, the year histogram -- is folded away, one click
// from the Q&A that asks for it.
import clsx from "clsx";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BY_YEAR, CHART } from "@/lib/chartTheme";
import { safeHref } from "@/lib/format";
import { headlineParts } from "@/lib/headline";
import type { RunState } from "@/lib/runReducer";
import { selectSourceStatus, type SourceStatusRow } from "@/lib/selectors";
import type { Facets, Scores, YearCount } from "@/lib/types";
import { AxisGauges } from "./AxisGauges";
import { SafeMarkdown } from "./SafeMarkdown";
import { Chip, SourceMark } from "./ui";

const FACET_KEYS = ["purpose", "mechanism", "audience", "data", "twist"] as const;

/** The number, said once, as large as it deserves. An abstention takes the same slot rather than hiding. */
function Answer({ scores, verifiedClaims }: { scores: Scores | null; verifiedClaims: number }) {
  const h = headlineParts(scores);

  if (h.abstain || h.value == null) {
    return (
      <section className="animate-rise border-b border-line px-5 py-6">
        <h3 className="font-display text-[30px] leading-tight text-bone">
          {h.abstain ? "Insufficient evidence" : "Not scored yet"}
        </h3>
        <p className="mt-1.5 max-w-[60ch] text-[14px] leading-snug text-bone-dim">
          {h.reason || "The run has not produced a score. Nothing here is withheld: there is not enough evidence to state one."}
        </p>
      </section>
    );
  }

  return (
    <section className="animate-rise flex flex-wrap items-end gap-x-8 gap-y-3 border-b border-line px-5 py-6">
      <div>
        <p className="label text-mute">Originality</p>
        <p className="mt-1 flex items-baseline gap-1 font-display text-[64px] leading-[0.9] tabular-nums text-bone">
          {Math.round(h.value)}<span className="text-[30px] text-mute">{h.suffix}</span>
        </p>
      </div>
      <div className="min-w-0 flex-1 pb-1.5">
        {h.interval && <p className="text-[15px] leading-snug text-bone-dim">{h.interval}</p>}
        <p className="mt-1 font-mono text-[10.5px] uppercase tracking-[0.12em] text-mute">
          {h.confidence != null && (
            <>confidence {h.confidenceLabel} · {(h.confidence * 100).toFixed(0)}%</>
          )}
          {verifiedClaims > 0 && <> · {verifiedClaims} verified claim{verifiedClaims === 1 ? "" : "s"}</>}
        </p>
      </div>
    </section>
  );
}

function Citation({ text, n }: { text: string; n: number }) {
  // "[1] Org. "Title." Site. Year. https://…" -> link only the URL, and only if it is http(s)
  const m = /(https?:\/\/\S+)\s*$/.exec(text);
  const href = m ? safeHref(m[1]) : null;
  const body = m ? text.slice(0, m.index).trimEnd() : text;
  return (
    <li id={`cite-${n}`} className="scroll-mt-4 text-[12px] leading-snug text-bone-dim target:text-bone">
      {body}{" "}
      {href && <a href={href} target="_blank" rel="noopener noreferrer" className="break-all font-mono text-[10.5px] text-accent hover:underline">{m![1]}</a>}
    </li>
  );
}

/** Everything that is process rather than finding lives behind one of these. */
function More({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="group border-t border-line px-5">
      <summary className="flex cursor-pointer list-none items-center gap-2 py-2.5 font-mono text-[10px] uppercase tracking-[0.14em] text-mute hover:text-bone">
        <span className="inline-block transition-transform group-open:rotate-90">›</span>
        {title}
      </summary>
      <div className="pb-4">{children}</div>
    </details>
  );
}

function FacetList({ facets }: { facets: Facets }) {
  return (
    <>
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
    </>
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
    <>
      <p className="text-[12px] leading-snug text-mute">The neighbourhood peaked in {peak.year} with {peak.count} projects.</p>
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
    </>
  );
}

const STATUS_TONE: Record<SourceStatusRow["status"], "teal" | "red" | "amber" | "mute"> = { ok: "teal", failed: "red", degraded: "amber", skipped: "mute", searching: "mute" };

function Sources({ rows }: { rows: SourceStatusRow[] }) {
  return (
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
  );
}

export function ReportPanel({ state }: { state: RunState }) {
  const report = state.report;
  const sources = selectSourceStatus(state);
  const verified = state.claimOrder.filter((c) => state.claims[c].status === "verified").length;

  return (
    <div className="flex flex-col">
      <Answer scores={state.scores} verifiedClaims={verified} />

      {report ? (
        <section className="animate-rise border-b border-line px-5 py-4">
          <SafeMarkdown source={report.summary_md} className="prose-atlas font-display text-[18px] leading-[1.4] text-bone-dim" />
          {report.citations?.length > 0 && (
            <ol className="mt-3 flex flex-col gap-1 border-l border-line pl-3">
              {report.citations.map((c, i) => <Citation key={i} text={c} n={i + 1} />)}
            </ol>
          )}
        </section>
      ) : (
        <section className="border-b border-line px-5 py-4">
          <p className="font-display text-[17px] italic leading-snug text-faint">No verdict yet.</p>
        </section>
      )}

      {/* the three axes behind the number, exactly as the header chip shows them */}
      {state.scores && (
        <section className="border-b border-line" aria-label="The axes behind the score">
          <div className="h-[150px]"><AxisGauges scores={state.scores} headline={false} /></div>
        </section>
      )}

      {report && report.by_year?.length > 0 && <More title="Similar projects per year"><ByYear rows={report.by_year} /></More>}
      {state.facets && <More title="How the conductor read your idea"><FacetList facets={state.facets} /></More>}
      {sources.length > 0 && <More title={`Sources · ${sources.length}`}><Sources rows={sources} /></More>}
    </div>
  );
}
