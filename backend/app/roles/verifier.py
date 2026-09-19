"""Verifier: no receipt, no claim. Holds a veto that is enforced in code, not by prompt.

Layer 1 (deterministic): the quoted text must actually appear in the source record.
Layer 2 (independent): GPTZero's bibliography scan checks the citations; status `fake` rejects the claim.
Also runs the Voice axis (GPTZero on the pitch) - a separate channel that never touches the originality score.
"""
from __future__ import annotations

import re

from app.config import get_settings
from app.orchestration.host import Ctx, result
from app.orchestration.registry import register
from app.roles.base import BaseRole
from app.schemas import Verification, Voice

MIN_VOICE_CHARS = 250


def _norm(text: str) -> str:
    text = text.lower().translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"}))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _quote_in_text(quote: str, text: str) -> tuple[bool, str]:
    """Layer 1. Returns (match, human-readable detail)."""
    try:
        from app.signals.quote_check import quote_in_text  # tolerant containment: exact, then in-order fuzzy window

        m = quote_in_text(quote, text)
        return m.match, m.detail
    except ImportError:
        q = _norm(quote)
        ok = bool(q) and q in _norm(text)
        return ok, "quote found in the source record" if ok else "quote does NOT appear in the source record"


def _final_status(v: Verification) -> str:
    """Both layers -> verified | unverified_lead | rejected. A citation GPTZero calls fake is rejected, unless we hold the
    source ourselves and the quote is in it: then the layers disagree and the claim is kept only as an unverified lead."""
    try:
        from app.signals.biblio import resolve_status

        return resolve_status(v, trust_local_match_over_fake=True)
    except ImportError:
        if v.gptzero_status == "fake":
            return "unverified_lead" if v.local_quote_match else "rejected"
        return "verified" if (v.local_quote_match and "contradict" not in (v.stance or "")) else "unverified_lead"


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
        ctx.board.set("voice", self.id, voice)
        await ctx.emit("voice.result", voice)
        return result(summary=voice.result_message or "voice analysed")

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
        try:
            from app.signals import biblio

            evidence = [ctx.board.evidence[c.evidence[0]] for c in claims]
            scan = await biblio.bibliography_scan(biblio.build_document(claims, evidence))
            verdicts = biblio.map_results(scan, claims, evidence)
        except Exception as exc:
            await ctx.emit("error", {"message": f"GPTZero bibliography scan unavailable, relying on the quote check: {type(exc).__name__}: {exc}"[:220], "recoverable": True})
            return
        if getattr(scan, "replayed", False):
            return
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
