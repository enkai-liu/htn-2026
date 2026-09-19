"use client";
// Small shared primitives: chart plates, chips, source marks, honesty labels, toasts.
import clsx from "clsx";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { sourceColor, sourceLabel } from "@/lib/format";

export function Plate({ index, title, right, children, className, bodyClassName }: {
  index?: string; title: string; right?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string;
}) {
  return (
    <section className={clsx("plate flex min-h-0 flex-col", className)}>
      <header className="plate-head">
        {index && <span className="idx">{index}</span>}
        <span className="ttl">{title}</span>
        {right && <span className="ml-auto flex items-center gap-2 normal-case tracking-normal">{right}</span>}
      </header>
      <div className={clsx("min-h-0 flex-1", bodyClassName)}>{children}</div>
    </section>
  );
}

export type ChipTone = "amber" | "teal" | "red" | "mute" | "bone" | undefined;

export function Chip({ tone, children, title, className, flip }: { tone?: ChipTone; children: ReactNode; title?: string; className?: string; flip?: boolean }) {
  return (
    <span className={clsx("chip", flip && "animate-flip", className)} data-tone={tone} title={title}>
      {children}
    </span>
  );
}

export function SourceMark({ source, withLabel = true }: { source: string; withLabel?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-bone-dim">
      <span className="inline-block size-[7px] rounded-full" style={{ background: sourceColor(source), boxShadow: `0 0 6px ${sourceColor(source)}` }} />
      {withLabel && sourceLabel(source)}
    </span>
  );
}

/** Hard requirement: anything the fire drill injected is labelled wherever it appears. */
export function SimulatedTag({ className }: { className?: string }) {
  return (
    <span className={clsx("hazard inline-flex h-[18px] items-center px-1.5 font-mono text-[9.5px] font-medium uppercase tracking-[0.14em]", className)}>
      Simulated — fire drill
    </span>
  );
}

/** Hard requirement: imputed values are visibly marked. */
export function InferredTag({ title }: { title?: string }) {
  return (
    <span
      className="ml-1 inline-flex h-[15px] items-center border border-dashed border-amber/60 px-1 align-middle font-mono text-[9px] uppercase tracking-[0.12em] text-amber"
      title={title ?? "This value was not stated by any source: the resolver inferred it."}
    >
      inferred
    </span>
  );
}

export function Empty({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={clsx("flex h-full min-h-24 flex-col items-center justify-center gap-1 px-6 py-8 text-center", className)}>
      <span className="font-display text-[19px] italic leading-tight text-bone-dim">{children}</span>
    </div>
  );
}

// --- toasts ----------------------------------------------------------------------------------------------------------

export interface ToastInput { title: string; body?: string; tone?: "amber" | "teal" | "red" }
interface ToastItem extends ToastInput { id: number }

const ToastContext = createContext<(t: ToastInput) => void>(() => {});
export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const push = useCallback((t: ToastInput) => {
    const id = nextId.current++;
    setItems((cur) => [...cur.slice(-3), { ...t, id }]);
    setTimeout(() => setItems((cur) => cur.filter((x) => x.id !== id)), 5200);
  }, []);
  const value = useMemo(() => push, [push]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[340px] flex-col gap-2" role="status" aria-live="polite">
        {items.map((t) => (
          <div
            key={t.id}
            className="pointer-events-auto border bg-ink-800/95 px-3.5 py-2.5 shadow-[0_12px_40px_rgb(0_0_0/0.6)] backdrop-blur"
            style={{ animation: "toast-in 0.28s cubic-bezier(0.2,0.7,0.2,1) both", borderColor: t.tone === "red" ? "var(--color-vermilion)" : t.tone === "teal" ? "var(--color-teal)" : "var(--color-amber)" }}
          >
            <div className="font-mono text-[10.5px] uppercase tracking-[0.16em]" style={{ color: t.tone === "red" ? "var(--color-vermilion)" : t.tone === "teal" ? "var(--color-teal)" : "var(--color-amber)" }}>
              {t.title}
            </div>
            {t.body && <div className="mt-1 text-[12.5px] leading-snug text-bone-dim">{t.body}</div>}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
