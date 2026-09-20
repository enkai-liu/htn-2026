"""Synthesizer: scores the idea and writes the report from what SURVIVED verification.

The restriction is enforced in code: only `verified` and `unverified_lead` claims are ever placed in its prompt.
"""
from __future__ import annotations

import statistics

from app.config import get_settings
from app.llm.router import LLMUnavailable
from app.orchestration.host import Ctx, result
from app.orchestration.registry import register
from app.roles.base import HOUSE_RULES, BaseRole
from app.schemas import Entity, FacetOverlap, JurorVote, Report, TermStat, YearCount
from app.scoring import axes
from app.scoring.similarity import tokens
from app.signals.surprisal import RCSResult

SOURCE_WEIGHT = {"devpost": 0.40, "github": 0.20, "yc": 0.15, "hn": 0.15, "arxiv": 0.05, "web": 0.05}
CORPUS = ("devpost", "yc")


class Synthesizer(BaseRole):
    id = "synthesizer"
    purpose = "Only what survived."
    phase = "score"

    async def handle(self, msg: dict, ctx: Ctx) -> dict:
        return await (self._report(ctx) if msg["payload"].get("kind") == "report" else self._score(ctx))

    async def _score(self, ctx: Ctx) -> dict:
        board = ctx.board
        stats = await self._corpus_stats(ctx)
        ents = board.top_entities(10)
        calibrated = not any(r.retrieval.get("uncalibrated") for r in board.records.values())
        rcs = await self._surprisal(ctx, ents)
        crowd = axes.crowding([e.similarity for e in ents], axes.corpus_percentile(), calibrated=calibrated,
                              names=[e.canonical_name for e in ents],
                              rcs=rcs.nats_per_token if rcs else None, rcs_pct=axes.rcs_percentile())
        if rcs is not None:
            crowd.detail.update(rcs.as_detail())

        cliches = stats.get("cliches") or []
        idea_terms = set(tokens(board.idea_text))
        overlap = (len(idea_terms & {t for c in cliches for t in tokens(c.term)}) / len(idea_terms)) if (cliches and idea_terms) else None
        pair = stats.get("pair") or {}
        rarity = axes.facet_rarity(stats.get("facet_dfs"), pair.get("df_ab", stats.get("pair_df")), overlap,
                                   pair_npmi=pair.get("npmi"), pair_expected=pair.get("expected"),
                                   facet_rarities=stats.get("facet_rarities"), facet_terms=stats.get("facet_terms"))
        pred = axes.llm_predictability(board.priors)

        latest = {(v["eid"], v["facet"]): v for v in board.jury}  # re-votes replace earlier votes on the same subject
        jury_std = statistics.fmean(v["std"] for v in latest.values()) if latest else 0.0
        planned = list(board.sources.values())
        total_w = sum(SOURCE_WEIGHT.get(s.source, 0.05) for s in planned) or 1.0
        coverage = sum(SOURCE_WEIGHT.get(s.source, 0.05) for s in planned if s.status in ("ok", "degraded")) / total_w
        exists = [c for c in board.claims.values() if c.kind == "exists"]
        verified_share = (sum(c.status == "verified" for c in exists) / len(exists)) if exists else 0.5
        searched = ("ok", "degraded")  # degraded = it answered, then failed or needed a retry; the corpus WAS searched
        corpus_ok = any(s.source in CORPUS and s.status in searched for s in planned)
        canary = 1.0 if any(s.source in CORPUS and s.status in searched and s.n_records > 0 for s in planned) else 0.0
        conf = axes.confidence(coverage=coverage, jury_std=jury_std, verified_share=verified_share, canary_pass=canary)
        missing = [f"{s.source} {s.status}" for s in planned if s.status in ("failed", "skipped")]
        if not corpus_ok:
            missing.insert(0, "the hackathon/startup corpus was not searched")
        scores = axes.assemble(crowd, rarity, pred, jury_std=jury_std, conf=conf,
                               abstain=axes.decide_abstain(coverage=coverage, corpus_ok=corpus_ok, conf=conf, missing=missing),
                               boot=self._bootstrap_inputs(board, ents, stats, pair, overlap, rcs))
        board.set("scores", self.id, scores)
        board.put("stats", self.id, "corpus", stats)
        await ctx.emit("score.updated", scores)
        return result(headline=scores.headline, confidence=conf, abstain=scores.abstain.active,
                      summary=scores.abstain.reason if scores.abstain.active else f"headline {scores.headline} ±{scores.band}, confidence {conf}")

    async def _report(self, ctx: Ctx) -> dict:
        """Runs last, after coaching, so mutations and whitespace are part of the report."""
        board, scores = ctx.board, ctx.board.scores
        stats = board.stats.get("corpus") or {}
        cliches, planned = stats.get("cliches") or [], list(board.sources.values())
        latest = {(v["eid"], v["facet"]): v for v in board.jury}
        exists = [c for c in board.claims.values() if c.kind == "exists"]
        summary, meta = await self._summary(ctx, scores)
        entities = []
        for e in board.top_entities(12):
            e = e.model_copy(deep=True)  # the report gets jury overlaps attached; the blackboard entity stays resolver-owned
            for (eid, facet), v in latest.items():
                if eid == e.eid:
                    e.facet_overlap[facet] = FacetOverlap(mean=v["mean"], std=v["std"], votes=[JurorVote(**x) for x in v["votes"]])
            entities.append(e)
        evidence = list(board.evidence.values())
        report = Report(
            run_id=ctx.run_id, idea_text=board.idea_text, facets=board.facets, scores=scores, voice=board.voice, entities=entities,
            claims=list(board.claims.values()), evidence=evidence, cliches=cliches, whitespace=stats.get("whitespace") or [],
            by_year=stats.get("by_year") or [], mutations=list(board.mutations.values()), sources=planned,
            citations=[ev.citation for ev in evidence], summary_md=summary)
        return result(report=report.model_dump(mode="json"), summary=f"report from {sum(c.status == 'verified' for c in exists)} verified claims", **({"llm": meta} if meta else {}))

    async def _summary(self, ctx: Ctx, scores) -> tuple[str, dict]:
        board = ctx.board
        allowed = [c for c in board.claims.values() if c.status in ("verified", "unverified_lead")]  # the veto, enforced here
        if not allowed:
            return "No claim about prior art survived verification, so there is nothing we can responsibly assert yet.", {}
        lines = []
        for c in allowed:
            cite = f" [{board.evidence[c.evidence[0]].citation.split(']')[0].lstrip('[')}]" if c.evidence else ""
            debate = " | ".join(f"{t.type}: {t.text}" for t in c.thread)
            lines.append(f"- ({c.status}, {c.kind}) {c.text}{cite}" + (f"\n    debate: {debate}" if debate else ""))
        system = (HOUSE_RULES + "Role: synthesizer. Write a 3-5 sentence verdict in Markdown for the person who pitched the idea. Lead with "
                  "the single most useful sentence in bold. Cite verified claims with their [n] marker. Present 'unverified_lead' items as "
                  "leads, not facts. Say plainly what is crowded and what is genuinely different. No score numbers, no hedging filler.")
        user = f"IDEA: {board.idea_text}\n\nSURVIVING CLAIMS:\n" + "\n".join(lines)
        try:
            res = await self.llm.chat(role=self.id, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                                      max_tokens=700, session=self.session(ctx), budget=ctx.budget)
            return res.text.strip(), res.meta()
        except LLMUnavailable as exc:
            await ctx.emit("error", {"message": f"summary unavailable: {exc}", "recoverable": True})
            return "\n".join(f"- {c.text}" for c in allowed), {}

    @staticmethod
    def _bootstrap_inputs(board, ents: list[Entity], stats: dict, pair: dict, overlap: float | None,
                          rcs: RCSResult | None) -> axes.BootstrapInputs:
        """Hand the scorer everything the point estimate was built from, so the band is the spread those
        inputs actually have rather than `8 + 40*jury_std`. No extra network calls: all of it is already here."""
        from app.search import calibration

        n = int(stats.get("corpus_n") or 0)
        p = pair or {}
        return axes.BootstrapInputs(
            sims=[e.similarity for e in ents],
            percentile=axes.corpus_percentile(),
            dkw=0.0 if calibration.is_placeholder() else calibration.get_cdf().epsilon(),
            rcs=rcs.nats_per_token if rcs else None,
            rcs_pct=axes.rcs_percentile(),
            rcs_dkw=0.0 if calibration.rcs_is_placeholder() else calibration.get_rcs_cdf().epsilon(),
            facet_term_dfs=stats.get("facet_term_dfs") or {},
            corpus_n=n,
            pair=(p["df_a"], p["df_b"], p["df_ab"]) if {"df_a", "df_b", "df_ab"} <= p.keys() else None,
            cliche_overlap=overlap,
            prior_sims=[float(x["similarity"]) for x in board.priors],
            rank_reference=None if calibration.headline_is_placeholder() else calibration.headline_percentile,
            rank_dkw=0.0 if calibration.headline_is_placeholder() else calibration.get_headline_cdf().epsilon(),
        )

    async def _surprisal(self, ctx: Ctx, ents: list[Entity]) -> RCSResult | None:
        """AXIS 1's second instrument: how many nats/token the nearest existing projects save when predicting
        this pitch. Returns None (and the axis says so) whenever the base model is not deployed or not well."""
        board = ctx.board
        if not ents:
            return None
        pitches, seen = [], set()
        for e in ents:
            for rid in e.records:
                rec = board.records.get(rid)
                text = (rec.pitch or rec.tagline or "") if rec else ""
                if text and rid not in seen:
                    seen.add(rid)
                    pitches.append(text)
                    break  # one write-up per resolved entity: a project on three sites is one neighbour
        if not pitches:
            return None
        try:
            from app.signals import surprisal

            if not surprisal.available():
                return None
            rcs = await surprisal.measure_rcs(board.idea_text, pitches)
        except Exception as exc:
            await ctx.emit("error", {"message": f"surprisal unavailable: {type(exc).__name__}: {exc}"[:200], "recoverable": True})
            return None
        if rcs is not None:
            await ctx.emit("surprisal.measured", rcs.as_detail())
        return rcs

    async def _corpus_stats(self, ctx: Ctx) -> dict:
        """Corpus-native maths from Elasticsearch: cliche terms (significant_text), crowding by year, facet frequencies."""
        board = ctx.board
        ids = [r.rid for r in board.records.values() if r.source in CORPUS]
        if not (get_settings().has_elastic and ids):
            return {}
        try:
            from app.search import rarity

            nb = await rarity.neighbourhood_stats(ids[:50])
            f = board.facets
            n = await rarity.corpus_size()
            names = [k for k in ("purpose", "mechanism", "audience", "twist") if getattr(f, k)]
            # One `filters` aggregation per facet gives every term's whole-index df; rarity then comes from the
            # term profile, not from one document count whose value tracked how long the phrase was.
            profiles = {k: await rarity.facet_profile(getattr(f, k), n) for k in names}
            return {
                "cliches": [TermStat(term=str(b.get("term") or b.get("key")), score=b.get("score"), neighbourhood_count=b.get("doc_count"),
                                     global_count=b.get("bg_count")) for b in nb.get("cliche_terms", [])],
                "by_year": [YearCount(year=int(y["year"]), count=int(y["count"])) for y in nb.get("by_year", []) if y.get("year") is not None],
                "neighbourhood_winners": nb.get("winners", 0),
                "corpus_n": n,
                "facet_rarities": {k: p["rarity"] for k, p in profiles.items() if p["rarity"] is not None},
                "facet_terms": {k: {"top": p["top_terms"], "unseen": p["unseen"], "n_terms": p["n_terms"]} for k, p in profiles.items()},
                "facet_term_dfs": {k: p["term_dfs"] for k, p in profiles.items()},
                # Both marginals, the joint and N in one place: NPMI needs the expectation, not just the joint.
                "pair": await rarity.pair_stats(f.purpose, f.mechanism) if (f.purpose and f.mechanism) else {},
            }
        except Exception as exc:
            await ctx.emit("error", {"message": f"corpus statistics unavailable: {type(exc).__name__}: {exc}"[:200], "recoverable": True})
            return {}


register("synthesizer")(Synthesizer)
