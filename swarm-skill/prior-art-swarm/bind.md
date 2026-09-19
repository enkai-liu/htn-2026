# Execution Guardrails

The numbers below are mirrored as constants at the top of [scripts/workflow.py](scripts/workflow.py). Change them here first, then there.

## Resource Constraints

| Item | Limit | Reason |
|---|---|---|
| `max_parallel_teammates` | 6 | One scout per source slice; matches the widest fan-out in workflow.md (Step 2). Jurors and blind samplers fan out to at most 4 |
| `total_wall_clock_budget` | 35 min | Worst case, not the expected duration: the longest path has 14 sequential barriers at the role timeout and 5 at the scout timeout (27.5 min), a second debate round adds 2.5 min, and the user confirmation can wait 5 min. Parallel fan-outs cost one barrier each |
| `total_token_budget` | 150k tokens (recommended ceiling; the host declares it when it launches the run) | Across all roles: 70 dispatches at roughly 2k tokens each. Once a ceiling is declared and fewer than 20k tokens remain, optional stages stop being dispatched |
| `max_model_calls` | 70 dispatches (floor 30) | The mandatory path needs at most 22; optional stages are dropped first, and 2 dispatches are always held back for the citation check and the synthesizer |
| `per_role_wall_clock` | scout 120 s · every other role 75 s · user confirmation 300 s | Scouts wait on external sources; a confirmation waits on a person |
| `debate_rounds` | 1 (max 2) | A second round runs only while contested claims remain; each round adds two dispatches |
| `critic_followups` | max 2 per run, first round only | Back-edge 1. Each must name a facet, a staffed slice and a query of at most 120 characters |
| `jury_tiebreaks` | max 1 per run | Back-edge 2. Triggered when the spread on an (entity, facet) pair is ≥ 0.25 |
| `jurors` / `blind_samplers` | max 4 / max 4 | One per model family; three same-family jurors when no families are configured, reported as a caveat |
| `records_per_scout` / `max_records` | 8 / 60 | Keeps every downstream prompt bounded |
| `claims_per_turn` / `jury_entities` | 8 / 4 | The jury scores only entities the critic made a live claim about |
| `citation_checks` | max 8 per run | Layer 2 of the veto; layer 1 (the quote check) always covers every claim |
| `adjudication_pairs` | 16 per call; above 24 ambiguous pairs the resolver stage runs on rules only | Title-similarity candidates (trigram ≥ 0.6) can grow quadratically |
| `mutations` | max 3 | Each costs one extra scout dispatch to re-score |
| `idea_length` | min 8 words or 40 characters; cut at 6,000 characters | Below the minimum there is nothing to decompose |
| `min_quote_words` | 4 (8 characters in scripts without word spacing) | Shorter quotes prove nothing and are refused by the quote check |
| `min_coverage` / `min_confidence` | 0.5 / 0.45 | Below either, the headline is withheld and the run abstains |

## Behavioral Constraints

