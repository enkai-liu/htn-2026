// The Debate page's regrouping of the mock run: cases per project, the jury bench per facet, the hand-off stages.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { juryTarget, selectDebateBoard } from "../lib/debate";
import { parseJsonl } from "../lib/replay";
import { foldEvents } from "../lib/runReducer";

const path = fileURLToPath(new URL("../public/replay/mock.jsonl", import.meta.url));
const events = parseJsonl(readFileSync(path, "utf8"));
const final = foldEvents(events);
const board = selectDebateBoard(final);

describe("selectDebateBoard on the mock run", () => {
  it("opens one case per project, in the order the critic raised them, plus the fire drill", () => {
    expect(board.cases.map((c) => c.eid)).toEqual(["e1", "e2", "e4", "sim"]);
    expect(board.cases.map((c) => c.claims.map((k) => k.cid))).toEqual([["c1"], ["c2"], ["c3"], ["c9"]]);
    expect(board.cases[0].name).toBe(final.entities.e1.canonical_name);
    expect(board.cases[3].simulated).toBe(true);
  });

  it("keeps what the advocate did apart from what the verifier ruled", () => {
    expect(board.cases.map((c) => c.stance)).toEqual(["contested", "contested", "conceded", "open"]);
    expect(board.cases.map((c) => c.outcome)).toEqual(["verified", "verified", "verified", "rejected"]);
  });

  it("puts the split, its tie-break and the re-vote on the facet they belong to", () => {
    const bench = board.cases[0].bench;
    expect(bench.map((b) => b.facet)).toEqual(["purpose", "mechanism"]);
    expect(bench[0].votes.length).toBe(1);
    expect(bench[0].tieBreak).toBeUndefined();
    expect(bench[1].votes.map((v) => [v.split, v.revote])).toEqual([[true, false], [false, true]]);
    expect(bench[1].tieBreak).toMatchObject({ from: "conductor", to: "scout.github", facet: "mechanism" });
    expect(bench[1].tieBreak?.result).toMatch(/debate \+ verification/);
  });

  it("lists the critic's own re-query as a back-edge and the advocate's difference apart from any case", () => {
    expect(board.backEdges.map((r) => [r.from, r.to])).toEqual([["critic", "scout.devpost"]]);
    expect(board.distinctions.map((c) => c.cid)).toEqual(["d1"]);
    expect(board.loose).toEqual([]);
    expect(board.scouts.fromCritic.count).toBe(1);
    expect(board.scouts.fromJury.count).toBe(1);
  });

  it("counts the funnel and finishes every stage", () => {
    expect(board.funnel).toEqual({ proposed: 4, struck: 1, leads: 0, reachReport: 3, pending: 0 });
    expect(board.stages.map((s) => s.status)).toEqual(["done", "done", "done", "done", "done"]);
    expect(board.jurors.length).toBe(3);
  });

  it("does not light the verifier or the report before the debate reaches them", () => {
    const upToAdvocate = foldEvents(events.filter((e) => e.seq <= 66));
    const early = selectDebateBoard(upToAdvocate);
    expect(early.stages.map((s) => s.status)).toEqual(["done", "active", "idle", "idle", "idle"]);
    expect(early.funnel.pending).toBe(3);
  });
});

describe("juryTarget", () => {
  const s = { entities: final.entities, entityOrder: final.entityOrder };
  it("prefers the judge's own eid and facet", () => {
    expect(juryTarget({ subject: "anything", eid: "e9", facet: "twist" }, s)).toEqual({ eid: "e9", facet: "twist" });
  });
  it("falls back to the subject line of older recordings", () => {
    expect(juryTarget({ subject: "e1 vs idea: mechanism (re-vote)" }, s)).toEqual({ eid: "e1", facet: "mechanism" });
    expect(juryTarget({ subject: `${final.entities.e2.canonical_name}: purpose` }, s)).toEqual({ eid: "e2", facet: "purpose" });
    expect(juryTarget({ subject: "nobody we know: purpose" }, s)).toEqual({ eid: null, facet: "purpose" });
  });
});
