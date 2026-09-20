"use client";
// Lead with the score and findings; keep supporting evidence and methodology on demand.
import clsx from "clsx";
import { ChevronDown } from "lucide-react";
import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BY_YEAR, CHART } from "@/lib/chartTheme";
import { safeHref } from "@/lib/format";
import { headlineParts } from "@/lib/headline";
import type { RunState } from "@/lib/runReducer";
import { selectSourceStatus, type SourceStatusRow } from "@/lib/selectors";
import type { Facets, Scores, YearCount } from "@/lib/types";
import styles from "./report/report.module.css";
import { SafeMarkdown } from "./SafeMarkdown";
import { Chip, SourceMark } from "./ui";

const FACET_KEYS = ["purpose", "mechanism", "audience", "data", "twist"] as const;

/** Use the same score and uncertainty as the run header. */
function Answer({ scores, verifiedClaims }: { scores: Scores | null; verifiedClaims: number }) {
  const h = headlineParts(scores);
  if (h.abstain || h.value == null) {
    return (
      <section className={styles.card}>
        <h2 className={styles.heading}>{h.abstain ? "Insufficient evidence" : "Not scored yet"}</h2>
        <p className={styles.empty}>{h.reason || "The score will appear once the debate and evidence checks are complete."}</p>
      </section>
    );
  }
  return (
    <section className={clsx(styles.card, styles.answer)} aria-label="Originality result">
      <div>
        <h2 className={styles.scoreLabel}>{h.suffix ? "Originality percentile" : "Originality score"}</h2>
        <p className={styles.score}>{Math.round(h.value)}<span>{h.suffix || "/ 100"}</span></p>
      </div>
      <div className={styles.scoreContext}>
        {h.interval && <p className={styles.interval}>{h.interval}</p>}
        <div className={styles.metadata}>
          {h.range && <span>{h.range}</span>}
          {h.confidence != null && <span>{h.confidenceLabel} confidence · {Math.round(h.confidence * 100)}%</span>}
          <span>{verifiedClaims} verified {verifiedClaims === 1 ? "claim" : "claims"}</span>
        </div>
      </div>
    </section>
  );
}

function Findings({ summary }: { summary: string }) {
  const [expanded, setExpanded] = useState(false);
  const [clipped, setClipped] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = previewRef.current;
    if (!node || expanded) return;
    const observer = new ResizeObserver(() => setClipped(node.scrollHeight > node.clientHeight + 1));
    observer.observe(node);
    return () => observer.disconnect();
  }, [summary, expanded]);
  return (
    <section className={styles.card} aria-label="Findings">
      <h2 className={styles.heading}>Findings</h2>
      <div ref={previewRef} className={clsx(styles.findings, !expanded && styles.preview)}><SafeMarkdown source={summary} className="prose-atlas" /></div>
      {(clipped || expanded) && <button type="button" className={styles.readMore} aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        {expanded ? "Show less" : "Read full findings"}<ChevronDown size={14} className={expanded ? "rotate-180" : undefined} />
      </button>}
    </section>
  );
}

function ScoreBreakdown({ scores }: { scores: Scores }) {
  const axes = [
    { label: "Crowding", scale: "Crowded → open", axis: scores.crowding },
    { label: "Facet rarity", scale: "Common → rare", axis: scores.facet_rarity },
    { label: "AI predictability", scale: "Obvious → surprising", axis: scores.llm_predictability },
  ];
  return (
    <>
      <p className={styles.axisIntro}>Each measure runs from 0 to 100. Higher values indicate greater originality.</p>
      <dl>{axes.map(({ label, scale, axis }) => (
        <div key={label} className={styles.axis}>
          <dt>{label}</dt>
          <dd>
            <span className={styles.axisTrack} aria-hidden><span style={{ width: `${Math.max(0, Math.min(100, axis?.score ?? 0))}%` }} /></span>
            <span className={styles.axisValue}>{axis?.score == null ? "—" : Math.round(axis.score)}</span>
            <p className={styles.axisNote}>{scale}{axis?.note && <> · {axis.note}</>}</p>
          </dd>
        </div>
      ))}</dl>
    </>
  );
}

