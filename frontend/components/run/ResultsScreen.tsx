"use client";
// Everything the scouts found, as a list you can search. The map shows where things sit; this is where you look one up.
import clsx from "clsx";
import { ArrowUpRight, ChevronDown, MapPin, Search, X } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useMemo, useState } from "react";
import { fmtMatch, fmtSim, matchOf, safeHref, sourceColor, sourceLabel } from "@/lib/format";
import type { EvidenceCardModel } from "@/lib/selectors";
import { EvidenceDetail, listingLabel } from "../EvidenceDetail";
import { Chip, SourceMark } from "../ui";
import { useRun } from "./RunProvider";
import { PageColumn } from "./RunShell";

const GRADE_RANK = { same: 3, close: 2, adjacent: 1, unrelated: 0 } as const;
const GRADE_LABEL: Partial<Record<keyof typeof GRADE_RANK, { label: string; title: string }>> = {
  same: { label: "same thing", title: "A model that read this beside your idea judged it a direct competitor, or your idea already built" },
  close: { label: "close", title: "A model that read this beside your idea judged it the same problem or mechanism, with one notable difference" },
};

/** The closest grade any of a result's listings was given. */
function gradeOf(card: EvidenceCardModel): keyof typeof GRADE_RANK | null {
  let best: keyof typeof GRADE_RANK | null = null;
  for (const r of card.records) {
    const g = r.retrieval?.grade;
    if (g && (best == null || GRADE_RANK[g] > GRADE_RANK[best])) best = g;
  }
  return best;
}

const haystack = (c: EvidenceCardModel) =>
  [c.title, c.summary, ...c.sources.map(sourceLabel), ...c.records.flatMap((r) => [r.title, r.tagline ?? "", r.url, ...(r.tags ?? []), ...(r.tech ?? [])])].join(" \n ").toLowerCase();

function Row({ card, open, onToggle, onMap }: { card: EvidenceCardModel; open: boolean; onToggle: () => void; onMap: boolean }) {
  const { select, hrefFor } = useRun();
  const grade = gradeOf(card);
  const match = matchOf(card.similarity);
  const href = safeHref(card.records[0]?.url);
  return (
    <li className="border-b border-line last:border-b-0">
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-ink-800/60">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
            <h3 className="min-w-0 truncate text-[15px] font-medium leading-snug text-bone">{card.title}</h3>
            {grade && GRADE_LABEL[grade] && <Chip tone={grade === "same" ? "bone" : "mute"} title={GRADE_LABEL[grade]!.title}>{GRADE_LABEL[grade]!.label}</Chip>}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1">
            {card.sources.map((s) => <SourceMark key={s} source={s} />)}
            {card.year != null && <span className="font-mono text-[10px] text-mute">{card.year}</span>}
          </div>
          {card.summary && <p className={clsx("mt-1.5 text-[13px] leading-snug text-bone-dim", !open && "line-clamp-2")}>{card.summary}</p>}
        </div>
        <div className="w-[64px] flex-none pt-0.5 text-right" title={`reranker score ${fmtSim(card.similarity)}`}>
          <div className="font-mono text-[15px] leading-none text-bone">{fmtMatch(card.similarity)}</div>
          <div className="mt-1.5 h-[3px] overflow-hidden rounded-full bg-ink-700">
            <div className="h-full rounded-full" style={{ width: `${(match ?? 0) * 100}%`, background: sourceColor(card.sources[0]) }} />
          </div>
        </div>
        <ChevronDown size={14} className={clsx("mt-1 flex-none text-mute transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="animate-rise border-t border-line bg-ink-800/40 px-4 py-3">
          <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12.5px]">
            {href && <a href={href} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-0.5 text-accent hover:underline">Open source <ArrowUpRight size={13} /></a>}
            {onMap && <Link href={hrefFor("")} onClick={() => select(card.nodeId)} className="inline-flex items-center gap-1 text-mute hover:text-bone"><MapPin size={13} /> Show on map</Link>}
          </div>
          <div className="label mb-1.5">{listingLabel(card)}</div>
          <EvidenceDetail card={card} />
        </div>
      )}
    </li>
  );
}

