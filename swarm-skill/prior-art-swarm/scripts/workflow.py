"""Executable SwarmFlow workflow for prior-art-swarm.

Standalone Python workflow module: META + JSON Schema literals +
explicit swarmflow primitive imports + async def run(args).

Topology (the same one workflow.md describes):
  Plan        facets + dynamic team formation (skipped scouts carry a reason)
  Scout       one isolated scout per source slice, in parallel; one broadened retry on failure
  Resolve     listings merged into entities: blocking, URL rule, union-find and field fusion run
              in code; only ambiguous pairs go to the resolver
  Debate      critic vs advocate rounds; the critic's follow-up requests and a split jury both
              send scouts back out; blind samplers probe how predictable the idea is
  Verify      the veto: a claim survives only if its quote is found in the evidence text
              (checked in Python, never by a model) and its citation is not judged fake
  Synthesize  scores and confidence computed in code; abstains instead of guessing
  Coach       facet-swap mutations, each re-scored by re-running retrieval
  Act         actions are proposed only; outside-world actions need an explicit user confirmation

Args: a JSON object (or a bare idea string). Keys: idea (required), url, domain_hint,
available_tools, sources, jury_models, prior_models, critic_model, advocate_model,
verifier_model, coach_model, debate_rounds, max_calls, timeouts {scout, role, confirm},
reliability_priors, ask_confirmation.
"""
import json
import math
import re
from string import Template

from swarmflow import agent, budget, compact, human, log, parallel, phase

# Each phase carries `detail` (what the Swarm Skill validator reads) and `description`
# (what the SwarmFlow engine shows in its phase plan). Both hold the same sentence.
META = {
    "name": "prior-art-swarm",
    "description": "Evidence-backed originality assessment: parallel scouts, entity resolution, a critic/advocate debate judged by a model jury, a verifier veto enforced in code, abstaining synthesis and re-scored coaching.",
    "whenToUse": "Reuse when someone wants to know whether an idea, product, feature or research direction has already been done, with verified citations, and how to make it more distinctive. Pass args as JSON with at least an `idea` string.",
    "phases": [
        {
            "title": "Plan",
            "detail": "Decompose the idea into facets and form the scout team by domain and by which sources are reachable.",
            "description": "Decompose the idea into facets and form the scout team by domain and by which sources are reachable.",
        },
        {
            "title": "Scout",
            "detail": "One isolated scout per source slice searches in parallel; a failed slice gets one broadened retry.",
            "description": "One isolated scout per source slice searches in parallel; a failed slice gets one broadened retry.",
        },
        {
            "title": "Resolve",
            "detail": "Merge listings of the same work into entities, fuse fields with source-reliability priors, surface conflicts and imputed fields.",
            "description": "Merge listings of the same work into entities, fuse fields with source-reliability priors, surface conflicts and imputed fields.",
        },
        {
            "title": "Debate",
            "detail": "Critic and advocate argue over quoted evidence, scouts are sent back out on request, a model jury scores facet overlap and a split jury triggers one targeted re-query.",
            "description": "Critic and advocate argue over quoted evidence, scouts are sent back out on request, a model jury scores facet overlap and a split jury triggers one targeted re-query.",
        },
        {
            "title": "Verify",
            "detail": "Veto gate: quotes are checked against the evidence text in code, then citations are checked independently; struck claims never reach the synthesizer.",
            "description": "Veto gate: quotes are checked against the evidence text in code, then citations are checked independently; struck claims never reach the synthesizer.",
        },
        {
            "title": "Synthesize",
            "detail": "Compute per-axis scores and confidence, then write the verdict from surviving claims only, or abstain with the reason.",
            "description": "Compute per-axis scores and confidence, then write the verdict from surviving claims only, or abstain with the reason.",
        },
        {
            "title": "Coach",
            "detail": "Propose facet-swap mutations grounded in whitespace terms and re-score each one by re-running retrieval.",
            "description": "Propose facet-swap mutations grounded in whitespace terms and re-score each one by re-running retrieval.",
        },
        {
            "title": "Act",
            "detail": "Propose follow-up actions; anything that writes outside the team waits for an explicit user confirmation.",
            "description": "Propose follow-up actions; anything that writes outside the team waits for an explicit user confirmation.",
        },
    ],
}

# ---------------------------------------------------------------------------
# Limits. The numbers mirror bind.md; change them there first.
# ---------------------------------------------------------------------------
FACET_KEYS = ("purpose", "mechanism", "audience", "data", "twist")
JURY_FACETS = ("purpose", "mechanism")
MAX_MODEL_CALLS = 70            # agent dispatches per run; optional stages are dropped first
MIN_MODEL_CALLS = 30            # the mandatory path (22 dispatches at most) always fits under the cap
KEEP_FOR_VERDICT = 2            # dispatches held back for the citation check and the synthesizer
TOKEN_RESERVE = 20000           # only meaningful when the run declares a token ceiling
MAX_SLICES = 6                  # max_parallel_teammates
RECORDS_PER_SCOUT = 8
MAX_RECORDS = 60
MAX_DEBATE_ROUNDS = 2
MAX_FOLLOWUPS = 2               # critic follow-up searches per run
MAX_TIEBREAKS = 1               # split-jury re-queries per run
MAX_CLAIMS_PER_TURN = 8
MAX_JURY_ENTITIES = 4
MAX_JURORS = 4
MAX_SAMPLERS = 4
MAX_MUTATIONS = 3
MAX_CITATION_CHECKS = 8
MAX_PAIRS_PER_CALL = 16
MAX_ADJUDICATION_PAIRS = 24     # above this the resolver stage degrades to rules only
NAME_BLOCK_THRESHOLD = 0.6      # trigram similarity that makes two titles a candidate pair
SPLIT_STD = 0.25                # jury disagreement that counts as a split
COLLISION = 0.80                # rated similarity at which a blind proposal is "the same idea"
MIN_QUOTE_WORDS = 4
MIN_DENSE_QUOTE_CHARS = 8       # scripts without word spacing
MIN_IDEA_WORDS = 8
MIN_IDEA_CHARS = 40
MAX_IDEA_CHARS = 6000
MIN_COVERAGE = 0.5
MIN_CONFIDENCE = 0.45
AXIS_WEIGHTS = {"crowding": 0.45, "facet_rarity": 0.35, "llm_predictability": 0.20}
ROLE_IDS = ("scout", "resolver", "critic", "advocate", "judge", "verifier", "synthesizer", "coach")

# Source slices. Reuse lever: pass your own list in args["sources"]; nothing else changes.
DEFAULT_SOURCES = [
    {
        "id": "corpus",
        "label": "indexed prior-work corpus",
        "needs": "elastic-agent-builder-mcp",
        "queries": "semantic",
        "guidance": "Use the hybrid prior-art search tools exposed over MCP (semantic plus keyword, reranked). Report the tool's relevance score as similarity and fill corpus_stats when the tools expose them.",
    },
    {
        "id": "code",
        "label": "public code hosts",
        "needs": "web_search",
        "queries": "keyword",
        "guidance": "Search public repositories (names, READMEs, topics).",
    },
    {
        "id": "launches",
        "label": "product and startup launches",
        "needs": "web_search",
        "queries": "keyword",
        "guidance": "Search launch listings, startup directories and launch discussions.",
    },
    {
        "id": "events",
        "label": "hackathon and competition galleries",
        "needs": "web_search",
        "queries": "keyword",
        "guidance": "Search project pages of hackathons and competitions. Never fetch a search page that sits behind a bot challenge.",
    },
    {
        "id": "papers",
        "label": "scholarly papers and preprints",
        "needs": "web_search",
        "queries": "semantic",
        "only_for": ["research"],
        "guidance": "Search preprint servers and paper indexes.",
    },
    {
        "id": "patents",
        "label": "patent publications",
        "needs": "web_search",
        "queries": "semantic",
        "only_for": ["patent"],
        "guidance": "Search public patent databases. This is a pre-screen, not a legal search.",
    },
    {
        "id": "web",
        "label": "general web",
        "needs": "web_search",
        "queries": "keyword",
        "guidance": "Search the open web for products, articles and announcements the other slices would miss.",
    },
]

# How much each slice is trusted for each fused field (0..1). Conflicts are resolved by these
# priors AND shown to the user; they are never averaged away. Override via args["reliability_priors"].
RELIABILITY_PRIORS = {
    "year": {"code": 0.9, "papers": 0.9, "patents": 0.9, "launches": 0.8, "corpus": 0.6, "events": 0.6, "web": 0.4},
    "state": {"code": 0.8, "launches": 0.7, "patents": 0.7, "web": 0.6, "corpus": 0.5, "events": 0.5, "papers": 0.5},
}
RELIABILITY_RULES = {
    "year": "first-party timestamps outrank listing years",
    "state": "observed activity outranks self-reported listing copy",
}

# ---------------------------------------------------------------------------
# JSON Schemas for structured agent outputs. Deliberately permissive: no strictness
# keywords, so a slightly off answer degrades into a fallback instead of a lost call.
# ---------------------------------------------------------------------------
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "facets": {
            "type": "object",
            "properties": {
                "purpose": {"type": "string"},
                "mechanism": {"type": "string"},
                "audience": {"type": "string"},
                "data": {"type": "string"},
                "twist": {"type": "string"},
            },
        },
        "idea_kind": {"type": "string"},
        "domain": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "semantic_queries": {"type": "array", "items": {"type": "string"}},
        "keyword_queries": {"type": "array", "items": {"type": "string"}},
        "slices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"slice_id": {"type": "string"}, "relevant": {"type": "boolean"}, "why": {"type": "string"}},
            },
        },
    },
}

SCOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "note": {"type": "string"},
        "queries_run": {"type": "array", "items": {"type": "string"}},
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "year": {"type": "string"},
                    "state": {"type": "string"},
                    "text": {"type": "string"},
                    "similarity": {"type": "number"},
                },
            },
        },
        "corpus_stats": {
            "type": "object",
            "properties": {
                "whitespace_terms": {"type": "array", "items": {"type": "string"}},
                "cliche_terms": {"type": "array", "items": {"type": "string"}},
                "facet_counts": {"type": "object"},
                "corpus_size": {"type": "number"},
            },
        },
    },
}

RESOLVER_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"pair": {"type": "integer"}, "verdict": {"type": "string"}, "rationale": {"type": "string"}},
            },
        },
    },
}

CRITIC_SCHEMA = {
    "type": "object",
    "properties": {
        "stance": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "record_id": {"type": "string"},
                    "text": {"type": "string"},
                    "quote": {"type": "string"},
                    "facets": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "rebuttals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"claim_id": {"type": "string"}, "action": {"type": "string"}, "text": {"type": "string"}},
            },
        },
        "followups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "facet": {"type": "string"},
                    "query": {"type": "string"},
                    "slice_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}

ADVOCATE_SCHEMA = {
    "type": "object",
    "properties": {
        "responses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "response": {"type": "string"},
                    "facet": {"type": "string"},
                    "text": {"type": "string"},
                },
            },
        },
        "distinctions": {
            "type": "array",
            "items": {"type": "object", "properties": {"text": {"type": "string"}, "facet": {"type": "string"}}},
        },
    },
}

BALLOT_SCHEMA = {
    "type": "object",
    "properties": {
        "overlaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "purpose": {"type": "number"},
                    "mechanism": {"type": "number"},
                    "why": {"type": "string"},
                },
            },
        },
    },
}

SAMPLER_SCHEMA = {"type": "object", "properties": {"ideas": {"type": "array", "items": {"type": "string"}}}}

PROBE_SCHEMA = {
    "type": "object",
    "properties": {
        "ratings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"index": {"type": "integer"}, "similarity": {"type": "number"}, "why": {"type": "string"}},
            },
        },
    },
}

