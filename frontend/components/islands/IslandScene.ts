// The floating-islands map, as a plain three.js scene with no React in it. React pushes data in with setData();
// the scene diffs by id and animates the difference: a new island rises and pops, an absorbed island flies into
// the one that swallowed it, a re-scored mutation drifts along its bearing.
//
// Plain three.js rather than @react-three/fiber on purpose: Next's App Router runs its own vendored React canary,
// and r3f's reconciler is pinned to the public React minor.
import {
  BufferGeometry, CanvasTexture, CircleGeometry, Color, CylinderGeometry, DirectionalLight, Group, HemisphereLight, Line,
  LineBasicMaterial, LineDashedMaterial, LineLoop, Mesh, MeshBasicMaterial, MeshStandardMaterial, OrthographicCamera,
  QuadraticBezierCurve3, Raycaster, RingGeometry, Scene, Sprite, SpriteMaterial, Vector2, Vector3, WebGLRenderer,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { layoutExtent, ringRadius, type IslandPlacement, type LayoutState } from "@/lib/islandLayout";
import { buildIslandGeometry, LANTERN_AT, lookKey, type IslandLook } from "./islandGeometry";

export interface IslandDatum {
  id: string;
  label: string;
  tint: string;
  badges: string[];
  similarity: number | null;
  p: IslandPlacement;
}
export interface SceneLink { a: string; b: string; kind: "similar" | "possible_same_as" | "mutation_of" }
export interface CameraPose { position: [number, number, number]; target: [number, number, number]; zoom: number; userMoved: boolean }
export interface SceneCallbacks { onHover(id: string | null): void; onSelect(id: string | null): void; onContextLost(): void; /** the first frame is on screen */ onReady?(): void }
export interface SceneOptions { reducedMotion: boolean; ambient?: boolean; seen: Set<string>; camera: CameraPose | null; labelLayer: HTMLElement | null }

const FLOOR_Y = -2.5;
const POP_MS = 720;
const MOVE_MS = 1400;
const MERGE_MS = 620;
const VIEW = 10; // half-height of the orthographic frustum at zoom 1
const INK = new Color("#16181d");
const AMBER = new Color("#e9a23b");
const TEAL = new Color("#0f766e");

const easeOutBack = (t: number) => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); };
const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);
const easeInOutCubic = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const clamp01 = (n: number) => Math.min(1, Math.max(0, n));

interface Island {
  datum: IslandDatum;
  group: Group;
  mesh: Mesh;
  hit: Mesh;
  shadow: Mesh;
  look: string;
  bornAt: number;
  from: Vector3;
  to: Vector3;
  moveAt: number;
  /** where the mutation sat before it was re-scored, for the trail */
  origin: Vector3 | null;
  lift: number;
  dying: { at: number; into: Vector3 | null } | null;
  phase: number;
}

interface Arc { key: string; a: string; b: string; kind: SceneLink["kind"]; line: Line; bornAt: number }
interface Ripple { mesh: Mesh; at: number; size: number }

function blobTexture(): CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const ctx = c.getContext("2d")!;
  const g = ctx.createRadialGradient(64, 64, 4, 64, 64, 64);
  g.addColorStop(0, "rgba(22,24,29,0.34)");
  g.addColorStop(0.55, "rgba(22,24,29,0.13)");
  g.addColorStop(1, "rgba(22,24,29,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  return new CanvasTexture(c);
}

function glowTexture(): CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const ctx = c.getContext("2d")!;
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, "rgba(244,185,66,0.85)");
  g.addColorStop(0.4, "rgba(244,185,66,0.28)");
  g.addColorStop(1, "rgba(244,185,66,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  return new CanvasTexture(c);
}

