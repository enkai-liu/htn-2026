"use client";
import { ArrowRight, Link2, LoaderCircle, Shuffle, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { ApiError, createRun } from "@/lib/api";

export const VOICE_MIN_CHARS = 250;
const SEARCH_MIN_CHARS = 1; // backend RunRequest.idea_text min_length
const MAX_CHARS = 5000;
const REPLAY_ONLY = process.env.NEXT_PUBLIC_REPLAY_ONLY === "1";

// The shuffle chip is the one-click way to fill the box for a demo, so every pitch here clears
// VOICE_MIN_CHARS on its own: a half-length sample would land in a form the Voice check abstains on.
const PITCHES: string[] = [
  "Chorus is a rehearsal room for bands whose members live in different cities. Each musician records their part in the browser, and the app time-aligns every take against a shared click track so drift never piles up. A mixing view lets anyone mute, pan or re-record a single bar without disturbing the others, and a finished song exports as stems or as one master ready to upload.",
  "Ledger Lamp points a phone camera at a paper receipt and turns it into a line-item expense claim. It reads the vendor, the tax and each item, checks them against the reimbursement policy your finance team wrote in plain English, and flags whatever is going to bounce before you submit it. Approved claims sync to the accounting system overnight.",
  "Tidewatch is a flood early-warning board for small coastal towns. It pulls tide gauges, rainfall radar and storm-surge forecasts onto one map, learns which streets historically go under at which water level, and texts residents in plain language a few hours before their own street is at risk, instead of the county-wide alert nobody acts on.",
  "Frets is a practice coach for people teaching themselves guitar. It listens through the laptop microphone, scores each attempt at a passage on timing and clean fretting, then slows down and loops the exact two bars you keep fumbling. A weekly review shows which chord changes got faster and picks a next song that stretches you only a little.",
];

export function IdeaInput() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nextPitch, setNextPitch] = useState(0);

  const chars = text.trim().length;
  const voiceReady = chars >= VOICE_MIN_CHARS;
  const searchReady = chars >= SEARCH_MIN_CHARS;

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
        <button
          type="button"
          className="chip ml-auto h-[26px] cursor-pointer gap-1.5 px-3 uppercase tracking-[inherit] text-bone-dim transition-colors hover:border-line-strong hover:text-bone"
          data-tone="mute"
          aria-label="Fill the box with an example pitch"
          onClick={() => {
            setText(PITCHES[nextPitch]);
            setError(null);
            setNextPitch((i) => (i + 1) % PITCHES.length);
          }}
        >
          <Shuffle size={12} aria-hidden /> Shuffle
        </button>
      </div>

      <div className="p-4 sm:p-5">
        <label htmlFor="idea" className="sr-only">Describe your idea</label>
        <textarea
          id="idea"
          value={text}
          onChange={(e) => setText(e.target.value.slice(0, MAX_CHARS))}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void submit(); }}
          rows={5}
          spellCheck
          placeholder="What are you thinking of building?"
          className="block w-full resize-y bg-transparent font-display text-[21px] leading-[1.4] text-bone outline-none placeholder:text-faint placeholder:italic"
        />

        {/* Never "x / 250" and no bar filling toward it: both read as a quota being spent. 250 is only the floor
            below which Voice abstains, and the real ceiling, MAX_CHARS, is worth a word only once you are near it. */}
        <div className="mt-3 flex items-start justify-between gap-4 font-mono text-[10.5px] tracking-[0.06em]">
          <span className={voiceReady ? "text-teal" : "text-amber"}>
            {chars.toLocaleString("en-US")} character{chars === 1 ? "" : "s"}
          </span>
          {!voiceReady ? (
            <span className="text-right text-mute">{(VOICE_MIN_CHARS - chars).toLocaleString("en-US")} more before the Voice check runs</span>
          ) : chars > MAX_CHARS - 500 ? (
            <span className="text-right text-mute">{(MAX_CHARS - chars).toLocaleString("en-US")} of {MAX_CHARS.toLocaleString("en-US")} left</span>
          ) : null}
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
            placeholder="Optional: your Devpost or GitHub link"
            className="w-full bg-transparent font-mono text-[12px] text-bone outline-none placeholder:text-faint"
          />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          {REPLAY_ONLY ? (
            // no backend behind this deploy: the way in is the recording, and it should not take a failed submit to find it
            <>
              <Link href="/runs/mock" className="btn btn-primary h-10 px-5">
                <ArrowRight size={14} />
                Watch a recorded run
              </Link>
              <span className="text-[12px] text-faint">This site replays a recording; live runs need the backend.</span>
            </>
          ) : (
            <button type="submit" className="btn btn-primary h-10 px-5" disabled={!searchReady || busy}>
              {busy ? <LoaderCircle size={14} className="animate-spin" /> : <ArrowRight size={14} />}
              {busy ? "Forming the team" : "Investigate"}
            </button>
          )}
        </div>

        {error && (
          <div role="alert" className="mt-4 flex animate-rise items-start gap-2.5 border border-vermilion/50 bg-vermilion/[0.07] px-3 py-2.5 text-[13px] leading-snug text-bone">
            <TriangleAlert size={15} className="mt-0.5 flex-none text-vermilion" />
            <span>
              {error}
              {REPLAY_ONLY && (
                <>
                  {" "}
                  <Link href="/runs/mock" className="text-accent underline decoration-dotted underline-offset-4 hover:text-bone">
                    Watch the recorded run instead
                  </Link>
                  .
                </>
              )}
            </span>
          </div>
        )}
      </div>
    </form>
  );
}
