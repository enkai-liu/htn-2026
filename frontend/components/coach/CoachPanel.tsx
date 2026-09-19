"use client";
// Coaching as a conversation. The coach speaks first (what is crowded, what is already yours, one question); the
// author answers; every turn is checked against the corpus before the coach replies. When the exchange changes the
// idea, a new version of the working pitch appears on the right and is re-measured, so the number follows the
// thinking instead of leading it. The facet swaps the mutator proposed are kept as directions to talk through.
import clsx from "clsx";
import { ArrowUp, ArrowUpRight, Check, Copy, CornerDownRight, LoaderCircle, MapPin, MessageCircle, RefreshCw, Telescope } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { ApiError, createRun } from "@/lib/api";
import { fmtInt } from "@/lib/format";
import type { MutationState, RunState } from "@/lib/runReducer";
import type { CoachCite, CoachMessage, CoachPitch, TermStat } from "@/lib/types";
import { useRun } from "../run/RunProvider";
import { Chip, Empty, SourceMark, useToast } from "../ui";

const label = "font-mono text-[10px] uppercase tracking-[0.16em] text-mute";
const card = "rounded-2xl border border-line bg-ink-900";

// --- the thread --------------------------------------------------------------------------------------------------

function Cite({ c }: { c: CoachCite }) {
  const { select, hrefFor } = useRun();
  const body = (
    <>
      {c.source && <SourceMark source={c.source} withLabel={false} />}
      <span className="truncate">{c.title}</span>
      {c.year != null && <span className="text-faint">{c.year}</span>}
      {c.eid ? <MapPin size={10} className="flex-none text-faint" /> : c.url ? <ArrowUpRight size={10} className="flex-none text-faint" /> : null}
    </>
  );
  const cls = "inline-flex h-[22px] max-w-[240px] items-center gap-1.5 rounded-full border border-line bg-ink-850 px-2 text-[11.5px] text-bone-dim transition-colors hover:border-line-strong hover:text-bone";
  if (c.eid) return <Link href={hrefFor("")} onClick={() => select(`ent:${c.eid}`)} className={cls} title="Show this project on the map">{body}</Link>;
  if (c.url) return <a href={c.url} target="_blank" rel="noreferrer noopener" className={cls} title="Found by searching what you just said">{body}</a>;
  return <span className={cls}>{body}</span>;
}

function CoachTurn({ m, pitch, onPickVersion }: { m: CoachMessage; pitch?: CoachPitch; onPickVersion: (v: number) => void }) {
  return (
    <div className="animate-rise">
      <div className={clsx(label, "mb-1 text-teal")}>coach</div>
      <p className="whitespace-pre-wrap text-[14.5px] leading-[1.55] text-bone-dim">{m.text}</p>
      {!!m.cites?.length && <div className="mt-2 flex flex-wrap gap-1">{m.cites.map((c) => <Cite key={`${c.title}${c.eid ?? ""}`} c={c} />)}</div>}
      {m.pitch_version != null && (
        <button type="button" onClick={() => onPickVersion(m.pitch_version!)} className="mt-2.5 flex items-center gap-1.5 text-left text-[12px] text-teal hover:underline">
          <CornerDownRight size={12} className="flex-none" />
          <span>working idea moved to <span className="font-mono">v{m.pitch_version}</span>{pitch?.note ? `: ${pitch.note}` : ""}</span>
        </button>
      )}
      {m.question && <p className="mt-3 font-display text-[20px] leading-[1.25] text-bone">{m.question}</p>}
    </div>
  );
}

function UserTurn({ text, pending, about }: { text: string; pending?: boolean; about?: MutationState }) {
  return (
    <div className={clsx("ml-auto max-w-[85%] animate-rise rounded-2xl rounded-br-md bg-ink-800 px-3.5 py-2.5", pending && "opacity-60")}>
      {about && <div className={clsx(label, "mb-1")}>about: swapping the {about.facet}</div>}
      <p className="whitespace-pre-wrap text-[14px] leading-[1.5] text-bone">{text}</p>
    </div>
  );
}

function Thinking() {
  return (
    <div className="flex items-center gap-2 text-[12.5px] text-mute" role="status">
      <LoaderCircle size={13} className="animate-spin text-teal" />
      searching the corpus for what you just said, then thinking
    </div>
  );
}