export class IslandScene {
  private renderer: WebGLRenderer;
  private scene = new Scene();
  private camera: OrthographicCamera;
  private controls: OrbitControls;
  private raycaster = new Raycaster();
  private islands = new Map<string, Island>();
  private arcs = new Map<string, Arc>();
  private ripples: Ripple[] = [];
  private labels = new Map<string, HTMLElement>();
  private material = new MeshStandardMaterial({ vertexColors: true, flatShading: true, roughness: 0.92, metalness: 0 });
  private shadowMat: MeshBasicMaterial;
  private shadowGeo = new CircleGeometry(1, 28);
  private rippleGeo = new RingGeometry(0.94, 1, 56);
  /** a generous invisible cylinder around each island: what the pointer actually hits */
  private hitGeo = new CylinderGeometry(1.1, 0.95, 1.8, 10);
  private hitMat = new MeshBasicMaterial({ visible: false });
  private halo: Sprite;
  private rings = new Group();
  private links: SceneLink[] = [];
  private pointer = new Vector2();
  private pointerDirty = false;
  private pointerInside = false;
  private down: { x: number; y: number } | null = null;
  private hoverId: string | null = null;
  private selectedId: string | null = null;
  private userMoved = false;
  private extent = 8;
  private zoomTarget: number | null = null;
  private raf = 0;
  private running = false;
  private visible = true;
  private w = 1;
  private h = 1;
  private disposed = false;
  private drawn = false;
  private io: IntersectionObserver | null = null;
  private tmp = new Vector3();
  private focus = new Vector3();
  private shift = new Vector3();

  constructor(private canvas: HTMLCanvasElement, private cb: SceneCallbacks, private opts: SceneOptions) {
    this.renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setClearColor(0x000000, 0);

    this.camera = new OrthographicCamera(-VIEW, VIEW, VIEW, -VIEW, 0.1, 400);
    this.camera.position.set(40, 34, 40);
    this.camera.lookAt(0, 0, 0);

    this.scene.add(new HemisphereLight(0xffffff, 0xd9d3c6, 1.35));
    const sun = new DirectionalLight(0xfff6e8, 2.1);
    sun.position.set(-14, 26, 9);
    this.scene.add(sun);

    this.shadowMat = new MeshBasicMaterial({ map: blobTexture(), transparent: true, depthWrite: false });
    this.scene.add(this.rings);
    this.buildRings();

    this.halo = new Sprite(new SpriteMaterial({ map: glowTexture(), transparent: true, depthWrite: false, opacity: 0 }));
    this.halo.scale.setScalar(7);
    this.scene.add(this.halo);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.09;
    this.controls.minPolarAngle = (38 * Math.PI) / 180;
    this.controls.maxPolarAngle = (70 * Math.PI) / 180;
    this.controls.minZoom = 0.35;
    this.controls.maxZoom = 4;
    this.controls.screenSpacePanning = true;
    this.controls.zoomSpeed = 0.8;
    if (opts.ambient) {
      this.controls.enabled = false;
      this.controls.autoRotate = !opts.reducedMotion;
      this.controls.autoRotateSpeed = 0.55;
    }
    this.controls.addEventListener("start", this.onControlStart);

    if (opts.camera) {
      this.camera.position.fromArray(opts.camera.position);
      this.controls.target.fromArray(opts.camera.target);
      this.camera.zoom = opts.camera.zoom;
      this.userMoved = opts.camera.userMoved;
      this.camera.updateProjectionMatrix();
    }

    if (!opts.ambient) {
      canvas.addEventListener("pointermove", this.onPointerMove);
      canvas.addEventListener("pointerleave", this.onPointerLeave);
      canvas.addEventListener("pointerdown", this.onPointerDown);
      canvas.addEventListener("pointerup", this.onPointerUp);
    }
    canvas.addEventListener("webglcontextlost", this.onLost);
    document.addEventListener("visibilitychange", this.onVisibility);
    if (typeof IntersectionObserver !== "undefined") {
      this.io = new IntersectionObserver((entries) => { this.visible = entries.some((e) => e.isIntersecting); this.sync(); });
      this.io.observe(canvas);
    }
    this.sync();
  }

