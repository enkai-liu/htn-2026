# The Slop Index

How much of the hackathon idea-space is now written by AI, and are those write-ups less original?

A year-stratified, length-controlled GPTZero scan of Devpost project write-ups from 2018 to 2026, with a placebo-year
false-positive rate and a test that ties the detector's verdict back to what Whitespace measures (crowding).
The format follows GPTZero's own NeurIPS / ICLR investigations: an unscanned corpus, a headline number with an
interval, and a public artifact anyone can re-analyse.

## Run it

All commands from the repo root, with the backend venv.

```bash
PY=backend/.venv/bin/python

$PY -m ingest.download_hf --yes               # once: both datasets (~390 MB) into data/  (or: investigation.sample --download)
$PY -m investigation.sample                   # 150 write-ups per year, seed 20260919

GPTZERO_MODE=live $PY -m investigation.scan --dry-run      # plan + word estimate, spends nothing
GPTZERO_MODE=live $PY -m investigation.scan --pilot        # 4 years x 50  (~60k words: 1,800 chars is ~290 words)
GPTZERO_MODE=live caffeinate -i $PY -m investigation.scan  # the rest; resumable, stops at the word cap

$PY -m investigation.analyze                  # -> investigation/results/slop_index.json  (read by /slop-index)
$PY -m investigation.export_public            # -> investigation/results/slop_index_public.csv
```

**Word budget.** A write-up cut at 1,800 characters is about 290 words, not the 200 the plan assumed: 8 years x 150 is
roughly 350k words, more than the 230k `investigation` cap. The scan interleaves years and stops cleanly at the cap,
so what it has is still balanced (about 95 per year). To finish all 150: get the word bump from the GPTZero booth and
raise `GPTZERO_INVESTIGATION_WORD_CAP`, or run `scan --per-year 95`, or re-sample with `sample --max-chars 1200`.
`sample` prints the exact estimate for the sample it drew.

No key yet? `$PY -m investigation.scan --allow-replay --limit 40` exercises the whole pipeline offline with synthetic
fixture verdicts. Those rows carry `model_version = replay-fixture`, `analyze` stamps its output `sample_data: true`,
and `export_public` refuses to publish them. A live run re-scans them for real.

| File | Contents | Committed? |
|---|---|---|
| `results/sample.parquet` | `sample_id, year, source_dataset, text, n_chars, n_words, is_winner, rank` | no (`*.parquet` is ignored) |
| `data/investigation_private/sample_map.parquet` | `sample_id` -> project URL, title, hackathon | **never** (`data/` is ignored) |
| `results/raw/scans.jsonl` | append-only scan log, the resume point | no |
| `results/scans.parquet` | `sample_id, year, predicted_class, confidence_category, subclass, ai_sentence_share, n_words, is_winner, model_version` | no |
| `results/slop_index.json` | aggregates for the page | yes |
| `results/slop_index_public.csv` | `year, predicted_class, confidence_category, subclass, nn_sim, is_winner` | yes |

