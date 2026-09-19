import Link from "next/link";
import { HeroChart } from "@/components/HeroChart";
import { IdeaInput } from "@/components/IdeaInput";
import { SiteNav } from "@/components/SiteNav";

const STEPS = [
  {
    n: "01",
    title: "Scouts chart the neighbourhood",
    body: "One agent per source searches 260k hackathon projects, YC companies, GitHub and Hacker News. A resolver merges the same project across listings and shows every conflict it settled.",
  },
  {
    n: "02",
    title: "Nothing survives without a receipt",
    body: "A critic argues it has been done. An advocate argues it has not. A jury of model families votes, a split sends scouts back out, and a verifier with a veto checks every quote against its source.",
  },
  {
    n: "03",
    title: "Then it coaches you outward",
    body: "Facet swaps seeded from what is common globally but absent near you. Each one is re-scored against the corpus, and you watch its star drift into open sky.",
  },
];

export default function Home() {
  return (
    <>
      <SiteNav active="/" />
      {/* flex-none: a flex item with overflow hidden may shrink below its content, which would clip the form */}
      <main className="relative flex-none overflow-hidden">
        <HeroChart className="pointer-events-none absolute -right-40 -top-24 hidden w-[860px] max-w-none opacity-90 lg:block xl:-right-24" />

        <div className="relative mx-auto grid w-full max-w-[1240px] gap-10 px-5 pb-16 pt-12 sm:px-8 lg:grid-cols-[minmax(0,620px)_1fr] lg:pt-20">
          <div>
            <p className="label animate-rise">
              <span className="text-amber">✦</span> A cartography of idea-space
            </p>
            <h1 className="mt-4 animate-rise font-display text-[58px] leading-[0.98] tracking-[-0.01em] text-bone sm:text-[76px]" style={{ animationDelay: "0.08s" }}>
              How original is your idea, <em className="text-amber">really?</em>
            </h1>
            <p className="mt-6 max-w-[54ch] animate-rise text-[16px] leading-relaxed text-bone-dim" style={{ animationDelay: "0.16s" }}>
              Paste a pitch. A swarm of AI agents charts everything already built around it, argues over whether it is truly the same
              idea, and verifies every claim against its source. Then it points at the empty parts of the map, with receipts.
            </p>

            <div className="mt-9">
              <IdeaInput />
            </div>
          </div>
        </div>

        <section className="relative border-t border-line bg-ink-900/70 backdrop-blur-sm">
          <div className="mx-auto grid w-full max-w-[1240px] gap-px px-5 sm:px-8 md:grid-cols-3">
            {STEPS.map((s, i) => (
              <div key={s.n} className="animate-rise border-line py-8 md:border-l md:px-7 md:first:border-l-0 md:first:pl-0" style={{ animationDelay: `${0.35 + i * 0.08}s` }}>
                <div className="font-mono text-[10.5px] tracking-[0.2em] text-amber">{s.n}</div>
                <h2 className="mt-2 font-display text-[25px] leading-tight text-bone">{s.title}</h2>
                <p className="mt-2 text-[13.5px] leading-relaxed text-bone-dim">{s.body}</p>
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="mt-auto flex flex-none flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-4 font-mono text-[10px] uppercase tracking-[0.16em] text-faint sm:px-8">
        <span>Built at Hack the North 2026</span>
        <span className="flex gap-4">
          <Link href="/slop-index" className="hover:text-bone">The Slop Index</Link>
          <Link href="/about" className="hover:text-bone">Architecture</Link>
        </span>
      </footer>
    </>
  );
}
