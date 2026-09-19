// Folds the whole recorded mock run through the reducers and checks the end state the UI depends on.
// Run with `pnpm test`.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { EVENT_TYPES } from "../lib/eventTypes";
import { applyGraphPatch, danglingLinks, emptyGraph } from "../lib/graphReducer";
import { gapMs, parseJsonl, parseSpeed, safeReplayName } from "../lib/replay";
import { foldEvents, initialRunState, runReducer } from "../lib/runReducer";
import { selectEvidenceCards, selectLedger, selectSourceStatus, selectSpend } from "../lib/selectors";
import type { AgentEvent } from "../lib/types";

const path = fileURLToPath(new URL("../public/replay/mock.jsonl", import.meta.url));
const events = parseJsonl(readFileSync(path, "utf8"));
const final = foldEvents(events);

describe("mock run fixture", () => {
  it("parses every line and only uses known event types", () => {
    expect(events.length).toBeGreaterThanOrEqual(125);
    const known = new Set<string>(EVENT_TYPES);
    expect(events.filter((e) => !known.has(e.type))).toEqual([]);
    expect(events.map((e) => e.seq)).toEqual(events.map((_, i) => i + 1));
  });
});

describe("runReducer on the mock run", () => {
  it("applies every event without recording reducer errors", () => {
    expect(final.eventCount).toBe(events.length);
    expect(final.lastSeq).toBe(events[events.length - 1].seq);
    expect(final.errors).toEqual([]);
  });

  it("flags the run as a fictional mock", () => {
    expect(final.mock).toBe(true);
    expect(final.recorded).toBe(true);
    expect(final.ideaText.length).toBeGreaterThan(250);
  });

  it("keeps the graph consistent: no link points at a missing node", () => {
    expect(danglingLinks(final.graph)).toEqual([]);
    expect(final.graph.pending).toEqual([]);
    for (const l of final.graph.links) {
      expect(final.graph.nodes[l.source]).toBeDefined();
      expect(final.graph.nodes[l.target]).toBeDefined();
    }
  });

  it("absorbs merged entity nodes", () => {
    expect(final.graph.nodes["ent:e1b"]).toBeUndefined();
    expect(final.graph.nodes["ent:e4b"]).toBeUndefined();
    expect(final.graph.nodes["ent:e1"].badges).toEqual(expect.arrayContaining(["winner", "merged", "conflict"]));
    expect(final.graph.links.some((l) => l.kind === "possible_same_as" && l.source === "ent:e2" && l.target === "ent:e5")).toBe(true);
    expect(final.recordEntity["github:acme/idearadar"]).toBe("e1");
    expect(final.recordEntity["hn:40000001"]).toBe("e4");
  });

  it("scores three mutations, each with a delta, and moves their nodes outward", () => {
    expect(final.mutationOrder).toEqual(["mu1", "mu2", "mu3"]);
    for (const mid of final.mutationOrder) {
      expect(typeof final.mutations[mid].delta).toBe("number");
      expect(final.mutations[mid].scoredSeq).toBeGreaterThan(final.mutations[mid].proposedSeq);
      expect(final.graph.nodes[`mut:${mid}`].similarity).toBeLessThan(0.8);
    }
    expect(final.mutations.mu3.delta).toBe(31);
  });

  it("rejects the simulated fire-drill claim and keeps it labelled", () => {
    const c9 = final.claims.c9;
    expect(c9.status).toBe("rejected");
    expect(c9.simulated).toBe(true);
    expect(c9.verification.quote?.ok).toBe(false);
    expect(c9.verification.gptzero?.status).toBe("fake");
  });

  it("tracks the debate: threads, verification layers, jury split and re-queries", () => {
    expect(final.claims.c1.status).toBe("verified");
    expect(final.claims.c1.thread.length).toBe(1);
    expect(final.claims.c1.verification.quote?.ok).toBe(true);
    expect(final.claims.c1.verification.gptzero?.ok).toBe(true);
    expect(final.claims.d1.status).toBe("unverified_lead"); // only the final report says so
    expect(final.juryVotes.map((v) => v.split)).toEqual([false, true, false]);
    expect(final.juryVotes[2].revote).toBe(true);
    expect(final.requeries.length).toBe(2);
    expect(final.requeries[1].fromJurySplit).toBe(true);
    expect(final.roster.agents["scout.devpost"].requeried).toBe(1);
  });

  it("builds the roster with skipped and recovered agents", () => {
    expect(final.roster.order[0]).toBe("conductor");
    expect(final.roster.agents["scout.arxiv"].status).toBe("skipped");
    expect(final.roster.agents["scout.arxiv"].why).toMatch(/product/);
    expect(final.roster.agents["scout.hn"].status).toBe("recovered");
    expect(final.failedSources.hn.recovered).toBe(true);
    expect(Object.values(final.roster.agents).filter((a) => a.status === "active")).toEqual([]);
  });

  it("ends with scores, voice, budget, actions and the report", () => {
    expect(final.scores?.headline).toBe(49);
    expect(final.scores?.band).toBe(11);
    expect(final.voice?.sentences.length).toBe(2);
    expect(final.priorSamples.length).toBe(8);
    expect(final.budget?.calls).toBe(52);
    expect(final.actions.map((a) => a.action)).toEqual(["arm_watch", "draft_pitch", "writeback"]);
    expect(final.report).not.toBeNull();
    expect(final.finished).toBe(true);
    // ev1-3 stream in with their claims (quotes are visible during the debate); ev9 is the fire drill's simulated receipt
    expect(Object.keys(final.evidence).sort()).toEqual(["ev1", "ev2", "ev3", "ev9"]);
    expect((final.evidence.ev9 as { simulated?: boolean }).simulated).toBe(true);
    expect(final.evidence.ev1.verification?.local_quote_match).toBe(true);
    expect(final.entityOrder.length).toBe(7);
  });

  it("is idempotent for duplicate and replayed events", () => {
    const twice = foldEvents(events, final);
    expect(twice).toBe(final);
    let s = initialRunState;
    for (const ev of events.slice(0, 40)) { s = runReducer(s, ev); s = runReducer(s, ev); }
    expect(s).toEqual(foldEvents(events.slice(0, 40)));
  });

  it("survives malformed events", () => {
    const bad = { seq: 1, run_id: "x", ts: 1, agent: "conductor", phase: "plan", type: "team.formed", data: { team: "nope" } } as unknown as AgentEvent;
    const s = runReducer(initialRunState, bad);
    expect(s.lastSeq).toBe(1);
    expect(runReducer(s, { nonsense: true } as unknown as AgentEvent)).toBe(s);
  });

  it("shows recoverable errors as amber degradations and keeps red for fatal ones", () => {
    const err = (seq: number, recoverable: boolean) =>
      ({ seq, run_id: "x", ts: seq, agent: "verifier", phase: "verify", type: "error", data: { message: `e${seq}`, recoverable } }) as AgentEvent;
    const s = foldEvents([err(1, true), err(2, false)]);
    const [soft, fatal] = s.timeline.filter((r) => r.type === "error");
    expect([soft.tone, soft.tag, soft.emphasis]).toEqual(["warn", "degraded", undefined]);
    expect([fatal.tone, fatal.tag, fatal.emphasis]).toEqual(["danger", "error", "failure"]);
    expect(s.errors.map((e) => e.recoverable)).toEqual([true, false]);
  });
});

