// Procedural low-poly islands. Everything is seeded by the node id, so an island has the same coastline, the same
// buildings and the same trees on every render. One merged, vertex-coloured geometry per island: one draw call each.
import { BoxGeometry, BufferAttribute, BufferGeometry, Color, ConeGeometry, CylinderGeometry } from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { mulberry32 } from "@/lib/seeded";
import type { IslandKind } from "@/lib/islandLayout";

const PAPER = new Color("#ece9e2");
const WHITE = new Color("#ffffff");
const ROCK_TOP = new Color("#c4bdb0");
const ROCK_TIP = new Color("#8f887c");
const TREE = new Color("#6f9b6c");
const TREE_DARK = new Color("#557f58");
const GOLD = new Color("#e0a422");

export interface IslandLook {
  seed: number;
  size: number;
  kind: IslandKind;
  tint: string;
  buildings: number;
  winner: boolean;
}

export const lookKey = (l: IslandLook) => `${l.seed}:${l.size.toFixed(3)}:${l.kind}:${l.tint}:${l.buildings}:${l.winner ? 1 : 0}`;

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
  const slabH = 0.26 * size + 0.08;
  const ground = kind === "prior" ? new Color("#d5d2ca") : tint.clone().lerp(PAPER, kind === "idea" ? 0.45 : 0.68);
  const slab = new CylinderGeometry(size, size * 0.9, slabH, sides, 1);
  roughen(slab, coast, 0.16);
  slab.translate(0, -slabH / 2, 0);
  parts.push(paint(slab, flat(ground)));

  // the rock underneath, tapering to a point
  const rockH = size * (1.25 + rnd() * 0.5);
  const rock = new ConeGeometry(size * 0.88, rockH, sides, 2);
  roughen(rock, coast, 0.16);
  rock.rotateX(Math.PI);
  rock.translate((rnd() - 0.5) * 0.1 * size, -slabH - rockH / 2, (rnd() - 0.5) * 0.1 * size);
  const tip = new Color();
  parts.push(paint(rock, (_x, y) => tip.copy(ROCK_TOP).lerp(ROCK_TIP, Math.min(1, (-y - slabH) / rockH))));

  // buildings: pale walls, a roof in the colour of the source
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

  const walls = tint.clone().lerp(WHITE, 0.62);
  const roofTint = kind === "idea" ? new Color("#e9a23b") : tint.clone().lerp(PAPER, 0.12);
  for (let b = 0; b < look.buildings; b++) {
    const tower = kind === "idea" && b === 0;
    const w = size * (tower ? 0.3 : 0.2 + rnd() * 0.14);
    const d = size * (tower ? 0.3 : 0.2 + rnd() * 0.14);
    const h = size * (tower ? 1.05 : 0.24 + rnd() * 0.42);
    const at = tower ? (taken.push({ x: 0, z: 0, r: w * 0.75 }), { x: 0, z: 0 }) : spot(Math.max(w, d) * 0.75);
    if (!at) continue;
    const turn = rnd() * Math.PI;
    const body = new BoxGeometry(w, h, d);
    body.rotateY(turn);
    body.translate(at.x, h / 2, at.z);
    parts.push(paint(body, flat(walls)));
    const roofH = Math.max(0.035, size * 0.05);
    const roof = new BoxGeometry(w * 1.12, roofH, d * 1.12);
    roof.rotateY(turn);
    roof.translate(at.x, h + roofH / 2, at.z);
    parts.push(paint(roof, flat(look.winner && b === 0 ? GOLD : roofTint)));
  }

  // trees
  const trees = kind === "prior" ? 0 : kind === "mutation" ? 1 : 1 + Math.floor(rnd() * 3);
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
