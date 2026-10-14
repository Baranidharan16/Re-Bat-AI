/**
 * RE-BAT AI — 3D EV battery pack digital twin (three.js, procedural, works offline).
 *
 * Layers (bottom → top, as in an exploded EV pack): base frame · BMS · battery modules (cells) · busbars · cooling plate · top cover.
 * Views:   overview (closed pack) · exploded (labelled layers) · module (one module) · cell (cut-away cell) ·
 *          power (current flow on busbars) · thermal (heat map + coolant flow) · twin (cells coloured by live health)
 */
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

export type LayerId = "base_frame" | "bms" | "modules" | "busbars" | "cooling" | "top_cover";
export type View = "overview" | "exploded" | "module" | "cell" | "power" | "thermal" | "twin" | "minerals";
export type PackSpec = { id: string; cell_shape: "cylindrical" | "pouch" | "prismatic"; visual: { modules: [number, number]; cells: [number, number] } };
export type Twin = { soh?: number | null; tempC?: number | null; currentA?: number | null; voltage?: number | null; imbalanceMv?: number | null; alarm?: boolean; lampOn?: boolean };

export const LAYERS: { id: LayerId; label: string; sub: string }[] = [
  { id: "top_cover", label: "Top cover", sub: "Protection & sealing" },
  { id: "cooling", label: "Cooling plate", sub: "Thermal management" },
  { id: "busbars", label: "Busbars & connectors", sub: "Electrical connection" },
  { id: "modules", label: "Battery modules", sub: "Cell assemblies" },
  { id: "bms", label: "BMS", sub: "Monitoring & protection" },
  { id: "base_frame", label: "Base frame", sub: "Structural support" },
];
const ORDER: LayerId[] = ["base_frame", "bms", "modules", "busbars", "cooling", "top_cover"];
export const CELL_LAYERS = [
  { id: "terminal_pos", label: "Positive terminal (+)", sub: "Aluminium tab / top cap" },
  { id: "vent", label: "Safety vent", sub: "Opens on over-pressure" },
  { id: "cathode", label: "Cathode", sub: "Li + Ni/Mn/Co oxide or FePO₄ on Al foil" },
  { id: "separator", label: "Separator", sub: "Polymer membrane" },
  { id: "anode", label: "Anode", sub: "Graphite on Cu foil" },
  { id: "can", label: "Can / casing", sub: "Steel (cylindrical) or Al / pouch film" },
  { id: "terminal_neg", label: "Negative terminal (−)", sub: "Copper / nickel tab" },
];

const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

function textTexture(text: string) {
  const c = document.createElement("canvas");
  c.width = 1024; c.height = 256;
  const g = c.getContext("2d")!;
  g.clearRect(0, 0, 1024, 256);
  g.font = "italic 700 120px Archivo, Arial, sans-serif";
  g.fillStyle = "rgba(20,26,38,0.55)";
  g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText(text, 512, 128);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}

