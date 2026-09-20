"""Verifier: no receipt, no claim. Holds a veto that is enforced in code, not by prompt.

Layer 1 (deterministic): the quoted text must actually appear in the source record.
Layer 2 (independent): GPTZero's bibliography scan checks the citations; status `fake` rejects the claim.
Also runs the Voice axis (GPTZero on the pitch) - a separate channel that never touches the originality score.
"""
from __future__ import annotations

import asyncio

from app.config import get_settings
from app.orchestration.host import Ctx, result
from app.orchestration.registry import register
from app.roles.base import BaseRole
from app.schemas import Verification, Voice
from app.signals.biblio import resolve_status
from app.signals.quote_check import quote_in_text

MIN_VOICE_CHARS = 250
# GPTZero checks citations serially: one scan took 3 s for 1 citation and 76 s for 7, past the client timeout, so a
# single combined document never finished inside the verifier's slot and no claim was ever resolved. One small
# document per claim, scanned in parallel, under a hard cap: whatever is not back by then keeps layer 1 only.
BIBLIO_BUDGET_S = 40.0
# GPTZero slows down sharply with concurrent scans (1 alone: 3-19 s; 3 at once: 32-46 s), so only the first claims
# (the critic lists the closest prior work first) get layer 2; the rest keep the local quote check.
BIBLIO_MAX_CLAIMS = 6


def _quote_in_text(quote: str, text: str) -> tuple[bool, str]:
    """Layer 1: tolerant containment (exact, then in-order fuzzy window). Returns (match, human-readable detail)."""
    m = quote_in_text(quote, text)
    return m.match, m.detail


def _final_status(v: Verification) -> str:
    """Both layers -> verified | unverified_lead | rejected. A citation GPTZero calls fake is rejected, unless we hold the
    source ourselves and the quote is in it: then the layers disagree and the claim is kept only as an unverified lead."""
    return resolve_status(v, trust_local_match_over_fake=True)


