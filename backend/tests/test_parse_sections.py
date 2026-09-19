"""ingest/parse_sections.py on real messy write-ups (fixtures are real rows from the two HF datasets)."""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ingest import parse_sections as ps  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ALVANLII = {r["title"]: r for r in json.loads((FIXTURES / "alvanlii_rows.json").read_text(encoding="utf-8"))["rows"]}
TWANGODEV = {r["title"]: r for r in json.loads((FIXTURES / "twangodev_rows.json").read_text(encoding="utf-8"))["rows"]}


@pytest.mark.parametrize(
    "line,key",
    [
        ("Inspiration", "inspiration"),
        ("INSPIRATION", "inspiration"),
        ("Inspiration-", "inspiration"),
        ("💡 Inspiration", "inspiration"),
        ("Our Inspiration", "inspiration"),
        ("What's the Buzz? - Inspiration", "inspiration"),
        ("## What it does", "what_it_does"),
        ("### What It Does", "what_it_does"),
        ("**What it does:**", "what_it_does"),
        ("__What it does__", "what_it_does"),
        ("What it does:", "what_it_does"),
        ("1. What it does", "what_it_does"),
        ("What it does (current stage)", "what_it_does"),
        ("🚀 WHAT IT DOES 🚀", "what_it_does"),
        ("How we built it", "how_we_built_it"),
        ("How I built it", "how_we_built_it"),
        ("How we build it", "how_we_built_it"),
        ("HOW WE BUILT IT", "how_we_built_it"),
        ("Challenges we ran into", "challenges"),
        ("Challenges I ran into", "challenges"),
        ("Challenges We Faced", "challenges"),
        ("CHALLENGES", "challenges"),
        ("Accomplishments that we're proud of", "accomplishments"),
        ("Accomplishments that we’re proud of", "accomplishments"),  # curly apostrophe
        ("Accomplishments that I'm proud of", "accomplishments"),
        ("Accomplishments We're Proud Of", "accomplishments"),
        ("Accomplishments that We are proud of", "accomplishments"),
        ("ACCOMPLISHMENTS", "accomplishments"),
        ("What we learned", "what_we_learned"),
        ("What I learned", "what_we_learned"),
        ("What we learned:", "what_we_learned"),
        ("What's next for Crazy Cows Game", "whats_next"),
        ("What’s next for plateful", "whats_next"),
        ("WHAT'S NEXT", "whats_next"),
        ("NEXT STEPS", "whats_next"),
        ("Built With", "built_with"),
        ("Try it out", "try_it_out"),
    ],
)
def test_heading_variants(line, key):
    assert ps.match_heading(line) == key


@pytest.mark.parametrize(
    "line",
    [
        "Built with ❤️ for optimal nutrition",
        "What if technology could give everyone new senses?",
        "🧩 Built deploy-first via",
        "NextJS, React, Tailwind for fast UI and optimistic updates",
        "Built the whole stack from 0!",
        "- Built transformer service to normalize Bright Data & Open-Meteo",
        "Inspiration struck us when we saw how many students struggle to find a study group on a big campus.",
        "What is the problem we are solving",
        "",
    ],
)
def test_prose_lines_are_not_headings(line):
    assert ps.match_heading(line) is None


def test_alvanlii_blank_line_format_and_empty_sections():
    row = ALVANLII["It Too Long I Don't Read"]
    sections = ps.parse_sections(row["full_desc"])
    assert sections["what_it_does"].startswith("This extension will extract the content")
    assert {"inspiration", "how_we_built_it", "challenges", "accomplishments", "built_with", "try_it_out"} <= set(sections)
    # "What we learned" and "What's next for …" are present as headings but EMPTY in the source: dropped.
    assert "what_we_learned" not in sections and "whats_next" not in sections
    assert sections["preamble"] == "Example of summarize"  # a gallery caption, kept out of the pitch below
    assert sections["built_with"].split() == ["chromeextension", "gemini", "vuejs"]


def test_twangodev_single_newline_format():
    sections = ps.parse_sections(TWANGODEV["Githired"]["description"])
    assert list(sections)[:3] == ["inspiration", "what_it_does", "how_we_built_it"]
    assert sections["what_it_does"].startswith("You create a smart application form")
    assert "whats_next" in sections


def test_repeated_headings_are_concatenated_and_generic_headings_kept():
    text = "## What it does\nFirst part.\n## Business Model\nFreemium.\n## What it does\nSecond part."
    sections = ps.parse_sections(text)
    assert sections["what_it_does"] == "First part.\nSecond part."
    assert sections["other:business_model"] == "Freemium."


def test_inline_heading_with_body_on_the_same_line():
    sections = ps.parse_sections("What it does: It summarises any web page into one paragraph for you.\nInspiration\nLong articles.")
    assert sections["what_it_does"].startswith("It summarises any web page")
    assert sections["inspiration"] == "Long articles."


def test_html_remnants_entities_images_and_links():
    raw = (
        "<h2>Inspiration</h2><p>Reading is <em>slow</em>.</p><h2>What it does</h2>"
        "<p>It <strong>summarises</strong> pages&nbsp;&amp; answers questions. See <a href='https://x.io/demo'>the demo</a>.</p>"
        "<img src='https://x.io/shot.png'><ul><li>Fast</li><li>Private</li></ul><script>alert(1)</script>"
    )
    sections = ps.parse_sections(raw)
    assert sections["inspiration"] == "Reading is slow."
    body = sections["what_it_does"]
    assert "<" not in body and "&amp;" not in body and "alert(1)" not in body
    assert "summarises pages & answers questions" in ps.to_prose(body)
    md = "What it does\n![screenshot](https://x.io/a.png) Our tool uses [OpenAI](https://openai.com) and **Pinecone** to rank ideas."
    pitch = ps.build_pitch("RankIt", "Rank ideas", md)
    assert "![" not in pitch and "](" not in pitch and "https://" not in pitch and "**" not in pitch
    assert "uses OpenAI and Pinecone to rank ideas." in pitch


