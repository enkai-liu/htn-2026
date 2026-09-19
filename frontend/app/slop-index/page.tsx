import type { Metadata } from "next";
import { SiteNav } from "@/components/SiteNav";
import { SlopIndexView } from "@/components/SlopIndexView";

export const metadata: Metadata = {
  title: "The Slop Index",
  description: "How much of hackathon writing is AI-written, year by year: GPTZero over a length-controlled, year-stratified sample of Devpost pitches, with a placebo false-positive rate.",
};

export default function SlopIndexPage() {
  return (
    <>
      <SiteNav active="/slop-index" />
      <main className="relative mx-auto w-full max-w-[1240px] flex-1 px-5 pb-16 pt-10 sm:px-8">
        <p className="label animate-rise"><span className="text-amber">✦</span> An investigation</p>
        <h1 className="mt-3 animate-rise font-display text-[52px] leading-[1] text-bone sm:text-[68px]" style={{ animationDelay: "0.06s" }}>
          The Slop <em className="text-amber">Index</em>
        </h1>
        <p className="mt-4 max-w-[68ch] animate-rise text-[15.5px] leading-relaxed text-bone-dim" style={{ animationDelay: "0.12s" }}>
          How much of what hackers write about their projects is written by a model, and did that change when ChatGPT arrived? We ran GPTZero over a
          year-stratified, length-controlled sample of public Devpost pitches, measured the detector&apos;s false-positive rate on years when the answer
          had to be zero, and then asked the question that matters to Whitespace: are AI-flagged pitches also closer to everything else?
        </p>
        {/* no transform animation on this wrapper: it would re-anchor the fixed SAMPLE DATA ribbon inside it */}
        <div className="mt-8">
          <SlopIndexView />
        </div>
      </main>
    </>
  );
}
