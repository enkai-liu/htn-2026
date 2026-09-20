"""Token-level instruments (signals/surprisal.py). All offline: synthetic logprobs, no deployment needed."""
import math

import pytest

from app.signals import surprisal
from app.signals.surprisal import TokenLogprobs


def reading(tokens, logprobs, offsets=None, top=None) -> TokenLogprobs:
    offsets = offsets if offsets is not None else _offsets(tokens)
    return TokenLogprobs(tokens=list(tokens), logprobs=list(logprobs), text_offsets=list(offsets),
                         top_logprobs=list(top) if top else [])


def _offsets(tokens):
    out, pos = [], 0
    for t in tokens:
        out.append(pos)
        pos += len(t)
    return out


def repeat(tokens, n):
    return tokens * n


# ---------------------------------------------------------------- shapes
def test_tokenlogprobs_rejects_ragged_input():
    with pytest.raises(ValueError):
        TokenLogprobs(tokens=["a", "b"], logprobs=[-1.0], text_offsets=[0, 1])


def test_suffix_from_cuts_at_a_character_offset():
    r = reading(["ab", "cd", "ef"], [-1.0, -2.0, -3.0])  # offsets 0, 2, 4
    assert r.suffix_from(2).tokens == ["cd", "ef"]
    assert r.suffix_from(0).tokens == ["ab", "cd", "ef"]
    assert len(r.suffix_from(99)) == 0


# ---------------------------------------------------------------- surprisal
def test_token_surprisals_is_negative_logprob():
    assert surprisal.token_surprisals([-1.0, -2.0]) == [1.0, 2.0]
    assert surprisal.mean_surprisal([-1.0, -3.0]) == 2.0
    assert surprisal.mean_surprisal([]) == 0.0


# ---------------------------------------------------------------- alignment
def test_align_takes_the_longest_common_suffix():
    cold = reading(["the", "idea"], [-1.0, -2.0])
    primed = reading(["prior", "art", "the", "idea"], [-9.0, -9.0, -0.5, -0.5])
    cold_lp, primed_lp, offsets = surprisal.align(cold, primed)
    assert cold_lp == [-1.0, -2.0] and primed_lp == [-0.5, -0.5]
    assert offsets == [0, 3]  # offsets come from the COLD reading, so they index the pitch


def test_align_survives_a_different_split_at_the_seam():
    cold = reading(["An", " idea", " here"], [-1.0, -2.0, -3.0])
    primed = reading(["ctx", "An", " idea", " here"], [-9.0, -1.5, -2.5, -3.5])
    cold_lp, _, _ = surprisal.align(cold, primed)
    assert len(cold_lp) == 3
    # only the tail matches -> only the tail is compared, never a silently misaligned pair
    odd = reading(["Anid", "ea", " here"], [-1.0, -2.0, -3.0])
    assert len(surprisal.align(odd, primed)[0]) == 1


def test_align_returns_nothing_when_no_tokens_match():
    assert surprisal.align(reading(["x"], [-1.0]), reading(["y"], [-1.0])) == ([], [], [])


# ---------------------------------------------------------------- RCS
def test_rcs_is_positive_when_the_neighbourhood_explains_the_pitch():
    toks = repeat(["a", "b", "c", "d"], 8)  # 32 tokens, above MIN_TOKENS
    cold = reading(toks, [-3.0] * len(toks))
    primed = reading(toks, [-1.0] * len(toks))
    out = surprisal.retrieval_conditioned_surprisal(cold, primed, n_neighbours=10)
    assert out is not None
    assert out.nats_per_token == pytest.approx(2.0)  # the prior art saves 2 nats/token
    assert out.cold_surprisal == pytest.approx(3.0) and out.primed_surprisal == pytest.approx(1.0)
    assert out.n_tokens == 32 and out.n_neighbours == 10


def test_rcs_is_zero_when_the_neighbourhood_does_not_help():
    toks = repeat(["a", "b", "c", "d"], 8)
    same = [-2.5] * len(toks)
    out = surprisal.retrieval_conditioned_surprisal(reading(toks, same), reading(toks, same))
    assert out is not None and out.nats_per_token == pytest.approx(0.0)


def test_rcs_abstains_on_a_pitch_too_short_to_average():
    toks = ["a", "b", "c"]
    assert surprisal.retrieval_conditioned_surprisal(reading(toks, [-1.0] * 3), reading(toks, [-1.0] * 3)) is None


def test_rcs_is_monotone_in_how_much_the_context_helps():
    toks = repeat(["a", "b"], 16)
    cold = reading(toks, [-4.0] * len(toks))
    values = [surprisal.retrieval_conditioned_surprisal(cold, reading(toks, [lp] * len(toks))).nats_per_token
              for lp in (-4.0, -3.0, -2.0, -1.0)]
    assert values == sorted(values) and len(set(values)) == 4


# ---------------------------------------------------------------- per-sentence rollup
def test_sentence_deltas_attribute_the_crowding_to_spans():
    text = "A flashcard app for students. Acoustic varroa mite detection."
    second = text.index("Acoustic")
    offsets = [0, 10, second, second + 9]
    spans = surprisal.sentence_deltas(text, offsets, [2.0, 3.0, 0.1, -0.1])
    assert len(spans) == 2
    assert spans[0].delta == pytest.approx(2.5) and spans[0].text.startswith("A flashcard")
    assert spans[1].delta == pytest.approx(0.0)  # nothing in the corpus saw this one coming
    assert spans[0].n_tokens == 2


def test_sentence_deltas_skips_sentences_with_no_tokens():
    assert surprisal.sentence_deltas("One. Two.", [0], [1.0])[0].text == "One."
    assert len(surprisal.sentence_deltas("One. Two.", [0], [1.0])) == 1


