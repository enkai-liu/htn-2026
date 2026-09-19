> Generated during planning (Sat 2026-09-19 ~01:30 EDT). `[V]`/**[VERIFIED]** = checked against a live source; `[T]`/**[INFERRED]** = must be tested by the team.

# A. GPTZero — "Best Use of GPTZero API"

## A0. Context you should know before talking to their judges

- **GPTZero was acquired by Superhuman (formerly Grammarly) — announced 2026-06-23.** GPTZero continues as a standalone product; co-founder Alex Cui and the ~30-person team joined Superhuman. Stated framing: building the internet's "authenticity layer." ([TechCrunch](https://techcrunch.com/2026/06/23/superhuman-acquires-ai-detection-startup-gptzero/), [SiliconANGLE](https://siliconangle.com/2026/06/24/grammarly-parent-superhuman-buys-ai-detector-gptzero/), [BetaKit](https://betakit.com/superhuman-formerly-grammarly-acquires-ai-detector-gptzero/)) — *verified across three outlets.*
- **HTN 2026 prize tiers** ([Devpost](https://hackthenorth2026.devpost.com/)): 1st = AirPods Pro 3 + premium swag + $2000 GPTZero credits **per teammate**; 2nd = swag + $500 credits per teammate. 2 winners.
- **The "investigative" half of the prize text is literally GPTZero's own content-marketing playbook.** They ran exactly this play twice and got mainstream press:
  - [GPTZero found 100+ hallucinated citations in NeurIPS 2025 accepted papers](https://gptzero.me/news/neurips/) → [covered by Fortune](https://fortune.com/2026/01/21/neurips-ai-conferences-research-papers-hallucinations/)
  - [50+ hallucinations in 300 of ~20,000 ICLR 2026 submissions](https://gptzero.me/news/iclr-2026/), several in papers rated 8/10 by 3–5 peer reviewers. Published as an **interactive spreadsheet** with paper titles, review scores, OpenReview links, and per-hallucination notes.
  - **Takeaway: they reward a scan of a corpus nobody has scanned, with a shareable artifact and a headline number.** Mirroring this structure is the single highest-signal thing you can do.

---

## A1. AI Detection API — verified from the live docs backend

The docs at `https://gptzero.me/docs` 307-redirect to `https://gptzero.stoplight.io/`, which is a JS SPA that WebFetch can't render. I pulled the **actual spec** out of its backend (Stoplight project `cHJqOjIwMzk5MA`):

```
https://gptzero.stoplight.io/api/v1/projects/cHJqOjIwMzk5MA/table-of-contents
https://gptzero.stoplight.io/api/v1/projects/cHJqOjIwMzk5MA/nodes/<slug>
```

Everything in A1/A2 below is from those responses unless marked otherwise. **This is authoritative, not reconstructed.**

### Base URL + auth
- Production server: `https://api.gptzero.me` (paths carry their own `/v2` or `/v3`)
- Header: **`x-api-key: <key>`** (plus `Accept: application/json`, `Content-Type: application/json`)
- Get a key: https://app.gptzero.me/app/api

### The full endpoint list (8 endpoints — note there is no `/batch` or `/reports`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/v2/predict/text` | AI detection on a single string |
| POST | `/v2/predict/files` | AI detection on an array of files |
| POST | `/v2/bibliography-scan/text` | **Hallucination / citation + claim verification** |
| POST | `/v2/bibliography-scan/files` | Same, on uploaded files |
| POST | `/v3/ai/patterns/stream` | **AI writing-pattern ("tropes") detection, SSE stream** — allow-list gated |
| GET | `/v2/model-versions/ai-scan` | Available detector model versions |
| GET | `/v2/api-versions/ai-scan` | Available response-format versions |
| GET | `/v3/usage-stats` | Words used / words left / billing cycle |

> ⚠️ A third-party "API Evangelist" profile ([api-evangelist/gptzero](https://github.com/api-evangelist/gptzero)) and [jentic.com](https://jentic.com/apis/gptzero.com/gptzero) both publish a *reconstructed* OpenAPI claiming 7 endpoints including `POST /batch`, `GET /batch/{id}`, `GET /reports`. **Those endpoints do not exist in GPTZero's real docs.** Don't code against them. That profile's own README says it's an unaffiliated scrape.

### `POST /v2/predict/text` — request

```json
{
  "document": "string (REQUIRED)",
  "multilingual": false,
  "modelVersion": "",
  "apiVersion": ""
}
```

- `document` — **truncated to 50,000 characters** (silently, no error).
- `multilingual` — *verbatim from the spec:* "the language in which the input text is written will be detected and a special multilingual AI detection model will be used. **Currently supported languages for this feature are French and Spanish**." If true and language unsupported → falls back to the English model. **Do not set `modelVersion` when `multilingual: true`.**
  - ⚠️ **Discrepancy worth knowing:** GPTZero's marketing pages claim [20+ languages](https://gptzero.me/news/multilingualdetection/) (Arabic, Italian, Korean, Chinese, Japanese, Turkish, Hindi, Dutch, Vietnamese, Indonesian…). The **API docs only list French and Spanish** for the `multilingual` flag, with a Google Form to request others. Assume English-only for your hack unless you test otherwise.
- `modelVersion` — e.g. `2025-11-28-base`. List via `GET /v2/model-versions/ai-scan`.
- `apiVersion` — controls **response format**. Empty = latest.

### `POST /v2/predict/text` — response (`DocumentPredictionsV3`)

Top level:
```
version          string   e.g. "2025-11-28-base"   (yyyy-mm-dd-{model_name})
neatVersion      string   e.g. "3.14b"             (x.y.{model_indicator})
scanId           string   uuid, dashboard linkage
meta.pagesCount  integer
documents[]      array
```

Per document — **document level**:

| Field | Type | Notes |
|---|---|---|
| `predicted_class` | `"human" \| "ai" \| "mixed"` | highest-probability class |
| `class_probabilities` | `{ai, human, mixed}` | each 0–1; the one matching `predicted_class` = chance the detector is right |
| `confidence_category` | `"high" \| "medium" \| "low"` | **thresholded so `high` has <1% error rate**. At `high`: 99.1% of human articles → human, 98.4% of AI articles → AI |
| `confidence_score` | number | *"normalized confidence score used internally for visualization. Refer to `confidence_category` instead for what to display"* |
| `document_classification` | `"HUMAN_ONLY" \| "MIXED" \| "AI_ONLY"` | the simple display-level label |
| `result_message` | string | one of 7 fixed strings, e.g. "Our detector is highly confident that the text may include parts written by AI" |
| `result_sub_message` | string \| null | extra context |
| `subclass` | object | **only when `predicted_class` is `ai` or `mixed`**. `subclass.ai.predicted_class` ∈ `pure_ai` \| `ai_paraphrased` (bypasser used); `subclass.mixed.predicted_class` ∈ `concatenated` \| `polished` (human-written, AI-polished). Each subclass carries its own `class_probabilities`, `confidence_category`, `confidence_score`. |
| `completely_generated_prob` | number | **⚠️ marked DEPRECATED / internal-use-only in the spec.** Still returned. Every third-party client in the wild reads this field. |
| `average_generated_prob` | number | **⚠️ DEPRECATED, "For Internal Use Only. Do not rely on this field for evaluation."** |
| `overall_burstiness` | number | (0 in modern responses) |
| `excluded_spans[]` | array | `{start, end, text, reason}` — char offsets of masked regions (e.g. `reason: "header"`) |
| `language` | string | e.g. `"en"` |
| `document_id` | string | |
| `writing_stats`, `confidence_thresholds_raw`, `confidence_scores_raw`, `pageNumber`, `inputText` | | raw threshold values are `{reject: 0.33, low: 0.6, medium: 0.8}` per class |

**Paragraph level** — `paragraphs[]` (newline-delimited bodies of text):
```
start_sentence_index  integer   index into sentences[] of first sentence
num_sentences         integer
completely_generated_prob  number   (spec: "legacy / internal use only. Do not use.")
```

**Sentence level** — `sentences[]` (in document order):
```
sentence                   string
generated_prob             number    P(this sentence AI-generated)
perplexity                 integer   lower ⇒ more likely AI
highlight_sentence_for_ai  boolean   true iff sentence generated_prob AND paragraph
                                     completely_generated_prob both exceed threshold
class_probabilities        {human, ai, paraphrased}    ← note: "paraphrased", not "mixed"
should_mask                boolean   exclude from highlighting/scoring
masking_reason             string    e.g. references, table, code_block
special_highlight_type     string|null
interpretability_value / _normalized_value / _designation / _alpha
                                     ← "internal use or whitelisted customers only" (Advanced Scan)
```

Real example response (from the docs' "Mixed Example"), abridged:
```json
{
  "meta": {"pagesCount": 1},
  "version": "2025-11-28-base",
  "neatVersion": "3.14b",
  "scanId": "9e5b6cbb-f30d-41f3-826d-fafa2d370056",
  "documents": [{
    "paragraphs": [
      {"start_sentence_index": 0, "num_sentences": 5, "completely_generated_prob": 0.887},
      {"start_sentence_index": 5, "num_sentences": 6, "completely_generated_prob": 1.47e-05}],
    "predicted_class": "mixed",
    "confidence_category": "high",
    "class_probabilities": {"human": 0, "ai": 5.15e-05, "mixed": 0.99994},
    "sentences": [{
      "generated_prob": 0.99971,
      "sentence": "Climate change refers to the long-term shift in global weather patterns...",
      "perplexity": 0,
      "class_probabilities": {"human": 0.000288, "ai": 0.99970, "paraphrased": 3.05e-06},
      "highlight_sentence_for_ai": true
    }],
    "subclass": {"mixed": {"predicted_class": "concatenated", "confidence_category": "high",
                            "class_probabilities": {"concatenated": 0.9999999998, "polished": 1.72e-10}}},
    "document_classification": "MIXED",
    "result_message": "Our detector is highly confident that the text may include parts written by AI.",
    "language": "en"
  }]
}
```

### `POST /v2/predict/files`
- `multipart/form-data`, field `files` (array). **Max 50 files simultaneously, 15 MB combined**, each doc truncated to 50,000 chars.
- Optional `modelVersion`, `apiVersion`. (`version` is deprecated — removed after 2024-11-28.)
- Returns the same `DocumentPredictions` shape with one entry per file in `documents`.

### Errors
`400` validation · `404` profile/plan/API key not found or key expired · `429` word limit **or** hourly rate limit — *"Sometimes, when this error occurs, it means that you did not add the API key to the header in the proper format, making you get the rate-limit of a free user"* · `500` upstream failure. Error body: `{"error": "..."}`.

### Rate limits & quotas
- **30,000 requests/hour on all subscription plans.** Higher → api@gptzero.me. ([support article](https://support.gptzero.me/articles/7371584464-what-is-the-rate-limit))
- Separately metered by **words/month**. `GET /v3/usage-stats` returns `{words_left, words_used, cycle_start, cycle_end, plan}`. On the *API (Enterprise)* plan `words_left` is `null` (metered billing).
- Example 429 body from the docs: `"Monthy limit of 1 million words has been reached. Consider upgrading your plan to Pro"` (sic).

### Batch support
**There is no async batch endpoint.** "Batch" = `/v2/predict/files` with up to 50 files per call. For a corpus scan you fan out concurrent `/v2/predict/text` calls under the 30k/hr ceiling.

---

## A2. The hallucination detection API — it's called **Bibliography Scan**

This is the piece the prize text refers to and it is **not documented anywhere on the marketing site**. I only found it in the docs backend. The consumer-facing product names are "[Hallucination Detector](https://gptzero.me/hallucination-detector)" / "[Source Finder](https://gptzero.me/news/sources-fact-checker/)" / "Hallucination Check"; the **API name is `bibliography-scan`**.

### `POST /v2/bibliography-scan/text`
> *"Runs Bibliography Scan on one document and returns detected citations, claims, and sources."*

Request — dead simple, just text:
```json
{ "document": "Perhaps the most cited argument against gun control is the second amendment [1].  Works Cited [1] Carroll, Lauren. \"Obama: US Spends More On Military Than Next 8 Nations Combined.\" PolitiFact. N.p., 2015. Web." }
```
Header: `x-api-key`. **No `sources` input parameter** — it does its own retrieval.

### Response — three parallel arrays

```
id           string    scan id
version      integer   response format version
inputText    string
bibliographic_citations[]
claims[]
sources[]
```

**`bibliographic_citations[]`** — one per detected citation:
```
id                integer
text              string      raw citation text
indices           {start, end}   char offsets into inputText
citation_type     string|null
citation_object   object|null    parsed metadata
citation_exists                  ← THE HALLUCINATION VERDICT
   .status        "exist" | "exist_with_issues" | "fake" | "unsure" | "unknown"
   .score         number|null    confidence
   .justification string|null    why
   .hallucination_label       string|null
   .hallucination_explanation string|null
ai_scan           object|null    ← AI detection run ON the citation text itself
   .predicted_class  "human"|"ai"|"mixed"
   .score            number
claim_reference   {has_reference: boolean}
```

**`claims[]`** — one per factual claim:
```
id            integer
text          string
indices       {start, end}
claim_type    "cited" | "uncited"
bibliographic_citation_ids[]    links to citations
agree_with_citation
   .stance       "support" | "contradict" | "partial support" | "partial contradict"
                 | "mixed" | "strongly support" | "slightly agree" | "neutral"
                 | "slightly disagree" | "strongly contradict" | "stance_unknown" | null
   .justification string|null
is_cited_in_bibliography
   .is_cited      boolean
   .check_worthy  boolean|null    ← is this claim even worth citing?
   .score         number
   .justification string|null
```

**`sources[]`** — retrieved evidence:
```
id, claim_id, citation_id
url, title, authors[], date, content, relevant_chunk
stance         string|null        this source's stance toward the claim
justification  string|null
sourcerer_name string               which retrieval system found it
citation_object  {title, authors[], publisher, publication_date, url, doi, access_date}
citations        {apa, mla, chicago, ieee, bibtex}      ← pre-formatted, free
citation_match
   .citation_match / .citation_does_not_match  boolean
   .confidence, .score, .llm_match_score
   .title_match_score, .authors_match_score, .publisher_match_score,
    .publication_date_match_score, .url_match_score, .doi_match_score
   .hallucination_label, .hallucination_explanation, .justification
```

`POST /v2/bibliography-scan/files` — same, `multipart/form-data` field `files`, returns an **array** of the above, one per file.

### Is it gated?
- **The spec documents no allow-list for bibliography-scan** — only `x-api-key` and a `500` error response. Contrast with `/v3/ai/patterns/stream`, which *explicitly* documents a `403` "Your API key is not allow-listed for AI Patterns. Contact api@gptzero.me to request access."
- **Inference (flag this):** bibliography-scan is *probably* available to any valid API key, but its response schema is unusually sparse on error codes (only 200/500), which hints it's newer and less hardened. **Test it in the first hour and have a fallback.** If it 403s, email api@gptzero.me / hit the GPTZero booth immediately — they're a sponsor, they'll unlock it.
- Behind it: a 220M-article corpus (Semantic Scholar + real-time news + web search), per their [Source Finder post](https://gptzero.me/news/sources-fact-checker/). Reported accuracy from their [technical report](https://gptzero.me/news/how-does-gptzeros-hallucination-check-detector-work-a-technical-report/): **96.1% precision / 94.2% recall on fake citations; 0.5% false-positive rate** (2 of 419 verified citations misflagged). Pipeline = citation detection/parsing → triage (formally verifiable / requires reasoning / non-checkable) → sourcing → 6-component matching (title, authors, publisher, date, URL, DOI) → taxonomy classification.
- **They explicitly do not fact-check.** They only report whether online evidence supports/contradicts/debates a claim. Frame your UI the same way or you'll get dinged.

### Bonus endpoint nobody knows about: `POST /v3/ai/patterns/stream`
> *"Identifies recurring stylistic and rhetorical AI writing patterns ('tropes') in a document and explains each match in plain language."*

- **Server-Sent Events** (`text/event-stream`), `data: <json>\n\n` per event. One event per matching sentence; non-matching sentences are not emitted.
- Request: `{"documents": [{"inputText": "..."}]}` — **exactly one document**; `maxLength 150000` chars, **rejected with 400 above that, not truncated**. Alternatively `{"document_id": "<uuid>"}` from a prior Advanced Scan.
- Each `AiPatternStreamEvent`: `document_index`, `sentence_index`, `sentence`, `interpretability_designation`, `patterns[]` where each `AiPatternHit` = `{domain_id, pattern_id (e.g. "rule_of_three"), pattern_name, display_name, category (e.g. "Language and grammar"), description, display_description, explanation (plain-language, why THIS sentence matched), relevance, k_times (how much more often this pattern occurs in AI text)}`.
- **`403` if your key isn't allow-listed. Ask GPTZero at the booth on Saturday morning.**
- This is the single most demo-friendly GPTZero endpoint for your project and almost nobody at the hackathon will find it. `k_times` + `explanation` gives you free, human-readable "your pitch sounds like AI slop because ___" copy.

---

## A3. Hack the North 2026-specific GPTZero resources

**What I could NOT find (flagging explicitly):**
- ❌ No GPTZero hackathon guide repo, Notion page, or starter repo. The GPTZero GitHub org (`github.com/GPTZero`) has only 3 repos: `gptzero-js` (last push **2023-03-05**), plus forks of FastChat and argo-cd. No HTN repo, unlike Baseten.
- ❌ No documented free-credits/promo-code mechanism for hackers. Contrast Baseten, which publishes the exact redemption flow.
- ❌ **No past "Best Use of GPTZero" winner anywhere.** GPTZero was **not a sponsor at Hack the North 2025** (verified against the 2025 Devpost sponsor list — Amazon, Cerebras, Cohere, Databricks, Shopify, Solana etc., no GPTZero, no Baseten). No Devpost prize gallery, MLH page, or blog post names a GPTZero prize winner at any event.
- **Implication: this is very likely GPTZero's first-ever "Best Use of GPTZero" prize.** There is no precedent for what wins. Judges will fall back to the prize text verbatim — so structure your submission around its two bullets, in its own words.

**What exists:** the prize text on [Devpost](https://hackthenorth2026.devpost.com/), the API key page (app.gptzero.me/app/api), [developer page](https://gptzero.me/developers), [support center](https://support.gptzero.me), and `api@gptzero.me` (their documented channel for allow-listing and rate-limit increases). Assume a Discord/Slack channel exists analogous to Baseten's `#spons-baseten-2026` — I could not verify its name.

---

## A4. SDKs and gotchas

**SDKs:**
- `gptzero-js` — *official* (GPTZero org), npm `gptzero`. **Effectively abandoned: last commit 2023-03-05.** Its README still documents the *old* response shape (`documents[].completely_generated_prob` / `sentences` / `paragraphs`, no `class_probabilities`, no `subclass`). API is: `createClient(key)`, `.predictText(str)`, `.predictFiles([paths])`. **Recommendation: skip it, call the REST API directly.**
- PyPI `gptzero` — community async wrapper by Haste171, **not maintained by GPTZero**.
- `gptzeror` — CRAN R package by Christopher Kenny.
- **Best reference implementations to copy:** [`liamdugan/raid/detectors/models/gptzero/gptzero.py`](https://github.com/liamdugan/raid) (clean, with 429 backoff) and [`markrussinovich/refchecker/src/refchecker/ai_detection/api_backend.py`](https://github.com/markrussinovich/refchecker) (defensive: falls back from `completely_generated_prob` → `class_probabilities.ai`, filters `highlight_sentence_for_ai` spans by word count).

**Gotchas — confirmed:**

1. **Minimum length: 250 characters (~50 words).** Confirmed in GPTZero's own [benchmarking article](https://gptzero.me/news/gptzero-ai-detection-benchmarking-the-industry-standard-in-accuracy-transparency-and-fairness/): *"minimum length requirement of 250 characters (approximately 50 words) specified on the GPTZero dashboard."* Third-party benchmarks put <100 words at ~78% accuracy vs ~96% at >500 words. **Your hard constraint: a one-line startup idea will NOT produce a trustworthy score. Gate your UI at 250 chars and say why.**
2. **Latency ~0.4s for a 700-word document** (per [gptzero.me/machine-learning](https://gptzero.me/machine-learning)). Fast enough for interactive use; a 2,000-doc corpus scan at ~0.4s serial = ~13 min, so parallelize ~20-way.
3. **`completely_generated_prob` and `average_generated_prob` are deprecated** and labeled internal-use-only, even though every tutorial uses them. **Use `class_probabilities` + `predicted_class` + `confidence_category`.** Judges from GPTZero will notice.
4. **Never display raw probabilities to users** — the spec tells you to show `result_message` / `confidence_category`, not `confidence_score`.
5. **Word-metered billing, not request-metered.** A corpus scan burns your quota by words. Budget it: the credits are the prize, not the entry fee — on the *Professional* plan it's ~500k words/month. Scanning 2,000 Devpost blurbs × ~150 words ≈ 300k words. **That is most of a month's quota in one afternoon.** Check `GET /v3/usage-stats` before and after; consider sampling.
6. **Pricing** (⚠️ *third-party sources, not verified on gptzero.me — their pricing page is JS-rendered*): API access bundled with the **Professional** plan (~$24.99/mo annual / $45.99 monthly, ~500k words/mo); pay-as-you-go reseller listings quote ~$0.39 per 1,000 words. Treat as indicative only.
7. **Sentence-level `class_probabilities` uses key `paraphrased`, not `mixed`** — different from document level. Easy crash.
8. **Respect `should_mask` / `masking_reason` / `excluded_spans`** — code blocks, tables and reference lists should be excluded from your score or you'll get garbage on technical pitches.

---

## A5. My assessment — how to use BOTH APIs "significantly"

Critiquing your four, then two additions. I'd build **#1 + #2 + #4**, and treat #3 as a stretch.

### (i) Investigative corpus scan — ✅ **strongest play, do this**
Scan Devpost hackathon project descriptions by year (2019→2026) and plot the AI-generated share over time. **Why it wins:** it's a structurally exact replay of the NeurIPS/ICLR investigations that got GPTZero into Fortune — same shape (unexpected corpus + headline number + shareable artifact), applied to a corpus they'd never think of, **at the very hackathon they're judging**. The reflexivity ("how much hackathon idea-space is now AI slop — including, possibly, this hackathon") is the wow factor.

**Critique / make it survive scrutiny:**
- **Confound: the 2019 baseline isn't a baseline.** Writing style, Devpost's own template prompts, and description length all shifted independently of AI. Mitigate by holding **length constant** (only scan blurbs ≥250 chars, report median length per year) and reporting `confidence_category == "high"` counts separately — that's the <1% error rate slice and it's the only number you should headline.
- **Use `subclass`.** The `mixed → polished` vs `mixed → concatenated` and `ai → pure_ai` vs `ai_paraphrased` split is a *far* more interesting finding than a single percentage. "AI-*polished* submissions rose 6× since 2023 while *pure AI* stayed flat" is a real result and nobody else will have it.
- **Scraping budget.** Devpost galleries are paginated HTML; don't spend 6 hours on the scraper. **Get 200–400 projects/year, not thousands** — it's enough for a trend and it protects your word quota.
- Product Hunt / YC blurbs are a good second corpus but **too short** (often <250 chars). Devpost descriptions are the right length. Prefer Devpost.

### (ii) Per-sentence AI-probability on the user's own pitch as a "genericness" signal — ✅ **do this, but be honest about the leap**
Feed `sentences[].generated_prob` + `highlight_sentence_for_ai` back as "these sentences read as boilerplate."

**Critique — this is the claim most likely to get challenged by a GPTZero judge, because they know their own detector's semantics:** AI-probability is *not* unoriginality. A human can write a genuinely novel idea in clichéd prose, and an AI can phrase a novel idea. **Do not conflate them in your scoring — and say so on stage.** Frame it precisely as: *"how much does your phrasing pattern-match the LLM prior"* — a **presentation** signal, shown in its own channel, never silently summed into an originality number. Weight it as a separate axis in your UI.

**Upgrade: use `/v3/ai/patterns/stream` here instead of raw probabilities.** It gives you `pattern_name` ("rule_of_three"), a plain-language `explanation` of why *that* sentence matched, and `k_times`. That turns a scary meaningless "87% AI" into *actionable* feedback — "this sentence uses the rule of three, 4.2× more common in AI writing" — which is exactly the "feedback on how to make it more original" your product promises. Request allow-listing at the booth Saturday morning.

### (iii) Filter retrieved web evidence by AI-slop probability — ⚠️ **great idea, wrong tool, fix it**
The idea (don't let SEO-spam "top 10 startup ideas" listicles count as prior art) is genuinely good and is *precisely* GPTZero's "age of rampant AI slop" framing.

**Critique:** scraped web pages are the **worst case** for this API — nav chrome, boilerplate, cookie text, mixed authorship, and highly variable length. Cost is real too: 20 pages × 800 words = 16k words **per user query**, which will torch your quota in a live demo. **Fixes:** extract main content only (Readability-style), truncate each page to a fixed ~1,500-char window, **cache aggressively by URL**, and only run detection on the top-k after reranking, not all retrieved pages. Use `document_classification == "AI_ONLY"` + `confidence_category == "high"` as the discard rule — nothing softer, or you'll throw away legitimate sources.

### (iv) Hallucination-check your own LLM output — ✅ **do this; it's the second prize bullet, literally**
Run `/v2/bibliography-scan/text` over your generated originality report so every "X already exists" claim is verified before display.

**Critique:** bibliography-scan is tuned for **academic citations**, and its strongest signal (`citation_exists.status`) needs a formatted citation to parse. A bare LLM sentence like "Notion already does this" has no citation to check. **So structure your report generator to emit real citations** — make your retrieval step attach `[1] Author. "Title." Site. Date. URL.` to every prior-art claim, then scan it. Now `citation_exists.status == "fake"` catches your own model inventing a competitor, and `claims[].agree_with_citation.stance` tells you whether the source you cited actually *supports* "this already exists" or in fact contradicts it. **That stance field is the killer feature**: it catches the failure mode where your tool cites a real page that doesn't actually say what you claimed.

Also use `claims[].is_cited_in_bibliography.check_worthy` to auto-flag uncited assertions, and `bibliographic_citations[].ai_scan` to flag when your *cited source itself* is AI-generated — GPTZero calls this "second-hand hallucinations" and it's their own marketing language. Quote it back to them.

### (v) My addition — the "slop-adjusted prior art" score
Combine (iii) + (iv) into one defensible number: an idea is *original* to the degree that prior art is **scarce, human-written, and genuinely supportive of the "this exists" claim**. Concretely: retrieve → drop `AI_ONLY`+`high` sources → bibliography-scan the claim/source pairs → **count only claims whose stance is `support`/`strongly support` against a human-written source**. That's a single metric that structurally requires *both* APIs and can't be faked with one.

### (vi) My addition — close the loop on the corpus
Take the winners from (i) and show **where the user's pitch sits in the distribution you built**: "your pitch is more AI-patterned than 78% of 2026 Devpost submissions, and its core claim has 14 pieces of human-written prior art." That's the move that turns the investigation from a side-quest into the product's backbone — one artifact serving both prize bullets. Judges reward a project where the investigation *is* the product, not a bolted-on stunt.

---

# B. Baseten — "Best Use of Baseten"

## B1. The repo: `github.com/basetenlabs/Hack-the-North-2026`

**Fetched in full** (single file, `README.md`, 8,743 bytes, last pushed **2026-09-09**). Near-verbatim contents:

**Three ways to use Baseten at this event:**
1. Hosted open-source models — "DeepSeek, Kimi, GLM, Inkling, GPT-OSS, and Nemotron — through a single OpenAI-compatible API"
2. **"H100 GPU workstations to train or fine-tune your own models"**
3. **Baseten Switch** — route Claude Code / Codex CLI / Pi through Baseten-hosted models

**Credits (exact steps):**
> "Every hacker can claim free Baseten credits with promo code shared in the event Slack! Check `#spons-baseten-2026` for more details!"
1. Create account at app.baseten.co → 2. **Billing and usage** in left sidebar → 3. **Redeem promo credits** → 4. enter code.
> ⚠️ "Credits apply to the **workspace, not each individual member**. If your team shares one Baseten workspace, the person who created that workspace must redeem the code. You only need to redeem it once for the whole team."

**Quickstart (verbatim):**
```bash
export BASETEN_API_KEY="your-api-key"
pip install openai
```
```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["BASETEN_API_KEY"],
    base_url="https://inference.baseten.co/v1",
)

response = client.chat.completions.create(
    model="zai-org/GLM-5.3",
    messages=[{"role": "user", "content": "Pitch me a hackathon project."}],
)
print(response.choices[0].message.content)
```
Live catalog:
```bash
curl https://inference.baseten.co/v1/models -H "Authorization: Bearer $BASETEN_API_KEY"
```
API keys: https://app.baseten.co/settings/api_keys

**Rate limits:** on `429`, "submit the event rate-limit form shared in the attendee channel." Advice given: exponential backoff, run independent requests concurrently but under the workspace limit, and **"Keep shared instructions and examples at the start of prompts so automatic prompt caching can reuse them."**

**Error table (verbatim):** `400` invalid request (check model slug/body) · `401` invalid/missing key (must be bearer token) · `402` payment required — redeem event credits · `404` model not found · `429` rate limit · `500` retry.

**Training section:** "We are offering H100 workstations for hackers who want to train or fine-tune their own models. **Visit the Baseten booth first so the team can enable training access** and help you choose an appropriate setup." Workflow: install CLI + sign in → define image/GPU/commands/secrets/cache/checkpoints → submit job, follow logs → **"Save outputs under the Baseten checkpoint directory so they persist after the job stops"** → deploy a completed checkpoint.

**Baseten Switch (macOS 13+, Apple Silicon or Intel, beta, not notarized):**
```bash
brew install basetenlabs/baseten/baseten-switch
baseten-switch setup && baseten-switch up --install
baseten-switch claude on && baseten-switch doctor --probe
# Codex is opt-in:
baseten-switch codex on && baseten-switch codex route zai-org/GLM-5.2 && codex --profile baseten
```
> **"If you redeemed hackathon inference credits in that workspace, you can use those credits for coding-agent traffic through Baseten Switch too."**

**Getting help:** docs.baseten.co (has a docs assistant), `#spons-baseten-2026`, the booth. *"Bring the request ID and full error response when asking for API help. For training issues, bring the training job ID and the relevant log lines."*

**Judging hints: there are none in the repo.** No criteria, no example projects, no "we're looking for X." The only signal is the prize text ("creative way to incorporate it") + the README's structure, which gives **equal billing to inference and training** and calls out training as needing a booth visit. *Inference: a project that uses only the LLM endpoint uses ⅓ of what they advertised. Touching training is differentiation.*

> ⚠️ **Unverified / likely wrong:** one search summary claimed the "Baseten track challenges teams to build a system that leverages LLMs to operate on real-world, messy data and take meaningful actions... agents that handle unstructured information, incomplete datasets, conflicting sources." **This does not appear in the repo or on the HTN Devpost page** and looks conflated with a different sponsor/event. Do not design to it.

---

## B2. Baseten's 2026 product surface

### Model APIs — ✅ base URL confirmed
- **`https://inference.baseten.co/v1`**, OpenAI-compatible, `Authorization: Bearer $BASETEN_API_KEY`.
- Also **Anthropic Messages API compatible** at `https://inference.baseten.co` (**no `/v1` suffix**), with a header override to use `Authorization` instead of `x-api-key`.
- Full catalog with slugs ([docs](https://docs.baseten.co/inference/model-apis/overview)):

| Model | Slug | Context | Max out | Reasoning | Vision |
|---|---|---|---|---|---|
| DeepSeek V4 Pro | `deepseek-ai/DeepSeek-V4-Pro` | 1048k | 262k | default | – |
| DeepSeek V4 Pro 0813 | `deepseek-ai/DeepSeek-V4-Pro-0813` | 1048k | 262k | default | – |
| DeepSeek V4 Flash 0731 | `deepseek-ai/DeepSeek-V4-Flash-0731` | 1048k | 384k | default | – |
| DeepSeek V4.1 Flash | `deepseek-ai/DeepSeek-V4.1-Flash` | 1048k | 32k | default | ✓ |
| GLM 4.7 | `zai-org/GLM-4.7` | 200k | 200k | opt-in | – |
| GLM 5.2 / 5.2 Fast | `zai-org/GLM-5.2`, `-Fast` | 1048k | 262k | opt-in | ✓ |
| GLM 5.3 / Fast / Flash | `zai-org/GLM-5.3`, `-Fast`, `-Flash` | 1048k | 262k | default | ✓ |
| Inkling / Inkling Small | `thinkingmachines/inkling`, `-small` | 1048k | 32k | default | ✓ (+audio) |
| Kimi K2.6 | `moonshotai/Kimi-K2.6` | 262k | 262k | opt-in | ✓ |
| Kimi K2.7 Code | `moonshotai/Kimi-K2.7-Code` | 262k | 262k | opt-in | ✓ |
| Kimi K3 | `moonshotai/Kimi-K3` | 1048k | 262k | default | ✓ |
| Nemotron Ultra | `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B` | 202k | 202k | opt-in | – |
| GPT-OSS 120B | `openai/gpt-oss-120b` | 128k | 128k | default | – |

- **All models support tool calling, structured outputs, and JSON mode.** (No Qwen or Llama in the shared Model APIs catalog as of now — those are dedicated-deployment / model-library only. Your brief assumed Qwen/Llama were on the shared endpoint; they're not.)

### ✅ **logprobs ARE exposed** — this answers your question (v)
From the [Chat Completions reference](https://docs.baseten.co/reference/inference-api/chat-completions):
- `logprobs` (boolean) and `top_logprobs` (**0–20**, requires `logprobs: true`). **"Log probability support varies by model"** — test your chosen slug early.
- Response carries `choices[].logprobs.content[] = {token, logprob, bytes, top_logprobs[]}`.
- Also supported and useful to you: `response_format` (`text` / `json_object` / **`json_schema`** / `grammar` / `structural_tag`), `seed`, `tools`, `tool_choice`, `parallel_tool_calls`, `min_p`, `top_k`, `repetition_penalty`, `echo`, `stream_options.include_usage`, `documents` (RAG), `chat_template`.
- ⚠️ `n` and `best_of` — **only 1 supported.** So your "jury" must be N separate requests, not `n>1`.

### Dedicated deployments (Truss)
`truss push` / `truss push --publish` / `truss watch` (live reload). Model library models ship as editable Truss packages. Chains: `truss chains push`. Repo: [basetenlabs/truss](https://github.com/basetenlabs/truss).

### Model library — embeddings & rerankers (BEI)
[Baseten Embeddings Inference](https://docs.baseten.co/examples/bei) — "2x higher throughput and 10% lower latency," up to ~1,400 embeddings/sec/client, fp8 PTQ + ahead-of-time compilation.

Available in the [library](https://www.baseten.co/library/tag/embedding/): **Qwen3 Embedding 0.6B (L4) / 4B / 8B (H100 MIG 40GB)**, **Qwen3 Reranker 0.6B (L4) / 4B / 8B**, EmbeddingGemma, Nomic Embed Code, BGE Embedding ICL, Mixedbread Embed Large V1 (L4), NVIDIA Nemotron 3 Embed 1B/8B, ZeroEntropy Zerank-1-small / Zerank-2 / Zembed-1, Voyage 4 Large.

Truss config for a BEI deploy:
```yaml
model_name: BEI-Model-Name
resources:
  accelerator: H100_40GB
  use_gpu: true
trt_llm:
  build:
    base_model: encoder
    checkpoint_repository: {repo: "model/repo", revision: main, source: HF}
    quantization_type: fp8
```
```bash
uvx truss push --promote
```

> ⚠️ **Critical constraint:** **embeddings and rerankers are NOT on the shared `inference.baseten.co/v1` endpoint.** They require a *dedicated deployment* with its own model URL (`https://model-<id>.api.baseten.co/environments/production/sync`). Embeddings are OpenAI-compatible at `/v1/embeddings`; rerankers/classifiers use `/sync/predict`. This is a real time cost in a 36h build — budget for it.

Python client ([`baseten-performance-client`](https://pypi.org/project/baseten-performance-client/)), benchmarked >1,200 req/s/client, 1.08×–12.74× faster than the OpenAI client:
```python
from baseten_performance_client import PerformanceClient
client = PerformanceClient(
    base_url="https://model-yqv4yjjq.api.baseten.co/environments/production/sync",
    api_key=api_key)
client.embed(input=["Hello world", "Example text"], model="my_model")
client.rerank(query="What is the best framework?", texts=["Doc 1", "Doc 2"], model="rerank-model")
client.classify(inputs=["This is great!", "Not good."], model="classification-model")
await client.async_embed(input=texts, model="my_model")
```

### Chains
[Docs](https://docs.baseten.co/development/chain/overview). Chainlets = Python classes inheriting `ChainletBase`, composed via `chains.depends()`, **each with its own hardware and dependencies** (separating GPU and CPU workloads), one marked `@chains.mark_entrypoint`. Parallelism is plain `asyncio.gather`:
```python
@chains.mark_entrypoint
class HelloAll(chains.ChainletBase):
    def __init__(self, say_hello_chainlet=chains.depends(SayHello)):
        self._say_hello = say_hello_chainlet
    async def run_remote(self, names: list[str]) -> str:
        tasks = [asyncio.create_task(self._say_hello.run_remote(n)) for n in names]
        return "\n".join(await asyncio.gather(*tasks))
```

### Training
[Getting started](https://docs.baseten.co/training/getting-started). The docs' own worked example is **a Qwen3-4B LoRA fine-tune on `pirate-ultrachat-10k` using TRL, with `max_steps=50`, `save_steps=25`** — i.e. **two checkpoints, minutes of H100 time.** That is emphatically hackathon-feasible.
```bash
brew tap basetenlabs/baseten && brew install baseten && baseten auth login
baseten train push --config config.py
baseten train job logs --job-id <job_id> --tail
baseten train checkpoint deploy
```
Config via `truss_train` objects: `TrainingProject` → `TrainingJob(Image, Compute, Runtime)`; `Compute(gpu="H100")`. Needs `uv` on PATH and an HF token stored as secret `hf_access_token`. **Save to `$BT_CHECKPOINT_DIR` or your weights vanish.** Deployed checkpoints serve base weights + your LoRA adapter via vLLM, callable through the OpenAI chat format. Billed per GPU-minute; `DELETE /v1/models/{model_id}` when done (checkpoints survive). Examples: [basetenlabs/ml-cookbook](https://github.com/basetenlabs/ml-cookbook).

---

## B3. Deploy speed, cold start, GPUs, cost

- **Cold start: 5–10s for most models** (30–60× faster than their old ~5min); SDXL on A100 reliably ~9s; largest models "a handful of minutes." Via the [Baseten Delivery Network](https://www.baseten.co/blog/baseten-delivery-network-fast-cold-starts-big-models/) + cluster/node-level weight caching.
- **Scale to zero: enabled for all model-library models.** Default **scale-down delay 900s (15 min)**. ([autoscaling docs](https://docs.baseten.co/deployment/autoscaling))
- **GPU pricing** ([baseten.co/pricing](https://www.baseten.co/pricing/)) — billed per minute:

| GPU | $/min | $/hr |
|---|---|---|
| T4 16GiB | 0.01052 | **0.63** |
| L4 24GiB | 0.01414 | **0.85** |
| A10G 24GiB | 0.02012 | **1.21** |
| H100 MIG 40GiB | 0.0625 | **3.75** |
| A100 80GiB | 0.06667 | **4.00** |
| H100 80GiB | 0.10833 | **6.50** |
| B200 180GiB | 0.16633 | **9.98** |

- **Model API token prices:** GLM-5.3 $1.40/$4.40 per 1M in/out · GLM-5.3-Flash $0.15/$0.50 · DeepSeek V4.1 Flash $0.30/$1.20 · DeepSeek-V4-Flash-0731 $0.13/$0.26 · Kimi K3 $3.00/$15.00. **Cached prefix tokens billed at a discount.**
- **Rate limits by tier** ([pricing-and-limits](https://docs.baseten.co/inference/model-apis/pricing-and-limits)): Basic unverified 15 RPM / 100k TPM · Basic **verified 120 RPM / 500k TPM** · Pro 120 RPM / 1M TPM. Replenish continuously. **Verify your account immediately — 15 RPM will kill a jury architecture.**
- **`x-session-affinity` header** (UUID/hashed ID) routes related requests to the same replica for better KV-cache hits. Free latency + cost win for multi-turn agents.
- **Credits math:** $30 free on signup + event promo code + $100/$200 if you win. **Your real budget is the promo code.** An L4 running a Qwen3-0.6B embedder for 30h ≈ **$25**. An H100 for a 30-min LoRA ≈ **$3.25**. Both are comfortably affordable; an H100 left running for 36h is **$234** and will not be.

---

## B4. What counts as "creative" — my evaluation of your five

Bluntly: **calling `chat.completions.create` against GLM-5.3 is what 80% of the Baseten submissions will do.** The README gives inference and training equal billing and tells you to visit the booth for training access — that's the differentiator hiding in plain sight. **Do (v) + (i), and do (ii) if and only if you're ahead of schedule.**

### (v) Perplexity / surprisal as an originality signal — ⭐ **highest creativity-per-hour. Do this first.**
**Feasible: yes, ~2 hours.** `logprobs: true, top_logprobs: 5` on a shared Model API model, `echo: true` to score the prompt tokens, then mean negative log-likelihood over the idea text = surprisal. Low surprisal = the phrasing is exactly what an LLM expects = generic.

**Why it's creative in Baseten's eyes:** it uses the inference endpoint as a **measurement instrument**, not a chatbot. That's an inference-engineering mindset, and the prize is from a company whose founders wrote a book called *Inference Engineering*. It is also the only one of your five that produces a number no competitor's project will have.

**How:** pick a *small, cheap, non-reasoning* model for stable logprobs — `openai/gpt-oss-120b` or `zai-org/GLM-5.3-Flash`. **Verify logprobs actually return for your slug in the first 20 minutes** ("support varies by model"). Normalize by token count, and **always report surprisal relative to a reference corpus** (score 200 Devpost blurbs once, cache the distribution, report the user's percentile) — a raw NLL number is meaningless to a judge. Pair it with GPTZero's `generated_prob` for a two-detector agreement story: *"two independent signals, one from a purpose-built detector, one from raw LM surprisal."*

**Risk:** if `echo` + `logprobs` on prompt tokens isn't supported, fall back to scoring a *continuation* — feed the first half of the idea, measure logprobs of the model's own generation vs. the user's actual second half. Slightly weaker but always available.

### (i) Embedding + cross-encoder reranker for idea similarity — ⭐ **do this; it's the product's spine**
**Feasible: yes, ~3–4 hours** including a dedicated deploy. Deploy **Qwen3 Embedding 0.6B on L4** (~$0.85/hr) and **Qwen3 Reranker 0.6B on L4** from the model library, hit them with `baseten-performance-client`.

**Why it's creative:** the bi-encoder → cross-encoder two-stage retrieval pattern is genuinely correct engineering for "is this idea novel," not decoration — and it uses **BEI**, a product Baseten built and blogged about extensively. **Critique:** don't deploy the 8B variants; 0.6B on L4 is ~8× cheaper, deploys faster, and the quality gap is irrelevant on short idea text. Embed your Devpost corpus *once* offline, store vectors locally (in-memory numpy is fine at this scale — do **not** spend 4 hours on a vector DB).

### (iii) A Chain composing embed → retrieve → rerank → judge — ⚠️ **the right architecture, the wrong 36-hour bet**
Chains is genuinely the idiomatic Baseten answer for a multi-model pipeline, and "each Chainlet gets its own hardware" maps perfectly onto embedder-on-L4 + reranker-on-L4 + judge-on-shared-API.

**Critique:** Chains adds a deployment abstraction, its own local dev loop, and a new failure surface on top of two dedicated deploys you're already fighting. **The demo looks identical to a Python function that calls three endpoints.** Unless you finish (i) and (v) by Saturday evening, orchestrate in your app and just *say* "this maps onto Chains; here's the chainlet decomposition" on a slide. If you do have time, it's a legitimate upgrade and a strong architecture-diagram slide.

### (ii) Fine-tune a small model on Devpost winners vs non-winners — ⚠️ **most impressive, most likely to sink you**
**Feasible in principle** — the docs' own example is a Qwen3-4B LoRA at `max_steps=50`, and H100 workstations are offered at the booth. Cost is trivial (~$3–7).

**Critique — three ways this fails:** (1) **Booth-gated.** Training access requires a Baseten person to enable it; if you start Sunday morning you're dead. **Go Saturday morning, first thing.** (2) **The label is bad.** "Winner vs non-winner" is dominated by demo quality, team, and luck — not idea originality. You'd be training a classifier on noise and then claiming it measures novelty; a sharp judge will take that apart. (3) **Data collection is the real cost**, not training — you need thousands of labeled blurbs before you can train on anything.

**If you do it, reframe the label to something the text actually determines:** train on **"generic vs distinctive"** using *weak supervision you already have* — label by your own surprisal percentile from (v) and GPTZero's `subclass`, then distill into a small fast classifier. That's defensible ("we distilled an expensive multi-API signal into a single cheap model") and it's a real inference-engineering story: *cost reduction through distillation*, which is exactly what Baseten sells. **Timebox to 3 hours, have the booth enable access Saturday AM, and be willing to drop it.**

### (iv) Multi-model "jury" for originality — ✅ **cheap, demos well, but it is not the differentiator**
**Feasible: 1 hour.** `asyncio.gather` over GLM-5.3, DeepSeek-V4.1-Flash, Kimi-K3, GPT-OSS-120B with `response_format: json_schema` for structured votes, then aggregate + report variance.

**Critique:** this is the *most commonly built* "creative multi-model" pattern at hackathons and Baseten will see several. **It only becomes interesting if you show the disagreement is informative** — e.g. "high inter-model variance on originality correlates with genuinely ambiguous ideas," plotted. Also: **`n` is capped at 1**, so this is N parallel requests; watch your RPM (15 unverified / 120 verified). Use it as a *supporting* signal and a nice visualization, not the headline.

**My recommended Baseten stack:** surprisal-via-logprobs (v) as the headline creative use + BEI embedder/reranker (i) as the retrieval spine + jury (iv) as garnish, with a Chains decomposition slide and a distillation fine-tune only if you're ahead.

---

## B5. Past "Best Use of Baseten" winners

No prize with that exact name is findable on Devpost. Closest evidence of what Baseten rewards:

- **SPC "Llamathon"** ([Baseten blog](https://www.baseten.co/blog/spc-hackathon-winners-build-with-llama-3-1-on-baseten/)):
  - **TestNinja** — won *Most Interesting Technical Achievement*. LLM-powered test generation from GitHub PRs. **Deployed Llama 3.1 405B on Baseten H100s**, and — the part Baseten highlighted — used **deterministic Python dependency-graph analysis to extract code context**, then fed that to the LLM. *Pattern: deterministic engineering around the model, not just prompting.* Quote: "Baseten streamlined the integration of Llama 3.1 405b into TestNinja, requiring minimal setup and delivering impressively low latency."
  - **VibeCheck** (finalist) — mood-board generator. Notably **benchmarked multiple Llama 3.1 sizes and deliberately chose 8B**, managing all of it with Truss. *Pattern: showing you picked the right-sized model on purpose.*
- **[basetenlabs/HackMIT-2024](https://github.com/basetenlabs/HackMIT-2024)** — their prior hackathon repo: three shared endpoints (Llama 3.1 chat, FLUX.1 image, Whisper 3 transcription) as notebooks, plus Truss and Chains docs. **No prizes or judging criteria stated there either** — consistent with the 2026 repo. Baseten does not publish rubrics.

**Inferred signal from both data points:** Baseten rewards *right-sizing and engineering around the model* — choosing a smaller model deliberately, wrapping it in deterministic logic, measuring latency/cost — over prompt cleverness. That maps directly onto the surprisal + 0.6B-embedder + distillation plan above.

---

# What I verified vs. what I'm inferring

**Verified from primary sources:** every GPTZero endpoint, request body, response field, enum, character limit, and error code in A1/A2 (pulled from GPTZero's live Stoplight docs backend — this is their real spec, not a scrape). The entire Baseten README (fetched raw). Baseten model slugs, context windows, logprobs support, GPU and token pricing, rate-limit tiers, cold-start and scale-to-zero behavior, BEI model list and Truss config, the training quickstart, `baseten-performance-client` API. GPTZero's 30k/hr rate limit, 250-char minimum, 0.4s latency, deprecated fields, the Superhuman acquisition, HTN prize tiers, and the NeurIPS/ICLR investigations.

**Inferred / unverified — flagging explicitly:**
1. **Bibliography-scan entitlement.** Docs show no allow-list, but only 200/500 responses are specified. I'm *inferring* it's open to any valid key. **Test in hour one; escalate to the booth or api@gptzero.me if not.**
2. **AI Patterns (`/v3/ai/patterns/stream`) is confirmed allow-list-gated (403).** You must request access. Whether GPTZero will grant it at a hackathon is unknown.
3. **GPTZero pricing / per-word cost** — their pricing page is JS-rendered; the $24.99–45.99 plan figures and ~$0.39/1k words come from third-party aggregators. Indicative only.
4. **GPTZero multilingual scope** — API docs say French + Spanish; marketing says 20+. I could not reconcile these. Assume the API doc.
5. **No GPTZero hackathon repo, guide, Discord channel name, or credit-redemption flow found.** Unlike Baseten. Likely their first such prize.
6. **No past "Best Use of GPTZero" or "Best Use of Baseten" winner exists anywhere I could find.** Neither sponsored HTN 2025.
7. **Rejected as wrong:** the third-party OpenAPI specs claiming GPTZero has `/batch` and `/reports` endpoints. They don't. Also the claim that Baseten's HTN track is about "messy data agents" — not in the repo or Devpost.
8. **Not independently confirmed:** the `#spons-baseten-2026` Slack channel and the "event rate-limit form" exist per the README but I can't see inside the event Slack.

**Two things worth doing in your first hour:** confirm `logprobs` returns for your chosen Baseten slug, and confirm `/v2/bibliography-scan/text` returns 200 for your GPTZero key. Both are load-bearing for the plan above, and both have clean fallbacks if they fail.