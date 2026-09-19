import type { Metadata } from "next";
import Link from "next/link";
import { SiteNav } from "@/components/SiteNav";

export const metadata: Metadata = {
  title: "How it works",
  description: "The architecture of Whitespace: a swarm of agents over Elasticsearch, Baseten, GPTZero, openJiuwen and Browserbase, streamed to the browser as one event contract.",
};

const ROLES: { name: string; job: string; color: string }[] = [
  { name: "conductor", job: "extracts facets, staffs the team, holds the budget, replans on failure", color: "#f4b942" },
  { name: "scout.*", job: "one per source: Devpost, YC, GitHub, Hacker News (arXiv when it fits)", color: "#78b4ff" },
  { name: "resolver", job: "schema match, entity match, field fusion, conflicts, imputation", color: "#d9c9a3" },
  { name: "critic", job: "argues it exists, with quotes; may send scouts back out", color: "#ff8a7a" },
  { name: "advocate", job: "different model family; must concede, distinguish or challenge", color: "#4fd6c0" },
  { name: "judge", job: "cross-family jury; a split triggers a targeted re-query", color: "#c4bdf0" },
  { name: "verifier", job: "quote check + GPTZero citation check; holds a veto", color: "#78b4ff" },
  { name: "synthesizer", job: "input restricted in code to verified claims", color: "#ece5d3" },
  { name: "mutator", job: "swaps one facet toward whitespace, re-scores it", color: "#7fe0d0" },
  { name: "actuator", job: "arms a watch, drafts a pitch, writes back: on your click", color: "#e0a94a" },
];

const SPONSORS: { name: string; role: string; points: string[]; color: string }[] = [
  {
    name: "Elasticsearch", role: "the context layer for every agent", color: "#78b4ff",
    points: [
      "Hybrid retrieval: BM25 + Jina v3 vectors (semantic_text), fused with RRF, then the Jina reranker",
      "significant_text for cliché terms; aggregations for the whitespace finder and per-year crowding",
      "ES|QL tools exposed to agents through Agent Builder over MCP",
      "A scheduled Workflow re-checks armed watches and raises alerts",
    ],
  },
  {
    name: "Baseten", role: "inference as a measuring instrument", color: "#ff9466",
    points: [
      "A right-sized model per role (the cost meter on every run shows which)",
      "A jury of different model families; their disagreement widens the band and triggers re-queries",
      "LLM-predictability: several families asked the same problem, to see if they propose your idea unprompted",
    ],
  },
  {
    name: "GPTZero", role: "voice, slop share, and a veto", color: "#4fd6c0",
    points: [
      "Voice: a sentence-level read of your pitch, shown in GPTZero's own words, never as a raw probability",
      "Neighbourhood slop share, and the Slop Index investigation with a placebo false-positive rate",
      "Bibliography scan on our own agents' claims: a citation that cannot be found strikes the claim",
    ],
  },
  {
    name: "openJiuwen agent-core", role: "the agent runtime", color: "#c4bdf0",
    points: [
      "Roles are host-agnostic and run on openJiuwen's team runtime (peer-to-peer messages, pub/sub, streaming)",
      "An asyncio host implements the same interface as a fallback; each run states which one ran it",
    ],
  },
  {
    name: "Browserbase", role: "the evidence browser", color: "#e87fa6",
    points: [
      "Renders the live product sites of top prior-art entities that plain HTTP cannot read",
      "Feeds conflicts such as “the listing says live, the site is dead”; a bot challenge is recorded as blocked, never evaded",
    ],
  },
];

