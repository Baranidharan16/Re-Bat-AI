import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, Cpu, FileUp, Keyboard, Layers } from "lucide-react";
import { api } from "../lib/api";
import { useAnalysis } from "../lib/store";
import { ErrorBox, PageHead } from "../components/ui";

type Tab = "demo" | "csv" | "manual" | "live";
const TABS: { id: Tab; label: string; icon: any }[] = [
  { id: "demo", label: "Demo battery", icon: Layers },
  { id: "csv", label: "CSV upload", icon: FileUp },
  { id: "manual", label: "Manual input", icon: Keyboard },
  { id: "live", label: "Live hardware", icon: Activity },
];

export default function Analyze() {
  const [tab, setTab] = useState<Tab>("demo");
  return (
    <>
      <PageHead title="Analyze a battery" sub="Pick an input. Every number on the following pages is computed by the backend pipeline from that input." />
      <div role="tablist" className="mb-6 flex flex-wrap gap-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
            className={`btn ${tab === id ? "bg-ink-700 text-fog-100" : "border border-ink-700 text-fog-400 hover:text-fog-100"}`}>
            <Icon className="h-4 w-4" /> {label}
          </button>
        ))}
      </div>
      {tab === "demo" && <DemoPicker />}
      {tab === "csv" && <CsvUpload />}
      {tab === "manual" && <Manual />}
      {tab === "live" && <LiveStart />}
    </>
  );
}

