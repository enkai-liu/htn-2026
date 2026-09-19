# Scoring

Source of truth: `backend/app/scoring/axes.py` (pure functions, unit-tested). Higher = more original. Every axis may **abstain** (`score: null`) and says why.

## Design rules

1. **Scores are grounded in retrieval, not in an LLM's opinion.** LLMs are unreliable novelty judges (Si, Yang & Hashimoto 2024), so models are used to *find, argue about and verify* evidence, and as a *measurement instrument* (Axis 3) — never to hand out the number.
2. **Voice is not originality.** GPTZero's AI-detection result on the pitch is reported in its own panel and never enters the headline. A human can phrase a novel idea in clichés, and an AI can phrase a novel idea well.
3. **Abstain rather than guess.** Thin evidence produces "Insufficient evidence: <what is missing>", not a confident number.
4. **One similarity scale for every source.** Devpost/YC hits arrive reranked by the Jina reranker; Hacker News and GitHub hits arrive with no score. All of them are reranked against the *full idea* with the same Jina reranker on the Elastic Inference Service (`scoring/similarity.py`). Without Elastic, a lexical cosine is used and the result is labelled **uncalibrated**.

## Axis 1 — Crowding (weight 0.45)

How dense is the neighbourhood of existing work?

```
r_i            = reranker score of resolved entity i against the full idea (top 10 entities, after entity resolution)
crowding_lite  = 0.6 · max(r) + 0.4 · mean(top-5 r)
pct            = percentile of crowding_lite in the calibration CDF
O1             = 100 · (1 − pct)
```

The calibration CDF comes from running ~300 random corpus documents as queries (self excluded) and recording their `crowding_lite` (`search/calibration.py`). It answers "crowded compared with what?": a typical hackathon project. Until calibration has been run the axis is labelled uncalibrated.

Entity resolution happens **before** scoring on purpose: a project that appears on Devpost, GitHub and Hacker News is one neighbour, not three.

## Axis 2 — Facet rarity (weight 0.35)

Which parts of the idea are common, and is the *combination* rare? The idea is decomposed into facets (purpose, mechanism, audience, data, twist).

```
rarity_f = 1 − log(1 + df_f) / log(1 + 2000)            df_f = corpus documents matching facet f (all terms)
pair     = 1 − log(1 + df(purpose AND mechanism)) / log(1 + 200)
cliche   = |idea terms ∩ significant_text(neighbours)| / |idea terms|
O2       = 100 · (0.5 · mean_f rarity_f + 0.3 · pair + 0.2 · (1 − cliche))
```

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
O    = 100 · Π_k (O_k / 100)^(w_k)          weighted geometric mean over axes that did not abstain (weights renormalised)
band = ± min(30, 8 + 40 · mean jury std + 6 · number of abstaining axes)
```

A geometric mean means one crowded axis cannot be averaged away by two good ones. Crowding is mandatory: without it there is no headline.

## Confidence and abstention

```
E = 0.35 · coverage + 0.25 · (1 − jury_std / 0.35) + 0.25 · verified_share + 0.15 · canary
```

- **coverage** — weighted share of planned sources that answered (devpost 0.40, github 0.20, yc 0.15, hn 0.15, other 0.05 each). A failed source lowers confidence; it never fails silently.
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
