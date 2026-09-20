"""Mutator: coaching. Proposes facet swaps grounded in the gaps between the closest projects, then RE-SCORES each one against evidence,
so the user sees the neighbourhood thin out instead of taking the suggestion on faith (SciMON-style loop).

After the run it stays on as a thinking partner: the author talks the idea through with it (`chat`), every turn is
checked against the corpus BEFORE the coach answers, and whenever the conversation changes the idea a new version of
the working pitch is written and re-measured. The goal is an idea worth building, not a bigger number.
"""
from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.orchestration.host import Ctx, error, result
from app.orchestration.registry import register
from app.roles.base import HOUSE_RULES, BaseRole, clipped
from app.schemas import CoachCite, CoachMessage, CoachPitch, GraphLink, GraphNode, GraphPatch, Mutation, SourceRecord
from app.scoring import axes
from app.scoring.similarity import lexical_cosine, rerank
from app.sources.idea_url import is_self


class Swap(BaseModel):
    facet: str = Field(description="purpose | mechanism | audience | data | twist")
    frm: clipped(120) = Field(description="what the idea says NOW for that part: copy it from PARTS, at most 10 words (not the part's name)")
    to: clipped(160) = Field(description="what it becomes, at most 14 words")
    rationale: clipped(260) = Field(description="ONE plain sentence to the author: what the named existing projects all do, and what this version does that none of them do")
    pitch: clipped(500) = Field(description="the WHOLE idea rewritten with this one change: 1-2 full sentences that start with what the product is, the way the author would say it. Not a copy of `to`")
    grounded_in: list[str] = Field(default_factory=list, description="whitespace terms or evidence this swap is based on")


class Swaps(BaseModel):
    model_config = ConfigDict(json_schema_extra={"required": ["mutations", "diagnosis", "question", "suggestions"]})

    mutations: list[Swap]
    # the coach's opening turn, written in the same call so the conversation costs the run nothing extra
    diagnosis: clipped(700) = Field(default="", description="2-3 short sentences to the author, at most 45 words (anything after the third sentence is cut): what the closest existing projects have in common with the idea (name at most 3), then what is already theirs, or, if the pitch is too short to tell, that it is early and you want to hear more")
    question: clipped(400) = Field(default="", description="ONE short open question, a single sentence of at most 20 words, not a list of options")
    suggestions: list[clipped(160)] = Field(default_factory=list, description="3 replies the author might tap, at most 8 words each, no numbering: a choice about the idea or a request to you, never a fact about the author")


class CoachTurn(BaseModel):
    # Every field is REQUIRED in the JSON schema the model sees (it skips optional ones), yet validation stays tolerant.
    model_config = ConfigDict(json_schema_extra={"required": ["reply", "question", "suggestions", "cited"]})

    reply: clipped(1600) = Field(description="your answer to the author: plain prose, no markdown, 2-3 sentences, at most 45 words; anything after the third sentence is cut")
    question: clipped(400) = Field(default="", description="ONE question, a single sentence of at most 20 words, that moves the idea forward. It goes here and NOT in `reply`")
    suggestions: list[clipped(160)] = Field(default_factory=list, description="3 replies the author might tap next, at most 8 words each, no numbering: answers to YOUR question or requests to you, never a fact about the author, never a new feature of yours")
    cited: list[int] = Field(default_factory=list, description="numbers of the PROJECTS you actually named in the reply")


class PitchEdit(BaseModel):
    """The working idea is kept by its own small call: asked to coach AND edit at once, the model just echoes the old pitch."""

    model_config = ConfigDict(json_schema_extra={"required": ["changed", "pitch", "note"]})

    changed: bool = Field(description="true only if the author's LAST message changes what the product is, who it is for or how it works")
    pitch: clipped(900) = Field(default="", description="the rewritten pitch, 1-2 sentences, at most 55 words; empty if changed is false")
    note: clipped(200) = Field(default="", description="what changed, at most 8 words; empty if changed is false")


