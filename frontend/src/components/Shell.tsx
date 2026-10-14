import { NavLink, Outlet, Link } from "react-router-dom";
import { Activity, Atom, Box, BatteryCharging, Brain, Fingerprint, FileSearch, FlaskConical, GaugeCircle, LayoutDashboard, Link2, Recycle, Route, Upload, Cpu } from "lucide-react";
import { useAnalysis } from "../lib/store";
import { DataBadge, Disclaimer, SafetyBanner } from "./ui";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Esp32Chip from "./Esp32Chip";
import ChatAssistant from "./ChatAssistant";

const NAV = [
  { to: "/app/live", label: "Live ESP32", icon: Activity },
  { to: "/app/analyze", label: "Analyze battery", icon: Upload },
  { to: "/app", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/app/health", label: "Health & RUL", icon: GaugeCircle },
  { to: "/app/fingerprint", label: "Fingerprint", icon: Fingerprint },
  { to: "/app/explorer", label: "3D battery twin", icon: Box },
  { to: "/app/circular", label: "Reuse recommendation", icon: Recycle },
  { to: "/app/minerals", label: "Battery minerals", icon: Atom },
  { to: "/app/router", label: "Second-life router", icon: Route },
  { to: "/app/explain", label: "Why this route", icon: Brain },
  { to: "/app/diagnostics", label: "Diagnostic assistant", icon: FlaskConical },
  { to: "/app/forensics", label: "Battery forensics", icon: FileSearch },
  { to: "/app/ledger", label: "Battery ledger", icon: Link2 },
  { to: "/app/model", label: "Model status", icon: Cpu },
];

export function Logo({ small }: { small?: boolean }) {
  return (
    <Link to="/" className="flex items-center gap-2.5" aria-label="RE-BAT AI home">
      <svg width={small ? 26 : 30} height={small ? 26 : 30} viewBox="0 0 32 32" aria-hidden>
        <rect x="3" y="8" width="23" height="16" rx="3" fill="none" stroke="#B6F23A" strokeWidth="2" />
        <rect x="26" y="13" width="3" height="6" rx="1" fill="#B6F23A" />
        <path d="M7 19 L11 13 L14 17 L17 11 L21 19" fill="none" stroke="#4FC3E0" strokeWidth="1.8" strokeLinejoin="round" />
      </svg>
      <span className="font-display-tight text-lg font-bold tracking-tight">RE-BAT <span className="text-volt">AI</span></span>
    </Link>
  );
}

export default function Shell() {
  const { result, source, loading } = useAnalysis();
  const [model, setModel] = useState<string>("");
  useEffect(() => { api.health().then((h) => setModel(h.model.status)).catch(() => setModel("backend offline")); }, []);

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_1fr]">
      <aside className="border-b border-ink-700 bg-ink-950 lg:sticky lg:top-0 lg:h-screen lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between px-5 py-4"><Logo /></div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:overflow-visible" aria-label="Main">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => `flex shrink-0 items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${isActive ? "bg-ink-800 text-fog-100 shadow-[inset_2px_0_0_#B6F23A]" : "text-fog-400 hover:text-fog-100"}`}>
              <Icon className="h-4 w-4" /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="hidden px-5 pt-6 text-2xs text-fog-500 lg:block">
          <div>Model</div>
          <div className="mt-0.5 text-fog-400">{model || "…"}</div>
          <div className="mt-3">Version 3.0 · digital twin · AI assistant</div>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-10 flex flex-wrap items-center gap-3 border-b border-ink-700 bg-ink-900/95 px-5 py-3 backdrop-blur sm:px-8">
          <BatteryCharging className="h-4 w-4 text-fog-400" />
          <span className="text-sm text-fog-400">Battery</span>
          <span className="font-display font-semibold">{result?.battery_id ?? "—"}</span>
          {result?.demo && <span className="text-sm text-fog-400">{result.demo.label} · {result.demo.title}</span>}
          {result && <DataBadge label={result.data_label} />}
          {loading && <span className="text-xs text-fog-400">updating…</span>}
          <span className="ml-auto flex items-center gap-4"><Esp32Chip /><Link to="/app/analyze" className="text-sm text-data hover:underline">Change battery</Link></span>
        </header>
        <main className="mx-auto max-w-7xl px-5 py-8 sm:px-8">
          {result && <SafetyBanner alerts={result.safety.alerts} status={result.safety.status} />}
          <Outlet />
          <Disclaimer text={result?.safety.disclaimer ?? "AI recommendations are screening/decision-support outputs. Final battery reuse requires validated electrical, thermal, mechanical and safety testing."} />
        </main>
      </div>
      <ChatAssistant />
    </div>
  );
}
