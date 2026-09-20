// Procedural low-poly islands. Everything is seeded by the node id, so an island has the same coastline and the same
// trees on every render. One merged, vertex-coloured geometry per island: one draw call each.
//
// The map is a chart of claimed territory, and every object on it means one thing:
//   your idea    a lighthouse          prior art    a hill with a flag in the colour of its source (gold: a winner)
//   LLM prior    bare rock, unclaimed  mutation     a boat leaving your island, bow pointing away from it
// How much there is of a project is the size of its island, and nothing else.
//
// Land stands in the sea: turf on top, a lip of beach at the waterline, and a shoal spreading out underneath that
// shows through the water as the pale shallows around the coast.
import { BufferAttribute, BufferGeometry, Color, ConeGeometry, CylinderGeometry } from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { mulberry32 } from "@/lib/seeded";
import type { IslandKind } from "@/lib/islandLayout";

const PAPER = new Color("#ece9e2");
const ROCK_TOP = new Color("#c4bdb0");
const ROCK_TIP = new Color("#8f887c");
const SAND = new Color("#efe3c6");
const SEABED = new Color("#b6e7f5");
/** how far down the shoal goes: shallow and wide, so it reads as pale water round the coast and not as a plinth,
 *  but deeper than a selected island is ever lifted, so its foot never leaves the water */
const SHOAL_DEPTH = 0.42;
const TREE = new Color("#6f9b6c");
const TREE_DARK = new Color("#557f58");
const GOLD = new Color("#e0a422");
const POLE = new Color("#5d564b");
const LIME = new Color("#faf6ec");
const BAND = new Color("#2a5fd0");
const BAND_DARK = new Color("#173f96");
const LANTERN = new Color("#ffd76a");
const HULL = new Color("#b98f63");
const DECK = new Color("#e6d2b0");
const LANTERN_H = 0.13;

/** Height of the lighthouse lantern above an idea island's turf, in island sizes: where the scene hangs the glow. */
export const LANTERN_AT = 0.1 + 0.3 + 0.18 + 0.32 + 0.035 + LANTERN_H / 2;

const slabHeight = (size: number) => 0.16 * size + 0.06;
const beachHeight = (size: number) => 0.08 * size + 0.05;

/** Where the sea meets an island, measured down from its turf: halfway up the beach. A boat draws a little water. */
export const waterline = (kind: IslandKind, size: number) => (kind === "mutation" ? 0.05 * size : slabHeight(size) + beachHeight(size) / 2);

export interface IslandLook {
  seed: number;
  size: number;
  kind: IslandKind;
  tint: string;
  winner: boolean;
  /** which way a boat points, as a rotation about y; ignored by everything that is not a boat */
  heading: number;
}

export const lookKey = (l: IslandLook) => `${l.seed}:${l.size.toFixed(3)}:${l.kind}:${l.tint}:${l.winner ? 1 : 0}:${l.heading.toFixed(2)}`;

function paint(g: BufferGeometry, colour: (x: number, y: number, z: number) => Color): BufferGeometry {
  const pos = g.getAttribute("position");
  const arr = new Float32Array(pos.count * 3);
  for (let i = 0; i < pos.count; i++) {
    const c = colour(pos.getX(i), pos.getY(i), pos.getZ(i));
    arr[i * 3] = c.r; arr[i * 3 + 1] = c.g; arr[i * 3 + 2] = c.b;
  }
  g.setAttribute("color", new BufferAttribute(arr, 3));
  return g;
}

const flat = (c: Color) => () => c;

/** A thin triangular plate standing in the xy plane: hoist edge at x = -0.5 (1.732 tall), tip at x = 1. A plate rather
 *  than a single triangle because the island material is single-sided. */
function pennant(thickness: number, sail = false): BufferGeometry {
  const g = new CylinderGeometry(1, 1, thickness, 3, 1); // tip at +z, lying flat
  g.rotateX(Math.PI / 2); // stand it up: tip at -y
  g.rotateZ(Math.PI / 2); // tip at +x
  if (sail) {
    // a sail is a right triangle: drop the tip to the foot
    const pos = g.getAttribute("position");
    for (let i = 0; i < pos.count; i++) if (pos.getX(i) > 0.9) pos.setY(i, -0.866);
  }
  return g;
}

