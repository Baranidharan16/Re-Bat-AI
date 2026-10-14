import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Cpu } from "lucide-react";
import { api } from "../lib/api";

/** Always-visible ESP32 status in the top bar; one click opens the live page for that battery. */
export default function Esp32Chip() {
  const [s, setS] = useState<any>(null);
  const [rig, setRig] = useState<any>(null);
  useEffect(() => {
    const load = () => {
      api.bridgeStatus().then(setS).catch(() => setS(null));
      api.rigs().then((h) => setRig(h.rigs[0] ?? null)).catch(() => setRig(null));
    };
    load(); const t = setInterval(load, 3000); return () => clearInterval(t);
  }, []);
  if (rig) {
    return (
      <Link to={`/app/live?b=${encodeURIComponent(rig.battery_id)}`} className="chip border border-volt/50 bg-volt/10 px-3 py-1.5 text-xs text-volt">
        <Cpu className="h-3.5 w-3.5" /><span className="h-2 w-2 rounded-full bg-volt live-dot" />ESP32 live · WebSocket · {rig.battery_id}
      </Link>
    );
  }
  const st = s?.state, connected = st?.running && st?.connected;
  const v = st?.last_raw?.battery_v;
  const label = !s ? "ESP32 offline" : connected ? `ESP32 live · ${s.config.battery_id}${v != null ? ` · ${Number(v).toFixed(2)} V` : ""}`
    : st?.discovering ? "Finding ESP32…" : st?.running ? "Waiting for ESP32" : "ESP32 not connected";
  return (
    <Link to={connected ? `/app/live?b=${encodeURIComponent(s.config.battery_id)}` : "/app/live"}
      className={`chip border px-3 py-1.5 text-xs ${connected ? "border-volt/50 bg-volt/10 text-volt" : "border-ink-600 text-fog-400 hover:text-fog-100"}`}>
      <Cpu className="h-3.5 w-3.5" />
      <span className={`h-2 w-2 rounded-full ${connected ? "bg-volt live-dot" : st?.running ? "bg-amber" : "bg-fog-500"}`} />
      {label}
    </Link>
  );
}
