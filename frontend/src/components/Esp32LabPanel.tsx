import { useEffect, useState, type FormEvent } from "react";
import { Cpu, Flag, Radar, Settings2, Square, Plug } from "lucide-react";
import { api } from "../lib/api";
import { ErrorBox } from "./ui";

type Form = { esp32_url: string; battery_id: string; series_cells: string; nominal_capacity_ah: string; invert_current: boolean; cycle_count: string };

/** ESP32 Battery Lab connection. The backend connects automatically at start-up and finds the
 *  ESP32 on the network if its address changes; this panel only shows status and optional settings. */
export default function Esp32LabPanel({ onBattery }: { onBattery: (batteryId: string) => void }) {
  const [status, setStatus] = useState<any>(null);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState<Form | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const load = () => api.bridgeStatus().then((s) => {
      setStatus(s);
      setF((cur) => cur ?? {
        esp32_url: s.config.esp32_url, battery_id: s.config.battery_id, series_cells: String(s.config.series_cells),
        nominal_capacity_ah: String(s.config.nominal_capacity_ah), invert_current: s.config.invert_current,
        cycle_count: s.config.cycle_count == null ? "" : String(s.config.cycle_count),
      });
    }).catch(() => {});
    load(); const t = setInterval(load, 2000); return () => clearInterval(t);
  }, []);

  useEffect(() => { if (status?.state?.connected && status.state.readings_sent > 0) onBattery(status.config.battery_id); },
    [status?.state?.connected, status?.config?.battery_id, status?.state?.readings_sent > 0]);

  async function save(e: FormEvent) {
    e.preventDefault(); if (!f) return; setBusy("save"); setErr(null);
    try {
      setStatus(await api.bridgeStart({
        esp32_url: f.esp32_url, battery_id: f.battery_id, series_cells: Number(f.series_cells),
        nominal_capacity_ah: Number(f.nominal_capacity_ah), invert_current: f.invert_current,
        cycle_count: f.cycle_count === "" ? null : Number(f.cycle_count),
      }));
      setOpen(false);
    } catch (e: any) { setErr(e.message); } finally { setBusy(null); }
  }
  async function find() {
    setBusy("find"); setErr(null);
    try { const s = await api.bridgeDiscover(); setStatus(s); setF((x) => x && { ...x, esp32_url: s.config.esp32_url }); }
    catch (e: any) { setErr(e.message); } finally { setBusy(null); }
  }

  const st = status?.state, cfg = status?.config;
  const connected = st?.running && st?.connected;
  const searching = st?.discovering || busy === "find";
  const field = (k: keyof Form, label: string, w = "") => f && (
    <div className={w}><label className="label" htmlFor={`lab-${k}`}>{label}</label>
      <input id={`lab-${k}`} className="input" value={f[k] as string} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></div>
  );

  return (
    <section className={`panel mb-5 ${connected ? "border-volt/50" : ""}`}>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3 p-5">
        <div className="flex items-center gap-3">
          <span className={`flex h-10 w-10 items-center justify-center rounded-full ${connected ? "bg-volt/15" : "bg-ink-700"}`}>
            <Cpu className={`h-5 w-5 ${connected ? "text-volt" : "text-fog-400"}`} />
          </span>
          <div>
            <div className="font-display text-lg font-semibold">ESP32 Battery Lab · HTTP polling</div>
            <div className="flex items-center gap-2 text-sm">
              <span className={`h-2.5 w-2.5 rounded-full ${connected ? "bg-volt live-dot" : searching || st?.running ? "bg-amber" : "bg-fog-500"}`} />
              {!status ? "Checking…" : connected ? <>Connected automatically · <span className="text-fog-300">{cfg.esp32_url}</span> · last reading {st.last_ok}</>
                : searching ? "Searching your Wi-Fi network for the ESP32…"
                : st?.running ? <>Waiting for the ESP32 at <span className="text-fog-300">{cfg.esp32_url}</span></> : "Not connected"}
            </div>
          </div>
        </div>
        <div className="ml-auto flex flex-wrap gap-2">
          {!connected && <button className="btn-primary" onClick={find} disabled={!!busy}><Radar className="h-4 w-4" />{searching ? "Searching…" : "Find ESP32 now"}</button>}
          {connected && <button className="btn-ghost" onClick={() => api.bridgeCloseWindow().then(setStatus)}><Flag className="h-4 w-4" />End test now</button>}
          <button className="btn-ghost" onClick={() => setOpen(!open)} aria-expanded={open}><Settings2 className="h-4 w-4" />Settings</button>
          {st?.running && <button className="btn-ghost" onClick={() => api.bridgeStop().then(setStatus)}><Square className="h-4 w-4" />Disconnect</button>}
        </div>
      </div>

      {connected && (
        <p className="border-t border-ink-700 px-5 py-3 text-xs text-fog-400">
          Battery {cfg.battery_id} · {cfg.series_cells}S · {cfg.nominal_capacity_ah} Ah · {st.readings_sent} readings · {st.windows_closed} tests completed
          {st.gas_baseline_v != null && <> · gas baseline {st.gas_baseline_v.toFixed(2)} V</>}
          {" "}· a test closes itself after {cfg.rest_close_s} s of rest following a discharge
        </p>
      )}
      {!connected && st?.running && st?.discovery_note && <p className="border-t border-ink-700 px-5 py-3 text-sm text-amber">{st.discovery_note}. Check that the ESP32 is powered and on the same Wi-Fi as this computer.</p>}

      {open && f && (
        <form onSubmit={save} className="grid gap-3 border-t border-ink-700 p-5 sm:grid-cols-2 lg:grid-cols-6">
          {field("esp32_url", "ESP32 address", "lg:col-span-2")}
          {field("battery_id", "Battery ID")}
          {field("series_cells", "Cells in series")}
          {field("nominal_capacity_ah", "Nominal capacity (Ah)")}
          {field("cycle_count", "Cycle count (if known)")}
          <label className="flex items-center gap-2 text-sm text-fog-300 lg:col-span-4">
            <input type="checkbox" checked={f.invert_current} onChange={(e) => setF({ ...f, invert_current: e.target.checked })} />
            Current reads negative while discharging (flip sign)
          </label>
          <div className="flex justify-end lg:col-span-2"><button className="btn-primary" disabled={!!busy}><Plug className="h-4 w-4" />Save and connect</button></div>
          <p className="text-xs text-fog-500 lg:col-span-6">Saved on this computer — next time RE-BAT AI starts it connects by itself. If the ESP32 gets a new IP address, it is found again automatically.</p>
        </form>
      )}
      {err && <div className="px-5 pb-5"><ErrorBox message={err} /></div>}
    </section>
  );
}