- **Leader-as-orchestrator only**: the Leader plans, dispatches teammates, runs the deterministic checks and integrates outputs. The Leader does NOT search, write claims, score overlap or substitute any role's work.
- **Phase-scoped visibility** (the Swarm Skill declares who sees whose output at which phase; delivery is the framework's choice: (1) direct peer-to-peer exchange, (2) shared blackboard, (3) Leader-relay as fallback):
  - Step 2: scouts are isolated. No scout sees another scout's records.
  - Step 4: the critic sees entities and evidence text. The advocate sees the critic's claims with their quotes and source text. From the second round each sees the other's previous turn.
  - Step 4: jurors are isolated from each other AND from the debate. They see the idea, its purpose and mechanism, and the entity listings only.
  - Step 4: blind samplers see the problem and the audience, never the idea.
  - Steps 6 and 7: the synthesizer and the coach see surviving claims only. Struck and withdrawn claims are withheld by the Leader, not by instruction.
- **Write permissions**: only scouts add records; only the resolver stage writes entities; only the critic creates claims; only the verifier stage changes a claim's verification status. No role edits another role's output.
- **The veto is enforced in code**: the quote check is a deterministic string match run by the Leader, never delegated to a model. Only a citation status of `fake` strikes a claim at layer 2; `unreachable` and `unchecked` never do.
- **Stage gates refuse to open**: Step 3 does not start until every staffed slice has a final status; Steps 6 and 7 MUST NOT start until every claim has a final verification status from Step 5, and they receive surviving claims only.
- **Scores are computed, not written**: no role produces, adjusts or re-states an axis score, the headline or the confidence value.
- **Contradiction handling**: when roles or sources disagree, the Leader surfaces both sides verbatim in the Final Report. The Leader NEVER mediates, picks a winner or averages opinions. The jury's spread is reported, not smoothed.
- **No evasion of access controls**: a source that blocks automated access, shows a bot challenge, requires a login or is excluded by robots rules is recorded as `blocked` and left alone. No role retries it through another route.
- **Nothing fails silently**: every skipped slice, dropped juror, capped stage and missing role is recorded under Degradations in the Final Report.
- **Outside-world actions need a person**: arming a recurring watch or writing the idea back to a corpus is only proposed. It runs after an explicit user confirmation, and an absent or timed-out confirmation approves nothing.

## Failure Handling

### (a) Teammate failure

| Failure mode | Response |
|---|---|
| Scout timeout, failure or empty result | One broadened retry. A retry that returns records marks the slice `degraded`; otherwise the slice is `failed` or `empty`. Coverage and confidence drop accordingly |
| Scout reports the source is blocked | Slice marked `blocked`. No retry, no alternative route |
| Malformed teammate output | The Leader extracts the first JSON object it can find. If nothing usable remains, treat as a timeout for that role |
| Planner returns nothing | The run is `failed` with `[ROLE MISSING - planner]`; no team is formed |
| Resolver returns nothing | `[ROLE MISSING - resolver]`; rule-based merges (shared URL) stand and every ambiguous pair is left unmerged as `insufficient_evidence` |
| Critic returns nothing | `[ROLE MISSING - critic]`; no claims this round; the run continues to scoring from retrieval alone |
| Advocate returns nothing | `[ROLE MISSING - advocate]`; claims stand unanswered and are reported as such |
| A juror returns no ballot | That juror is dropped and the drop is recorded. No ballot at all → `[ROLE MISSING - judge]`; crowding falls back to the scouts' similarity |
| Verifier returns nothing | `[ROLE MISSING - verifier]`; claims rest on the quote check alone, and the report says layer 2 did not run |
| Synthesizer returns nothing | A rule-written verdict is used and marked `written_by: rules` |
| Coach returns nothing, or a mutation cannot be re-scored | No mutations, or the mutation is reported as not re-scored with no delta |

### (b) Input over-scale and under-scale degradation

| Trigger condition | Degraded mode |
|---|---|
| Idea shorter than 8 words and 40 characters, or no purpose and mechanism can be extracted | Stop before dispatching a team with status `needs_input`; ask what it does, for whom, and how |
| Idea longer than 6,000 characters | Cut to 6,000 characters for every prompt; recorded as a degradation |
| No source slice can be staffed (no search capability found in pre-flight) | No scouts run; Step 6 abstains with the missing capability named |
| More than 60 records | Later records are not ingested |
| More than 24 ambiguous candidate pairs | Resolver stage runs on rules only |
| Dispatch cap or token reserve reached | Each optional stage (second debate round, critic follow-ups, jury tie-break, predictability probe, citation check, coaching) checks what is left when it is reached and is skipped if it does not fit, always keeping 2 dispatches back for the citation check and the synthesizer. Each skip is recorded |
| A dependency marked `required: false` was missing in pre-flight | The user already chose to proceed in Step 0; the missing dependency is recorded in the Final Report |

### Escalation rules

- If 50%+ of roles are `[ROLE MISSING]`, the run is **FAILED**: emit a partial report headed "FAILED: insufficient role coverage" and surface it to the user.
- If no source returned any prior work, the run **abstains**. The report states that this is not a finding that the idea is original.
- If `total_wall_clock_budget` is exceeded, halt all in-flight teammates, emit whatever partial outputs exist, and tag the report `INCOMPLETE: budget exceeded`.
- If `total_token_budget` is exceeded mid-run, halt new dispatches, allow in-flight to complete, emit a partial report tagged `INCOMPLETE: token budget exceeded`.
