// Pure steering for the scout boats on the islands map. No three.js in here, so it runs under Vitest's node environment.
//
// A scout does not ride its orbit any more: it chases a point that does. The orbit knows nothing about the islands
// and goes straight through them; the boat is what has to stay in the water. Chasing gives it a position of its own,
// so going round a shore is a detour at its own pace rather than a jump, and an island that surfaces under it shoulders
// it aside instead of swallowing it.

export interface Shore { x: number; z: number; /** the hull may not come closer to the centre than this */ r: number }

export interface Scout {
  x: number;
  z: number;
  /** rotation about y, bow along +z */
  heading: number;
  /** which way round it is passing the shore it is up against; 0 in open water. Kept until it is clear, so a
   *  cluster of islands is followed like one coast instead of being dithered at. */
  side: -1 | 0 | 1;
}

/** how far off a shore a boat starts to turn away from it */
export const SHORE_BAND = 1.4;
/** the boat trails its mark by this much time, so it eases off as it closes and never snaps onto it */
const LEAD_MS = 2500;
/** how hard it may press to catch up after a detour, in orbit speeds */
const CATCH_UP = 3;
const TURN_MS = 450;

/** Push a point out of every shore it is inside. Twice, because leaving one can mean entering its neighbour. */
export function keepOffShores(p: { x: number; z: number }, shores: readonly Shore[]): void {
  for (let pass = 0; pass < 2; pass++) {
    for (const o of shores) {
      const dx = p.x - o.x, dz = p.z - o.z;
      const d = Math.hypot(dx, dz);
      if (d >= o.r) continue;
      if (d < 1e-6) { p.x = o.x + o.r; continue; }
      p.x = o.x + (dx / d) * o.r;
      p.z = o.z + (dz / d) * o.r;
    }
  }
}

/**
 * One step of a scout toward its mark. `markSpeed` is how fast the mark is moving (map units per ms) and
 * `markDir` the way it is going, which breaks the tie when a boat meets a shore head on.
 */
export function stepScout(s: Scout, mark: { x: number; z: number }, markSpeed: number, markDir: { x: number; z: number }, shores: readonly Shore[], dt: number): void {
  let vx = (mark.x - s.x) / LEAD_MS;
  let vz = (mark.z - s.z) / LEAD_MS;
  const cap = markSpeed * CATCH_UP;
  const sp = Math.hypot(vx, vz);
  if (sp > cap && sp > 0) { vx *= cap / sp; vz *= cap / sp; }

  let near = false;
  for (const o of shores) {
    const dx = s.x - o.x, dz = s.z - o.z;
    const d = Math.hypot(dx, dz) || 1e-6;
    const k = Math.min(1, 1 - (d - o.r) / SHORE_BAND);
    if (k <= 0) continue;
    near = true;
    const nx = dx / d, nz = dz / d;
    const vn = vx * nx + vz * nz;
    if (vn >= 0) continue; // already heading away from it
    const tx = -nz, tz = nx;
    if (!s.side) {
      const vt = vx * tx + vz * tz;
      const along = Math.abs(vt) > 0.2 * -vn ? vt : tx * markDir.x + tz * markDir.z;
      s.side = along < 0 ? -1 : 1;
    }
    // what was carrying it ashore carries it along the shore instead: all of it by the time it is at the rim
    vx += (-nx * vn + tx * s.side * -vn) * k;
    vz += (-nz * vn + tz * s.side * -vn) * k;
  }
  if (!near) s.side = 0;

  s.x += vx * dt;
  s.z += vz * dt;
  keepOffShores(s, shores);

  if (Math.hypot(vx, vz) > markSpeed * 0.05) {
    let turn = Math.atan2(vx, vz) - s.heading;
    turn = Math.atan2(Math.sin(turn), Math.cos(turn));
    s.heading += turn * (1 - Math.exp(-dt / TURN_MS));
  }
}
