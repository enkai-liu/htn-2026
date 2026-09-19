# Huawei openJiuwen track — what Whitespace shows

Judging weights (Huawei issue #3067): collaboration 30 · scenario 25 · demo completeness 20 · implementation 15 · reusability 10.

## What runs on openJiuwen

Every agent role in Whitespace is host-agnostic (`Role.handle(msg, ctx)` against a `Ctx` protocol) and runs on two hosts that are tested for event parity. With `ORCHESTRATOR=jiuwen` the run executes on **openjiuwen agent-core 0.1.18**, the SDK underneath JiuwenSwarm ([backend/app/orchestration/jiuwen_host.py](../../backend/app/orchestration/jiuwen_host.py)):

- each role is a `CommunicableAgent` on a `TeamRuntime`: P2P `send` for request/response, `publish`/`subscribe` for pub/sub;
- the run is a `BaseTeam` executed by `Runner.run_agent_team_streaming(..., base=True)`;
- role events travel through the team session stream and are forwarded to our event bus, so what the UI draws is what flowed through the openJiuwen runtime (the offline test asserts that more than 50 events were mirrored this way).

## Collaboration that is real, not a pipeline (30)

| Behaviour | Where it is enforced |
|---|---|
| The critic sends scouts back out when the evidence has a hole (max 2 follow-ups) | `roles/critic.py`, event `requery.issued` |
| Critic and advocate run on different model families; the advocate may only concede, distinguish by facet, or challenge the evidence | `roles/advocate.py` |
| A jury of model families votes without hearing the debate; a split (std ≥ 0.25) triggers a targeted re-query and a re-vote on that pair only | `roles/judge.py` detects the split, `roles/conductor.py` issues the re-query; events `jury.vote`, `requery.issued` |
| The verifier's veto is enforced in code: the synthesizer's input is restricted to `verified` / `unverified_lead` claims | `roles/verifier.py`, `roles/synthesizer.py` |
| Dynamic team formation: scouts are staffed by idea type and by which sources are reachable; skipped scouts are shown with the reason | `roles/conductor.py`, event `team.formed` |
| Failure reassignment: a failed source gets one broadened retry, then the run degrades visibly and confidence drops | `roles/scouts/base.py`, `roles/conductor.py`; event `source.failed` |
| Only the resolver writes entities; blackboard write permissions are checked | `core/blackboard.py` |

## Reusability: the `prior-art-swarm` Swarm Skill (10)

[swarm-skill/prior-art-swarm/](../../swarm-skill/prior-art-swarm/) packages the same team as a Swarm Skill (`kind: swarm-skill`, eight roles of `kind: ai_agent`): `SKILL.md`, `workflow.md` (mermaid + gated steps), `bind.md` (budgets, visibility, failure handling), `dependencies.yaml`, eight role files with self-contained Inline Personas, and an executable SwarmFlow script `scripts/workflow.py` in which the veto, the jury tally, scoring and abstention are computed in code. Nothing in it is specific to hackathons: the scouts' source slices are an argument, so the same skill pre-screens a startup idea, a product feature, a research direction or a patent.

### Official validator

Validator: `validate_swarmskill.py` from `openJiuwen-ai/jiuwenswarm` (branch `develop`, pinned to commit `a1241d0c1919`, SHA-256 checked by [scripts/validate_swarm_skill.sh](../../scripts/validate_swarm_skill.sh)). Run on Sat 2026-09-19 12:13 EDT:

```text
$ bash scripts/validate_swarm_skill.sh
Validating Swarm Skill: /Users/enkailiu/Projects/htn-2026/swarm-skill/prior-art-swarm


[PASS] 0 warning(s), 0 error(s).
```

Exit code 0. The validator also statically checks `scripts/workflow.py` against the SwarmFlow safety envelope (literal META, inline prompts, safe imports, phase/agent consistency, budget discipline, no filesystem or subprocess access).

### openJiuwen host test

```text
$ cd backend && .venv-jiuwen/bin/pytest -q tests/test_pipeline_offline.py
.......                                                                  [100%]
7 passed in 3.14s
```

The same end-to-end test runs under both hosts (fake LLM and fake sources, real roles, real scoring) and asserts contract-valid events, the critic and conductor re-queries, the split-jury re-vote, the verifier's veto and abstention.

## Honest status

- The openJiuwen host is tested offline with a fake LLM. It has **not yet** been run against a real model.
- The Swarm Skill passes the official validator. It has **not yet** been executed inside a JiuwenSwarm workspace (team mode or SwarmFlow mode).
- Open question for the booth: does "openjiuwen agent-core + a validated Swarm Skill" count as building "on top of JiuwenSwarm/WorkSwarm"?
