"""Mutator: coaching. Proposes facet swaps grounded in corpus whitespace, then RE-SCORES each one against evidence,
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


class Swap(BaseModel):
    facet: str = Field(description="purpose | mechanism | audience | data | twist")
    frm: clipped(120)
    to: clipped(160)
    rationale: clipped(260)
    pitch: clipped(500) = Field(description="the rewritten idea in 1-2 sentences")
    grounded_in: list[str] = Field(default_factory=list, description="whitespace terms or evidence this swap is based on")


class Swaps(BaseModel):
    model_config = ConfigDict(json_schema_extra={"required": ["mutations", "diagnosis", "question", "suggestions"]})

    mutations: list[Swap]
    # the coach's opening turn, written in the same call so the conversation costs the run nothing extra
    diagnosis: clipped(700) = Field(default="", description="2-4 sentences to the author: which part of the idea is crowded (name the neighbours), and what is already theirs")
    question: clipped(400) = Field(default="", description="ONE open question to the author, a single sentence, that would help find a more original direction")
    suggestions: list[clipped(160)] = Field(default_factory=list, description="up to 3 replies the author might tap: first person, at most 10 words each, no numbering")


class CoachTurn(BaseModel):
    # Every field is REQUIRED in the JSON schema the model sees (it skips optional ones), yet validation stays tolerant.
    model_config = ConfigDict(json_schema_extra={"required": ["reply", "question", "suggestions", "cited"]})

    reply: clipped(1600) = Field(description="your answer to the author: plain prose, no markdown, at most 90 words in one or two short paragraphs")
    question: clipped(400) = Field(default="", description="ONE question, a single sentence, that moves the idea forward. It goes here and NOT in `reply`")
    suggestions: list[clipped(160)] = Field(default_factory=list, description="2-3 replies the author might tap next: first person, at most 10 words each, no numbering")
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


COACH_RULES = (
    "Role: originality coach, in conversation with the idea's author. You are a thinking partner, not a score optimiser: the goal is an idea "
    "the author wants to build that is genuinely different from what exists, and a higher number is only a side effect.\n"
    "- Respond to what the author just said, specifically. Build on their constraints, skills and interests.\n"
    "- PROJECTS lists real prior art, including a FRESH corpus search run on the author's latest message. When their new direction lands on an "
    "existing project, say so and name it; when it lands in open space, say that too. Never name a project that is not listed.\n"
    "- Disagree when you should. Do not flatter, and do not hand over a menu of options: offer at most one concrete direction per turn.\n"
    "- This is a conversation, not a plan: at most 90 words, no feature lists, no markdown. Say the one thing that matters most and stop.\n"
    "- Always give 2-3 `suggestions`: replies in the author's voice, at most 10 words each, that would each take the idea somewhere different.\n"
    "- End with ONE question (in `question`, not in `reply`) unless the author asked you to just answer.\n"
    "- A separate editor keeps the WORKING PITCH in step with what the author decides and re-measures it; you never need to restate it.\n"
)
TRANSCRIPT_TURNS = 12
REPLY_CAP = 750


def _named(title: str, text: str) -> bool:
    """Did the coach name this project? Whole words and exact case, so a project called Quiz is not 'cited' by the word quizzes."""
    return len(title) >= 4 and re.search(rf"(?<!\w){re.escape(title)}(?!\w)", text) is not None


def _chips(suggestions: list[str]) -> list[str]:
    """Tap-to-send replies: no list numbering, nothing cut mid-word, nothing too long to read at a glance."""
    out = []
    for s in suggestions:
        s = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", s).strip().strip('"')
        if s and len(s) <= 110:
            out.append(s)
    return out[:3]


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
        whitespace = await self._whitespace(ctx)
        cliches = [c.term for c in (stats.get("cliches") or [])][:10]
        neighbours = "\n".join(f"- {e.canonical_name}: {e.summary[:160]}" for e in board.top_entities(6))
        differs = [c.text for c in board.claims.values() if c.kind == "differs"]
        system = (HOUSE_RULES + f"Role: originality coach. Propose exactly {n} mutations. Each changes ONE facet of the idea so it moves away "
                  "from the crowded neighbours while keeping what is already distinctive. Ground each swap in the WHITESPACE terms (common "
                  "in the corpus overall, absent near this idea) or in a stated difference. Avoid the CLICHE terms. Be concrete and buildable "
                  "in a weekend; no buzzwords.\nThen open a conversation with the author: `diagnosis` tells them plainly which part of their idea "
                  "is crowded (name the neighbours) and what is already theirs; `question` asks the ONE thing you most need to know to help them "
                  "find a more original direction (their skills, who they care about, what they refuse to give up); `suggestions` are replies they might tap.")
        user = (f"IDEA: {board.idea_text}\nFACETS: purpose={f.purpose} | mechanism={f.mechanism} | audience={f.audience} | data={f.data} | twist={f.twist}\n"
                f"CROWDED NEIGHBOURS:\n{neighbours}\nCLICHE TERMS: {cliches}\nWHITESPACE TERMS: {[w.term for w in whitespace][:12]}\nALREADY DISTINCTIVE: {differs}")
        swaps, res = await self.llm.structured(role=self.id, system=system, user=user, schema=Swaps, temperature=1.0,
                                               session=self.session(ctx), budget=ctx.budget)
        muts = []
        for i, s in enumerate(swaps.mutations[:n], 1):
            mu = Mutation(mid=f"mu{len(board.mutations) + 1}", **s.model_dump())
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
        await self._open(ctx, swaps, res.meta())
        return result(mids=[m.mid for m in muts], summary=f"{len(muts)} mutations, each re-scored against the evidence")

    async def _measure(self, ctx: Ctx, pitch: str, q: str | None = None) -> tuple[float | None, list[float], list[SourceRecord], bool]:
        """Re-run retrieval for `pitch` and recompute crowding. Falls back to reranking known neighbours.
        Returns (crowding score, similarities, corpus hits (empty on the fallback), calibrated)."""
        board = ctx.board
        sims: list[float] = []
        hits: list[SourceRecord] = []
        calibrated = True
        if get_settings().has_elastic:
            try:
                from app.search.hybrid import search as hybrid_search

                hits = await hybrid_search(q or pitch, pitch, size=10)
                sims = [float(h.retrieval.get("rerank_score") or 0) for h in hits]
            except Exception as exc:
                await ctx.emit("error", {"message": f"corpus re-search degraded: {type(exc).__name__}: {exc}"[:200], "recoverable": True})
        if not sims:
            ents = board.top_entities(10)
            sims, calibrated = await rerank(pitch, [e.summary for e in ents])
        return axes.crowding(sims, axes.corpus_percentile(), calibrated=calibrated).score, sims, hits, calibrated

    async def _score(self, ctx: Ctx, mu: Mutation) -> None:
        board = ctx.board
        after, sims, _, _ = await self._measure(ctx, mu.pitch)
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
            diagnosis = (f"The closest existing work is {names}." if names else "Nothing close turned up in the corpus.") + (f" What already looks like yours: {differs}" if differs else "")
            question = question or "Which part of this idea would you refuse to give up, and which part are you happy to change?"
        named = [e for e in board.top_entities(12) if _named(e.canonical_name, diagnosis)][:4]
        await self._say(ctx, "coach", diagnosis, meta, question=_whole_sentences(question, 260) or None, suggestions=_chips(swaps.suggestions),
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
        whitespace = [w.term for w in (board.stats.get("whitespace") or [])][:12]
        cliches = [c.term for c in (stats.get("cliches") or [])][:10]
        transcript = "\n".join(f"{'COACH' if m.role == 'coach' else 'AUTHOR'}: {m.text}{(' ' + m.question) if m.question else ''}" for m in board.coach[-TRANSCRIPT_TURNS:])
        directions = "\n".join(f"- ({m.facet}) {m.frm} -> {m.to}: {m.rationale}" for m in board.mutations.values())
        user = (f"ORIGINAL IDEA: {board.idea_text}\n"
                + (f"FACETS: purpose={f.purpose} | mechanism={f.mechanism} | audience={f.audience} | data={f.data} | twist={f.twist}\n" if f else "")
                + f"WORKING PITCH (v{current.version if current else 0}): {pitch_now}\n"
                f"PROJECTS (FRESH = found by searching the author's latest message):\n{listing or '(none retrieved)'}\n"
                f"CLICHE TERMS HERE: {cliches}\nWHITESPACE TERMS (common in the corpus, absent near this idea): {whitespace}\n"
                f"DIRECTIONS ALREADY ON THE TABLE:\n{directions or '(none)'}\n"
                + (f"THE AUTHOR WANTS TO EXPLORE: ({mu.facet}) {mu.frm} -> {mu.to}. {mu.rationale}\n" if mu else "")
                + f"CONVERSATION SO FAR:\n{transcript}\n\nReply to the author's last message in at most 70 words.")
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
        reply, question = _whole_sentences(turn.reply), _whole_sentences(turn.question, 260)
        if question and reply.endswith(question):  # said twice: keep it only where the UI sets it apart
            reply = reply[:-len(question)].rstrip()
        if not question:  # the question was written into the reply: lift it out so the UI can set it apart
            head, sep, tail = reply.rpartition(". ")
            if sep and tail.endswith("?") and len(tail) <= 260:
                reply, question = head + ".", tail
        # models name projects without listing them in `cited`: a project counts as cited when the reply says its name
        named = [i for i, c in enumerate(projects, 1) if _named(c.title, reply)]
        cites = [projects[i - 1] for i in dict.fromkeys([*turn.cited, *named]) if 1 <= i <= len(projects)][:4]
        await self._say(ctx, "coach", reply, res.meta(), question=question or None,
                        suggestions=_chips(turn.suggestions), cites=cites, mid=mu.mid if mu else None, pitch_version=version)
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

    async def _whitespace(self, ctx: Ctx) -> list:
        if not get_settings().has_elastic:
            return []
        try:
            from app.schemas import TermStat
            from app.search.whitespace import find_whitespace

            found = await find_whitespace(ctx.board.facets.purpose)
            rows = sorted(found.get("tech", []) + found.get("tags", []), key=lambda c: -c["global_count"])
            return [TermStat(term=c["term"], global_count=c["global_count"], neighbourhood_count=c["neighbourhood_count"]) for c in rows[:20]]
        except Exception as exc:
            await ctx.emit("error", {"message": f"whitespace finder unavailable: {type(exc).__name__}: {exc}"[:200], "recoverable": True})
            return []


register("mutator")(Mutator)
