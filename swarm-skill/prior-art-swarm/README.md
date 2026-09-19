# prior-art-swarm

A reusable openJiuwen **Swarm Skill**: an eight-role team that finds out whether an idea has already been done, shows verified receipts, and coaches the idea toward open ground. It is the portable form of the agent team inside [Whitespace](../../README.md): the same roles, the same veto, the same abstention rules, with nothing tied to hackathons. Point the scouts at other sources and it pre-screens a startup idea, a product feature, a research direction or a patent.

**Status.** The package passes the official validator (`validate_swarmskill.py` from `openJiuwen-ai/jiuwenswarm`, branch `develop`); the run is recorded in [docs/sponsors/huawei.md](../../docs/sponsors/huawei.md). It has not yet been executed inside a JiuwenSwarm workspace. In Whitespace the same roles run on openJiuwen agent-core (`backend/app/orchestration/jiuwen_host.py`).

## Why a team and not one agent

One agent that searches, judges and cites for itself will report prior work that does not exist, miss work that does, and never notice, because nothing in it is positioned to disagree. Here the disagreement is structural:

| Mechanism | Where |
|---|---|
| Retrieval is isolated: only scouts search, one per source slice, blind to each other | Step 2 |
| The critic can send scouts back out when the evidence has a hole | Step 4, back-edge 1 |
| Critic and advocate run on different model families; the advocate may only concede, distinguish by facet, or challenge the evidence | Step 4 |
| A jury of model families votes without hearing the debate; a split jury triggers one targeted re-query and a re-vote | Step 4, back-edge 2 |
| The verifier's veto is a string check in code plus an independent citation check; struck claims never reach the synthesizer | Step 5 |
| Scores are computed from retrieval and ballots; no role writes a number. Thin evidence produces "Insufficient evidence: …" | Step 6 |
| Every coached mutation is re-scored by re-running retrieval | Step 7 |

## Layout

```
SKILL.md              frontmatter (kind: swarm-skill, 8 roles of kind ai_agent) + workflow summary
workflow.md           mermaid diagram, steps with quality gates, Final Report format, acceptance criteria
bind.md               budgets and caps, phase-scoped visibility, failure handling, degraded modes
dependencies.yaml     tools checked in pre-flight (one required, two optional; no skills needed)
roles/*.md            identity, success criteria, boundary, output schema, Inline Persona per role
scripts/workflow.py   the same topology as an executable SwarmFlow script
```

## Install and run

1. Copy the `prior-art-swarm/` folder into your JiuwenSwarm workspace `skills/` directory (the one that holds `swarmskill-creator`).
2. **Team mode**: ask the Leader to use `prior-art-swarm` on an idea. It reads `SKILL.md`, runs the pre-flight in `dependencies.yaml`, and dispatches teammates with the Inline Persona from each role file.
3. **SwarmFlow mode** (deterministic): enable SwarmFlow (`/swarmflow on`, and `modes.team.jiuwen_team.enable_swarmflow: true` in `config.yaml`), then have the Leader run `scripts/workflow.py` with the arguments below. Progress appears as a phase tree under `/swarmflows`.

## Arguments (`scripts/workflow.py`)

A JSON object, or a bare idea string.

| Key | Meaning | Default |
|---|---|---|
| `idea` (required) | The pitch: what it does, for whom, how | none |
| `url` | A page describing the idea | none |
| `domain_hint` | For example `research` or `patent`: staffs the slices marked `only_for` | none |
| `available_tools` | Tools found in pre-flight; decides which slices can be staffed | `["web_search"]` |
| `sources` | Replace the source slices (see below) | 7 built-in slices |
| `jury_models`, `prior_models` | One model id per juror / blind sampler, ideally different families | host default, three same-family jurors, reported as a caveat |
| `critic_model`, `advocate_model`, `verifier_model`, `coach_model` | Per-role model ids; use different families for critic and advocate | host default |
| `debate_rounds` | 1 or 2 | 1 |
| `max_calls` | Dispatch cap, 30 to 70 | 70 |
| `timeouts` | `{scout, role, confirm}` in seconds | 120 / 75 / 300 |
| `reliability_priors` | Per-field trust in each slice, used when sources conflict | built-in table |
| `ask_confirmation` | Ask the user to approve outside-world actions at the end | false |

The script returns the Originality Report as JSON: status, facets, team (staffed and skipped slices with reasons), sources, scores with the abstention reason, verdict, claims split into verified / struck / withdrawn, the debate and jury record, the predictability probe, entities with conflicts, mutations with their re-scores, proposed actions, missing roles, degradations and the dispatch count.

## Pointing the scouts somewhere else

A source slice is one entry in `sources`:

```json
{"id": "clinical-trials", "label": "registered clinical trials", "needs": "web_search",
 "queries": "semantic", "only_for": ["research"],
 "guidance": "Search trial registries for interventions with the same mechanism."}
```

`needs` names the tool the slice depends on (a slice whose tool is missing is skipped with the reason), `queries` picks semantic or keyword queries, `only_for` restricts the slice to a domain hint, and `guidance` is given to that scout. Add a matching row to `reliability_priors` if the slice should win or lose conflicts on a field. No role file changes.

## Rules the team keeps

- A source that blocks automated access is reported as `blocked` and left alone.
- Only a citation judged `fake` strikes a claim; a page that would not load is `unreachable`, never `fake`.
- Actions that write outside the team are proposed only and need an explicit confirmation.
- Every skipped slice, dropped juror and capped stage is listed under Degradations.

## Validate

```bash
bash scripts/validate_swarm_skill.sh        # from the repository root
```

The script downloads the official validator on first use (it is stdlib + PyYAML and only reads files; read it before running anything you download), then checks this folder. Exit code 0 means PASS.
