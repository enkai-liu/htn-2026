"use client";
// The floating card beside the map: what you clicked, in one glance, with a way through to the full page.
import { ArrowUpRight, ChevronDown, LoaderCircle, X } from "lucide-react";
import Link from "next/link";
import { FACET_KEYS } from "@/lib/islandLayout";
import { fmtSim, safeHref, shortModel, splitEnumerated } from "@/lib/format";
import type { GraphNode } from "@/lib/types";
import { EvidenceDetail, listingLabel } from "../EvidenceDetail";
import { Chip, InferredTag, SourceMark } from "../ui";
import { useRun } from "./RunProvider";

function SimilarityBar({ value }: { value: number | null | undefined }) {
  if (value == null) return null;
  return (
    <div className="mt-3">
      <div className="flex items-baseline justify-between text-[12px] text-mute"><span>Similarity to your idea</span><span className="font-mono text-bone">{fmtSim(value)}</span></div>
      <div className="mt-1 h-[5px] overflow-hidden rounded-full bg-ink-700"><div className="h-full rounded-full bg-bone transition-[width] duration-700" style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} /></div>
    </div>
  );
}

/**
 * Facets the conductor returns as enumerations rather than prose. `mechanism` is an ordered pipeline,
 * so it gets step numerals; the other two are unordered sets. `twist`, `purpose` and `audience` stay
 * prose — `twist` in particular often ends in a contrastive ", rather than …" that a split would sever.
 */
const STEP_FACETS = new Set(["mechanism"]);
const SET_FACETS = new Set(["data", "domain"]);

function FacetRow({ label, value }: { label: string; value: string }) {
  const ordered = STEP_FACETS.has(label);
  const items = ordered || SET_FACETS.has(label) ? splitEnumerated(value) : [];
  // Three or more is where a comma-spliced value stops reading as a sentence. Below that, prose is
  // clearer and safer: a lone comma is as likely to join a compound phrase as to separate two items.
  const asList = items.length > 2;
  const List = ordered ? "ol" : "ul";
  return (
    <div className="border-b border-line py-2.5 last:border-b-0">
      <dt className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-faint">{label}</dt>
      <dd className="mt-1.5 text-[13px] leading-snug text-bone">
        {asList ? (
          // One gutter for both kinds, so the facets line up down the card: numerals where the order is
          // the point, a bullet where it is not. Separators between inline items dangle at line ends.
          <List className="space-y-1">
            {items.map((it, i) => (
              <li key={it} className="flex gap-2">
                {ordered ? (
                  <span className="flex-none select-none font-mono text-[9.5px] leading-[1.45] tabular-nums text-amber">{String(i + 1).padStart(2, "0")}</span>
                ) : (
                  // shares the text's line box so it sits on the same baseline; muted, because the marker
                  // carries no meaning here — amber is reserved for the steps, where the order is the point
                  <span className="w-[14px] flex-none select-none text-center leading-snug text-line-strong">·</span>
                )}
                <span className="min-w-0">{it}</span>
              </li>
            ))}
          </List>
        ) : (
          value
        )}
      </dd>
    </div>
  );
}

