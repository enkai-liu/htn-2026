"use client";
import { useEffect, useState } from "react";
import { loadSlopIndex, placeboRate, type SlopResult } from "@/lib/slop";
import { SlopShareChart, SlopTable } from "./SlopCharts";

function effectSize(d: number): string {
  const a = Math.abs(d);
  return a < 0.147 ? "negligible" : a < 0.33 ? "small" : a < 0.474 ? "medium" : "large";
}

function SampleStamp() {
  return <span className="hazard ml-auto flex-none whitespace-nowrap px-1.5 py-[1px] font-mono text-[9px] font-medium uppercase tracking-[0.16em]">Sample data</span>;
}

export function SlopIndexView() {
  const [result, setResult] = useState<SlopResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    loadSlopIndex()
      .then((r) => { if (alive) setResult(r); })
      .catch(() => { if (alive) setError("Neither the investigation endpoint nor the bundled sample file could be loaded."); });
    return () => { alive = false; };
  }, []);

  if (error) return <p role="alert" className="border border-vermilion/50 bg-vermilion/[0.07] px-4 py-3 text-[13px] text-bone">{error}</p>;
  if (!result) return <p className="py-24 text-center font-mono text-[10.5px] uppercase tracking-[0.2em] text-faint">Loading the investigation…</p>;

  const { data, isSample } = result;
  const fpr = placeboRate(data);
  const tie = data.tie_in;
  const placeboYears = data.placebo?.years ?? [];
  const last = [...data.years].sort((a, b) => a.year - b.year).at(-1);
  const lastShare = last ? ((last.ai_high + last.mixed_high) / last.scanned) * 100 : null;
  const totalScanned = data.years.reduce((a, y) => a + y.scanned, 0);

  return (
    <>
      {isSample && (
        <>
          {/* corner ribbon: visible on every scroll position whenever the fallback file is in use */}
          <div className="pointer-events-none fixed bottom-[38px] right-[-62px] z-40 w-[240px] -rotate-45 bg-amber py-1.5 text-center font-mono text-[11px] font-medium uppercase tracking-[0.22em] text-white shadow-[0_6px_24px_rgb(0_0_0/0.18)]" aria-hidden>
            Sample data
          </div>
          <div className="hazard mb-6 px-4 py-3" role="note">
            <p className="font-mono text-[11px] font-medium uppercase tracking-[0.16em]">Sample data — not results</p>
            <p className="mt-1 text-[13px] leading-snug text-bone">
              These numbers are illustrative placeholders so the page can be built and rehearsed: {result.reason ?? "the live investigation results are not available"}.
              Nothing below is a finding. Real figures replace this file when <code className="font-mono text-[12px] text-amber">GET /api/investigation/slop-index</code> answers.
            </p>
          </div>
        </>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section className="plate flex flex-col p-0">
          <div className="plate-head"><span className="idx">A</span><span className="ttl min-w-0 truncate">AI-written share of pitches, by year</span>{isSample && <SampleStamp />}</div>
          <div className="flex min-h-0 flex-1 flex-col p-4 sm:p-5">
            <SlopShareChart data={data} />
          </div>
        </section>

        <div className="flex flex-col gap-4">
          <section className="plate p-0">
            <div className="plate-head"><span className="idx">B</span><span className="ttl min-w-0 truncate">Placebo: false-positive rate</span>{isSample && <SampleStamp />}</div>
            <div className="p-4">
              <div className="flex items-baseline gap-2">
                <span className="font-display text-[54px] leading-none text-bone">{fpr == null ? "–" : `${(fpr * 100).toFixed(1)}%`}</span>
                {data.placebo?.flagged != null && data.placebo?.scanned != null && <span className="font-mono text-[11px] text-mute">{data.placebo.flagged} of {data.placebo.scanned} pitches</span>}
              </div>
              {data.placebo?.ci_low != null && data.placebo?.ci_high != null && <p className="mt-1 font-mono text-[10.5px] text-mute">95% Wilson interval {(data.placebo.ci_low * 100).toFixed(1)}–{(data.placebo.ci_high * 100).toFixed(1)}%</p>}
              <p className="mt-2 text-[13px] leading-relaxed text-bone-dim">
                Pitches from {placeboYears.length ? placeboYears.join(", ") : "before late 2022"} were written before ChatGPT existed, so any flag there can only be a false alarm.
                That makes this the detector&apos;s <em>measured</em> false-positive rate on hackathon write-ups, and every later bar should be read against it
                {lastShare != null && fpr ? <> ({last!.year}: {lastShare.toFixed(0)}%, about {Math.round(lastShare / (fpr * 100))}× the placebo rate)</> : null}.
              </p>
            </div>
          </section>

          <section className="plate p-0">
            <div className="plate-head"><span className="idx">C</span><span className="ttl">Tie-in test</span>{isSample && <SampleStamp />}</div>
            {tie ? (
              <div className="p-4">
                <p className="font-display text-[19px] italic leading-snug text-bone-dim">Are AI-flagged pitches also less original?</p>
                <div className="mt-2 flex items-baseline gap-2.5">
                  <span className="whitespace-nowrap font-display text-[40px] leading-none text-bone">δ = {tie.cliffs_delta.toFixed(2)}</span>
                  <span className="font-mono text-[10.5px] leading-snug text-mute">Cliff&apos;s delta<br />{effectSize(tie.cliffs_delta)} effect</span>
                </div>
                <p className="mt-1 font-mono text-[10.5px] text-mute">p = {tie.p_value < 0.001 ? tie.p_value.toExponential(1) : tie.p_value.toFixed(3)}{tie.test ? ` · ${tie.test}` : ""}</p>

                <div className="mt-3 flex flex-col gap-2" role="img" aria-label={`Median nearest-neighbour similarity: flagged ${tie.median_nn_sim_flagged}, human ${tie.median_nn_sim_human}`}>
                  {[
                    { label: "AI-flagged pitches", v: tie.median_nn_sim_flagged, n: tie.n_flagged, color: "#d95926" },
                    { label: "Human-read pitches", v: tie.median_nn_sim_human, n: tie.n_human, color: "#3987e5" },
                  ].map((b) => (
                    <div key={b.label}>
                      <div className="flex items-baseline justify-between font-mono text-[10.5px]">
                        <span className="flex items-center gap-1.5 text-bone-dim"><span className="size-2" style={{ background: b.color }} />{b.label}{b.n != null && <span className="text-faint">n = {b.n}</span>}</span>
                        <span className="text-bone">{b.v.toFixed(2)}</span>
                      </div>
                      <div className="mt-1 h-[6px] bg-ink-700"><div className="h-full rounded-r-[3px]" style={{ width: `${b.v * 100}%`, background: b.color }} /></div>
                    </div>
                  ))}
                  <p className="font-mono text-[9.5px] text-faint">median similarity to the 5 nearest neighbours in the corpus (0 to 1)</p>
                </div>

                <p className="mt-3 text-[13px] leading-relaxed text-bone-dim">
                  {tie.cliffs_delta > 0
                    ? "Flagged pitches sit closer to their nearest neighbours than human-read pitches from the same year: they are measurably more like what already exists."
                    : "Flagged pitches are not closer to their nearest neighbours than human-read ones: no evidence here that they are less original."}
                  {" "}This is association, not cause, and it is the reason Whitespace keeps Voice separate from the originality headline.
                </p>
              </div>
            ) : <p className="p-4 text-[13px] text-mute">The tie-in test has not been run yet.</p>}
          </section>

          {typeof data.user_percentile === "number" && (
            <section className="plate p-4">
              <p className="label">Your last pitch</p>
              <p className="mt-1 text-[13px] leading-relaxed text-bone-dim">Its sentence-level AI share is higher than {Math.round(data.user_percentile * 100)}% of this year&apos;s scanned pitches.</p>
            </section>
          )}
        </div>
      </div>

      <section className="plate mt-4 p-0">
        <div className="plate-head"><span className="idx">D</span><span className="ttl">The numbers behind the chart</span>{isSample && <SampleStamp />}</div>
        <div className="p-4 sm:p-5"><SlopTable data={data} /></div>
      </section>

      <section className="mt-4 grid gap-4 md:grid-cols-2">
        <div className="plate p-5">
          <h2 className="font-display text-[24px] leading-tight text-bone">Method</h2>
          <ul className="mt-3 flex list-none flex-col gap-2 text-[13px] leading-relaxed text-bone-dim">
            <li><strong className="text-bone">Year-stratified.</strong> The same number of pitches per year{totalScanned ? ` (${totalScanned.toLocaleString("en-US")} in total here)` : ""}, so a big year cannot drown a small one.</li>
            <li><strong className="text-bone">Length-controlled.</strong> English pitches of at least 600 characters, truncated to 1,800 at a sentence boundary: detectors behave differently on short text, so every pitch gets the same window.</li>
            <li><strong className="text-bone">High confidence only.</strong> A pitch counts as flagged only when GPTZero classes it AI or mixed with <code className="font-mono text-[12px] text-amber">confidence_category = high</code>. No raw probabilities are reported anywhere.</li>
            <li><strong className="text-bone">Intervals, not points.</strong> Every share carries a 95% Wilson interval; the whiskers are the honest width of what {data.years[0]?.scanned ?? "the"} pitches per year can tell you.</li>
            <li><strong className="text-bone">A placebo.</strong> Pre-ChatGPT years measure the detector&apos;s false-positive rate on this exact genre of writing.</li>
          </ul>
        </div>
        <div className="plate p-5">
          <h2 className="font-display text-[24px] leading-tight text-bone">What this page will never do</h2>
          <ul className="mt-3 flex list-none flex-col gap-2 text-[13px] leading-relaxed text-bone-dim">
            <li><strong className="text-bone">Name a project.</strong> Aggregates only. No project, team, student or URL appears here or in the published CSV.</li>
            <li><strong className="text-bone">Call AI-written &ldquo;unoriginal&rdquo;.</strong> An AI-polished write-up can describe a genuinely new project. The tie-in test asks whether the two go together on average; it says nothing about any single pitch.</li>
            <li><strong className="text-bone">Accuse.</strong> A detector flag is a statistical read with a measured error rate, shown above. It is not evidence about an individual.</li>
          </ul>
          <p className="mt-3 font-mono text-[10px] leading-snug text-faint">{data.detector ?? "Detector: GPTZero"} · {data.corpus ?? "Corpus: public Devpost pitches"}</p>
        </div>
      </section>
    </>
  );
}