export function ResultsScreen() {
  const { cards, run, streaming } = useRun();
  const [query, setQuery] = useState("");
  const [source, setSource] = useState<string | null>(null);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const needle = useDeferredValue(query).trim().toLowerCase();

  const indexed = useMemo(() => cards.map((card) => ({ card, text: haystack(card) })), [cards]);
  const sources = useMemo(() => {
    const n = new Map<string, number>();
    for (const c of cards) for (const s of c.sources) n.set(s, (n.get(s) ?? 0) + 1);
    return [...n].sort((a, b) => b[1] - a[1]);
  }, [cards]);
  const shown = useMemo(() => {
    const words = needle.split(/\s+/).filter(Boolean);
    return indexed.filter(({ card, text }) => (!source || card.sources.includes(source)) && words.every((w) => text.includes(w))).map((x) => x.card);
  }, [indexed, needle, source]);

  const pill = (on: boolean) => clsx("flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12.5px] transition-colors",
    on ? "border-accent bg-ink-900 text-accent" : "border-line bg-ink-900/70 text-bone-dim hover:text-bone");

  return (
    <PageColumn title="Results" hint="Every company, product and project the scouts found, closest first.">
      <div className="sticky top-0 z-10 -mx-1 mb-3 bg-ink-950/90 px-1 pb-2 pt-1 backdrop-blur">
        <label className="flex h-11 items-center gap-2.5 rounded-2xl border border-line bg-ink-900 px-3.5 focus-within:border-accent">
          <Search size={16} className="flex-none text-mute" />
          <input
            type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search results by name, description or tag"
            className="min-w-0 flex-1 bg-transparent text-[14px] text-bone outline-none placeholder:text-faint [&::-webkit-search-cancel-button]:hidden" aria-label="Search results"
          />
          {query && <button type="button" onClick={() => setQuery("")} className="flex size-6 flex-none items-center justify-center rounded-full text-mute hover:bg-ink-800 hover:text-bone" aria-label="Clear search"><X size={14} /></button>}
        </label>
        {sources.length > 1 && (
          <div className="mt-2 flex flex-wrap gap-1.5" role="group" aria-label="Filter by source">
            <button type="button" className={pill(source == null)} aria-pressed={source == null} onClick={() => setSource(null)}>All <span className="font-mono text-[11px] text-mute">{cards.length}</span></button>
            {sources.map(([s, n]) => (
              <button key={s} type="button" className={pill(source === s)} aria-pressed={source === s} onClick={() => setSource(source === s ? null : s)}>
                <span className="size-[7px] rounded-full" style={{ background: sourceColor(s) }} />{sourceLabel(s)} <span className="font-mono text-[11px] text-mute">{n}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {shown.length > 0 ? (
        <ol className="overflow-hidden rounded-2xl border border-line bg-ink-900" aria-label={`${shown.length} results`}>
          {shown.map((card) => <Row key={card.key} card={card} open={openKey === card.key} onToggle={() => setOpenKey(openKey === card.key ? null : card.key)} onMap={!!card.nodeId && !!run.state.graph.nodes[card.nodeId]} />)}
        </ol>
      ) : (
        <p className="rounded-2xl border border-line bg-ink-900 px-4 py-10 text-center text-[13.5px] text-mute">
          {cards.length === 0 ? (streaming ? "The scouts are still out. Results land here as they come back." : "Nothing was found for this idea.") : "No result matches that search."}
        </p>
      )}
      {shown.length > 0 && (
        <p className="mt-3 px-1 text-[12px] leading-relaxed text-on-sea">
          Match is the reranker&rsquo;s score against the dataset: 50% is as close as a typical project&rsquo;s nearest neighbour, 90% is closer than 95% of them.
          A result marked <em>same thing</em> or <em>close</em> was also read beside your idea by a model, which can raise a score the reranker read too literally.
        </p>
      )}
    </PageColumn>
  );
}