function Box({ title, sub, children, accent }: { title: string; sub?: string; children?: React.ReactNode; accent?: string }) {
  return (
    <div className="plate px-4 py-3" style={accent ? { borderColor: `color-mix(in srgb, ${accent} 45%, transparent)` } : undefined}>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-display text-[21px] leading-tight text-bone">{title}</span>
        {sub && <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-mute">{sub}</span>}
      </div>
      {children}
    </div>
  );
}

function Wire({ label }: { label: string }) {
  return (
    <div className="flex h-11 items-center justify-center gap-2" aria-hidden>
      <svg width="12" height="44" viewBox="0 0 12 44" className="flex-none text-amber-dim">
        <path d="M6 0v36" stroke="currentColor" strokeDasharray="2 4" />
        <path d="M2 34l4 8 4-8" fill="none" stroke="currentColor" />
      </svg>
      <span className="font-mono text-[10px] tracking-[0.06em] text-mute">{label}</span>
    </div>
  );
}

export default function AboutPage() {
  return (
    <>
      <SiteNav active="/about" />
      <main className="mx-auto w-full max-w-[1100px] flex-1 px-5 pb-20 pt-10 sm:px-8">
        <p className="label animate-rise"><span className="text-amber">✦</span> How it works</p>
        <h1 className="mt-3 max-w-[18ch] animate-rise font-display text-[50px] leading-[1] text-bone sm:text-[64px]" style={{ animationDelay: "0.06s" }}>
          Ten roles, one contract, <em className="text-amber">no claim without a receipt.</em>
        </h1>
        <p className="mt-5 max-w-[66ch] animate-rise text-[15.5px] leading-relaxed text-bone-dim" style={{ animationDelay: "0.12s" }}>
          Language models are unreliable judges of novelty and tend to propose the same ideas. So Whitespace never asks one model for an opinion.
          It grounds the score in retrieval, makes agents argue across model families, lets a verifier strike anything it cannot trace to a source,
          and abstains (&ldquo;Insufficient evidence&rdquo;) when coverage is too thin to say.
        </p>

        {/* architecture diagram */}
        <section className="mt-10 animate-rise" style={{ animationDelay: "0.2s" }} aria-label="Architecture diagram">
          <Box title="The browser" sub="Next.js · this site">
            <p className="mt-1 text-[13px] leading-relaxed text-bone-dim">
              Star chart, swarm timeline, debate, coach, report. A pure reducer folds the event stream into state, so a live run and a recording render identically.
            </p>
          </Box>
          <Wire label="POST /api/runs  ·  SSE /api/runs/{id}/events  (one AgentEvent per message; the same JSONL is the replay file)" />
          <Box title="FastAPI + event bus" sub="assigns seq · persists every run as JSONL">
            <p className="mt-1 text-[13px] leading-relaxed text-bone-dim">
              Every degradation is an event: a failed source, a blown budget, a dropped juror. Nothing fails silently, and anything simulated is labelled as such.
            </p>
          </Box>
          <Wire label="Role.handle(msg, ctx): send · publish · emit · board · budget" />
          <Box title="The swarm" sub="openJiuwen agent-core · asyncio fallback" accent="#c4bdf0">
            <ul className="mt-2 grid gap-x-5 gap-y-1.5 sm:grid-cols-2">
              {ROLES.map((r) => (
                <li key={r.name} className="flex items-baseline gap-2 text-[12.5px] leading-snug">
                  <span className="w-[86px] flex-none font-mono text-[11px]" style={{ color: r.color }}>{r.name}</span>
                  <span className="text-bone-dim">{r.job}</span>
                </li>
              ))}
            </ul>
          </Box>
          <Wire label="search · MCP tools · model calls · detection · page renders" />
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {SPONSORS.map((s) => (
              <Box key={s.name} title={s.name} sub={s.role} accent={s.color}>
                <ul className="mt-2 flex flex-col gap-1.5">
                  {s.points.map((p) => (
                    <li key={p} className="flex gap-2 text-[12.5px] leading-snug text-bone-dim">
                      <span className="mt-[7px] size-[4px] flex-none" style={{ background: s.color }} />
                      {p}
                    </li>
                  ))}
                </ul>
              </Box>
            ))}
            <Box title="Live sources" sub="GitHub · Hacker News">
              <p className="mt-2 text-[12.5px] leading-snug text-bone-dim">Queried at run time with a broaden-and-retry policy. When one times out you see it fail, retry and recover on the timeline, and confidence drops accordingly.</p>
            </Box>
          </div>
        </section>

        <section className="mt-12 grid gap-8 md:grid-cols-3">
          {[
            { h: "Three axes, one headline", p: "Crowding (how close and how many), facet rarity (purpose, mechanism, audience, data, twist against the whole corpus) and LLM-predictability. The headline carries an uncertainty band that widens when the jury disagrees." },
            { h: "Voice stays separate", p: "Whether a pitch reads as AI-written says nothing about whether the idea is new. GPTZero's read gets its own panel and never moves the originality number." },
            { h: "Replay is a first-class mode", p: "Every run is a JSONL file of the same events the UI streams live. The recorded run on this site plays with no backend at all." },
          ].map((b) => (
            <div key={b.h} className="border-t border-line pt-4">
              <h2 className="font-display text-[24px] leading-tight text-bone">{b.h}</h2>
              <p className="mt-2 text-[13.5px] leading-relaxed text-bone-dim">{b.p}</p>
            </div>
          ))}
        </section>

        <div className="mt-12 flex flex-wrap gap-3">
          <Link href="/runs/mock" className="btn btn-primary h-10 px-5">Watch a recorded run</Link>
          <Link href="/slop-index" className="btn h-10 px-4">Read the Slop Index</Link>
        </div>
      </main>
    </>
  );
}