EDITOR_RULES = (
    "You keep an author's working pitch up to date while they talk an idea through with a coach. Read the author's LAST message.\n"
    "It CHANGES the pitch when they propose something (\"what if it...\"), choose between options, or say yes to the coach's suggestion "
    "(then the coach's last message says what they agreed to). Fold the change in straight away, even if it is unproven: the new version "
    "gets measured against prior art, that is the point. Drop the parts of the old pitch that the author has moved away from.\n"
    "It does NOT change the pitch when they only ask a question, state a constraint about themselves, voice a doubt, or say they want to explore.\n"
    "When it changes, REFOCUS rather than append: lead with what the author has said they care about most, and cut features they have set aside or "
    "never defended, so the pitch stays 1-2 sentences and under 55 words. Write it the way the author would say it: plain, concrete, no buzzwords, "
    "nothing the author has not said or agreed to. `note` is a label of at most 8 words, like \"input is past exams, not notes\".\n"
)


# How the coach talks, in the opener and in every turn after it. Written after reading what the model really said to
# people: it scolded one-line pitches ("the idea is a blank template"), quoted its own prompt back ("twist=unspecified",
# "WHITESPACE term 'opencv'"), and put invented life stories in the author's mouth ("I grew up on a farm").
VOICE = (
    "How you talk: like a friend who has seen a lot of projects. Warm, direct, plain words, short sentences. Say \"you\".\n"
    "- Never use the labels from your notes: no \"facet\", \"twist\", \"whitespace\", \"cliche\", \"neighbour\", \"corpus\", \"crowding\", "
    "no field=value. Call the projects we searched \"the dataset\" if you must mention it at all. No jargon (\"arbitrage\", \"vertical\", \"positioning\").\n"
    "- Talk about the projects, not about the dataset: name them and say what they do, never \"the dataset shows...\".\n"
    "- Never scold, and never list what the pitch lacks. A one-line pitch is not a bad idea, it is an early one: say who it is up against "
    "and what those have in common, then say it is early and you would like to hear what they picture.\n"
    "- No flattery and no drama either: never open with praise or with \"That reframes everything\".\n"
    "- You know NOTHING about the author beyond what they wrote. Never invent their background, skills, contacts or experience, "
    "not even inside a suggested reply.\n"
    "- `suggestions` are things the author might tap instead of typing, at most 8 words each: a choice that names parts of THEIR idea "
    "(keep this, drop that, aim it at someone else), or a request to you. Each one different, none repeated from earlier in the "
    "conversation, never a blank to fill in.\n"
)

COACH_RULES = (
    "Role: originality coach, in conversation with the idea's author. You are a thinking partner, not a score optimiser: the goal is an idea "
    "the author wants to build that is genuinely different from what exists, and a higher number is only a side effect.\n"
    "- Respond to what the author just said, specifically. Build on the constraints, skills and interests THEY have told you about.\n"
    "- PROJECTS lists real prior art, including a FRESH search of the dataset run on the author's latest message. When their new direction lands on an "
    "existing project, say so and name it; when nothing listed does it, say that too. Never name a project that is not listed.\n"
    "- Disagree when you should. Do not hand over a menu of options: offer at most one concrete direction per turn.\n"
    "- This is a conversation, not a plan: 2-3 sentences, at most 45 words, no feature lists, no build steps, no markdown. Say the one thing "
    "that matters most and stop; anything after the third sentence is cut. If they asked a practical question, answer it in a sentence or two.\n"
    "- VERSIONS shows how each version of the idea measured (higher = more original). Mention a number only when it moved and only once.\n"
    "- End with ONE short question (in `question`, not in `reply`) unless the author asked you to just answer.\n"
    "- A separate editor keeps the WORKING PITCH in step with what the author decides and re-measures it; you never need to restate it.\n"
) + VOICE
TRANSCRIPT_TURNS = 12
REPLY_CAP = 420


def _named(title: str, text: str) -> bool:
    """Did the coach name this project? Whole words and exact case, so a project called Quiz is not 'cited' by the word quizzes."""
    return len(title) >= 4 and re.search(rf"(?<!\w){re.escape(title)}(?!\w)", text) is not None


