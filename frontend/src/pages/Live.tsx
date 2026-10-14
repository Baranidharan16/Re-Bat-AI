import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BatteryFull, Eye, Footprints, Lightbulb, Moon, Sun, Zap } from "lucide-react";
import { api, fmt, openLiveFeed, type Analysis } from "../lib/api";
import { useAnalysis } from "../lib/store";
import { DataBadge, ErrorBox, Meter, PageHead, SafetyBanner } from "../components/ui";
import Esp32LabPanel from "../components/Esp32LabPanel";
import RigPanel from "../components/RigPanel";
import LazyTwin from "../components/LazyTwin";
import { CompositionBar, PATHWAY_STYLE, PathwayIcon, ReuseIcon, sizingLines } from "../components/circular";

type Reading = { t_s: number; voltage: number; current: number; temperature: number | null; capacity: number | null; cycle_count: number | null;
  internal_resistance: number | null; gas_v?: number | null; ldr?: number; dark?: boolean; pir?: boolean; battery_present?: boolean; lamp_on?: boolean; load_on?: boolean; rig_state?: string };
const tip = { contentStyle: { background: "#121D31", border: "1px solid #2A3B5C", borderRadius: 6, fontSize: 12 }, labelStyle: { color: "#8A9AB5" } };

function Trace({ data, k, color, unit, label }: { data: Reading[]; k: keyof Reading; color: string; unit: string; label: string }) {
  return (
    <div className="panel panel-pad">
      <div className="flex justify-between text-sm"><span>{label}</span><span className="num text-fog-400">{fmt.n(data.at(-1)?.[k] as number, 2)} {unit}</span></div>
      <ResponsiveContainer width="100%" height={170}>
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
          <CartesianGrid strokeDasharray="2 4" />
          <XAxis dataKey="t_s" type="number" domain={["dataMin", "dataMax"]} tickFormatter={(x) => `${(x / 60).toFixed(0)}m`} />
          <YAxis domain={["auto", "auto"]} width={44} tickFormatter={(x) => Number(x).toFixed(1)} />
          <Tooltip {...tip} labelFormatter={(l) => `t = ${(Number(l) / 60).toFixed(1)} min`} formatter={(v: any) => `${Number(v).toFixed(3)} ${unit}`} />
          <Line dataKey={k as string} stroke={color} dot={false} strokeWidth={1.8} isAnimationActive={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Street-light output on the rig: LDR (dusk), PIR (motion), IR (battery in bay), lamp relay. */
function StreetLight({ aux }: { aux: Record<string, any> }) {
  const dark = aux.dark ?? (aux.ldr != null ? aux.ldr > 2500 : null);
  const lamp = !!aux.lamp_on;
  const items: [string, string, any, boolean | null][] = [
    ["LDR · GPIO 35", dark == null ? "—" : dark ? `dark${aux.ldr != null ? ` (${Math.round(aux.ldr)})` : ""}` : `daylight${aux.ldr != null ? ` (${Math.round(aux.ldr)})` : ""}`, dark ? Moon : Sun, dark],
    ["PIR · GPIO 27", aux.pir == null ? "—" : aux.pir ? "person detected" : "no motion", Footprints, aux.pir ?? null],
    ["IR · GPIO 13", aux.battery_present == null ? "—" : aux.battery_present ? "battery in bay" : "bay empty", Eye, aux.battery_present ?? null],
    ["Test load · GPIO 25", aux.load_on == null ? "—" : aux.load_on ? "on" : "off", Zap, aux.load_on ?? null],
  ];
  return (
    <section className="panel mt-4 grid overflow-hidden md:grid-cols-[220px_1fr]">
      <div className={`flex flex-col items-center justify-end gap-0 p-5 ${dark ? "bg-[#0B1530]" : "bg-ink-800"}`} aria-label={`Street light ${lamp ? "on" : "off"}`}>
        <div className={`flex h-16 w-16 items-center justify-center rounded-full border-2 ${lamp ? "border-[#FFD66B] bg-[#FFD66B] shadow-[0_0_0_14px_rgba(255,214,107,.25),0_0_0_30px_rgba(255,214,107,.1)]" : "border-ink-600 bg-ink-700"}`}>
          <Lightbulb className={`h-7 w-7 ${lamp ? "text-ink-950" : "text-fog-500"}`} />
        </div>
        <div className="h-20 w-2 bg-ink-600" />
        <div className="h-1.5 w-16 rounded bg-ink-600" />
        <div className={`mt-3 font-display text-lg font-semibold ${lamp ? "text-[#FFD66B]" : "text-fog-400"}`}>Lamp {lamp ? "ON" : "OFF"}</div>
        <div className="text-2xs text-fog-500">relay · GPIO 26</div>
      </div>
      <div className="p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="h-section">Second-life output · rural street light</h2>
          <span className="text-xs text-fog-400">{aux.rig_state ? `rig state ${aux.rig_state}` : ""}{aux.at ? ` · ${new Date(aux.at).toLocaleTimeString()}` : ""}</span>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
          {items.map(([l, v, Icon, active]) => (
            <div key={l} className={`rounded-md border px-3 py-2.5 ${active ? "border-volt/40 bg-volt/5" : "border-ink-700"}`}>
              <div className="flex items-center gap-1.5 text-2xs text-fog-400"><Icon className="h-3.5 w-3.5" />{l}</div>
              <div className="mt-0.5 text-sm font-medium">{v}</div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-fog-500">Automatic mode: the lamp lights when the LDR says it is dark and the PIR sees someone, then stays on for a hold time. The lamp is also the discharge load, so every night of light measures the battery's capacity.</p>
      </div>
    </section>
  );
}

export default function Live() {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const { setAnalysis } = useAnalysis();
  const [sessions, setSessions] = useState<any[]>([]);
  const [readings, setReadings] = useState<Reading[]>([]);
  const [session, setSession] = useState<any>(null);
  const [forecast, setForecast] = useState<Analysis | null>(null);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [link, setLink] = useState<"ws" | "sse" | "down">("down");
  const [err, setErr] = useState<string | null>(null);
  const [profile, setProfile] = useState("RB-B02");
  const [bridgeOn, setBridgeOn] = useState(false);
  const bid = params.get("b") ?? (sessions.find((x) => x.source === "ESP32") ?? sessions[0])?.battery_id ?? null;

  useEffect(() => {
    const load = () => api.liveSessions().then(setSessions).catch((e) => setErr(e.message));
    load(); const t = setInterval(load, 4000); return () => clearInterval(t);
  }, []);
  useEffect(() => {
    const load = () => api.bridgeStatus().then((s) => setBridgeOn(!!(s.state?.running && s.state?.connected))).catch(() => {});
    load(); const t = setInterval(load, 4000); return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!bid) return;
    setReadings([]); setForecast(null); setAlerts([]);
    return openLiveFeed(bid, {
      status: setLink,
      event: (e) => {
        if (e.session) setSession(e.session);
        if (e.type === "snapshot") { setReadings(e.readings); if (e.forecast) setForecast(e.forecast); setAlerts(e.alerts ?? []); }
        if (e.type === "reading") {
          setReadings((r) => {
            const prev = r.at(-1);
            if (prev && e.reading.t_s < prev.t_s - 1) return [e.reading];   // a new test window started
            return r.length >= 600 ? [...r.slice(-599), e.reading] : [...r, e.reading];
          });
          if (e.alerts?.length) setAlerts((a) => [...a, ...e.alerts].slice(-10));
        }
        if (e.type === "forecast") setForecast(e.result);
      },
    });
  }, [bid]);

  const last = readings.at(-1);
  const isSim = session?.source === "LIVE_SIM";
  const aux = { ...(session?.aux ?? {}), ...Object.fromEntries(Object.entries(last ?? {}).filter(([k, v]) => ["ldr", "dark", "pir", "battery_present", "lamp_on", "load_on", "rig_state"].includes(k) && v != null)) };
  const hasAux = Object.keys(aux).some((k) => k !== "at");
  const ir = last?.internal_resistance ?? (forecast?.measurements?.ir_pack_mohm != null ? Number(forecast.measurements.ir_pack_mohm) / 1000 : null);
  const c = forecast?.circular;
  const best = c?.reuse.options.find((o) => o.id === c.reuse.best);

  async function start() {
    setErr(null);
    try { const s = await api.simStart(profile, 8); setParams({ b: s.battery_id }); } catch (e: any) { setErr(e.message); }
  }
  function open(path: string) {
    if (!forecast) return;
    setAnalysis(forecast, { kind: "live", id: forecast.battery_id }); nav(path);
  }

  return (
    <>
      <PageHead title="Live ESP32 battery intelligence" sub="The ESP32 streams over a WebSocket. Every reading is safety-checked, forecast by the AI, routed to reuse or recycling, then stored and sealed in the ledger."
        right={
          <div className="flex flex-wrap items-center gap-2">
            <select aria-label="Session" className="input w-auto" value={bid ?? ""} onChange={(e) => setParams({ b: e.target.value })}>
              {!sessions.length && <option value="">No sessions yet</option>}
              {sessions.map((s) => <option key={s.battery_id} value={s.battery_id}>{s.battery_id} · {s.source === "ESP32" ? "ESP32" : "simulation"} · {s.status}</option>)}
            </select>
            <select aria-label="Simulated profile" className="input w-auto" value={profile} onChange={(e) => setProfile(e.target.value)}>
              {["RB-A01", "RB-B02", "RB-C03", "RB-D04", "RB-E05", "RB-F06"].map((p) => <option key={p}>{p}</option>)}
            </select>
            <button className="btn-ghost" onClick={start}>Simulate (no hardware)</button>
            {bid && session?.status === "streaming" && <button className="btn-ghost" onClick={() => api.liveStop(bid)}>Stop</button>}
          </div>
        } />
      {err && <div className="mb-4"><ErrorBox message={err} /></div>}
      <RigPanel batteryId={bid} onRig={(b) => { if (!params.get("b") && sessions.some((x) => x.battery_id === b)) setParams({ b }); }} />
      <details className="mb-5" open={bridgeOn}>
        <summary className="cursor-pointer text-xs text-fog-400 hover:text-fog-100">Older Battery Lab firmware (HTTP polling bridge){bridgeOn ? " · connected" : ""}</summary>
        <div className="mt-3"><Esp32LabPanel onBattery={(b) => { if (!params.get("b") && sessions.some((x) => x.battery_id === b)) setParams({ b }); }} /></div>
      </details>
      {!bid && <div className="panel panel-pad text-sm text-fog-400">No battery is streaming. Connect the ESP32 rig (it appears here automatically) or start a simulated stream above.</div>}

      {bid && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <span className="flex items-center gap-2"><span className={`h-2.5 w-2.5 rounded-full ${link !== "down" ? "bg-volt" : "bg-fog-500"} ${link !== "down" && session?.status === "streaming" ? "live-dot" : ""}`} />{link === "ws" ? "Live over WebSocket" : link === "sse" ? "Live over SSE" : "Reconnecting…"}</span>
            <span className="text-fog-400">{({ streaming: "Data streaming", idle: "Test window closed", complete: "Test complete", stopped: "Stopped" } as Record<string, string>)[session?.status] ?? "—"}</span>
            <span className="text-fog-400">Last update {session?.last_update ? new Date(session.last_update).toLocaleTimeString() : "—"}</span>
            <span className="text-fog-400">Buffer {session?.buffer ?? 0} · total {session?.readings_total ?? 0}</span>
            {session && <DataBadge label={isSim ? "SIMULATION MODE" : "LIVE · ESP32 HARDWARE"} />}
          </div>
          {alerts.length > 0 && <SafetyBanner alerts={alerts} status={alerts.some((a) => a.level === "ALARM") ? "ALARM" : "WARNING"} />}

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-8">
            {[["Voltage", fmt.n(last?.voltage, 2), "V"], ["Current", fmt.n(last?.current, 2), "A"], ["Temperature", fmt.n(last?.temperature, 1), "°C"],
              ["Power", last ? fmt.n(last.voltage * last.current, 1) : "—", "W"], ["Capacity out", fmt.n(last?.capacity, 3), "Ah"],
              ["Energy out", last?.capacity != null ? fmt.n(last.capacity * last.voltage, 1) : "—", "Wh"],
              ["Internal resistance", ir != null ? fmt.n(ir * 1000, 1) : "—", "mΩ"],
              last?.gas_v != null ? ["Gas sensor", fmt.n(last.gas_v, 2), "V"] : ["Cycle count", last?.cycle_count != null ? fmt.int(last.cycle_count) : "unknown", ""]].map(([l, v, u]) => (
              <div key={l} className="panel px-4 py-3"><div className="text-2xs text-fog-400">{l}</div><div className="num font-display text-xl font-semibold">{v}<span className="ml-1 text-xs font-normal text-fog-400">{u}</span></div></div>
            ))}
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <Trace data={readings} k="voltage" color="#4FC3E0" unit="V" label="Voltage vs time" />
            <Trace data={readings} k="current" color="#B6F23A" unit="A" label="Current vs time" />
            <Trace data={readings} k="temperature" color="#F2B33D" unit="°C" label="Temperature vs time" />
          </div>

          {hasAux && <StreetLight aux={aux} />}

          <div className="mt-4">
            <LazyTwin modelId="rebat_rig" height={420} initialTab="working"
              twin={{ soh: forecast?.soh.soh ?? null, tempC: last?.temperature ?? null, currentA: last?.current ?? 0, alarm: alerts.some((a) => a.level === "ALARM"),
                imbalanceMv: last && (last as any).cell_v_max != null && (last as any).cell_v_min != null ? ((last as any).cell_v_max - (last as any).cell_v_min) * 1000 : null }}
              live={{ voltage: last?.voltage, current: last?.current, temperature: last?.temperature, gas: last?.gas_v ?? null, soh: forecast?.soh.soh, rul: forecast?.rul.rul_cycles,
                label: `Live from ${bid}: power pulses follow the measured current, cells take the AI's SOH colour after the first forecast.` }} />
          </div>

          <section className="panel mt-4 overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
              <h2 className="h-section">Live AI verdict</h2>
              {forecast && <div className="flex flex-wrap gap-2">
                <button className="btn-ghost" onClick={() => open("/app/forensics")}>Forensics</button>
                <button className="btn-ghost" onClick={() => open("/app/minerals")}>Minerals</button>
                <button className="btn-primary" onClick={() => open("/app/circular")}>Open reuse / recycle</button>
              </div>}
            </div>
            {!forecast ? <p className="border-t border-ink-700 px-5 py-4 text-sm text-fog-400">Waiting for enough discharge data to forecast (a pulse plus a few minutes of load).</p> : (
              <>
                {c && (
                  <div className={`border-t border-ink-700 px-5 py-4 ${PATHWAY_STYLE[c.pathway].bg}`}>
                    <div className={`flex items-center gap-2 font-display text-2xl font-bold ${PATHWAY_STYLE[c.pathway].text}`}><PathwayIcon p={c.pathway} className="h-6 w-6" />{c.headline}</div>
                    <p className="mt-1 text-sm text-fog-300">{c.reason}</p>
                  </div>
                )}
                <div className="grid gap-6 border-t border-ink-700 p-5 text-sm md:grid-cols-4">
                  <div><div className="text-xs text-fog-400">SOH</div><div className="num font-display text-3xl font-bold">{forecast.soh.soh.toFixed(1)}%</div><div className="text-xs text-fog-400">{forecast.soh.lo.toFixed(1)}–{forecast.soh.hi.toFixed(1)}%</div></div>
                  <div><div className="text-xs text-fog-400">RUL</div><div className="num font-display text-3xl font-bold">{forecast.rul.capped ? `${fmt.int(forecast.rul.rul_cycles)}+` : fmt.int(forecast.rul.rul_cycles)}</div><div className="text-xs text-fog-400">cycles to {forecast.rul.eol_soh}% SOH</div></div>
                  <div><div className="text-xs text-fog-400">Confidence</div><div className="num font-display text-3xl font-bold">{forecast.confidence.value.toFixed(0)}%</div><Meter value={forecast.confidence.value} tone="data" height={4} /></div>
                  <div><div className="text-xs text-fog-400">Sealed in ledger</div>{forecast.ledger ? <><div className="font-display text-lg">Block #{forecast.ledger.idx}</div><div className="break-all text-2xs text-fog-500">{forecast.ledger.block_hash.slice(0, 32)}…</div><div className="text-xs text-fog-400">{forecast.ledger.stored_readings} readings stored{forecast.live?.final ? " · test complete" : " · rolling"}</div></> : "—"}</div>
                </div>
                {c && (
                  <div className="grid gap-6 border-t border-ink-700 p-5 lg:grid-cols-2">
                    <div>
                      <div className="text-xs text-fog-400">{c.reuse.eligible ? "Best reuse" : "Best reuse (not recommended)"}</div>
                      {best && <>
                        <div className="mt-1 flex items-center gap-2 font-display text-lg font-semibold"><ReuseIcon id={best.id} className="h-5 w-5 text-volt" />{best.name}<span className="num text-fog-400">{best.score.toFixed(0)}</span></div>
                        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">{sizingLines(best).slice(0, 4).map(([k, v]) => <div key={k}><dt className="text-fog-500">{k}</dt><dd className="num text-fog-100">{v}</dd></div>)}</dl>
                      </>}
                      <div className="mt-3 flex flex-wrap gap-2 text-2xs text-fog-400">{c.reuse.options.filter((o) => o.id !== best?.id).map((o) => <span key={o.id} className="chip border border-ink-600">{o.name} {o.score.toFixed(0)}</span>)}</div>
                    </div>
                    <div>
                      <div className="text-xs text-fog-400">Minerals inside ({c.recycle.n_cells} cells · {fmt.n(c.recycle.pack_mass_g, 0)} g)</div>
                      <div className="mt-2"><CompositionBar m={c.recycle} height={20} /></div>
                      <div className="mt-2 text-xs text-fog-400">Critical minerals recoverable: <span className="num text-amber">{fmt.n(c.recycle.totals.critical_recoverable_g, 1)} g</span> · Li₂CO₃ equivalent <span className="num text-volt">{fmt.n(c.recycle.totals.lithium_carbonate_equivalent_g, 1)} g</span></div>
                    </div>
                  </div>
                )}
              </>
            )}
          </section>
          {!hasAux && session && !isSim && <p className="mt-3 flex items-center gap-2 text-xs text-fog-500"><BatteryFull className="h-3.5 w-3.5" />Street-light sensors (LDR, PIR, IR, lamp relay) appear here when the WebSocket firmware reports them.</p>}
        </>
      )}
    </>
  );
}
