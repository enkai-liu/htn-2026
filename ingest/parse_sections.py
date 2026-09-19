"""Turn messy Devpost write-ups into clean sections, a bounded `pitch`, and a tech list.

This is the "messy real-world text" showcase. Real inputs we have seen (HF datasets + live pages):

* alvanlii rows: plain text where every block is separated by a blank line, headings are bare lines
  ("Inspiration", "What it does", "How I built it", "What's next for <Project>"), the text starts with
  gallery captions ("Login Screen", "Hero Page"), bold labels were flattened into "Label\\n\\n: text", and
  the tail carries "Built With\\n\\npython\\n\\nreact\\n\\nTry it out\\n\\ngithub.com".
* twangodev rows: same headings but single newlines, plus ALL-CAPS / Title Case / trailing-colon variants,
  curly apostrophes, emoji-prefixed headings, markdown (`## `, `**bold**`), and even a LaTeX document.
* live project pages: HTML (`<h2>Inspiration</h2><p>..</p><ul><li>..`).

Everything here is pure (no network, no Elastic) so it is unit-testable offline.
"""
from __future__ import annotations

import html as _html
import re
import unicodedata
from typing import Iterable

PITCH_CAP = 1500  # chars; one short field bounds EIS token cost (design 2.3)
TOO_SHORT = 250  # chars of pitch below which the ingest pipeline flags `too_short`

# --------------------------------------------------------------------------------------
# Heading vocabulary. Patterns are matched against a *normalised* heading candidate:
# lower-case, straight apostrophes, no markdown/emoji/numbering decoration, no trailing ":" / "-".
# --------------------------------------------------------------------------------------
_HEADING_PATTERNS: list[tuple[str, str]] = [
    ("inspiration", r"(our |the |my )?inspirations?"),
    ("inspiration", r"what inspired (us|me)"),
    ("inspiration", r".{1,40}[-:] inspiration"),  # "What's the Buzz? - Inspiration"
    ("what_it_does", r"what (it|this|the \w+|our \w+) does( \(.{1,30}\))?"),
    ("what_it_does", r"what does (it|this) do"),
    ("what_it_does", r"what it does .{1,30} do"),  # "What it does Stigmatized do" (seen in the wild)
    ("what_it_does", r"what is (?!next\b|the\b|our\b|a\b|an\b)[\w.&'-]+( [\w.&'-]+){0,3}"),
    ("what_it_does", r"(project |product )?(overview|description|summary)"),
    ("what_it_does", r"about( the| this| our)? (project|app|product|game|tool)"),
    ("what_it_does", r"(the |our )?solution"),
    ("how_it_works", r"how (it|this) works"),
    ("how_it_works", r"how to use( it)?"),
    ("how_it_works", r"(key |main |core )?features"),
    ("how_we_built_it", r"how (we|i|it was|it is|it's|the team) (buil[dt]|made|developed|created)( it| this)?"),
    ("how_we_built_it", r"(the |our )?(tech(nology)? stack|technical implementation|implementation|architecture)"),
    ("how_we_built_it", r"technolog(y|ies) used"),
    ("challenges", r"(the |our )?challenges?( (we|i) (ran into|faced|encountered|had|overcame))?"),
    ("accomplishments", r"accomplishments?( that)?( (we're|we are|i'm|i am|were) (most )?proud of)?"),
    ("accomplishments", r"what (we're|we are|i'm|i am) proud of"),
    ("what_we_learned", r"what (we|i)( have|'ve)? (learned|learnt)"),
    ("what_we_learned", r"(key )?(lessons|learnings|takeaways)( learned)?"),
    ("whats_next", r"what's next( for .{0,80})?"),
    ("whats_next", r"what is next( for .{0,80})?"),
    ("whats_next", r"(next steps|future work|future plans|future scope|roadmap)"),
    ("problem", r"(the |our )?problem( statement)?( we('re| are) solving)?"),
    ("built_with", r"built with"),
    ("try_it_out", r"try it out"),
]
_HEADING_RES = [(key, re.compile(rf"^(?:{pat})$")) for key, pat in _HEADING_PATTERNS]

# When "What it does" is missing we fall back through these (then to the first real paragraphs).
_PITCH_FALLBACK_ORDER = ("what_it_does", "how_it_works", "problem", "preamble", "inspiration", "how_we_built_it")

