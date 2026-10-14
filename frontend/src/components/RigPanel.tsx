import { useEffect, useState } from "react";
import { Copy, Lightbulb, LightbulbOff, Play, Radio, Square, Timer, Wand2 } from "lucide-react";
import { api } from "../lib/api";
import { ErrorBox } from "./ui";

/** ESP32 WebSocket connector: who is connected, the address to flash into the firmware, and
 *  commands sent straight to the board (lamp, tests, stop). */
export default function RigPanel({ batteryId, onRig }: { batteryId: string | null; onRig?: (bid: string) => void }) {
  const [info, setInfo] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const load = () => api.connectInfo().then(setInfo).catch(() => setInfo(null));
    load(); const t = setInterval(load, 2500); return () => clearInterval(t);
  }, []);

  const rigs: any[] = info?.hub?.rigs ?? [];
  const rig = rigs.find((r) => r.battery_id === batteryId) ?? rigs[0];
  useEffect(() => { if (rig && onRig) onRig(rig.battery_id); }, [rig?.battery_id]);

  async function send(cmd: string) {
    if (!rig) return;
    setBusy(cmd); setErr(null); setMsg(null);
    try { const r = await api.rigCommand(rig.battery_id, cmd); setMsg(`Sent to ESP32: ${r.description}`); }
    catch (e: any) { setErr(e.message); } finally { setBusy(null); }
  }
  function copy() {
    const u = info?.websocket_urls?.[0];
    if (!u) return;
    try { navigator.clipboard.writeText(u); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard blocked */ }
  }

  const on = !!rig;
  const cmdBtn = (cmd: string, label: string, Icon: any, primary = false) => (
    <button key={cmd} className={primary ? "btn-primary" : "btn-ghost"} disabled={!on || !!busy} onClick={() => send(cmd)}>
      <Icon className="h-4 w-4" />{busy === cmd ? "Sending…" : label}
    </button>
  );

  return (
    <section className={`panel mb-4 ${on ? "border-volt/50" : ""}`}>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3 p-5">
        <div className="flex items-center gap-3">
          <span className={`flex h-10 w-10 items-center justify-center rounded-full ${on ? "bg-volt/15" : "bg-ink-700"}`}><Radio className={`h-5 w-5 ${on ? "text-volt" : "text-fog-400"}`} /></span>
          <div>
            <div className="font-display text-lg font-semibold">ESP32 WebSocket connector</div>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className={`h-2.5 w-2.5 rounded-full ${on ? "bg-volt live-dot" : "bg-amber"}`} />
              {!info ? "Checking…" : on
                ? <>Rig <span className="font-semibold">{rig.battery_id}</span> connected{rig.device_ip ? <> from {rig.device_ip}</> : null} · {rig.firmware ?? "firmware"} · {rig.messages} messages · last {rig.last_message_s_ago}s ago</>
                : <>Waiting for the ESP32 to connect to <span className="font-mono text-fog-300">{info.websocket_urls?.[0] ?? "ws://<laptop-ip>:8000/api/v1/hardware/ws"}</span></>}
            </div>
          </div>
        </div>
        {!on && info?.websocket_urls?.[0] && <button className="btn-ghost ml-auto" onClick={copy}><Copy className="h-4 w-4" />{copied ? "Copied" : "Copy address"}</button>}
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-ink-700 px-5 py-3">
        <span className="mr-1 text-xs text-fog-400">Control the rig</span>
        {cmdBtn("quick_test", "Quick test (2 min)", Timer, true)}
        {cmdBtn("start_test", "Full capacity test", Play)}
        {cmdBtn("lamp_auto", "Street light auto", Wand2)}
        {cmdBtn("lamp_on", "Lamp on", Lightbulb)}
        {cmdBtn("lamp_off", "Lamp off", LightbulbOff)}
        {cmdBtn("stop", "Stop all", Square)}
      </div>
      {!on && info && (
        <p className="border-t border-ink-700 px-5 py-3 text-xs text-fog-400">
          In <span className="font-mono">firmware/rebat_ws_rig/config.h</span> set <span className="font-mono text-fog-300">WS_HOST "{info.firmware_settings.WS_HOST}"</span>, <span className="font-mono text-fog-300">WS_PORT {info.firmware_settings.WS_PORT}</span>, and your Wi-Fi.
          Laptop and ESP32 must be on the same network. No board? Run <span className="font-mono">python tools/esp32_ws_emulator.py</span>.
        </p>
      )}
      {msg && <p className="border-t border-ink-700 px-5 py-2 text-xs text-volt">{msg}</p>}
      {err && <div className="px-5 pb-4"><ErrorBox message={err} /></div>}
    </section>
  );
}
