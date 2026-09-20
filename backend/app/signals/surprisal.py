"""Token-level instruments on a base model we host ourselves (docs/design-full.md section 2.8.4).

Shared Model APIs return logprobs for tokens they GENERATE, not for tokens you SUPPLY. Both measurements here
need the latter, so they run against the Truss + vLLM deployment (`/v1/completions` with `echo: true`,
`logprobs: k`), which returns one logprob per prompt token. One L4, scales to zero. Two instruments share it:

AXIS 1, second instrument - retrieval-conditioned surprisal (RCS)
    Read the pitch twice: cold, and again with the k nearest existing projects in front of it.

        delta_t = log p(x_t | x_<t, neighbours) - log p(x_t | x_<t)
        RCS     = mean_t delta_t                                            [nats / token]
                ~ (1/T) * PMI(pitch ; neighbourhood)

    Large RCS: once the model had seen the prior art, the pitch became easy to predict - the neighbourhood
    already contains this idea. Near zero: knowing the prior art did not help, so the idea is not in it.
    Unlike `0.6*max(r) + 0.4*mean(top5 r)` this is a quantity with units and an interpretation, and because
    delta_t is per token it also says WHICH SPANS of the pitch the prior art explains (`sentence_deltas`).

Voice, second opinion - Fast-DetectGPT conditional probability curvature
    Arxiv 2310.05130. Machine text sits high above the model's own expected log-probability at each position;
    human text wanders. One forward pass, no perturbations, no second model:

        d(x) = (sum_t log p(x_t|x_<t) - sum_t mu_t) / sqrt(sum_t sigma_t^2)
        mu_t = E_{v ~ p(.|x_<t)}[log p(v|x_<t)]      sigma_t^2 = Var_{v ~ p(.|x_<t)}[log p(v|x_<t)]

    Not here to beat GPTZero: to disagree with it. One detector can never tell you it is wrong; two can, and
    docs/scoring.md rule 3 says abstain rather than guess. Voice stays out of the headline either way.

Everything above `--- network ---` is pure and unit-tested against synthetic logprobs. With
SURPRISAL_BASE_URL unset every entry point returns None and the callers abstain with a reason.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.config import get_settings

# vLLM returns the top-k alternatives per position; the expectations below are taken over those k, renormalised.
# k=5 (the Truss default) is enough for a stable statistic; k=20 tightens it at no extra GPU cost.
TOP_K = 5
MIN_TOKENS = 24  # below this the per-token means are too noisy to report


# --------------------------------------------------------------------------------------
# Structures
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TokenLogprobs:
    """One `echo: true` reading. The first token has no logprob (nothing conditions it) and is dropped."""

    tokens: list[str]
    logprobs: list[float]
    text_offsets: list[int]
    top_logprobs: list[dict[str, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        n = len(self.tokens)
        if not (len(self.logprobs) == len(self.text_offsets) == n):
            raise ValueError(f"tokens/logprobs/text_offsets must be the same length, got {n}/{len(self.logprobs)}/{len(self.text_offsets)}")

    def __len__(self) -> int:
        return len(self.tokens)

    def suffix_from(self, char_offset: int) -> TokenLogprobs:
        """The tokens at or after `char_offset` - used to cut the pitch out of a primed reading."""
        keep = [i for i, off in enumerate(self.text_offsets) if off >= char_offset]
        return TokenLogprobs(
            tokens=[self.tokens[i] for i in keep],
            logprobs=[self.logprobs[i] for i in keep],
            text_offsets=[self.text_offsets[i] for i in keep],
            top_logprobs=[self.top_logprobs[i] for i in keep] if self.top_logprobs else [],
        )


@dataclass(frozen=True)
class SpanDelta:
    """One sentence of the pitch, with how much the prior art helped predict it."""

    text: str
    start: int
    end: int
    delta: float  # nats/token; high = the neighbourhood explains this span
    n_tokens: int


@dataclass(frozen=True)
class RCSResult:
    nats_per_token: float
    n_tokens: int
    cold_surprisal: float  # nats/token with no context; the baseline the delta is measured from
    primed_surprisal: float
    spans: list[SpanDelta]
    n_neighbours: int

    def as_detail(self) -> dict[str, Any]:
        return {"rcs_nats_per_token": round(self.nats_per_token, 4), "n_tokens": self.n_tokens,
                "cold_surprisal": round(self.cold_surprisal, 4), "primed_surprisal": round(self.primed_surprisal, 4),
                "n_neighbours": self.n_neighbours,
                "explained_spans": [{"text": s.text[:120], "start": s.start, "end": s.end, "delta": round(s.delta, 3)}
                                    for s in sorted(self.spans, key=lambda s: s.delta, reverse=True)[:5]]}


@dataclass(frozen=True)
class Curvature:
    d: float  # Fast-DetectGPT statistic; higher = more machine-like
    n_tokens: int
    mean_logprob: float

    def as_detail(self) -> dict[str, Any]:
        return {"curvature": round(self.d, 4), "n_tokens": self.n_tokens, "mean_logprob": round(self.mean_logprob, 4)}


# --------------------------------------------------------------------------------------
# Pure maths
# --------------------------------------------------------------------------------------
def token_surprisals(logprobs: Sequence[float]) -> list[float]:
    """Surprisal in nats: -log p of the token that actually appeared."""
    return [-float(lp) for lp in logprobs]


def mean_surprisal(logprobs: Sequence[float]) -> float:
    s = token_surprisals(logprobs)
    return sum(s) / len(s) if s else 0.0


def align(cold: TokenLogprobs, primed: TokenLogprobs) -> tuple[list[float], list[float], list[int]]:
    """Line the two readings up on the pitch tokens, returning (cold lp, primed lp, char offset) per token.

    The pitch is a suffix of the primed prompt, so the same tokenizer produces the same tokens for it - except
    possibly at the seam, where the preceding character changes how the first token is split. We take the
    longest common suffix of the two token sequences rather than trusting the lengths to match."""
    i, j = len(cold.tokens), len(primed.tokens)
    k = 0
    while k < min(i, j) and cold.tokens[i - 1 - k] == primed.tokens[j - 1 - k]:
        k += 1
    if k == 0:
        return [], [], []
    return (cold.logprobs[i - k:], primed.logprobs[j - k:], cold.text_offsets[i - k:])


def retrieval_conditioned_surprisal(cold: TokenLogprobs, primed: TokenLogprobs, *, text: str = "",
                                    n_neighbours: int = 0) -> RCSResult | None:
    """delta_t = primed logprob - cold logprob, averaged over the pitch tokens both readings share.

    Positive: the neighbourhood made the pitch easier to predict (crowded). Returns None when the two readings
    share too few tokens to average over."""
    cold_lp, primed_lp, offsets = align(cold, primed)
    if len(cold_lp) < MIN_TOKENS:
        return None
    deltas = [p - c for c, p in zip(cold_lp, primed_lp)]
    spans = sentence_deltas(text, offsets, deltas) if text else []
    return RCSResult(nats_per_token=sum(deltas) / len(deltas), n_tokens=len(deltas),
                     cold_surprisal=mean_surprisal(cold_lp), primed_surprisal=mean_surprisal(primed_lp),
                     spans=spans, n_neighbours=n_neighbours)


_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|\n|$)")


def split_sentences(text: str) -> list[tuple[int, int]]:
    """(start, end) character spans. Deliberately the same crude rule the Voice panel uses: the spans only
    have to be stable enough to colour, and a sentence splitter is not what this measurement is about."""
    return [(m.start(), m.end()) for m in _SENTENCE.finditer(text) if m.group().strip()]


def sentence_deltas(text: str, offsets: Sequence[int], deltas: Sequence[float]) -> list[SpanDelta]:
    """Roll per-token deltas up to sentences through the tokenizer's `text_offset`, so the UI can colour the
    pitch: high delta = prior art predicted this span, near zero = nothing in the corpus saw it coming."""
    out: list[SpanDelta] = []
    for start, end in split_sentences(text):
        vals = [d for off, d in zip(offsets, deltas) if start <= off < end]
        if vals:
            out.append(SpanDelta(text=text[start:end].strip(), start=start, end=end,
                                 delta=sum(vals) / len(vals), n_tokens=len(vals)))
    return out


def _moments(top: dict[str, float]) -> tuple[float, float] | None:
    """Mean and variance of log p(v) under p(.|x_<t), taken over the returned top-k and renormalised.

    The exact statistic sums over the whole vocabulary. vLLM returns k alternatives, so this is a truncated
    estimate: it understates the variance a little, identically for every text, which is what matters for a
    statistic that is only ever read as a percentile against a reference set built the same way."""
    lps = [float(v) for v in top.values()]
    if len(lps) < 2:
        return None
    m = max(lps)
    weights = [math.exp(lp - m) for lp in lps]
    total = sum(weights)
    if total <= 0:
        return None
    probs = [w / total for w in weights]
    mu = sum(p * lp for p, lp in zip(probs, lps))
    var = sum(p * (lp - mu) ** 2 for p, lp in zip(probs, lps))
    return mu, var


def fast_detect_curvature(reading: TokenLogprobs) -> Curvature | None:
    """Fast-DetectGPT conditional probability curvature (arxiv 2310.05130), one forward pass.

        d = (sum_t log p(x_t) - sum_t mu_t) / sqrt(sum_t sigma_t^2)

    Higher = the text sits further above what the model expected of itself = more machine-like. The number is
    only meaningful against a reference distribution of known-human text of the same genre, which is why
    `search/calibration.py` builds one from the pre-2022 (pre-ChatGPT) corpus."""
    if not reading.top_logprobs or len(reading) < MIN_TOKENS:
        return None
    observed = mu_sum = var_sum = 0.0
    n = 0
    for lp, top in zip(reading.logprobs, reading.top_logprobs):
        moments = _moments(top)
        if moments is None:
            continue
        mu, var = moments
        observed += float(lp)
        mu_sum += mu
        var_sum += var
        n += 1
    if n < MIN_TOKENS or var_sum <= 0:
        return None
    return Curvature(d=(observed - mu_sum) / math.sqrt(var_sum), n_tokens=n, mean_logprob=observed / n)


CURVATURE_FPR = 0.05  # the operating point: flag only above the 95th percentile of known-human pitches


def classify_curvature(percentile: float | None, *, fpr: float = CURVATURE_FPR) -> str | None:
    """Turn a percentile against the HUMAN reference into a verdict, with the error rate chosen up front.

    At fpr=0.05 the detector calls "ai" only above the 95th percentile of pre-ChatGPT hackathon write-ups, so
    its false-positive rate on that genre is 5% by construction. None when there is no reference to compare to."""
    if percentile is None:
        return None
    return "ai" if percentile >= 1.0 - fpr else "human"


def detector_agreement(gptzero_class: str | None, curvature_class: str | None) -> str:
    """"ai" and "mixed" both mean the pitch is partly machine-written, so both agree with a curvature "ai"."""
    if gptzero_class is None or curvature_class is None:
        return "unknown"
    return "agree" if (gptzero_class in ("ai", "mixed")) == (curvature_class == "ai") else "disagree"


def build_primed_prompt(pitch: str, neighbours: Sequence[str], *, max_chars: int = 6000) -> tuple[str, int]:
    """(prompt, character offset where the pitch starts). Neighbours go first so the pitch is a clean suffix
    and so the shared prefix caches across the calls in one run."""
    header = "Existing hackathon and startup projects:\n\n"
    budget = max(0, max_chars - len(pitch) - len(header) - 64)
    blocks, used = [], 0
    for nb in neighbours:
        block = f"- {nb.strip()[:600]}\n"
        if used + len(block) > budget:
            break
        blocks.append(block)
        used += len(block)
    prefix = f"{header}{''.join(blocks)}\nA new project:\n" if blocks else ""
    return prefix + pitch, len(prefix)


# --------------------------------------------------------------------------------------
# --- network ---
# --------------------------------------------------------------------------------------
def available() -> bool:
    return get_settings().has_surprisal


def parse_completion(payload: dict[str, Any]) -> TokenLogprobs | None:
    """Pull the echoed prompt logprobs out of an OpenAI-shaped `/v1/completions` response.

    The first prompt token carries `null` (nothing conditions it) and is dropped."""
    choices = payload.get("choices") or []
    lp = (choices[0] or {}).get("logprobs") if choices else None
    if not lp:
        return None
    tokens = list(lp.get("tokens") or [])
    logprobs = list(lp.get("token_logprobs") or [])
    offsets = list(lp.get("text_offset") or [])
    tops = list(lp.get("top_logprobs") or [])
    keep = [i for i in range(min(len(tokens), len(logprobs), len(offsets))) if logprobs[i] is not None]
    if not keep:
        return None
    return TokenLogprobs(
        tokens=[tokens[i] for i in keep],
        logprobs=[float(logprobs[i]) for i in keep],
        text_offsets=[int(offsets[i]) for i in keep],
        top_logprobs=[dict(tops[i] or {}) for i in keep] if len(tops) >= len(tokens) else [],
    )


async def read(text: str, *, top_k: int = TOP_K) -> TokenLogprobs | None:
    """One `echo` reading of `text`. Returns None when the deployment is not configured or does not answer:
    every caller treats that as "this instrument abstains", never as a zero."""
    s = get_settings()
    if not s.has_surprisal or not text.strip():
        return None
    import httpx

    headers = {"Content-Type": "application/json"}
    if s.surprisal_api_key:
        headers["Authorization"] = f"Bearer {s.surprisal_api_key}"
    body = {"model": s.surprisal_model, "prompt": text[: s.surprisal_max_chars], "max_tokens": 1,
            "temperature": 0, "echo": True, "logprobs": top_k}
    try:
        async with httpx.AsyncClient(timeout=s.surprisal_timeout_s) as client:
            resp = await client.post(f"{s.surprisal_base_url.rstrip('/')}/completions", json=body, headers=headers)
            resp.raise_for_status()
            return parse_completion(resp.json())
    except Exception:
        return None  # degrade rather than fail the run; the caller surfaces the abstention


async def measure_rcs(pitch: str, neighbours: Sequence[str]) -> RCSResult | None:
    """Both readings of the pitch, cold and primed on the nearest existing projects."""
    import asyncio

    if not available() or not neighbours or not pitch.strip():
        return None
    s = get_settings()
    primed_prompt, pitch_start = build_primed_prompt(pitch, neighbours, max_chars=s.surprisal_max_chars)
    if pitch_start == 0:
        return None  # no neighbour survived the character budget: there is nothing to condition on
    cold, primed = await asyncio.gather(read(pitch), read(primed_prompt))
    if cold is None or primed is None:
        return None
    return retrieval_conditioned_surprisal(cold, primed.suffix_from(pitch_start), text=pitch,
                                           n_neighbours=len(neighbours))


async def measure_curvature(text: str) -> Curvature | None:
    """Fast-DetectGPT on the pitch. Needs top-k alternatives, so it reads with a larger k than RCS."""
    reading = await read(text, top_k=max(TOP_K, 5))
    return fast_detect_curvature(reading) if reading else None