# A chip that starts like this is the model inventing the author's life ("I grew up on a farm and know pests").
_BIO = re.compile(r"^(?:i\s+(?:grew|spent|worked|used\s+to|was|am\s+an?|have\s+(?:experience|contacts|years|access|an?\b)|already\s+(?:have|know|built|designed)|know\s+(?:exactly|people|someone))"
                  r"|i['’](?:m\s+an?|ve)\b)", re.I)
FALLBACK_CHIPS = ["What is the least crowded angle?", "What does nobody here do yet?", "Let me tell you more about it"]


_FACET_WORDS = {"purpose": ("purpose", "what it is for", "goal"), "mechanism": ("mechanism", "how it works", "method"),
                "audience": ("audience", "who it is for", "user"), "data": ("data", "what it runs on", "input"), "twist": ("twist", "angle")}


def _facet(raw: str) -> str:
    """The key the map berths a direction by. The model paraphrases it ("who it is for") as soon as the prompt does."""
    low = raw.strip().lower()
    return next((key for key, words in _FACET_WORDS.items() if any(w in low for w in words)), low[:20] or "twist")


def _chips(suggestions: list[str], fallback: bool = False, said: tuple[str, ...] = ()) -> list[str]:
    """Tap-to-send replies: no list numbering, nothing too long to read at a glance, no blanks to fill in, and no
    invented biography, nothing offered before (`said`). `fallback` tops a thin set up with neutral chips, so the opener never leaves the author with nothing to tap."""
    out: list[str] = []
    stale = {x.lower() for x in said}  # a chip the author has already been offered (or tapped) is not offered again
    for s in suggestions:
        s = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", s).strip().strip('"')
        if s and len(s) <= 70 and "__" not in s and not _BIO.search(s) and s.lower() not in {o.lower() for o in out} | stale:
            out.append(s)
    if fallback and len(out) < 2:
        out += [c for c in FALLBACK_CHIPS if c.lower() not in {o.lower() for o in out}]
    return out[:3]


_LABELS = [(re.compile(r"\b(?:the\s+)?corpus\b", re.I), "the dataset"), (re.compile(r"\bcorpora\b", re.I), "datasets"),
           (re.compile(r"\bWHITESPACE(?:\s+terms?)?\b:?\s*"), ""), (re.compile(r"\bCLICHE(?:\s+terms?)?\b:?\s*"), ""),
           (re.compile(r"\bSTATED DIFFERENCE\b:?\s*", re.I), ""), (re.compile(r"\s+with no (?:stated\s+)?twist\b", re.I), ""),
           (re.compile(r"\bThe dataset (?:has|shows|is packed with|contains)\b:?\s*", re.I), "")]


def _plain(text: str) -> str:
    """The model quotes its notes back at the author (\"WHITESPACE: 'opencv' appears in corpus\"). Take the labels out."""
    for pat, to in _LABELS:
        text = pat.sub(to, text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:1].upper() + text[1:] if text else text


