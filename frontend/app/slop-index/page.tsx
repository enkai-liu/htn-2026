import type { Metadata } from "next";
import { SiteNav } from "@/components/SiteNav";
import { SlopIndexView } from "@/components/SlopIndexView";

export const metadata: Metadata = {
  title: "The Slop Index",
  description: "How much of hackathon writing is AI-written, year by year.",
};

export default function SlopIndexPage() {
  return (
    <>
      <SiteNav active="/slop-index" />
      <main className="relative mx-auto w-full max-w-[1240px] flex-1 px-5 pb-16 pt-10 sm:px-8">
        <h1 className="animate-rise font-display text-[52px] leading-[1] text-bone sm:text-[68px]" style={{ animationDelay: "0.06s" }}>
          The Slop <em className="text-amber">Index</em>
        </h1>
        <p className="mt-4 max-w-[68ch] animate-rise text-[15.5px] leading-relaxed text-bone-dim" style={{ animationDelay: "0.12s" }}>
          How much of hackathon writing is AI-written, year by year: GPTZero over a sample of public Devpost pitches.
        </p>
        {/* no transform animation on this wrapper: it would re-anchor the fixed SAMPLE DATA ribbon inside it */}
        <div className="mt-8">
          <SlopIndexView />
        </div>
      </main>
    </>
  );
}
