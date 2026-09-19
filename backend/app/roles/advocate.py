"""Advocate: answers every 'exists' claim by conceding, distinguishing by facet, or challenging the evidence.

Runs on a different model family from the critic so the two do not share blind spots.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.orchestration.host import Ctx, result
from app.orchestration.registry import register
from app.roles.base import HOUSE_RULES, BaseRole
from app.schemas import Claim, ThreadEntry


class Response(BaseModel):
    cid: str
    type: Literal["CONCEDE", "REBUTTAL", "CHALLENGE"]
    text: str = Field(max_length=320)


class Difference(BaseModel):
    text: str = Field(max_length=260, description="a concrete way the idea differs from ALL the prior work shown")
    facet: str


class Defence(BaseModel):
    responses: list[Response]
    differences: list[Difference] = Field(default_factory=list)


class Advocate(BaseRole):
    id = "advocate"
    purpose = "Same words are not the same idea."
    phase = "debate"

    async def handle(self, msg: dict, ctx: Ctx) -> dict:
        board = ctx.board
        claims = [c for c in board.claims.values() if c.kind == "exists" and c.status == "proposed"]
        if not claims:
            return result(summary="nothing to answer")
        f = board.facets
        listing = "\n".join(f"{c.cid}: {c.text}\n   QUOTE: \"{board.evidence[c.evidence[0]].quote}\"" for c in claims if c.evidence)
        system = (HOUSE_RULES + "Role: advocate for the idea. For EACH claim choose exactly one: CONCEDE (it really is the same), "
                  "REBUTTAL (same purpose but name the facet that differs: mechanism, audience, data or twist), or CHALLENGE "
                  "(the quote does not support the claim). Be honest: concede when the critic is right. Then list up to 3 concrete "
                  "differences that hold against all the prior work shown. Do not claim a difference the evidence cannot support.")
        user = f"IDEA: {board.idea_text}\nFACETS: purpose={f.purpose} | mechanism={f.mechanism} | audience={f.audience} | twist={f.twist}\n\nCLAIMS:\n{listing}"
        defence, res = await self.llm.structured(role=self.id, system=system, user=user, schema=Defence, session=self.session(ctx), budget=ctx.budget)

        for r in defence.responses:
            claim = board.claims.get(r.cid)
            if claim is None:
                continue
            claim.thread.append(ThreadEntry(frm=self.id, type=r.type, text=r.text))
            claim.status = "conceded" if r.type == "CONCEDE" else "challenged"
            board.put("claims", self.id, claim.cid, claim)
            await ctx.emit("claim.challenged", {"cid": r.cid, "by": self.id, "challenge_type": r.type, "text": r.text}, **res.meta())
        for d in defence.differences[:3]:
            claim = Claim(cid=f"d{sum(1 for c in board.claims.values() if c.kind == 'differs') + 1}", kind="differs",
                          text=d.text.strip(), by=self.id, status="unverified_lead")
            board.put("claims", self.id, claim.cid, claim)
            await ctx.emit("claim.proposed", {"claim": claim.model_dump(mode="json"), "facets": [d.facet]}, **res.meta())
        conceded = sum(1 for r in defence.responses if r.type == "CONCEDE")
        return result(summary=f"{conceded} conceded, {len(defence.responses) - conceded} contested, {len(defence.differences[:3])} differences")


register("advocate")(Advocate)
