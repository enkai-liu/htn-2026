"""Generate backend/fixtures/mock_run.jsonl: a schema-valid, fully fictional run for UI work and replay.

All projects, quotes and numbers here are INVENTED fixture data (run.started carries mock=true).
Real demo runs are recorded from live runs with scripts/record_golden.py.

    backend/.venv/bin/python backend/fixtures/make_mock_run.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas import (  # noqa: E402
    Abstain,
    AgentEvent,
    AxisScore,
    Claim,
    Conflict,
    ConflictValue,
    Entity,
    Evidence,
    FacetOverlap,
    Facets,
    FusedField,
    GraphLink,
    GraphNode,
    GraphPatch,
    JurorVote,
    MergeDecision,
    Mutation,
    Report,
    Scores,
    SourceRecord,
    SourceStatus,
    TermStat,
    ThreadEntry,
    Verification,
    Voice,
    VoiceSentence,
    YearCount,
)

RUN_ID = "mock"
T0 = 1_790_000_000.0
OUT = Path(__file__).with_name("mock_run.jsonl")

IDEA = (
    "Whitespace checks how original your hackathon idea is before you build it. You paste a pitch, and a team "
    "of AI agents searches hundreds of thousands of past hackathon projects, startups and repos for prior art, "
    "argues about whether it is really the same idea, verifies every claim against its source, and then "
    "suggests concrete changes that move your idea into emptier territory, re-scoring each suggestion live."
)

FLASH, PRO, GLM, GLMF, KIMI, OSS = (
    "deepseek-ai/DeepSeek-V4-Flash-0731",
    "deepseek-ai/DeepSeek-V4-Pro",
    "zai-org/GLM-5.3",
    "zai-org/GLM-5.3-Flash",
    "moonshotai/Kimi-K2.6",
    "openai/gpt-oss-120b",
)


class Rec:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []
        self.t = T0

    def emit(self, dt, agent, phase, type, data=None, *, to=None, model=None, latency=None, tok=None, cost=None):
        self.t += dt
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="json")
        ev = AgentEvent(
            seq=len(self.events) + 1, run_id=RUN_ID, ts=round(self.t, 3), agent=agent, to=to, phase=phase,
            type=type, data=data or {}, model=model, provider="baseten" if model else None,
            latency_ms=latency, tokens={"in": tok[0], "out": tok[1]} if tok else None, cost_usd=cost,
        )
        self.events.append(ev)
        return ev


def rec(rid, source, title, tagline, pitch, year, tags, tech, url, *, status="unknown", traction=None, links=None,
        score=0.5, prov=None, gz=None):
    return SourceRecord(
        rid=rid, source=source, url=url, title=title, tagline=tagline, description=pitch, pitch=pitch, year=year,
        date_precision="year", tags=tags, tech=tech, status=status, traction=traction or {}, links=links or [],
        lang="en", field_provenance=prov or {}, retrieval={"leg": "hybrid", "rerank_score": score}, gptzero=gz,
    )


RECORDS = [
    rec("devpost:idearadar", "devpost", "IdeaRadar", "Is your hack already on Devpost?",
        "IdeaRadar takes a hackathon idea, extracts keywords with an LLM and searches Devpost for similar "
        "projects, then returns an originality score out of 100.", 2024, ["ai", "hackathon", "search"],
        ["react", "flask", "openai"], "https://example.org/devpost/idearadar", traction={"is_winner": True},
        links=["https://example.org/github/idearadar"], score=0.91),
    rec("github:acme/idearadar", "github", "acme/idearadar", "Hackathon idea uniqueness checker",
        "Keyword-based Devpost similarity search with a GPT scoring prompt.", 2024, ["hackathon"], [],
        "https://example.org/github/idearadar", status="dormant", traction={"stars": 14, "pushed_at": "2024-04-02"},
        score=0.84, prov={"tech": "imputed"}),
    rec("devpost:hackcheck", "devpost", "HackCheck", "Originality scores for judges",
        "Judges paste a Devpost link; HackCheck finds look-alike submissions and flags likely recycled projects.",
        2023, ["judging", "plagiarism", "nlp"], ["nextjs", "postgres", "openai"],
        "https://example.org/devpost/hackcheck", traction={"is_winner": True}, score=0.88),
    rec("devpost:noveltylens", "devpost", "NoveltyLens", "Semantic search over winning hacks",
        "Embeds winning hackathon projects and lets you search them semantically for inspiration.", 2023,
        ["search", "embeddings"], ["python", "chroma"], "https://example.org/devpost/noveltylens", score=0.71),
    rec("yc:pitchprobe", "yc", "PitchProbe", "Validate startup ideas in 60 seconds",
        "PitchProbe scans the web for competitors and produces a market viability report for founders.", 2025,
        ["b2b", "market-research"], [], "https://example.org/yc/pitchprobe", status="active",
        traction={"batch": "W25"}, links=["https://pitchprobe.example.org"], score=0.64),
    rec("hn:40000001", "hn", "Show HN: PitchProbe – find out who already built your idea", None,
        "Show HN thread. Commenters note it measures market crowding, not novelty of the idea itself.", 2025,
        [], [], "https://example.org/hn/40000001", traction={"points": 212, "comments": 97},
        links=["https://pitchprobe.example.org"], score=0.6),
    rec("devpost:copycatch", "devpost", "CopyCatch", "A plagiarism detector for hackers",
        "Compares submitted code and write-ups against earlier hackathon repos to catch reused projects.", 2022,
        ["plagiarism", "code-similarity"], ["python"], "https://example.org/devpost/copycatch", score=0.58),
    rec("github:lab/idea-novelty", "github", "lab/idea-novelty", "Research-idea novelty checker (paper code)",
        "Retrieve-then-rerank pipeline that judges the novelty of research ideas against the literature.", 2025,
        ["research", "rag"], ["python"], "https://example.org/github/idea-novelty", status="active",
        traction={"stars": 310, "pushed_at": "2026-06-11"}, score=0.55),
    rec("devpost:studysage", "devpost", "StudySage", "Your AI study buddy",
        "Upload notes and chat with an AI tutor that makes flashcards.", 2025, ["education", "rag", "chatbot"],
        ["nextjs", "openai", "pinecone"], "https://example.org/devpost/studysage", score=0.22,
        gz={"predicted_class": "ai", "confidence_category": "high", "subclass": "pure_ai",
            "ai_sentence_share": 0.92, "result_message": "Our detector is highly confident that the text is AI generated."}),
]
BY_RID = {r.rid: r for r in RECORDS}


def node_for(r: SourceRecord, eid: str, badges=None) -> GraphNode:
    return GraphNode(id=f"ent:{eid}", kind="entity", label=r.title, source=r.source,
                     similarity=r.retrieval["rerank_score"], year=r.year, url=r.url, badges=badges or [],
                     val=1 + 4 * r.retrieval["rerank_score"])


def build() -> list[AgentEvent]:
    R = Rec()
    e = R.emit

    # ---- plan -------------------------------------------------------------------------------------------
    e(0.0, "conductor", "plan", "run.started", {"idea_text": IDEA, "orchestrator": "asyncio", "replay": True, "mock": True})
    e(0.2, "conductor", "plan", "agent.started", {"purpose": "Decompose, staff, replan."})
    facets = Facets(
        purpose="tell a hacker whether their project idea has been done before",
        mechanism="multi-agent retrieval, debate and claim verification over a large prior-art corpus",
        audience="hackathon participants and early founders", data="past hackathon write-ups, startup directories, repos",
        twist="coaches you toward whitespace and re-scores each suggestion against evidence",
        domain="developer-tools", keywords=["originality", "hackathon", "idea", "prior art", "novelty"],
    )
    e(1.6, "conductor", "plan", "facets.extracted", {"facets": facets.model_dump()}, model=GLMF, latency=1480, tok=(620, 210), cost=0.0002)
    e(0.1, "conductor", "plan", "graph.patch", GraphPatch(
        add_nodes=[GraphNode(id="idea", kind="idea", label="Your idea", val=8)]
        + [GraphNode(id=f"facet:{k}", kind="facet", label=getattr(facets, k)[:48], val=2.5)
           for k in ("purpose", "mechanism", "audience", "data", "twist")],
        add_links=[GraphLink(source="idea", target=f"facet:{k}", kind="has_facet")
                   for k in ("purpose", "mechanism", "audience", "data", "twist")]))
    e(0.4, "conductor", "plan", "team.formed", {
        "team": [{"agent": a, "purpose": p} for a, p in [
            ("scout.devpost", "260k hackathon projects (Elasticsearch hybrid search)"),
            ("scout.yc", "6k YC companies (Elasticsearch hybrid search)"),
            ("scout.github", "live GitHub repository search"), ("scout.hn", "live Hacker News search"),
            ("resolver", "Four listings, one project."), ("critic", "This has been done. Prove me wrong."),
            ("advocate", "Same words are not the same idea."), ("judge", "Count the votes, measure the split."),
            ("verifier", "No receipt, no claim."), ("synthesizer", "Only what survived."),
            ("mutator", "Move one facet into the whitespace."), ("actuator", "An answer that doesn't act is a report.")]],
        "skipped": [{"agent": "scout.arxiv", "why": "the idea is a product, not a research contribution"}]})
    voice = Voice(
        predicted_class="human", confidence_category="medium",
        result_message="Our detector is moderately confident that the text is written by a human.",
        ai_sentence_share=0.0, neighbourhood_slop_share=None,
        sentences=[VoiceSentence(text=s.strip() + ".", start=IDEA.find(s.strip()), end=IDEA.find(s.strip()) + len(s.strip()) + 1, flagged=False)
                   for s in IDEA.split(".") if s.strip()])
    e(0.9, "verifier", "verify", "voice.result", voice, latency=410)

    # ---- scout ------------------------------------------------------------------------------------------
    for s in ("devpost", "yc", "github", "hn"):
        e(0.05, "conductor", "scout", "message.sent", {"mid": f"m-task-{s}", "msg_type": "TASK", "to": f"scout.{s}",
          "summary": "find prior art for 3 queries: full idea, purpose+mechanism, twist"}, to=f"scout.{s}")
        e(0.05, f"scout.{s}", "scout", "agent.started", {"purpose": "If it was built, I find it."})
    e(0.6, "scout.devpost", "scout", "tool.call", {"tool": "originality.hybrid_prior_art (MCP)", "args_summary": "q=full idea, k=25"})
    e(0.1, "scout.yc", "scout", "tool.call", {"tool": "es.hybrid_search", "args_summary": "source=yc, q=purpose+mechanism"})
    e(0.1, "scout.github", "scout", "tool.call", {"tool": "github.search_repositories", "args_summary": "hackathon idea originality checker"})
    e(0.1, "scout.hn", "scout", "tool.call", {"tool": "hn.algolia_search", "args_summary": "idea validator show hn"})
    e(1.9, "scout.devpost", "scout", "tool.result", {"tool": "originality.hybrid_prior_art (MCP)", "summary": "BM25 + Jina semantic via RRF, reranked by Jina v3", "n_hits": 25})

    eid_of = {"devpost:idearadar": "e1", "github:acme/idearadar": "e1b", "devpost:hackcheck": "e2", "devpost:noveltylens": "e3",
              "yc:pitchprobe": "e4", "hn:40000001": "e4b", "devpost:copycatch": "e5", "github:lab/idea-novelty": "e6", "devpost:studysage": "e7"}

    def found(dt, agent, rid):
        r = BY_RID[rid]
        e(dt, agent, "scout", "evidence.found", {"record": r.model_dump(mode="json")})
        badges = (["winner"] if r.traction.get("is_winner") else []) + (["ai_written"] if r.gptzero and r.gptzero.predicted_class == "ai" else [])
        e(0.02, agent, "scout", "graph.patch", GraphPatch(add_nodes=[node_for(r, eid_of[rid], badges)],
          add_links=[GraphLink(source="idea", target=f"ent:{eid_of[rid]}", kind="similar", weight=r.retrieval["rerank_score"])]))

    for rid in ("devpost:idearadar", "devpost:hackcheck", "devpost:noveltylens"):
        found(0.35, "scout.devpost", rid)
    e(0.3, "scout.yc", "scout", "tool.result", {"tool": "es.hybrid_search", "summary": "1 company above the rerank threshold", "n_hits": 1})
    found(0.2, "scout.yc", "yc:pitchprobe")
    e(0.4, "scout.github", "scout", "tool.result", {"tool": "github.search_repositories", "summary": "2 relevant of 919 total", "n_hits": 2})
    found(0.2, "scout.github", "github:acme/idearadar")
    found(0.3, "scout.github", "github:lab/idea-novelty")
    found(0.3, "scout.devpost", "devpost:copycatch")
    found(0.25, "scout.devpost", "devpost:studysage")
    e(3.8, "scout.hn", "scout", "source.failed", {"source": "hn", "error": "timeout after 8s (2 retries); circuit open", "reassigned_to": None})
    e(0.1, "scout.hn", "scout", "agent.finished", {"ok": False, "summary": "source failed; confidence will be reduced"})
    e(0.1, "conductor", "scout", "message.sent", {"mid": "m-retry-hn", "msg_type": "REPLAN", "to": "scout.hn", "summary": "one broadened retry, then degrade"}, to="scout.hn")
    e(2.4, "scout.hn", "scout", "tool.result", {"tool": "hn.algolia_search", "summary": "retry succeeded with a broadened query", "n_hits": 1})
    found(0.2, "scout.hn", "hn:40000001")
    for s, n in (("devpost", 5), ("yc", 1), ("github", 2)):
        e(0.05, f"scout.{s}", "scout", "agent.finished", {"ok": True, "summary": f"{n} records"}, model=FLASH, latency=900, tok=(1400, 260), cost=0.0003)
    e(0.2, "conductor", "scout", "budget.updated", {"calls": 11, "tokens": 9800, "cost_usd": 0.004, "elapsed_s": 17.0, "degraded": False})

    # ---- resolve ----------------------------------------------------------------------------------------
    e(0.3, "resolver", "resolve", "agent.started", {"purpose": "Four listings, one project."})
    m1 = MergeDecision(a="devpost:idearadar", b="github:acme/idearadar", verdict="same",
                       signals={"url_xref": True, "name_sim": 1.0}, rationale="Devpost 'Try it out' link points at this repository.")
    ent1 = Entity(
        eid="e1", canonical_name="IdeaRadar", summary="Keyword-based Devpost similarity search with an LLM originality score.",
        records=[m1.a, m1.b], sources=["devpost", "github"], merges=[m1], similarity=0.91,
        conflicts=[Conflict(field="status", values=[ConflictValue(value="active (live demo link)", rid=m1.a, reliability=0.6),
                                                    ConflictValue(value="dormant (no push since 2024-04)", rid=m1.b, reliability=0.95)],
                            resolution="dormant", rule="github.pushed_at outranks self-reported Devpost copy")],
        fields={"tech": FusedField(value=["react", "flask", "openai"], provenance=[m1.a], imputed=False),
                "status": FusedField(value="dormant", provenance=[m1.b]),
                "last_activity": FusedField(value="2024-04-02", provenance=[m1.b])})
    e(1.1, "resolver", "resolve", "entity.merged", {"entity": ent1.model_dump(mode="json"), "rids": ent1.records, "verdict": "same"})
    e(0.05, "resolver", "resolve", "graph.patch", GraphPatch(remove_nodes=["ent:e1b"], update_nodes=[{"id": "ent:e1", "badges": ["winner", "merged", "conflict"], "val": 5.5}]))
    e(0.2, "resolver", "resolve", "conflict.detected", {"eid": "e1", "conflict": ent1.conflicts[0].model_dump(mode="json")})
    m2 = MergeDecision(a="yc:pitchprobe", b="hn:40000001", verdict="same", signals={"url_xref": True, "name_sim": 0.74},
                       model=FLASH, rationale="Both link to pitchprobe.example.org; the HN post is the launch thread.")
    ent4 = Entity(eid="e4", canonical_name="PitchProbe", summary="Startup idea validator focused on market viability.",
                  records=[m2.a, m2.b], sources=["yc", "hn"], merges=[m2], similarity=0.64,
                  fields={"status": FusedField(value="active", provenance=[m2.a]),
                          "tech": FusedField(value=["web-scraping", "llm"], provenance=[m2.b], imputed=True)})
    e(1.3, "resolver", "resolve", "entity.merged", {"entity": ent4.model_dump(mode="json"), "rids": ent4.records, "verdict": "same"},
      model=FLASH, latency=1210, tok=(1900, 240), cost=0.0004)
    e(0.05, "resolver", "resolve", "graph.patch", GraphPatch(remove_nodes=["ent:e4b"], update_nodes=[{"id": "ent:e4", "badges": ["merged", "imputed"]}]))
    m3 = MergeDecision(a="devpost:hackcheck", b="devpost:copycatch", verdict="insufficient_evidence",
                       signals={"url_xref": False, "name_sim": 0.31, "desc_sim": 0.72}, model=FLASH,
                       rationale="Similar purpose, different teams and years; nothing links them.")
    e(0.9, "resolver", "resolve", "entity.merged", {"entity": Entity(eid="e2", canonical_name="HackCheck", records=[m3.a], sources=["devpost"],
      merges=[m3], possible_same_as=["e5"], similarity=0.88).model_dump(mode="json"), "rids": [m3.a], "verdict": "insufficient_evidence"})
    e(0.05, "resolver", "resolve", "graph.patch", GraphPatch(add_links=[GraphLink(source="ent:e2", target="ent:e5", kind="possible_same_as", weight=0.72)]))
    e(0.2, "resolver", "resolve", "agent.finished", {"ok": True, "summary": "9 records -> 7 entities; 2 merges, 1 left open, 1 conflict, 1 imputed field"})

    # ---- debate -----------------------------------------------------------------------------------------
    evs = [
        Evidence(evid="ev1", eid="e1", rid="devpost:idearadar", url=BY_RID["devpost:idearadar"].url,
                 quote="extracts keywords with an LLM and searches Devpost for similar projects",
                 citation='[1] IdeaRadar team. "IdeaRadar." Devpost. 2024. https://example.org/devpost/idearadar'),
        Evidence(evid="ev2", eid="e2", rid="devpost:hackcheck", url=BY_RID["devpost:hackcheck"].url,
                 quote="Judges paste a Devpost link; HackCheck finds look-alike submissions",
                 citation='[2] HackCheck team. "HackCheck." Devpost. 2023. https://example.org/devpost/hackcheck'),
        Evidence(evid="ev3", eid="e4", rid="hn:40000001", url=BY_RID["hn:40000001"].url,
                 quote="it measures market crowding, not novelty of the idea itself",
                 citation='[3] "Show HN: PitchProbe." Hacker News. 2025. https://example.org/hn/40000001'),
    ]
    e(0.4, "critic", "debate", "agent.started", {"purpose": "This has been done. Prove me wrong."})
    c1 = Claim(cid="c1", kind="exists", by="critic", evidence=["ev1"], text="IdeaRadar (2024) already scores hackathon-idea originality against Devpost.")
    c2 = Claim(cid="c2", kind="exists", by="critic", evidence=["ev2"], text="HackCheck (2023) already detects look-alike hackathon submissions.")
    c3 = Claim(cid="c3", kind="exists", by="critic", evidence=["ev3"], text="PitchProbe already validates ideas against existing competitors.")
    for i, c in enumerate((c1, c2, c3)):
        e(1.2 if i == 0 else 0.5, "critic", "debate", "claim.proposed", {"claim": c.model_dump(mode="json")}, model=PRO, latency=2300, tok=(3100, 380), cost=0.004)
    e(0.4, "critic", "debate", "requery.issued", {"reason": "need to know whether any prior tool coaches the user, not just scores", "facet": "twist",
      "query": "suggest changes to make hackathon idea more original", "to": "scout.devpost"}, to="scout.devpost")
    e(0.1, "critic", "debate", "message.sent", {"mid": "m-req-1", "msg_type": "REQUEST_EVIDENCE", "to": "scout.devpost", "summary": "twist facet: coaching / re-scoring"}, to="scout.devpost")
    e(1.8, "scout.devpost", "debate", "tool.result", {"tool": "originality.combination_rarity (MCP)", "summary": "purpose AND coaching: 0 projects; purpose alone: 143", "n_hits": 0})
    e(0.3, "advocate", "debate", "agent.started", {"purpose": "Same words are not the same idea."})
    e(1.4, "advocate", "debate", "claim.challenged", {"cid": "c1", "by": "advocate", "challenge_type": "REBUTTAL",
      "text": "Concede the purpose overlaps. The mechanism differs: keyword search and one LLM opinion versus hybrid retrieval, entity resolution and verified claims."},
      model=GLM, latency=2100, tok=(2900, 300), cost=0.005)
    e(0.5, "advocate", "debate", "claim.challenged", {"cid": "c2", "by": "advocate", "challenge_type": "REBUTTAL",
      "text": "HackCheck serves judges after submission; this serves hackers before they build. Different audience and moment."}, model=GLM)
    e(0.5, "advocate", "debate", "claim.challenged", {"cid": "c3", "by": "advocate", "challenge_type": "CONCEDE",
      "text": "Conceded for startups: the evidence itself says it measures market crowding. It is adjacent, not the same."}, model=GLM)
    d1 = Claim(cid="d1", kind="differs", by="advocate", evidence=[], text="No retrieved project coaches the user toward whitespace or re-scores suggestions against evidence.")
    e(0.4, "advocate", "debate", "claim.proposed", {"claim": d1.model_dump(mode="json")}, model=GLM)
    e(0.3, "judge", "debate", "agent.started", {"purpose": "Count the votes, measure the split."})
    e(2.2, "judge", "debate", "jury.vote", {"subject": "e1 vs idea: purpose", "mean": 0.86, "std": 0.05, "votes": [
        {"model": GLMF, "score": 0.9, "why": "same goal"}, {"model": FLASH, "score": 0.85, "why": "same goal, narrower corpus"}, {"model": OSS, "score": 0.82, "why": "same goal"}]})
    e(0.3, "judge", "debate", "jury.vote", {"subject": "e1 vs idea: mechanism", "mean": 0.41, "std": 0.27, "votes": [
        {"model": GLMF, "score": 0.2, "why": "keyword search is a different mechanism"}, {"model": FLASH, "score": 0.75, "why": "both are LLM + search"},
        {"model": OSS, "score": 0.28, "why": "no verification or resolution step"}]})
    e(0.2, "conductor", "debate", "requery.issued", {"reason": "jury split (std 0.27) on mechanism", "facet": "mechanism",
      "query": "multi-agent debate verification prior art search", "to": "scout.github"}, to="scout.github")
    e(2.0, "scout.github", "debate", "tool.result", {"tool": "github.search_repositories", "summary": "no hackathon-facing project combines debate + verification", "n_hits": 0})
    e(1.5, "judge", "debate", "jury.vote", {"subject": "e1 vs idea: mechanism (re-vote)", "mean": 0.27, "std": 0.08, "votes": [
        {"model": GLMF, "score": 0.2, "why": "different mechanism"}, {"model": FLASH, "score": 0.38, "why": "shared LLM use only"}, {"model": OSS, "score": 0.24, "why": "different mechanism"}]})
    e(0.2, "judge", "debate", "claim.resolved", {"cid": "c1", "status": "challenged", "reason": "purpose overlaps (0.86); mechanism does not (0.27)"})
    e(0.1, "judge", "debate", "claim.resolved", {"cid": "c3", "status": "conceded", "reason": "advocate conceded adjacency"})
    e(0.2, "conductor", "debate", "budget.updated", {"calls": 31, "tokens": 48200, "cost_usd": 0.031, "elapsed_s": 41.0, "degraded": False})

    # ---- verify -----------------------------------------------------------------------------------------
    e(0.3, "verifier", "verify", "agent.started", {"purpose": "No receipt, no claim."})
    for cid in ("c1", "c2", "c3"):
        e(0.35, "verifier", "verify", "verify.result", {"cid": cid, "layer": "quote", "status": "match", "detail": "quote found verbatim in the fetched page"})
    fire = Claim(cid="c9", kind="exists", by="fire-drill", evidence=["ev9"], text="OriginalityOracle (2025) already does exactly this, per its TechCrunch launch.")
    fire_d = fire.model_dump(mode="json") | {"simulated": True}
    e(0.6, "verifier", "verify", "claim.proposed", {"claim": fire_d, "simulated": True})
    e(1.0, "verifier", "verify", "verify.result", {"cid": "c9", "layer": "quote", "status": "no_match", "detail": "cited page does not exist", "simulated": True})
    for cid, st in (("c1", "exist"), ("c2", "exist"), ("c3", "exist")):
        e(0.9, "verifier", "verify", "verify.result", {"cid": cid, "layer": "gptzero", "status": st, "detail": "citation exists; source stance: support"})
        e(0.05, "verifier", "verify", "claim.resolved", {"cid": cid, "status": "verified", "reason": "quote matched and citation verified"})
    e(0.6, "verifier", "verify", "verify.result", {"cid": "c9", "layer": "gptzero", "status": "fake", "detail": "GPTZero bibliography scan: citation could not be found", "simulated": True})
    e(0.05, "verifier", "verify", "claim.resolved", {"cid": "c9", "status": "rejected", "reason": "caught hallucination (fire drill)", "simulated": True})
    e(0.2, "verifier", "verify", "agent.finished", {"ok": True, "summary": "3 verified, 1 rejected (simulated)"})

    # ---- LLM-predictability -----------------------------------------------------------------------------
    priors = [
        (GLMF, "A browser extension that warns you when your hackathon idea matches a past Devpost winner.", 0.78),
        (FLASH, "A chatbot that rates your project idea from 1 to 10 for originality.", 0.74),
        (OSS, "A search engine over old hackathon projects so you can check for duplicates.", 0.81),
        (KIMI, "A plagiarism detector comparing hackathon repos with earlier code.", 0.62),
        (GLMF, "An idea generator that mixes random APIs into project prompts.", 0.41),
        (FLASH, "A leaderboard of the most overused hackathon ideas.", 0.66),
        (OSS, "A Discord bot that tells teams when two of them are building the same thing.", 0.57),
        (KIMI, "A tool that matches your idea with sponsor prizes.", 0.33),
    ]
    add_nodes, add_links = [], []
    for i, (m, text, sim) in enumerate(priors, 1):
        e(0.25, "judge", "score", "prior.sample", {"model": m, "text": text, "similarity": sim}, model=m, latency=700, tok=(180, 40), cost=0.00005)
        add_nodes.append(GraphNode(id=f"prior:{i}", kind="prior", label=text[:60], similarity=sim, val=1.2))
        add_links.append(GraphLink(source="idea", target=f"prior:{i}", kind="similar", weight=sim))
    e(0.1, "judge", "score", "graph.patch", GraphPatch(add_nodes=add_nodes, add_links=add_links))

    # ---- score ------------------------------------------------------------------------------------------
    scores = Scores(
        crowding=AxisScore(score=34, detail={"crowding_lite": 0.83, "percentile": 0.66, "top": ["IdeaRadar", "HackCheck", "NoveltyLens"]},
                           note="Crowded on purpose: two direct neighbours, both keyword-based."),
        facet_rarity=AxisScore(score=71, detail={"rarity": {"purpose": 0.22, "mechanism": 0.81, "audience": 0.35, "data": 0.4, "twist": 0.97},
                                                 "pair_purpose_mechanism": 0.93, "cliche_overlap": 0.18},
                               note="Purpose is common (143 projects); purpose + coaching appears in 0."),
        llm_predictability=AxisScore(score=58, detail={"max_similarity": 0.81, "hit_rate": 0.125, "n_samples": 8},
                                     note="Models readily propose 'search old hackathons'; none proposed debate, verification or coaching."),
        headline=49, band=11, confidence=0.72, abstain=Abstain(active=False))
    e(0.6, "synthesizer", "score", "score.updated", scores)

    # ---- synthesize + mutate ----------------------------------------------------------------------------
    e(0.2, "synthesizer", "score", "agent.started", {"purpose": "Only what survived."})
    e(2.6, "synthesizer", "score", "agent.finished", {"ok": True, "summary": "report written from 3 verified claims and 1 difference"}, model=GLM, latency=2500, tok=(5200, 640), cost=0.01)
    e(0.2, "mutator", "mutate", "agent.started", {"purpose": "Move one facet into the whitespace."})
    muts = [
        Mutation(mid="mu1", facet="audience", frm="hackathon participants", to="hackathon organisers screening 1,000 submissions for recycled projects",
                 rationale="'organiser tooling' is common globally but absent from this neighbourhood.", grounded_in=["organizer", "moderation"],
                 pitch="A triage console for organisers: every submission is resolved against prior art and flagged with verified evidence."),
        Mutation(mid="mu2", facet="mechanism", frm="one LLM opinion", to="adversarial agents whose claims are independently verified before display",
                 rationale="No neighbour verifies its own claims; 'verification' is a whitespace term here.", grounded_in=["verification", "citations"],
                 pitch="An originality checker where a critic and an advocate argue, and nothing reaches you unless a verifier finds the receipt."),
        Mutation(mid="mu3", facet="twist", frm="a score", to="coaching: facet swaps re-scored live against the corpus",
                 rationale="purpose AND coaching returns 0 projects.", grounded_in=["coaching", "iteration"],
                 pitch="Don't just grade the idea: propose concrete swaps and show the neighbourhood thinning out as you accept them."),
    ]
    for mu in muts:
        e(0.8, "mutator", "mutate", "mutation.proposed", {"mutation": mu.model_dump(mode="json")}, model=KIMI, latency=1500, tok=(2100, 220), cost=0.003)
        e(0.02, "mutator", "mutate", "graph.patch", GraphPatch(
            add_nodes=[GraphNode(id=f"mut:{mu.mid}", kind="mutation", label=mu.to[:60], similarity=0.8, val=3)],
            add_links=[GraphLink(source="idea", target=f"mut:{mu.mid}", kind="mutation_of", weight=0.8)]))
    for mu, (delta, sim) in zip(muts, ((14, 0.61), (22, 0.52), (31, 0.44))):
        mu.delta, mu.axes = delta, {"crowding": 34 + delta}
        e(1.6, "mutator", "mutate", "mutation.scored", {"mid": mu.mid, "delta": delta, "axes": mu.axes})
        e(0.02, "mutator", "mutate", "graph.patch", GraphPatch(update_nodes=[{"id": f"mut:{mu.mid}", "similarity": sim}]))
    e(0.2, "mutator", "mutate", "agent.finished", {"ok": True, "summary": "3 mutations, all re-scored against the corpus"})

    # ---- act --------------------------------------------------------------------------------------------
    e(0.3, "actuator", "act", "agent.started", {"purpose": "An answer that doesn't act is a report."})
    for action, label, click in (("arm_watch", "Watch for new look-alikes (re-checks every 30 min, pings Slack)", True),
                                 ("draft_pitch", "Draft a differentiated pitch from the chosen mutation", False),
                                 ("writeback", "Add this idea to the corpus so the next search can find it", True)):
        e(0.3, "actuator", "act", "action.proposed", {"action": action, "label": label, "requires_click": click})
    e(0.2, "conductor", "act", "budget.updated", {"calls": 52, "tokens": 91400, "cost_usd": 0.058, "elapsed_s": 74.0, "degraded": False})

    ents = [ent1, ent4] + [Entity(eid=eid_of[r.rid], canonical_name=r.title, summary=r.pitch, records=[r.rid], sources=[r.source],
                                  similarity=r.retrieval["rerank_score"], possible_same_as=["e5"] if r.rid == "devpost:hackcheck" else [])
                           for r in RECORDS if eid_of[r.rid] in {"e2", "e3", "e5", "e6", "e7"}]
    ents[0].facet_overlap = {"purpose": FacetOverlap(mean=0.86, std=0.05, votes=[JurorVote(model=GLMF, score=0.9, why="same goal")]),
                             "mechanism": FacetOverlap(mean=0.27, std=0.08, votes=[JurorVote(model=OSS, score=0.24, why="different mechanism")])}
    for ev_ in evs:
        ev_.verification = Verification(local_quote_match=True, gptzero_status="exist", stance="support")
    c1.status, c2.status, c3.status, d1.status = "verified", "verified", "verified", "unverified_lead"
    c1.thread = [ThreadEntry(frm="advocate", type="REBUTTAL", text="Purpose overlaps; mechanism differs.")]
    report = Report(
        run_id=RUN_ID, idea_text=IDEA, facets=facets, scores=scores, voice=voice, entities=sorted(ents, key=lambda x: -x.similarity),
        claims=[c1, c2, c3, d1], evidence=evs, mutations=muts,
        cliches=[TermStat(term=t, score=s) for t, s in (("devpost", 41.2), ("originality score", 33.0), ("similar projects", 27.5), ("keywords", 19.1), ("judges", 12.4))],
        whitespace=[TermStat(term=t, global_count=g, neighbourhood_count=n) for t, g, n in (("verification", 2140, 0), ("coaching", 890, 0), ("organizer", 1320, 1), ("knowledge graph", 760, 0))],
        by_year=[YearCount(year=y, count=c, winners=w) for y, c, w in ((2019, 3, 0), (2020, 5, 1), (2021, 8, 1), (2022, 14, 2), (2023, 31, 4), (2024, 47, 5), (2025, 35, 3))],
        sources=[SourceStatus(source="devpost", status="ok", n_records=5), SourceStatus(source="yc", status="ok", n_records=1),
                 SourceStatus(source="github", status="ok", n_records=2), SourceStatus(source="hn", status="degraded", n_records=1, error="first attempt timed out"),
                 SourceStatus(source="arxiv", status="skipped")],
        citations=[x.citation for x in evs],
        summary_md="**The purpose is crowded; the way you do it is not.** Two earlier hackathon projects score idea originality against Devpost [1][2], "
                   "both with keyword search and a single LLM opinion. None verifies its claims, resolves the same project across sources, or coaches the user. "
                   "A startup validates ideas against competitors but measures market crowding rather than novelty [3].")
    e(0.4, "conductor", "done", "run.finished", {"report": report.model_dump(mode="json")})
    return R.events


if __name__ == "__main__":
    events = build()
    OUT.write_text("\n".join(json.dumps(ev.model_dump(mode="json", exclude_none=True)) for ev in events) + "\n")
    kinds = sorted({ev.type for ev in events})
    print(f"wrote {len(events)} events, {len(kinds)} distinct types, {events[-1].ts - events[0].ts:.0f}s simulated -> {OUT}")
