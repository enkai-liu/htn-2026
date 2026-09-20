// The islands map, as a plain three.js scene with no React in it. React pushes data in with setData();
// the scene diffs by id and animates the difference: a new island rises out of the sea and pops, an absorbed island flies into
// the one that swallowed it, a re-scored mutation drifts along its bearing.
//
// Plain three.js rather than @react-three/fiber on purpose: Next's App Router runs its own vendored React canary,
// and r3f's reconciler is pinned to the public React minor.
import {
  BufferGeometry, CanvasTexture, Color, CylinderGeometry, DirectionalLight, DoubleSide, Float32BufferAttribute, Group, HemisphereLight, Line,
  LineBasicMaterial, LineDashedMaterial, Mesh, MeshBasicMaterial, MeshStandardMaterial, OrthographicCamera,
  PlaneGeometry, QuadraticBezierCurve3, Raycaster, RingGeometry, Scene, Sprite, SpriteMaterial, Vector2, Vector3, WebGLRenderer,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { layoutExtent, type IslandPlacement, type LayoutState } from "@/lib/islandLayout";
import { buildIslandGeometry, LANTERN_AT, lookKey, waterline, type IslandLook } from "./islandGeometry";

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
export interface SceneOptions {
  reducedMotion: boolean; ambient?: boolean;
  /** where across a wide canvas the middle of the map sits, 0..1: the landing page keeps its islands clear of the form */
  anchorX?: number;
  seen: Set<string>; camera: CameraPose | null; labelLayer: HTMLElement | null;
}

/** sea level: everything on the map stands in, or sails on, this plane */
const SEA_Y = 0;
const POP_MS = 720;
const MOVE_MS = 1400;
// Slow on purpose: this is the resolver's decision becoming visible -- two listings of one project sailing
// together into a single island. At 620ms it was over before anyone could follow what had happened.
const MERGE_MS = 1500;
const MERGE_PULSE_MS = 620; // the absorber's answering swell, once the other island lands
const VIEW = 10; // half-height of the orthographic frustum at zoom 1
const INK = new Color("#16181d");
const AMBER = new Color("#e9a23b");
const TEAL = new Color("#0f766e");
const FOAM = new Color("#ffffff");
const SEA = new Color("#b6e7f5");
const SEA_DEEP = new Color("#93d3ec");

/**
 * How hard OrbitControls pulls the camera toward the pointer, as a fraction of the gap per 60fps frame.
 * 0.09 leaves a ~180ms tail behind a drag, which is most of what read as lag; the factor is recomputed
 * from the real frame time every tick, so the glide feels the same at 30fps as at 120.
 */
const DAMPING = 0.22;

/** a per-60fps-frame lerp fraction, re-expressed for the frame we actually got */
const ease = (per60: number, dt: number) => 1 - Math.pow(1 - per60, dt / 16.667);

/** idle beam sweep, rad/ms — a full turn in about 11s */
const IDLE_SWEEP = 0.00058;
/** how hard the beam is allowed to swing when it is chasing a find */
const SLEW_MAX = 0.0031;

const easeOutBack = (t: number) => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); };
const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);
const easeInOutCubic = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const clamp01 = (n: number) => Math.min(1, Math.max(0, n));
const smoothstep = (a: number, b: number, x: number) => { const t = clamp01((x - a) / (b - a)); return t * t * (3 - 2 * t); };

