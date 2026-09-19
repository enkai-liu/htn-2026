"""Every fixture/golden event must validate as AgentEvent, and key payloads must parse into their schemas."""
import json
from pathlib import Path

import pytest

from app.schemas import EVENT_TYPES, AgentEvent, Claim, CoachMessage, CoachPitch, Entity, Facets, GraphPatch, Mutation, Report, Scores, SourceRecord, Voice

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FILES = [FIXTURES / "mock_run.jsonl", *sorted((FIXTURES / "golden").glob("*.jsonl"))]

PAYLOADS = {
    "facets.extracted": lambda d: Facets(**d["facets"]),
    "evidence.found": lambda d: SourceRecord(**d["record"]),
    "entity.merged": lambda d: Entity(**d["entity"]),
    "claim.proposed": lambda d: Claim(**{k: v for k, v in d["claim"].items() if k != "simulated"}),
    "voice.result": lambda d: Voice(**d),
    "score.updated": lambda d: Scores(**d),
    "graph.patch": lambda d: GraphPatch(**d),
    "mutation.proposed": lambda d: Mutation(**d["mutation"]),
    "coach.message": lambda d: CoachMessage(**d["message"]),
    "coach.pitch": lambda d: CoachPitch(**d["pitch"]),
    "run.finished": lambda d: Report(**d["report"]),
}


def load(path: Path) -> list[AgentEvent]:
    return [AgentEvent(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_events_validate(path: Path):
    events = load(path)
    assert events, f"{path} is empty"
    assert [e.seq for e in events] == list(range(1, len(events) + 1)), "seq must be 1..n without gaps"
    assert all(a.ts <= b.ts for a, b in zip(events, events[1:])), "ts must be non-decreasing"
    assert events[0].type == "run.started" and events[-1].type == "run.finished"
    for ev in events:
        assert ev.type in EVENT_TYPES
        if ev.type in PAYLOADS:
            PAYLOADS[ev.type](ev.data)


def test_graph_patches_are_consistent():
    """Links may only reference nodes that exist at that point in the stream (the UI reducer relies on it)."""
    nodes: set[str] = set()
    for ev in load(FIXTURES / "mock_run.jsonl"):
        if ev.type != "graph.patch":
            continue
        patch = GraphPatch(**ev.data)
        nodes |= {n.id for n in patch.add_nodes}
        nodes -= set(patch.remove_nodes)
        for link in patch.add_links:
            assert link.source in nodes and link.target in nodes, f"seq {ev.seq}: dangling link {link}"
        for upd in patch.update_nodes:
            assert upd["id"] in nodes, f"seq {ev.seq}: update of unknown node {upd['id']}"
