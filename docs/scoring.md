# Scoring

Source of truth: `backend/app/scoring/axes.py` (pure functions, unit-tested), with the corpus-side maths in `search/rarity.py` and the token-level instruments in `signals/surprisal.py`. Higher = more original. Every axis may **abstain** (`score: null`) and says why.

## Design rules

1. **Scores are grounded in retrieval, not in an LLM's opinion.** LLMs are unreliable novelty judges (Si, Yang & Hashimoto 2024), so models are used to *find, argue about and verify* evidence, and as a *measurement instrument* (Axis 3) — never to hand out the number.
2. **Voice is not originality.** The AI-detection result on the pitch is reported in its own panel and never enters the headline. A human can phrase a novel idea in clichés, and an AI can phrase a novel idea well. Two detectors read it: GPTZero, and Fast-DetectGPT curvature on our own base model. The second one exists to be able to *disagree* — one detector can never tell you it is wrong. When they disagree the panel reports both and calls neither. The curvature verdict has an explicit operating point: it flags only above the 95th percentile of **pre-ChatGPT (pre-2022) corpus write-ups**, so its false-positive rate on this genre is 5% by construction rather than by a borrowed threshold, and without that human reference CDF it reports the statistic and refuses to classify.
3. **Abstain rather than guess.** Thin evidence produces "Insufficient evidence: <what is missing>", not a confident number.
4. **One similarity scale for every source.** Devpost/YC hits arrive reranked by the Jina reranker; Hacker News and GitHub hits arrive with no score. All of them are reranked against the *full idea* with the same Jina reranker on the Elastic Inference Service (`scoring/similarity.py`). Without Elastic, a lexical cosine is used and the result is labelled **uncalibrated**.
   Two corrections for what a reranker is — a measure of whether a text answers a query, word for word — both found on the pitch "ai chipmaker", where an explainer titled "How AI Chips are Made" scored 0.34, Etched 0.02 and Cerebras 0.00:
   - **A few-word pitch is scored as a description of itself.** Under 8 content words, records are reranked against the planner's `writeup` (the idea as a project page would put it) rather than the pitch; sentences of the write-up that talk *about* the pitch are dropped (`conductor.scored_as`, `Blackboard.similarity_text`). The calibration population is project write-ups, so this is also the register the CDF was built in. Every agent still reads the pitch as typed.
   - **A reader's grade is a floor.** Each scout has one model call read its new hits beside the idea and grade them `same / close / adjacent / unrelated` (`ScoutRole._grade`, GLM-5.3-Flash, 25 s limit, fails open). `same` floors the hit at the 95th percentile of the crowding CDF and `close` at the 75th, plus a quarter of the reranker's own score so graded hits still rank among themselves (`similarity.graded`). A grade never lowers a score. The record keeps `retrieval.grade` and, when lifted, `retrieval.rerank_raw`. This is a second instrument patched into the first one's scale, not a calibrated measurement: the floors are landmarks of the CDF, chosen, not fitted.
   - The UI shows project similarity on a **match scale** (`frontend/lib/format.ts: matchOf`): a logistic through the CDF's median (0.156 -> 50%) and 95th percentile (0.365 -> 90%). Monotone and display-only; every score in this document is the raw one.

## Axis 1 — Crowding (weight 0.45)

How dense is the neighbourhood of existing work? **Two independent instruments, averaged on the percentile scale** — the only scale they share.

```
# Instrument 1 — retrieval distance
r_i            = reranker score of resolved entity i against the full idea (top 10 entities, after entity resolution)
crowding_lite  = 0.6 · max(r) + 0.4 · mean(top-5 r)
p_rerank       = percentile of crowding_lite in the calibration CDF

# Instrument 2 — retrieval-conditioned surprisal (RCS)
Δ_t            = log p(x_t | x_<t, neighbours) − log p(x_t | x_<t)
RCS            = mean_t Δ_t                                     [nats / token]  ≈ (1/T)·PMI(pitch ; neighbourhood)
p_rcs          = percentile of RCS in the RCS reference CDF

O1             = 100 · (1 − mean of the available percentiles)
```

The reranker measures how *close* the nearest existing projects are. RCS measures how much of your pitch the prior art actually *predicts*: read the pitch twice on a base model, once cold and once with the nearest projects in front of it, and see how many nats per token they save. It has units and an interpretation, where `0.6·max + 0.4·mean(top-5)` has neither. They fail independently, which is the point of running both.

Because Δ is per token, RCS also says **which spans** of the pitch the prior art explains (`explained_spans` on the `surprisal.measured` event) — that drives the pitch highlighting, and it tells the mutator which phrase to rewrite.

Both CDFs come from running ~300 random corpus documents as queries, self excluded (`search/calibration.py`; `build` and `build-rcs`). They answer "crowded compared with what?": a typical hackathon project. An uncalibrated instrument is labelled as such, and with no base model deployed the axis is exactly the single-instrument score it always was and says so in its note.

Entity resolution happens **before** scoring on purpose: a project that appears on Devpost, GitHub and Hacker News is one neighbour, not three — and it contributes one write-up to the RCS context, not three.

