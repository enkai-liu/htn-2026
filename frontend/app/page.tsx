import { HeroIslands } from "@/components/HeroIslands";
import { IdeaInput } from "@/components/IdeaInput";
import { SiteNav } from "@/components/SiteNav";

export default function Home() {
  return (
    <>
      <SiteNav />
      {/* shrink-0: a flex item with overflow hidden may shrink below its content, which would clip the form */}
      <main className="flex shrink-0 grow items-center overflow-hidden">
        <div className="mx-auto grid w-full max-w-[1240px] grid-cols-[minmax(0,1fr)] items-center gap-10 px-5 py-12 sm:px-8 lg:grid-cols-[minmax(0,600px)_minmax(0,1fr)]">
          <div className="mx-auto w-full max-w-[600px]">
            <h1 className="animate-rise font-display text-[44px] leading-[1] tracking-[-0.01em] text-bone sm:text-[60px]" style={{ animationDelay: "0.08s" }}>
              How original is your idea?
            </h1>
            <div className="mt-8">
              <IdeaInput />
            </div>
          </div>
          {/* the islands get a column of their own, so they never slide under the form; it bleeds out to the viewport's right edge */}
          <HeroIslands className="pointer-events-none relative -ml-8 hidden h-[580px] lg:block lg:mr-[min(-32px,calc((1240px_-_100vw)/2_-_32px))]" />
        </div>
      </main>

      <footer className="mt-auto flex flex-none flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-4 text-[12.5px] text-mute sm:px-8">
        <span>Built at Hack the North 2026</span>
      </footer>
    </>
  );
}
