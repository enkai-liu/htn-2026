# Devpost submission — draft

Two moments: the **initial submission by Sat 14:00 EDT** (team, badge IDs and sponsor prizes are LOCKED then; the text can change) and the **final text by Sun 08:00** (aim 07:15). Anything marked `TODO(measure)` must come from a real run. Do not publish a number we have not measured. **This draft describes the design: as of Sat 12:20 nothing has run against a real LLM, Elasticsearch or GPTZero. On Sunday morning re-check every feature sentence against what actually works and delete what did not ship.**

## Checklist for 14:00 (only a teammate can do this: it needs the Devpost login)

- [ ] Project created on the Hack the North 2026 Devpost, all 4 teammates added, every badge ID entered
- [ ] Name, tagline and the short description below pasted in (placeholders are fine, the opt-ins are what lock)
- [ ] Prizes opted into: **GPTZero · Baseten · Huawei openJiuwen · Rox · Elastic · Browserbase · GoDaddy Registry (MLH domain)**
- [x] **RBC: decided — not opted in** (it is a financial-data Q&A benchmark on RBC's own MCP server, a different project). Sponsor prizes locked at initial submission: GPTZero, Elastic, Baseten, Rox, Huawei openJiuwen, GoDaddy, Browserbase.
- [ ] Repo link: `github.com/enkai-liu/htn-2026` (private until `scripts/secret_scan.sh` is clean on Sunday morning)
- [ ] Booth answers written down: Rox (separate write-up or deadline?), Huawei (does agent-core + a validated Swarm Skill count?)

## Name and tagline

**Whitespace** — *How original is your idea? With receipts.*

Alternative taglines: "Find out if it's been done before you build it." · "An agent team that argues about your idea, then proves it."

## Short description (initial submission, ~90 words)

Whitespace tells you how original a hackathon or startup idea is before you spend a weekend on it. Paste a pitch and a team of AI agents searches past hackathon projects, startups, code and discussions, merges the duplicates, and argues it out: a critic claims "already done" with verbatim quotes, an advocate has to concede or name what differs, a jury of different model families scores the overlap, and a verifier strikes any claim whose quote or citation does not check out. You get scores you can trace to evidence, an honest "insufficient evidence" when there is not enough, and coached variations that are re-scored against the corpus.

## Inspiration

Every hackathon produces the same twenty projects, and this year a language model will happily suggest all twenty to you. The only tools we found for checking an idea against past hackathons (HackAnalyzer, HackHarvard 2023; DevSpot, HackPSU 2024) do keyword search over Devpost and hand back an ungrounded LLM score: no evidence you can check, no advice, no picture of where the open ground is. Research says that is the wrong way round. Si, Yang and Hashimoto (2024) found that LLM-generated ideas lack diversity at scale and that LLMs are unreliable judges of novelty. So we built the opposite: models find, argue about and verify evidence, and never hand out the number.

## What it does

- **Live investigation.** A pitch goes in; you watch scouts fan out over an indexed corpus of hackathon projects and YC companies plus live GitHub and Hacker News, a resolver collapse the same project seen on four sites into one entity (conflicts between sources shown, not hidden), and a debate stream in with quotes attached.
- **Scores grounded in retrieval.** *Crowding* (how dense is the neighbourhood of existing work, as a percentile against typical projects), *Facet rarity* (which parts of the idea are common and whether the combination is rare), and *LLM-predictability* (give several model families only the problem and the audience: do they independently propose your idea?). The headline is a weighted geometric mean, so one crowded axis cannot be averaged away.
- **It can say "I don't know".** Low source coverage, a split jury or unverified claims produce "Insufficient evidence: …" with what is missing, instead of a confident number.
- **A verifier with a veto.** Every "this already exists" claim needs a verbatim quote found in the fetched source, and its citation is checked independently with GPTZero's bibliography scan. Struck claims never reach the report writer; that restriction is enforced in code, not in a prompt.
- **Voice is its own panel.** GPTZero's sentence-level read of your pitch is shown separately and never enters the originality score: an AI can phrase a novel idea, and a human can phrase a cliché.
- **Coaching that is measured.** The whitespace finder surfaces terms common across the corpus but absent near your idea; the coach swaps one facet at a time, and every variation is re-scored by re-running retrieval. Its node visibly moves away from the cluster in the idea-space graph.
- **Actions.** Arm a recurring watch that re-searches and pings you when similar work appears, draft a differentiated pitch, or write the idea back into the corpus. Anything that touches the outside world waits for your click.
- **The Slop Index.** A year-stratified scan of Devpost write-ups from 2018 to 2026 with GPTZero, reported with a placebo-year false-positive rate, asking one question: are AI-flagged pitches measurably closer to their nearest neighbours? Aggregates only; no project or student is named. `TODO(measure)`: results.

## How we built it

- **Elastic** is the context layer for every agent: an ingest pipeline cleans messy write-ups, `semantic_text` embeds them with Jina v3 on the Elastic Inference Service, retrieval is BM25 plus semantic fused with RRF and reranked by the Jina reranker, and the originality maths runs natively (`significant_text` for a neighbourhood's clichés, aggregations for whitespace). ES|QL tools in Agent Builder are served to agents over MCP, and a scheduled Workflow closes the loop for watches. `TODO(measure)`: corpus size.
- **Baseten** runs every model call through one router with a token bucket and an OpenRouter overflow. Inference is used as a measurement instrument (the predictability probe and a jury whose disagreement triggers re-planning), with a bake-off table that right-sizes a model per role. `TODO(measure)`: bake-off table, cost per run.
- **Huawei openJiuwen.** Roles are host-agnostic and run on openjiuwen agent-core (`TeamRuntime` P2P plus pub/sub, `BaseTeam` streaming), with an asyncio host tested for event parity. The team is also packaged as a reusable Swarm Skill, `prior-art-swarm`, which passes the official validator with 0 errors and 0 warnings.
- **Rox.** The resolver is a data-wrangling agent: schema matching from every source into one schema with provenance (`TODO`: state the real source count), entity matching with a calibrated `insufficient_evidence` verdict, field fusion with source-reliability priors, visible conflicts and visibly imputed fields, and confidence-gated actions. `TODO(measure)`: entity-resolution precision and recall on Devpost-to-GitHub links.
- **GPTZero** in three places: Voice, the share of AI-written work in your idea's neighbourhood, and veto power over our own agents' citations, plus the Slop Index investigation. We show GPTZero's result message and confidence category, never raw probabilities.
- **Browserbase** renders the live sites of the closest prior work (many are JavaScript apps a plain fetch cannot read) to report whether each is alive, parked, dead or pivoted. A site that shows a bot challenge is reported as blocked; we never try to get around one. `TODO`: only if built.
- FastAPI streams every agent event over SSE; each run is a JSONL file that doubles as the replay format. Next.js renders the swarm timeline, the idea-space graph, the debate and the evidence ledger.

## Challenges we ran into

- Devpost's search endpoint sits behind a bot challenge. We left it alone: the corpus comes from public datasets and from pages Devpost serves normally, fetched politely.
- Hosted model APIs do not expose prompt log-probabilities, so "how surprising is this idea to a model" became a behavioural probe: ask several model families cold and count collisions.
- Our SSE event type `error` shares its name with the browser's own `EventSource` error event, so every recoverable degradation looked like a dropped connection. One `instanceof`-style check fixed it.
- `TODO`: add what actually hurt on Saturday night.

## Accomplishments that we're proud of

- A verifier whose veto is enforced in code: a claim with a fabricated quote is struck and never reaches the report writer (covered by the offline end-to-end test). `TODO`: mention the live fire drill (inject a labelled fake competitor, watch it get struck) only if the trigger endpoint ships.
- An originality score that abstains. `TODO(measure)`: benchmark ordering (Spearman ρ against the expected order of 8 pitches, cliché to novel).
- Running it on itself: it finds DevSpot, HackAnalyzer and Plagia, and the variation it coached is the product we built.

## What we learned

`TODO` (Sunday morning, from what really happened).

## What's next

Calibrating crowding per venue, more corpora (patents, papers), and watches that report when the whitespace you claimed starts to fill.

## Built with

`python` `fastapi` `next.js` `typescript` `elasticsearch` `elastic-agent-builder` `jina` `baseten` `openjiuwen` `gptzero` `browserbase` `openrouter` `sse`

## Credits and data

Datasets: `twangodev/devpost-hacks` and `alvanlii` Devpost projects (Hugging Face), YC company directory. `TODO`: licences and attribution lines copied from each dataset card before publishing.