function Composer({ suggestions, disabled, busy, onSend }: { suggestions: string[]; disabled: boolean; busy: boolean; onSend: (text: string) => void }) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);

  const send = (e?: FormEvent) => {
    e?.preventDefault();
    if (!text.trim() || busy) return;
    onSend(text);
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) send(e);
  };

  return (
    <div className="sticky bottom-0 -mx-1 bg-gradient-to-t from-ink-950 from-70% to-transparent px-1 pb-3 pt-6">
      {suggestions.length > 0 && !busy && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {suggestions.map((s) => (
            <button key={s} type="button" onClick={() => onSend(s)} className="rounded-full border border-line-strong bg-ink-900 px-3 py-1.5 text-left text-[12.5px] text-bone-dim transition-colors hover:border-teal hover:text-teal">
              {s}
            </button>
          ))}
        </div>
      )}
      <form onSubmit={send} className={clsx(card, "flex items-end gap-2 py-2 pl-3.5 pr-2 shadow-[0_8px_30px_rgb(0_0_0/0.06)] focus-within:border-line-strong")}>
        <textarea
          ref={ref} rows={1} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} maxLength={1500}
          placeholder={disabled ? "A recording. Start a live run to talk to the coach." : "Answer, push back, or float a half-formed idea…"}
          disabled={disabled} aria-label="Message the coach"
          className="max-h-40 min-h-[28px] flex-1 resize-none bg-transparent py-1 text-[14px] leading-[1.45] text-bone outline-none placeholder:text-faint disabled:cursor-not-allowed"
        />
        <button type="submit" disabled={disabled || busy || !text.trim()} aria-label="Send" className="grid size-8 flex-none place-items-center rounded-full bg-bone text-ink-900 transition-opacity disabled:opacity-25">
          {busy ? <LoaderCircle size={14} className="animate-spin" /> : <ArrowUp size={15} />}
        </button>
      </form>
    </div>
  );
}

// --- the working idea --------------------------------------------------------------------------------------------

function WorkingIdea({ pitches, shown, onPick }: { pitches: CoachPitch[]; shown: number; onPick: (v: number) => void }) {
  const { isReplay } = useRun();
  const toast = useToast();
  const router = useRouter();
  const [copied, setCopied] = useState(false);
  const [starting, setStarting] = useState(false);
  const p = pitches.find((x) => x.version === shown) ?? pitches[pitches.length - 1];
  const base = pitches.find((x) => x.version === 0);
  const checking = p.version > 0 && p.crowding == null;
  const score = p.headline ?? p.crowding;
  const baseScore = p.headline != null ? base?.headline : base?.crowding;
  const gain = score != null && baseScore != null && p.version > 0 ? Math.round((score - baseScore) * 10) / 10 : null;

  const copy = async () => {
    try { await navigator.clipboard.writeText(p.text); setCopied(true); setTimeout(() => setCopied(false), 1400); } catch { /* clipboard unavailable */ }
  };
  const investigate = async () => {
    if (isReplay) { toast({ title: "This is a recording", body: "Start a live investigation to run the full swarm on a new version.", tone: "amber" }); return; }
    setStarting(true);
    try {
      const { run_id } = await createRun(p.text);
      router.push(`/runs/${encodeURIComponent(run_id)}`);
    } catch (err) {
      setStarting(false);
      toast({ title: "Could not start a run", body: err instanceof ApiError ? err.message : undefined, tone: "red" });
    }
  };

  return (
    <section className={clsx(card, "p-4")} aria-label="Working idea">
      <div className="flex items-center gap-2">
        <span className={label}>working idea</span>
        <div className="ml-auto flex gap-1" role="tablist" aria-label="Versions">
          {pitches.map((x) => (
            <button
              key={x.version} type="button" role="tab" aria-selected={x.version === p.version} onClick={() => onPick(x.version)}
              title={x.version === 0 ? "Your original pitch" : x.note}
              className={clsx("h-[22px] rounded-full px-2 font-mono text-[10.5px] transition-colors", x.version === p.version ? "bg-bone text-ink-900" : "text-mute hover:bg-ink-800 hover:text-bone")}
            >
              v{x.version}{(x.headline ?? x.crowding) != null && <span className="ml-1 opacity-70">{Math.round((x.headline ?? x.crowding)!)}</span>}
            </button>
          ))}
        </div>
      </div>

      <p key={p.version} className="mt-3 animate-rise font-display text-[18.5px] leading-[1.3] text-bone">{p.text}</p>
      {p.version > 0 && p.note && <p className="mt-1.5 text-[12px] text-teal">{p.note}</p>}

      <div className="mt-3.5 border-t border-line pt-3">
        {checking ? (
          <div className="flex items-center gap-2 text-[12.5px] text-mute" role="status"><LoaderCircle size={13} className="animate-spin text-teal" /> checking this version against the corpus</div>
        ) : score == null ? (
          <p className="text-[12.5px] text-mute">Not measured: no prior art was retrieved for this version.</p>
        ) : (
          <div className="flex items-baseline gap-2" title={p.headline != null ? "Originality with crowding re-measured for this version; the other axes are held at the run's values." : "Crowding axis, re-measured by re-running retrieval on this version."}>
            <span key={`${p.version}-${score}`} className="animate-flip font-display text-[34px] leading-none text-bone">{Math.round(score)}</span>
            <span className="text-[12px] text-mute">{p.headline != null ? "originality" : "crowding"}</span>
            {gain != null && gain !== 0 && <span className={clsx("ml-auto font-mono text-[12px]", gain > 0 ? "text-teal" : "text-vermilion")}>{gain > 0 ? "+" : ""}{gain} vs your original</span>}
          </div>
        )}
        {p.calibrated === false && !checking && <p className="mt-1 text-[11px] text-amber">Uncalibrated: measured against known neighbours only.</p>}
      </div>

      {!!p.nearest?.length && !checking && (
        <div className="mt-3">
          <div className={clsx(label, "mb-1.5")}>closest to this version</div>
          <div className="flex flex-wrap gap-1">{p.nearest.map((c) => <Cite key={`${c.title}${c.eid ?? ""}`} c={c} />)}</div>
        </div>
      )}

      <div className="mt-3.5 flex flex-wrap gap-1.5">
        <button type="button" className="btn btn-sm" onClick={copy}>{copied ? <Check size={11} /> : <Copy size={11} />} {copied ? "Copied" : "Copy pitch"}</button>
        {p.version > 0 && (
          <button type="button" className="btn btn-sm btn-teal" onClick={investigate} disabled={starting || checking} title="Run the whole swarm (scouts, debate, verification) on this version">
            {starting ? <LoaderCircle size={11} className="animate-spin" /> : <Telescope size={11} />} Investigate this version
          </button>
        )}
      </div>
    </section>
  );
}