CITATION_SCHEMA = {
    "type": "object",
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "citation_status": {"type": "string"},
                    "quote_on_page": {"type": "string"},
                    "detail": {"type": "string"},
                },
            },
        },
    },
}

SYNTH_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict_md": {"type": "string"},
        "crowded": {"type": "array", "items": {"type": "string"}},
        "different": {"type": "array", "items": {"type": "string"}},
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
}

COACH_SCHEMA = {
    "type": "object",
    "properties": {
        "mutations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "facet": {"type": "string"},
                    "from_value": {"type": "string"},
                    "to_value": {"type": "string"},
                    "rationale": {"type": "string"},
                    "pitch": {"type": "string"},
                    "grounded_in": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}

CONFIRM_SCHEMA = {
    "type": "object",
    "properties": {"approved": {"type": "array", "items": {"type": "string"}}, "note": {"type": "string"}},
}


# ---------------------------------------------------------------------------
# Resilient helpers
# ---------------------------------------------------------------------------

def extract_json(text, fallback=None):
    """Extract the first JSON object from text (LLM output may have prose).

    Handles three cases:
    1. Already a dict - return as-is (agent() schema validation succeeded).
    2. Pure JSON string - parse directly.
    3. JSON embedded in prose - scan for the outermost braces and parse.
    Falls back to *fallback* (default {}) if nothing parses.
    """
    fallback_value = {} if fallback is None else fallback
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return fallback_value
    text = text.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else fallback_value
    except (json.JSONDecodeError, ValueError):
        pass
    depth = 0
    start = None
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    parsed = json.loads(text[start:i + 1])
                    return parsed if isinstance(parsed, dict) else fallback_value
                except (json.JSONDecodeError, ValueError):
                    start = None
    return fallback_value


def safe_get(obj, key, default=""):
    """Safely get a key from an agent result as a stripped string, handling None/non-dict."""
    if isinstance(obj, dict):
        value = obj.get(key, default)
        return str(default if value is None else value).strip()
    return str(default)


def parse_args(args):
    """Normalize args to dict. Swarmflow may pass a JSON string, a dict, or a bare idea string."""
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        text = args.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"idea": text}
        return parsed if isinstance(parsed, dict) else {"idea": text}
    return {}


def as_list(value):
    return value if isinstance(value, list) else []


def as_dict(value):
    return value if isinstance(value, dict) else {}


def clip(value, limit):
    return str(value or "").strip()[:limit]