function stripeTexture(a: string, b: string) {
  const c = document.createElement("canvas");
  c.width = 128; c.height = 8;
  const g = c.getContext("2d")!;
  const grd = g.createLinearGradient(0, 0, 128, 0);
  grd.addColorStop(0, a); grd.addColorStop(0.5, b); grd.addColorStop(1, a);
  g.fillStyle = grd; g.fillRect(0, 0, 128, 8);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(10, 1);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

type Layer = { id: LayerId; outer: THREE.Group; inner: THREE.Group; meshes: THREE.Mesh[]; baseY: number; height: number };

export class PackViewer {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private raycaster = new THREE.Raycaster();
  private pointer = new THREE.Vector2();
  private layers = new Map<LayerId, Layer>();
  private pack = new THREE.Group();
  private cellGroup = new THREE.Group();
  private cells: THREE.InstancedMesh | null = null;
  private cellCenters: THREE.Vector3[] = [];
  private cellSeeds: number[] = [];
  private pulses: { mesh: THREE.Mesh; path: THREE.CurvePath<THREE.Vector3> | THREE.Curve<THREE.Vector3>; t: number; speed: number }[] = [];
  private coolant: THREE.Texture[] = [];
  private explode = 0;
  private explodeTarget = 0;
  private view: View = "overview";
  private twin: Twin = {};
  private selected: LayerId | null = null;
  private hovered: LayerId | null = null;
  private camGoal: { pos: THREE.Vector3; target: THREE.Vector3 } | null = null;
  private labels: { el: HTMLElement; anchor: () => THREE.Vector3; show: () => boolean }[] = [];
  private labelRoot: HTMLElement;
  private raf = 0;
  private clock = new THREE.Clock();
  private ro: ResizeObserver;
  private moduleFocus = new THREE.Vector3();
  private packSize = new THREE.Vector3(10, 1, 6);
  private cellShape: PackSpec["cell_shape"] = "cylindrical";
  private lastInteract = 0;
  private disposed = false;
  onSelect: (id: LayerId | null) => void = () => {};
  onCellPart: (id: string) => void = () => {};

  constructor(private host: HTMLElement, labelRoot: HTMLElement, private opts: { autoRotate?: boolean; compact?: boolean } = {}) {
    this.labelRoot = labelRoot;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    host.appendChild(this.renderer.domElement);
    this.renderer.domElement.style.touchAction = "none";

    const pm = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture;

    this.camera = new THREE.PerspectiveCamera(32, 1, 0.1, 200);
    this.camera.position.set(11, 8.5, 12);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.minDistance = 3;
    this.controls.maxDistance = 40;
    this.controls.maxPolarAngle = Math.PI * 0.49;
    this.controls.autoRotate = !!opts.autoRotate;
    this.controls.autoRotateSpeed = 0.6;
    this.controls.target.set(0, 0.8, 0);
    this.controls.addEventListener("start", () => { this.lastInteract = performance.now(); this.camGoal = null; });

    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(8, 14, 6);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    Object.assign(key.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12, near: 1, far: 40 });
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x6fb6ff, 1.1);
    rim.position.set(-10, 6, -8);
    this.scene.add(rim);
    this.scene.add(new THREE.HemisphereLight(0xbfd8ff, 0x0a1220, 0.55));

    const floor = new THREE.Mesh(new THREE.CircleGeometry(16, 64), new THREE.ShadowMaterial({ opacity: 0.35 }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.02;
    floor.receiveShadow = true;
    this.scene.add(floor);
    const glow = new THREE.Mesh(new THREE.RingGeometry(5.5, 9, 64), new THREE.MeshBasicMaterial({ color: 0x4fc3e0, transparent: true, opacity: 0.05 }));
    glow.rotation.x = -Math.PI / 2;
    glow.position.y = -0.01;
    this.scene.add(glow);

    this.scene.add(this.pack);
    this.scene.add(this.cellGroup);
    this.cellGroup.visible = false;

    const el = this.renderer.domElement;
    el.addEventListener("pointermove", this.onMove);
    el.addEventListener("click", this.onClick);
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.resize();
    this.loop();
  }

  // ------------------------------------------------------------------ build
  load(spec: PackSpec) {
    for (const l of this.layers.values()) { this.pack.remove(l.outer); this.disposeObj(l.outer); }
    this.layers.clear();
    this.pulses = []; this.coolant = []; this.cellCenters = []; this.cellSeeds = [];
    this.cellShape = spec.cell_shape;
    this.clearLabels();

    const [mx, mz] = spec.visual.modules;
    const [cx, cz] = spec.visual.cells;
    const shape = spec.cell_shape;
    // cell footprint in "cell units"
    const pitchX = shape === "cylindrical" ? 1.08 : shape === "pouch" ? 0.55 : 1.25;
    const pitchZ = shape === "cylindrical" ? 1.08 : shape === "pouch" ? 4.4 : 3.8;
    const cellH = shape === "cylindrical" ? 3.4 : 3.0;
    const pad = 0.8, gap = 0.6;
    const modW = cx * pitchX + pad, modD = cz * pitchZ + pad;
    const W = mx * modW + (mx - 1) * gap + 1.6, D = mz * modD + (mz - 1) * gap + 1.6;
    const s = 10 / Math.max(W, D);                // plan scale -> 10 world units on the long side
    const k = Math.max(1, (2.2 / (cellH + 1.6)) / s);  // exaggerate height so cells stay visible
    const sy = s * k;
    this.packSize.set(W * s, (cellH + 1.6) * sy, D * s);

    const mk = (id: LayerId, baseY: number, height: number) => {
      const outer = new THREE.Group(), inner = new THREE.Group();
      inner.scale.set(s, sy, s);
      outer.add(inner);
      outer.position.y = baseY;
      this.pack.add(outer);
      const l: Layer = { id, outer, inner, meshes: [], baseY, height };
      this.layers.set(id, l);
      return l;
    };
    const add = (l: Layer, m: THREE.Mesh) => { m.castShadow = true; m.receiveShadow = true; m.userData.layer = l.id; l.inner.add(m); l.meshes.push(m); return m; };
    const std = (color: number, metalness = 0.6, roughness = 0.45, extra: THREE.MeshPhysicalMaterialParameters = {}) =>
      new THREE.MeshPhysicalMaterial({ color, metalness, roughness, ...extra });

    // base frame (tray) -------------------------------------------------
    const base = mk("base_frame", 0, 0.6 * sy);
    const tray = std(0x39414f, 0.75, 0.45);
    add(base, new THREE.Mesh(new THREE.BoxGeometry(W, 0.4, D), tray)).position.y = 0.2;
    const wallH = cellH * 0.55;
    for (const [w, d, x, z] of [[W, 0.35, 0, D / 2 - 0.175], [W, 0.35, 0, -D / 2 + 0.175], [0.35, D, W / 2 - 0.175, 0], [0.35, D, -W / 2 + 0.175, 0]]) {
      add(base, new THREE.Mesh(new THREE.BoxGeometry(w, wallH, d), tray)).position.set(x, 0.4 + wallH / 2, z);
    }
    for (let i = 1; i < mx; i++) {
      const x = -W / 2 + 0.8 + i * (modW + gap) - gap / 2;
      add(base, new THREE.Mesh(new THREE.BoxGeometry(0.25, 0.5, D - 0.8), std(0x2c3340, 0.7, 0.5))).position.set(x, 0.6, 0);
    }
    const orange = std(0xff7a1a, 0.2, 0.45);
    for (let i = 0; i < 2; i++) {
      const c = add(base, new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.9, 1.1), orange));
      c.position.set(W / 2 + 0.3, 0.9, D / 2 - 1.6 - i * 1.5);
    }

    // BMS board (sits at the front end of the tray) -----------------------
    const bmsY = 0.45 * sy;
    const bms = mk("bms", bmsY, 0.4 * sy);
    const bw = Math.min(W * 0.32, 9), bd = Math.min(D * 0.12, 3.2);
    const board = add(bms, new THREE.Mesh(new THREE.BoxGeometry(bw, 0.12, bd), std(0x1f7a3a, 0.1, 0.55)));
    board.position.set(-W / 2 + 0.8 + bw / 2, 0.06, D / 2 - 0.6 - bd / 2);
    const chip = std(0x0d1117, 0.2, 0.4);
    const gold = std(0xd4a640, 1, 0.25);
    for (let i = 0; i < 6; i++) {
      const c = add(bms, new THREE.Mesh(new THREE.BoxGeometry(bw * (i === 0 ? 0.18 : 0.08), 0.12, bd * (i === 0 ? 0.35 : 0.2)), chip));
      c.position.set(board.position.x - bw * 0.35 + i * bw * 0.14, 0.18, board.position.z + (i % 2 ? -bd * 0.2 : bd * 0.15));
    }
    for (let i = 0; i < 10; i++) {
      const p = add(bms, new THREE.Mesh(new THREE.CylinderGeometry(bd * 0.03, bd * 0.03, 0.15, 8), gold));
      p.position.set(board.position.x + bw * 0.42, 0.18, board.position.z - bd * 0.4 + i * bd * 0.09);
    }

    // modules + cells --------------------------------------------------------
    const modY = 0.6 * sy;
    const mods = mk("modules", modY, (cellH + 0.4) * sy);
    const frameMat = std(0x161d2a, 0.35, 0.6);
    const holderMat = std(0x0e1420, 0.1, 0.8);
    const cellGeo = shape === "cylindrical" ? new THREE.CylinderGeometry(0.47, 0.47, cellH, 18)
      : shape === "pouch" ? new THREE.BoxGeometry(0.42, cellH * 0.95, pitchZ - 0.4) : new THREE.BoxGeometry(1.1, cellH, pitchZ - 0.25);
    const cellMat = new THREE.MeshPhysicalMaterial({ color: 0xffffff, metalness: shape === "pouch" ? 0.5 : 0.35, roughness: 0.32, clearcoat: 0.6, clearcoatRoughness: 0.3 });
    const nCells = mx * mz * cx * cz;
    const inst = new THREE.InstancedMesh(cellGeo, cellMat, nCells);
    inst.castShadow = true; inst.receiveShadow = true;
    inst.userData.layer = "modules";
    const dummy = new THREE.Object3D();
    let n = 0;
    for (let i = 0; i < mx; i++) for (let j = 0; j < mz; j++) {
      const ox = -W / 2 + 0.8 + i * (modW + gap) + modW / 2;
      const oz = -D / 2 + 0.8 + j * (modD + gap) + modD / 2;
      if (i === 0 && j === 0) this.moduleFocus.set(ox * s, modY + (cellH / 2) * sy, oz * s);
      // module frame: end plates + side rails (open top so cells show)
      for (const sz of [-1, 1]) add(mods, new THREE.Mesh(new THREE.BoxGeometry(modW, cellH + 0.3, 0.25), frameMat)).position.set(ox, (cellH + 0.3) / 2, oz + sz * (modD / 2 - 0.12));
      for (const sx of [-1, 1]) add(mods, new THREE.Mesh(new THREE.BoxGeometry(0.2, cellH * 0.85, modD), frameMat)).position.set(ox + sx * (modW / 2 - 0.1), cellH * 0.425, oz);
      add(mods, new THREE.Mesh(new THREE.BoxGeometry(modW - 0.3, 0.18, modD - 0.3), holderMat)).position.set(ox, 0.09, oz);
      for (let a = 0; a < cx; a++) for (let b = 0; b < cz; b++) {
        const x = ox - (cx * pitchX) / 2 + pitchX * (a + 0.5);
        const z = oz - (cz * pitchZ) / 2 + pitchZ * (b + 0.5);
        dummy.position.set(x, cellH / 2 + 0.18, z);
        dummy.updateMatrix();
        inst.setMatrixAt(n, dummy.matrix);
        this.cellCenters.push(new THREE.Vector3(x / (W / 2), 0, z / (D / 2)));
        this.cellSeeds.push(Math.abs(Math.sin((n + 1) * 12.9898) * 43758.5453) % 1);
        n++;
      }
    }
    inst.instanceMatrix.needsUpdate = true;
    mods.inner.add(inst);
    mods.meshes.push(inst);
    this.cells = inst;
    this.paintCells();

    // busbars + HV cables -----------------------------------------------------
    const busY = modY + (cellH + 0.25) * sy;
    const bus = mk("busbars", busY, 0.3 * sy);
    const copper = std(0xd9823f, 0.95, 0.28);
    const busW = shape === "cylindrical" ? 0.5 : 0.7;
    const pulseMat = new THREE.MeshBasicMaterial({ color: 0xffb04a });
    for (let i = 0; i < mx; i++) for (let j = 0; j < mz; j++) {
      const ox = -W / 2 + 0.8 + i * (modW + gap) + modW / 2;
      const oz = -D / 2 + 0.8 + j * (modD + gap) + modD / 2;
      const rows = Math.min(cx, shape === "cylindrical" ? 4 : cx);
      for (let r = 0; r < rows; r++) {
        const x = ox - modW / 2 + 0.4 + (r + 0.5) * ((modW - 0.8) / rows);
        add(bus, new THREE.Mesh(new THREE.BoxGeometry(busW, 0.12, modD - 0.6), copper)).position.set(x, 0.06, oz);
      }
      add(bus, new THREE.Mesh(new THREE.BoxGeometry(modW - 0.6, 0.14, busW), copper)).position.set(ox, 0.12, oz + modD / 2 - 0.5);
    }
    // HV cable loop around the modules to the connectors (orange), with current pulses
    const y = 0.35;
    const pts = [
      new THREE.Vector3(W / 2 + 0.3, y, D / 2 - 1.6), new THREE.Vector3(W / 2 - 0.4, y, D / 2 - 0.6),
      new THREE.Vector3(-W / 2 + 0.6, y, D / 2 - 0.6), new THREE.Vector3(-W / 2 + 0.6, y, -D / 2 + 0.6),
      new THREE.Vector3(W / 2 - 0.4, y, -D / 2 + 0.6), new THREE.Vector3(W / 2 + 0.3, y, D / 2 - 3.1),
    ];
    const curve = new THREE.CatmullRomCurve3(pts, false, "catmullrom", 0.2);
    const cable = add(bus, new THREE.Mesh(new THREE.TubeGeometry(curve, 160, 0.22, 10, false), orange));
    cable.castShadow = false;
    cable.userData.cable = true;
    for (let i = 0; i < 14; i++) {
      const p = new THREE.Mesh(new THREE.SphereGeometry(0.3, 12, 12), pulseMat.clone());
      p.visible = false;
      bus.inner.add(p);
      this.pulses.push({ mesh: p, path: curve, t: i / 14, speed: 0.08 });
    }

    // cooling plate --------------------------------------------------------------
    const coolY = busY + 0.5 * sy;
    const cool = mk("cooling", coolY, 0.35 * sy);
    const alu = std(0xb8c2cf, 0.9, 0.32);
    add(cool, new THREE.Mesh(new THREE.BoxGeometry(W - 1.2, 0.18, D - 1.2), alu)).position.y = 0.09;
    const lanes = Math.max(3, Math.min(9, Math.round(W / 6)));
    const serp: THREE.Vector3[] = [];
    for (let i = 0; i < lanes; i++) {
      const x = -W / 2 + 1.4 + i * ((W - 2.8) / (lanes - 1));
      const zs = i % 2 ? [D / 2 - 1.4, -D / 2 + 1.4] : [-D / 2 + 1.4, D / 2 - 1.4];
      serp.push(new THREE.Vector3(x, 0.3, zs[0]), new THREE.Vector3(x, 0.3, zs[1]));
    }
    const half = Math.ceil(serp.length / 2);
    for (const [seg, a, b] of [[serp.slice(0, half + 1), "#1f6fff", "#7fc8ff"], [serp.slice(half), "#ff7a3a", "#ffcf6a"]] as const) {
      const tex = stripeTexture(a, b);
      this.coolant.push(tex);
      const tc = new THREE.CatmullRomCurve3(seg as THREE.Vector3[], false, "catmullrom", 0.05);
      add(cool, new THREE.Mesh(new THREE.TubeGeometry(tc, 220, 0.2, 10, false),
        new THREE.MeshStandardMaterial({ map: tex, metalness: 0.3, roughness: 0.35, emissive: new THREE.Color(a), emissiveIntensity: 0.25 })));
    }

    // top cover --------------------------------------------------------------------
    const topY = coolY + 0.45 * sy;
    const top = mk("top_cover", topY, 0.5 * sy);
    const coverMat = std(0x8d97a8, 0.85, 0.33, { clearcoat: 0.5, clearcoatRoughness: 0.4 });
    const lid = add(top, new THREE.Mesh(new THREE.BoxGeometry(W + 0.1, 0.35, D + 0.1), coverMat));
    lid.position.y = 0.175;
    const ribs = Math.max(3, Math.round(W / 3));
    for (let i = 0; i < ribs; i++) {
      const r = add(top, new THREE.Mesh(new THREE.BoxGeometry(0.25, 0.12, D * 0.86), coverMat));
      r.position.set(-W / 2 + (i + 0.5) * (W / ribs), 0.41, 0);
    }
    const label = new THREE.Mesh(new THREE.PlaneGeometry(Math.min(W, D * 2) * 0.55, Math.min(W, D * 2) * 0.14),
      new THREE.MeshBasicMaterial({ map: textTexture("EV BATTERY PACK"), transparent: true, depthWrite: false }));
    label.rotation.x = -Math.PI / 2;
    label.rotation.z = D > W ? Math.PI / 2 : 0;
    label.position.y = 0.48;
    add(top, label).castShadow = false;
    label.userData.decal = true;

    for (const l of this.layers.values()) for (const m of l.meshes) {
      const mat = m.material as THREE.MeshStandardMaterial;
      m.material = mat.clone();
      (m.material as any).userData = { baseOpacity: 1 };
    }
    this.buildCellDetail();
    this.buildLabels();
    this.applyLook();
  }

  private buildCellDetail() {
    this.cellGroup.clear();
    const g = this.cellGroup;
    const cyl = this.cellShape === "cylindrical";
    const parts: { id: string; mesh: THREE.Mesh }[] = [];
    const mat = (c: number, m = 0.2, r = 0.5, extra: any = {}) => new THREE.MeshPhysicalMaterial({ color: c, metalness: m, roughness: r, side: THREE.DoubleSide, ...extra });
    if (cyl) {
      const H = 5, cut = Math.PI * 1.45;
      const shell = (r: number, h: number, m: THREE.Material, id: string) => {
        const mesh = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, 64, 1, true, Math.PI * 0.3, cut), m);
        mesh.userData.cellPart = id; g.add(mesh); parts.push({ id, mesh }); return mesh;
      };
      shell(1.0, H, mat(0x9aa4b4, 0.95, 0.25), "can");
      shell(0.93, H * 0.92, mat(0x2b3a66, 0.3, 0.55), "cathode");
      shell(0.86, H * 0.92, mat(0xf2f4f7, 0, 0.7), "separator");
      shell(0.80, H * 0.92, mat(0x1a1d22, 0.2, 0.6), "anode");
      shell(0.72, H * 0.92, mat(0xd08045, 0.9, 0.3), "anode");
      const core = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, H * 0.95, 16), mat(0x707a88, 0.8, 0.3));
      g.add(core);
      const capTop = new THREE.Mesh(new THREE.CylinderGeometry(0.98, 0.98, 0.18, 48), mat(0xc0c8d4, 0.95, 0.25));
      capTop.position.y = H / 2; capTop.userData.cellPart = "vent"; g.add(capTop); parts.push({ id: "vent", mesh: capTop });
      const nub = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, 0.22, 32), mat(0xe1e6ee, 1, 0.2));
      nub.position.y = H / 2 + 0.18; nub.userData.cellPart = "terminal_pos"; g.add(nub); parts.push({ id: "terminal_pos", mesh: nub });
      const capBot = new THREE.Mesh(new THREE.CylinderGeometry(0.98, 0.98, 0.14, 48), mat(0x8c96a6, 0.95, 0.3));
      capBot.position.y = -H / 2; capBot.userData.cellPart = "terminal_neg"; g.add(capBot); parts.push({ id: "terminal_neg", mesh: capBot });
      const sleeve = new THREE.Mesh(new THREE.CylinderGeometry(1.02, 1.02, H * 0.98, 64, 1, true, Math.PI * 0.3, cut),
        new THREE.MeshPhysicalMaterial({ color: 0x4fc3e0, transparent: true, opacity: 0.18, roughness: 0.1, transmission: 0.2, side: THREE.DoubleSide }));
      g.add(sleeve);
      g.userData.anchors = { terminal_pos: [0, H / 2 + 0.3, 0], vent: [0.8, H / 2, 0], cathode: [0.93, 1.2, 0.2], separator: [0.86, 0.3, 0.3],
        anode: [0.8, -0.6, 0.3], can: [1.0, -1.6, 0], terminal_neg: [0, -H / 2 - 0.1, 0] };
    } else {
      // stacked sheets (pouch / prismatic), front quarter cut away
      const W = 3.6, H = 4.2, T = this.cellShape === "pouch" ? 0.9 : 1.6;
      const sheets = 9;
      for (let i = 0; i < sheets; i++) {
        const id = i % 3 === 0 ? "cathode" : i % 3 === 1 ? "separator" : "anode";
        const c = id === "cathode" ? 0x2b3a66 : id === "separator" ? 0xf2f4f7 : 0x1a1d22;
        const m = new THREE.Mesh(new THREE.BoxGeometry(W * (1 - i * 0.02), H * 0.9, T / sheets * 0.8), mat(c, 0.2, 0.55));
        m.position.set(-i * 0.08, 0, -T / 2 + (i + 0.5) * (T / sheets));
        m.userData.cellPart = id; g.add(m); parts.push({ id, mesh: m });
      }
      const caseMat = new THREE.MeshPhysicalMaterial({ color: this.cellShape === "pouch" ? 0xb9c0cc : 0x9aa4b4, metalness: 0.8, roughness: 0.3, transparent: true, opacity: 0.22, side: THREE.DoubleSide });
      const shell = new THREE.Mesh(new THREE.BoxGeometry(W + 0.2, H + 0.2, T + 0.2), caseMat);
      shell.userData.cellPart = "can"; g.add(shell); parts.push({ id: "can", mesh: shell });
      for (const [x, id] of [[-W / 3, "terminal_pos"], [W / 3, "terminal_neg"]] as const) {
        const tab = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.5, 0.3), mat(id === "terminal_pos" ? 0xc0c8d4 : 0xd08045, 0.95, 0.25));
        tab.position.set(x, H / 2 + 0.35, 0); tab.userData.cellPart = id; g.add(tab); parts.push({ id, mesh: tab });
      }
      const vent = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 0.1, 24), mat(0x707a88, 0.9, 0.3));
      vent.position.set(0, H / 2 + 0.12, 0); vent.userData.cellPart = "vent"; g.add(vent); parts.push({ id: "vent", mesh: vent });
      g.userData.anchors = { terminal_pos: [-W / 3, H / 2 + 0.6, 0], vent: [0, H / 2 + 0.2, 0], cathode: [W / 2, 1.0, -T / 2], separator: [W / 2, 0.2, 0],
        anode: [W / 2, -0.6, T / 3], can: [W / 2 + 0.1, -1.5, T / 2], terminal_neg: [W / 3, H / 2 + 0.6, 0] };
    }
    g.position.set(0, 3.0, 0);
    g.userData.parts = parts;
  }

  private buildLabels() {
    this.clearLabels();
    const mkEl = (title: string, sub: string, onClick: () => void, cls = "") => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = `pointer-events-auto absolute left-0 top-0 whitespace-nowrap rounded-md border border-data/50 bg-ink-950/85 px-2.5 py-1 text-left text-[11px] leading-tight text-fog-100 shadow-lg backdrop-blur transition-opacity duration-300 hover:border-volt ${cls}`;
      el.innerHTML = `<span class="block font-semibold">${title}</span><span class="block text-[10px] text-fog-400">${sub}</span>`;
      el.addEventListener("click", (e) => { e.stopPropagation(); onClick(); });
      this.labelRoot.appendChild(el);
      return el;
    };
    for (const L of LAYERS) {
      const l = this.layers.get(L.id)!;
      const el = mkEl(L.label, L.sub, () => this.select(L.id));
      this.labels.push({ el, show: () => (this.view === "exploded" || this.view === "minerals") && !this.opts.compact,
        anchor: () => new THREE.Vector3(this.packSize.x / 2 + 0.2, l.outer.position.y + l.height / 2, -this.packSize.z / 2 + 0.2) });
    }
    const anchors = this.cellGroup.userData.anchors as Record<string, number[]>;
    for (const C of CELL_LAYERS) {
      const a = anchors[C.id];
      const el = mkEl(C.label, C.sub, () => this.onCellPart(C.id), "border-volt/50");
      this.labels.push({ el, show: () => this.view === "cell", anchor: () => new THREE.Vector3(a[0], a[1], a[2]).add(this.cellGroup.position) });
    }
  }

  private clearLabels() { for (const l of this.labels) l.el.remove(); this.labels = []; }

  // ------------------------------------------------------------------ state
  setView(v: View) {
    this.view = v;
    this.explodeTarget = v === "exploded" || v === "minerals" ? 1 : v === "module" ? 0.55 : v === "power" ? 0.35 : 0;
    this.selected = v === "module" ? "modules" : this.selected && (v === "exploded" || v === "minerals") ? this.selected : null;
    this.pack.visible = v !== "cell";
    this.cellGroup.visible = v === "cell";
    const H = this.packSize.y;
    const goals: Record<View, [number[], number[]]> = {
      overview: [[11, 8.5, 12], [0, H / 2, 0]],
      exploded: [[17, 12.5, 17], [0, 3.1, 0]],
      minerals: [[17, 12.5, 17], [0, 3.1, 0]],
      module: [[this.moduleFocus.x + 5, 6.5, this.moduleFocus.z + 6], [this.moduleFocus.x, this.moduleFocus.y + 1, this.moduleFocus.z]],
      cell: [[8.5, 6.5, 10.5], [0, 3, 0]],
      power: [[10, 11, 11], [0, 1.2, 0]],
      thermal: [[0.01, 16, 9], [0, 0.6, 0]],
      twin: [[11, 9, 12], [0, H / 2, 0]],
    };
    const [p, t] = goals[v];
    this.camGoal = { pos: new THREE.Vector3(...(p as [number, number, number])), target: new THREE.Vector3(...(t as [number, number, number])) };
    this.applyLook();
  }

  setTwin(t: Twin) { this.twin = { ...this.twin, ...t }; this.paintCells(); }

  select(id: LayerId | null) {
    this.selected = id;
    this.applyLook();
    this.onSelect(id);
  }

  private paintCells() {
    const inst = this.cells;
    if (!inst) return;
    const col = new THREE.Color();
    const base = new THREE.Color(0x5a5fe0);
    const soh = this.twin.soh ?? null;
    const temp = this.twin.tempC ?? 30;
    const imb = Math.min(1, (this.twin.imbalanceMv ?? 20) / 120);
    for (let i = 0; i < inst.count; i++) {
      const c = this.cellCenters[i], seed = this.cellSeeds[i];
      if (this.view === "thermal") {
        // centre of the pack runs hotter; scale by measured temperature
        const r = Math.min(1, Math.hypot(c.x, c.z));
        const t = Math.min(1, Math.max(0, ((temp - 20) / 30) * (1.15 - 0.55 * r) + (seed - 0.5) * 0.12));
        col.setHSL(0.62 - 0.62 * t, 0.85, 0.5);
      } else if (this.view === "twin" && soh != null) {
        const h = Math.min(1, Math.max(0, (soh - 40) / 55 - (seed - 0.5) * imb * 0.6));
        col.setHSL(0.02 + 0.22 * h, 0.85, 0.52);
      } else {
        col.copy(base).offsetHSL((seed - 0.5) * 0.03, 0, (seed - 0.5) * 0.08);
      }
      inst.setColorAt(i, col);
    }
    if (inst.instanceColor) inst.instanceColor.needsUpdate = true;
  }

  private applyLook() {
    const xray = this.view === "power" || this.view === "thermal" || this.view === "twin";
    for (const l of this.layers.values()) {
      let op = 1;
      if (this.selected && this.selected !== l.id && (this.view === "exploded" || this.view === "minerals" || this.view === "module")) op = 0.14;
      if (xray && (l.id === "top_cover" || (l.id === "cooling" && this.view !== "thermal"))) op = this.view === "thermal" && l.id === "cooling" ? 1 : 0.07;
      if (this.view === "thermal" && l.id === "top_cover") op = 0;
      for (const m of l.meshes) {
        const mat = m.material as THREE.MeshPhysicalMaterial;
        let o = op;
        // thermal view: see-through cooling plate, opaque coolant tubes, cells visible underneath
        if (this.view === "thermal" && l.id === "cooling") o = mat.map ? 1 : 0.18;
        // health / thermal views: copper busbars go see-through so the coloured cells show
        if ((this.view === "twin" || this.view === "thermal") && l.id === "busbars" && !m.userData.cable) o = 0.22;
        mat.transparent = o < 1 || !!m.userData.decal;
        mat.opacity = o;
        m.visible = o > 0.01;
        if (m.userData.decal) { mat.depthWrite = false; continue; }
        mat.depthWrite = o > 0.5;
        if ("emissive" in mat && !(mat as any).map) {
          const hl = this.hovered === l.id || this.selected === l.id;
          mat.emissive.setHex(this.twin.alarm && l.id === "modules" ? 0x601010 : hl ? 0x1c3d10 : 0x000000);
        }
      }
    }
    this.paintCells();
    for (const p of this.pulses) p.mesh.visible = this.view === "power" || this.view === "twin";
  }

  // ------------------------------------------------------------------ interaction
  private pick(ev: PointerEvent | MouseEvent): { layer?: LayerId; cellPart?: string } {
    const r = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    if (this.view === "cell") {
      const hit = this.raycaster.intersectObjects(this.cellGroup.children, false).find((h) => h.object.userData.cellPart);
      return { cellPart: hit?.object.userData.cellPart };
    }
    const objs: THREE.Object3D[] = [];
    for (const l of this.layers.values()) for (const m of l.meshes) if (m.visible && ((m.material as THREE.Material).opacity ?? 1) > 0.2) objs.push(m);
    const hit = this.raycaster.intersectObjects(objs, false)[0];
    return { layer: hit?.object.userData.layer };
  }

  private lastPick = 0;
  private onMove = (ev: PointerEvent) => {
    const now = performance.now();
    if (now - this.lastPick < 70) return;
    this.lastPick = now;
    const { layer } = this.pick(ev);
    const h = layer ?? null;
    this.renderer.domElement.style.cursor = h || this.view === "cell" ? "pointer" : "grab";
    if (h !== this.hovered) { this.hovered = h; this.applyLook(); }
  };

  private onClick = (ev: MouseEvent) => {
    this.lastInteract = performance.now();
    const { layer, cellPart } = this.pick(ev);
    if (this.view === "cell") { if (cellPart) this.onCellPart(cellPart); return; }
    if (this.view === "overview" && layer) { this.setView("exploded"); this.select(layer); return; }
    this.select(layer ?? null);
  };

  // ------------------------------------------------------------------ loop
  private resize() {
    const w = this.host.clientWidth || 600, h = this.host.clientHeight || 400;
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "100%";
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  private loop = () => {
    if (this.disposed) return;
    this.raf = requestAnimationFrame(this.loop);
    const dt = Math.min(0.05, this.clock.getDelta());
    const tNow = performance.now();
    // smooth explode
    this.explode += (this.explodeTarget - this.explode) * Math.min(1, dt * 4);
    const e = ease(Math.min(1, Math.max(0, this.explode)));
    const gap = 1.25;
    ORDER.forEach((id, i) => {
      const l = this.layers.get(id);
      if (!l) return;
      l.outer.position.y = l.baseY + e * gap * i;
    });
    // camera glide
    if (this.camGoal) {
      const k = Math.min(1, dt * 2.6);
      this.camera.position.lerp(this.camGoal.pos, k);
      this.controls.target.lerp(this.camGoal.target, k);
      if (this.camera.position.distanceTo(this.camGoal.pos) < 0.05) this.camGoal = null;
    }
    this.controls.autoRotate = !!this.opts.autoRotate && tNow - this.lastInteract > 4000 && !this.camGoal;
    this.controls.update();
    // current pulses (direction and speed follow the measured current)
    const cur = this.twin.currentA ?? 1;
    const dir = cur >= 0 ? 1 : -1;
    const speed = 0.04 + Math.min(0.25, Math.abs(cur) * 0.05);
    for (const p of this.pulses) {
      if (!p.mesh.visible) continue;
      p.t = (p.t + dir * speed * dt + 1) % 1;
      p.mesh.position.copy(p.path.getPointAt(p.t));
      (p.mesh.material as THREE.MeshBasicMaterial).color.setHex(cur >= 0 ? 0xffa53a : 0x4fa8ff);
    }
    for (const t of this.coolant) t.offset.x -= dt * (this.view === "thermal" ? 0.9 : 0.25);
    if (this.view === "cell") this.cellGroup.rotation.y += dt * 0.15;
    if (this.twin.alarm && this.cells) {
      const m = this.cells.material as THREE.MeshPhysicalMaterial;
      m.emissive.setRGB(0.35 + 0.25 * Math.sin(tNow / 180), 0.02, 0.02);
    }
    this.renderer.render(this.scene, this.camera);
    this.placeLabels();
  };

  private placeLabels() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    for (const l of this.labels) {
      const show = l.show();
      if (!show) { l.el.style.opacity = "0"; l.el.style.pointerEvents = "none"; continue; }
      const p = l.anchor().project(this.camera);
      const x = (p.x * 0.5 + 0.5) * w, y = (-p.y * 0.5 + 0.5) * h;
      const vis = p.z < 1 && x > -40 && x < w + 40 && y > -20 && y < h + 20;
      l.el.style.opacity = vis ? "1" : "0";
      l.el.style.pointerEvents = vis ? "auto" : "none";
      l.el.style.transform = `translate(${Math.min(w - l.el.offsetWidth - 4, Math.max(4, x + 8))}px, ${y - 14}px)`;
    }
  }

  private disposeObj(o: THREE.Object3D) {
    o.traverse((c) => {
      const m = c as THREE.Mesh;
      if (m.geometry) m.geometry.dispose();
      const mats = Array.isArray(m.material) ? m.material : m.material ? [m.material] : [];
      for (const x of mats) { (x as any).map?.dispose?.(); x.dispose(); }
    });
  }

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    this.clearLabels();
    this.disposeObj(this.scene);
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