describe("selectors", () => {
  it("collapses records into entity cards with the right badges", () => {
    const cards = selectEvidenceCards(final);
    expect(cards.length).toBe(7);
    expect(cards[0].title).toBe("IdeaRadar");
    expect(cards[0].records.length).toBe(2);
    expect(cards[0].badges).toEqual(expect.arrayContaining(["winner", "merged", "conflict"]));
    const pitchProbe = cards.find((c) => c.eid === "e4");
    expect(pitchProbe?.badges).toEqual(expect.arrayContaining(["merged", "imputed", "source_failed"]));
    expect(cards.find((c) => c.eid === "e2")?.possibleSameAs).toEqual(["CopyCatch"]);
    expect(cards.every((c) => c.nodeId && final.graph.nodes[c.nodeId])).toBe(true);
  });

  it("shows cards before the resolver has run", () => {
    const mid = foldEvents(events.filter((e) => e.seq <= 46));
    const cards = selectEvidenceCards(mid);
    expect(cards.length).toBe(9);
    expect(cards.every((c) => c.nodeId)).toBe(true);
  });

  it("builds the ledger: merges, conflict, imputed field, failed source", () => {
    const ledger = selectLedger(final);
    expect(ledger.filter((r) => r.kind === "merge").length).toBe(3);
    expect(ledger.filter((r) => r.kind === "conflict").length).toBe(1);
    // one fused entity field (PitchProbe.tech) and one record-level field (acme/idearadar tech)
    expect(ledger.filter((r) => r.kind === "imputed").map((r) => r.kind === "imputed" && `${r.entity}.${r.field}`)).toEqual(["PitchProbe.tech", "acme/idearadar.tech"]);
    expect(ledger.filter((r) => r.kind === "source_failed").length).toBe(1);
  });

  it("describes one imputed field once, however many ways the record says it is imputed", () => {
    // A Devpost record whose year came from the hackathon name carries field_provenance.date = "imputed" AND
    // date_precision = "inferred". Emitting a row for each gives two rows under one React key.
    const state = foldEvents([{
      seq: 1, run_id: "t", ts: 0, agent: "scout.devpost", phase: "scout", type: "evidence.found",
      data: {
        eid: "e1",
        record: {
          rid: "devpost:omnis-gb4zfj", source: "devpost", url: "https://devpost.com/software/omnis-gb4zfj",
          title: "Omnis", year: 2024, date_precision: "inferred", field_provenance: { date: "imputed" },
        },
      },
    } as unknown as AgentEvent]);
    const keys = selectLedger(state).filter((r) => r.kind === "imputed").map((r) => r.key);
    expect(keys).toEqual(["i:devpost:omnis-gb4zfj:date"]);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("reports source status and spend", () => {
    expect(selectSourceStatus(final).find((s) => s.source === "hn")?.status).toBe("degraded");
    const mid = foldEvents(events.filter((e) => e.seq <= 39));
    expect(selectSourceStatus(mid).find((s) => s.source === "hn")?.status).toBe("failed");
    expect(selectSourceStatus(mid).find((s) => s.source === "arxiv")?.status).toBe("skipped");
    expect(selectSpend(final).usd).toBeGreaterThanOrEqual(0.058);
  });
});

describe("graphReducer", () => {
  it("drops links with a removed node and parks links whose endpoint has not arrived", () => {
    let g = applyGraphPatch(emptyGraph, { add_nodes: [{ id: "idea", kind: "idea", label: "x", badges: [], val: 8 }], add_links: [{ source: "idea", target: "ent:a", kind: "similar", weight: 0.5 }], update_nodes: [], remove_nodes: [] });
    expect(g.links).toEqual([]);
    expect(g.pending.length).toBe(1);
    g = applyGraphPatch(g, { add_nodes: [{ id: "ent:a", kind: "entity", label: "a", badges: [], val: 2 }], add_links: [], update_nodes: [], remove_nodes: [] });
    expect(g.links.length).toBe(1);
    expect(g.pending).toEqual([]);
    const again = applyGraphPatch(g, { add_nodes: [], add_links: [{ source: "idea", target: "ent:a", kind: "similar", weight: 0.5 }], update_nodes: [], remove_nodes: [] });
    expect(again.links.length).toBe(1);
    g = applyGraphPatch(g, { add_nodes: [], add_links: [], update_nodes: [], remove_nodes: ["ent:a"] });
    expect(g.links).toEqual([]);
    expect(Object.keys(g.nodes)).toEqual(["idea"]);
  });
});

describe("replay helpers", () => {
  it("honours original timing divided by speed, with a capped gap", () => {
    const a = { ts: 10 } as AgentEvent;
    expect(gapMs(undefined, a, 1.5)).toBe(0);
    expect(gapMs(a, { ts: 11.5 } as AgentEvent, 1.5)).toBeCloseTo(1000);
    expect(gapMs(a, { ts: 60 } as AgentEvent, 1)).toBe(2500);
    expect(gapMs(a, { ts: 60 } as AgentEvent, 0)).toBe(0);
  });
  it("sanitises query params", () => {
    expect(parseSpeed("2")).toBe(2);
    expect(parseSpeed("fast")).toBe(1.5);
    expect(parseSpeed(null)).toBe(1.5);
    expect(safeReplayName("golden-1")).toBe("golden-1");
    expect(safeReplayName("../etc/passwd")).toBeNull();
  });
});
