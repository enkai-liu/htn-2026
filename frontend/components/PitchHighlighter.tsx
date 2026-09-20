"use client";
// Voice: GPTZero's sentence-level read of the pitch. Its own axis, never folded into the headline, and it
// shows GPTZero's own wording (result_message + confidence_category), never a raw probability.
import clsx from "clsx";
import { useMemo } from "react";
import type { Voice } from "@/lib/types";
import { Chip } from "./ui";

interface Segment { text: string; flagged: boolean; sentence: boolean }

function segments(ideaText: string, voice: Voice | null): Segment[] {
  const sentences = [...(voice?.sentences ?? [])].sort((a, b) => a.start - b.start);
  if (!sentences.length) return ideaText ? [{ text: ideaText, flagged: false, sentence: false }] : [];
  const aligned = sentences.every((s) => s.start >= 0 && s.end <= ideaText.length && s.end > s.start);
  if (!aligned) return sentences.flatMap((s, i) => [{ text: s.text, flagged: s.flagged, sentence: true }, ...(i < sentences.length - 1 ? [{ text: " ", flagged: false, sentence: false }] : [])]);
  const out: Segment[] = [];
  let cursor = 0;
  for (const s of sentences) {
    if (s.start > cursor) out.push({ text: ideaText.slice(cursor, s.start), flagged: false, sentence: false });
    out.push({ text: ideaText.slice(Math.max(cursor, s.start), s.end), flagged: s.flagged, sentence: true });
    cursor = Math.max(cursor, s.end);
  }
  if (cursor < ideaText.length) out.push({ text: ideaText.slice(cursor), flagged: false, sentence: false });
  return out;
}

const CLASS_LABEL: Record<string, string> = { human: "reads human-written", ai: "reads AI-written", mixed: "reads mixed" };

export function PitchHighlighter({ ideaText, voice, layout = "panel" }: { ideaText: string; voice: Voice | null; layout?: "panel" | "reading" }) {
  const segs = useMemo(() => segments(ideaText, voice), [ideaText, voice]);
  const total = voice?.sentences?.length ?? 0;
  const flagged = voice?.sentences?.filter((s) => s.flagged).length ?? 0;

  return (
    <div className={clsx("flex min-h-0", layout === "reading" ? "flex-col gap-5" : "h-full gap-3 px-3 py-1.5")}>
      <div className={clsx("flex flex-none flex-col justify-center gap-1.5", layout === "panel" && "w-[286px]")}>
        {!voice ? (
          <p className="font-display text-[15px] italic leading-snug text-faint">Waiting for GPTZero to read the pitch…</p>
        ) : voice.too_short ? (
          <>
            <p className="font-display text-[16px] italic leading-snug text-bone">Too short to assess reliably.</p>
            <p className="text-[11px] leading-snug text-mute">GPTZero needs ≥250 characters, so Voice abstains. The search does not.</p>
          </>
        ) : (
          <>
            <p key={voice.result_message} className="line-clamp-2 flex-none animate-rise font-display text-[15px] italic leading-[1.2] text-bone" title={voice.result_message ?? undefined}>“{voice.result_message ?? "No verdict returned."}”</p>
            <div className="flex flex-none flex-wrap gap-1">
              {voice.predicted_class && <Chip tone={voice.predicted_class === "human" ? "teal" : "amber"}>{CLASS_LABEL[voice.predicted_class] ?? voice.predicted_class}</Chip>}
              {voice.confidence_category && <Chip tone="bone">confidence: {voice.confidence_category}</Chip>}
              <Chip tone={flagged ? "amber" : "mute"} title="Sentences GPTZero flagged as likely AI-written">{flagged}/{total} sentences flagged</Chip>
              {typeof voice.neighbourhood_slop_share === "number" && <Chip tone="mute" title="Share of neighbouring pitches that GPTZero reads as AI-written">{Math.round(voice.neighbourhood_slop_share * 100)}% of neighbours AI-written</Chip>}
            </div>
          </>
        )}
      </div>

      <div className={clsx("min-h-0 min-w-0 flex-1 border-line", layout === "reading" ? "border-t pt-4" : "overflow-y-auto border-l pl-3 pr-1")}>
        {segs.length === 0 ? (
          <p className="font-display text-[15px] italic text-faint">The pitch appears here once the run starts.</p>
        ) : (
          <p className={clsx("text-bone-dim", layout === "reading" ? "text-[14px] leading-relaxed" : "text-[12.5px] leading-[1.55]")}>
            {segs.map((s, i) => (
              <span
                key={i}
                className={clsx(s.flagged && "bg-amber/15 text-bone underline decoration-amber decoration-2 underline-offset-[3px]", s.sentence && !s.flagged && voice && "text-bone/90")}
                title={s.sentence ? (s.flagged ? "GPTZero flagged this sentence as likely AI-written" : "Not flagged") : undefined}
              >
                {s.text}
              </span>
            ))}
          </p>
        )}
      </div>
    </div>
  );
}