`nn_sim` (mean similarity to a write-up's 5 nearest semantic neighbours) comes from `investigation/neighbours.py`, which
writes `results/neighbours.parquet` (`sample_id, nn_sim`). Without it `analyze` still runs and reports `tie_in: null`.

## Method

**Corpus.** `alvanlii/devpost-hackathon-projects` (261,940 projects, through January 2025) for 2018, 2019, 2021, 2022,
2023 and 2024, and `twangodev/devpost-hacks` (2,222 projects) for 2025 and 2026. The historic dataset has no date
column; a project's year is the **end** of its hackathon's `submission_period_dates` from `hackathons.json`
("Dec 15, 2023 - Jan 20, 2024" counts as 2024, because that is when the write-up was finalised). The recent dataset
only has the hackathon's Devpost slug; the slug-to-year table in `common.py` was checked against
`devpost.com/api/hackathons`.

**Eligibility.** English write-ups of at least 600 characters. Language is a cheap heuristic (ASCII share plus the
share of common English function words), good enough to drop other languages, not a language identifier.
Duplicate URLs and duplicate openings are removed.

**Length control.** Every write-up is truncated to 1,800 characters at a sentence boundary before scanning. Detector
accuracy depends on length, and write-ups have grown over the years; without this, a change in length would show up
as a change in "AI share". `sample_summary.json` records the median pre-truncation length per year.

**Sampling.** N per year (default 150), taking the N smallest values of `sha256(seed : url)`. That is a uniform draw,
reproducible on any machine, and stable under N: the 50-per-year pilot is a subset of the 150-per-year run, so no
pilot scan is wasted.

**Detector.** GPTZero `POST /v2/predict/text`, one call per write-up. We read `predicted_class`,
`confidence_category` and `subclass`. The deprecated `*_generated_prob` fields are never read or stored, masked
sentences (`should_mask`) are excluded from `ai_sentence_share`, and raw probabilities are not reported anywhere.

**Headline.** The share of write-ups classed `ai` or `mixed` **with `high` confidence**, per year, with a Wilson 95%
interval, split by subclass (`pure_ai`, `ai_paraphrased`, `polished`, `concatenated`). `high` is the band GPTZero
thresholds to under 1% error on its own benchmarks; nothing softer is counted.

**Placebo years.** ChatGPT launched on 2022-11-30. A write-up from 2018-2021 that is flagged is a false positive, so
the pooled flag rate for those years is the detector's empirical false-positive rate *on this genre*. It is reported
next to the headline, with its own interval, and every later year should be read against it rather than against zero.

**Tie-in test.** Does the detector's verdict say anything about originality? We compare `nn_sim` between flagged
write-ups and confidently human ones (`human` + `high`): Mann-Whitney U with the normal approximation, tie-corrected
variance and a continuity correction, two-sided, plus Cliff's delta as the effect size. It is reported within each year
(at least 5 write-ups per group) and pooled across years as a **stratified** test: within-year U statistics are summed
and only within-year pairs enter the pooled delta, so a trend over time in either variable cannot manufacture the
effect. The statistics are implemented with numpy in `stats.py` and unit-tested against hand-computed examples.

**Winners.** Winner share by predicted class, with Wilson intervals. `is_winner` is a non-empty `prize` list in the
historic data and the dataset's own flag in the recent data.

## Caveats

- **A flag is not proof.** The detector is probabilistic. The placebo rate is our honest estimate of how often it is
  wrong on hackathon write-ups, a genre it was not benchmarked on: short, templated ("Inspiration / What it does / How we
  built it"), often written by non-native speakers at 5 am. Non-native English is a known source of false positives.
- **Style drift.** Devpost's prompts, typical length and the register of hackathon writing changed between 2018 and
  2026 for reasons unrelated to AI. Length is controlled; register is not.
- **Two datasets.** 2018-2024 and 2025-2026 come from different collections with different hackathon mixes (the recent
  one is a handful of large US collegiate events). A jump between 2024 and 2025 may partly be a change of population.
- **AI-written is not unoriginal.** A person can describe a novel project in boilerplate, and a model can phrase a
  novel idea. That is why Whitespace shows Voice as its own axis and never folds it into the originality score. The
  tie-in test reports an association between two measurements; it does not show that using an LLM makes ideas worse.
- **Sample size.** 150 per year gives intervals several points wide. Subclass splits and within-year tests are
  exploratory; the pooled, stratified numbers carry the argument.
- **Truncation.** Only the first 1,800 characters are scanned. A write-up with a human opening and a generated tail
  would be missed.

## Ethics

- **Aggregates only.** We publish yearly shares, intervals and an anonymised CSV. No project, team, hackathon or
  student is named, on the page, in the repo or in the demo.
- **No identifiers leave the machine.** Project URLs live only in `data/investigation_private/` (git-ignored).
  `sample_id` is a hash of the URL, so it is treated as private too and is dropped from the public CSV; rows are
  shuffled and `nn_sim` is rounded so neither order nor precision can be used to re-identify a row.
- **No individual verdicts.** We do not tell anyone "this write-up is AI". The false-positive rate makes individual
  accusations indefensible, and using an LLM to tidy a write-up breaks no rule.
- **Data use.** Both datasets are public Hugging Face datasets of public Devpost pages, used here for a
  non-commercial hackathon project and attributed in the root README. `devpost.com/software/search` is never fetched.
- **Budget.** Scans are charged to a separate `investigation` word bucket with a hard cap, so the study cannot
  starve the live product.
