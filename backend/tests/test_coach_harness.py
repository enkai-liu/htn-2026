"""The coach is held to a few plain sentences in code, because the model ignores the limits it is given in the prompt.
Every input here is something it really said to someone."""
from app.roles.mutator import REPLY_CAP, _brief, _chips, _one_question, _plain

YAP = ("That reframes everything. You're not building a study buddy; you're building a mark-per-hour optimizer that treats past exams as a "
       "betting market on where effort pays off. That's genuinely different—none of the listed projects position themselves as exam-value "
       "arbitrage. Your backend skills fit: parse PDF exams, map questions to syllabus topics, weight by frequency and mark density, then "
       "divide by estimated mastery time. The design stays minimal: a ranked list, not a chatbot. Your weekend build: single course, three "
       "past papers, crude topic tagger, output a ranked priority list. Ship that.")


def test_a_long_reply_is_cut_to_three_whole_sentences():
    out = _brief(YAP)
    assert out.endswith("arbitrage.") and "Your backend skills" not in out
    assert len(out) <= REPLY_CAP and len(out.split()) <= 60


def test_a_short_reply_is_left_alone_and_a_dotted_name_does_not_end_a_sentence():
    text = "TensorChip Co.,Ltd and Baud both sell this. Nothing here is yours yet."
    assert _brief(text) == text


def test_a_question_with_a_menu_bolted_on_keeps_the_question():
    q = ("What do you refuse to give up — the physical act of making chips, the scale of data-center revenue, or the identity of being a "
         "hardware company — and what skill or community do you already have that software people in this space lack?")
    assert _one_question(q) == "What do you refuse to give up?"
    short = "Which course do you have past exams for already, and do they publish mark schemes?"
    assert _one_question(short) == short
    assert _one_question("Who is it for? And what would they pay?") == "Who is it for?"


def test_chips_never_put_a_life_story_in_the_authors_mouth():
    chips = _chips(["I grew up on a farm and know exactly what pest detection looks like in practice",
                    "I'm a former climate scientist with contacts at NOAA", "I've already designed a PCB and have a reflow oven in my garage",
                    "None of these—my pain point is: ________", "1. I'd change who it's for"], fallback=True)
    assert chips[0] == "I'd change who it's for" and len(chips) == 3
    assert not any("farm" in c or "NOAA" in c or "PCB" in c or "__" in c for c in chips)
    assert _chips(["Keep the scheduler, drop the chat", "Keep the scheduler, drop the chat"]) == ["Keep the scheduler, drop the chat"]


def test_the_models_notes_are_not_quoted_back_at_the_author():
    assert _plain("WHITESPACE: 'opencv' appears in corpus but absent near all neighbours") == "'opencv' appears in the dataset but absent near all neighbours"
    assert "corpus" not in _plain("Nothing in the corpus does this.").lower()


def test_a_chip_is_not_offered_twice():
    assert _chips(["What is the least crowded angle?", "Aim it at warehouse robots"], said=("what is the least crowded angle?",)) == ["Aim it at warehouse robots"]


def test_an_either_or_question_that_runs_on_is_cut_at_the_or_not_mid_word():
    q = ("When you picture someone using this, are they panicking two days before an exam, or are they the kind of person who wishes they "
         "could study a little every week but life keeps getting in the way and they never manage to start?")
    assert _one_question(q) == "When you picture someone using this, are they panicking two days before an exam?"