  // --- data -----------------------------------------------------------------------------------------------------------

  setData(data: IslandDatum[], links: SceneLink[], layout: LayoutState): void {
    const now = performance.now();
    const next = new Map(data.map((d) => [d.id, d] as const));
    this.links = links;

    // removals: an island that vanishes in the same update that marks another as "merged" was absorbed by it
    const gone = [...this.islands.values()].filter((i) => !i.dying && !next.has(i.datum.id));
    if (gone.length) {
      const absorbers = data.filter((d) => d.badges.includes("merged") && !this.islands.get(d.id)?.datum.badges.includes("merged"));
      for (const g of gone) {
        const home = absorbers.length === 1 ? absorbers[0] : absorbers.sort((a, b) => dist(a.p, g.datum.p) - dist(b.p, g.datum.p))[0];
        g.dying = { at: now, into: home ? new Vector3(home.p.x, home.p.y, home.p.z) : null };
        this.removeLabel(g.datum.id);
        const absorber = home ? this.islands.get(home.id) : undefined;
        if (absorber) absorber.group.userData.pulseAt = now + MERGE_MS * 0.8;
      }
    }

    // births and updates
    const newcomers = data.filter((d) => !this.islands.has(d.id));
    const unseen = newcomers.filter((d) => !this.opts.seen.has(d.id));
    const stagger = unseen.length > 1 ? Math.min(60, 1200 / unseen.length) : 0;
    let k = 0;
    for (const d of data) {
      const cur = this.islands.get(d.id);
      if (!cur) {
        const fresh = !this.opts.seen.has(d.id) && !this.opts.reducedMotion;
        this.add(d, fresh ? now + stagger * k++ : -Infinity);
        this.opts.seen.add(d.id);
        continue;
      }
      if (cur.dying) { cur.dying = null; }
      const look = this.lookOf(d);
      if (lookKey(look) !== cur.look) {
        cur.mesh.geometry.dispose();
        cur.mesh.geometry = buildIslandGeometry(look);
        cur.look = lookKey(look);
        cur.shadow.scale.setScalar(d.p.size * 1.5);
        cur.hit.scale.setScalar(d.p.size);
        cur.hit.position.y = -0.05 * d.p.size;
      }
      if (d.p.x !== cur.to.x || d.p.z !== cur.to.z || d.p.y !== cur.to.y) {
        this.current(cur, now, cur.from);
        if (d.p.kind === "mutation" && !cur.origin) cur.origin = cur.to.clone();
        cur.to.set(d.p.x, d.p.y, d.p.z);
        cur.moveAt = this.opts.reducedMotion ? -Infinity : now;
      }
      cur.datum = d;
    }

    // Lean the camera halfway toward where the islands actually are: a real run is lopsided (one source dominates),
    // but your idea should stay near the middle of the picture.
    let minX = 0, maxX = 0, minZ = 0, maxZ = 0;
    for (const id of layout.order) {
      const p = layout.byId[id];
      minX = Math.min(minX, p.x - p.size); maxX = Math.max(maxX, p.x + p.size);
      minZ = Math.min(minZ, p.z - p.size); maxZ = Math.max(maxZ, p.z + p.size);
    }
    this.focus.set((minX + maxX) / 4, 0, (minZ + maxZ) / 4);
    this.extent = Math.max(layoutExtent(layout) * 0.62, ...layout.order.map((id) => Math.hypot(layout.byId[id].x - this.focus.x, layout.byId[id].z - this.focus.z) + layout.byId[id].size));
    this.syncArcs(now);
    if (!this.userMoved) this.fit(false);
    this.sync();
  }

  setSelected(id: string | null): void {
    if (id === this.selectedId) return;
    this.selectedId = id;
    this.syncArcs(performance.now());
    this.sync();
  }