function Citation({ text, n }: { text: string; n: number }) {
  // "[1] Org. "Title." Site. Year. https://…" -> link only the URL, and only if it is http(s)
  const m = /(https?:\/\/\S+)\s*$/.exec(text);
  const href = m ? safeHref(m[1]) : null;
  const body = m ? text.slice(0, m.index).trimEnd() : text;
  return (
    <li id={`cite-${n}`}>
      {body}{" "}
      {href && <a href={href} target="_blank" rel="noopener noreferrer" aria-label={`Open source ${n}`}>Open source ↗</a>}
    </li>
  );
}

/** Supporting detail stays available without competing with the findings. */
export function ReportDetail({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className={styles.details}>
      <summary>{title}<ChevronDown size={15} /></summary>
      <div className={styles.detailBody}>{children}</div>
    </details>
  );
}

function FacetList({ facets }: { facets: Facets }) {
  return (
    <>
      <dl className={styles.facetList}>
        {FACET_KEYS.map((k) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{facets[k]}</dd>
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
    <ul className={styles.sources}>
      {rows.map((s) => (
        <li key={s.source}>
          <span className="w-[104px] flex-none"><SourceMark source={s.source} /></span>
          <Chip tone={STATUS_TONE[s.status]}>{s.status}</Chip>
          <span className="font-mono text-[10px] text-mute">{s.n_records} record{s.n_records === 1 ? "" : "s"}</span>
          {s.error && <span className={styles.sourceError}>{s.error}</span>}
        </li>
      ))}
    </ul>
  );
}

export function ReportPanel({ state }: { state: RunState }) {
  const report = state.report;
  const sources = selectSourceStatus(state);
  const verified = state.claimOrder.filter((c) => state.claims[c].status === "verified").length;
  const citationsRef = useRef<HTMLDetailsElement>(null);

  // Citation links must reveal the source list before the browser scrolls to an anchor.
  useEffect(() => {
    const reveal = () => {
      if (!/^#cite-\d+$/.test(window.location.hash)) return;
      const details = citationsRef.current;
      const target = details?.querySelector(window.location.hash);
      if (!details || !target) return;
      details.open = true;
      target.scrollIntoView({ block: "nearest" });
    };
    reveal();
    window.addEventListener("hashchange", reveal);
    return () => window.removeEventListener("hashchange", reveal);
  }, [report]);

  const revealCitation = (event: MouseEvent<HTMLDivElement>) => {
    const anchor = event.target instanceof Element ? event.target.closest("a") : null;
    if (/^#cite-\d+$/.test(anchor?.getAttribute("href") ?? "") && citationsRef.current) citationsRef.current.open = true;
  };

  return (
    <div className={styles.report} onClickCapture={revealCitation}>
      <Answer scores={state.scores} verifiedClaims={verified} />
      {report?.summary_md ? <Findings summary={report.summary_md} /> : (
        <section className={styles.card}>
          <h2 className={styles.heading}>Findings are on the way</h2>
          <p className={styles.empty}>The report will appear when the investigation is complete.</p>
        </section>
      )}
      <div className={styles.supporting}>
        {state.scores && <ReportDetail title="Score breakdown"><ScoreBreakdown scores={state.scores} /></ReportDetail>}
        {!!report?.citations?.length && (
          <details ref={citationsRef} className={styles.details}>
            <summary>References · {report.citations.length}<ChevronDown size={15} /></summary>
            <ol className={clsx(styles.detailBody, styles.citations)}>{report.citations.map((c, i) => <Citation key={i} text={c} n={i + 1} />)}</ol>
          </details>
        )}
        {report && report.by_year?.length > 0 && <ReportDetail title="Similar projects over time"><ByYear rows={report.by_year} /></ReportDetail>}
        {state.facets && <ReportDetail title="How your idea was interpreted"><FacetList facets={state.facets} /></ReportDetail>}
        {sources.length > 0 && <ReportDetail title={`Search coverage · ${sources.length} sources`}><Sources rows={sources} /></ReportDetail>}
      </div>
    </div>
  );
}
