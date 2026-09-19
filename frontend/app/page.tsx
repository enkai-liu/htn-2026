import Link from "next/link";
import { HeroIslands } from "@/components/HeroIslands";
import { IdeaInput } from "@/components/IdeaInput";
import { SiteNav } from "@/components/SiteNav";

export default function Home() {
  return (
    <>
      <SiteNav active="/" />
      {/* flex-none: a flex item with overflow hidden may shrink below its content, which would clip the form */}
      <main className="relative flex-none overflow-hidden">
        <HeroIslands className="pointer-events-none absolute -right-32 top-0 hidden h-[640px] w-[820px] lg:block xl:-right-10" />

        <div className="relative mx-auto grid w-full max-w-[1240px] gap-10 px-5 pb-16 pt-12 sm:px-8 lg:grid-cols-[minmax(0,620px)_1fr] lg:pt-20">
          <div>
            <h1 className="animate-rise font-display text-[58px] leading-[0.98] tracking-[-0.01em] text-bone sm:text-[76px]" style={{ animationDelay: "0.08s" }}>
              How original is your idea, <em className="text-amber">really?</em>
            </h1>
            <p className="mt-6 max-w-[54ch] animate-rise text-[16px] leading-relaxed text-bone-dim" style={{ animationDelay: "0.16s" }}>
              Paste a pitch. AI agents map everything already built around it, then point you at the open space.
            </p>

            <div className="mt-9">
              <IdeaInput />
            </div>
          </div>
        </div>

      </main>

      <footer className="mt-auto flex flex-none flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-4 text-[12.5px] text-mute sm:px-8">
        <span>Built at Hack the North 2026</span>
        <Link href="/slop-index" className="hover:text-bone">The Slop Index</Link>
      </footer>
    </>
  );
}
