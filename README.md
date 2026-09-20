# S.L.O.P.

*Similarity Lookup for Originality Prediction*

> How original is your idea — with receipts — and how do you make it more original?

Built at Hack the North 2026. A swarm of specialised agents investigates a hackathon or startup idea against 260k+ real projects and live sources, argues about what it found, verifies its own claims, and coaches you toward emptier territory.

**Start here:** [docs/PLAN.md](docs/PLAN.md) (schedule, lanes, cut lines) · [docs/design-full.md](docs/design-full.md) (exact mappings, queries, workflows, host sketch, scoring) · [docs/events.md](docs/events.md) (the SSE contract every lane builds against) · [docs/research/](docs/research/)

## What it measures

| Axis | Question | Powered by |
|---|---|---|
| Crowding | How dense is the neighbourhood of existing projects? | Elasticsearch hybrid search (BM25 + Jina vectors, RRF, Jina reranker) |
| Facet rarity | Which parts of the idea are cliché, which are rare? | `significant_text`, ES\|QL |
| LLM-predictability | Do language models independently propose this idea? | Baseten (4 model families) |
| Voice (separate) | Does the pitch read like the median LLM output? | GPTZero |
| Confidence | Is there enough evidence to say anything? If not, it abstains. | source coverage, jury agreement, verified claims |

## Quickstart

```bash
cp .env.example .env        # fill in keys
make setup                  # python 3.12 venv + pnpm install
make smoke                  # validates every key/endpoint
make apply                  # Elastic mappings, pipeline, tools, workflows
make ingest-tier0           # YC + recent Devpost + seeded prior art
make backend                # http://localhost:8000
make frontend               # http://localhost:3000
```

## Deploy (free tiers)

- **Backend on Render**: `render.yaml` is a Blueprint. Open <https://render.com/deploy?repo=https://github.com/enkai-liu/htn-2026>, paste the keys it asks for (the same names as `.env`; blank = that feature is off). It sleeps when idle and takes about a minute to wake. `MAX_RUNS_PER_DAY` is the only thing between the public URL and the keys: there is no auth.
- **Frontend on Vercel**: import the repo with Root Directory `frontend` and `NEXT_PUBLIC_API_BASE=https://<the Render service>.onrender.com`. It has to be a Next.js server, not a static host: `/runs/<id>` is rendered on demand.
- **Replay-only on GitHub Pages**: `.github/workflows/pages.yml` publishes the static export to <https://enkai-liu.github.io/htn-2026/> on every push. No backend, plays the recorded run, never sleeps: the fallback if the other two are down.

## Layout

`backend/` FastAPI + agents · `frontend/` Next.js · `ingest/` corpus loaders · `elastic/` mappings, pipeline, Agent Builder tools, Workflows · `swarm-skill/` reusable openJiuwen Swarm Skill · `baseten/` bake-off + surprisal deployment · `scripts/` smokes and benchmarks

## Data and attribution

Corpus: [`alvanlii/devpost-hackathon-projects`](https://huggingface.co/datasets/alvanlii/devpost-hackathon-projects), [`twangodev/devpost-hacks`](https://huggingface.co/datasets/twangodev/devpost-hacks) (research use), [`yc-oss/api`](https://github.com/yc-oss/api), plus live Hacker News (Algolia) and GitHub search. Used for a non-commercial hackathon demo.
