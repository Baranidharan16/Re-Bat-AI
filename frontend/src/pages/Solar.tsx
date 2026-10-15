import { ExternalLink, Maximize2, RefreshCw, Sun, Zap, BatteryCharging, Gauge } from "lucide-react";
import { PageHead } from "../components/ui";

export default function Solar() {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <PageHead
          title="Solar & Second-Life Twin"
          sub="Physics-based accelerated simulation: Sun (GHI) → PV Panel → MPPT Charge Controller → Second-life Pack → LED Street Light"
        />
        <div className="flex items-center gap-2">
          <a
            href="/solar"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-lg bg-volt px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-volt/90 shadow-md"
          >
            <Maximize2 className="h-4 w-4" /> Open Fullscreen Twin
          </a>
        </div>
      </div>

      {/* Feature summary banner */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="panel panel-pad border-l-4 border-amber-400 bg-ink-900/50">
          <div className="flex items-center gap-2 text-xs font-medium text-amber-400">
            <Sun className="h-4 w-4" /> Solar Irradiance
          </div>
          <div className="mt-1 font-display text-lg font-semibold text-fog-100">Haurwitz Clear-Sky & GHI</div>
          <div className="text-xs text-fog-400 mt-1">Stochastic cloud index, NOCT cell temp derating</div>
        </div>
        <div className="panel panel-pad border-l-4 border-teal-400 bg-ink-900/50">
          <div className="flex items-center gap-2 text-xs font-medium text-teal-400">
            <Zap className="h-4 w-4" /> MPPT Controller
          </div>
          <div className="mt-1 font-display text-lg font-semibold text-fog-100">96% Efficiency CC-CV</div>
          <div className="text-xs text-fog-400 mt-1">Thermal derate above 40°C, LVD cut-off at 10% SOC</div>
        </div>
        <div className="panel panel-pad border-l-4 border-volt bg-ink-900/50">
          <div className="flex items-center gap-2 text-xs font-medium text-volt">
            <BatteryCharging className="h-4 w-4" /> Second-Life Pack
          </div>
          <div className="mt-1 font-display text-lg font-semibold text-fog-100">Live Battery State</div>
          <div className="text-xs text-fog-400 mt-1">Coulomb counting, DC IR, OCV curve & pack thermal model</div>
        </div>
        <div className="panel panel-pad border-l-4 border-indigo-400 bg-ink-900/50">
          <div className="flex items-center gap-2 text-xs font-medium text-indigo-400">
            <Gauge className="h-4 w-4" /> Lifetime Projection
          </div>
          <div className="mt-1 font-display text-lg font-semibold text-fog-100">Multi-Year Ageing</div>
          <div className="text-xs text-fog-400 mt-1">Cycle + calendar fade with Arrhenius & knee onset</div>
        </div>
      </div>

      {/* Embedded interactive Solar Twin Dashboard */}
      <div className="panel overflow-hidden border border-ink-700 shadow-2xl rounded-xl">
        <div className="flex items-center justify-between border-b border-ink-700 bg-ink-950 px-4 py-2.5 text-xs text-fog-400">
          <span className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-volt animate-pulse" />
            Interactive Solar Twin Simulator Engine
          </span>
          <div className="flex items-center gap-3">
            <a href="/solar" target="_blank" rel="noreferrer" className="flex items-center gap-1 text-data hover:underline">
              Direct Link <ExternalLink className="h-3 w-3" />
            </a>
          </div>
        </div>
        <div className="w-full bg-[#0e151d]" style={{ height: "calc(100vh - 230px)", minHeight: "780px" }}>
          <iframe
            src="/solar"
            title="Solar Twin Simulator"
            className="h-full w-full border-0"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope"
          />
        </div>
      </div>
    </div>
  );
}