def bounded_int(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def to_unit(value, default=0.0):
    """Coerce a model-supplied number into a float between 0 and 1."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:
        return default
    return max(0.0, min(1.0, number))


def mean_of(values):
    return sum(values) / len(values) if values else 0.0


def spread_of(values):
    """Population standard deviation (0 for fewer than two values)."""
    if len(values) < 2:
        return 0.0
    centre = mean_of(values)
    return math.sqrt(sum((v - centre) ** 2 for v in values) / len(values))


def string_list(value, limit, width):
    return [clip(item, width) for item in as_list(value) if clip(item, width)][:limit]


# ---------------------------------------------------------------------------
# Deterministic text checks (no model involved)
# ---------------------------------------------------------------------------
ELLIPSIS_RE = re.compile(r"\[\s*\.\.\.\s*\]|\(\s*\.\.\.\s*\)|\.{3,}|…")
URL_RE = re.compile(r"https?://[^\s)\]\"']+")
YEAR_RE = re.compile(r"\b(19[7-9]\d|20[0-4]\d)\b")


def words_of(text):
    """Lowercase word sequence; punctuation, markup remnants and whitespace are separators."""
    cleaned = str(text or "").casefold().replace("'", "").replace("’", "")
    return "".join(ch if ch.isalnum() else " " for ch in cleaned).split()


def quote_in_text(quote, text):
    """The receipt check behind the veto. Returns (found, detail).

    The quote (each part of it, when it contains an elision) must appear as the same words in
    the same order in the source text, after case, punctuation and whitespace are normalized.
    Quotes under four words prove nothing and are refused. Text in scripts without word
    spacing is compared with separators removed.
    """
    pieces = [words_of(part) for part in ELLIPSIS_RE.split(str(quote or ""))]
    pieces = [piece for piece in pieces if piece]
    dense_quote = "".join("".join(piece) for piece in pieces)
    if not dense_quote:
        return False, "the claim carries no quote"
    wide = sum(1 for ch in dense_quote if ord(ch) > 0x2E7F)
    unspaced = wide * 2 > len(dense_quote)
    if unspaced:
        if len(dense_quote) < MIN_DENSE_QUOTE_CHARS:
            return False, "quote too short to verify"
    elif sum(len(piece) for piece in pieces) < MIN_QUOTE_WORDS:
        return False, f"quote too short to verify (needs at least {MIN_QUOTE_WORDS} words)"
    source_words = words_of(text)
    if not source_words:
        return False, "the evidence text is empty"
    if unspaced:
        dense_source = "".join(source_words)
        found = all("".join(piece) in dense_source for piece in pieces)
    else:
        haystack = " " + " ".join(source_words) + " "
        found = all((" " + " ".join(piece) + " ") in haystack for piece in pieces)
    if found:
        return True, "quote found verbatim in the evidence text"
    return False, "quote does not appear in the evidence text"


def normalize_url(url):
    cleaned = str(url or "").strip().lower()
    cleaned = re.sub(r"^[a-z]+://", "", cleaned)
    cleaned = re.sub(r"^www\.", "", cleaned)
    return cleaned.split("#")[0].split("?")[0].rstrip("/.,;")


def links_of(url, text):
    """Normalized URLs a listing points at (its own plus any it mentions). Bare hosts are ignored."""
    found = {normalize_url(url)} | {normalize_url(hit) for hit in URL_RE.findall(str(text or ""))}
    return sorted(link for link in found if "/" in link)


def trigrams(text):
    dense = "".join(words_of(text))
    if len(dense) < 3:
        return {dense} if dense else set()
    return {dense[i:i + 3] for i in range(len(dense) - 2)}


def name_similarity(left, right):
    a, b = trigrams(left), trigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# Settings, run state, budget
# ---------------------------------------------------------------------------

def read_settings(args):
    timeouts = as_dict(args.get("timeouts"))
    idea = str(args.get("idea") or args.get("idea_text") or args.get("input") or "").strip()
    tools = string_list(args.get("available_tools"), 20, 80) or ["web_search"]
    priors = {field: dict(table) for field, table in RELIABILITY_PRIORS.items()}
    for field, table in as_dict(args.get("reliability_priors")).items():
        priors.setdefault(field, {}).update({k: to_unit(v, 0.5) for k, v in as_dict(table).items()})
    return {
        "idea_full_length": len(idea),
        "idea": idea[:MAX_IDEA_CHARS],
        "url": clip(args.get("url"), 400),
        "domain_hint": clip(args.get("domain_hint"), 80),
        "available_tools": tools,
        "sources": [s for s in as_list(args.get("sources")) if isinstance(s, dict) and s.get("id")] or DEFAULT_SOURCES,
        "jury_models": string_list(args.get("jury_models"), MAX_JURORS, 120),
        "prior_models": string_list(args.get("prior_models"), MAX_SAMPLERS, 120),
        "critic_model": clip(args.get("critic_model"), 120) or None,
        "advocate_model": clip(args.get("advocate_model"), 120) or None,
        "verifier_model": clip(args.get("verifier_model"), 120) or None,
        "coach_model": clip(args.get("coach_model"), 120) or None,
        "debate_rounds": bounded_int(args.get("debate_rounds"), 1, 1, MAX_DEBATE_ROUNDS),
        "max_calls": bounded_int(args.get("max_calls"), MAX_MODEL_CALLS, MIN_MODEL_CALLS, MAX_MODEL_CALLS),
        "scout_timeout": bounded_int(timeouts.get("scout"), 120, 20, 900),
        "role_timeout": bounded_int(timeouts.get("role"), 75, 20, 900),
        "confirm_timeout": bounded_int(timeouts.get("confirm"), 300, 10, 3600),
        "priors": priors,
        "ask_confirmation": bool(args.get("ask_confirmation")),
    }


def new_state():
    return {
        "calls": 0,
        "plan": {},
        "staffed": [],
        "skipped": [],
        "sources": {},
        "records": [],
        "decisions": {},
        "entities": [],
        "record_entity": {},
        "corpus_stats": {},
        "claims": [],
        "distinctions": [],
        "requeries": [],
        "jury": [],
        "jury_note": "",
        "probe": {},
        "rounds_run": 0,
        "followups_used": 0,
        "tiebreaks_used": 0,
        "missing_roles": [],
        "degradations": [],
    }


def call_options(timeout, model):
    """Tuning knobs for one dispatch. The engine drops None values, so no model means the host default."""
    return {"timeout": timeout, "model": model}


def tokens_low():
    """True only when the run declares a token ceiling and less than the reserve is left."""
    return bool(budget.total and budget.remaining() < TOKEN_RESERVE)


def can_spend(state, settings, count, keep=0):
    """Gate for OPTIONAL work: refuse when the call cap (minus `keep` dispatches held back for
    later mandatory stages) or the token reserve would be breached."""
    return state["calls"] + count + keep <= settings["max_calls"] and not tokens_low()


def charge(state, count):
    state["calls"] += count


def degrade(state, message):
    """Every degradation is recorded and logged. Nothing fails silently."""
    if message not in state["degradations"]:
        state["degradations"].append(message)
    log("DEGRADED: " + message)


def mark_missing(state, role_id, why):
    if role_id not in state["missing_roles"]:
        state["missing_roles"].append(role_id)
    degrade(state, f"[ROLE MISSING - {role_id}] {why}")


def input_problem(settings):
    """Under-scale gate: refuse to staff a team for an idea that cannot be decomposed."""
    idea = settings["idea"]
    if not idea:
        return "No idea text was provided. Pass args as JSON with an `idea` string."
    if len(idea.split()) < MIN_IDEA_WORDS and len(idea) < MIN_IDEA_CHARS:
        return "The idea text is too short to decompose. Say what it does, for whom, and how it works."
    return ""


# ---------------------------------------------------------------------------
# Plan + dynamic team formation
# ---------------------------------------------------------------------------

def read_plan(raw, settings):
    """Validate the planner's output semantically; a plan without purpose and mechanism is unusable."""
    facets_in = as_dict(raw.get("facets"))
    facets = {key: clip(facets_in.get(key), 160) for key in FACET_KEYS}
    idea = settings["idea"]
    return {
        "facets": facets,
        "decomposed": bool(facets["purpose"] and facets["mechanism"]),
        "idea_kind": safe_get(raw, "idea_kind", "other").lower() or "other",
        "domain": clip(raw.get("domain"), 60) or settings["domain_hint"] or "project",
        "keywords": string_list(raw.get("keywords"), 6, 40),
        "semantic_queries": string_list(raw.get("semantic_queries"), 3, 300) or [idea[:300]],
        "keyword_queries": string_list(raw.get("keyword_queries"), 3, 80) or [idea[:80]],
        "slice_notes": {
            safe_get(entry, "slice_id"): entry
            for entry in as_list(raw.get("slices"))
            if isinstance(entry, dict)
        },
    }


def form_team(plan, settings):
    """Who joins depends on the idea (relevance) and on what is reachable right now (tools).

    Returns (staffed, skipped); every skipped slice carries the reason it was skipped.
    """
    staffed, skipped = [], []
    hint = (plan["idea_kind"] + " " + settings["domain_hint"]).lower()
    for source in settings["sources"]:
        slice_id = str(source.get("id"))
        note = as_dict(plan["slice_notes"].get(slice_id))
        gated = as_list(source.get("only_for"))
        needs = str(source.get("needs") or "web_search")
        if needs not in settings["available_tools"]:
            skipped.append({"slice_id": slice_id, "counts": True,
                            "why": f"tool `{needs}` is not available (pre-flight)"})
        elif gated and not any(word in hint for word in gated):
            skipped.append({"slice_id": slice_id, "counts": False,
                            "why": clip(note.get("why"), 160) or "not relevant to this kind of idea"})
        elif note.get("relevant") is False and not gated:
            skipped.append({"slice_id": slice_id, "counts": False,
                            "why": clip(note.get("why"), 160) or "the planner judged this slice irrelevant"})
        elif len(staffed) >= MAX_SLICES:
            skipped.append({"slice_id": slice_id, "counts": True,
                            "why": f"over the parallel cap of {MAX_SLICES} scouts"})
        else:
            staffed.append(source)
    return staffed, skipped


def scout_item(source, plan, settings, assignment, queries):
    """Everything one isolated scout is allowed to see."""
    return {
        "slice_id": str(source.get("id")),
        "label": clip(source.get("label"), 120),
        "guidance": clip(source.get("guidance"), 500) or "Search this source with the tools you have.",
        "assignment": assignment,
        "queries": [clip(q, 300) for q in queries if clip(q, 300)][:3],
        "idea": settings["idea"],
        "facets": plan["facets"],
    }


def initial_queries(source, plan):
    style = str(source.get("queries") or "keyword")
    return plan["semantic_queries"] if style == "semantic" else plan["keyword_queries"]


def broadened_queries(plan):
    """One broadened retry: fall back to the most specific keywords only."""
    terms = plan["keywords"][:3] or plan["keyword_queries"][:1]
    return [" ".join(terms)]


# ---------------------------------------------------------------------------
# Evidence store
# ---------------------------------------------------------------------------

def read_records(raw):
    """Usable records from one scout result (title plus verbatim text are mandatory)."""
    out = []
    for entry in as_list(as_dict(raw).get("records"))[:RECORDS_PER_SCOUT]:
        if not isinstance(entry, dict):
            continue
        title, text = clip(entry.get("title"), 200), clip(entry.get("text"), 1200)
        if title and text:
            out.append({
                "title": title,
                "url": clip(entry.get("url"), 400),
                "year": clip(entry.get("year"), 4),
                "state": safe_get(entry, "state", "unknown").lower() or "unknown",
                "text": text,
                "similarity": to_unit(entry.get("similarity")),
            })
    return out


def ingest_scout(state, item, raw, leg):
    """Store one scout's records. Returns (outcome, new_record_ids).

    outcome: ok | empty | blocked | failed. Fabrication guard: a record needs a title and a
    verbatim text excerpt; records repeating a known URL are dropped as duplicates.
    """
    slice_id = item["slice_id"]
    result = extract_json(raw, fallback={})
    status = safe_get(result, "status", "").lower()
    note = clip(result.get("note"), 240)
    if raw is None or not result:
        return "failed", [], "no usable answer (timeout or malformed output)"
    if status == "blocked":
        return "blocked", [], note or "the source blocked automated access"
    if status == "failed":
        return "failed", [], note or "the scout reported a failure"
    known = {normalize_url(r["url"]) for r in state["records"] if r["url"]}
    new_ids = []
    for entry in read_records(result):
        link = normalize_url(entry["url"])
        if link and link in known:
            continue
        if len(state["records"]) >= MAX_RECORDS:
            degrade(state, f"evidence store is full ({MAX_RECORDS} records); further records from {slice_id} were not kept")
            break
        known.add(link)
        entry.update({
            "id": f"r{len(state['records']) + 1}",
            "slice": slice_id,
            "leg": leg,
            "links": links_of(entry["url"], entry["text"]),
            "year_imputed": False,
        })
        if not entry["year"]:
            hit = YEAR_RE.search(entry["text"])
            if hit:  # imputation is allowed, but it is always marked
                entry["year"], entry["year_imputed"] = hit.group(1), True
        state["records"].append(entry)
        new_ids.append(entry["id"])
    stats = as_dict(result.get("corpus_stats"))
    if stats and not state["corpus_stats"]:
        state["corpus_stats"] = {
            "whitespace_terms": string_list(stats.get("whitespace_terms"), 12, 40),
            "cliche_terms": string_list(stats.get("cliche_terms"), 12, 40),
            "facet_counts": {k: v for k, v in as_dict(stats.get("facet_counts")).items() if k in FACET_KEYS},
            "source_slice": slice_id,
        }
    return ("ok" if new_ids else "empty"), new_ids, note


def bump_source(state, slice_id, n_records):
    """Records found on a back-edge (follow-up, tie-break) count toward their slice; its status is kept."""
    if slice_id in state["sources"]:
        state["sources"][slice_id]["n_records"] += n_records


def set_source(state, slice_id, status, n_records, note):
    previous = as_dict(state["sources"].get(slice_id))
    state["sources"][slice_id] = {
        "slice_id": slice_id,
        "status": status,
        "n_records": int(previous.get("n_records") or 0) + n_records,
        "note": note,
    }


# ---------------------------------------------------------------------------
# Resolution: blocking, rules, union-find and fusion in code; adjudication by the resolver
# ---------------------------------------------------------------------------

def plan_resolution(state):
    """Blocking plus the URL rule. Returns the pairs that still need the resolver's judgment."""
    records, decided, undecided = state["records"], state["decisions"], []
    for index, left in enumerate(records):
        for right in records[index + 1:]:
            key = left["id"] + "|" + right["id"]
            if key in decided:
                continue
            shared = sorted(set(left["links"]) & set(right["links"]))
            likeness = round(name_similarity(left["title"], right["title"]), 2)
            if shared:
                decided[key] = {"a": left["id"], "b": right["id"], "verdict": "same", "by": "rule",
                                "rationale": f"Both listings link to {shared[0]}.", "name_similarity": likeness}
            elif likeness >= NAME_BLOCK_THRESHOLD:
                undecided.append({"a": left["id"], "b": right["id"], "name_similarity": likeness})
    rules_only = len(undecided) > MAX_ADJUDICATION_PAIRS
    if rules_only:
        degrade(state, f"{len(undecided)} candidate pairs exceed the adjudication cap of {MAX_ADJUDICATION_PAIRS}: "
                       "resolution ran on rules only and the ambiguous pairs stay unmerged")
    pairs = [] if rules_only else undecided[:MAX_PAIRS_PER_CALL]
    for pair in undecided[len(pairs):]:
        decided[pair["a"] + "|" + pair["b"]] = dict(pair, verdict="insufficient_evidence", by="unadjudicated",
                                                     rationale="Not adjudicated; left unmerged.")
    return {"pairs": pairs, "rules_only": rules_only}


def finish_resolution(state, settings, resolution, raw):
    """Record the resolver's verdicts, then rebuild every entity from all decisions."""
    verdicts = {}
    for entry in as_list(extract_json(raw, fallback={}).get("verdicts")):
        if isinstance(entry, dict):
            verdict = safe_get(entry, "verdict", "").lower()
            if verdict in ("same", "different", "insufficient_evidence"):
                verdicts[bounded_int(entry.get("pair"), -1, -1, 10000)] = (verdict, clip(entry.get("rationale"), 240))
    if resolution["pairs"] and not verdicts:
        mark_missing(state, "resolver", "no adjudication available: ambiguous pairs were left unmerged (rules only)")
    for index, pair in enumerate(resolution["pairs"]):
        verdict, rationale = verdicts.get(index, ("insufficient_evidence", "No adjudication available; left unmerged."))
        state["decisions"][pair["a"] + "|" + pair["b"]] = dict(
            pair, verdict=verdict, rationale=rationale, by="resolver" if index in verdicts else "unadjudicated")
    rebuild_entities(state, settings)


def reliability(settings, field, slice_id):
    return float(as_dict(settings["priors"].get(field)).get(slice_id, 0.5))


def fuse_field(settings, field, members):
    """Pick the value from the most reliable source; report a conflict when sources disagree."""
    known = [m for m in members if m.get(field) and m.get(field) != "unknown"]
    if not known:
        return None, None
    ranked = sorted(known, key=lambda m: -reliability(settings, field, m["slice"]))
    winner = ranked[0]
    fused = {"value": winner[field], "from": winner["id"],
             "imputed": bool(field == "year" and winner.get("year_imputed"))}
    values = {m[field] for m in known}
    if field == "year":
        years = [int(v) for v in values if str(v).isdigit()]
        disagree = len(years) > 1 and max(years) - min(years) > 1
    else:
        disagree = "active" in values and "inactive" in values
    if not disagree:
        return fused, None
    return fused, {
        "field": field,
        "chosen": winner[field],
        "rule": RELIABILITY_RULES.get(field, "highest source reliability wins"),
        "values": [{"value": m[field], "record_id": m["id"], "slice": m["slice"],
                    "reliability": reliability(settings, field, m["slice"])} for m in ranked],
    }


def rebuild_entities(state, settings):
    """Union-find over `same` decisions. Entity ids are stable: e + the lowest member record number."""
    parent = {r["id"]: r["id"] for r in state["records"]}

    def find(node):
        for _ in range(len(parent) + 1):
            if parent[node] == node:
                break
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for decision in state["decisions"].values():
        if decision["verdict"] == "same" and decision["a"] in parent and decision["b"] in parent:
            parent[find(decision["a"])] = find(decision["b"])
    groups = {}
    for record in state["records"]:
        groups.setdefault(find(record["id"]), []).append(record)
    entities, record_entity = [], {}
    for members in groups.values():
        members = sorted(members, key=lambda m: (-m["similarity"], int(m["id"][1:])))
        entity_id = "e" + str(min(int(m["id"][1:]) for m in members))
        fields, conflicts = {}, []
        for field in ("year", "state"):
            fused, conflict = fuse_field(settings, field, members)
            if fused:
                fields[field] = fused
            if conflict:
                conflicts.append(conflict)
        ids = {m["id"] for m in members}
        entities.append({
            "id": entity_id,
            "name": members[0]["title"],
            "summary": members[0]["text"][:280],
            "records": [m["id"] for m in members],
            "slices": sorted({m["slice"] for m in members}),
            "url": members[0]["url"],
            "similarity": members[0]["similarity"],
            "fields": fields,
            "conflicts": conflicts,
            "imputed_fields": sorted(k for k, v in fields.items() if v["imputed"]),
            "merged_because": [d["rationale"] for d in state["decisions"].values()
                               if d["verdict"] == "same" and d["a"] in ids and d["b"] in ids],
            "possible_same_as": [],
        })
        record_entity.update({m["id"]: entity_id for m in members})
    by_id = {e["id"]: e for e in entities}
    for decision in state["decisions"].values():  # open pairs stay separate but visibly linked
        if decision["verdict"] == "insufficient_evidence":
            left, right = record_entity.get(decision["a"]), record_entity.get(decision["b"])
            if left and right and left != right and right not in by_id[left]["possible_same_as"]:
                by_id[left]["possible_same_as"].append(right)
    state["entities"] = sorted(entities, key=lambda e: (-e["similarity"], e["id"]))
    state["record_entity"] = record_entity


def top_entities(state, limit):
    return state["entities"][:limit]


def entities_holding(state, record_ids):
    wanted = {state["record_entity"].get(rid) for rid in record_ids}
    return [e for e in state["entities"] if e["id"] in wanted]


def record_by_id(state, record_id):
    for record in state["records"]:
        if record["id"] == record_id:
            return record
    return None


def entity_by_id(state, entity_id):
    for entity in state["entities"]:
        if entity["id"] == entity_id:
            return entity
    return None


def evidence_text(record):
    return record["title"] + " " + record["text"]


# ---------------------------------------------------------------------------
# Debate bookkeeping
# ---------------------------------------------------------------------------

def add_claims(state, critique, round_index):
    """Register the critic's claims. A claim that cites nothing we hold is kept and struck later, never hidden."""
    added = []
    for entry in as_list(critique.get("claims"))[:MAX_CLAIMS_PER_TURN]:
        if not isinstance(entry, dict):
            continue
        text, quote = clip(entry.get("text"), 300), clip(entry.get("quote"), 400)
        if not text:
            continue
        record = record_by_id(state, safe_get(entry, "record_id"))
        entity = entity_by_id(state, safe_get(entry, "entity_id"))
        if record is None and entity is not None:
            members = [record_by_id(state, rid) for rid in entity["records"]]
            holders = [m for m in members if m and quote_in_text(quote, evidence_text(m))[0]]
            record = (holders or [m for m in members if m] or [None])[0]
        record_id = record["id"] if record else ""
        if any(c["record_id"] == record_id and words_of(c["quote"]) == words_of(quote) for c in state["claims"]):
            continue
        claim = {
            "id": f"c{len(state['claims']) + 1}",
            "record_id": record_id,
            "text": text,
            "quote": quote,
            "facets": [f for f in string_list(entry.get("facets"), 5, 20) if f in FACET_KEYS],
            "round": round_index + 1,
            "debate_status": "proposed",
            "thread": [],
            "verification": {"status": "pending", "quote_match": False, "citation_status": "unchecked", "reason": ""},
        }
        state["claims"].append(claim)
        added.append(claim)
    return added


def apply_rebuttals(state, critique):
    by_id = {c["id"]: c for c in state["claims"]}
    for entry in as_list(critique.get("rebuttals")):
        claim = by_id.get(safe_get(as_dict(entry), "claim_id"))
        if claim is None or claim["debate_status"] != "contested":
            continue
        withdrawn = safe_get(entry, "action", "").upper().startswith("WITHDRAW")
        claim["debate_status"] = "withdrawn" if withdrawn else "sustained"
        claim["thread"].append({"by": "critic", "type": "WITHDRAW" if withdrawn else "SUSTAIN",
                                "text": clip(entry.get("text"), 320)})


def read_followups(state, critique, staffed):
    """At most MAX_FOLLOWUPS per run, and only to scouts that are on the team."""
    on_team = {str(s.get("id")) for s in staffed}
    room = MAX_FOLLOWUPS - state["followups_used"]
    picked = []
    for entry in as_list(critique.get("followups")):
        entry = as_dict(entry)
        query, slice_id = clip(entry.get("query"), 120), safe_get(entry, "slice_id")
        if query and slice_id in on_team and len(picked) < room:
            picked.append({"facet": clip(entry.get("facet"), 20), "query": query, "slice_id": slice_id,
                           "reason": clip(entry.get("reason"), 200)})
    return picked


def claims_to_answer(state):
    return [c for c in state["claims"] if c["debate_status"] in ("proposed", "sustained")]


def contested_claims(state):
    return [c for c in state["claims"] if c["debate_status"] == "contested"]


def record_defence(state, defence):
    by_id = {c["id"]: c for c in state["claims"]}
    for entry in as_list(defence.get("responses")):
        entry = as_dict(entry)
        claim = by_id.get(safe_get(entry, "claim_id"))
        if claim is None or claim["debate_status"] not in ("proposed", "sustained"):
            continue
        kind = safe_get(entry, "response", "").upper()
        kind = "CONCEDE" if kind.startswith("CONCEDE") else "CHALLENGE" if kind.startswith("CHALLENGE") else "DISTINGUISH"
        claim["debate_status"] = "conceded" if kind == "CONCEDE" else "contested"
        claim["thread"].append({"by": "advocate", "type": kind, "facet": clip(entry.get("facet"), 20),
                                "text": clip(entry.get("text"), 320)})
    for entry in as_list(defence.get("distinctions"))[:3]:
        text = clip(as_dict(entry).get("text"), 260)
        if text and all(d["text"] != text for d in state["distinctions"]):
            state["distinctions"].append({"text": text, "facet": clip(as_dict(entry).get("facet"), 20),
                                          "standing": "advocate argument, not verified evidence"})


def jury_entities(state):
    """Entities the critic made a live claim about, closest first."""
    live = {state["record_entity"].get(c["record_id"]) for c in state["claims"]
            if c["debate_status"] != "withdrawn" and c["record_id"]}
    return [e for e in state["entities"] if e["id"] in live][:MAX_JURY_ENTITIES]


def jury_panel(settings):
    """One juror per configured model family; three same-family jurors when none is configured."""
    models = settings["jury_models"] or [None, None, None]
    return [{"juror": f"juror-{i + 1}", "model": model} for i, model in enumerate(models[:MAX_JURORS])]


def sampler_panel(settings):
    models = settings["prior_models"] or settings["jury_models"] or [None, None, None]
    return [{"index": i + 1, "model": model} for i, model in enumerate(models[:MAX_SAMPLERS])]


def tally_votes(state, entities, jurors, raw_ballots, revote):
    """Mean and spread per (entity, facet). Returns the worst split, or None when the jury agrees."""
    ballots = compact([
        dict(juror, overlaps=as_list(extract_json(raw, fallback={}).get("overlaps")))
        if extract_json(raw, fallback={}).get("overlaps") else None
        for juror, raw in zip(jurors, raw_ballots)
    ])
    dropped = len(jurors) - len(ballots)
    if dropped:
        degrade(state, f"{dropped} of {len(jurors)} jurors returned no ballot and were dropped")
    if not ballots:
        mark_missing(state, "judge", "no juror returned a ballot")
        return None
    worst = None
    for entity in entities:
        for facet in JURY_FACETS:
            votes = [{"juror": b["juror"], "model": b["model"] or "host default",
                      "score": to_unit(o.get(facet)), "why": clip(o.get("why"), 200)}
                     for b in ballots for o in b["overlaps"]
                     if isinstance(o, dict) and safe_get(o, "entity_id") == entity["id"]]
            if not votes:
                continue
            scores = [v["score"] for v in votes]
            vote = {"anchor": entity["records"][0], "entity_id": entity["id"], "entity": entity["name"],
                    "facet": facet, "votes": votes, "mean": round(mean_of(scores), 3),
                    "std": round(spread_of(scores), 3), "revote": revote}
            state["jury"].append(vote)
            if len(scores) > 1 and vote["std"] >= SPLIT_STD and (worst is None or vote["std"] > worst["std"]):
                worst = vote
    return worst


def latest_votes(state):
    """A re-vote replaces the earlier vote on the same subject."""
    latest = {}
    for vote in state["jury"]:
        latest[(state["record_entity"].get(vote["anchor"], vote["entity_id"]), vote["facet"])] = vote
    return latest


def read_probe(proposals, raw):
    """LLM-predictability: did models that never saw the idea propose it anyway?"""
    ratings = {bounded_int(as_dict(r).get("index"), -1, -1, 1000): as_dict(r)
               for r in as_list(extract_json(raw, fallback={}).get("ratings"))}
    samples = []
    for index, proposal in enumerate(proposals):
        if index in ratings:
            samples.append(dict(proposal, similarity=to_unit(ratings[index].get("similarity")),
                                why=clip(ratings[index].get("why"), 200)))
    return {"samples": samples, "n_proposals": len(proposals)}


# ---------------------------------------------------------------------------
# The veto (enforced here, outside every prompt)
# ---------------------------------------------------------------------------

def quote_gate(state):
    """Layer 1: the quoted words must appear in the evidence text the scout returned."""
    for claim in state["claims"]:
        if claim["debate_status"] == "withdrawn":
            claim["verification"].update({"status": "withdrawn", "reason": "withdrawn by the critic during the debate"})
            continue
        record = record_by_id(state, claim["record_id"])
        if record is None:
            claim["verification"].update({"status": "rejected", "reason": "cites a record that is not in the evidence store"})
            continue
        found, detail = quote_in_text(claim["quote"], evidence_text(record))
        claim["verification"].update({"quote_match": found, "reason": detail,
                                      "status": "pending" if found else "rejected"})


def apply_citation_checks(state, checks):
    """Layer 2: an independent checker re-reads the cited page. Only `fake` strikes a claim."""
    by_id = {c["id"]: c for c in state["claims"]}
    for entry in as_list(checks.get("checks")):
        entry = as_dict(entry)
        claim = by_id.get(safe_get(entry, "claim_id"))
        status = safe_get(entry, "citation_status", "").lower()
        if claim is None or claim["verification"]["status"] != "pending":
            continue
        if status not in ("exists", "fake", "unreachable", "unchecked"):
            status = "unchecked"
        claim["verification"]["citation_status"] = status
        claim["verification"]["citation_detail"] = clip(entry.get("detail"), 240)
        if status == "fake":
            claim["verification"].update({"status": "rejected",
                                          "reason": "citation could not be found by the independent check"})


def finalize_claims(state):
    for claim in state["claims"]:
        if claim["verification"]["status"] == "pending":
            claim["verification"]["status"] = "verified"
    return [c for c in state["claims"] if c["verification"]["status"] == "verified"]


# ---------------------------------------------------------------------------
# Scoring (pure functions; higher = more original; any axis may abstain with score None)
# ---------------------------------------------------------------------------

def crowding_axis(similarities):
    if not similarities:
        return {"score": None, "note": "No prior work was retrieved, so crowding cannot be measured."}
    top = sorted(similarities, reverse=True)[:5]
    lite = 0.6 * top[0] + 0.4 * mean_of(top)
    percentile = 1 / (1 + math.exp(-8 * (lite - 0.5)))
    return {"score": round(100 * (1 - percentile), 1),
            "note": "Uncalibrated: similarity has not been calibrated against a reference corpus.",
            "detail": {"crowding_lite": round(lite, 3), "n_neighbours": len(top)}}


def rarity_axis(corpus_stats):
    counts = {k: v for k, v in as_dict(corpus_stats.get("facet_counts")).items()
              if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0}
    if not counts:
        return {"score": None, "note": "Needs an indexed corpus that can count how common each facet is."}
    rarity = {k: round(max(0.0, 1 - math.log1p(v) / math.log1p(2000)), 3) for k, v in counts.items()}
    return {"score": round(100 * mean_of(list(rarity.values())), 1),
            "note": "Rarest facet: " + max(rarity, key=rarity.get) + ".", "detail": {"rarity": rarity, "counts": counts}}


def predictability_axis(probe):
    samples = as_list(probe.get("samples"))
    if not samples:
        return {"score": None, "note": "No blind model samples were collected."}
    sims = [s["similarity"] for s in samples]
    hit_rate = sum(1 for s in sims if s >= COLLISION) / len(sims)
    scaled = min(max((max(sims) - 0.3) / 0.6, 0.0), 1.0)
    return {"score": round(max(100 * (1 - 0.6 * scaled - 0.4 * hit_rate), 0.0), 1),
            "note": "Similarity was rated by a model (this host has no embedding service).",
            "detail": {"max_similarity": round(max(sims), 3), "hit_rate": round(hit_rate, 3), "n_samples": len(sims)}}


def entity_similarities(state):
    """Jury overlap when the jury scored the entity, the scout's similarity otherwise."""
    latest, out = latest_votes(state), []
    for entity in top_entities(state, 10):
        means = [latest[(entity["id"], f)]["mean"] for f in JURY_FACETS if (entity["id"], f) in latest]
        out.append(mean_of(means) if means else entity["similarity"])
    return out


def score_run(state):
    crowding, rarity = crowding_axis(entity_similarities(state)), rarity_axis(state["corpus_stats"])
    predictability = predictability_axis(state["probe"])
    axes = {"crowding": crowding, "facet_rarity": rarity, "llm_predictability": predictability}
    latest = latest_votes(state)
    jury_std = mean_of([v["std"] for v in latest.values()])
    planned = [s for s in state["sources"].values()] + [s for s in state["skipped"] if s["counts"]]
    answered = [s for s in state["sources"].values() if s["status"] in ("ok", "empty", "degraded")]
    coverage = len(answered) / len(planned) if planned else 0.0
    judged = [c for c in state["claims"] if c["verification"]["status"] in ("verified", "rejected")]
    verified_share = (sum(1 for c in judged if c["verification"]["status"] == "verified") / len(judged)) if judged else 0.5
    canary = 1.0 if state["records"] else 0.0
    confidence = round(0.35 * coverage + 0.25 * (1 - min(jury_std / 0.35, 1.0))
                       + 0.25 * verified_share + 0.15 * canary, 3)
    missing = [f"`{s['slice_id']}` {s['status']}" for s in state["sources"].values()
               if s["status"] in ("failed", "blocked")]
    missing += [f"`{s['slice_id']}` not searched: {s['why']}" for s in state["skipped"] if s["counts"]]
    gaps = "; ".join(missing)
    abstain = {"active": False, "reason": ""}
    if not state["records"]:
        abstain = {"active": True, "reason": "Insufficient evidence: no source returned any prior work. "
                   + ("Gaps: " + gaps + ". " if gaps else "Every search came back empty. ")
                   + "This is not a finding that the idea is original."}
    elif coverage < MIN_COVERAGE:
        abstain = {"active": True, "reason": "Insufficient evidence: " + (gaps or "too few sources answered") + "."}
    elif confidence < MIN_CONFIDENCE:
        abstain = {"active": True, "reason": f"Low confidence ({confidence:.2f}): the evidence is thin or the jury "
                   "disagreed. Axes are shown; the headline is withheld."}
    live = {k: a["score"] for k, a in axes.items() if a["score"] is not None}
    headline, band = None, None
    if "crowding" in live and not abstain["active"]:
        total = sum(AXIS_WEIGHTS[k] for k in live)
        log_sum = sum(AXIS_WEIGHTS[k] / total * math.log(max(v, 1.0) / 100) for k, v in live.items())
        headline = round(100 * math.exp(log_sum), 1)
        band = round(min(30.0, 8 + 40 * jury_std + 6 * (len(AXIS_WEIGHTS) - len(live))), 1)
    return {"axes": axes, "headline": headline, "band": band, "confidence": confidence, "abstain": abstain,
            "inputs": {"coverage": round(coverage, 3), "jury_std": round(jury_std, 3),
                       "verified_share": round(verified_share, 3), "canary": canary}}


def attach_rescore(mutation, raw, baseline):
    """Re-score = re-run retrieval for the mutated pitch. No retrieval, no claimed improvement."""
    records = read_records(extract_json(raw, fallback={}))
    after = crowding_axis([r["similarity"] for r in records])["score"]
    mutation["rescored"] = after is not None
    mutation["crowding_after"] = after
    mutation["nearest"] = [r["title"] for r in sorted(records, key=lambda r: -r["similarity"])[:3]]
    if after is None or baseline is None:
        mutation["delta"] = None
        mutation["note"] = "Not re-scored: re-running retrieval returned nothing usable, so no improvement is claimed."
    else:
        mutation["delta"] = round(after - baseline, 1)
        mutation["note"] = "Crowding re-measured on the mutated pitch (positive delta = emptier neighbourhood)."


def read_mutations(raw, count):
    out = []
    for entry in as_list(extract_json(raw, fallback={}).get("mutations"))[:count]:
        entry = as_dict(entry)
        pitch, facet = clip(entry.get("pitch"), 500), safe_get(entry, "facet", "").lower()
        if pitch and facet in FACET_KEYS:
            out.append({"id": f"m{len(out) + 1}", "facet": facet, "from": clip(entry.get("from_value"), 120),
                        "to": clip(entry.get("to_value"), 160), "rationale": clip(entry.get("rationale"), 260),
                        "pitch": pitch, "grounded_in": string_list(entry.get("grounded_in"), 6, 60)})
    return out


def propose_actions(state, settings, scores, mutations):
    """Actions by confidence. This script never executes them; outside-world ones need the user's yes."""
    actions = [{"id": "draft_pitch", "label": "Draft a differentiated pitch from the best re-scored mutation",
                "writes_outside_team": False, "requires_user_confirmation": False, "confirmed": False,
                "available": bool(mutations)}]
    if any(s["status"] in ("ok", "empty", "degraded") for s in state["sources"].values()):
        actions.append({"id": "arm_watch", "label": "Arm a recurring watch that re-runs the scouts and alerts on new look-alikes",
                        "writes_outside_team": True, "requires_user_confirmation": True, "confirmed": False,
                        "available": True})
    if "elastic-agent-builder-mcp" in settings["available_tools"] and not scores["abstain"]["active"]:
        # never write an idea we could not even assess back into a corpus
        actions.append({"id": "writeback", "label": "Write the analysed idea back to the corpus so the next search finds it",
                        "writes_outside_team": True, "requires_user_confirmation": True, "confirmed": False,
                        "available": True})
    return actions


def apply_confirmation(actions, answer):
    """Only an explicit, structured yes confirms an action. Silence, a timeout or prose do not."""
    approved = set(string_list(extract_json(answer, fallback={}).get("approved"), 10, 40))
    for action in actions:
        if action["requires_user_confirmation"]:
            action["confirmed"] = action["id"] in approved


def default_verdict(scores, surviving):
    if scores["abstain"]["active"]:
        text = scores["abstain"]["reason"]
    elif not surviving:
        text = ("No claim about prior work survived verification, so there is nothing we can responsibly "
                "assert about specific prior work yet.")
    else:
        text = "\n".join(f"- [{c['id']}] {c['text']}" for c in surviving)
    return {"verdict_md": text, "crowded": [], "different": [], "unresolved": [], "caveats": [], "written_by": "rules"}


def read_verdict(raw, fallback_verdict):
    parsed = extract_json(raw, fallback={})
    if not safe_get(parsed, "verdict_md"):
        return fallback_verdict
    return {"verdict_md": clip(parsed.get("verdict_md"), 2400), "crowded": string_list(parsed.get("crowded"), 6, 240),
            "different": string_list(parsed.get("different"), 6, 240),
            "unresolved": string_list(parsed.get("unresolved"), 6, 320),
            "caveats": string_list(parsed.get("caveats"), 6, 240), "written_by": "synthesizer"}


def build_report(state, settings, scores, verdict, mutations, actions, status, message):
    """The JSON-serializable Originality Report (same tiers as workflow.md's Final Report Format)."""
    failed = len(state["missing_roles"]) * 2 >= len(ROLE_IDS)
    if failed:
        status, message = "failed", "FAILED: insufficient role coverage - " + ", ".join(state["missing_roles"])
    latest = latest_votes(state)
    for entity in state["entities"]:
        entity["jury_overlap"] = {f: {"mean": latest[(entity["id"], f)]["mean"], "std": latest[(entity["id"], f)]["std"]}
                                  for f in JURY_FACETS if (entity["id"], f) in latest}
    return {
        "status": status,
        "message": message,
        "idea": settings["idea"],
        "facets": as_dict(state["plan"].get("facets")),
        "team": {"staffed": [str(s.get("id")) for s in state["staffed"]],
                 "skipped": [{"slice_id": s["slice_id"], "why": s["why"]} for s in state["skipped"]]},
        "sources": list(state["sources"].values()),
        "scores": scores,
        "verdict": verdict,
        "claims": {
            "verified": [c for c in state["claims"] if c["verification"]["status"] == "verified"],
            "struck": [c for c in state["claims"] if c["verification"]["status"] == "rejected"],
            "withdrawn": [c for c in state["claims"] if c["verification"]["status"] == "withdrawn"],
        },
        "debate": {"rounds_run": state["rounds_run"], "distinctions": state["distinctions"],
                   "requeries": state["requeries"], "jury": state["jury"], "jury_note": state["jury_note"]},
        "predictability_probe": state["probe"],
        "entities": state["entities"][:12],
        "conflicts": [dict(c, entity_id=e["id"], entity=e["name"]) for e in state["entities"] for c in e["conflicts"]],
        "whitespace": state["corpus_stats"],
        "mutations": mutations,
        "actions": actions,
        "missing_roles": state["missing_roles"],
        "degradations": state["degradations"],
        "budget": {"model_calls": state["calls"], "max_model_calls": settings["max_calls"]},
    }


# ---------------------------------------------------------------------------
# Prompt builders - every prompt lives in this file. string.Template ($-placeholders) keeps
# literal braces in prompt prose from being read as Python expressions.
# ---------------------------------------------------------------------------
HOUSE_RULES = """You are one teammate in a team that assesses how original an idea is against retrieved prior work.
House rules: use only the evidence you are given or retrieve yourself with your own tools. Never invent
projects, quotes, numbers or URLs. Quotes must be copied verbatim from the provided text. If the evidence
is thin, say so."""

JSON_RULE = """Answer with ONE JSON object and nothing else: no markdown fences, no commentary. If a
structured-output tool is available, submit the same object through it."""

PLAN_PROMPT = Template("""$house_rules

ROLE: Planner working for the team lead. You decompose the idea and say which source slices are worth
searching. You do not search and you do not judge originality.

IDEA:
$idea
$context
CANDIDATE SOURCE SLICES:
$catalogue

Do this:
1. facets - short noun phrases in plain words: purpose (the goal, and for whom), mechanism (how it works),
   audience, data (what it consumes), twist (what the author believes is new). Use an empty string when the
   idea does not say.
2. idea_kind: product, research, feature, patent or other. domain: two or three words. keywords: up to 6
   specific terms.
3. semantic_queries: exactly 3 natural-language queries - the full idea; purpose plus mechanism; the twist
   alone. keyword_queries: 2 or 3 queries of at most 5 words each for lexical search engines.
4. slices: one entry per candidate slice with relevant (true or false) and why (one short sentence). Call a
   slice irrelevant only when searching it could not find prior work for this kind of idea.

$json_rule
Fields: facets {purpose, mechanism, audience, data, twist}, idea_kind, domain, keywords, semantic_queries,
keyword_queries, slices [{slice_id, relevant, why}].
""")

SCOUT_PROMPT = Template("""$house_rules

ROLE: Scout. Motto: "If it was built, I find it."
You search exactly ONE source slice for prior work that resembles the idea. You work alone and see no other
scout's results. You report listings. You do not merge listings (the resolver does), argue about them (the
critic and the advocate do) or score originality (the judge and the synthesizer do).

SLICE: $slice_id - $label
HOW TO SEARCH THIS SLICE: $guidance
ASSIGNMENT: $assignment
IDEA: $idea
FACETS: $facets
QUERIES:
$queries

Rules:
- Run every query with your search tools. When a query returns nothing, broaden it once (keep its three most
  specific terms) before calling it empty.
- Return at most $limit records, closest first, one record per listing.
- text must be a verbatim excerpt (up to about 600 characters) copied from the page or search result that
  says what the work does. A later check compares quotes against this text, so never paraphrase inside it.
- similarity is a number from 0 to 1 (1 = the same idea). Prefer your tool's relevance score when it gives one.
- year: four digits or an empty string. state: active, inactive or unknown. Do not guess either.
- Respect robots.txt and site terms. If a page answers with a bot challenge, a login wall or a block, do not
  try to get around it: set status to blocked and name the page in note.
- status: ok (records found), empty (searched, nothing relevant), blocked, or failed (no usable search tool,
  or every call errored - say why in note).
- corpus_stats is optional. Fill it only when your tools expose corpus statistics: whitespace_terms (common in
  the corpus overall, absent near this idea), cliche_terms (over-represented near this idea), facet_counts
  (documents matching each facet), corpus_size.

$json_rule
Fields: status, note, queries_run, records [{title, url, year, state, text, similarity}], corpus_stats
{whitespace_terms, cliche_terms, facet_counts, corpus_size}.
""")

RESOLVER_PROMPT = Template("""$house_rules

ROLE: Resolver. Motto: "Four listings, one project."
Task: entity matching. For each pair decide whether A and B are listings of the SAME work (for example a
showcase page and its code repository), DIFFERENT works, or INSUFFICIENT_EVIDENCE. A similar purpose alone is
not "same". Prefer insufficient_evidence over guessing. You do not search, you do not rewrite any listing, and
you do not judge how original the idea is.

IDEA (context only): $idea

$pairs

$json_rule
Fields: verdicts [{pair, verdict, rationale}] - pair is the number shown above; verdict is same, different or
insufficient_evidence; rationale is one sentence.
""")

CRITIC_PROMPT = Template("""$house_rules

ROLE: Critic. Motto: "This has been done - prove me wrong."
Make the strongest honest case that the idea is NOT original. One claim per entity that genuinely overlaps;
skip entities that do not. Every claim needs a quote of at least four words copied verbatim from the TEXT of one
RECORD of that entity - no paraphrase, no stitching sentences together. A separate deterministic check strikes
every claim whose quote is not in that text. You do not search yourself (you may ask scouts to), you do not
defend the idea (the advocate does) and you do not score it (the judge does).

IDEA: $idea
FACETS: $facets

$listing
$round_block$followup_block
$json_rule
Fields: stance (already-done, partly-done, no-case or need-more-evidence), claims [{entity_id, record_id, text,
quote, facets}], rebuttals [{claim_id, action, text}], followups [{facet, query, slice_id, reason}].
""")

CRITIC_ROUND_BLOCK = Template("""
THE ADVOCATE ANSWERED YOUR EARLIER CLAIMS:
$answers
For each contested claim add one rebuttal: action SUSTAIN (say why the distinction or challenge does not hold)
or WITHDRAW (the advocate is right). You may also add new claims.
""")

CRITIC_FOLLOWUP_BLOCK = Template("""
FOLLOW-UP SEARCHES: you may request up to $room more searches, only when the result could change your verdict.
Pick slice_id from: $slices. Give the facet it targets, a query of at most 120 characters, and the reason.
""")

ADVOCATE_PROMPT = Template("""$house_rules

ROLE: Advocate. Motto: "Same words are not the same idea."
For EACH claim choose exactly one response: CONCEDE (it really is the same), DISTINGUISH (same purpose, but
name the one facet that differs: mechanism, audience, data or twist) or CHALLENGE (the quote does not support
the claim). Be honest: concede when the critic is right. Then list up to 3 concrete distinctions that hold
against ALL the prior work shown. Never claim a difference the evidence cannot support. You do not search, you
do not add prior work, and you do not score.

IDEA: $idea
FACETS: $facets

CLAIMS:
$claims

$json_rule
Fields: responses [{claim_id, response, facet, text}], distinctions [{text, facet}].
""")

JUROR_PROMPT = Template("""$house_rules

ROLE: Juror $juror on a jury of independent models. Motto: "Count the votes, measure the split."
Rate each entity from 0 to 1 on how much it overlaps the idea on PURPOSE (the same goal for the same kind of
user) and on MECHANISM (the same way of achieving it). 1 = identical, 0 = unrelated. One short reason each.
You vote alone: you see no other ballot and none of the debate. Do not search, and do not drift toward the
middle to be safe - the spread between jurors is itself a measurement.

IDEA: $idea
PURPOSE: $purpose
MECHANISM: $mechanism

$listing

$json_rule
Fields: overlaps [{entity_id, purpose, mechanism, why}].
""")

SAMPLER_PROMPT = Template("""You are brainstorming $domain ideas (brainstormer number $index).
Propose exactly three DISTINCT ideas, one sentence each, for the problem and audience below.

PROBLEM: $purpose
AUDIENCE: $audience

$json_rule
Fields: ideas [three strings].
""")

PROBE_PROMPT = Template("""$house_rules

ROLE: Judge, predictability probe. Motto: "Count the votes, measure the split."
Other models were given ONLY the problem and the audience - never the idea - and asked to brainstorm. Rate how
close each proposal is to the idea's mechanism and twist: similarity from 0 to 1, where 0.8 or more means a
reader would call it the same idea. Judge the substance, not shared vocabulary.

IDEA: $idea
MECHANISM: $mechanism
TWIST: $twist

PROPOSALS:
$proposals

$json_rule
Fields: ratings [{index, similarity, why}] - index is the number shown above.
""")

VERIFIER_PROMPT = Template("""$house_rules

ROLE: Verifier. Motto: "No receipt, no claim."
A deterministic check has already confirmed that each quote below appears in the evidence text a scout
returned. Your job is the independent citation check: does the cited work really exist at the cited URL?
Open each URL with your page-fetch tool and report citation_status:
- exists: the page loads and is about the cited work
- fake: the URL does not lead to the cited work and you cannot find that work at all (a fabricated citation)
- unreachable: network error, block, robots exclusion or login wall - never try to get around a block
- unchecked: you have no page-fetch tool
Also report quote_on_page: yes, no or unknown. Never guess: when you could not load the page the status is
unreachable or unchecked - not fake, and not exists. You do not judge originality and you do not rewrite claims.

CLAIMS:
$claims

$json_rule
Fields: checks [{claim_id, citation_status, quote_on_page, detail}].
""")

SYNTH_PROMPT = Template("""$house_rules

ROLE: Synthesizer. Motto: "Only what survived."
Write the verdict for the person who pitched the idea using ONLY the surviving claims below; each one passed the
quote check and the citation check. Claims that were struck are deliberately not shown to you. Advocate
distinctions are arguments, not evidence: present them as such. The scores were computed outside this prompt:
do not invent, change or restate numbers. $abstain_note

verdict_md: 3 to 5 sentences of Markdown. Lead with the single most useful sentence in bold. Cite claims by
their [id]. Say plainly what is crowded and what is genuinely different. No hedging filler.
crowded / different: short bullets. unresolved: disputes the debate did not settle, stated from both sides,
never averaged. caveats: degraded sources, conflicts between sources, imputed fields that matter.

IDEA: $idea
FACETS: $facets

SURVIVING CLAIMS (with the debate on each):
$claims

ADVOCATE DISTINCTIONS (unverified arguments):
$distinctions

CONFLICTS BETWEEN SOURCES:
$conflicts

SOURCE STATUS: $sources

$json_rule
Fields: verdict_md, crowded, different, unresolved, caveats.
""")

COACH_PROMPT = Template("""$house_rules

ROLE: Coach. Motto: "Move one facet into the whitespace."
Propose exactly $count mutations. Each changes ONE facet of the idea (purpose, mechanism, audience, data or
twist) so the idea moves away from the crowded neighbours while keeping what is already distinctive. Ground
every swap in a WHITESPACE term or in a stated distinction, and name what you grounded it in. Avoid the CLICHE
terms. Be concrete and buildable; no buzzwords. Never claim a mutation is more original: each one is re-scored
afterwards by re-running retrieval, and only that measurement counts. You do not search and you do not re-argue
the debate.

IDEA: $idea
FACETS: $facets
CROWDED NEIGHBOURS:
$neighbours
CLICHE TERMS: $cliches
WHITESPACE TERMS: $whitespace
ALREADY DISTINCTIVE: $distinctions

$json_rule
Fields: mutations [{facet, from_value, to_value, rationale, pitch, grounded_in}] - pitch is the rewritten idea
in one or two sentences.
""")

CONFIRM_PROMPT = Template("""The originality investigation proposes actions that write OUTSIDE this team.
Nothing has been executed.

$actions

Which of these do you approve? Answer with the ids you approve in `approved` (an empty list approves nothing).
""")


def facet_line(facets):
    return " | ".join(f"{key}={facets.get(key) or 'not stated'}" for key in FACET_KEYS)


def build_plan_prompt(settings):
    context = ""
    if settings["url"]:
        context += "PAGE DESCRIBING THE IDEA: " + settings["url"] + "\n"
    if settings["domain_hint"]:
        context += "KIND OF IDEA (from the user): " + settings["domain_hint"] + "\n"
    catalogue = "\n".join(f"- {s.get('id')}: {clip(s.get('label'), 120)}" for s in settings["sources"])
    return PLAN_PROMPT.substitute(house_rules=HOUSE_RULES, idea=settings["idea"], context=context,
                                  catalogue=catalogue, json_rule=JSON_RULE)


def build_scout_prompt(item):
    queries = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(item["queries"]))
    return SCOUT_PROMPT.substitute(house_rules=HOUSE_RULES, slice_id=item["slice_id"], label=item["label"],
                                   guidance=item["guidance"], assignment=item["assignment"], idea=item["idea"],
                                   facets=facet_line(item["facets"]), queries=queries, limit=RECORDS_PER_SCOUT,
                                   json_rule=JSON_RULE)


