import { HeroIslands } from "@/components/HeroIslands";
import { IdeaInput } from "@/components/IdeaInput";
import { SiteNav } from "@/components/SiteNav";

export default function Home() {
  return (
    <>
      {/* the sea is the page: it sits behind everything and fills the window */}
      <HeroIslands className="landing-ocean pointer-events-none fixed inset-0 bg-sea" />
      <SiteNav />
      {/* shrink-0: a flex item with overflow hidden may shrink below its content, which would clip the form */}
      <main className="landing-main relative z-10 flex shrink-0 grow items-center overflow-hidden">
        <div className="mx-auto grid w-full max-w-[1320px] grid-cols-[minmax(0,1fr)] items-center gap-10 px-5 py-10 sm:px-10 lg:grid-cols-[minmax(0,520px)_minmax(0,1fr)]">
          <div className="landing-content mx-auto w-full max-w-[520px]">
            {/* what the mark in the corner stands for: rises just before the headline, so it reads as the byline to it */}
            <p className="label animate-rise text-mute" style={{ animationDelay: "0.04s" }}>
              Similarity Lookup for Originality Prediction
            </p>
            <h1 className="mt-3 animate-rise font-display text-[46px] leading-[1.04] tracking-[-0.045em] text-bone sm:text-[64px]" style={{ animationDelay: "0.08s" }}>
              How original<br />is your idea?
            </h1>
            <div className="landing-pitch mt-7">
              <IdeaInput />
            </div>
          </div>
          {/* an empty column: the islands in the sea behind show through here, so they never slide under the form */}
          <div className="hidden h-[600px] lg:block" aria-hidden />
        </div>
      </main>

      <footer className="relative z-10 mt-auto flex flex-none flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-4 text-[12.5px] text-on-sea sm:px-8">
        <span>Built at Hack the North 2026</span>
      </footer>
    </>
  );
}