export function DetailCard({ node }: { node: GraphNode }) {
  const { run, cards, select, hrefFor, onRescore, busyMid } = useRun();
  const { state } = run;
  const close = () => select(null);

  let body: React.ReactNode;
  let eyebrow: React.ReactNode;
  let title = node.label;

  if (node.kind === "idea") {
    eyebrow = "Your idea";
    title = "The centre of the map";
    body = (
      <>
        <p className="line-clamp-3 font-display text-[14.5px] italic leading-snug text-mute">“{state.ideaText}”</p>
        {state.facets && (
          <dl className="mt-4 border-t border-line">
            {FACET_KEYS.map((k) => {
              const v = state.facets?.[k];
              return v ? <FacetRow key={k} label={k} value={String(v)} /> : null;
            })}
          </dl>
        )}
      </>
    );
  } else if (node.kind === "mutation") {
    const mid = node.id.slice("mut:".length);
    const m = state.mutations[mid];
    eyebrow = <span className="text-teal">Mutation{m ? ` · ${m.facet}` : ""}</span>;
    body = m ? (
      <>
        <p className="text-[13.5px] leading-snug text-bone"><span className="text-mute line-through decoration-1">{m.frm}</span> → <span className="font-medium">{m.to}</span></p>
        <p className="mt-2 text-[13px] leading-relaxed text-bone-dim">{m.rationale}</p>
        <SimilarityBar value={node.similarity} />
        {m.delta != null && <p className="mt-2 text-[12.5px] text-teal">Originality {m.delta >= 0 ? "+" : ""}{Math.round(m.delta)} after re-scoring</p>}
        <div className="mt-4 flex items-center gap-2">
          <button type="button" className="btn btn-primary btn-sm !h-[32px] !px-4 !text-[12.5px]" onClick={() => onRescore(mid)} disabled={busyMid === mid}>
            {busyMid === mid && <LoaderCircle size={13} className="animate-spin" />} Re-score
          </button>
          <Link href={hrefFor("coach")} className="text-[12.5px] text-mute underline-offset-2 hover:text-bone hover:underline">Open in Coach</Link>
        </div>
      </>
    ) : <p className="text-[13px] text-mute">The mutator has not described this one yet.</p>;
  } else if (node.kind === "prior") {
    const sample = state.priorSamples[Number(node.id.slice("prior:".length)) - 1];
    eyebrow = "LLM prior";
    title = sample ? shortModel(sample.model) : node.label;
    body = (
      <>
        {sample && <p className="text-[13.5px] leading-relaxed text-bone">{sample.text}</p>}
        <SimilarityBar value={node.similarity} />
      </>
    );
  } else {
    const card = cards.find((c) => c.nodeId === node.id);
    const href = safeHref(node.url ?? card?.records[0]?.url);
    const inferredYear = !!card?.records.length && card.records.every((r) => r.date_precision === "inferred");
    eyebrow = (
      <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        {(card?.sources.length ? card.sources : node.source ? [node.source] : []).map((s) => <SourceMark key={s} source={s} />)}
        {(card?.year ?? node.year) != null && <span className="text-mute">{card?.year ?? node.year}{inferredYear && <InferredTag />}</span>}
      </span>
    );
    title = card?.title ?? node.label;
    body = (
      <>
        {card?.summary && <p className="line-clamp-5 text-[13.5px] leading-relaxed text-bone-dim">{card.summary}</p>}
        <SimilarityBar value={card?.similarity ?? node.similarity} />
        {!!(card?.badges.length ?? node.badges.length) && (
          <div className="mt-3 flex flex-wrap gap-1">
            {(card?.badges ?? node.badges).map((b) => <Chip key={b} tone={b === "winner" ? "amber" : b === "conflict" || b === "source_failed" ? "red" : undefined}>{b.replace(/_/g, " ")}</Chip>)}
          </div>
        )}
        {!!card?.possibleSameAs.length && <p className="mt-2 text-[12.5px] text-amber">Possibly the same as {card.possibleSameAs.join(", ")}: left open for lack of evidence.</p>}
        {href && (
          <div className="mt-3 text-[12.5px]">
            <a href={href} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-0.5 text-mute hover:text-bone">Source <ArrowUpRight size={13} /></a>
          </div>
        )}
        {/* the receipts: the listings this entity was fused from, and which fields came from where */}
        {card && !!card.records.length && (
          <details className="group mt-3 border-t border-line pt-3">
            <summary className="flex cursor-pointer list-none items-center gap-1 text-[12.5px] text-mute transition-colors hover:text-bone">
              <ChevronDown size={13} className="flex-none transition-transform group-open:rotate-180" />
              {listingLabel(card)}
            </summary>
            <div className="mt-2.5"><EvidenceDetail card={card} /></div>
          </details>
        )}
      </>
    );
  }

  return (
    <aside className="absolute bottom-4 right-4 top-2 z-20 flex w-[min(352px,calc(100vw-32px))] animate-rise flex-col" aria-label="Selected island">
      <div className="max-h-full overflow-y-auto rounded-[22px] border border-line bg-ink-900/95 p-5 shadow-[0_18px_60px_rgb(0_0_0/0.10)] backdrop-blur">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-[12px] text-mute">{eyebrow}</div>
            <h2 className="mt-1 font-display text-[25px] leading-[1.1] text-bone">{title}</h2>
          </div>
          <button type="button" onClick={close} className="flex size-8 flex-none items-center justify-center rounded-full bg-ink-800 text-bone-dim transition-colors hover:bg-ink-700" aria-label="Close"><X size={15} /></button>
        </div>
        <div className="mt-3">{body}</div>
      </div>
    </aside>
  );
}