def build_resolver_prompt(state, settings, resolution):
    lines = []
    for index, pair in enumerate(resolution["pairs"]):
        left, right = record_by_id(state, pair["a"]), record_by_id(state, pair["b"])
        lines.append(f"PAIR {index} (name similarity {pair['name_similarity']}):\n"
                     f"  A [{left['slice']}, {left['year'] or 'n.d.'}] {left['title']} :: {left['text'][:300]}\n"
                     f"  B [{right['slice']}, {right['year'] or 'n.d.'}] {right['title']} :: {right['text'][:300]}")
    return RESOLVER_PROMPT.substitute(house_rules=HOUSE_RULES, idea=settings["idea"][:600],
                                      pairs="\n".join(lines), json_rule=JSON_RULE)


def entity_listing(state, entities, width):
    lines = []
    for entity in entities:
        lines.append(f"ENTITY {entity['id']} [{'+'.join(entity['slices'])}] {entity['name']} "
                     f"(similarity {entity['similarity']:.2f})")
        for rid in entity["records"]:
            record = record_by_id(state, rid)
            lines.append(f"  RECORD {rid} [{record['slice']}] {record['url']}\n  TEXT: {evidence_text(record)[:width]}")
    return "\n".join(lines)


def build_critic_prompt(state, settings, entities, round_index, staffed):
    round_block, followup_block = "", ""
    if round_index:
        answers = "\n".join(f"{c['id']}: {c['text']}\n   ADVOCATE {c['thread'][-1]['type']}: {c['thread'][-1]['text']}"
                            for c in contested_claims(state) if c["thread"])
        round_block = CRITIC_ROUND_BLOCK.substitute(answers=answers)
    room = MAX_FOLLOWUPS - state["followups_used"]
    if staffed and room and not round_index:
        followup_block = CRITIC_FOLLOWUP_BLOCK.substitute(room=room, slices=", ".join(str(s.get("id")) for s in staffed))
    return CRITIC_PROMPT.substitute(house_rules=HOUSE_RULES, idea=settings["idea"],
                                    facets=facet_line(state["plan"]["facets"]),
                                    listing=entity_listing(state, entities, 700), round_block=round_block,
                                    followup_block=followup_block, json_rule=JSON_RULE)


