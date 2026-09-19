# Research 01 — HTN 2026 rules, prior art, data sources

> Condensed from planning research (Sat 2026-09-19 ~01:00 EDT). Endpoints marked ✅/❌ were probed live.

## 1. Logistics (all EDT) — https://hackthenorth2026.devpost.com/

| Event | Time |
|---|---|
| Submission period opens | Fri Sep 18, 17:00 |
| **Initial submission + sponsor prize selection LOCKED** (team, badge IDs exactly as printed, prizes) | **Sat Sep 19, 14:00** |
| Final submission closes | Sun Sep 20, 08:00 |
| Sponsor judging | Sun Sep 20, 09:45–11:45 |

- Round 1: 5-minute **live demo** + Q&A — "a live demo, not a slide deck or a product pitch". Top two per room advance (4-min demo + 1-min Q&A). Demo video optional but recommended.
- Criteria: originality, technical complexity, design/UX, WOW factor. No published weights.
- Team ≤ 4, in person. **All code and design assets created during the event.** Allowed in advance: planning, installing software, **gathering datasets**. Not allowed: pre-trained custom models. Public libraries/assets are fine. Submission must link source.
- Multiple sponsor prizes allowed; no cap found. Each opt-in costs a slot in the 2-hour sponsor judging window.
- Unverified: exact hacking start time; whether Rox takes submissions off-Devpost (ask booth).

## 2. Prior art (the tool itself must be original)

**Hackathon-specific**
- **HackAnalyzer** (HackHarvard 2023) — https://devpost.com/software/hackanalyzer — Devpost URL → ChatGPT keywords → Devpost keyword search → "originality score". Judge-facing, keyword-based, Devpost-only, no advice, no visualisation.
- **DevSpot** (HackPSU Spring 2024) — https://devpost.com/software/devspot — GPT-4 uniqueness check vs Devpost; authors cite compute as the bottleneck.
- **HackathonProjectSearch** — https://github.com/Ayon-Bhowmick/HackathonProjectSearch — semantic search over winners; no scoring.
- **Plagia** — "plagiarism detector for hackers" (surfaced in the HF dataset).

**Commercial validators:** Preuve AI (evidence-linked *market viability*, not novelty), ValidatorAI / IdeaProof / NxCode (ungrounded LLM opinion).

**Academic blueprints**
- Si, Yang, Hashimoto 2024, *Can LLMs Generate Novel Research Ideas?* — https://arxiv.org/abs/2409.04109 — LLM ideas lack diversity at scale; LLMs are unreliable novelty judges → ground scores in retrieval.
- Idea Novelty Checker (Shahid et al. 2025) — https://arxiv.org/abs/2506.22026 — retrieve → embedding filter → facet-based LLM rerank.
- Scideator — https://arxiv.org/abs/2409.14634 — facets (purpose / mechanism / evaluation), recombine to get novelty.
- SciMON — iterative novelty boosting loop. ScholarEval — https://arxiv.org/abs/2510.16234 — actionability, depth, evidence support.

**Whitespace we occupy:** large hackathon corpus with semantic search · detecting "median-LLM" ideas · facet-swap coaching that is re-scored against evidence · idea-space graph with visible gaps · independently verified, cited claims · cross-corpus (hackathon + startup + repo) novelty.

## 3. Data sources

| Source | Status | Access |
|---|---|---|
| HF `alvanlii/devpost-hackathon-projects` | ✅ 261,940 rows, 381 MB parquet, through Jan 2025 | fields: hackathon_id, project_link, full_desc, title, brief_desc, team_members, prize, tags; `hackathons.json` has `submission_period_dates` (year join). Licence unstated → attribute, demo use only |
| HF `twangodev/devpost-hacks` (config `all`) | ✅ 2,222 projects, 2024–2026 | built_with, is_winner, other_links, linked GitHub READMEs → ER ground truth. Research use |
| YC companies | ✅ https://yc-oss.github.io/api/companies/all.json | 6,237 companies, refreshed daily, no auth |
| Hacker News | ✅ https://hn.algolia.com/api/v1/search?query=…&tags=story | no auth |
| GitHub search | ✅ `GET /search/repositories?q=…` | 30 req/min with token, 10 without |
| arXiv | ✅ https://export.arxiv.org/api/query?search_query=all:… | Atom XML, ~1 req / 3 s, use https |
| OpenAlex | ✅ but now credit-metered (~100 searches/day free) | add `mailto=` |
| Devpost project pages + hackathon galleries | ✅ HTTP 200 with a normal browser UA; robots.txt permissive | e.g. https://hackthenorth2026.devpost.com/project-gallery ; `https://devpost.com/api/hackathons?search=` returns JSON |
| Devpost `/software/search?query=` | ❌ AWS WAF JS challenge (HTTP 202) | **Leave it alone — do not build anything to defeat bot detection.** Fresh projects come from galleries |
| Reddit | ❌ 403 / licensing | skip |
| Semantic Scholar | ❌ 429 without approved key | skip |
| Brave Search | ❌ free tier ended Feb 2026 | skip |
| Patents | ❌ no practical free keyword API | skip |
| Exa `/findSimilar`, `/search` | optional, `x-api-key`, ~$20 signup credit | P2 |

## 4. Other sponsor tracks checked
- **RBC: Signal in the Noise** — requires RBC's MCP server (`http://3.143.20.160/mcp`, single tool `financialDataRetrieval`) and a two-phase Q&A accuracy benchmark on financial research data. Different project; recommended against.
- **Browserbase** ($2k) — used for an evidence-browser agent that renders prior-art products' live sites (screenshots, alive/dead status). Not for getting around Devpost's WAF.
- **MLH GoDaddy domain** — register with the MLH code, point at the replay-only deploy.
