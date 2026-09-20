"""Inspector: opens the closest prior art's own site in a cloud browser and reports what is there today."""
from __future__ import annotations

from urllib.parse import urlparse

from app.config import RUNS_DIR
from app.orchestration.host import Ctx, error, result
from app.orchestration.registry import register
from app.roles.base import BaseRole
from app.schemas import Conflict, ConflictValue, Entity, SiteCheck, SourceRecord
from app.sources import browserbase
from app.sources.http import SourceError
from app.wrangle.reliability import reliability

MAX_SITES = 3  # one browser session, visited in turn: three sites is ~15 s, and the demo shows the top of the list anyway
LOOK_AT = 8
RENDER_RELIABILITY = 0.95  # we looked, today; a listing recorded it once
GONE = ("dead", "parked")
SHOTS_DIR = RUNS_DIR / "shots"


def site_of(ent: Entity, records: dict[str, SourceRecord]) -> tuple[SourceRecord, str] | None:
    """The entity's own product site: an outbound link of any of its records, or the page itself for an open-web hit."""
    for rid in ent.records:
        rec = records.get(rid)
        if rec and (url := browserbase.product_site([*rec.links, *([rec.url] if rec.source == "web" else [])])):
            return rec, url
    return None


def contradiction(ent: Entity, rec: SourceRecord, status: str, records: dict[str, SourceRecord]) -> Conflict | None:
    """'The listing says active, the site is gone' (or the reverse). A blocked site contradicts nothing: we did not see it."""
    listed = ent.fields.get("status")
    if not listed or not ((listed.value == "active" and status in GONE) or (listed.value == "dead" and status == "alive")):
        return None
    src = records.get(listed.provenance[0]) if listed.provenance else None
    return Conflict(field="status", resolution="dead" if status in GONE else "active",
                    rule="a render of the live site today outranks what a listing recorded",
                    values=[ConflictValue(value=f"site {status}", rid=rec.rid, reliability=RENDER_RELIABILITY),
                            ConflictValue(value=listed.value, rid=src.rid if src else rec.rid,
                                          reliability=reliability("status", src.source) if src else 0.5)])


class Inspector(BaseRole):
    id = "inspector"
    purpose = "A listing is a claim. I go and look."
    phase = "verify"

    async def handle(self, msg: dict, ctx: Ctx) -> dict:
        board = ctx.board
        targets = [(ent, *hit) for ent in board.top_entities(LOOK_AT) if (hit := site_of(ent, board.records))][:MAX_SITES]
        if not targets:
            return result(checked=0, summary="none of the closest prior art links to a site of its own")
        hosts = ", ".join(urlparse(url).hostname or url for _, _, url in targets)
        await ctx.emit("tool.call", {"tool": "browserbase.render", "args_summary": hosts[:120]})
        try:
            renders = await browserbase.render([url for _, _, url in targets])
        except SourceError as exc:  # no browser is a gap in the evidence, not a reason to stop the run
            await ctx.emit("error", {"message": f"evidence browser unavailable: {exc}", "recoverable": True})
            return error(str(exc))

        for (ent, rec, url), r in zip(targets, renders):
            status, why = browserbase.classify(r)
            shot = None
            if r.screenshot and status != "blocked":  # a picture of someone's challenge page is not evidence
                SHOTS_DIR.mkdir(parents=True, exist_ok=True)
                (SHOTS_DIR / f"{ctx.run_id}-{ent.eid}.jpg").write_bytes(r.screenshot)
                shot = f"/api/runs/{ctx.run_id}/shots/{ent.eid}.jpg"
            check = SiteCheck(eid=ent.eid, rid=rec.rid, url=url, final_url=r.final_url, status=status,
                              why="; ".join([why, *r.notes]), http_status=r.http_status, title=r.title, excerpt=r.text[:600],
                              screenshot=shot, elapsed_ms=r.elapsed_ms, conflict=contradiction(ent, rec, status, board.records))
            board.put("sites", self.id, ent.eid, check)
            await ctx.emit("site.checked", {"eid": ent.eid, "site": check.model_dump(mode="json")})
            if check.conflict:
                await ctx.emit("conflict.detected", {"eid": ent.eid, "conflict": check.conflict.model_dump(mode="json")})
        tally = {s: sum(c.status == s for c in board.sites.values()) for s in ("alive", "dead", "parked", "blocked")}
        summary = f"{len(renders)} sites rendered: " + ", ".join(f"{n} {s}" for s, n in tally.items() if n)
        await ctx.emit("tool.result", {"tool": "browserbase.render", "summary": summary, "n_hits": len(renders)})
        return result(checked=len(renders), summary=summary)


register("inspector")(Inspector)