def claim_lines(state, claims, with_thread):
    lines = []
    for claim in claims:
        record = record_by_id(state, claim["record_id"])
        where = f"{record['title']} - {record['url']}" if record else "unknown source"
        lines.append(f"{claim['id']}: {claim['text']}\n   QUOTE: \"{claim['quote']}\"\n   SOURCE: {where}")
        if record and not with_thread:
            lines.append(f"   SOURCE TEXT: {evidence_text(record)[:500]}")
        if with_thread:
            lines += [f"   {t['by'].upper()} {t['type']}: {t['text']}" for t in claim["thread"]]
    return "\n".join(lines)


def build_advocate_prompt(state, settings, claims):
    return ADVOCATE_PROMPT.substitute(house_rules=HOUSE_RULES, idea=settings["idea"],
                                      facets=facet_line(state["plan"]["facets"]),
                                      claims=claim_lines(state, claims, False), json_rule=JSON_RULE)


def build_juror_prompt(state, settings, entities, juror):
    listing = "\n".join(f"ENTITY {e['id']}: {e['name']} :: {e['summary'][:400]}" for e in entities)
    facets = state["plan"]["facets"]
    return JUROR_PROMPT.substitute(house_rules=HOUSE_RULES, juror=juror["juror"], idea=settings["idea"],
                                   purpose=facets["purpose"], mechanism=facets["mechanism"], listing=listing,
                                   json_rule=JSON_RULE)


