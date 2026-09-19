"""The verifier's veto, as a decision table over both layers (local quote check x GPTZero bibliography scan)."""
import pytest

from app.roles.verifier import _final_status, _quote_in_text
from app.schemas import Verification


@pytest.mark.parametrize(
    ("local", "gptzero", "stance", "expected"),
    [
        (True, None, None, "verified"),  # GPTZero silent / not run: layer 1 alone can verify
        (True, "exist", "support", "verified"),
        (True, "unknown", None, "verified"),  # the scanner is tuned for academic citations; "unknown" must never block
        (True, "unsure", None, "verified"),
        (False, "exist", "support", "unverified_lead"),  # real page, but it does not say what the agent claimed
        (False, None, None, "unverified_lead"),
        (True, "exist", "strongly contradict", "unverified_lead"),  # an independent source disagrees
        (False, "fake", None, "rejected"),  # fabricated competitor: no receipt anywhere
        (True, "fake", None, "unverified_lead"),  # layers disagree about a source we hold: show it, do not assert it
    ],
)
def test_decision_table(local, gptzero, stance, expected):
    assert _final_status(Verification(local_quote_match=local, gptzero_status=gptzero, stance=stance)) == expected


def test_quote_layer_is_tolerant_but_not_gullible():
    source = "IdeaRadar takes a hackathon idea, extracts keywords with an LLM and searches Devpost for similar projects."
    assert _quote_in_text("extracts keywords with an LLM and searches Devpost", source)[0]
    assert _quote_in_text("Extracts  keywords with an LLM, and searches “Devpost”", source)[0]  # case, spacing, punctuation, curly quotes
    assert not _quote_in_text("won the grand prize at three consecutive hackathons", source)[0]
    assert not _quote_in_text("", source)[0]