  private lookOf(d: IslandDatum): IslandLook {
    return { seed: d.p.seed, size: d.p.size, kind: d.p.kind, tint: d.tint, winner: d.badges.includes("winner"), heading: d.p.kind === "mutation" ? Math.atan2(d.p.x, d.p.z) : 0 };
  }

  private add(d: IslandDatum, bornAt: number) {
    const look = this.lookOf(d);
    const mesh = new Mesh(buildIslandGeometry(look), this.material);
    mesh.userData.id = d.id;
    const hit = new Mesh(this.hitGeo, this.hitMat);
    hit.scale.setScalar(d.p.size);
    hit.position.y = -0.05 * d.p.size;
    hit.userData.id = d.id;
    const group = new Group();
    group.add(mesh, hit);
    const shadow = new Mesh(this.shadowGeo, this.shadowMat);
    shadow.rotation.x = -Math.PI / 2;
    shadow.scale.setScalar(d.p.size * 1.5);
    shadow.renderOrder = -1;
    this.scene.add(group, shadow);
    const to = new Vector3(d.p.x, d.p.y, d.p.z);
    const island: Island = { datum: d, group, mesh, hit, shadow, look: lookKey(look), bornAt, from: to.clone(), to, moveAt: -Infinity, origin: null, lift: 0, dying: null, phase: (d.p.seed % 1000) / 159 };
    this.islands.set(d.id, island);
    if (bornAt > 0 && d.p.kind !== "prior") this.ripple(to, d.p.size, bornAt);
  }

  private ripple(at: Vector3, size: number, when: number) {
    const mesh = new Mesh(this.rippleGeo, new MeshBasicMaterial({ color: INK, transparent: true, opacity: 0, depthWrite: false }));
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set(at.x, FLOOR_Y + 0.01, at.z);
    this.scene.add(mesh);
    this.ripples.push({ mesh, at: when, size });
  }

  /** where an island is right now, given its tween */
  private current(i: Island, now: number, out: Vector3): Vector3 {
    const t = i.moveAt === -Infinity ? 1 : clamp01((now - i.moveAt) / MOVE_MS);
    return out.copy(i.from).lerp(i.to, easeInOutCubic(t));
  }

  // --- links ----------------------------------------------------------------------------------------------------------

  private syncArcs(now: number) {
    const want = new Map<string, SceneLink>();
    const focus = this.selectedId ?? this.hoverId;
    const similar = this.links.filter((l) => l.kind === "similar" && this.islands.get(l.b)?.datum.p.kind === "entity" && !this.islands.get(l.b)!.dying);
    const top = [...similar].sort((x, y) => (this.islands.get(y.b)!.datum.similarity ?? 0) - (this.islands.get(x.b)!.datum.similarity ?? 0)).slice(0, 6);
    for (const l of top) want.set(`${l.a}>${l.b}`, l);
    for (const l of this.links) {
      if (!this.islands.has(l.a) || !this.islands.has(l.b)) continue;
      if (l.kind !== "similar" || l.a === focus || l.b === focus) want.set(`${l.a}>${l.b}`, l);
    }
    for (const [key, arc] of this.arcs) {
      if (want.has(key)) continue;
      this.scene.remove(arc.line);
      arc.line.geometry.dispose();
      (arc.line.material as LineBasicMaterial).dispose();
      this.arcs.delete(key);
    }
    for (const [key, l] of want) {
      if (this.arcs.has(key)) continue;
      const geometry = new BufferGeometry().setFromPoints(Array.from({ length: 28 }, () => new Vector3()));
      const material = l.kind === "similar"
        ? new LineBasicMaterial({ color: INK, transparent: true, opacity: 0.22 })
        : new LineDashedMaterial({ color: l.kind === "mutation_of" ? TEAL : AMBER, transparent: true, opacity: 0.85, dashSize: 0.32, gapSize: 0.22 });
      const line = new Line(geometry, material);
      line.frustumCulled = false;
      this.scene.add(line);
      this.arcs.set(key, { key, a: l.a, b: l.b, kind: l.kind, line, bornAt: this.opts.reducedMotion ? -Infinity : now });
    }
  }

