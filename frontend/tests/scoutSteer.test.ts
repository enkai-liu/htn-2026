// The scout boats are decoration, but they promise one thing: they stay in the water.
import { describe, expect, it } from "vitest";
import { keepOffShores, stepScout, type Scout, type Shore } from "../lib/scoutSteer";

const SPD = 0.00005; // radians per ms, like the scene's
const R = 8;
const mark = (a: number) => ({ x: Math.cos(a) * R, z: Math.sin(a) * R });

/** Sail one full orbit at 60fps. Returns the closest the boat came to each shore's rim (negative = inside it). */
function sail(shores: Shore[], each?: (ms: number, s: Scout) => void): { s: Scout; clearance: number; lag: number; maxStep: number } {
  const s: Scout = { ...mark(0), heading: 0, side: 0 };
  keepOffShores(s, shores);
  let clearance = Infinity, maxStep = 0, a = 0;
  const dt = 16;
  for (let ms = 0; a < Math.PI * 2; ms += dt) {
    a += SPD * dt;
    const m = mark(a), n = mark(a + SPD * 240);
    const dir = { x: n.x - m.x, z: n.z - m.z };
    const before = { x: s.x, z: s.z };
    each?.(ms, s);
    stepScout(s, m, Math.hypot(dir.x, dir.z) / 240, dir, shores, dt);
    maxStep = Math.max(maxStep, Math.hypot(s.x - before.x, s.z - before.z));
    for (const o of shores) clearance = Math.min(clearance, Math.hypot(s.x - o.x, s.z - o.z) - o.r);
  }
  const end = mark(a);
  return { s, clearance, lag: Math.hypot(s.x - end.x, s.z - end.z), maxStep };
}

describe("scoutSteer", () => {
  it("follows its mark in open water", () => {
    const { lag } = sail([]);
    expect(lag).toBeLessThan(2);
  });

  it("goes round islands that sit right on its orbit, without ever touching one, and catches up after", () => {
    // dead on the orbit, just off it, and two close together that have to be passed as one coast
    const shores: Shore[] = [
      { ...mark(1), r: 2.2 },
      { x: Math.cos(2.5) * (R + 0.6), z: Math.sin(2.5) * (R + 0.6), r: 1.6 },
      { ...mark(4), r: 1.8 },
      { ...mark(4.35), r: 1.8 },
    ];
    const { clearance, lag, maxStep } = sail(shores);
    expect(clearance).toBeGreaterThanOrEqual(-1e-9);
    expect(lag).toBeLessThan(3);
    // a detour is sailed, not jumped: never more than the catch-up speed allows in one frame
    expect(maxStep).toBeLessThan(SPD * R * 16 * 5);
  });

  it("is shouldered aside by an island that surfaces under it", () => {
    const shores: Shore[] = [];
    let rock: Shore | null = null;
    const { clearance } = sail(shores, (ms, s) => {
      if (ms === 16 * 2000) { rock = { x: s.x + 0.05, z: s.z, r: 0 }; shores.push(rock); }
      if (rock && rock.r < 2) rock.r += 0.03; // growing, like an island popping in
    });
    expect(clearance).toBeGreaterThanOrEqual(-1e-9);
  });
});
