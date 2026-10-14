import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, Atom, Box, Cpu, Hand, Home, Layers, Thermometer, Zap } from "lucide-react";
import { api, fmt, type EvModel } from "../lib/api";
import { CELL_LAYERS, LAYERS, PackViewer, type LayerId, type Twin, type View } from "../three/PackViewer";

type Tab = "overview" | "exploded" | "components" | "working" | "monitoring" | "future";
const TABS: { id: Tab; label: string; icon: any }[] = [
  { id: "overview", label: "Overview", icon: Home },
  { id: "exploded", label: "Exploded view", icon: Layers },
  { id: "components", label: "Components", icon: Box },
  { id: "working", label: "Working", icon: Zap },
  { id: "monitoring", label: "Monitoring", icon: Activity },
  { id: "future", label: "Future", icon: Atom },
];

const CELL_INFO: Record<string, { text: string; minerals: string[] }> = {
  terminal_pos: { text: "Positive terminal on the top cap. Connected to the cathode through an aluminium tab.", minerals: ["Al"] },
  vent: { text: "Safety vent: a thin scored disc that bursts to release gas if pressure builds up (over-charge, overheating). The MQ gas sensor watches for this.", minerals: [] },
  cathode: { text: "Cathode: the lithium metal oxide (NMC / NCA) or lithium iron phosphate (LFP) coated on aluminium foil. Holds most of the valuable minerals.", minerals: ["Li", "Ni", "Co", "Mn", "Fe", "P", "Al"] },
  separator: { text: "Separator: a porous polymer film that keeps cathode and anode apart while letting lithium ions pass. Shrinks and fails if overheated.", minerals: [] },
  anode: { text: "Anode: graphite coated on copper foil. Lithium is stored here when the battery is charged; lithium trapped in its surface layer is the main cause of capacity fade.", minerals: ["C", "Cu"] },
  can: { text: "Can / casing: nickel-plated steel for cylindrical cells, aluminium for prismatic, laminated aluminium film for pouch cells.", minerals: ["Fe", "Al"] },
  terminal_neg: { text: "Negative terminal at the bottom, connected to the anode by a nickel/copper tab.", minerals: ["Cu"] },
};

function viewFor(tab: Tab, sub: string): View {
  switch (tab) {
    case "overview": return "overview";
    case "exploded": return "exploded";
    case "components": return sub === "cell" ? "cell" : "module";
    case "working": return "power";
    case "monitoring": return sub === "thermal" ? "thermal" : "twin";
    case "future": return "minerals";
  }
}

const kg = (g: number) => (g >= 1000 ? `${fmt.n(g / 1000, g >= 100000 ? 0 : 1)} kg` : `${fmt.n(g, g < 10 ? 2 : 1)} g`);

