"""Actuator: an answer that doesn't act is a report. Proposes actions by confidence; anything that writes outside
this process (arming a watch, writing to the corpus) only runs after an explicit user click (`confirmed`).
"""
from __future__ import annotations

import datetime as dt

from app.config import get_settings
from app.llm.router import LLMUnavailable
from app.orchestration.host import Ctx, error, result
from app.orchestration.registry import register
from app.roles.base import HOUSE_RULES, BaseRole


class Actuator(BaseRole):
    id = "actuator"
    purpose = "An answer that doesn't act is a report."
    phase = "act"

    async def handle(self, msg: dict, ctx: Ctx) -> dict:
        p = msg["payload"]
        action = p.get("action")
        if not action:
            return await self._propose(ctx)
        if action in ("arm_watch", "writeback") and not p.get("confirmed"):
            return error(f"{action} needs an explicit user confirmation")
        handler = {"arm_watch": self._arm_watch, "writeback": self._writeback, "draft_pitch": self._draft_pitch}[action]
        try:
            detail = await handler(ctx, p)
            await ctx.emit("action.done", {"action": action, "ok": True, "detail": detail})
            return result(action=action, detail=detail)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"[:240]
            await ctx.emit("action.done", {"action": action, "ok": False, "detail": detail})
            return error(detail, action=action)

    async def _propose(self, ctx: Ctx) -> dict:
        s, scores = get_settings(), ctx.board.scores
        proposals = [("draft_pitch", "Draft a differentiated pitch from the best mutation", False)]
        if s.has_elastic:
            proposals.insert(0, ("arm_watch", "Watch for new look-alikes (re-checked on a schedule; alerts to Slack)", True))
            if scores and not scores.abstain.active:  # don't pollute the corpus with ideas we could not even assess
                proposals.append(("writeback", "Add this idea to the corpus so the next search can find it", True))
        for action, label, click in proposals:
            await ctx.emit("action.proposed", {"action": action, "label": label, "requires_click": click})
        return result(actions=[a for a, _, _ in proposals], summary=f"{len(proposals)} actions proposed")

    async def _arm_watch(self, ctx: Ctx, p: dict) -> str:
        from app.search.es import get_async_es

        s, f = get_settings(), ctx.board.facets
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        doc = {"run_id": ctx.run_id, "idea_text": ctx.board.idea_text, "facets_query": f"{f.purpose} {f.mechanism}"[:300],
               "threshold": float(p.get("threshold", 0.55)), "active": True, "armed_at": now, "last_checked_at": now}
        await get_async_es().index(index=s.es_watches_index, id=ctx.run_id, document=doc)
        return f"Watch armed in {s.es_watches_index}; the scheduled workflow re-checks it and alerts on new look-alikes."

    async def _writeback(self, ctx: Ctx, p: dict) -> str:
        from app.search.es import get_async_es

        s, board = get_settings(), ctx.board
        now = dt.datetime.now(dt.timezone.utc)
        text = board.idea_text[:1500]
        doc = {"rid": f"idea:{ctx.run_id}", "source": "web", "url": f"whitespace://runs/{ctx.run_id}", "title": board.facets.purpose[:120],
               "description": board.idea_text, "pitch": text, "semantic_pitch": text, "year": now.year, "date": now.date().isoformat(),
               "date_precision": "day", "tags": ["whitespace-user-idea"], "status": "unknown", "has_semantic": True, "first_seen_at": now.isoformat()}
        await get_async_es().index(index=s.es_index, id=doc["rid"], document=doc)
        return "Idea written back to the corpus; the next person with this idea will find it."

    async def _draft_pitch(self, ctx: Ctx, p: dict) -> str:
        board = ctx.board
        mu = board.mutations.get(p.get("mid") or "") or max(board.mutations.values(), key=lambda m: m.delta or 0, default=None)
        differs = [c.text for c in board.claims.values() if c.kind == "differs"]
        system = (HOUSE_RULES + "Role: pitch writer. Rewrite the idea as a 90-word pitch that leads with what is genuinely different from the "
                  "prior work. Plain, specific language. No buzzwords, no claims the evidence cannot support.")
        user = (f"ORIGINAL: {board.idea_text}\nCHOSEN CHANGE: {mu.frm} -> {mu.to} ({mu.rationale})" if mu else f"ORIGINAL: {board.idea_text}") + f"\nDIFFERENCES: {differs}"
        try:
            res = await self.llm.chat(role=self.id, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                                      max_tokens=400, temperature=0.6, session=self.session(ctx), budget=ctx.budget)
        except LLMUnavailable as exc:
            raise RuntimeError(f"no LLM available: {exc}") from exc
        return res.text.strip()


register("actuator")(Actuator)
