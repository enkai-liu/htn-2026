---
name: prior-art-swarm
description: |
  Eight-role prior-art investigation (scouts, resolver, critic-advocate debate, model jury, verifier veto, synthesizer, coach) that scores an idea's originality from verified evidence and coaches it toward open ground.
  Use when someone wants to know whether an idea, product, feature or research direction has already been done, and how to make it more distinctive.
  Do NOT use for legal patentability or freedom-to-operate opinions, plagiarism checks on finished text, or general market sizing.
version: "1.0.0"
kind: swarm-skill
roles:
  - id: scout
    kind: ai_agent
    purpose: Searches one source slice for prior work, isolated from the other scouts, and returns verbatim excerpts; re-dispatched when evidence is missing.
    skills: []
    tools: [web_search, elastic-agent-builder-mcp]
  - id: resolver
    kind: ai_agent
    purpose: Merges listings of the same work into entities, fuses fields by source reliability, and surfaces conflicts and imputed fields.
    skills: []
    tools: []
  - id: critic
    kind: ai_agent
    purpose: Argues the idea already exists, one verbatim-quoted claim per overlapping entity, and may send scouts back out for missing evidence.
    skills: []
    tools: []
  - id: advocate
    kind: ai_agent
    purpose: Answers every critic claim by conceding, distinguishing by facet or challenging the evidence; runs on a different model family.
    skills: []
    tools: []
  - id: judge
    kind: ai_agent
    purpose: Jury of independent model families that scores facet overlap; a split jury triggers one targeted re-query; also rates blind model proposals.
    skills: []
    tools: []
  - id: verifier
    kind: ai_agent
    purpose: Holds the veto - a claim survives only if its quote is in the source text and its citation is not judged fake by an independent check.
    skills: []
    tools: [web_fetch]
  - id: synthesizer
    kind: ai_agent
    purpose: Writes the verdict from surviving claims only, reports per-axis scores with a confidence value, and abstains rather than guessing.
    skills: []
    tools: []
  - id: coach
    kind: ai_agent
    purpose: Proposes single-facet mutations grounded in corpus whitespace terms and has each one re-scored by re-running retrieval.
    skills: []
    tools: []
---

# Prior-Art Swarm

A mixed-pattern team: scouts fan out in parallel by source slice (B), a resolver turns listings into entities (C), a critic and an advocate debate the evidence in front of a multi-model jury with two back-edges that send scouts out again, and a verifier gate decides which claims the synthesizer and the coach are allowed to use. It exists to remove one failure mode: a single agent that searches, judges and cites for itself will confidently report prior work that does not exist, miss the work that does, and never notice, because nothing in it is positioned to disagree.

The idea can be anything that can be described in a paragraph: a hackathon project, a startup, a product feature, a research direction, a patent pre-screen. Only the scouts' source slices change.

## Workflow

0. **Pre-flight: check dependencies** — read [dependencies.yaml](dependencies.yaml) and verify each entry.
   Report missing items: `required: true` = likely fails without it; `required: false` = degraded but functional. **User decides** whether to proceed.
   The team can run on inline-persona-only mode: no skill is required, and every tool except a search capability is optional.
   Note: dependencies were populated during authoring via Stage 2 auto-matching (local scan). `skills: []` means "checked, none needed". Tool availability found here decides which scouts can be staffed in Step 1.

1. **Plan and form the team** — Leader. Decompose the idea into five facets (purpose, mechanism, audience, data, twist), write the search queries, and staff one scout per source slice that is both relevant to this kind of idea and reachable with the tools found in Step 0. Scouts that are not staffed are reported with the reason. An idea too short to decompose stops here: see [bind.md](bind.md) § Failure Handling (b).

2. **Scout in parallel** — scout × N, one per source slice, isolated from each other. A scout that fails gets one broadened retry, then its slice is marked degraded or failed and confidence drops. A blocked source is reported as blocked, never evaded. Limits: [bind.md](bind.md) § Resource Constraints.

3. **Resolve** — resolver. Listings of the same work across sources become one entity (verdicts: same, different, insufficient_evidence). Fields are fused with source-reliability priors; conflicts and imputed fields are surfaced, not smoothed over. Zero evidence skips to Step 6, which abstains.

4. **Debate** — critic, advocate, judge. The critic claims "already done" with verbatim quotes and may send scouts back out. The advocate must concede, distinguish by facet, or challenge the evidence. The jury scores facet overlap independently; a split jury triggers one targeted re-query on exactly the disputed facet and a re-vote on that pair only. The judge also runs the blind predictability probe. Rounds and caps: [bind.md](bind.md); full protocol: [workflow.md](workflow.md) Step 4.