def test_flattened_bold_label_is_rejoined():
    # "<strong>Description</strong>: text" is flattened to "Description\n\n: text" in the HF dump.
    sections = ps.parse_sections(ALVANLII["DevSpot"]["full_desc"])
    assert sections["what_it_does"].count("\n\n:") == 0
    pitch = ps.build_pitch("DevSpot", ALVANLII["DevSpot"]["brief_desc"], ALVANLII["DevSpot"]["full_desc"])
    assert "DevSpot is a pioneering platform designed to enhance the hackathon experience" in pitch
    assert "Hero Page" not in pitch and "DevSpot Logo" not in pitch  # gallery captions never reach the pitch


@pytest.mark.parametrize("row,title_key,tagline_key,desc_key", [
    *[(r, "title", "brief_desc", "full_desc") for r in ALVANLII.values()],
    *[(r, "title", "tagline", "description") for r in TWANGODEV.values()],
], ids=lambda v: v.get("title") if isinstance(v, dict) else None)
def test_pitch_invariants_on_real_rows(row, title_key, tagline_key, desc_key):
    pitch = ps.build_pitch(row[title_key], row[tagline_key], row[desc_key])
    assert pitch.startswith(row[title_key])
    assert len(pitch) <= ps.PITCH_CAP
    assert "\n" not in pitch and "  " not in pitch
    assert "Built With" not in pitch and "\\documentclass" not in pitch and "\\section" not in pitch


def test_pitch_cap_ends_on_a_sentence_boundary():
    row = TWANGODEV["DoGood"]
    pitch = ps.build_pitch(row["title"], row["tagline"], row["description"])
    assert 1000 < len(pitch) <= 1500
    assert pitch[-1] in ".!?…\"')"
    long = "Alpha beta gamma. " * 200
    cut = ps.truncate_at_sentence(long, 1500)
    assert len(cut) <= 1500 and cut.endswith("gamma.")
    assert ps.truncate_at_sentence("word " * 1000, 100).endswith("…")
    assert ps.truncate_at_sentence("short text", 100) == "short text"


def test_fallback_when_headings_are_missing_skips_captions():
    text = "Login Screen\n\nHome Screen\n\nhttps://youtu.be/abc\n\nTipster lets travellers share verified local tips. Reviews are ranked by credibility.\n\nIt runs on ASP.NET."
    pitch = ps.build_pitch("TIPSTER!", "Tips you can trust", text)
    assert pitch.startswith("TIPSTER! Tips you can trust. Tipster lets travellers share verified local tips.")
    assert "Login Screen" not in pitch and "youtu.be" not in pitch


def test_thin_what_it_does_is_topped_up_from_other_sections():
    row = ALVANLII["Crazy Cows Game"]  # has no "What it does" at all
    pitch = ps.build_pitch(row["title"], row["brief_desc"], row["full_desc"])
    assert "humorous 2 player platform fighting game" in pitch and "Super Smash Bros" in pitch
    assert "P1 Cow Sprite" not in pitch


def test_latex_writeup_is_made_readable():
    row = TWANGODEV["ScoutExchange"]
    sections = ps.parse_sections(row["description"])
    assert sections["inspiration"].startswith("Fantasy sports meet Wall Street")
    assert not any("\\" in v for v in sections.values())


def test_extract_tech_provenance_ladder():
    assert ps.extract_tech(["React", " python ", "react", ""]) == (["react", "python"], "source")
    sections = ps.parse_sections(ALVANLII["Crazy Cows Game"]["full_desc"])
    assert ps.extract_tech([], sections=sections) == (["c#", "unity"], "normalized")  # parsed from the "Built With" block
    prose = {"how_we_built_it": "We used Next.js and FastAPI, stored vectors in Pinecone and called GPT-4 through LangChain."}
    tech, prov = ps.extract_tech(None, sections=prose)
    assert prov == "imputed" and {"next.js", "fastapi", "pinecone", "openai", "langchain"} <= set(tech)
    assert ps.extract_tech(None, sections={"inspiration": "We love hackathons."}) == ([], None)
    # word boundaries: "go" inside "google"/"good" or "java" inside "javascript" must not match
    tech, _ = ps.extract_tech(None, sections={"how_we_built_it": "A good javascript frontend on Google Cloud."})
    assert "java" not in tech and "go" not in tech and "javascript" in tech and "google-cloud" in tech


def test_guess_lang_is_conservative():
    assert ps.guess_lang("This extension will extract the content of the website and then summarize it for you in a paragraph.") == "en"
    assert ps.guess_lang("Nuestra aplicación ayuda a los estudiantes a encontrar grupos de estudio para que puedan aprender más con sus compañeros y los profesores.") == "es"
    assert ps.guess_lang("这个应用帮助学生找到学习小组并且用人工智能总结他们的笔记内容以便更好地学习") == "zh"
    # English full of "as … as" must not be mistaken for Portuguese; short text is undetermined.
    assert ps.guess_lang("Access all your live data in one place. As easy and flexible as a spreadsheet, as powerful as SQL.") == "en"
    assert ps.guess_lang("Uber for dogs") == "und"
    assert ps.guess_lang(None) == "und"