def test_split_sentences_ignores_empty_fragments():
    assert surprisal.split_sentences("A. B!  ") == [(0, 2), (2, 5)]
    assert surprisal.split_sentences("   ") == []


# ---------------------------------------------------------------- Fast-DetectGPT
def _flat_top(n, k=5, spread=1.0):
    """k alternatives spaced `spread` nats apart at every position."""
    return [{f"t{j}": -1.0 - j * spread for j in range(k)} for _ in range(n)]


def test_curvature_is_higher_when_the_text_sits_above_the_models_expectation():
    n = 40
    top = _flat_top(n)
    machine = reading(["a"] * n, [-1.0] * n, top=top)  # picked the model's own top token every time
    human = reading(["a"] * n, [-4.0] * n, top=top)  # picked unlikely tokens
    assert surprisal.fast_detect_curvature(machine).d > surprisal.fast_detect_curvature(human).d


def test_curvature_abstains_without_alternatives_or_length():
    n = 40
    assert surprisal.fast_detect_curvature(reading(["a"] * n, [-1.0] * n)) is None  # no top_logprobs
    assert surprisal.fast_detect_curvature(reading(["a"] * 5, [-1.0] * 5, top=_flat_top(5))) is None  # too short


def test_curvature_abstains_when_the_distribution_has_no_spread():
    n = 40
    flat = [{"t0": -1.0, "t1": -1.0} for _ in range(n)]
    assert surprisal.fast_detect_curvature(reading(["a"] * n, [-1.0] * n, top=flat)) is None  # variance 0


def test_moments_match_a_hand_computed_two_point_distribution():
    # logprobs -1 and -2 renormalise to p = (e^-1, e^-2) / (e^-1 + e^-2)
    p0 = math.exp(-1) / (math.exp(-1) + math.exp(-2))
    mu_expected = p0 * -1 + (1 - p0) * -2
    mu, var = surprisal._moments({"a": -1.0, "b": -2.0})
    assert mu == pytest.approx(mu_expected)
    assert var == pytest.approx(p0 * (-1 - mu_expected) ** 2 + (1 - p0) * (-2 - mu_expected) ** 2)
    assert surprisal._moments({"a": -1.0}) is None


# ---------------------------------------------------------------- verdicts
def test_classify_curvature_has_an_explicit_false_positive_rate():
    assert surprisal.classify_curvature(0.96) == "ai"  # above the 95th percentile of human pitches
    assert surprisal.classify_curvature(0.95) == "ai"
    assert surprisal.classify_curvature(0.94) == "human"
    assert surprisal.classify_curvature(None) is None  # no human reference -> no verdict
    assert surprisal.classify_curvature(0.92, fpr=0.10) == "ai"


def test_detector_agreement_treats_mixed_as_partly_machine():
    assert surprisal.detector_agreement("ai", "ai") == "agree"
    assert surprisal.detector_agreement("mixed", "ai") == "agree"
    assert surprisal.detector_agreement("human", "human") == "agree"
    assert surprisal.detector_agreement("human", "ai") == "disagree"
    assert surprisal.detector_agreement("ai", "human") == "disagree"
    assert surprisal.detector_agreement(None, "ai") == "unknown"
    assert surprisal.detector_agreement("ai", None) == "unknown"


# ---------------------------------------------------------------- prompt construction
def test_primed_prompt_puts_the_pitch_last_and_reports_where_it_starts():
    prompt, start = surprisal.build_primed_prompt("MY PITCH", ["neighbour one", "neighbour two"])
    assert prompt.endswith("MY PITCH") and prompt[start:] == "MY PITCH"
    assert "neighbour one" in prompt[:start] and "neighbour two" in prompt[:start]


def test_primed_prompt_drops_neighbours_that_do_not_fit_the_budget():
    prompt, start = surprisal.build_primed_prompt("PITCH", ["x" * 500, "y" * 500], max_chars=700)
    assert "x" * 500 in prompt and "y" * 500 not in prompt and start > 0


def test_primed_prompt_with_no_neighbours_is_just_the_pitch():
    prompt, start = surprisal.build_primed_prompt("PITCH", [])
    assert (prompt, start) == ("PITCH", 0)  # start == 0 is the caller's signal that there is nothing to condition on


# ---------------------------------------------------------------- response parsing
def test_parse_completion_drops_the_unconditioned_first_token():
    payload = {"choices": [{"logprobs": {
        "tokens": ["An", " idea"], "token_logprobs": [None, -2.0], "text_offset": [0, 2],
        "top_logprobs": [None, {"t": -2.0, "u": -3.0}]}}]}
    out = surprisal.parse_completion(payload)
    assert out.tokens == [" idea"] and out.logprobs == [-2.0] and out.text_offsets == [2]
    assert out.top_logprobs == [{"t": -2.0, "u": -3.0}]


def test_parse_completion_returns_none_without_logprobs():
    assert surprisal.parse_completion({"choices": [{"text": "hi"}]}) is None
    assert surprisal.parse_completion({}) is None
    assert surprisal.parse_completion({"choices": [{"logprobs": {"tokens": ["a"], "token_logprobs": [None], "text_offset": [0]}}]}) is None


# ---------------------------------------------------------------- abstention
async def test_measure_rcs_abstains_without_a_deployment(monkeypatch):
    monkeypatch.setattr(surprisal, "available", lambda: False)
    assert await surprisal.measure_rcs("a pitch", ["a neighbour"]) is None


async def test_measure_rcs_abstains_with_no_neighbours():
    assert await surprisal.measure_rcs("a pitch", []) is None