  private curve = new QuadraticBezierCurve3(new Vector3(), new Vector3(), new Vector3());

  private updateArc(arc: Arc, now: number) {
    const a = this.islands.get(arc.a);
    const b = this.islands.get(arc.b);
    if (!a || !b) return;
    const pa = a.group.position;
    const pb = b.group.position;
    const span = pa.distanceTo(pb);
    this.curve.v0.set(pa.x, pa.y + 0.15, pa.z);
    this.curve.v2.set(pb.x, pb.y + 0.15, pb.z);
    this.curve.v1.copy(this.curve.v0).add(this.curve.v2).multiplyScalar(0.5);
    this.curve.v1.y += 0.9 + span * 0.22;
    const pos = arc.line.geometry.getAttribute("position");
    for (let i = 0; i < pos.count; i++) {
      this.curve.getPoint(i / (pos.count - 1), this.tmp);
      pos.setXYZ(i, this.tmp.x, this.tmp.y, this.tmp.z);
    }
    pos.needsUpdate = true;
    if (arc.kind !== "similar") arc.line.computeLineDistances();
    const grown = arc.bornAt === -Infinity ? 1 : easeOutCubic(clamp01((now - arc.bornAt) / 520));
    arc.line.geometry.setDrawRange(0, Math.max(2, Math.round(grown * pos.count)));
    if (arc.kind === "similar") {
      const focus = this.selectedId ?? this.hoverId;
      (arc.line.material as LineBasicMaterial).opacity = focus && (arc.a === focus || arc.b === focus) ? 0.55 : 0.2;
    }
  }

  // --- range rings ----------------------------------------------------------------------------------------------------

  private buildRings() {
    for (const sim of [0.75, 0.5, 0.25]) {
      const r = ringRadius(sim);
      const pts = Array.from({ length: 128 }, (_, i) => new Vector3(Math.cos((i / 128) * Math.PI * 2) * r, FLOOR_Y, Math.sin((i / 128) * Math.PI * 2) * r));
      const loop = new LineLoop(new BufferGeometry().setFromPoints(pts), new LineBasicMaterial({ color: INK, transparent: true, opacity: 0.09 }));
      this.rings.add(loop);
    }
  }

  // --- camera ---------------------------------------------------------------------------------------------------------

  private fitZoom(): number {
    const aspect = this.w / Math.max(1, this.h);
    const need = this.extent + 1.2;
    // the ground circle keeps its width on screen and is squashed vertically by the camera's elevation
    const elev = Math.atan2(this.camera.position.y - this.controls.target.y, Math.hypot(this.camera.position.x - this.controls.target.x, this.camera.position.z - this.controls.target.z));
    const zx = (VIEW * aspect) / need;
    const zy = VIEW / (need * Math.sin(elev) + 3.2);
    return Math.max(this.controls.minZoom, Math.min(1.9, Math.min(zx, zy)));
  }

  private fit(snap: boolean) {
    const z = this.fitZoom();
    if (snap || this.opts.reducedMotion || this.islands.size <= 1) { this.camera.zoom = z; this.camera.updateProjectionMatrix(); this.zoomTarget = null; }
    else this.zoomTarget = z;
  }

  recenter(): void {
    this.userMoved = false;
    this.controls.target.copy(this.focus);
    this.camera.position.set(40, 34, 40).add(this.focus);
    this.fit(false);
  }

  getCameraPose(): CameraPose {
    return { position: this.camera.position.toArray() as [number, number, number], target: this.controls.target.toArray() as [number, number, number], zoom: this.camera.zoom, userMoved: this.userMoved };
  }