def build_sampler_prompt(plan, sampler):
    """Deliberately blind: problem and audience only. The idea itself never enters this prompt."""
    return SAMPLER_PROMPT.substitute(domain=plan["domain"], index=sampler["index"],
                                     purpose=plan["facets"]["purpose"],
                                     audience=plan["facets"]["audience"] or "general", json_rule=JSON_RULE)


def build_probe_prompt(settings, plan, proposals):
    listing = "\n".join(f"{i}. {p['text']}" for i, p in enumerate(proposals))
    return PROBE_PROMPT.substitute(house_rules=HOUSE_RULES, idea=settings["idea"],
                                   mechanism=plan["facets"]["mechanism"],
                                   twist=plan["facets"]["twist"] or "not stated", proposals=listing,
                                   json_rule=JSON_RULE)


def build_verifier_prompt(state, claims):
    return VERIFIER_PROMPT.substitute(house_rules=HOUSE_RULES, claims=claim_lines(state, claims, False),
                                      json_rule=JSON_RULE)


def build_synth_prompt(state, settings, scores, surviving):
    abstain_note = ""
    if scores["abstain"]["active"]:
        abstain_note = ("The run ABSTAINS from a headline score (" + scores["abstain"]["reason"]
                        + ") Say so first, and do not imply a verdict on originality.")
    conflicts = "\n".join(f"- {e['name']}: {c['field']} = {c['chosen']} chosen ({c['rule']}); sources said "
                          + ", ".join(f"{v['value']} [{v['slice']}]" for v in c["values"])
                          for e in state["entities"] for c in e["conflicts"]) or "none"
    sources = "; ".join(f"{s['slice_id']} {s['status']}" for s in state["sources"].values())
    distinctions = "\n".join(f"- ({d['facet']}) {d['text']}" for d in state["distinctions"]) or "none"
    return SYNTH_PROMPT.substitute(house_rules=HOUSE_RULES, abstain_note=abstain_note, idea=settings["idea"],
                                   facets=facet_line(state["plan"]["facets"]),
                                   claims=claim_lines(state, surviving, True), distinctions=distinctions,
                                   conflicts=conflicts, sources=sources, json_rule=JSON_RULE)