/** Push vertices in or out by an amount that depends only on their bearing, so duplicated seam vertices stay welded. */
function roughen(g: BufferGeometry, coast: number[], amount: number) {
  const pos = g.getAttribute("position");
  const n = coast.length;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i);
    const z = pos.getZ(i);
    if (Math.abs(x) < 1e-6 && Math.abs(z) < 1e-6) continue;
    const a = (Math.atan2(z, x) + Math.PI * 2) % (Math.PI * 2);
    const k = 1 + coast[Math.round((a / (Math.PI * 2)) * n) % n] * amount;
    pos.setX(i, x * k);
    pos.setZ(i, z * k);
  }
}

export function buildIslandGeometry(look: IslandLook): BufferGeometry {
  const rnd = mulberry32(look.seed ^ 0x9e3779b9);
  const { size, kind } = look;
  const tint = new Color(look.tint);
  const sides = kind === "prior" ? 6 : 7 + Math.floor(rnd() * 2);
  const coast = Array.from({ length: sides }, () => rnd() * 2 - 1);
  const parts: BufferGeometry[] = [];

  // the turf
  const slabH = slabHeight(size);
  const ground = kind === "prior" ? new Color("#d5d2ca") : tint.clone().lerp(PAPER, kind === "idea" ? 0.45 : 0.68);
  const land = kind !== "mutation"; // a boat has no land under it
  if (land) {
    const slab = new CylinderGeometry(size, size * 0.96, slabH, sides, 1);
    roughen(slab, coast, 0.16);
    slab.translate(0, -slabH / 2, 0);
    parts.push(paint(slab, flat(ground)));

    // the beach the sea laps at, then the shoal running out under the water. Bare rock has no sand on it.
    const shore = kind === "prior" ? ROCK_TOP : SAND;
    const beachH = beachHeight(size);
    const beach = new CylinderGeometry(size * 1.03, size * 1.2, beachH, sides, 1);
    roughen(beach, coast, 0.16);
    beach.translate(0, -slabH - beachH / 2, 0);
    parts.push(paint(beach, flat(shore)));

    const shoal = new CylinderGeometry(size * 1.2, size * 1.62 + 0.25, SHOAL_DEPTH, sides, 3, true);
    roughen(shoal, coast, 0.16);
    shoal.translate(0, -slabH - beachH - SHOAL_DEPTH / 2, 0);
    const deep = new Color();
    const from = kind === "prior" ? ROCK_TIP : shore;
    // the sand gives way to the colour of the water well before the foot, so the shoal has no outline
    parts.push(paint(shoal, (_x, y) => deep.copy(from).lerp(SEABED, Math.min(1, ((-y - slabH - beachH) / SHOAL_DEPTH) * 2.2))));
  }

  // Nothing below is decoration: each kind carries exactly one object, and it says what the island is.
  const taken: { x: number; z: number; r: number }[] = [];
  const spot = (r: number): { x: number; z: number } | null => {
    for (let tries = 0; tries < 24; tries++) {
      const a = rnd() * Math.PI * 2;
      const d = Math.sqrt(rnd()) * Math.max(0, size * 0.66 - r);
      const x = Math.cos(a) * d;
      const z = Math.sin(a) * d;
      if (taken.every((t) => Math.hypot(t.x - x, t.z - z) > t.r + r + 0.03)) { taken.push({ x, z, r }); return { x, z }; }
    }
    return null;
  };

  if (kind === "idea") {
    // your idea: a lighthouse. The scene hangs its glow on the lantern.
    taken.push({ x: 0, z: 0, r: size * 0.38 });
    let y = 0;
    const stack = (rBottom: number, rTop: number, h: number, colour: Color) => {
      const g = new CylinderGeometry(size * rTop, size * rBottom, size * h, 8, 1);
      g.translate(0, y + (size * h) / 2, 0);
      parts.push(paint(g, flat(colour)));
      y += size * h;
    };
    stack(0.36, 0.3, 0.1, ROCK_TOP);
    stack(0.21, 0.18, 0.3, LIME);
    stack(0.18, 0.16, 0.18, BAND);
    stack(0.16, 0.13, 0.32, LIME);
    stack(0.19, 0.19, 0.035, POLE);
    stack(0.1, 0.1, LANTERN_H, LANTERN);
    const cap = new ConeGeometry(size * 0.15, size * 0.13, 8, 1);
    cap.translate(0, y + size * 0.065, 0);
    parts.push(paint(cap, flat(BAND_DARK)));
  } else if (kind === "entity") {
    // prior art is claimed land: a low hill with one flag on it, flying the colour of where the project was found
    const hx = (rnd() - 0.5) * 0.3 * size;
    const hz = (rnd() - 0.5) * 0.3 * size;
    const hillH = size * 0.14;
    taken.push({ x: hx, z: hz, r: size * 0.36 });
    const hill = new CylinderGeometry(size * 0.15, size * 0.34, hillH, sides, 1);
    roughen(hill, coast, 0.12);
    hill.translate(hx, hillH / 2, hz);
    parts.push(paint(hill, flat(ground.clone().multiplyScalar(0.95))));

    const poleH = size * 0.62;
    const pole = new CylinderGeometry(Math.max(0.018, size * 0.02), Math.max(0.018, size * 0.02), poleH, 5, 1);
    pole.translate(hx, hillH + poleH / 2, hz);
    parts.push(paint(pole, flat(POLE)));

    const flagL = size * 0.44;
    const flagH = size * 0.27;
    const flag = pennant(Math.max(0.016, size * 0.022));
    flag.scale(flagL / 1.5, flagH / 1.732, 1);
    flag.translate(flagL / 3, 0, 0); // the hoist edge onto the pole
    flag.rotateY(rnd() * Math.PI * 2);
    flag.translate(hx, hillH + poleH - flagH / 2 - size * 0.02, hz);
    parts.push(paint(flag, flat(look.winner ? GOLD : tint)));
  } else if (kind === "mutation") {
    // a mutation is your idea setting out for open water: a boat, bow pointing away from home
    const boat: BufferGeometry[] = [];
    const hull = new CylinderGeometry(1, 0.55, 1, 6, 1);
    hull.scale(size * 0.36, size * 0.24, size * 0.82);
    hull.translate(0, -size * 0.02, 0);
    boat.push(paint(hull, flat(HULL)));
    const deck = new CylinderGeometry(1, 1, 1, 6, 1);
    deck.scale(size * 0.3, size * 0.03, size * 0.72);
    deck.translate(0, size * 0.115, 0);
    boat.push(paint(deck, flat(DECK)));
    const mastH = size * 0.95;
    const mast = new CylinderGeometry(Math.max(0.018, size * 0.022), Math.max(0.018, size * 0.022), mastH, 5, 1);
    mast.translate(0, size * 0.1 + mastH / 2, size * 0.2);
    boat.push(paint(mast, flat(POLE)));
    const sail = pennant(Math.max(0.016, size * 0.024), true);
    sail.rotateY(Math.PI / 2); // tip astern, hoist edge on the mast
    sail.scale(1, (size * 0.72) / 1.732, (size * 0.62) / 1.5);
    sail.translate(0, size * 0.6, size * 0.2 - (size * 0.62) / 3 - size * 0.02);
    boat.push(paint(sail, flat(tint)));
    for (const g of boat) { g.rotateY(look.heading); parts.push(g); }
  }

  // trees: on land people have been to. LLM guesses stay bare rock.
  const trees = kind === "idea" || kind === "entity" ? 1 + Math.floor(rnd() * 3) : 0;
  for (let t = 0; t < trees; t++) {
    const r = size * (0.09 + rnd() * 0.05);
    const at = spot(r);
    if (!at) continue;
    const h = r * (2.6 + rnd());
    const cone = new ConeGeometry(r, h, 5, 1);
    cone.translate(at.x, h / 2, at.z);
    parts.push(paint(cone, flat(rnd() < 0.5 ? TREE : TREE_DARK)));
  }

  const merged = mergeGeometries(parts, false);
  for (const p of parts) p.dispose();
  merged.computeVertexNormals();
  merged.computeBoundingSphere();
  return merged;
}
