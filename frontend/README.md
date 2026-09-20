# Whitespace: frontend

Next.js (App Router) + Tailwind v4 + `react-force-graph-2d` + Recharts. It renders a swarm investigation from **one event
stream** (`docs/events.md`), live over SSE or replayed from a JSONL file with no backend at all.

## Run it

```bash
cd frontend
pnpm install
pnpm dev                 # http://localhost:3000
```

| Command | What it does |
|---|---|
| `pnpm dev` | dev server on :3000 |
| `pnpm build` / `pnpm start` | production build / serve (any `/runs/<id>` works) |
| `pnpm build:static` | fully static export into `out/` (only `/runs/mock` is generated; see "Replay-only deploy") |
| `pnpm lint` · `pnpm typecheck` | ESLint · `tsc --noEmit` |
| `pnpm test` | vitest: folds the whole mock run through the reducers and asserts the end state |
| `pnpm sync-replay` | copies `../backend/fixtures/mock_run.jsonl` to `public/replay/mock.jsonl` |

The build needs no network: fonts are self-hosted in `app/fonts/` (OFL, see `LICENSES.txt` there).

## Environment

Copy `.env.example` to `.env.local`.

| Variable | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8000` | FastAPI base URL, no trailing slash. Inlined at build time. The backend must allow this origin (CORS). |
| `NEXT_PUBLIC_REPLAY_ONLY` | unset | Set to `1` on a deploy with no backend: "Investigate" explains itself instead of POSTing. |

## Pages

- `/` : hero + pitch input. 250-character gate for the GPTZero voice read (with a "run anyway" escape hatch from 20 characters, the
  backend minimum). `POST {API}/api/runs` then routes to `/runs/{run_id}`. If the POST fails you get an inline error (on a replay-only deploy it also links to the recorded run).
- `/runs/[id]` : the live view.

## Transports: live vs replay

Replay is demo insurance, not a feature of the site: nothing in the UI links to `/runs/mock` any more, and the route is
reached only by typing it, by `?replay=`, or on the replay-only deploy. It is still prerendered, which is what `build:static` exports.

`lib/useRunEvents.ts` picks the transport:

| URL | Transport |
|---|---|
| `/runs/mock` | static replay of `public/replay/mock.jsonl` (no backend needed) |
| `/runs/anything?replay=<name>` | static replay of `public/replay/<name>.jsonl` |
| `/runs/<run_id>` | live SSE from `{API}/api/runs/<run_id>/events` |

Replay URL parameters: `?speed=2` (default `1.5`; `0` jumps straight to the end). Timing mirrors the backend's replayer:
`min(gap, 2.5 s) / speed`. Controls in the top bar: restart, play/pause, step, skip to end, scrubber (seek backwards re-folds the run),
speed. Keyboard: `Space` play/pause, `→` step one event, `E` skip to end, `R` restart.

To demo a real run offline: copy `backend/runs/<run_id>.jsonl` to `public/replay/<name>.jsonl` and open `/runs/x?replay=<name>`.

Live SSE notes (`lib/sse.ts`): the server names every message (`event: <type>`), so a listener is registered for every `EventType`
(`lib/eventTypes.ts` fails the build if `lib/types.ts` gains a type that is not listed). Reconnects are the browser's (Last-Event-ID).
Once `run.finished` has been seen, a closed stream is treated as the normal end rather than retried. After a rescore or an action
POST the stream is re-opened once (`resync`) so events emitted after the bus closed still arrive; the reducer ignores any `seq` it has already seen.

## Replay-only deploy

The recorded run is a static file, so the site works with no backend:

- **Vercel (simplest):** deploy `frontend/` as a normal Next.js project with `NEXT_PUBLIC_REPLAY_ONLY=1`. `/runs/mock` is prerendered.
- **Any static host:** `NEXT_PUBLIC_REPLAY_ONLY=1 pnpm build:static` and upload `out/`. Only `/runs/mock` exists in a static export
  (dynamic ids need a server), which is all a replay-only site needs.

Run `pnpm sync-replay` before deploying if the fixture changed.

## Where things live

```
lib/types.ts          mirror of backend/app/schemas (the contract; change together with docs/events.md)
lib/payloads.ts       typed `data` payload per event type
lib/runReducer.ts     pure fold: AgentEvent -> RunState (idempotent on seq, never throws)
lib/graphReducer.ts   pure fold of GraphPatch (removing a node drops its links; early links wait for their endpoints)
lib/selectors.ts      evidence cards (records collapse into entities), ledger rows, source status, spend
lib/replay.ts         JSONL replay controller      lib/sse.ts   EventSource client      lib/useRunEvents.ts   the hook
components/run/       the multi-page run shell: RunProvider (one stream, many pages) · RunShell · TabBar · MapScreen
                      DetailCard (islands + their listings) · screens (Debate / Coach / Report / Swarm+Ledger)
components/           SwarmTimeline · IdeaGraph(+Canvas) · islands/* · AxisGauges · PitchHighlighter
                      EvidenceDetail (listings + fused fields, shared) · EvidenceLedger · DebateThread · MutationPanel
                      ReportPanel · ActionBar · CostMeter · ReplayControls · RunView + EvidenceCard (/classic only)
tests/reducers.test.ts
```

## Honesty rules the UI enforces

- `run.started.data.mock === true` : persistent banner "Recorded mock run — fictional fixture data".
- Anything with `simulated: true` (the fire drill) is labelled "SIMULATED — fire drill" in the timeline and on the claim.
- Imputed values are marked "inferred" (detail card, ledger, graph ring).
- Voice shows GPTZero's `result_message` + `confidence_category`, never a raw probability, and never touches the headline.
- When `scores.abstain.active`, the reason replaces the headline number.
- In replay mode, action and re-score buttons show "Replay mode — actions are disabled" and call nothing.
- Chart colours are the validated dark steps of the dataviz reference palette (see `lib/chartTheme.ts`), in a fixed order.