function DemoPicker() {
  const [list, setList] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const { loadDemo, source, loading } = useAnalysis();
  const nav = useNavigate();
  useEffect(() => { api.demoList().then(setList).catch((e) => setErr(e.message)); }, []);
  if (err) return <ErrorBox message={err} />;
  return (
    <div>
      <p className="mb-4 text-sm text-fog-400">Five simulated modules. Only their hidden physics differs — the AI sees nothing but their test data.</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {list.map((b) => {
          const active = source?.kind === "demo" && source.id === b.battery_id;
          return (
            <button key={b.battery_id} disabled={loading}
              onClick={async () => { await loadDemo(b.battery_id); nav("/app"); }}
              className={`panel panel-pad text-left transition-colors hover:border-fog-400 ${active ? "border-volt" : ""}`}>
              <div className="text-xs text-fog-400">{b.battery_id}</div>
              <div className="mt-1 font-display text-lg font-semibold">{b.label}</div>
              <div className="text-sm text-volt">{b.title}</div>
              <p className="mt-2 text-xs leading-relaxed text-fog-400">{b.story}</p>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function CsvUpload() {
  const { setAnalysis } = useAnalysis();
  const nav = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [meta, setMeta] = useState({ battery_id: "CSV-001", series_cells: 3, nominal_capacity_ah: 2.5 });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true); setErr(null);
    try {
      const a = await api.csv(file, meta);
      setAnalysis(a, { kind: "csv", id: meta.battery_id });
      nav("/app");
    } catch (e: any) { setErr(e); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
      <div className="panel panel-pad">
        <label className="flex cursor-pointer flex-col items-center justify-center rounded-md border border-dashed border-ink-600 px-6 py-12 text-center hover:border-data">
          <FileUp className="h-6 w-6 text-data" />
          <span className="mt-3 text-sm">{file ? file.name : "Choose a CSV time-series file"}</span>
          <span className="mt-1 text-xs text-fog-500">Required columns: timestamp, voltage, current · optional: temperature, capacity, cycle, internal_resistance, cell_v_min, cell_v_max</span>
          <input type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <div><label className="label" htmlFor="bid">Battery ID</label><input id="bid" className="input" value={meta.battery_id} onChange={(e) => setMeta({ ...meta, battery_id: e.target.value })} /></div>
          <div><label className="label" htmlFor="cells">Cells in series</label><input id="cells" type="number" min={1} className="input" value={meta.series_cells} onChange={(e) => setMeta({ ...meta, series_cells: +e.target.value })} /></div>
          <div><label className="label" htmlFor="ah">Nominal capacity (Ah)</label><input id="ah" type="number" step="0.1" className="input" value={meta.nominal_capacity_ah} onChange={(e) => setMeta({ ...meta, nominal_capacity_ah: +e.target.value })} /></div>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button className="btn-primary" disabled={!file || busy}>{busy ? "Analysing…" : "Analyze file"}</button>
          <a className="text-sm text-data hover:underline" href="/api/v1/samples/csv">Download a sample file (simulated)</a>
        </div>
        {err && <div className="mt-4"><ErrorBox message={err.message} />
          {err.detail?.report && <ul className="mt-2 list-disc pl-6 text-xs text-fog-400">{err.detail.report.errors.map((x: string) => <li key={x}>{x}</li>)}</ul>}</div>}
      </div>
      <div className="text-sm leading-relaxed text-fog-400">
        <h3 className="h-section mb-2">What happens to the file</h3>
        <p>Columns are matched by name (aliases like <em>Voltage_measured</em> work), rows are validated for plausible per-cell voltage and temperature, current sign is normalised, and capacity is coulomb-counted if missing.</p>
        <p className="mt-3">If the file holds several cycles, earlier cycles become the ageing history for the RUL fit and the last cycle is analysed.</p>
        <p className="mt-3">Uploaded files are analysed but not stored — only real-time rig data is written to the ledger.</p>
      </div>
    </form>
  );
}

const MANUAL_FIELDS: [string, string, string][] = [
  ["measured_voltage", "Measured pack voltage", "V"], ["current", "Test current", "A"], ["temperature", "Temperature", "°C"],
  ["temperature_rise", "Temperature rise during test", "°C"], ["capacity_ah", "Measured full-discharge capacity", "Ah"],
  ["internal_resistance_mohm", "Pack internal resistance", "mΩ"], ["cycle_count", "Cycle count", ""],
];

function Manual() {
  const { setAnalysis } = useAnalysis();
  const nav = useNavigate();
  const [v, setV] = useState<Record<string, string>>({ battery_id: "MANUAL-001", series_cells: "3", nominal_capacity_ah: "2.5", nominal_voltage: "11.1" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null);
    const body: Record<string, unknown> = { battery_id: v.battery_id };
    for (const [k, x] of Object.entries(v)) if (k !== "battery_id" && x !== "") body[k] = Number(x);
    try {
      const a = await api.manual(body);
      setAnalysis(a, { kind: "manual", id: v.battery_id }); nav("/app");
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  const field = (k: string, label: string, unit: string) => (
    <div key={k}><label className="label" htmlFor={k}>{label}{unit && ` (${unit})`}</label>
      <input id={k} className="input" inputMode="decimal" value={v[k] ?? ""} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></div>
  );
  return (
    <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
      <div className="panel panel-pad">
        <div className="grid gap-4 sm:grid-cols-2">
          {field("battery_id", "Battery ID", "")}{field("series_cells", "Cells in series", "")}
          {field("nominal_capacity_ah", "Nominal capacity", "Ah")}{field("nominal_voltage", "Nominal voltage", "V")}
          {MANUAL_FIELDS.map(([k, l, u]) => field(k, l, u))}
        </div>
        <button className="btn-primary mt-5" disabled={busy}>{busy ? "Analysing…" : "Analyze measurements"}</button>
        {err && <div className="mt-4"><ErrorBox message={err} /></div>}
      </div>
      <div className="text-sm leading-relaxed text-fog-400">
        <h3 className="h-section mb-2">Spot measurements, honest uncertainty</h3>
        <p>Manual entry uses a separate XGBoost variant trained only on scalar measurements. It is less precise than the time-series model, so expect wider intervals and a lower confidence — leave a field blank rather than guessing it.</p>
        <p className="mt-3">Capacity measured from a full discharge carries the most information; resistance decides power-hungry applications.</p>
      </div>
    </form>
  );
}

function LiveStart() {
  const nav = useNavigate();
  const [profiles, setProfiles] = useState<any[]>([]);
  const [p, setP] = useState("RB-B02");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.demoList().then(setProfiles).catch(() => {}); }, []);
  async function start() {
    setBusy(true); setErr(null);
    try { const s = await api.simStart(p, 8); nav(`/app/live?b=${s.battery_id}`); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="panel panel-pad">
        <h3 className="h-section flex items-center gap-2"><Cpu className="h-4 w-4 text-volt" /> ESP32 test rig</h3>
        <p className="mt-2 text-sm text-fog-400">Flash <code className="text-fog-300">firmware/rebat_esp32</code>, set Wi-Fi and this computer's IP in <code className="text-fog-300">config.h</code>. The rig posts readings to:</p>
        <pre className="mt-3 overflow-x-auto rounded-md bg-ink-950 p-3 text-xs text-fog-300">POST /api/v1/hardware/ingest
{`{"battery_id":"RB-001","t_s":312,"voltage":11.72,"current":1.42,
 "temperature":29.4,"capacity":0.124,"internal_resistance":0.042,
 "cycle_count":185,"phase":"run"}`}</pre>
        <p className="mt-3 text-sm text-fog-400">As soon as readings arrive the battery appears on the Live data page. Readings are stored only after the AI has forecast them, and each stored window is sealed in the ledger.</p>
        <button className="btn-ghost mt-4" onClick={() => nav("/app/live")}>Open live data</button>
      </div>
      <div className="panel panel-pad">
        <h3 className="h-section">No rig connected? Stream a simulated one</h3>
        <p className="mt-2 text-sm text-fog-400">The simulator sends the exact ESP32 JSON through the same ingest path, labelled simulation mode.</p>
        <label className="label mt-4" htmlFor="prof">Battery behaviour</label>
        <select id="prof" className="input" value={p} onChange={(e) => setP(e.target.value)}>
          {profiles.map((x) => <option key={x.battery_id} value={x.battery_id}>{x.label} — {x.title}</option>)}
        </select>
        <button className="btn-primary mt-4" disabled={busy} onClick={start}>{busy ? "Starting…" : "Start simulated stream"}</button>
        {err && <div className="mt-4"><ErrorBox message={err} /></div>}
      </div>
    </div>
  );
}