5. **Verify (veto gate)** — verifier. A claim survives only if its quote is found in the source text and its citation is not judged fake by an independent check. Struck claims are listed in the report and never reach Steps 6 or 7. The gate is enforced outside the prompt: see [workflow.md](workflow.md) Step 5.

6. **Synthesize** — synthesizer. Per-axis scores and a confidence value from surviving claims only. When coverage or confidence is too low it abstains with "Insufficient evidence: …" instead of producing a number.

7. **Coach** — coach, then scouts again. Single-facet mutations grounded in corpus whitespace terms; each mutated pitch goes back to a scout so its crowding is re-measured by re-running retrieval. No retrieval, no claimed improvement.

8. **Final: emit the Originality Report** — Leader. Verdict or abstention, axis scores, verified prior work with citations, struck claims, conflicts, unresolved disputes, coverage map, re-scored mutations, degradations and proposed actions (format in [workflow.md](workflow.md) Step 8). The Leader surfaces contradictions verbatim and never mediates. Actions that write outside the team (arming a recurring watch, writing the idea back to a corpus) are only proposed; they run after an explicit user confirmation.

## Roles

| id | Purpose | When dispatched | Input | Key dependencies | Role file |
|---|---|---|---|---|---|
| scout | Search one source slice; bring back verbatim excerpts | Step 2, N in parallel; again on a critic follow-up, a jury tie-break and each mutation re-score | idea, facets, its slice, its queries, its assignment | web_search (required); elastic-agent-builder-mcp (optional) | [roles/scout.md](roles/scout.md) |
| resolver | Merge listings into entities; surface conflicts and imputed fields | Step 3; again whenever a back-edge adds records | all scout records, candidate pairs, reliability priors | none | [roles/resolver.md](roles/resolver.md) |
| critic | Argue "already done" with verbatim quotes; request follow-up searches | Step 4, every round | idea, facets, resolved entities with their evidence text, staffed slices | none | [roles/critic.md](roles/critic.md) |
| advocate | Concede, distinguish by facet, or challenge the evidence | Step 4, after the critic, every round; different model family from the critic | idea, facets, the critic's claims with quotes and source text | none | [roles/advocate.md](roles/advocate.md) |
| judge | Independent ballots on facet overlap; rate blind proposals | Step 4, one juror per model family in parallel; re-vote after a split | idea, purpose, mechanism, contested entities; blind proposals for the probe | none | [roles/judge.md](roles/judge.md) |
| verifier | Quote check and independent citation check; veto | Step 5, every run that produced claims | claims, quotes, cited evidence text and URLs | web_fetch (optional) | [roles/verifier.md](roles/verifier.md) |
| synthesizer | Verdict, axis scores, confidence, or abstention | Step 6, every run | surviving claims with their debate, distinctions, conflicts, coverage, scores or scoring rules | none | [roles/synthesizer.md](roles/synthesizer.md) |
| coach | Single-facet mutations, each re-scored by retrieval | Step 7, when evidence exists and budget remains | idea, facets, crowded neighbours, whitespace and cliché terms, distinctions | none | [roles/coach.md](roles/coach.md) |

> Before dispatching each teammate, read the corresponding role file and extract the
> `## Inline Persona for Teammate` section — paste it directly into the dispatch prompt.
> Most adopting agents do NOT auto-load role files for teammates.

## Files

| File | What it contains | When to read |
|---|---|---|
| [workflow.md](workflow.md) | Mermaid diagram, step-by-step protocol with quality gates, the two back-edges, Final Report format | Before first dispatch — the complete playbook |
| [bind.md](bind.md) | Budgets, caps and thresholds, phase-scoped visibility, write permissions, failure handling and degraded modes | When hitting limits, handling failures, or needing degraded-mode rules |
| [roles/\*.md](roles/) | Per-role identity, success criteria, boundary, output schema, Inline Persona for Teammate | Before dispatching each teammate — extract Inline Persona |
| [dependencies.yaml](dependencies.yaml) | External skills and tools required to run | **Startup** — verify deps, report missing items, user decides go/no-go |
| [scripts/workflow.py](scripts/workflow.py) | Executable workflow script: the same topology, with the veto, the jury tally, scoring and abstention computed in code | When running in SwarmFlow mode |
| [README.md](README.md) | Install, run, arguments, how to point the scouts at other sources | When adopting the skill in a new workspace or domain |