_MD_HEADING_PREFIX = re.compile(r"^\s{0,3}#{1,6}\s+")
_DECORATION = re.compile(r"^[\s#>*_`~\-–—•·|]+|[\s#*_`~:\-–—.|?!]+$")
_LEADING_NUMBER = re.compile(r"^\(?\d{1,2}[.)]\s+")
_INLINE_HEADING = re.compile(r"^(?P<h>[^:\n]{3,60}?)\s*[:\-–—]\s+(?P<body>\S.{15,})$")

_URL = re.compile(r"(?:https?://|www\.)[^\s<>()\[\]\"']+", re.I)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]*)\)")
_MD_REF_LINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_MD_AUTOLINK = re.compile(r"<((?:https?://|mailto:)[^>\s]+)>")
_CODE_FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.S)
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]{0,200}>")
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff\u00ad]")
_SENTENCE_END = re.compile(r"[.!?…][\"')\]]?(?=\s|$)")


def _is_symbol(ch: str) -> bool:
    """Emoji / pictographs / dingbats (unicode category 'So', 'Sk', variation selectors, ZWJ)."""
    return unicodedata.category(ch) in ("So", "Sk", "Cs", "Co") or ch in "\ufe0f\u200d\u20e3"


def strip_symbols(text: str) -> str:
    return "".join(ch for ch in text if not _is_symbol(ch))


# --------------------------------------------------------------------------------------
# Cleaning
# --------------------------------------------------------------------------------------
def html_to_text(raw: str) -> str:
    """HTML -> markdown-ish text that `parse_sections` understands (headings become '## x' lines)."""
    from bs4 import BeautifulSoup  # local import: keeps module import cheap when bs4 is unused

    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "img", "figure", "video", "audio", "button"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for level in range(1, 7):
        for h in soup.find_all(f"h{level}"):
            h.replace_with(f"\n\n## {h.get_text(' ', strip=True)}\n\n")
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
        li.unwrap()
    for block in soup.find_all(["p", "div", "ul", "ol", "blockquote", "pre", "table", "tr", "section", "article"]):
        block.insert_before("\n\n")
        block.insert_after("\n\n")
        block.unwrap()
    return soup.get_text()


_LATEX_DROP = re.compile(
    r"\\(documentclass|usepackage|title|author|date|geometry|hypersetup|label|includegraphics)(\[[^\]]*\])?\{[^{}]*(\{[^{}]*\}[^{}]*)*\}"
)
_LATEX_SECTION = re.compile(r"\\(?:sub)*section\*?\{([^{}]*)\}")
_LATEX_WRAP = re.compile(r"\\(?:textbf|textit|emph|underline|texttt|textsc|large|Large|huge)\{([^{}]*)\}")
_LATEX_ENV = re.compile(r"\\(?:begin|end)\{[^{}]*\}(\[[^\]]*\])?|\\(maketitle|tableofcontents|newpage|noindent|centering|hline)\b")


def _delatex(text: str) -> str:
    """A few people paste a LaTeX article into Devpost. Make it readable instead of dropping it."""
    if "\\section" not in text and "\\documentclass" not in text and "\\begin{" not in text:
        return text
    for _ in range(3):  # unwrap nested \textbf{\textit{..}}
        text = _LATEX_WRAP.sub(r"\1", text)
    text = _LATEX_DROP.sub(" ", text)
    text = _LATEX_SECTION.sub(lambda m: f"\n\n## {m.group(1)}\n\n", text)
    text = _LATEX_ENV.sub(" ", text)
    text = re.sub(r"\\item\b", "\n- ", text)
    text = text.replace("\\\\", "\n").replace("\\&", "&").replace("\\%", "%").replace("\\$", "$").replace("\\#", "#").replace("\\_", "_")
    text = text.replace("``", '"').replace("''", '"').replace("--", "–")
    return re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", text)


