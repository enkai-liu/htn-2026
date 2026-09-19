"use client";
// The listing-level receipts behind one resolved entity: every source row that was folded into it, and the
// fused fields with their provenance. Shared by the map's detail card and the classic dashboard's evidence card.
import clsx from "clsx";
import { ExternalLink } from "lucide-react";
import { fmtSim, fmtValue, safeHref, sourceColor } from "@/lib/format";
import type { EvidenceCardModel } from "@/lib/selectors";
import { Chip, InferredTag, SourceMark } from "./ui";

/** "3 listings, one project" — the merge, said out loud. */
export function listingLabel(card: EvidenceCardModel): string {
  return card.records.length > 1 ? `${card.records.length} listings, one project` : "Listing";
}

function traction(t: Record<string, unknown>): string[] {
  return Object.entries(t ?? {}).filter(([k]) => k !== "is_winner").map(([k, v]) => `${k.replace(/_/g, " ")}: ${fmtValue(v)}`);
}

export function EvidenceDetail({ card }: { card: EvidenceCardModel }) {
  const fields = Object.entries(card.entity?.fields ?? {});

  return (
    <>
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
    </>
  );
}