def build_coach_prompt(state, settings, count):
    stats = state["corpus_stats"]
    neighbours = "\n".join(f"- {e['name']}: {e['summary'][:160]}" for e in top_entities(state, 6))
    return COACH_PROMPT.substitute(house_rules=HOUSE_RULES, count=count, idea=settings["idea"],
                                   facets=facet_line(state["plan"]["facets"]), neighbours=neighbours,
                                   cliches=", ".join(as_list(stats.get("cliche_terms"))) or "none available",
                                   whitespace=", ".join(as_list(stats.get("whitespace_terms"))) or "none available",
                                   distinctions="; ".join(d["text"] for d in state["distinctions"]) or "none stated",
                                   json_rule=JSON_RULE)


def build_confirm_prompt(actions):
    lines = "\n".join(f"- {a['id']}: {a['label']}" for a in actions)
    return CONFIRM_PROMPT.substitute(actions=lines)


# ---------------------------------------------------------------------------
# Workflow entrypoint
# ---------------------------------------------------------------------------

async def run(args):
    """Execute the workflow and return a JSON-serializable Originality Report."""
    args = parse_args(args)
    settings = read_settings(args)
    state = new_state()
    no_scores = {"axes": {}, "headline": None, "band": None, "confidence": 0.0, "inputs": {},
                 "abstain": {"active": True, "reason": "Insufficient evidence: the run stopped before any search."}}

    # ------------------------------------------------------------------ Plan
    phase("Plan")
    problem = input_problem(settings)
    if problem:
        log("Plan: " + problem)
        no_scores["abstain"]["reason"] = "Insufficient evidence: " + problem
        return build_report(state, settings, no_scores, default_verdict(no_scores, []), [], [], "needs_input", problem)
    if settings["idea_full_length"] > MAX_IDEA_CHARS:
        degrade(state, f"the idea text was cut to {MAX_IDEA_CHARS} characters for every prompt")
    log("Plan: decomposing the idea into facets")
    charge(state, 1)
    raw_plan = await agent(
        build_plan_prompt(settings),
        label="planner",
        phase="Plan",
        schema=PLAN_SCHEMA,
        options=call_options(settings["role_timeout"], None),
    )
    plan = read_plan(extract_json(raw_plan, fallback={}), settings)
    state["plan"] = plan
    if not plan["decomposed"]:
        if raw_plan is None:
            status = "failed"
            problem = "[ROLE MISSING - planner] the planning step returned nothing (timeout or malformed output); no team was formed."
        else:
            status = "needs_input"
            problem = ("The idea could not be decomposed into at least a purpose and a mechanism. "
                       "Say what it does, for whom, and how it works.")
        log("Plan: " + problem)
        no_scores["abstain"]["reason"] = "Insufficient evidence: " + problem
        return build_report(state, settings, no_scores, default_verdict(no_scores, []), [], [], status, problem)
    staffed, skipped = form_team(plan, settings)
    state["staffed"], state["skipped"] = staffed, skipped
    for entry in skipped:
        log(f"Team: scout `{entry['slice_id']}` skipped - {entry['why']}")
    log("Team: scouts staffed for " + (", ".join(str(s.get("id")) for s in staffed) or "no slice"))

    # ------------------------------------------------------------------ Scout
    phase("Scout")
    scout_items = [scout_item(source, plan, settings, "initial search", initial_queries(source, plan))
                   for source in staffed]
    if not scout_items:
        degrade(state, "no scout could be staffed: every source slice was skipped")
    else:
        charge(state, len(scout_items))
        raw_scouts = await parallel([
            lambda item=item: agent(
                build_scout_prompt(item),
                label="scout",
                phase="Scout",
                schema=SCOUT_SCHEMA,
                options=call_options(settings["scout_timeout"], None),
            )
            for item in scout_items
        ])
        retry_items = []
        for item, raw in zip(scout_items, raw_scouts):
            outcome, new_ids, note = ingest_scout(state, item, raw, "initial")
            set_source(state, item["slice_id"], outcome, len(new_ids), note)
            if outcome == "failed":
                log(f"Scout `{item['slice_id']}` failed ({note}); one broadened retry follows")
                retry_items.append(dict(item, assignment="broadened retry after a failed first attempt",
                                        queries=broadened_queries(plan)))
            elif outcome == "blocked":
                degrade(state, f"source `{item['slice_id']}` is blocked ({note}); it was not retried or evaded")
        if retry_items:
            charge(state, len(retry_items))
            raw_retries = await parallel([
                lambda item=item: agent(
                    build_scout_prompt(item),
                    label="scout-retry",
                    phase="Scout",
                    schema=SCOUT_SCHEMA,
                    options=call_options(settings["scout_timeout"], None),
                )
                for item in retry_items
            ])
            for item, raw in zip(retry_items, raw_retries):
                outcome, new_ids, note = ingest_scout(state, item, raw, "retry")
                if outcome in ("ok", "empty"):
                    set_source(state, item["slice_id"], "degraded", len(new_ids),
                               "first attempt failed; the broadened retry succeeded")
                    degrade(state, f"source `{item['slice_id']}` is degraded: first attempt failed, broadened retry succeeded")
                else:
                    set_source(state, item["slice_id"], "failed" if outcome == "failed" else outcome, 0, note)
                    degrade(state, f"source `{item['slice_id']}` {outcome} after one retry ({note}); confidence drops")
        if all(s["status"] in ("failed", "blocked") for s in state["sources"].values()):
            mark_missing(state, "scout", "every staffed scout failed or was blocked")
    log(f"Scout: {len(state['records'])} records from {len(state['sources'])} slices")

    # ------------------------------------------------------------------ Resolve
    phase("Resolve")
    if state["records"]:
        resolution = plan_resolution(state)
        raw_verdicts = None
        if resolution["pairs"]:
            charge(state, 1)
            raw_verdicts = await agent(
                build_resolver_prompt(state, settings, resolution),
                label="resolver",
                phase="Resolve",
                schema=RESOLVER_SCHEMA,
                options=call_options(settings["role_timeout"], None),
            )
        finish_resolution(state, settings, resolution, raw_verdicts)
        log(f"Resolve: {len(state['records'])} records became {len(state['entities'])} entities; "
            f"{sum(len(e['conflicts']) for e in state['entities'])} conflicts surfaced")
    else:
        log("Resolve: skipped, no evidence was retrieved")

    # ------------------------------------------------------------------ Debate
    phase("Debate")
    if state["entities"]:
        for round_index in range(settings["debate_rounds"]):
            if round_index and not (contested_claims(state) and can_spend(state, settings, 2, KEEP_FOR_VERDICT)):
                break
            state["rounds_run"] = round_index + 1
            charge(state, 1)
            raw_critique = await agent(
                build_critic_prompt(state, settings, top_entities(state, 8), round_index, staffed),
                label="critic",
                phase="Debate",
                schema=CRITIC_SCHEMA,
                options=call_options(settings["role_timeout"], settings["critic_model"]),
            )
            critique = extract_json(raw_critique, fallback={})
            if raw_critique is None:
                mark_missing(state, "critic", "the critic returned nothing; no claim was made this round")
            add_claims(state, critique, round_index)
            apply_rebuttals(state, critique)

            # Back-edge 1: the critic may send scouts back out (first round only, capped per run).
            followups = [] if round_index else read_followups(state, critique, staffed)
            if followups and not can_spend(state, settings, len(followups) + 2, KEEP_FOR_VERDICT):
                degrade(state, "critic follow-up searches were skipped: the run is close to its budget")
                followups = []
            if followups:
                state["followups_used"] += len(followups)
                charge(state, len(followups))
                follow_items = []
                for request in followups:
                    source = [s for s in staffed if str(s.get("id")) == request["slice_id"]][0]
                    follow_items.append(scout_item(source, plan, settings,
                                                   f"critic follow-up on facet `{request['facet']}`: {request['reason']}",
                                                   [request["query"]]))
                    state["requeries"].append(dict(request, by="critic"))
                    log(f"Requery: critic sends scout `{request['slice_id']}` back out - {request['query']}")
                raw_follow = await parallel([
                    lambda item=item: agent(
                        build_scout_prompt(item),
                        label="scout-followup",
                        phase="Debate",
                        schema=SCOUT_SCHEMA,
                        options=call_options(settings["scout_timeout"], None),
                    )
                    for item in follow_items
                ])
                fresh_ids = []
                for item, raw in zip(follow_items, raw_follow):
                    outcome, new_ids, note = ingest_scout(state, item, raw, "critic-followup")
                    bump_source(state, item["slice_id"], len(new_ids))
                    fresh_ids += new_ids
                    if outcome in ("failed", "blocked"):
                        degrade(state, f"critic follow-up on `{item['slice_id']}` {outcome} ({note})")
                if fresh_ids:
                    resolution = plan_resolution(state)
                    raw_verdicts = None
                    if resolution["pairs"]:
                        charge(state, 1)
                        raw_verdicts = await agent(
                            build_resolver_prompt(state, settings, resolution),
                            label="resolver-followup",
                            phase="Debate",
                            schema=RESOLVER_SCHEMA,
                            options=call_options(settings["role_timeout"], None),
                        )
                    finish_resolution(state, settings, resolution, raw_verdicts)
                    charge(state, 1)
                    raw_second = await agent(
                        build_critic_prompt(state, settings, entities_holding(state, fresh_ids)[:4], 0, []),
                        label="critic-second-look",
                        phase="Debate",
                        schema=CRITIC_SCHEMA,
                        options=call_options(settings["role_timeout"], settings["critic_model"]),
                    )
                    add_claims(state, extract_json(raw_second, fallback={}), round_index)

            open_claims = claims_to_answer(state)
            if not open_claims:
                break
            charge(state, 1)
            raw_defence = await agent(
                build_advocate_prompt(state, settings, open_claims),
                label="advocate",
                phase="Debate",
                schema=ADVOCATE_SCHEMA,
                options=call_options(settings["role_timeout"], settings["advocate_model"]),
            )
            if raw_defence is None:
                mark_missing(state, "advocate", "the advocate returned nothing; claims stand unanswered")
            record_defence(state, extract_json(raw_defence, fallback={}))

        # The jury: independent ballots, spread measured in code.
        contested = jury_entities(state)
        jurors = jury_panel(settings)
        if contested:
            if not settings["jury_models"]:
                state["jury_note"] = ("The jury ran on one model family (no jury_models configured), "
                                      "so disagreement is under-estimated.")
                log("Caveat: " + state["jury_note"])
            charge(state, len(jurors))
            raw_ballots = await parallel([
                lambda juror=juror: agent(
                    build_juror_prompt(state, settings, contested, juror),
                    label="juror",
                    phase="Debate",
                    schema=BALLOT_SCHEMA,
                    options=call_options(settings["role_timeout"], juror["model"]),
                )
                for juror in jurors
            ])
            split = tally_votes(state, contested, jurors, raw_ballots, False)

            # Back-edge 2: a split jury is information. One targeted re-query on exactly the
            # disputed facet of the disputed entity, then a re-vote on that entity only.
            if split and state["tiebreaks_used"] >= MAX_TIEBREAKS:
                split = None
            if split and not (staffed and can_spend(state, settings, 2 + len(jurors), KEEP_FOR_VERDICT)):
                degrade(state, f"jury split (std {split['std']}) on {split['entity']} / {split['facet']} "
                               "was not re-queried: the run is close to its budget")
                split = None
            if split:
                state["tiebreaks_used"] += 1
                disputed = entity_by_id(state, split["entity_id"])
                home = [s for s in staffed if str(s.get("id")) in disputed["slices"]] or staffed
                query = clip(f"{plan['facets'][split['facet']]} {disputed['name']}", 120)
                state["requeries"].append({"by": "judge", "facet": split["facet"], "query": query,
                                           "slice_id": str(home[0].get("id")),
                                           "reason": f"jury split (std {split['std']}) on {disputed['name']}"})
                log(f"Requery: jury split (std {split['std']}) on `{split['facet']}` of {disputed['name']}; "
                    f"scout `{home[0].get('id')}` goes back out")
                charge(state, 1)
                raw_tiebreak = await agent(
                    build_scout_prompt(scout_item(home[0], plan, settings,
                                                  f"tie-break evidence on facet `{split['facet']}` for {disputed['name']}",
                                                  [query])),
                    label="scout-tiebreak",
                    phase="Debate",
                    schema=SCOUT_SCHEMA,
                    options=call_options(settings["scout_timeout"], None),
                )
                outcome, new_ids, note = ingest_scout(state, {"slice_id": str(home[0].get("id"))}, raw_tiebreak, "jury-tiebreak")
                bump_source(state, str(home[0].get("id")), len(new_ids))
                if new_ids:
                    resolution = plan_resolution(state)
                    raw_verdicts = None
                    if resolution["pairs"]:
                        charge(state, 1)
                        raw_verdicts = await agent(
                            build_resolver_prompt(state, settings, resolution),
                            label="resolver-tiebreak",
                            phase="Debate",
                            schema=RESOLVER_SCHEMA,
                            options=call_options(settings["role_timeout"], None),
                        )
                    finish_resolution(state, settings, resolution, raw_verdicts)
                else:
                    log(f"Requery: the tie-break search added nothing new ({outcome}); the re-vote still runs")
                revote_on = entities_holding(state, [split["anchor"]])
                charge(state, len(jurors))
                raw_revotes = await parallel([
                    lambda juror=juror: agent(
                        build_juror_prompt(state, settings, revote_on, juror),
                        label="juror-revote",
                        phase="Debate",
                        schema=BALLOT_SCHEMA,
                        options=call_options(settings["role_timeout"], juror["model"]),
                    )
                    for juror in jurors
                ])
                tally_votes(state, revote_on, jurors, raw_revotes, True)

        # The LLM-predictability probe: blind samplers see the problem and the audience, never the idea.
        samplers = sampler_panel(settings)
        if can_spend(state, settings, len(samplers) + 1, KEEP_FOR_VERDICT):
            charge(state, len(samplers))
            raw_samples = await parallel([
                lambda sampler=sampler: agent(
                    build_sampler_prompt(plan, sampler),
                    label="blind-sampler",
                    phase="Debate",
                    schema=SAMPLER_SCHEMA,
                    options=call_options(settings["role_timeout"], sampler["model"]),
                )
                for sampler in samplers
            ])
            proposals = [{"sampler": sampler["index"], "model": sampler["model"] or "host default", "text": text}
                         for sampler, raw in zip(samplers, raw_samples)
                         for text in string_list(extract_json(raw, fallback={}).get("ideas"), 3, 300)]
            if proposals:
                charge(state, 1)
                raw_ratings = await agent(
                    build_probe_prompt(settings, plan, proposals),
                    label="judge-probe",
                    phase="Debate",
                    schema=PROBE_SCHEMA,
                    options=call_options(settings["role_timeout"], None),
                )
                state["probe"] = read_probe(proposals, raw_ratings)
            else:
                degrade(state, "the predictability probe collected no blind samples; that axis abstains")
        else:
            degrade(state, "the predictability probe was skipped: the run is close to its budget")
    else:
        log("Debate: skipped, there is nothing to argue about")

    # ------------------------------------------------------------------ Verify
    phase("Verify")
    quote_gate(state)
    to_check = [c for c in state["claims"] if c["verification"]["status"] == "pending"][:MAX_CITATION_CHECKS]
    if to_check and can_spend(state, settings, 1, 1):
        charge(state, 1)
        raw_checks = await agent(
            build_verifier_prompt(state, to_check),
            label="verifier",
            phase="Verify",
            schema=CITATION_SCHEMA,
            options=call_options(settings["role_timeout"], settings["verifier_model"]),
        )
        if raw_checks is None:
            mark_missing(state, "verifier", "the citation check is unavailable; claims rest on the quote check alone")
        apply_citation_checks(state, extract_json(raw_checks, fallback={}))
    elif to_check:
        degrade(state, "the citation check was skipped (budget); claims rest on the quote check alone")
    surviving = finalize_claims(state)
    struck = [c for c in state["claims"] if c["verification"]["status"] == "rejected"]
    for claim in struck:
        log(f"Veto: claim {claim['id']} struck - {claim['verification']['reason']}")
    log(f"Verify: {len(surviving)} claims survived, {len(struck)} struck")

    # ------------------------------------------------------------------ Synthesize
    phase("Synthesize")
    scores = score_run(state)
    verdict = default_verdict(scores, surviving)
    if surviving:  # the synthesizer is only ever shown claims that survived the veto
        charge(state, 1)
        raw_verdict = await agent(
            build_synth_prompt(state, settings, scores, surviving),
            label="synthesizer",
            phase="Synthesize",
            schema=SYNTH_SCHEMA,
            options=call_options(settings["role_timeout"], None),
        )
        if raw_verdict is None:
            mark_missing(state, "synthesizer", "no written verdict; surviving claims are listed as they are")
        verdict = read_verdict(raw_verdict, verdict)
    if scores["abstain"]["active"]:
        log("Synthesize: ABSTAIN - " + scores["abstain"]["reason"])
    else:
        log(f"Synthesize: headline {scores['headline']} +/- {scores['band']}, confidence {scores['confidence']}")

    # ------------------------------------------------------------------ Coach
    phase("Coach")
    mutations = []
    if state["entities"] and staffed and can_spend(state, settings, 2):
        count = 2 if not can_spend(state, settings, 1 + MAX_MUTATIONS) else MAX_MUTATIONS
        charge(state, 1)
        raw_swaps = await agent(
            build_coach_prompt(state, settings, count),
            label="coach",
            phase="Coach",
            schema=COACH_SCHEMA,
            options=call_options(settings["role_timeout"], settings["coach_model"]),
        )
        mutations = read_mutations(raw_swaps, count)
        if raw_swaps is None or not mutations:
            mark_missing(state, "coach", "no usable mutation was proposed")
        # Re-score loop: each mutated pitch goes back to the densest slice's scout.
        densest = max(staffed, key=lambda s: int(as_dict(state["sources"].get(str(s.get("id")))).get("n_records") or 0))
        if len(mutations) > settings["max_calls"] - state["calls"]:
            kept = max(settings["max_calls"] - state["calls"], 0)
            degrade(state, f"{len(mutations) - kept} mutations were not re-scored: the call cap was reached")
            for mutation in mutations[kept:]:
                attach_rescore(mutation, None, None)
        rescore_items = [dict(scout_item(densest, plan, settings, "re-score of a mutated pitch: find its nearest prior work",
                                         [mutation["pitch"]]), idea=mutation["pitch"], mutation_id=mutation["id"])
                         for mutation in mutations if "delta" not in mutation]
        if rescore_items:
            charge(state, len(rescore_items))
            raw_rescores = await parallel([
                lambda item=item: agent(
                    build_scout_prompt(item),
                    label="scout-rescore",
                    phase="Coach",
                    schema=SCOUT_SCHEMA,
                    options=call_options(settings["scout_timeout"], None),
                )
                for item in rescore_items
            ])
            baseline = scores["axes"]["crowding"]["score"]
            by_id = {m["id"]: m for m in mutations}
            for item, raw in zip(rescore_items, raw_rescores):
                attach_rescore(by_id[item["mutation_id"]], raw, baseline)
                log(f"Coach: mutation {item['mutation_id']} re-scored, delta {by_id[item['mutation_id']]['delta']}")
    elif state["entities"]:
        degrade(state, "coaching was skipped: the run is close to its budget")
    else:
        log("Coach: skipped, there is no evidence to move away from")

    # ------------------------------------------------------------------ Act
    phase("Act")
    actions = propose_actions(state, settings, scores, mutations)
    gated = [a for a in actions if a["requires_user_confirmation"]]
    if gated and settings["ask_confirmation"]:
        answer = await human(
            build_confirm_prompt(gated),
            schema=CONFIRM_SCHEMA,
            label="user-confirmation",
            phase="Act",
            options={"timeout": settings["confirm_timeout"]},
        )
        apply_confirmation(actions, answer)
    for action in gated:
        log(f"Act: `{action['id']}` proposed; confirmed by the user: {action['confirmed']}")

    status = "abstained" if scores["abstain"]["active"] else "degraded" if state["degradations"] else "complete"
    return build_report(state, settings, scores, verdict, mutations, actions, status, scores["abstain"]["reason"])