## Axis 2 — Facet rarity (weight 0.35)

Which parts of the idea are common, and is the *combination* rare? The idea is decomposed into facets (purpose, mechanism, audience, data, twist).

```
rarity_f = mean IDF of facet f's k=3 most distinctive terms, / log(N+1)      idf(t) = log((N+1)/(df_t+1))
npmi     = log( p(purpose, mechanism) / p(purpose)·p(mechanism) ) / −log p(purpose, mechanism)     ∈ [−1, +1]
pair     = (1 − npmi) / 2
cliche   = |idea terms ∩ significant_text(neighbours)| / |idea terms|
O2       = 100 · (0.5 · mean_f rarity_f + 0.3 · pair + 0.2 · (1 − cliche))
```

**Why per-facet rarity is not a document count.** It used to be `1 − log(1+df_f)/log(1+2000)`, where `df_f` counted documents matching the facet under a `minimum_should_match` rule. No such rule works at both ends. Requiring every word made every LLM-written phrase unique (`df=0`, so every idea scored maximally rare); the fix for that — any 3 words of a long phrase — meant a 20-word mechanism matched **1,020 of 8,110 documents, 12.6% of the corpus**, and scored 0.089. That number measured how long the planner's phrase was, not how rare the idea was.

A facet is a bundle of concepts, not a phrase the corpus either contains or does not. Its rarity is how unusual its most distinctive concepts are, and taking a **fixed k** of them is length-invariant by construction: words more common than the top k cannot enter the top k, so an LLM's verbosity cannot move the score. One `filters` aggregation returns every term's whole-index `df` in a single request. Measured on the 8.1k corpus:

| facet | IDF rarity | old rule |
|---|---|---|
| "Acoustic detection of varroa mite wingbeats" | 1.00 | — |
| "Team of AI agents that search prior art, debate novelty, …" | 0.71 | **0.089** |
| "A web app with a React frontend and a Flask backend" | 0.56 | — |
| "An AI chatbot powered by a large language model" | 0.40 | — |
| "help students study more effectively" | 0.39 | — |

The NPMI pair term still uses document counts, because it is a *ratio*: a lenient match rule largely cancels between the joint and the product of the marginals, where it does not cancel in an absolute count.

**Why NPMI and not a pair document count.** A raw `df(purpose AND mechanism)` only says how many projects match both, so it cannot tell a rare *combination* of two common facets — the case a hackathon idea is actually hoping for — from a pair whose halves are both rare. In a 200k corpus, "help students study" (20,000) × "flashcards" (8,000) gives 3,000 joint hits, but independence predicts 800: they co-occur **4× more** than chance, which is the definition of a cliché pairing. "help students study" × "acoustic sensing" (800) gives 3 joint hits against an expectation of 80: **26× less** than chance. The old formula scored those similarly; NPMI puts them at opposite ends. `+1` = always together, `0` = independent, `−1` = nobody has combined them, i.e. the whitespace.

This is the same observed-vs-expected comparison as the z-score in Uzzi et al., *Atypical Combinations and Scientific Impact* (Science, 2013) — whose result, that the highest-impact work is mostly conventional with one atypical combination, is exactly the intervention the mutator performs. `pair_rarity` (the old curve) remains the fallback when the corpus size is unknown, and the axis reports which measure it used (`pair_measure`).

`significant_text` is an Elasticsearch aggregation: foreground = the idea's top-50 neighbours, background = the whole corpus. Terms that are significant in the neighbourhood are that niche's clichés. Requires the indexed corpus; abstains without it.

## Axis 3 — LLM-predictability (weight 0.20)

If you give language models only the *problem and the audience*, do they independently propose this idea? Four model families on Baseten each propose three ideas at temperature 1.0. Each proposal is embedded (Jina on EIS) and compared with the idea's mechanism + twist.

```
collision = max_j cos(idea, sample_j)
hit_rate  = share of samples with cos > 0.80
O3        = 100 · (1 − 0.6 · pct(collision) − 0.4 · hit_rate)
```

This is about the *idea*, not the phrasing, and it is the operational version of "LLM ideas lack diversity at scale": an idea the models converge on is an idea a thousand other hackers were also handed this weekend. The samples are drawn in the graph as a grey cloud.

## Headline and uncertainty

```
C           = 100 · Π_k (C_k / 100)^(w_k)   weighted geometric mean over RANK_AXES = {crowding, facet_rarity}
RANK        = 100 · F_ref(C)                share of the reference population whose composite is below C
[low, high] = 5th and 95th percentiles of RANK over 1,000 bootstrap replicates
```

**The headline is a percentile rank, not a score.** `63%` means *63% of real hackathon projects, scored by this same pipeline, came out lower*. That is a statement about a named population which someone can go and check. The previous headline was 63 points on a scale nobody had defined, and its axis weights (0.45/0.35/0.20) had to be correct on an absolute scale for the number to mean anything. They still are not derived from anything — but a rank only needs them to preserve an **ordering**, which is a far weaker claim than the one a raw score was making.

