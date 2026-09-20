"use client";
// The pitch is the subject of the whole run, so the header shows it and lets you read all of it.
// A one-line quote is the trigger; the full text drops as an overlay, so opening it never reflows the map
// underneath. The author's own link lives here too, marked excluded, because this is where the run's inputs are.
import clsx from "clsx";
import { Check, ChevronDown, Copy, Link2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { safeHref, truncate } from "@/lib/format";

export function PitchDisclosure({ text, url }: { text: string; url: string | null }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);

  // Esc closes, and so does a click anywhere else: this floats over the map, so it must be easy to dismiss.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); setOpen(false); } };
    const onDown = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onDown); };
  }, [open]);

  useEffect(() => { if (!copied) return; const t = setTimeout(() => setCopied(false), 1600); return () => clearTimeout(t); }, [copied]);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false); // a denied clipboard is not worth an error state; the text is on screen to select
    }
  }, [text]);

  if (!text) {
    return <p className="hidden min-w-0 flex-1 truncate font-display text-[17px] italic text-mute md:block">Waiting for the run to start…</p>;
  }

  const href = url ? safeHref(url) : null;
  const chars = text.length.toLocaleString("en-US");

  return (
    <div ref={wrap} className="relative min-w-0 flex-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="pitch-panel"
        className="group flex w-full min-w-0 items-center gap-2 text-left"
      >
        {/* the quote reads as prose on a wide screen; on a narrow one it collapses to a label so the run still names its subject */}
        <span className="hidden min-w-0 truncate font-display text-[17px] italic text-bone-dim transition-colors group-hover:text-bone md:block">
          “{truncate(text, 140)}”
        </span>
        <span className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-mute transition-colors group-hover:text-bone md:hidden">
          Your idea
        </span>
        <ChevronDown size={13} className={clsx("flex-none text-faint transition-transform duration-200 group-hover:text-bone", open && "rotate-180")} aria-hidden />
      </button>

      {open && (
        <div
          id="pitch-panel"
          className="animate-rise absolute left-0 top-[calc(100%+10px)] z-50 w-[min(680px,calc(100vw-40px))] border border-line bg-ink-900 shadow-[0_18px_50px_-12px_rgba(0,0,0,0.45)]"
        >
          <div className="plate-head">
            <span className="ttl">The pitch</span>
            <span className="ml-auto font-mono text-[10px] tabular-nums tracking-[0.08em] text-mute">{chars} characters</span>
          </div>

          <div className="max-h-[46vh] overflow-y-auto overscroll-contain px-4 py-3.5">
            <p className="whitespace-pre-wrap font-display text-[16.5px] leading-[1.5] text-bone">{text}</p>
          </div>

          {href && (
            <div className="flex items-center gap-2 border-t border-line px-4 py-2.5">
              <Link2 size={13} className="flex-none text-mute" aria-hidden />
              <a href={href} target="_blank" rel="noopener noreferrer" className="min-w-0 truncate font-mono text-[11.5px] text-bone-dim underline decoration-dotted underline-offset-4 hover:text-bone">
                {url}
              </a>
              {/* says what the run did with it: read as context, and never counted against the author */}
              <span className="chip flex-none" data-tone="teal">read · not prior art</span>
            </div>
          )}

          <div className="flex items-center justify-between border-t border-line px-4 py-2">
            <button type="button" onClick={copy} className="flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.12em] text-mute hover:text-bone">
              {copied ? <Check size={12} className="text-teal" aria-hidden /> : <Copy size={12} aria-hidden />}
              {copied ? "Copied" : "Copy"}
            </button>
            <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-faint">esc to close</span>
          </div>
        </div>
      )}
    </div>
  );
}