def clean_text(raw: str | None) -> str:
    """Normalise one write-up: HTML remnants, entities, LaTeX, zero-width chars, newlines.

    Keeps line structure (headings need it). Markdown emphasis is kept here and removed per line later.
    """
    if not raw:
        return ""
    text = str(raw)
    if _HTML_TAG.search(text):
        text = html_to_text(text)
    text = _html.unescape(text)
    text = _ZERO_WIDTH.sub("", text).replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = _delatex(text)
    text = _CODE_FENCE.sub("\n", text)
    text = _MD_IMAGE.sub("", text)
    text = _MD_AUTOLINK.sub(r"\1", text)
    # "Label\n\n: rest" is what a flattened "<strong>Label</strong>: rest" looks like in the HF dump.
    text = re.sub(r"\s*\n\s*:\s+", ": ", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_markdown_inline(text: str) -> str:
    text = _MD_IMAGE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_REF_LINK.sub(r"\1", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<![\w*])[*_](?!\s)(.+?)(?<!\s)[*_](?![\w*])", r"\1", text)
    text = text.replace("`", "")
    return text


def normalise_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_BULLET = re.compile(r"^\s*(?:[-*+•·>]+|\(?\d{1,2}[.)])\s+")
# A line ending in one of these is a sentence that continues on the next line (flattened <a>/<strong>).
_DANGLING = {"the", "a", "an", "of", "to", "like", "with", "and", "or", "for", "in", "on", "at", "by", "from", "as",
             "is", "are", "was", "our", "their", "its", "using", "called", "named", "via", "including", "that", "which"}


def to_prose(text: str, *, drop_urls: bool = True) -> str:
    """Section body -> single-line prose suitable for the pitch (no markdown, bullets, URLs or emoji).

    Lines are joined with spaces. A full stop is inserted only where two real sentences would otherwise
    run together (bullet items, or a complete line followed by a capitalised line) - NOT after fragments
    such as "systems like" / "MELD/PELD" / ", which ..." that come from flattened inline links.
    """
    text = strip_markdown_inline(text)
    text = _HTML_TAG.sub(" ", text)
    if drop_urls:
        text = _URL.sub("", text)
    items: list[tuple[str, bool]] = []  # (line, was_bullet)
    for raw_line in text.split("\n"):
        line = _MD_HEADING_PREFIX.sub("", raw_line)
        was_bullet = bool(_BULLET.match(line))
        line = normalise_ws(strip_symbols(_BULLET.sub("", line)))
        if line:
            items.append((line, was_bullet))
    out = ""
    for i, (line, was_bullet) in enumerate(items):
        if out and out[-1] not in ".!?:;,…":
            prev, prev_bullet = items[i - 1]
            prev_words = prev.split()
            complete_prev = len(prev_words) >= 4 and prev_words[-1].lower().strip("\"')") not in _DANGLING
            starts_sentence = line[0].isupper() and len(line.split()) >= 3
            if prev_bullet or (complete_prev and starts_sentence):
                out += "."
        out = f"{out} {line}" if out else line
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    return re.sub(r"([.!?])\1{2,}", r"\1", out)


# --------------------------------------------------------------------------------------
# Headings and sections
# --------------------------------------------------------------------------------------
def _normalise_heading(line: str) -> str:
    s = strip_markdown_inline(line)
    s = strip_symbols(s)
    s = s.replace("’", "'").replace("‘", "'").replace("`", "'")
    s = _DECORATION.sub("", s)
    s = _LEADING_NUMBER.sub("", s)
    s = _DECORATION.sub("", s)
    return normalise_ws(s).lower()


def match_heading(line: str) -> str | None:
    """Canonical section key if `line` is (only) a known heading, else None."""
    stripped = line.strip()
    if not stripped or len(stripped) > 90:
        return None
    norm = _normalise_heading(stripped)
    if not norm or len(norm) > 80:
        return None
    for key, rx in _HEADING_RES:
        if rx.match(norm):
            return key
    return None


def _generic_heading(line: str) -> str | None:
    """Unknown but explicit headings ('## Business Model', '**Pricing**') -> 'other:<slug>'."""
    stripped = line.strip()
    explicit = bool(_MD_HEADING_PREFIX.match(stripped)) or bool(re.fullmatch(r"(\*\*|__).{2,70}\1:?", stripped))
    if not explicit:
        return None
    slug = re.sub(r"[^a-z0-9]+", "_", _normalise_heading(stripped)).strip("_")
    return f"other:{slug}" if slug else None


def parse_sections(raw: str | None) -> dict[str, str]:
    """Split a write-up into canonical sections.

    Keys: inspiration, what_it_does, how_it_works, how_we_built_it, challenges, accomplishments,
    what_we_learned, whats_next, problem, built_with, try_it_out, preamble (text before the first heading)
    and other:<slug> for explicit markdown/bold headings we do not know. Empty sections are dropped and
    repeated headings are concatenated, so callers can rely on every value being non-empty text.
    """
    text = clean_text(raw)
    sections: dict[str, list[str]] = {}
    current = "preamble"
    for line in text.split("\n"):
        key = match_heading(line)
        body_on_same_line = None
        if key is None:
            m = _INLINE_HEADING.match(line.strip())
            if m and (k2 := match_heading(m.group("h"))) and k2 not in ("built_with", "try_it_out"):
                key, body_on_same_line = k2, m.group("body")
        if key is None:
            key = _generic_heading(line)
        if key is not None:
            current = key
            sections.setdefault(current, [])
            if body_on_same_line:
                sections[current].append(body_on_same_line)
            continue
        sections.setdefault(current, []).append(line)
    out: dict[str, str] = {}
    for key, lines in sections.items():
        body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        if body:
            out[key] = body
    return out


def _looks_like_caption(paragraph: str) -> bool:
    """Gallery captions / stray labels that precede real prose: short, no sentence punctuation."""
    p = paragraph.strip()
    if _URL.fullmatch(p):
        return True
    return len(p) < 60 and not re.search(r"[.!?]\s*$", p) and len(p.split()) <= 8


def first_paragraphs(text: str, *, max_chars: int = PITCH_CAP, allow_captions: bool = False) -> str:
    """Fallback body when no usable heading exists: the first real paragraphs, leading captions skipped.

    Returns "" when everything looks like a caption, unless `allow_captions` (the last resort) is set.
    """
    paragraphs = [p for p in re.split(r"\n\s*\n|\n(?=\S)", text) if p.strip()]
    picked: list[str] = []
    total = 0
    for p in paragraphs:
        if match_heading(p) or _generic_heading(p):
            continue
        if not picked and _looks_like_caption(p):
            continue
        picked.append(p.strip())
        total += len(p)
        if total >= max_chars:
            break
    if not picked and allow_captions:  # better a weak pitch than none
        picked = [p.strip() for p in paragraphs if not match_heading(p)][:6]
    return "\n".join(picked)


def truncate_at_sentence(text: str, cap: int = PITCH_CAP) -> str:
    """Cap at `cap` chars, preferring the last sentence end; never returns more than `cap` chars."""
    if len(text) <= cap:
        return text
    window = text[:cap]
    ends = [m.end() for m in _SENTENCE_END.finditer(window)]
    if ends and ends[-1] >= int(cap * 0.5):
        return window[: ends[-1]].rstrip()
    cut = window.rfind(" ")
    return (window[:cut] if cut > cap * 0.5 else window[: cap - 1]).rstrip(" ,;:-") + "…"


def build_pitch(
    title: str | None,
    tagline: str | None,
    description: str | None,
    *,
    sections: dict[str, str] | None = None,
    cap: int = PITCH_CAP,
) -> str:
    """pitch = title + tagline + "What it does" (fallbacks when the heading is missing), <= `cap` chars.

    The pitch is the one field we search (BM25), rerank against, run significant_text on and embed.
    A thin "What it does" is topped up from the next-best sections until the body reaches ~300 chars, so
    fewer real projects are flagged `too_short` just because they wrote one sentence under that heading.
    """
    title_c = normalise_ws(strip_symbols(strip_markdown_inline(_html.unescape(title or ""))))
    tagline_c = to_prose(_html.unescape(tagline or ""))
    if sections is None:
        sections = parse_sections(description)

    def _without_title_lines(chunk: str) -> str:
        # Sub-headings that just repeat the project name ("🌐 DevSpot") add nothing to the pitch.
        keep = [ln for ln in chunk.split("\n") if _normalise_heading(ln) != title_c.lower() or not title_c]
        return "\n".join(keep)

    body_parts: list[str] = []
    body_len = 0
    for key in _PITCH_FALLBACK_ORDER:
        chunk = sections.get(key)
        if not chunk:
            continue
        chunk = _without_title_lines(chunk)
        prose = to_prose(first_paragraphs(chunk) if key == "preamble" else chunk)
        if len(prose) < 25:
            continue
        body_parts.append(prose)
        body_len += len(prose)
        if body_len >= 300:
            break
    if not body_parts:  # nothing structured at all: opening prose of the whole write-up, captions allowed
        prose = to_prose(first_paragraphs(clean_text(description), allow_captions=True))
        if prose:
            body_parts.append(prose)
    parts: list[str] = [title_c] if title_c else []
    if tagline_c and tagline_c.lower() != title_c.lower():
        parts.append(tagline_c)
    for prose in body_parts:
        low = prose.lower()
        if any(low == p.lower() for p in parts):
            continue
        if tagline_c and tagline_c in parts and low.startswith(tagline_c.lower()):
            parts.remove(tagline_c)  # the body repeats the tagline verbatim: keep one copy
        parts.append(prose)
    joined = ""
    for part in parts:
        if joined and joined[-1] not in ".!?:…":
            joined += "."
        joined = f"{joined} {part}".strip()
    return truncate_at_sentence(normalise_ws(joined), cap)


# --------------------------------------------------------------------------------------
# Tech extraction
# --------------------------------------------------------------------------------------
# alias -> canonical Devpost-style tag. Multi-word and punctuated names first (matched as phrases).
_TECH_ALIASES: dict[str, str] = {
    "next.js": "next.js", "nextjs": "next.js", "node.js": "node.js", "nodejs": "node.js", "react native": "react-native",
    "react.js": "react", "reactjs": "react", "react": "react", "vue.js": "vue", "vuejs": "vue", "vue": "vue",
    "angular": "angular", "svelte": "svelte", "tailwind": "tailwindcss", "tailwindcss": "tailwindcss", "bootstrap": "bootstrap",
    "express.js": "express.js", "express": "express.js", "flask": "flask", "django": "django", "fastapi": "fastapi",
    "spring boot": "spring-boot", "ruby on rails": "ruby-on-rails", "rails": "ruby-on-rails", "laravel": "laravel",
    "python": "python", "javascript": "javascript", "typescript": "typescript", "java": "java", "kotlin": "kotlin",
    "swift": "swift", "swiftui": "swiftui", "c++": "c++", "c#": "c#", "golang": "go", "rust": "rust", "php": "php", "ruby": "ruby",
    "html": "html", "css": "css", "sql": "sql", "solidity": "solidity", "dart": "dart", "flutter": "flutter", "matlab": "matlab",
    "openai": "openai", "gpt-4": "openai", "gpt-4o": "openai", "gpt-3": "openai", "gpt-3.5": "openai", "chatgpt": "chatgpt",
    "gemini": "gemini", "claude": "claude", "anthropic": "anthropic", "llama": "llama", "mistral": "mistral", "cohere": "cohere",
    "groq": "groq", "ollama": "ollama", "hugging face": "huggingface", "huggingface": "huggingface", "whisper": "whisper",
    "langchain": "langchain", "llamaindex": "llamaindex", "pinecone": "pinecone", "chromadb": "chromadb", "chroma": "chromadb",
    "weaviate": "weaviate", "qdrant": "qdrant", "elasticsearch": "elasticsearch", "tensorflow": "tensorflow", "pytorch": "pytorch",
    "keras": "keras", "scikit-learn": "scikit-learn", "sklearn": "scikit-learn", "opencv": "opencv", "mediapipe": "mediapipe",
    "yolo": "yolo", "pandas": "pandas", "numpy": "numpy", "streamlit": "streamlit", "gradio": "gradio",
    "mongodb": "mongodb", "postgresql": "postgresql", "postgres": "postgresql", "mysql": "mysql", "sqlite": "sqlite",
    "redis": "redis", "firebase": "firebase", "firestore": "firebase", "supabase": "supabase", "graphql": "graphql",
    "aws": "amazon-web-services", "amazon web services": "amazon-web-services", "google cloud": "google-cloud", "gcp": "google-cloud",
    "azure": "azure", "docker": "docker", "kubernetes": "kubernetes", "vercel": "vercel", "heroku": "heroku", "netlify": "netlify",
    "cloudflare": "cloudflare", "twilio": "twilio", "stripe": "stripe", "auth0": "auth0", "figma": "figma", "unity": "unity",
    "unreal engine": "unreal-engine", "godot": "godot", "arduino": "arduino", "raspberry pi": "raspberry-pi", "esp32": "esp32",
    "ethereum": "ethereum", "web3": "web3", "solana": "solana", "selenium": "selenium", "beautifulsoup": "beautiful-soup",
    "beautiful soup": "beautiful-soup", "puppeteer": "puppeteer", "playwright": "playwright", "websockets": "websockets",
    "socket.io": "socket.io", "three.js": "three.js", "d3.js": "d3.js", "expo": "expo", "electron": "electron", "jupyter": "jupyter",
    "google maps": "google-maps", "mapbox": "mapbox", "spotify api": "spotify", "gmail api": "gmail", "chrome extension": "chrome",
    "livekit": "livekit", "elevenlabs": "elevenlabs", "deepgram": "deepgram", "assemblyai": "assemblyai", "replicate": "replicate",
}
_TECH_RX = re.compile(
    r"(?<![\w+#.-])(" + "|".join(sorted((re.escape(a) for a in _TECH_ALIASES), key=len, reverse=True)) + r")(?![\w+#-])",
    re.I,
)


def normalise_tech(values: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or []:
        t = normalise_ws(strip_symbols(str(v))).lower().strip(" ,;.")
        if t and len(t) <= 60 and t not in out:
            out.append(t)
    return out


def extract_tech(
    built_with: Iterable[str] | None,
    *,
    sections: dict[str, str] | None = None,
    description: str | None = None,
) -> tuple[list[str], str | None]:
    """Return (tech, provenance): 'source' from the structured list, 'normalized' when parsed out of a
    "Built With" text block, 'imputed' when mined from "How we built it" prose. (None when nothing found.)"""
    tech = normalise_tech(built_with)
    if tech:
        return tech, "source"
    if sections is None:
        sections = parse_sections(description)
    block = sections.get("built_with")
    if block:
        tech = normalise_tech(re.split(r"[\n,]+", block))
        if tech:
            return tech, "normalized"
    prose = sections.get("how_we_built_it") or ""
    found: list[str] = []
    for m in _TECH_RX.finditer(prose):
        canon = _TECH_ALIASES[m.group(1).lower()]
        if canon not in found:
            found.append(canon)
    return (found, "imputed") if found else ([], None)


# --------------------------------------------------------------------------------------
# Language guess (client-side fallback when lang_ident_model_1 is unavailable on the cluster)
# --------------------------------------------------------------------------------------
_STOPWORDS = {
    # Deliberately without tokens that are also common English words ("as", "do", "a", "no", "me", "in", "on" ...):
    # an English sentence full of "as ... as" must never vote for Portuguese.
    "en": {"the", "and", "to", "of", "that", "is", "for", "with", "we", "our", "this", "it", "in", "you", "are", "on", "your", "can"},
    "es": {"el", "los", "las", "que", "y", "para", "con", "una", "es", "por", "nuestra", "nuestro", "del", "más", "como", "sus"},
    "fr": {"le", "les", "des", "et", "pour", "avec", "une", "est", "nous", "notre", "qui", "dans", "du", "sur", "aux", "vous"},
    "de": {"der", "die", "das", "und", "ist", "für", "mit", "wir", "ein", "eine", "nicht", "zu", "den", "von", "unsere", "auf"},
    "pt": {"os", "que", "em", "para", "com", "uma", "um", "é", "nós", "nosso", "não", "da", "por", "mais", "como", "sua"},
    "it": {"il", "gli", "di", "che", "per", "con", "una", "è", "noi", "nostro", "non", "del", "della", "più", "sono", "alla"},
}
_SCRIPTS = (("zh", "CJK UNIFIED"), ("ja", "HIRAGANA"), ("ja", "KATAKANA"), ("ko", "HANGUL"), ("ru", "CYRILLIC"),
            ("ar", "ARABIC"), ("hi", "DEVANAGARI"), ("he", "HEBREW"), ("th", "THAI"), ("el", "GREEK"))


def guess_lang(text: str | None) -> str:
    """Cheap language guess: script detection, then stop-word voting. 'und' when unsure (short text)."""
    sample = (text or "")[:1200]
    letters = [c for c in sample if c.isalpha()]
    if len(letters) < 20:
        return "und"
    counts: dict[str, int] = {}
    for c in letters:
        if ord(c) < 0x250:
            continue
        name = unicodedata.name(c, "")
        for code, marker in _SCRIPTS:
            if marker in name:
                counts[code] = counts.get(code, 0) + 1
                break
    if counts and sum(counts.values()) / len(letters) >= 0.3:
        return "ja" if counts.get("ja") else max(counts, key=counts.get)
    words = re.findall(r"[^\W\d_]+", sample.lower())
    votes = {lang: sum(1 for w in words if w in sw) for lang, sw in _STOPWORDS.items()}
    en = votes.pop("en")
    best = max(votes, key=votes.get)
    if en >= 3 and en >= votes[best]:
        return "en"
    # Non-English needs strong evidence (a wrong `non_english` flag hides a document from search):
    # >= 5 stop-word hits and twice the English votes. Spanish-vs-Portuguese ties do not matter here.
    if votes[best] >= 5 and votes[best] >= 2 * en:
        return best
    return "und"