**The reference population** is N random corpus documents put through the *same code path* as a live idea: the same hybrid retrieval (self excluded), the same LLM facet-extraction prompt the planner uses, the same term profiles and the same NPMI. "Same" is the whole point; a percentile against a population scored differently means nothing. Build it with `python -m app.search.calibration build-headline --n 300`.

`llm_predictability` is deliberately **not** in the rank: it costs 12 model calls per document, so 3,600 for a 300-document reference. It is reported as its own axis, like Voice. `rank_axes` on every result says which axes the rank covers, and with no reference built the rank is `null` and the UI falls back to the raw composite rather than inventing a percentile.

Measured on the 8.1k corpus with a 120-document reference (quantiles: 5% → 20.4, 50% → 49.5, 95% → 75.4), the run that used to read `14 ± 10.8` now reads **1.7%, interval 0–13%** — an AI-novelty-scorer pitched into a corpus that already contains AI-novelty-scorers.

A geometric mean means one crowded axis cannot be averaged away by two good ones. Crowding is mandatory: without it there is no headline.

**The interval is bootstrapped, and asymmetric.** It used to be `± min(30, 8 + 40·jury_std + 6·abstains)`, a formula with no derivation. On a geometric mean near the floor a *symmetric* band is not even well defined: a real run reported `14 ± 10.8`, claiming 3.2 to 24.8 for an estimator whose axes are clamped at 1 and whose spread up there is strongly one-sided. The raw composite for that run is now **12.8, interval 9.8–26.2**, and its rank 1.7%, interval 0–13%.

Each replicate resamples every input the point estimate was built from — none of which costs another network call, because all of it was already fetched:

| source | how it is resampled | why |
|---|---|---|
| retrieved neighbours | nonparametric bootstrap over the reranker scores | `crowding_lite` leans on `max(r)`, one order statistic of ten selected documents |
| calibration set | uniform draw inside the DKW bound | a percentile read off an empirical CDF of size *n* carries `√(ln(2/α)/2n)` of error — 0.078 at n=300, 0.043 at n=1000 |
| document frequencies | `df′ ~ Binomial(N, df/N)` | the corpus is itself a sample of the projects that exist |
| model samples | nonparametric bootstrap over the 12 prior-collision similarities | `hit_rate` out of 12 trials is a Bernoulli rate, not a constant |

`band` is retained as `(high − low)/2` for callers that want one number, but the interval is the honest output and the UI shows both ends.

**The crowding percentile is fitted in the tail.** Below the 90th percentile of the calibration set the empirical CDF has plenty of points and is used directly. Above it, counting order statistics runs out of resolution exactly where the headline is most sensitive: `crowding_lite = 0.435` had about seven of 300 calibration documents above it, and the difference between 0.977 and 0.990 is the difference between O1 = 2.3 and O1 = 1.0. Worse, *everything* past the largest calibration value read 1.0, so O1 = 0 for a wide range of genuinely different inputs. A Generalised Pareto fitted by probability-weighted moments (Hosking & Wallis 1987 — closed form, far steadier than maximum likelihood at n≈30) takes over above the threshold, joining continuously because `tail_mass = n_exceed/n_total`:

| `crowding_lite` | O1 counting | O1 fitted |
|---|---|---|
| 0.400 | 3.33 | 3.16 |
| 0.435 | 2.33 | 1.76 |
| 0.500 | **0.00** | 0.50 |
| 0.580 | **0.00** | 0.07 |

The fit *replaces* the empirical value above the threshold rather than raising it. The empirical CDF is biased up there — with 300 draws the largest is not the population maximum — so the fit landing below it is correct, not a softening.

## Confidence and abstention

```
E = 0.35 · coverage + 0.25 · (1 − jury_std / 0.35) + 0.25 · verified_share + 0.15 · canary
```

- **coverage** — weighted share of planned sources that answered (devpost 0.40, github 0.20, web 0.20, yc 0.15, hn 0.15, arxiv 0.05). A failed source lowers confidence; it never fails silently.
- **jury_std** — mean standard deviation across the jury's facet-overlap votes (different model families). Disagreement is information: it widens the band, lowers E, and (≥ 0.25) triggers a targeted re-query and re-vote.
- **verified_share** — share of "already exists" claims whose quote was found in the source (layer 1) and whose citation GPTZero did not judge fake (layer 2).
- **canary** — the corpus answered a broad query at all.

| Condition | Result |
|---|---|
| Corpus not searched, or coverage < 0.5 | Headline replaced by "Insufficient evidence: …" (axes still shown) |
| E < 0.45 | Headline withheld with the reason |
| Pitch < 250 characters | Voice panel says "too short for a reliable read" (the search still runs) |
| Claim's quote not found in its source | Claim demoted to *unverified lead*; the synthesizer may mention it only as a lead |
| GPTZero judges a citation `fake` | Claim rejected and logged as a caught hallucination |

## Re-scoring a mutation

A coached mutation is scored by re-running retrieval for the rewritten pitch and recomputing Axis 1 (about 3–5 s). `delta` is the change in the crowding score; the mutation's node moves outward in the graph as its neighbourhood thins.