  resize(w: number, h: number): void {
    if (w <= 0 || h <= 0) return;
    const first = this.w === 1 && this.h === 1;
    this.w = w; this.h = h;
    const aspect = w / h;
    this.camera.left = -VIEW * aspect; this.camera.right = VIEW * aspect;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
    if (!this.userMoved) this.fit(first);
  }

  // --- frame ----------------------------------------------------------------------------------------------------------

  private sync() {
    const should = !this.disposed && this.visible && !document.hidden;
    if (should && !this.running) { this.running = true; this.raf = requestAnimationFrame(this.frame); }
    else if (!should && this.running) { this.running = false; cancelAnimationFrame(this.raf); }
    // nobody is watching an animation in a hidden tab: jump every tween to its end and draw once
    if (!should && !this.disposed && this.w > 1) { if (this.zoomTarget != null) { this.camera.zoom = this.zoomTarget; this.zoomTarget = null; this.camera.updateProjectionMatrix(); } this.tick(performance.now() + 10_000); }
  }

  private frame = (now: number) => {
    if (!this.running) return;
    this.raf = requestAnimationFrame(this.frame);
    this.tick(now);
  };

  /** One frame of work. Also called directly while the loop is paused (hidden tab), so new data still gets drawn. */
  private tick(now: number) {

    if (this.zoomTarget != null) {
      this.camera.zoom += (this.zoomTarget - this.camera.zoom) * 0.06;
      if (Math.abs(this.zoomTarget - this.camera.zoom) < 0.002) { this.camera.zoom = this.zoomTarget; this.zoomTarget = null; }
      this.camera.updateProjectionMatrix();
    }
    if (!this.userMoved && !this.opts.ambient) {
      // slide target and camera together so the viewing angle never changes
      this.shift.copy(this.focus).sub(this.controls.target);
      if (this.shift.lengthSq() > 1e-6) {
        this.shift.multiplyScalar(this.running ? 0.05 : 1);
        this.controls.target.add(this.shift);
        this.camera.position.add(this.shift);
      }
    }
    this.controls.update();
    if (this.pointerDirty) this.pick();

    const still = this.opts.reducedMotion;
    for (const [id, i] of this.islands) {
      const p = this.current(i, now, i.group.position);
      const born = i.bornAt === -Infinity ? 1 : clamp01((now - i.bornAt) / POP_MS);
      let scale = born <= 0 ? 0 : easeOutBack(born);
      p.y += (1 - easeOutCubic(born)) * -2.2;
      if (!still) p.y += Math.sin(now * 0.0011 + i.phase) * 0.07;

      const wantLift = id === this.selectedId ? 0.42 : id === this.hoverId ? 0.22 : 0;
      i.lift += (wantLift - i.lift) * (still ? 1 : 0.16);
      p.y += i.lift;
      scale *= 1 + i.lift * 0.18;

      const pulseAt = i.group.userData.pulseAt as number | undefined;
      if (pulseAt && now > pulseAt) {
        const t = (now - pulseAt) / 520;
        if (t < 1) scale *= 1 + Math.sin(t * Math.PI) * 0.16; else i.group.userData.pulseAt = undefined;
      }

      if (i.dying) {
        const t = clamp01((now - i.dying.at) / MERGE_MS);
        if (i.dying.into) p.lerp(i.dying.into, easeInOutCubic(t)); else p.y -= t * 2;
        scale *= 1 - easeInOutCubic(t);
        if (t >= 1) { this.drop(id); continue; }
      }
      i.group.scale.setScalar(Math.max(0.0001, scale));
      i.shadow.position.set(p.x, FLOOR_Y, p.z);
      i.shadow.visible = scale > 0.05;
      i.shadow.scale.setScalar(i.datum.p.size * 1.5 * Math.min(1, scale));
    }

    const idea = this.islands.get("idea");
    if (idea) {
      this.halo.position.copy(idea.group.position).y += idea.datum.p.size * LANTERN_AT * idea.group.scale.y;
      const born = idea.bornAt === -Infinity ? 1 : clamp01((now - idea.bornAt) / POP_MS);
      (this.halo.material as SpriteMaterial).opacity = born * (still ? 0.6 : 0.52 + Math.sin(now * 0.0016) * 0.12);
    } else (this.halo.material as SpriteMaterial).opacity = 0;

    for (let r = this.ripples.length - 1; r >= 0; r--) {
      const rp = this.ripples[r];
      const t = (now - rp.at) / 950;
      if (t < 0) continue;
      if (t >= 1) { this.scene.remove(rp.mesh); (rp.mesh.material as MeshBasicMaterial).dispose(); this.ripples.splice(r, 1); continue; }
      rp.mesh.scale.setScalar(rp.size * (1 + easeOutCubic(t) * 2.2));
      (rp.mesh.material as MeshBasicMaterial).opacity = 0.3 * (1 - t);
    }

    for (const arc of this.arcs.values()) this.updateArc(arc, now);
    this.renderer.render(this.scene, this.camera);
    // the first render is the slow one (it compiles the shaders), so this is when the loader may go
    if (!this.drawn && this.w > 1) { this.drawn = true; this.cb.onReady?.(); }
    if (!this.opts.ambient) this.placeLabels();
  }