// --- directions and context --------------------------------------------------------------------------------------

function Direction({ m, onTalk, onRescore, busy, disabled }: { m: MutationState; onTalk: () => void; onRescore: () => void; busy: boolean; disabled: boolean }) {
  return (
    <li className="border-t border-line py-2.5 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex items-center gap-2">
        <Chip tone="teal">{m.facet}</Chip>
        {m.delta == null
          ? <LoaderCircle size={11} className="ml-auto animate-spin text-mute" />
          : <span className={clsx("ml-auto font-mono text-[11px]", m.delta > 0 ? "text-teal" : "text-mute")} title="Change in crowding if you made this swap, measured by re-running retrieval">{m.delta > 0 ? "+" : ""}{m.delta}</span>}
      </div>
      <p className="mt-1 text-[13px] leading-snug text-bone">{m.to}</p>
      <p className="mt-0.5 text-[11.5px] leading-snug text-mute">{m.rationale}</p>
      <div className="mt-1.5 flex gap-1.5">
        <button type="button" className="btn btn-sm" onClick={onTalk} disabled={disabled}><MessageCircle size={11} /> Talk it through</button>
        <button type="button" className="btn btn-sm" onClick={onRescore} disabled={busy} aria-label={`Re-score ${m.mid}`} title="Re-run retrieval for this swap">
          {busy ? <LoaderCircle size={11} className="animate-spin" /> : <RefreshCw size={11} />}
        </button>
      </div>
    </li>
  );
}

function Terms({ title, blurb, terms, kind }: { title: string; blurb: string; terms: TermStat[]; kind: "whitespace" | "cliche" }) {
  return (
    <div>
      <div className={clsx(label, kind === "whitespace" && "text-teal")}>{title}</div>
      <p className="mt-0.5 text-[11px] leading-snug text-mute">{blurb}</p>
      <div className="mt-1.5 flex flex-wrap gap-1">
        {terms.map((t) => (
          <Chip key={t.term} tone={kind === "whitespace" ? "teal" : "mute"} title={kind === "cliche" ? `significance ${t.score?.toFixed(1) ?? "–"}` : `${fmtInt(t.global_count)} in the corpus · ${fmtInt(t.neighbourhood_count)} near you`}>{t.term}</Chip>
        ))}
      </div>
    </div>
  );
}