interface Island {
  datum: IslandDatum;
  group: Group;
  mesh: Mesh;
  hit: Mesh;
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

interface Arc { key: string; a: string; b: string; kind: SceneLink["kind"]; line: Line; bornAt: number; lastA: Vector3; lastB: Vector3 }
interface Ripple { mesh: Mesh; at: number; size: number }
/** a label and what was last written to it, so a still map stops writing styles altogether */
interface Label { el: HTMLElement; x: number; y: number; shown: boolean }

const SEA_CELLS = 96;
/** the finest facet, in map units; the sheet doubles it each time the view outgrows the water */
const SEA_CELL = 0.7;

/**
 * The sea: one sheet of low-poly water that always fills the view. There is no edge to it: every frame the sheet
 * is laid back down under the camera, snapped to its own grid, and every vertex takes its jitter, swell and depth
 * from where it is on the map. So panning slides the view over still water instead of dragging the facets along.
 */
function seaGeometry(): PlaneGeometry {
  const g = new PlaneGeometry(1, 1, SEA_CELLS, SEA_CELLS);
  g.rotateX(-Math.PI / 2);
  return g;
}

/** -0.5..0.5 for a grid point: the same point always gets the same nudge, whichever vertex lands on it */
function jitter(i: number, j: number): number {
  const n = Math.sin(i * 127.1 + j * 311.7) * 43758.5453;
  return n - Math.floor(n) - 0.5;
}

/**
 * The wave train, as [dirX, dirZ, wavenumber, speed, height]: each row is one sine rolling across the map in
 * its own direction. One long swell carries the sea, with a second running a few degrees off it so the crests
 * wander instead of corrugating, and the three short ones on top are the chop this sea always had. The second
 * swell stays small on purpose: at equal heights two crossing trains stop being a swell and become an egg
 * crate, which from the landing page's altitude read as a cloudy sky rather than water.
 *
 * This table is the only place the waves are written down. The shader's GLSL is generated from it (see
 * seaMaterial) and swell() below sums the same rows, so the water the boats ride cannot drift out of step with
 * the water they are drawn on.
 */
const WAVES: readonly (readonly [number, number, number, number, number])[] = [
  [0.86, 0.51, 0.55, 0.6, 0.105], // the swell that carries the sea
  [0.62, 0.78, 0.95, -0.75, 0.048], // a shorter one a few degrees off it
  [1, 0, 0.62, 0.9, 0.05],
  [0.273, 0.962, 0.842, -0.7, 0.045],
  [-0.5, 0.87, 1.45, 0.95, 0.022],
  [0.707, 0.707, 1.938, 1.3, 0.028],
];

/**
 * How much of one wave survives at a given facet size. A sheet whose facets are half a wavelength across cannot
 * draw that wave; it draws the beat between the wave and its own grid instead, and with the vertices jittered
 * that beat is noise -- which is what turned the zoomed-out hero's water into a cloudy sky. So each row fades
 * out as the facets close on it, and the view is left with the long swell that the grid can still carry.
 *
 * The facet size handed in here is the unrounded one. The sheet itself can only step in doublings, and fading
 * against a value that jumps by 2x would pop the whole surface as you crossed each boundary.
 */
const waveFade = (k: number, cell: number) => smoothstep(2, 4, (2 * Math.PI) / k / cell);

/** The height of the swell at a point on the map. Boats ask too, so they ride the same water they are drawn on. */
function swell(x: number, z: number, t: number, cell: number): number {
  let h = 0;
  for (const [dx, dz, k, speed, amp] of WAVES) h += Math.sin((x * dx + z * dz) * k + t * speed) * amp * waveFade(k, cell);
  return h;
}

interface SeaUniforms { uTime: { value: number }; uFocus: { value: Vector2 }; uFar: { value: number }; uCell: { value: number } }

/**
 * The water's material. Swell and depth tint are pure functions of where a vertex is on the map and what time
 * it is, so they belong on the GPU: in JS they meant rewriting and re-uploading every one of the sheet's ~9,400
 * vertices -- position and colour, a sine per wave apiece, a quarter of a megabyte -- on every single frame,
 * which was the bulk of the map's frame budget. Here the vertex buffer only changes when the grid the sheet is
 * laid on moves (see laySea), and a still camera uploads nothing at all. Which is why the sea can afford a
 * proper wave train and foam on the crests now: another few sines per vertex is nothing to a GPU, and the CPU
 * never sees them.
 *
 * Displacing in the vertex shader keeps the facets: flat shading takes its normals from screen-space
 * derivatives in the fragment shader, so it sees the water the vertex shader actually built.
 */
function seaMaterial(uniforms: SeaUniforms): MeshStandardMaterial {
  const m = new MeshStandardMaterial({ flatShading: true, transparent: true, opacity: 0.88, depthWrite: false, roughness: 0.5, metalness: 0 });
  // Colors are already in the renderer's linear working space, which is what the shader wants
  const rgb = (c: Color) => `vec3(${c.r.toFixed(5)}, ${c.g.toFixed(5)}, ${c.b.toFixed(5)})`;
  const f = (n: number) => n.toFixed(5);
  // The same rows swell() sums, unrolled: no loop, no uniform array, and the compiler folds every constant
  // but the fade, which needs the live facet size. `power` accumulates the variance the rows contribute, so
  // the crest and trough thresholds below can be set in standard deviations of the surface at this zoom.
  // Adding them up instead would give the height of every row peaking at once, which six waves never do: the
  // thresholds would sit above anything the water reaches and the foam would wash out to nothing.
  const train = WAVES.map(([dx, dz, k, speed, a]) => `
        amp = ${f(a)} * smoothstep(2.0, 4.0, ${f((2 * Math.PI) / k)} / uCell);
        wave += sin((p.x * ${f(dx)} + p.y * ${f(dz)}) * ${f(k)} + uTime * ${f(speed)}) * amp;
        power += amp * amp * 0.5;`).join("");
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", `#include <common>
        uniform float uTime;
        uniform vec2 uFocus;
        uniform float uFar;
        uniform float uCell;
        varying vec3 vSeaTint;`)
      .replace("#include <begin_vertex>", `#include <begin_vertex>
        vec2 p = vec2(position.x, position.z);
        float wave = 0.0;
        float amp = 0.0;
        float power = 0.0;${train}
        transformed.y += wave;
        // the water deepens away from the archipelago, which is what gives a screen of flat colour a middle
        float depth = clamp(length(p - uFocus) / uFar, 0.0, 1.0);
        vec3 tint = mix(${rgb(SEA)}, ${rgb(SEA_DEEP)}, depth * depth * (3.0 - 2.0 * depth));
        // Foam, and the reason the waves are visible at all: from this camera a tenth of a unit of height is
        // almost nothing, but the colour breaking on the crests reads from across the room. Only the top of a
        // crest catches it, so the sea stays pale and calm between them rather than going stormy.
        // Foam, and the reason the waves are visible at all: from this camera a tenth of a unit of height is
        // almost nothing, but the colour breaking along the crest lines reads from across the room. The
        // troughs darken by the same measure -- half the sense of a swell is the shadow between the crests.
        float sigma = sqrt(max(power, 1e-8));
        float crest = smoothstep(sigma * 0.9, sigma * 1.8, wave);
        float trough = smoothstep(-sigma * 0.7, -sigma * 1.7, wave);
        vSeaTint = mix(tint * (1.0 - trough * 0.14), ${rgb(FOAM)}, crest * 0.5);`);
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vSeaTint;")
      .replace("#include <color_fragment>", "#include <color_fragment>\ndiffuseColor.rgb *= vSeaTint;");
  };
  return m;
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

/**
 * The lighthouse beam: a real shaft of light leaving the lantern, not a decal on the water.
 *
 * A truncated cone, narrow at the lantern and flaring out over the sea, built with per-vertex alpha so the
 * light thins out along its length and dies before the horizon. Two nested shells — a tight bright core and a
 * wider soft haze — stand in for the volumetric falloff a real light has, which is as close as this gets
 * without a post-processing pass. Drawn double-sided and without depth writes so the shells blend into each
 * other rather than z-fighting, and tilted down so it rakes across the islands instead of shooting past them.
 */
function beamShell(halfAngle: number, alpha: number): Mesh {
  const LEN = 1; // scaled to the map's reach every frame
  // The whole cone is scaled by the beam's length each frame, so the near radius is scaled too: at 0.018 and
  // a 20-unit reach the shaft started 0.36 across -- wider than the lamp it is supposed to leave, which is
  // what made it read as a disc parked on the tower rather than light coming out of it. 0.004 lands near 0.08.
  const g = new CylinderGeometry(Math.tan(halfAngle) * LEN, 0.004, LEN, 20, 8, true);
  g.translate(0, LEN / 2, 0); // lantern end at the origin, beam runs up +Y
  g.rotateZ(-Math.PI / 2); // ...then lay it along +X, so a group rotation about Y sweeps it

  const pos = g.getAttribute("position");
  const col = new Float32BufferAttribute(new Float32Array(pos.count * 4), 4);
  for (let i = 0; i < pos.count; i++) {
    const t = clamp01(pos.getX(i) / LEN); // 0 at the lantern, 1 at the far end
    // bright at the source, then a long tail: light falls off fast but never cuts off square
    const a = alpha * (1 - t) ** 2.1 * (0.25 + 0.75 * (1 - t));
    col.setXYZW(i, 1, 0.78, 0.36, a);
  }
  g.setAttribute("color", col);
  return new Mesh(g, new MeshBasicMaterial({ transparent: true, vertexColors: true, depthWrite: false, side: DoubleSide }));
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
  private labels = new Map<string, Label>();
  /** ids that currently deserve a label; rebuilt on data/selection/hover, not per frame */
  private labelWant: string[] = [];
  /** hit meshes for picking, rebuilt with the island set rather than on every pointer move */
  private pickMeshes: Mesh[] = [];
  private material = new MeshStandardMaterial({ vertexColors: true, flatShading: true, roughness: 0.92, metalness: 0 });
  private sea: Mesh;
  /** the facet size the water is drawn at right now */
  private seaCell = SEA_CELL;
  private seaUniforms: SeaUniforms = { uTime: { value: 0 }, uFocus: { value: new Vector2() }, uFar: { value: 16 }, uCell: { value: SEA_CELL } };
  /** the facet size the waves are faded against: the one the view asks for, before it is rounded to a doubling */
  private waveCell = SEA_CELL;
  /** the grid the sheet is currently laid on: while that does not move, its buffer is left alone */
  private seaAt = { i: NaN, j: NaN, c: 0 };
  private rippleGeo = new RingGeometry(0.94, 1, 56);
  /** a generous invisible cylinder around each island: what the pointer actually hits */
  private hitGeo = new CylinderGeometry(1.1, 0.95, 1.8, 10);
  private hitMat = new MeshBasicMaterial({ visible: false });
  /** scout boats working the water: decoration, on their own wandering orbits */
  private boats: { mesh: Mesh; r: number; spd: number; ph: number; wob: number; bob: number }[] = [];
  private halo: Sprite;
  private beacon = new Group();
  private shells: Mesh[] = [];
  private links: SceneLink[] = [];
  private pointer = new Vector2();
  /** the last pointer position in client space; turned into scene coordinates once a frame, in pick() */
  private client = { x: 0, y: 0 };
  private pointerDirty = false;
  private pointerInside = false;
  private down: { x: number; y: number } | null = null;
  private hoverId: string | null = null;
  private selectedId: string | null = null;
  private userMoved = false;
  private extent = 8;
  private zoomTarget: number | null = null;
  /** an explicit camera fly toward a focused island; overrides the passive follow, cancelled if you grab the camera */
  private flyTo: Vector3 | null = null;
  /** live render scale and a rolling frame time, for the adaptive-resolution step in tick() */
  private dpr = 1;
  private dprMax = 1;
  private frameAvg = 0;
  /** how long frames have been comfortable, in ms, and how much of a penalty a step down left behind */
  private calm = 0;
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
  private beam = new Vector3();
  private eye = new Vector3();
  private ground = new Vector3();
  private look = new Vector3();
  /** the beam's own bearing, integrated by hand so it can be steered off the idle sweep and back */
  private beaconAngle = 0;
  /** angular velocity, so swinging onto a target ramps up and settles instead of snapping */
  private beaconVel = -IDLE_SWEEP;
  private lastNow = 0;
  /** islands that have arrived and not yet been swept: the light goes and looks at each one */
  private scanQueue: string[] = [];
  private scanning: { id: string; until: number } | null = null;
  /** eased beam length, so locking on pulls the light in to land on the island instead of past it */
  private beamLen = 0;

  constructor(private canvas: HTMLCanvasElement, private cb: SceneCallbacks, private opts: SceneOptions) {
    // On a 2x display the multisample buffer costs real bandwidth over a full-window canvas, for edges the
    // pixel density has already smoothed. It earns its keep at 1x and not much above.
    this.dprMax = this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.renderer = new WebGLRenderer({ canvas, antialias: this.dpr < 1.5, alpha: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(this.dpr);
    this.renderer.setClearColor(0x000000, 0);

    this.camera = new OrthographicCamera(-VIEW, VIEW, VIEW, -VIEW, 0.1, 400);
    this.camera.position.set(40, 34, 40);
    this.camera.lookAt(0, 0, 0);

    this.scene.add(new HemisphereLight(0xffffff, 0xd9d3c6, 1.35));
    const sun = new DirectionalLight(0xfff6e8, 2.1);
    sun.position.set(-14, 26, 9);
    this.scene.add(sun);

    // The water is translucent and writes no depth: the shoals under each island show through it as shallows,
    // and everything drawn on the surface (rings, ripples, the beam) simply goes over it.
    this.sea = new Mesh(seaGeometry(), seaMaterial(this.seaUniforms));
    this.sea.position.y = SEA_Y;
    this.sea.renderOrder = -2;
    this.sea.frustumCulled = false;
    this.scene.add(this.sea);

    this.halo = new Sprite(new SpriteMaterial({ map: glowTexture(), transparent: true, depthWrite: false, opacity: 0 }));
    this.halo.scale.setScalar(2.5); // a glow around the lamp, not a disc laid over the whole island
    this.scene.add(this.halo);

    // three nested shells stand in for radial falloff: a tight bright core, a haze, and a faint outer bloom.
    // A single cone would read as a solid wedge, because every vertex of an open cone sits on its rim.
    this.shells = [beamShell(0.042, 0.52), beamShell(0.105, 0.2), beamShell(0.2, 0.075)];
    for (const m of this.shells) {
      m.renderOrder = 3; // over the islands, so the light rakes across them
      this.beacon.add(m);
    }
    this.beacon.rotation.order = "YZX"; // sweep about Y first, then the fixed downward tilt
    this.beacon.rotation.z = -0.085; // rake down toward the water rather than out to the horizon
    this.scene.add(this.beacon);

    // Boats out working the water. The same hull the mutations use, so they belong to the same world, but
    // small and grey-sailed: a teal boat means "your idea went this way" and these must not read as that.
    // Radii are fractions of the map's extent, so they keep their station as the neighbourhood grows.
    if (!opts.reducedMotion) {
      for (let i = 0; i < 5; i++) {
        const mesh = new Mesh(buildIslandGeometry({ seed: 9001 + i * 137, size: 0.52, kind: "mutation", tint: "#8d929c", winner: false, heading: 0 }), this.material);
        mesh.frustumCulled = false;
        this.boats.push({ mesh, r: 0.42 + i * 0.16, spd: (i % 2 ? -1 : 1) * (0.000035 + (i % 3) * 0.000012), ph: i * 1.27, wob: 0.06 + (i % 3) * 0.03, bob: i * 0.9 });
        this.scene.add(mesh);
      }
    }

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = DAMPING; // recomputed from the real frame time every tick
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
    this.rebuildLabelSet();
    this.rebuildPickList();
    if (!this.userMoved) this.fit(false);
    this.sync();
  }

  setSelected(id: string | null): void {
    if (id === this.selectedId) return;
    this.selectedId = id;
    const isl = id ? this.islands.get(id) : undefined;
    if (isl && !this.opts.reducedMotion && !this.opts.ambient) {
      // fly to the island and close in on it; the zoom eases through the existing zoomTarget ramp
      this.flyTo = new Vector3(isl.group.position.x, 0, isl.group.position.z);
      this.zoomTarget = Math.min(1.9, Math.max(this.controls.minZoom, this.fitZoom() * 2.1));
    } else if (!id) {
      this.flyTo = this.opts.ambient ? null : this.focus.clone();
      if (!this.opts.reducedMotion) this.fit(false);
    }
    this.syncArcs(performance.now());
    this.rebuildLabelSet();
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
    this.scene.add(group);
    const to = new Vector3(d.p.x, d.p.y, d.p.z);
    const island: Island = { datum: d, group, mesh, hit, look: lookKey(look), bornAt, from: to.clone(), to, moveAt: -Infinity, origin: null, lift: 0, dying: null, phase: (d.p.seed % 1000) / 159 };
    this.islands.set(d.id, island);
    if (bornAt > 0 && d.p.kind !== "prior") this.ripple(to, d.p.size, bornAt);
    // a fresh arrival is something the swarm just found: send the light over to look at it. Keep only the
    // newest few -- a burst of forty hits would otherwise queue up minutes of sweeping nobody waits through.
    if (bornAt > 0 && d.id !== "idea" && !this.opts.reducedMotion) {
      this.scanQueue.push(d.id);
      if (this.scanQueue.length > 4) this.scanQueue.splice(0, this.scanQueue.length - 4);
    }
  }

  private ripple(at: Vector3, size: number, when: number) {
    const mesh = new Mesh(this.rippleGeo, new MeshBasicMaterial({ color: FOAM, transparent: true, opacity: 0, depthWrite: false }));
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set(at.x, SEA_Y + 0.12, at.z); // clear of the crests
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
    // Focusing an island reveals its own links. The idea is the exception: every `similar` link starts at it,
    // so "show what this connects to" would be "show all of them" -- forty-odd lines converging on one island,
    // which says nothing. Focusing the idea widens the ranked set instead of lifting the cap.
    const ideaFocused = focus === "idea";
    const ranked = [...similar].sort((x, y) => (this.islands.get(y.b)!.datum.similarity ?? 0) - (this.islands.get(x.b)!.datum.similarity ?? 0));
    for (const l of ranked.slice(0, ideaFocused ? 12 : 6)) want.set(`${l.a}>${l.b}`, l);
    for (const l of this.links) {
      if (!this.islands.has(l.a) || !this.islands.has(l.b)) continue;
      if (l.kind !== "similar" || (!ideaFocused && (l.a === focus || l.b === focus))) want.set(`${l.a}>${l.b}`, l);
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
      // NaN ends: never equal to a real position, so updateArc builds the curve on its first frame
      this.arcs.set(key, { key, a: l.a, b: l.b, kind: l.kind, line, bornAt: this.opts.reducedMotion ? -Infinity : now, lastA: new Vector3(NaN, NaN, NaN), lastB: new Vector3(NaN, NaN, NaN) });
    }
  }

  private curve = new QuadraticBezierCurve3(new Vector3(), new Vector3(), new Vector3());

  private updateArc(arc: Arc, now: number) {
    const a = this.islands.get(arc.a);
    const b = this.islands.get(arc.b);
    if (!a || !b) return;
    const pa = a.group.position;
    const pb = b.group.position;
    if (arc.kind === "similar") {
      const focus = this.selectedId ?? this.hoverId;
      (arc.line.material as LineBasicMaterial).opacity = focus && (arc.a === focus || arc.b === focus) ? 0.55 : 0.2;
    }
    // Both ends standing still and the line fully drawn means the 28-point sweep, the dash lengths and the
    // buffer upload are all work to arrive at the curve that is already there.
    const grown = arc.bornAt === -Infinity ? 1 : easeOutCubic(clamp01((now - arc.bornAt) / 520));
    if (grown === 1 && arc.lastA.equals(pa) && arc.lastB.equals(pb)) return;
    arc.lastA.copy(pa);
    arc.lastB.copy(pb);

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
    arc.line.geometry.setDrawRange(0, Math.max(2, Math.round(grown * pos.count)));
  }

  // --- sea ------------------------------------------------------------------------------------------------------------

  private laySea(t: number) {
    // where the middle of the screen meets the water, and how much water the view takes in around it
    this.camera.updateMatrixWorld();
    this.camera.getWorldDirection(this.look);
    this.ground.set(0, 0, -1).unproject(this.camera);
    this.ground.addScaledVector(this.look, (SEA_Y - this.ground.y) / this.look.y);
    const halfW = (this.camera.right - this.camera.left) / 2;
    const reach = (Math.hypot(halfW, VIEW / Math.max(0.3, -this.look.y)) / this.camera.zoom) * 1.12;

    this.waveCell = Math.max(SEA_CELL, (2 * reach) / SEA_CELLS);
    // coarser facets when zoomed out, finer again on the way back in; the slack stops it flickering at a boundary
    while (2 * reach > SEA_CELLS * this.seaCell) this.seaCell *= 2;
    while (this.seaCell > SEA_CELL && 2 * reach < SEA_CELLS * this.seaCell * 0.42) this.seaCell /= 2;
    const c = this.seaCell;
    const i0 = Math.round(this.ground.x / c) - SEA_CELLS / 2;
    const j0 = Math.round(this.ground.z / c) - SEA_CELLS / 2;

    // The swell and the depth tint are the shader's job now, so they cost nothing here: hand it the clock and
    // where the archipelago is, and leave the buffer alone unless the sheet has actually been picked up.
    this.seaUniforms.uTime.value = t;
    this.seaUniforms.uFocus.value.set(this.focus.x, this.focus.z);
    this.seaUniforms.uFar.value = this.extent * 1.5 + 8;
    this.seaUniforms.uCell.value = this.waveCell;
    if (i0 === this.seaAt.i && j0 === this.seaAt.j && c === this.seaAt.c) return;
    this.seaAt = { i: i0, j: j0, c };

    // Laid back down under the camera and snapped to its own grid: every vertex takes its nudge from where it
    // is on the map, so panning slides the view over still water instead of dragging the facets along. Only a
    // pan across a whole facet gets this far, which is a handful of times a second rather than sixty.
    const pos = this.sea.geometry.getAttribute("position").array as Float32Array;
    for (let j = 0, v = 0; j <= SEA_CELLS; j++) {
      for (let i = 0; i <= SEA_CELLS; i++, v++) {
        pos[v * 3] = (i0 + i + jitter(i0 + i, j0 + j) * 0.6) * c;
        pos[v * 3 + 2] = (j0 + j + jitter(j0 + j, i0 + i + 57) * 0.6) * c;
      }
    }
    this.sea.geometry.getAttribute("position").needsUpdate = true;
  }

  // --- camera ---------------------------------------------------------------------------------------------------------

  /** where the middle of the map sits across the canvas: off-centre only when there is the width to spare */
  private anchor(): number {
    return this.w / Math.max(1, this.h) > 1.25 ? this.opts.anchorX ?? 0.5 : 0.5;
  }

  private fitZoom(): number {
    const aspect = this.w / Math.max(1, this.h);
    const need = this.extent + 1.2;
    // the ground circle keeps its width on screen and is squashed vertically by the camera's elevation
    const elev = Math.atan2(this.camera.position.y - this.controls.target.y, Math.hypot(this.camera.position.x - this.controls.target.x, this.camera.position.z - this.controls.target.z));
    const u = this.anchor();
    // off-centre, the map gets the room from its anchor back to the middle of the canvas (the other half belongs
    // to whatever pushed it aside) and may run off the near edge
    const zx = (VIEW * aspect * 2 * (u === 0.5 ? 0.5 : Math.abs(u - 0.5) * 0.95)) / need;
    const zy = VIEW / (need * Math.sin(elev) + 2.4);
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
    // a view offset rather than a lopsided frustum: zoom scales the frustum about its own middle, which would drag an
    // off-centre map back toward the centre of the canvas as it zoomed out
    const u = this.anchor();
    if (u === 0.5) this.camera.clearViewOffset(); else this.camera.setViewOffset(w, h, (0.5 - u) * w, 0, w, h);
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
    // A tick called straight out of sync() carries a made-up timestamp, and the first one after a hidden tab
    // carries a huge one: neither is a real interval, so fall back to a single 60fps frame.
    const raw = now - this.lastNow;
    const real = this.lastNow > 0 && raw > 0 && raw < 200;
    const dt = real ? raw : 16.667;
    if (real && this.running) this.frameAvg = this.frameAvg ? this.frameAvg * 0.9 + raw * 0.1 : raw;
    if (this.running) this.lastNow = now;
    // Every ease below is a fraction of the remaining gap per frame, so on a slow frame the camera would
    // cover half as much ground as on a fast one -- heavier exactly when the map is already struggling.
    this.controls.dampingFactor = ease(DAMPING, dt);

    if (this.zoomTarget != null) {
      this.camera.zoom += (this.zoomTarget - this.camera.zoom) * ease(0.06, dt);
      if (Math.abs(this.zoomTarget - this.camera.zoom) < 0.002) { this.camera.zoom = this.zoomTarget; this.zoomTarget = null; }
      this.camera.updateProjectionMatrix();
    }
    // A focus fly overrides the passive follow, and survives userMoved: selecting an island is itself a
    // pointerdown, so OrbitControls has already flagged the camera as user-driven by the time we hear about
    // the selection. Grabbing the camera afterwards cancels the fly (see onControlStart).
    if (this.flyTo && !this.opts.ambient) {
      this.shift.copy(this.flyTo).sub(this.controls.target);
      if (this.shift.lengthSq() < 4e-4) this.flyTo = null;
      else {
        this.shift.multiplyScalar(this.running ? ease(0.075, dt) : 1);
        this.controls.target.add(this.shift);
        this.camera.position.add(this.shift);
      }
    } else if (!this.userMoved && !this.selectedId && !this.opts.ambient) {
      // Nothing is selected, so the camera is free to follow the archipelago as it grows. A selection holds it
      // where the fly left it: a click does that by flagging userMoved on its own pointerdown, but a selection
      // made in code (the map tour, focusing a mutation from another tab) never touches the pointer, and without
      // this the camera would slide off the island a second after arriving.
      // slide target and camera together so the viewing angle never changes
      this.shift.copy(this.focus).sub(this.controls.target);
      if (this.shift.lengthSq() > 1e-6) {
        this.shift.multiplyScalar(this.running ? ease(0.05, dt) : 1);
        this.controls.target.add(this.shift);
        this.camera.position.add(this.shift);
      }
    }
    this.controls.update(dt / 1000); // in seconds, and only the hero's auto-rotation reads it: without it that drifts with the frame rate
    if (this.pointerDirty) this.pick();

    const still = this.opts.reducedMotion;
    const t = still ? 0 : now * 0.001;
    const liftK = still ? 1 : ease(0.16, dt);

    this.laySea(t);

    for (const [id, i] of this.islands) {
      const p = this.current(i, now, i.group.position);
      const born = i.bornAt === -Infinity ? 1 : clamp01((now - i.bornAt) / POP_MS);
      let scale = born <= 0 ? 0 : easeOutBack(born);
      p.y += (1 - easeOutCubic(born)) * -2.2;
      // land stands still; only a boat rides the swell
      const afloat = i.datum.p.kind === "mutation";
      if (afloat) p.y += swell(p.x, p.z, t, this.waveCell);

      const wantLift = id === this.selectedId ? 0.16 : id === this.hoverId ? 0.08 : 0;
      i.lift += (wantLift - i.lift) * liftK;
      p.y += i.lift;
      scale *= 1 + i.lift * 0.5;

      const pulseAt = i.group.userData.pulseAt as number | undefined;
      if (pulseAt && now > pulseAt) {
        const u = (now - pulseAt) / MERGE_PULSE_MS;
        if (u < 1) scale *= 1 + Math.sin(u * Math.PI) * 0.16; else i.group.userData.pulseAt = undefined;
      }

      if (i.dying) {
        const u = clamp01((now - i.dying.at) / MERGE_MS);
        if (i.dying.into) p.lerp(i.dying.into, easeInOutCubic(u)); else p.y -= u * 2; // nowhere to go: it sinks
        scale *= 1 - easeInOutCubic(u);
        if (u >= 1) { this.drop(id); continue; }
      }
      // placements are heights above the sea; the group's origin is the turf, so stand it on its waterline
      p.y += SEA_Y + waterline(i.datum.p.kind, i.datum.p.size) * Math.min(1, scale);
      if (afloat && !still) i.mesh.rotation.z = Math.sin(now * 0.0011 + i.phase) * 0.04; // roll with the swell
      i.group.scale.setScalar(Math.max(0.0001, scale));
    }

    // sail the scouts: a wandering orbit, heading taken from where the next step actually puts them
    for (const b of this.boats) {
      const span = Math.max(6, this.extent);
      const at = (t: number) => {
        const a = b.ph + t * b.spd;
        const r = span * (b.r + Math.sin(a * 2.3 + b.ph) * b.wob);
        return { x: Math.cos(a) * r, z: Math.sin(a) * r };
      };
      const p = at(now), q = at(now + 240);
      b.mesh.position.set(p.x, SEA_Y + waterline("mutation", 0.52) + swell(p.x, p.z, t, this.waveCell), p.z);
      b.mesh.rotation.y = Math.atan2(q.x - p.x, q.z - p.z);
      b.mesh.rotation.z = Math.sin(now * 0.0011 + b.bob) * 0.05; // roll with the swell
    }

    const idea = this.islands.get("idea");
    if (idea) {
      this.halo.position.copy(idea.group.position).y += idea.datum.p.size * LANTERN_AT * idea.group.scale.y;
      const born = idea.bornAt === -Infinity ? 1 : clamp01((now - idea.bornAt) / POP_MS);
      // the beam leaves the lantern and reaches the furthest island, so it lights the neighbourhood searched
      let reach = 6;
      for (const i of this.islands.values()) reach = Math.max(reach, Math.hypot(i.group.position.x, i.group.position.z) + i.datum.p.size);
      const lantern = idea.datum.p.size * LANTERN_AT * idea.group.scale.y;
      this.beacon.position.copy(idea.group.position).y += lantern;
      this.beacon.visible = !still && born > 0.25;

      // Steering. Idle is a slow sweep; an arrival pulls the light off it, holds a beat on the island, then
      // hands back. The hold shortens when arrivals are stacked up, so a busy run still feels like scanning
      // rather than a queue being worked through.
      let locked = 0;
      let wantLen = reach * 1.15;
      if (!still) {
        if (!this.scanning && this.scanQueue.length) {
          const id = this.scanQueue.shift()!;
          if (this.islands.has(id)) this.scanning = { id, until: 0 };
        }
        const target = this.scanning ? this.islands.get(this.scanning.id) : undefined;
        if (this.scanning && (!target || target.dying)) this.scanning = null;

        // Steer by velocity, not by position. Lerping the angle straight at the target makes the beam
        // change direction in a single frame when a find lands; ramping the velocity instead means every
        // swing accelerates out of the idle sweep and settles into it again.
        let wantVel = -IDLE_SWEEP;
        if (this.scanning && target) {
          // the beam's local +X maps to (cos y, 0, -sin y) under a Y rotation, hence the negated dz
          const want = Math.atan2(-(target.group.position.z - idea.group.position.z), target.group.position.x - idea.group.position.x);
          let d = want - this.beaconAngle;
          d = Math.atan2(Math.sin(d), Math.cos(d)); // shortest way round
          wantVel = Math.max(-SLEW_MAX, Math.min(SLEW_MAX, d * 0.0042));
          if (!this.scanning.until && Math.abs(d) < 0.05) {
            this.scanning.until = now + (this.scanQueue.length > 1 ? 340 : 820);
            target.group.userData.pulseAt = now; // the island reacts as the light lands on it
          }
          locked = this.scanning.until ? 1 : 1 - Math.min(1, Math.abs(d));
          // pull the shaft in so the light lands on the island rather than running past it to the horizon;
          // scaling the cone shortens and narrows it together, which is what a tightening spot should do
          wantLen = Math.hypot(target.group.position.x - idea.group.position.x, target.group.position.z - idea.group.position.z) + target.datum.p.size * 0.5;
          if (this.scanning.until && now > this.scanning.until) this.scanning = null;
        }
        this.beaconVel += (wantVel - this.beaconVel) * Math.min(1, dt * 0.0032);
        this.beaconAngle += this.beaconVel * dt;
      }
      this.beacon.rotation.y = still ? 0.6 : this.beaconAngle;
      this.beamLen = this.beamLen ? this.beamLen + (wantLen - this.beamLen) * Math.min(1, dt * 0.005) : wantLen;
      this.beacon.scale.setScalar(this.beamLen);

      // a real lighthouse flares as the beam comes round to face you, and the shaft is shortest head-on:
      // driving both the halo and the shells from one angle keeps them reading as a single light
      let flash = 0;
      if (!still) {
        this.beam.set(1, 0, 0).applyQuaternion(this.beacon.quaternion).setY(0).normalize();
        this.eye.copy(this.camera.position).sub(this.controls.target).setY(0).normalize();
        flash = Math.max(0, this.beam.dot(this.eye)) ** 6;
        // locked on a find the light burns harder, but the boost is weighted to the core: brightening the
        // outer bloom as hard would just fatten the shaft into a slab instead of tightening it to a spot
        const BOOST = [0.95, 0.4, 0.18];
        this.shells.forEach((m, n) => { (m.material as MeshBasicMaterial).opacity = born * (0.7 + flash * 0.28 + locked * BOOST[n]); });
      }
      (this.halo.material as SpriteMaterial).opacity = born * (still ? 0.6 : 0.46 + Math.sin(now * 0.0016) * 0.08 + flash * 0.5);
      this.halo.scale.setScalar(2.5 * (1 + flash * 0.3));
    } else {
      (this.halo.material as SpriteMaterial).opacity = 0;
      this.beacon.visible = false;
    }

    for (let r = this.ripples.length - 1; r >= 0; r--) {
      const rp = this.ripples[r];
      const t = (now - rp.at) / 950;
      if (t < 0) continue;
      if (t >= 1) { this.scene.remove(rp.mesh); (rp.mesh.material as MeshBasicMaterial).dispose(); this.ripples.splice(r, 1); continue; }
      rp.mesh.scale.setScalar(rp.size * (1 + easeOutCubic(t) * 2.2));
      (rp.mesh.material as MeshBasicMaterial).opacity = 0.3 * (1 - t);
    }

    for (const arc of this.arcs.values()) this.updateArc(arc, now);
    // Adaptive resolution. This scene is fill-bound, not draw-call bound: three double-sided transparent beam
    // shells and a shadow blob under every island mean a lot of overdraw, and on a 2x display that is four
    // times the pixels. When frames are consistently over budget, render fewer of them rather than dropping
    // the effects.
    if (this.running && this.frameAvg > 0) {
      // Floor at 1.25: below that the low-poly edges visibly soften, and a blurry map at 60fps is a worse
      // trade than a crisp one at 45. A real GPU should rarely step at all.
      if (this.frameAvg > 24 && this.dpr > 1.3) {
        this.setScale(Math.max(1.25, this.dpr - 0.25));
        this.calm = -4000; // and a long way back before it may try to climb again
      } else if (this.dpr < this.dprMax) {
        // Earn the resolution back, but slowly: a run that stutters while forty islands land should not
        // spend the rest of the session at 1.25, and a brief calm patch should not start it oscillating.
        this.calm = Math.max(-6000, this.calm + (this.frameAvg < 14 ? dt : -dt * 2));
        if (this.calm > 2500) this.setScale(Math.min(this.dprMax, this.dpr + 0.25));
      }
    }
    this.renderer.render(this.scene, this.camera);
    // the first render is the slow one (it compiles the shaders), so this is when the loader may go
    if (!this.drawn && this.w > 1) { this.drawn = true; this.cb.onReady?.(); }
    if (!this.opts.ambient) this.placeLabels();
  }

  private setScale(dpr: number) {
    this.dpr = dpr;
    this.renderer.setPixelRatio(dpr);
    this.frameAvg = 0; // let it settle before judging again
    this.calm = 0;
  }

  private drop(id: string) {
    const i = this.islands.get(id);
    if (!i) return;
    this.scene.remove(i.group);
    i.mesh.geometry.dispose();
    this.islands.delete(id);
    // the label set and the pick list are cached, and this is the other way an island leaves the map
    this.rebuildLabelSet();
    this.rebuildPickList();
    this.syncArcs(performance.now());
  }

  // --- picking --------------------------------------------------------------------------------------------------------

  private onControlStart = () => { this.userMoved = true; this.zoomTarget = null; this.flyTo = null; };
  // A trackpad or a high-rate mouse sends pointermove far more often than the screen refreshes, and
  // getBoundingClientRect() can flush layout: keep the raw position and convert it once, in pick().
  private onPointerMove = (e: PointerEvent) => {
    this.client.x = e.clientX;
    this.client.y = e.clientY;
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
      const r = this.canvas.getBoundingClientRect();
      this.pointer.set(((this.client.x - r.left) / r.width) * 2 - 1, -((this.client.y - r.top) / r.height) * 2 + 1);
      this.raycaster.setFromCamera(this.pointer, this.camera);
      const meshes = this.pickMeshes;
      const hit = this.raycaster.intersectObjects(meshes, false)[0];
      id = (hit?.object.userData.id as string | undefined) ?? null;
    }
    if (id === this.hoverId) return;
    this.hoverId = id;
    this.canvas.style.cursor = id ? "pointer" : "grab";
    this.syncArcs(performance.now());
    this.rebuildLabelSet();
    this.sync();
    this.cb.onHover(id);
  }

  private rebuildPickList() {
    this.pickMeshes.length = 0;
    for (const i of this.islands.values()) if (!i.dying) this.pickMeshes.push(i.hit);
  }

  // --- labels ---------------------------------------------------------------------------------------------------------

  private removeLabel(id: string) {
    this.labels.get(id)?.el.remove();
    this.labels.delete(id);
  }

  /**
   * Which islands get a label. Ranking the whole map and de-duplicating is not frame work -- the answer only
   * changes when the data, the selection or the hover changes -- but it used to run every frame: six arrays,
   * a sort over every island and an O(n^2) dedupe, sixty times a second. Cached here and rebuilt on those
   * three events instead.
   */
  private rebuildLabelSet() {
    const ranked: Island[] = [];
    for (const i of this.islands.values()) if (!i.dying && i.datum.p.kind === "entity") ranked.push(i);
    ranked.sort((a, b) => (b.datum.similarity ?? 0) - (a.datum.similarity ?? 0));

    const want = this.labelWant;
    want.length = 0;
    const add = (id: string | null) => { if (id && this.islands.has(id) && !want.includes(id)) want.push(id); };
    add("idea");
    add(this.selectedId);
    add(this.hoverId);
    for (const i of this.islands.values()) if (i.datum.p.kind === "mutation") add(i.datum.id);
    for (let n = 0; n < ranked.length && n < 5; n++) add(ranked[n].datum.id);

    for (const id of [...this.labels.keys()]) if (!want.includes(id)) this.removeLabel(id);
  }

  private placeLabels() {
    const layer = this.opts.labelLayer;
    if (!layer) return;
    const want = this.labelWant;

    const boxes: { x: number; y: number; w: number; h: number }[] = [];
    for (const id of want) {
      const i = this.islands.get(id)!;
      let lab = this.labels.get(id);
      if (!lab) {
        const el = document.createElement("div");
        el.className = "island-label";
        layer.appendChild(el);
        lab = { el, x: NaN, y: NaN, shown: false };
        this.labels.set(id, lab);
      }
      const el = lab.el;
      const text = id === "idea" ? "Your idea" : i.datum.label.length > 30 ? `${i.datum.label.slice(0, 29).trimEnd()}…` : i.datum.label;
      if (el.textContent !== text) el.textContent = text;
      const kind = id === "idea" ? "idea" : i.datum.p.kind;
      const on = id === this.selectedId || id === this.hoverId;
      if (el.dataset.kind !== kind) el.dataset.kind = kind;
      if ((el.dataset.on === "1") !== on) el.dataset.on = on ? "1" : "0";

      this.tmp.copy(i.group.position);
      this.tmp.y += i.datum.p.size * (id === "idea" ? 1.3 : 0.8) + 0.3; // clear of the lighthouse cap
      this.tmp.project(this.camera);
      const x = (this.tmp.x * 0.5 + 0.5) * this.w;
      const y = (-this.tmp.y * 0.5 + 0.5) * this.h;
      const w = Math.min(190, text.length * 6.6 + 18);
      const box = { x: x - w / 2, y: y - 22, w, h: 22 };
      const forced = id === "idea" || on;
      const clash = boxes.some((b) => box.x < b.x + b.w && box.x + box.w > b.x && box.y < b.y + b.h && box.y + box.h > b.y);
      const born = i.bornAt === -Infinity ? 1 : clamp01((performance.now() - i.bornAt) / POP_MS);
      const show = (forced || !clash) && born > 0.6 && x > -40 && x < this.w + 40 && y > 0 && y < this.h + 20;
      if (show !== lab.shown) { el.style.opacity = show ? "1" : "0"; lab.shown = show; }
      if (x !== lab.x || y !== lab.y) {
        el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -100%)`;
        lab.x = x; lab.y = y;
      }
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
    this.sea.geometry.dispose();
    (this.sea.material as MeshStandardMaterial).dispose();
    this.rippleGeo.dispose();
    this.hitGeo.dispose();
    this.hitMat.dispose();
    (this.halo.material as SpriteMaterial).map?.dispose();
    (this.halo.material as SpriteMaterial).dispose();
    for (const m of this.shells) { m.geometry.dispose(); (m.material as MeshBasicMaterial).dispose(); }
    for (const b of this.boats) b.mesh.geometry.dispose(); // hulls own their geometry; the material is shared
    this.material.dispose();
    this.renderer.dispose();
  }
}

function dist(a: IslandPlacement, b: IslandPlacement): number {
  return Math.hypot(a.x - b.x, a.z - b.z);
}