export default function BatteryTwin3D({ modelId, twin, compact = false, height = 560, initialTab = "overview", onModelChange, live }: {
  modelId: string; twin?: Twin; compact?: boolean; height?: number; initialTab?: Tab; onModelChange?: (id: string) => void;
  live?: { voltage?: number | null; current?: number | null; temperature?: number | null; gas?: number | null; soh?: number | null; rul?: number | null; label?: string };
}) {
  const host = useRef<HTMLDivElement>(null);
  const labels = useRef<HTMLDivElement>(null);
  const viewer = useRef<PackViewer | null>(null);
  const [model, setModel] = useState<EvModel | null>(null);
  const [list, setList] = useState<{ id: string; name: string }[]>([]);
  const [tab, setTab] = useState<Tab>(initialTab);
  const [sub, setSub] = useState("module");
  const [sel, setSel] = useState<LayerId | null>(null);
  const [cellPart, setCellPart] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [hint, setHint] = useState(true);

  useEffect(() => { if (!compact) api.evModels().then(setList).catch(() => {}); }, [compact]);
  useEffect(() => { api.evModel(modelId).then(setModel).catch((e) => setErr(e.message)); }, [modelId]);

  useEffect(() => {
    if (!host.current || !labels.current) return;
    let v: PackViewer;
    try {
      v = new PackViewer(host.current, labels.current, { autoRotate: true, compact });
    } catch {
      setErr("3D needs WebGL. Enable hardware acceleration in your browser settings.");
      return;
    }
    v.onSelect = (id) => { setSel(id); setCellPart(null); };
    v.onCellPart = (id) => setCellPart(id);
    viewer.current = v;
    return () => { v.dispose(); viewer.current = null; };
  }, [compact]);

  useEffect(() => {
    if (!model || !viewer.current) return;
    viewer.current.load({ id: model.id, cell_shape: model.cell_shape, visual: model.visual });
    viewer.current.setView(viewFor(tab, sub));
    if (twin) viewer.current.setTwin(twin);
  }, [model]);

  useEffect(() => { viewer.current?.setView(viewFor(tab, sub)); if (tab !== "exploded" && tab !== "future") setSel(tab === "components" && sub === "module" ? "modules" : null); setCellPart(null); }, [tab, sub]);
  useEffect(() => { if (twin) viewer.current?.setTwin(twin); }, [twin?.soh, twin?.tempC, twin?.currentA, twin?.alarm, twin?.imbalanceMv]);

  const part = model?.parts.find((p) => p.id === sel) ?? null;
  const mins = model?.minerals;
  const maxMetal = useMemo(() => Math.max(1, ...Object.values(model?.pack_metal_totals_g ?? { a: 1 })), [model]);
  const color = (sym: string) => mins?.materials.find((m) => m.symbol === sym)?.color ?? "#8A9AB5";
  const name = (sym: string) => mins?.materials.find((m) => m.symbol === sym)?.name ?? sym;

  const panel = () => {
    if (!model || !mins) return <p className="text-sm text-fog-400">Loading pack…</p>;
    if (tab === "components" && sub === "cell") {
      const info = cellPart ? CELL_INFO[cellPart] : null;
      return (
        <>
          <h3 className="font-display text-lg font-semibold">Inside one cell</h3>
          <p className="mt-1 text-xs text-fog-400">{mins.cell_format_label} · {mins.chemistry_label}. Tap a layer of the cut-away cell.</p>
          {info ? (
            <div className="mt-3">
              <div className="font-semibold text-volt">{CELL_LAYERS.find((c) => c.id === cellPart)?.label}</div>
              <p className="mt-1 text-sm text-fog-300">{info.text}</p>
              <ul className="mt-3 space-y-2">{mins.materials.filter((m) => info.minerals.includes(m.symbol)).map((m) => (
                <li key={m.symbol} className="text-xs"><div className="flex justify-between"><span><span className="font-semibold" style={{ color: m.color }}>{m.symbol}</span> {m.name}</span><span className="num">{kg(m.contained_g / mins.n_cells)} / cell</span></div>
                  <div className="mt-1 h-1.5 rounded-full bg-ink-700"><div className="bar-grow h-full rounded-full" style={{ width: `${Math.min(100, m.share_pct * 3)}%`, background: m.color }} /></div></li>
              ))}</ul>
            </div>
          ) : <ul className="mt-3 space-y-1.5 text-sm">{CELL_LAYERS.map((c) => <li key={c.id}><button className="text-left hover:text-volt" onClick={() => setCellPart(c.id)}>{c.label} <span className="text-xs text-fog-500">· {c.sub}</span></button></li>)}</ul>}
        </>
      );
    }
    if (tab === "future" && !part) {
      return (
        <>
          <h3 className="font-display text-lg font-semibold">Mineral levels in this pack</h3>
          <p className="mt-1 text-xs text-fog-400">{kg(model.pack_mass_g)} pack · cells + housing, cooling and wiring. Tap a layer to see what it is made of.</p>
          <ul className="mt-3 space-y-2">{Object.entries(model.pack_metal_totals_g).map(([s, g]) => (
            <li key={s} className="text-xs"><div className="flex justify-between"><span><span className="font-semibold" style={{ color: color(s) }}>{s}</span> {name(s)}{mins.materials.find((m) => m.symbol === s)?.critical ? <span className="ml-1 text-amber">· critical</span> : null}</span><span className="num">{kg(g)}</span></div>
              <div className="mt-1 h-1.5 rounded-full bg-ink-700"><div className="bar-grow h-full rounded-full" style={{ width: `${(g / maxMetal) * 100}%`, background: color(s) }} /></div></li>
          ))}</ul>
          <p className="mt-3 text-xs text-volt">{mins.closed_loop.statement}</p>
          <p className="mt-2 text-2xs text-fog-500">{model.note}</p>
        </>
      );
    }
    if (tab === "working") {
      return (
        <>
          <h3 className="font-display text-lg font-semibold">Connection & power flow</h3>
          <p className="mt-2 text-sm text-fog-300">{model.config}. Cells are joined in parallel inside a module for capacity and the modules in series for voltage{model.nominal_v ? ` (≈ ${model.nominal_v} V nominal)` : ""}. Busbars carry the current to the high-voltage connector.</p>
          <ul className="mt-3 space-y-1 text-xs"><li><span className="mr-2 inline-block h-2.5 w-2.5 rounded-full bg-[#ffa53a]" />Discharge (to motor / lamp)</li><li><span className="mr-2 inline-block h-2.5 w-2.5 rounded-full bg-[#4fa8ff]" />Charge (from solar / grid)</li></ul>
          <p className="mt-3 text-xs text-fog-400">Pulse speed follows the measured current{live?.current != null ? ` (${fmt.n(live.current, 2)} A now)` : ""}.</p>
        </>
      );
    }
    if (tab === "monitoring") {
      const rows: [string, string][] = [["Voltage", live?.voltage != null ? `${fmt.n(live.voltage, 2)} V` : "—"], ["Current", live?.current != null ? `${fmt.n(live.current, 2)} A` : "—"],
        ["Temperature", live?.temperature != null ? `${fmt.n(live.temperature, 1)} °C` : "—"], ["Gas sensor", live?.gas != null ? `${fmt.n(live.gas, 2)} V` : "—"],
        ["SOH", live?.soh != null ? `${fmt.n(live.soh, 1)} %` : "—"], ["RUL", live?.rul != null ? `${fmt.int(live.rul)} cycles` : "—"]];
      return (
        <>
          <h3 className="font-display text-lg font-semibold">Digital twin · live data</h3>
          <p className="mt-1 text-xs text-fog-400">{live?.label ?? "Cells coloured by the AI's health estimate (green healthy → red weak); thermal view shows the heat map and coolant flow."}</p>
          <dl className="mt-3 grid grid-cols-2 gap-2">{rows.map(([k, v]) => <div key={k} className="rounded-md border border-ink-700 px-2.5 py-1.5"><dt className="text-2xs text-fog-500">{k}</dt><dd className="num font-display text-lg font-semibold">{v}</dd></div>)}</dl>
          {twin?.alarm && <p className="mt-3 rounded-md border border-alarm/60 bg-alarm/10 p-2 text-xs text-alarm">Safety alarm — the twin pulses red.</p>}
        </>
      );
    }
    if (part) {
      const isCells = part.id === "modules";
      return (
        <>
          <div className="text-2xs uppercase tracking-wide text-data">{model.name}</div>
          <h3 className="font-display text-lg font-semibold">{part.name}</h3>
          <p className="mt-1 text-sm text-fog-300">{part.role}</p>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
            <div><dt className="text-2xs text-fog-500">Mass (est.)</dt><dd className="num">{kg(part.mass_g)}</dd></div>
            <div><dt className="text-2xs text-fog-500">Made of</dt><dd>{part.material_name}</dd></div>
          </dl>
          {isCells ? (
            <ul className="mt-3 space-y-2">{mins.materials.map((m) => (
              <li key={m.symbol} className="text-xs"><div className="flex justify-between"><span><span className="font-semibold" style={{ color: m.color }}>{m.symbol}</span> {m.name} <span className="text-fog-500">· {m.part}</span></span><span className="num">{kg(m.contained_g)}</span></div>
                <div className="mt-1 h-1.5 rounded-full bg-ink-700"><div className="bar-grow h-full rounded-full" style={{ width: `${Math.min(100, m.share_pct * 5)}%`, background: m.color }} /></div></li>
            ))}</ul>
          ) : part.material === "E-waste" ? (
            <p className="mt-3 text-xs text-fog-400">Goes to the e-waste stream: copper, tin solder and trace precious metals are recovered by e-waste recyclers.</p>
          ) : (
            <div className="mt-3 text-xs"><div className="flex justify-between"><span><span className="font-semibold" style={{ color: color(part.material) }}>{part.material}</span> {name(part.material)}</span><span className="num">{kg(part.mass_g)}</span></div>
              <p className="mt-1 text-fog-400">Recovered as scrap metal and remelted.</p></div>
          )}
          <button className="mt-4 text-xs text-data hover:underline" onClick={() => viewer.current?.select(null)}>Clear selection</button>
        </>
      );
    }
    return (
      <>
        <div className="text-2xs uppercase tracking-wide text-data">{model.vehicle}</div>
        <h3 className="font-display text-lg font-semibold">{model.name}</h3>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
          <div><dt className="text-2xs text-fog-500">Energy</dt><dd className="num">{model.pack_kwh >= 1 ? `${model.pack_kwh} kWh` : `${fmt.n(model.pack_kwh * 1000, 1)} Wh`}</dd></div>
          <div><dt className="text-2xs text-fog-500">Chemistry</dt><dd>{model.chemistry}</dd></div>
          <div><dt className="text-2xs text-fog-500">Cells</dt><dd className="num">{model.cells ? fmt.int(model.cells) : "not published"}</dd></div>
          <div><dt className="text-2xs text-fog-500">Format</dt><dd className="capitalize">{model.cell_shape}</dd></div>
          <div className="col-span-2"><dt className="text-2xs text-fog-500">Layout</dt><dd>{model.config}</dd></div>
          <div className="col-span-2"><dt className="text-2xs text-fog-500">Pack mass (est.)</dt><dd className="num">{kg(model.pack_mass_g)} · {model.mass_note}</dd></div>
        </dl>
        <p className="mt-3 text-2xs text-fog-500">Source: {model.source}</p>
        <p className="mt-3 text-xs text-fog-400">Tap the pack to explode it into layers, then tap a layer.</p>
      </>
    );
  };

  return (
    <div className="panel overflow-hidden">
      {!compact && (
        <div className="flex flex-wrap items-center gap-3 border-b border-ink-700 px-4 py-3">
          <Cpu className="h-4 w-4 text-data" />
          <span className="font-display font-semibold">Battery digital twin</span>
          {onModelChange ? (
            <select aria-label="EV battery model" className="input ml-auto w-auto py-1.5" value={modelId} onChange={(e) => onModelChange(e.target.value)}>
              {list.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          ) : <span className="ml-auto text-xs text-fog-400">{model?.name}</span>}
          {tab === "components" && (
            <div className="flex overflow-hidden rounded-md border border-ink-600 text-xs">
              {["module", "cell"].map((x) => <button key={x} className={`px-3 py-1.5 ${sub === x ? "bg-volt text-ink-950" : "text-fog-300"}`} onClick={() => setSub(x)}>{x === "module" ? "Module" : "Single cell"}</button>)}
            </div>
          )}
          {tab === "monitoring" && (
            <div className="flex overflow-hidden rounded-md border border-ink-600 text-xs">
              {[["twin", "Health"], ["thermal", "Thermal"]].map(([x, l]) => <button key={x} className={`flex items-center gap-1 px-3 py-1.5 ${sub === x || (x === "twin" && sub !== "thermal") ? "bg-volt text-ink-950" : "text-fog-300"}`} onClick={() => setSub(x)}>{x === "thermal" && <Thermometer className="h-3 w-3" />}{l}</button>)}
            </div>
          )}
        </div>
      )}
      <div className={`grid ${compact ? "" : "lg:grid-cols-[1fr_320px]"}`}>
        <div className="relative bg-[radial-gradient(ellipse_at_center,#16233B_0%,#0A1220_75%)]" style={{ height }} onPointerDown={() => setHint(false)}>
          <div ref={host} className="absolute inset-0" />
          <div ref={labels} className="pointer-events-none absolute inset-0 overflow-hidden" />
          {err && <div className="absolute inset-0 flex items-center justify-center p-6 text-sm text-amber">{err}</div>}
          {hint && tab === "overview" && !compact && (
            <div className="pointer-events-none absolute bottom-24 right-6 flex items-center gap-2 rounded-full border border-data/60 bg-ink-950/80 px-4 py-2 text-sm text-fog-100">
              <Hand className="h-4 w-4 text-data" />Tap to explore · drag to rotate
            </div>
          )}
          <nav className={`absolute inset-x-0 bottom-0 flex justify-center gap-1.5 p-3 ${compact ? "gap-1 p-2" : ""}`} aria-label="Battery views">
            {TABS.map(({ id, label, icon: I }) => (
              <button key={id} onClick={() => { setTab(id); if (id === "components") setSub("module"); if (id === "monitoring") setSub("twin"); }}
                className={`flex flex-col items-center gap-1 rounded-md border px-2.5 py-1.5 text-[10px] backdrop-blur transition-colors sm:px-3 sm:text-2xs ${tab === id ? "border-volt bg-volt/15 text-volt" : "border-ink-600 bg-ink-950/70 text-fog-300 hover:text-fog-100"}`}>
                <I className={compact ? "h-3.5 w-3.5" : "h-4 w-4"} />{label}
              </button>
            ))}
          </nav>
        </div>
        {!compact && <aside className="overflow-y-auto border-t border-ink-700 p-5 lg:border-l lg:border-t-0" style={{ maxHeight: height }}>{panel()}</aside>}
      </div>
    </div>
  );
}

export { LAYERS };