_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]?\s+(?=[A-Z\"'(\[])")


def _brief(text: str, sentences: int = 3, cap: int = REPLY_CAP) -> str:
    """The coach's turn, held to a few sentences. The model ignores every word limit it is given (asked for 90 words it
    wrote 130, as a build plan), so the limit lives here: the first `sentences` sentences, and never more than `cap`."""
    parts = _SENTENCE_END.split(" ".join(text.split()))
    out = ""
    for part in parts[:sentences]:
        if out and len(out) + 1 + len(part) > cap:
            break
        out = f"{out} {part}".strip()
    return _whole_sentences(out, cap)


def _one_question(text: str, cap: int = 170) -> str:
    """One short question. A long one is usually a question with a menu bolted on ("... - the chips, the revenue, or
    the identity - and what skill do you have?"): keep what comes before the menu."""
    text = " ".join(text.split())
    if "?" in text:
        text = text[:text.index("?") + 1]
    if len(text) <= cap:
        return text
    head = re.split(r"\s+[—–-]\s+|—|:\s", text, maxsplit=1)[0].rstrip(" ,;")
    if 20 <= len(head) <= cap:
        return head + "?"
    # "are they X, or are they Y and Z and ...?": the first alternative is a whole question on its own
    clauses = [m.start() for m in re.finditer(r",?\s+(?:or|and)\s", text) if 20 <= m.start() <= cap]
    cut = clauses[-1] if clauses else text.rfind(",", 20, cap)
    return (text[:cut] if cut > 0 else text[:cap].rsplit(" ", 1)[0]).rstrip(" ,;") + "?"


def _whole_sentences(text: str, cap: int = REPLY_CAP) -> str:
    """A chatty model gets cut at the last full sentence inside the cap, never mid-word."""
    text = text.strip()
    if len(text) <= cap:
        return text
    cut = max(text.rfind(end, 0, cap) for end in (". ", "? ", "! ", ".\n", "?\n", "!\n"))
    return text[:cut + 1].rstrip() if cut > cap // 3 else text[:cap].rsplit(" ", 1)[0] + "…"


class Mutator(BaseRole):
    id = "mutator"
    purpose = "Move one facet into the whitespace."
    phase = "mutate"

    async def handle(self, msg: dict, ctx: Ctx) -> dict:
        p = msg["payload"]
        if p.get("rescore"):
            mu = ctx.board.mutations.get(p["rescore"])
            if mu is None:
                return error(f"unknown mutation {p['rescore']!r}")
            await self._score(ctx, mu)
            return result(mid=mu.mid, delta=mu.delta, axes=mu.axes)
        if p.get("chat"):
            return await self._chat(ctx, str(p["chat"]), p.get("mid"))
        return await self._propose(ctx, n=2 if ctx.budget.low() else 3)

    async def _propose(self, ctx: Ctx, n: int) -> dict:
        board, f = ctx.board, ctx.board.facets
        stats = board.stats.get("corpus") or {}
        whitespace, topics = await self._whitespace(ctx)
        cliches = [c.term for c in (stats.get("cliches") or [])][:10]
        neighbours = "\n".join(f"- {e.canonical_name}: {e.summary[:160]}" for e in board.top_entities(6))
        differs = [c.text for c in board.claims.values() if c.kind == "differs"]
        system = (HOUSE_RULES + f"Role: originality coach. Propose exactly {n} mutations: directions the author could take this idea.\n"
                  "- Each changes ONE part of the idea and keeps the rest; `facet` is that part's key, exactly one of purpose | mechanism | audience | data | twist, "
                  "so the author still recognises it as theirs. Stay in their field: a chip idea stays a chip idea, a study tool stays a study tool.\n"
                  "- Find each direction in the GAP between the closest projects: read what they do, and look for the user, the moment or the "
                  "method that none of them cover. The rationale names those projects and says what they all do and what this version does instead.\n"
                  "- TOPICS THAT ARE RARE NEAR THIS IDEA are only hints: use one when it fits the idea naturally, ignore the rest. Never "
                  "bolt on an unrelated industry or a software library to be different. OVERUSED WORDS are what everyone nearby says: do not lean on them.\n"
                  "- Concrete and buildable in a weekend; no buzzwords. Make the three directions really different from each other.\n"
                  "Then open a conversation with the author: `diagnosis`, `question` (the ONE thing you most need to know to help: which part "
                  "they care about, who they picture using it, what they would refuse to give up) and `suggestions`.\n" + VOICE)
        user = (f"IDEA: {board.idea_text}\nPARTS: purpose={f.purpose} | mechanism={f.mechanism} | audience={f.audience} | data={f.data} | twist={f.twist}\n"
                f"CLOSEST EXISTING PROJECTS:\n{neighbours}\nOVERUSED WORDS: {cliches}\nTOPICS THAT ARE RARE NEAR THIS IDEA: {topics}\nALREADY DISTINCTIVE: {differs}")
        swaps, res = await self.llm.structured(role=self.id, system=system, user=user, schema=Swaps, temperature=1.0,
                                               session=self.session(ctx), budget=ctx.budget)
        muts = []
        for i, s in enumerate(swaps.mutations[:n], 1):
            mu = Mutation(mid=f"mu{len(board.mutations) + 1}", **(s.model_dump() | {"facet": _facet(s.facet), "rationale": _whole_sentences(_plain(s.rationale), 240)}))
            board.put("mutations", self.id, mu.mid, mu)
            muts.append(mu)
            await ctx.emit("mutation.proposed", {"mutation": mu.model_dump(mode="json")}, **res.meta())
            await ctx.emit("graph.patch", GraphPatch(
                add_nodes=[GraphNode(id=f"mut:{mu.mid}", kind="mutation", label=mu.to[:60], similarity=board.scores.crowding.detail.get("crowding_lite") if board.scores else None, val=3)],
                add_links=[GraphLink(source="idea", target=f"mut:{mu.mid}", kind="mutation_of", weight=0.8)]))
        for mu in muts:
            await self._score(ctx, mu)
        if whitespace:
            stats["whitespace"] = whitespace
            board.put("stats", self.id, "coach_topics", topics)
        await self._open(ctx, swaps, res.meta())
        return result(mids=[m.mid for m in muts], summary=f"{len(muts)} mutations, each re-scored against the evidence")

    async def _measure(self, ctx: Ctx, pitch: str, q: str | None = None) -> tuple[float | None, list[float], list[SourceRecord], bool]:
        """Re-run retrieval for `pitch` and recompute crowding, against the dataset AND against what this run already found.
        Returns (crowding score, similarities (the fresh hits' first, in order), dataset hits, calibrated).

        The second half matters: the original was scored against everything the scouts brought back, live web search
        included, while the dataset only holds Devpost and YC. Measured against the dataset alone, any rewording of
        "ai chipmaker" jumped 70 points, because Cerebras and Graphcore were simply no longer in the room."""
        board = ctx.board
        hits: list[SourceRecord] = []
        hit_sims: list[float] = []
        ents = board.top_entities(12)

        async def fresh() -> None:
            nonlocal hits, hit_sims
            if not get_settings().has_elastic:
                return
            try:
                from app.search.hybrid import search as hybrid_search

                found = await hybrid_search(q or pitch, pitch, size=10)
                # A re-score must exclude the author's own project too, or every coached version is measured
                # against itself and the coach cites the author back to themselves as their own nearest neighbour.
                hits = [h for h in found if not is_self(h, board.self_page)]
                hit_sims = [float(h.retrieval.get("rerank_score") or 0) for h in hits]
            except Exception as exc:
                await ctx.emit("error", {"message": f"dataset re-search degraded: {type(exc).__name__}: {exc}"[:200], "recoverable": True})

        (_, (ent_sims, calibrated)) = await asyncio.gather(fresh(), rerank(pitch, [e.summary for e in ents]))
        seen = {h.title.lower() for h in hits}
        known = [s for e, s in zip(ents, ent_sims) if e.canonical_name.lower() not in seen]
        sims = hit_sims + known
        if not sims:
            return None, [], hits, calibrated
        calibrated = calibrated or bool(hit_sims)
        return axes.crowding(sorted(sims, reverse=True)[:10], axes.corpus_percentile(), calibrated=calibrated).score, sims, hits, calibrated

    async def _score(self, ctx: Ctx, mu: Mutation) -> None:
        board = ctx.board
        # the model writes the pitch as a tagline ("Catch gaps before they grow."): too little to measure on its own
        after, sims, _, _ = await self._measure(ctx, mu.pitch if len(mu.pitch) >= 90 else f"{mu.to}. {mu.pitch}")
        before = board.scores.crowding.score if (board.scores and board.scores.crowding.score is not None) else None
        mu.axes = {"crowding": after} if after is not None else None
        mu.delta = round(after - before, 1) if (after is not None and before is not None) else None
        board.put("mutations", self.id, mu.mid, mu)
        await ctx.emit("mutation.scored", {"mid": mu.mid, "delta": mu.delta, "axes": mu.axes})
        await ctx.emit("graph.patch", GraphPatch(update_nodes=[{"id": f"mut:{mu.mid}", "similarity": round(axes.crowding_lite(sims), 3)}]))

    # -- the conversation ------------------------------------------------------------------------------
    async def _say(self, ctx: Ctx, role: str, text: str, meta: dict | None = None, **fields) -> CoachMessage:
        m = CoachMessage(id=f"cm{len(ctx.board.coach) + 1}", role=role, text=text.strip(), **fields)
        ctx.board.append("coach", self.id, m)
        await ctx.emit("coach.message", {"message": m.model_dump(mode="json", exclude_none=True)}, **(meta or {}))
        return m

    async def _open(self, ctx: Ctx, swaps: Swaps, meta: dict) -> None:
        """v0 of the working idea is the original pitch at the run's own scores; then the coach speaks first."""
        board = ctx.board
        if board.pitches or board.coach:
            return
        sc = board.scores
        top = board.top_entities(3)
        v0 = CoachPitch(version=0, text=board.idea_text, note="your original pitch", crowding=sc.crowding.score if sc else None,
                        delta=0.0 if (sc and sc.crowding.score is not None) else None, headline=sc.headline if sc else None,
                        nearest=[self._cite_entity(e) for e in top], calibrated=bool(sc and sc.crowding.detail.get("calibrated", True)))
        board.append("pitches", self.id, v0)
        await ctx.emit("coach.pitch", {"pitch": v0.model_dump(mode="json")})
        diagnosis, question = swaps.diagnosis.strip(), swaps.question.strip()
        if not diagnosis:  # the model skipped the opener: say what the evidence says, without inventing anything
            differs = next((c.text for c in board.claims.values() if c.kind == "differs"), "")
            names = ", ".join(e.canonical_name for e in top)
            diagnosis = (f"The closest existing work is {names}." if names else "Nothing close turned up in the dataset.") + (f" What already looks like yours: {differs}" if differs else "")
            question = question or "Which part of this idea would you refuse to give up, and which part are you happy to change?"
        diagnosis, question = _brief(_plain(diagnosis)), _one_question(_plain(question))
        named = [e for e in board.top_entities(12) if _named(e.canonical_name, diagnosis)][:4]
        await self._say(ctx, "coach", diagnosis, meta, question=question or None, suggestions=_chips(swaps.suggestions, fallback=True),
                        cites=[self._cite_entity(e) for e in (named or top)])

    @staticmethod
    def _cite_entity(e) -> CoachCite:
        def field(name: str):
            ff = e.fields.get(name)
            return ff.value if ff is not None else None

        year = field("year")
        return CoachCite(title=e.canonical_name, url=str(field("url") or ""), source=(e.sources or [""])[0],
                         year=year if isinstance(year, int) else None, similarity=round(float(e.similarity), 3), eid=e.eid)

    async def _chat(self, ctx: Ctx, text: str, mid: str | None) -> dict:
        board, f = ctx.board, ctx.board.facets
        text = text.strip()[:1500]
        mu = board.mutations.get(mid) if mid else None
        current = board.pitches[-1] if board.pitches else None
        pitch_now = current.text if current else board.idea_text
        await self._say(ctx, "user", text, mid=mu.mid if mu else None)

        # check what the author just said against the corpus BEFORE answering, so pushback comes with a receipt
        _, sims, hits, _ = await self._measure(ctx, f"{pitch_now}\n{text}"[:1500], q=text if len(text) >= 24 else None)
        known = {e.canonical_name.lower(): e for e in board.entities.values()}
        projects: list[CoachCite] = []
        for h, sim in zip(hits[:5], sims):
            e = known.get(h.title.lower())
            projects.append(CoachCite(title=h.title, url=h.url, source=h.source, year=h.year, similarity=round(sim, 3), eid=e.eid if e else None))
        seen = {c.title.lower() for c in projects}
        projects += [c for c in (self._cite_entity(e) for e in board.top_entities(5)) if c.title.lower() not in seen]
        blurbs = {h.title.lower(): (h.tagline or h.pitch or h.description)[:200] for h in hits[:5]} | {k: e.summary[:200] for k, e in known.items() if k not in {h.title.lower() for h in hits[:5]}}
        listing = "\n".join(f"[{i}] {c.title} ({c.source}{f', {c.year}' if c.year else ''}){' FRESH' if i <= min(len(hits), 5) else ''}: {blurbs.get(c.title.lower(), '')}"
                            for i, c in enumerate(projects, 1))

        stats = board.stats.get("corpus") or {}
        topics = list(board.stats.get("coach_topics") or [])[:10]
        cliches = [c.term for c in (stats.get("cliches") or [])][:10]
        versions = " | ".join(f"v{p.version} {round(p.headline if p.headline is not None else p.crowding)}" + (f" ({p.note})" if p.version and p.note else "")
                              for p in board.pitches if (p.headline if p.headline is not None else p.crowding) is not None)
        transcript = "\n".join(f"{'COACH' if m.role == 'coach' else 'AUTHOR'}: {m.text}{(' ' + m.question) if m.question else ''}" for m in board.coach[-TRANSCRIPT_TURNS:])
        directions = "\n".join(f"- ({m.facet}) {m.frm} -> {m.to}: {m.rationale}" for m in board.mutations.values())
        user = (f"ORIGINAL IDEA: {board.idea_text}\n"
                + (f"FACETS: purpose={f.purpose} | mechanism={f.mechanism} | audience={f.audience} | data={f.data} | twist={f.twist}\n" if f else "")
                + f"WORKING PITCH (v{current.version if current else 0}): {pitch_now}\n"
                f"PROJECTS (FRESH = found by searching the author's latest message):\n{listing or '(none retrieved)'}\n"
                + (f"VERSIONS (originality, 0-100): {versions}\n" if versions else "")
                + f"OVERUSED WORDS NEAR THIS IDEA: {cliches}\nTOPICS THAT ARE RARE NEAR THIS IDEA (hints only, ignore unless one fits): {topics}\n"
                f"DIRECTIONS ALREADY ON THE TABLE:\n{directions or '(none)'}\n"
                + (f"THE AUTHOR WANTS TO EXPLORE: ({mu.facet}) {mu.frm} -> {mu.to}. {mu.rationale}\n" if mu else "")
                + f"CONVERSATION SO FAR:\n{transcript}\n\nReply to the author's last message in 2-3 sentences, at most 45 words.")
        last_coach = next((m for m in reversed(board.coach[:-1]) if m.role == "coach"), None)
        earlier = " / ".join(m.text[:300] for m in board.coach[:-1] if m.role == "user")[-900:]
        edit_user = (f"ORIGINAL IDEA: {board.idea_text}\nWORKING PITCH: {pitch_now}\n"
                     + (f"WHAT THE AUTHOR SAID EARLIER: {earlier}\n" if earlier else "")
                     + (f"COACH'S LAST MESSAGE: {last_coach.text} {last_coach.question or ''}\n" if last_coach else "")
                     + (f"(The author opened a direction to EXPLORE, not yet to adopt: {mu.frm} -> {mu.to})\n" if mu else "")
                     + f"AUTHOR'S LAST MESSAGE: {text}")
        coach_call = self.llm.structured(role=self.id, system=HOUSE_RULES + COACH_RULES, user=user, schema=CoachTurn, temperature=0.7,
                                         max_tokens=1200, session=self.session(ctx), budget=ctx.budget)
        edit_call = self.llm.structured(role=self.id, system=EDITOR_RULES, user=edit_user, schema=PitchEdit, temperature=0.2,
                                        max_tokens=500, session=self.session(ctx), budget=ctx.budget)
        answered, edited = await asyncio.gather(coach_call, edit_call, return_exceptions=True)
        if isinstance(answered, BaseException):
            await self._say(ctx, "coach", "I could not reach a model for that turn, so nothing was lost: your message is saved. Try again in a moment.")
            return error(f"coach turn failed: {type(answered).__name__}: {answered}"[:200])
        turn, res = answered
        edit = edited[0] if not isinstance(edited, BaseException) else PitchEdit(changed=False)  # a failed edit costs a version, not the turn

        new_pitch = _whole_sentences(edit.pitch, 520) if edit.changed else ""
        changed = bool(new_pitch) and lexical_cosine(new_pitch, pitch_now) < 0.95  # a reworded copy is not a new version
        version = (current.version if current else 0) + 1 if changed else None
        reply, asked = " ".join(_plain(turn.reply).split()), " ".join(_plain(turn.question).split())
        if asked and asked in reply:  # said twice: keep it only where the UI sets it apart
            reply = reply.replace(asked, "").strip()
        if not asked:  # the question was written into the reply: lift it out so the UI can set it apart
            head, sep, tail = reply.rpartition(". ")
            if sep and tail.endswith("?") and len(tail) <= 260:
                reply, asked = head + ".", tail
        reply, question = _brief(reply), _one_question(asked)
        # models name projects without listing them in `cited`: a project counts as cited when the reply says its name
        named = [i for i, c in enumerate(projects, 1) if _named(c.title, reply)]
        cites = [projects[i - 1] for i in dict.fromkeys([*turn.cited, *named]) if 1 <= i <= len(projects)][:4]
        await self._say(ctx, "coach", reply, res.meta(), question=question or None,
                        suggestions=_chips(turn.suggestions, said=tuple(c for m in board.coach for c in (m.suggestions or []))), cites=cites, mid=mu.mid if mu else None, pitch_version=version)
        if changed:
            await self._version(ctx, version, new_pitch, _whole_sentences(edit.note.split(". ")[0], 80).rstrip("."))
        return result(version=version, summary=f"coach replied{f'; working idea v{version}' if version else ''}")

    async def _version(self, ctx: Ctx, version: int, text: str, note: str) -> None:
        """Announce the new working idea at once (the UI shows it as 'checking'), then measure it against the corpus."""
        board = ctx.board
        draft = CoachPitch(version=version, text=text, note=note)
        board.append("pitches", self.id, draft)
        await ctx.emit("coach.pitch", {"pitch": draft.model_dump(mode="json")})
        after, sims, hits, calibrated = await self._measure(ctx, text)
        sc = board.scores
        before = sc.crowding.score if (sc and sc.crowding.score is not None) else None
        draft.crowding, draft.calibrated = after, calibrated
        draft.delta = round(after - before, 1) if (after is not None and before is not None) else None
        if sc and after is not None:
            crowd = sc.crowding.model_copy(update={"score": after})
            draft.headline, _ = axes.headline({"crowding": crowd, "facet_rarity": sc.facet_rarity, "llm_predictability": sc.llm_predictability}, 0.0)
        draft.nearest = ([CoachCite(title=h.title, url=h.url, source=h.source, year=h.year, similarity=round(s, 3)) for h, s in zip(hits[:3], sims)]
                         or [self._cite_entity(e) for e in board.top_entities(3)])
        await ctx.emit("coach.pitch", {"pitch": draft.model_dump(mode="json")})

    async def _whitespace(self, ctx: Ctx) -> tuple[list, list[str]]:
        """-> (whitespace terms for the report, the subject tags among them). Only the tags go to the coach: told that
        'opencv' or 'express.js' was open ground, it bolted a software library onto a chip company to be different."""
        if not get_settings().has_elastic:
            return [], []
        try:
            from app.schemas import TermStat
            from app.search.whitespace import find_whitespace

            found = await find_whitespace(ctx.board.facets.purpose)
            rows = sorted(found.get("tech", []) + found.get("tags", []), key=lambda c: -c["global_count"])
            topics = [c["term"] for c in sorted(found.get("tags", []), key=lambda c: -c["global_count"])][:10]
            return [TermStat(term=c["term"], global_count=c["global_count"], neighbourhood_count=c["neighbourhood_count"]) for c in rows[:20]], topics
        except Exception as exc:
            await ctx.emit("error", {"message": f"whitespace finder unavailable: {type(exc).__name__}: {exc}"[:200], "recoverable": True})
            return [], []


register("mutator")(Mutator)
