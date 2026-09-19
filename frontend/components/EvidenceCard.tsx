"use client";
import clsx from "clsx";
import { ChevronDown, ExternalLink, Trophy } from "lucide-react";
import { memo, useEffect, useRef, useState } from "react";
import { fmtSim, fmtValue, safeHref, sourceColor } from "@/lib/format";
import type { EvidenceBadge, EvidenceCardModel } from "@/lib/selectors";
import { Chip, InferredTag, SourceMark } from "./ui";

const BADGE: Record<EvidenceBadge, { label: string; tone: "amber" | "teal" | "red" | "mute" | "bone"; title: string }> = {
  winner: { label: "winner", tone: "amber", title: "This project won a prize at its hackathon" },
  merged: { label: "merged", tone: "bone", title: "The resolver matched several listings to one real-world project" },
  conflict: { label: "conflict", tone: "red", title: "Sources disagreed on a field; see how it was settled in the ledger" },
  imputed: { label: "inferred", tone: "amber", title: "At least one field was inferred, not stated by a source" },
  ai_written: { label: "AI-written", tone: "mute", title: "GPTZero reads this write-up as AI-written with high confidence. It is still a real project, so it is kept." },
  source_failed: { label: "source failed", tone: "red", title: "This source failed at least once during the run" },
  left_open: { label: "left open", tone: "amber", title: "A possible duplicate the resolver declined to merge: insufficient evidence" },
};

function traction(t: Record<string, unknown>): string[] {
  return Object.entries(t ?? {}).filter(([k]) => k !== "is_winner").map(([k, v]) => `${k.replace(/_/g, " ")}: ${fmtValue(v)}`);
}

export const EvidenceCard = memo(function EvidenceCard({ card, selected, onSelect }: { card: EvidenceCardModel; selected: boolean; onSelect: (card: EvidenceCardModel | null) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLElement>(null);
  const expanded = open || selected;

  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);

  const fields = Object.entries(card.entity?.fields ?? {});

  return (
    <article
      ref={ref}
      className={clsx("animate-rise border bg-ink-800/50 transition-colors duration-300", selected ? "border-amber shadow-[0_0_0_1px_var(--color-amber),0_0_24px_rgb(244_185_66/0.12)]" : "border-line hover:border-line-strong")}
    >
      <button type="button" className="block w-full px-3 pb-2 pt-2.5 text-left" onClick={() => { if (expanded) { setOpen(false); if (selected) onSelect(null); } else { setOpen(true); onSelect(card); } }} aria-expanded={expanded}>
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <h3 className="truncate font-display text-[19px] leading-tight text-bone">{card.title}</h3>
            <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1">
              {card.sources.map((s) => <SourceMark key={s} source={s} />)}
              {card.year && <span className="font-mono text-[10px] text-mute">{card.year}</span>}
            </div>
          </div>
          <div className="flex-none text-right">
            <div className="font-mono text-[15px] leading-none text-bone">{fmtSim(card.similarity)}</div>
            <div className="mt-0.5 font-mono text-[8.5px] uppercase tracking-[0.14em] text-faint">similarity</div>
          </div>
          <ChevronDown size={14} className={clsx("mt-1 flex-none text-mute transition-transform", expanded && "rotate-180")} />
        </div>

        {typeof card.similarity === "number" && (
          <div className="mt-2 h-[2px] bg-ink-700">
            <div className="h-full transition-[width] duration-700" style={{ width: `${card.similarity * 100}%`, background: sourceColor(card.sources[0]) }} />
          </div>
        )}

        {card.badges.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {card.badges.map((b) => (
              <Chip key={b} tone={BADGE[b].tone} title={BADGE[b].title} flip>
                {b === "winner" && <Trophy size={9} />}
                {b === "merged" ? `merged ×${card.records.length}` : b === "left_open" && card.possibleSameAs.length ? `same as ${card.possibleSameAs[0]}? left open` : BADGE[b].label}
              </Chip>
            ))}
          </div>
        )}

        {card.summary && <p className={clsx("mt-2 text-[12.5px] leading-snug text-bone-dim", !expanded && "line-clamp-2")}>{card.summary}</p>}
      </button>

      {expanded && (
        <div className="animate-rise border-t border-line px-3 py-2.5">
          <div className="label mb-1.5">{card.records.length > 1 ? `${card.records.length} listings, one project` : "Listing"}</div>
          <ul className="flex flex-col gap-2">
            {card.records.map((r) => {
              const href = safeHref(r.url);
              return (
                <li key={r.rid} className="border-l-2 pl-2" style={{ borderColor: sourceColor(r.source) }}>
                  <div className="flex items-center gap-2">
                    <SourceMark source={r.source} />
                    {href ? (
                      <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex min-w-0 items-center gap-1 text-[12px] text-bone hover:text-amber">
                        <span className="truncate">{r.title}</span>
                        <ExternalLink size={10} className="flex-none" />
                      </a>
                    ) : <span className="truncate text-[12px] text-bone">{r.title}</span>}
                  </div>
                  {r.tagline && <p className="mt-0.5 font-display text-[14px] italic leading-snug text-bone-dim">{r.tagline}</p>}
                  <p className="mt-0.5 text-[11.5px] leading-snug text-mute">{r.description}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {typeof r.retrieval?.rerank_score === "number" && <Chip tone="mute" title="Jina reranker score for this listing">{r.retrieval.leg ?? "retrieval"} · rerank {fmtSim(r.retrieval.rerank_score)}</Chip>}
                    {r.status && r.status !== "unknown" && <Chip tone="mute">{r.status}</Chip>}
                    {r.date_precision === "inferred" && <Chip tone="amber">date inferred</Chip>}
                    {traction(r.traction).map((t) => <Chip key={t} tone="mute">{t}</Chip>)}
                    {r.tech.slice(0, 5).map((t) => (
                      <Chip key={t} tone="mute">{t}{r.field_provenance?.tech === "imputed" && <span className="text-amber"> · inferred</span>}</Chip>
                    ))}
                    {r.gptzero?.result_message && <Chip tone="mute" title={r.gptzero.result_message}>GPTZero: {r.gptzero.predicted_class} · {r.gptzero.confidence_category}</Chip>}
                  </div>
                </li>
              );
            })}
          </ul>

          {fields.length > 0 && (
            <>
              <div className="label mb-1 mt-3">Fused fields</div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11.5px]">
                {fields.map(([k, f]) => (
                  <div key={k} className="contents">
                    <dt className="font-mono text-[10.5px] text-mute">{k.replace(/_/g, " ")}</dt>
                    <dd className="min-w-0 text-bone-dim">
                      <span className={clsx(f.imputed && "text-amber")}>{fmtValue(f.value)}</span>
                      {f.imputed && <InferredTag />}
                      <span className="ml-1.5 font-mono text-[9.5px] text-faint">from {(f.provenance ?? []).map((p) => p.split(":")[0]).join(", ") || "?"}</span>
                    </dd>
                  </div>
                ))}
              </dl>
            </>
          )}
        </div>
      )}
    </article>
  );
});