// --- the page ----------------------------------------------------------------------------------------------------

export function CoachPanel({ state, footer }: { state: RunState; footer?: ReactNode }) {
  const { isReplay, onCoachSay, coachBusy, pendingSay, onRescore, busyMid } = useRun();
  const { coach, pitches, mutations, mutationOrder } = state;
  const latest = pitches.length ? pitches[pitches.length - 1].version : 0;
  // a pick only holds until the next version arrives: a new version always comes to the front
  const [picked, setPicked] = useState<{ version: number; latest: number } | null>(null);
  const shown = picked && picked.latest === latest && pitches.some((p) => p.version === picked.version) ? picked.version : latest;
  const pick = (version: number) => setPicked({ version, latest });

  const endRef = useRef<HTMLDivElement>(null);
  const turns = coach.length + (pendingSay ? 1 : 0);
  useEffect(() => { if (turns > 1) endRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [turns, coachBusy]);

  const whitespace = state.report?.whitespace ?? [];
  const cliches = state.report?.cliches ?? [];
  const last = coach[coach.length - 1];
  const suggestions = last?.role === "coach" && !pendingSay ? last.suggestions ?? [] : [];
  const waiting = coachBusy || (isReplay && last?.role === "user" && !state.finished);

  if (!coach.length && !mutationOrder.length) return <div className={card}><Empty>The coach joins once the scores are in.</Empty></div>;

  const talk = (m: MutationState) => onCoachSay(`Let's talk through swapping the ${m.facet}: ${m.to}`, m.mid);

  return (
    <div className="grid gap-x-8 gap-y-5 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-h-[calc(100dvh-260px)] min-w-0 flex-col">
        <div className="flex flex-1 flex-col gap-6 pb-2" aria-live="polite">
          {isReplay && coach.some((m) => m.role === "user") && <p className={label}>a recorded conversation · the author&apos;s turns are part of the recording</p>}
          {!coach.length && <p className="text-[13.5px] text-mute">{isReplay ? "This recording predates the coaching conversation. The directions on the right are what the coach proposed." : "Tell the coach what you care about in this idea, or pick a direction on the right to talk through."}</p>}
          {coach.map((m) => m.role === "coach"
            ? <CoachTurn key={m.id} m={m} pitch={pitches.find((p) => p.version === m.pitch_version)} onPickVersion={pick} />
            : <UserTurn key={m.id} text={m.text} about={m.mid ? mutations[m.mid] : undefined} />)}
          {pendingSay && <UserTurn text={pendingSay} pending />}
          {waiting && <Thinking />}
          <div ref={endRef} className="scroll-mb-44" />
        </div>
        <Composer suggestions={suggestions} disabled={isReplay} busy={coachBusy} onSend={(t) => onCoachSay(t)} />
      </div>

      <aside className="flex flex-col gap-4 lg:sticky lg:top-0 lg:max-h-[calc(100dvh-200px)] lg:self-start lg:overflow-y-auto lg:pb-4">
        {pitches.length > 0 && <WorkingIdea pitches={pitches} shown={shown} onPick={pick} />}

        {mutationOrder.length > 0 && (
          <section className={clsx(card, "p-4")} aria-label="Directions">
            <div className={clsx(label, "mb-2.5")}>directions to talk through</div>
            <ul>
              {mutationOrder.map((mid) => (
                <Direction key={mid} m={mutations[mid]} onTalk={() => talk(mutations[mid])} onRescore={() => onRescore(mid)} busy={busyMid === mid} disabled={coachBusy} />
              ))}
            </ul>
          </section>
        )}

        {(whitespace.length > 0 || cliches.length > 0) && (
          <details className={clsx(card, "group p-4")}>
            <summary className={clsx(label, "cursor-pointer list-none select-none group-open:mb-3")}>what the corpus says around you <span className="text-faint group-open:hidden">+</span></summary>
            <div className="flex flex-col gap-4">
              {whitespace.length > 0 && <Terms kind="whitespace" title="open ground" blurb="Common across the corpus, (almost) absent among your neighbours." terms={whitespace} />}
              {cliches.length > 0 && <Terms kind="cliche" title="clichés here" blurb="Over-represented among your neighbours." terms={cliches} />}
            </div>
          </details>
        )}
        {footer}
      </aside>
    </div>
  );
}