  private drop(id: string) {
    const i = this.islands.get(id);
    if (!i) return;
    this.scene.remove(i.group, i.shadow);
    i.mesh.geometry.dispose();
    this.islands.delete(id);
    this.syncArcs(performance.now());
  }

  // --- picking --------------------------------------------------------------------------------------------------------

  private onControlStart = () => { this.userMoved = true; this.zoomTarget = null; };
  private onPointerMove = (e: PointerEvent) => {
    const r = this.canvas.getBoundingClientRect();
    this.pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    this.pointerInside = true;
    this.pointerDirty = true;
  };
  private onPointerLeave = () => { this.pointerInside = false; this.pointerDirty = true; };
  private onPointerDown = (e: PointerEvent) => { this.down = { x: e.clientX, y: e.clientY }; };
  private onPointerUp = (e: PointerEvent) => {
    const d = this.down;
    this.down = null;
    if (!d || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 5) return;
    this.onPointerMove(e);
    this.pick();
    this.cb.onSelect(this.hoverId);
  };

  private pick() {
    this.pointerDirty = false;
    let id: string | null = null;
    if (this.pointerInside) {
      this.raycaster.setFromCamera(this.pointer, this.camera);
      const meshes = [...this.islands.values()].filter((i) => !i.dying).map((i) => i.hit);
      const hit = this.raycaster.intersectObjects(meshes, false)[0];
      id = (hit?.object.userData.id as string | undefined) ?? null;
    }
    if (id === this.hoverId) return;
    this.hoverId = id;
    this.canvas.style.cursor = id ? "pointer" : "grab";
    this.syncArcs(performance.now());
    this.sync();
    this.cb.onHover(id);
  }

  // --- labels ---------------------------------------------------------------------------------------------------------

  private removeLabel(id: string) {
    this.labels.get(id)?.remove();
    this.labels.delete(id);
  }