class Verifier(BaseRole):
    id = "verifier"
    purpose = "No receipt, no claim."
    phase = "verify"

    async def handle(self, msg: dict, ctx: Ctx) -> dict:
        kind = msg["payload"].get("kind", "claims")
        return await (self._voice(ctx) if kind == "voice" else self._claims(ctx))

    # -- Voice -------------------------------------------------------------------------------------------
    async def _voice(self, ctx: Ctx) -> dict:
        text = ctx.board.idea_text
        if len(text) < MIN_VOICE_CHARS:
            voice = Voice(too_short=True)
            ctx.board.set("voice", self.id, voice)
            await ctx.emit("voice.result", voice)
            return result(summary="pitch is under 250 characters: too short for a reliable read")
        try:
            from app.signals import gptzero

            doc = await gptzero.predict_text(text, bucket="interactive")
            if getattr(doc, "replayed", False):  # fixture data must never be presented as a real reading
                return result(summary="GPTZero is in replay mode (GPTZERO_MODE=replay): voice analysis skipped")
            voice = gptzero.to_voice(text, doc)
        except Exception as exc:  # ImportError, budget exceeded, network, auth
            await ctx.emit("error", {"message": f"voice analysis unavailable: {type(exc).__name__}: {exc}"[:200], "recoverable": True})
            return result(summary="voice analysis unavailable")
        voice = await self._second_opinion(text, voice)
        ctx.board.set("voice", self.id, voice)
        await ctx.emit("voice.result", voice)
        return result(summary=voice.result_message or "voice analysed")

    async def _second_opinion(self, text: str, voice: Voice) -> Voice:
        """Fast-DetectGPT on our own base model, so the panel has a detector that can contradict GPTZero.

        Silent no-op without a surprisal deployment, and without the human reference CDF it reports the raw
        statistic but refuses to turn it into a verdict."""
        try:
            from app.search import calibration
            from app.signals import surprisal

            if not surprisal.available():
                return voice
            curv = await surprisal.measure_curvature(text)
            if curv is None:
                return voice
            pct = None if calibration.curvature_is_placeholder() else calibration.curvature_percentile(curv.d)
            cls = surprisal.classify_curvature(pct)
            agreement = surprisal.detector_agreement(voice.predicted_class, cls)
            message = voice.result_message
            if agreement == "disagree":
                message = ("Our two detectors disagree on this pitch, so we are not calling it. "
                           f"GPTZero reads it as {voice.predicted_class}; our own base model reads it as {cls}.")
            return voice.model_copy(update={"curvature": round(curv.d, 4), "curvature_percentile": pct,
                                            "curvature_class": cls, "agreement": agreement, "result_message": message})
        except Exception:
            return voice  # a second opinion must never take the first one down

    # -- Claims ------------------------------------------------------------------------------------------
    async def _claims(self, ctx: Ctx) -> dict:
        board = ctx.board
        claims = [c for c in board.claims.values() if c.kind == "exists" and c.evidence]
        for c in claims:
            ev = board.evidence[c.evidence[0]]
            rec = board.records.get(ev.rid)
            text = " ".join(filter(None, [rec.title, rec.tagline, rec.pitch, rec.description])) if rec else ""
            ok, detail = _quote_in_text(ev.quote, text)
            ev.verification = Verification(local_quote_match=ok)
            board.put("evidence", self.id, ev.evid, ev)
            await ctx.emit("verify.result", {"cid": c.cid, "layer": "quote", "status": "match" if ok else "no_match", "detail": detail})
        await self._bibliography(ctx, claims)

        verified = rejected = 0
        for c in claims:
            v = board.evidence[c.evidence[0]].verification or Verification()
            c.status = _final_status(v)
            if c.status == "rejected":
                reason = "citation could not be found and the quote is not in any source we hold (caught hallucination)"
                rejected += 1
            elif c.status == "verified":
                reason = "quote matched its source" + (" and the citation checked out" if v.gptzero_status == "exist" else "")
                verified += 1
            elif v.gptzero_status == "fake":
                reason = "GPTZero could not find this citation although the quote is in the retrieved source: kept as an unverified lead"
            elif "contradict" in (v.stance or ""):
                reason = "an independent source contradicts this claim: kept as an unverified lead"
            else:
                reason = "quote not found in the source: kept only as an unverified lead"
            board.put("claims", self.id, c.cid, c)
            await ctx.emit("claim.resolved", {"cid": c.cid, "status": c.status, "reason": reason})
        return result(verified=verified, rejected=rejected, summary=f"{verified} verified, {rejected} rejected, {len(claims) - verified - rejected} unverified leads")

    async def _bibliography(self, ctx: Ctx, claims) -> None:
        """Layer 2: GPTZero bibliography scan, recorded on each Evidence. Any failure here degrades to layer 1 only."""
        if not claims or get_settings().gptzero_mode != "live":  # replay fixtures must never decide a real claim's fate
            return
        from app.signals import biblio

        async def scan_one(c) -> dict:
            ev = [ctx.board.evidence[c.evidence[0]]]
            scan = await biblio.bibliography_scan(biblio.build_document([c], ev))
            return {} if getattr(scan, "replayed", False) else biblio.map_results(scan, [c], ev)

        tasks = [asyncio.ensure_future(scan_one(c)) for c in claims[:BIBLIO_MAX_CLAIMS]]
        done, pending = await asyncio.wait(tasks, timeout=BIBLIO_BUDGET_S)
        for t in pending:
            t.cancel()
        verdicts: dict = {}
        failures = [t.exception() for t in done if t.exception() is not None]
        for t in done:
            if t.exception() is None:
                verdicts.update(t.result())
        if pending or failures:
            n = len(pending) + len(failures)
            reason = f"not back within {BIBLIO_BUDGET_S:.0f}s" if not failures else f"{type(failures[0]).__name__}: {failures[0]}"
            await ctx.emit("error", {"message": f"Citation check (GPTZero): {n} of {len(tasks)} claims {reason}; the quote check "
                                                f"decides {'it' if n == 1 else 'those'}"[:220], "recoverable": True})
        for c in claims:
            v = verdicts.get(c.cid)
            if v is None:
                continue
            ev = ctx.board.evidence[c.evidence[0]]
            ev.verification = Verification(local_quote_match=(ev.verification or Verification()).local_quote_match,
                                           gptzero_status=v.gptzero_status, stance=v.stance, justification=v.justification)
            ctx.board.put("evidence", self.id, ev.evid, ev)
            await ctx.emit("verify.result", {"cid": c.cid, "layer": "gptzero", "status": v.gptzero_status or "unknown",
                                             "detail": v.justification or (f"source stance: {v.stance}" if v.stance else "no verdict")})


register("verifier")(Verifier)
