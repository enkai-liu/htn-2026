"use client";
import clsx from "clsx";
import { ArrowRight, Link2, LoaderCircle, Play, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { ApiError, createRun } from "@/lib/api";

export const VOICE_MIN_CHARS = 250;
const SEARCH_MIN_CHARS = 20; // backend RunRequest.idea_text min_length
const MAX_CHARS = 5000;
const REPLAY_ONLY = process.env.NEXT_PUBLIC_REPLAY_ONLY === "1";

const EXAMPLES: { label: string; text: string }[] = [
  {
    label: "An originality checker (ours)",
    text: "Whitespace checks how original your hackathon idea is before you build it. You paste a pitch, and a team of AI agents searches hundreds of thousands of past hackathon projects, startups and repos for prior art, argues about whether it is really the same idea, verifies every claim against its source, and then suggests concrete changes that move your idea into emptier territory, re-scoring each suggestion live.",
  },
  {
    label: "An AI study buddy",
    text: "StudyPal is an AI study buddy for university students. Upload your lecture slides and notes, and it uses a large language model to generate flashcards, practice quizzes and short summaries for every chapter. A chat tutor answers questions about the material at any hour, tracks which topics you keep getting wrong, and builds a personalised revision schedule before each exam.",
  },
];

export function IdeaInput() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chars = text.trim().length;
  const voiceReady = chars >= VOICE_MIN_CHARS;
  const searchReady = chars >= SEARCH_MIN_CHARS;
  const pct = Math.min(100, (chars / VOICE_MIN_CHARS) * 100);

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!searchReady || busy) return;
    setError(null);
    if (REPLAY_ONLY) {
      setError("This deployment is replay-only.");
      return;
    }
    setBusy(true);
    try {
      const { run_id } = await createRun(text.trim(), url.trim() || undefined);
      router.push(`/runs/${encodeURIComponent(run_id)}`);
    } catch (err) {
      setBusy(false);
      setError(err instanceof ApiError && err.status != null ? `The backend refused the run: ${err.message}` : "The investigation backend is not reachable right now.");
    }
  }

  return (
    <form onSubmit={submit} className="plate animate-rise p-0" style={{ animationDelay: "0.25s" }}>
      <div className="plate-head">
        <span className="ttl">Your pitch</span>
        <span className="ml-auto flex items-center gap-1.5 normal-case tracking-normal">
          {EXAMPLES.map((ex) => (
            <button key={ex.label} type="button" className="chip cursor-pointer hover:text-bone" data-tone="mute" onClick={() => { setText(ex.text); setError(null); }}>
              {ex.label}
            </button>
          ))}
        </span>
      </div>

      <div className="p-4 sm:p-5">
        <label htmlFor="idea" className="sr-only">Describe your idea</label>
        <textarea
          id="idea"
          value={text}
          onChange={(e) => setText(e.target.value.slice(0, MAX_CHARS))}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && voiceReady) void submit(); }}
          rows={7}
          spellCheck
          placeholder="What does it do, for whom, and how? Write it the way you would pitch it to a judge."
          className="block w-full resize-y bg-transparent font-display text-[21px] leading-[1.4] text-bone outline-none placeholder:text-faint placeholder:italic"
        />

        {/* character gauge with the 250 mark */}
        <div className="mt-3">
          <div className="relative h-[3px] bg-ink-700">
            <div className={clsx("absolute inset-y-0 left-0 transition-[width,background-color] duration-300", voiceReady ? "bg-teal" : "bg-amber")} style={{ width: `${pct}%` }} />
          </div>
          <div className="mt-1.5 flex items-start justify-between gap-4 font-mono text-[10.5px] tracking-[0.06em]">
            <span className={voiceReady ? "text-teal" : "text-amber"}>
              {chars.toLocaleString("en-US")} <span className="text-mute">/ {VOICE_MIN_CHARS} characters</span>
            </span>
          </div>
        </div>

        <div className="mt-4 flex items-center gap-2 border-t border-line pt-3">
          <Link2 size={14} className="flex-none text-mute" aria-hidden />
          <label htmlFor="url" className="sr-only">Optional link to a Devpost page or repository</label>
          <input
            id="url"
            type="url"
            inputMode="url"
            value={url}
            onChange={(e) => setUrl(e.target.value.slice(0, 500))}
            placeholder="Optional: a Devpost or GitHub link for this idea"
            className="w-full bg-transparent font-mono text-[12px] text-bone outline-none placeholder:text-faint"
          />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button type="submit" className="btn btn-primary h-10 px-5" disabled={!voiceReady || busy}>
            {busy ? <LoaderCircle size={14} className="animate-spin" /> : <ArrowRight size={14} />}
            {busy ? "Forming the team" : "Investigate"}
          </button>
          <Link href="/runs/mock" className="btn h-10 px-4">
            <Play size={12} />
            Watch a recorded run
          </Link>
          {!voiceReady && searchReady && !busy && (
            <button type="button" onClick={() => void submit()} className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-mute underline decoration-dotted underline-offset-4 hover:text-bone">
              Run anyway (Voice will abstain)
            </button>
          )}
        </div>

        {error && (
          <div role="alert" className="mt-4 flex animate-rise items-start gap-2.5 border border-vermilion/50 bg-vermilion/[0.07] px-3 py-2.5 text-[13px] leading-snug text-bone">
            <TriangleAlert size={15} className="mt-0.5 flex-none text-vermilion" />
            <span>
              {error}{" "}
              <Link href="/runs/mock" className="text-amber underline decoration-dotted underline-offset-4 hover:text-bone">
                Watch a recorded run instead
              </Link>
              .
            </span>
          </div>
        )}
      </div>
    </form>
  );
}