  private placeLabels() {
    const layer = this.opts.labelLayer;
    if (!layer) return;
    const ranked = [...this.islands.values()].filter((i) => !i.dying && i.datum.p.kind === "entity").sort((a, b) => (b.datum.similarity ?? 0) - (a.datum.similarity ?? 0)).slice(0, 5).map((i) => i.datum.id);
    const want: string[] = ["idea", this.selectedId, this.hoverId, ...[...this.islands.values()].filter((i) => i.datum.p.kind === "mutation").map((i) => i.datum.id), ...ranked]
      .filter((id, n, all): id is string => !!id && this.islands.has(id) && all.indexOf(id) === n);

    for (const id of [...this.labels.keys()]) if (!want.includes(id)) this.removeLabel(id);

    const boxes: { x: number; y: number; w: number; h: number }[] = [];
    for (const id of want) {
      const i = this.islands.get(id)!;
      let el = this.labels.get(id);
      if (!el) {
        el = document.createElement("div");
        el.className = "island-label";
        layer.appendChild(el);
        this.labels.set(id, el);
      }
      const text = id === "idea" ? "Your idea" : i.datum.label.length > 30 ? `${i.datum.label.slice(0, 29).trimEnd()}…` : i.datum.label;
      if (el.textContent !== text) el.textContent = text;
      el.dataset.kind = id === "idea" ? "idea" : i.datum.p.kind;
      el.dataset.on = id === this.selectedId || id === this.hoverId ? "1" : "0";

      this.tmp.copy(i.group.position);
      this.tmp.y += i.datum.p.size * (id === "idea" ? 1.3 : 0.8) + 0.3; // clear of the lighthouse cap
      this.tmp.project(this.camera);
      const x = (this.tmp.x * 0.5 + 0.5) * this.w;
      const y = (-this.tmp.y * 0.5 + 0.5) * this.h;
      const w = Math.min(190, text.length * 6.6 + 18);
      const box = { x: x - w / 2, y: y - 22, w, h: 22 };
      const forced = id === "idea" || id === this.selectedId || id === this.hoverId;
      const clash = boxes.some((b) => box.x < b.x + b.w && box.x + box.w > b.x && box.y < b.y + b.h && box.y + box.h > b.y);
      const born = i.bornAt === -Infinity ? 1 : clamp01((performance.now() - i.bornAt) / POP_MS);
      const show = (forced || !clash) && born > 0.6 && x > -40 && x < this.w + 40 && y > 0 && y < this.h + 20;
      el.style.opacity = show ? "1" : "0";
      el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -100%)`;
      if (show) boxes.push(box);
    }
  }

  // --- lifecycle ------------------------------------------------------------------------------------------------------

  private onLost = (e: Event) => { e.preventDefault(); this.cb.onContextLost(); };
  private onVisibility = () => this.sync();

  dispose(): void {
    this.disposed = true;
    this.sync();
    this.io?.disconnect();
    document.removeEventListener("visibilitychange", this.onVisibility);
    this.canvas.removeEventListener("pointermove", this.onPointerMove);
    this.canvas.removeEventListener("pointerleave", this.onPointerLeave);
    this.canvas.removeEventListener("pointerdown", this.onPointerDown);
    this.canvas.removeEventListener("pointerup", this.onPointerUp);
    this.canvas.removeEventListener("webglcontextlost", this.onLost);
    this.controls.removeEventListener("start", this.onControlStart);
    this.controls.dispose();
    for (const id of [...this.labels.keys()]) this.removeLabel(id);
    for (const i of this.islands.values()) i.mesh.geometry.dispose();
    for (const a of this.arcs.values()) { a.line.geometry.dispose(); (a.line.material as LineBasicMaterial).dispose(); }
    for (const r of this.ripples) (r.mesh.material as MeshBasicMaterial).dispose();
    for (const ring of this.rings.children) { (ring as LineLoop).geometry.dispose(); ((ring as LineLoop).material as LineBasicMaterial).dispose(); }
    this.shadowMat.map?.dispose();
    this.shadowMat.dispose();
    this.shadowGeo.dispose();
    this.rippleGeo.dispose();
    this.hitGeo.dispose();
    this.hitMat.dispose();
    (this.halo.material as SpriteMaterial).map?.dispose();
    (this.halo.material as SpriteMaterial).dispose();
    this.material.dispose();
    this.renderer.dispose();
  }
}

function dist(a: IslandPlacement, b: IslandPlacement): number {
  return Math.hypot(a.x - b.x, a.z - b.z);
}
