import type { ReactNode } from "react";
import { AlertTriangle, Info, OctagonAlert } from "lucide-react";
import type { Alert, Analysis } from "../lib/api";

export function DataBadge({ label }: { label: string }) {
  const live = label.includes("ESP32");
  const sim = label.includes("SIMUL") || label.includes("DEMO");
  const cls = live ? "bg-volt/15 text-volt border-volt/40" : sim ? "bg-amber/10 text-amber border-amber/40" : "bg-data/10 text-data border-data/40";
  return <span className={`chip border ${cls}`}>{label}</span>;
}

export function PageHead({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-2xl font-bold sm:text-3xl">{title}</h1>
        {sub && <p className="mt-1 max-w-2xl text-sm text-fog-400">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

export function Stat({ label, value, unit, sub, tone }: { label: string; value: ReactNode; unit?: string; sub?: ReactNode; tone?: "volt" | "data" | "amber" | "alarm" }) {
  const c = tone === "volt" ? "text-volt" : tone === "data" ? "text-data" : tone === "amber" ? "text-amber" : tone === "alarm" ? "text-alarm" : "text-fog-100";
  return (
    <div className="panel panel-pad">
      <div className="text-xs text-fog-400">{label}</div>
      <div className={`mt-1 font-display text-2xl font-semibold num ${c}`}>
        {value}{unit && <span className="ml-1 text-sm font-normal text-fog-400">{unit}</span>}
      </div>
      {sub && <div className="mt-1 text-xs text-fog-400">{sub}</div>}
    </div>
  );
}

const GRADE_TONE: Record<string, string> = {
  GOOD: "text-volt border-volt/40", HIGH: "text-volt border-volt/40", LOW: "text-volt border-volt/40",
  MEDIUM: "text-data border-data/40", MODERATE: "text-data border-data/40",
  POOR: "text-amber border-amber/40", "NOT MEASURED": "text-fog-500 border-ink-600", UNKNOWN: "text-fog-500 border-ink-600",
};
// For resistance/degradation/imbalance/thermal-risk, LOW is good; for power, LOW is bad.
export function Grade({ g, invert }: { g: string; invert?: boolean }) {
  let cls = GRADE_TONE[g] ?? "text-fog-300 border-ink-600";
  if (invert && g === "LOW") cls = "text-amber border-amber/40";
  if (invert && g === "HIGH") cls = "text-volt border-volt/40";
  return <span className={`chip border ${cls}`}>{g.toLowerCase()}</span>;
}

export function RiskChip({ risk }: { risk: string }) {
  const cls = risk === "LOW" ? "text-volt border-volt/40" : risk === "MEDIUM" ? "text-amber border-amber/40" : risk === "HIGH" ? "text-alarm border-alarm/50" : "text-fog-500 border-ink-600";
  return <span className={`chip border ${cls}`}>{risk.toLowerCase()}</span>;
}

export function Meter({ value, max = 100, tone = "volt", height = 6, animate = false }: { value: number; max?: number; tone?: "volt" | "data" | "amber" | "alarm"; height?: number; animate?: boolean }) {
  const bg = { volt: "bg-volt", data: "bg-data", amber: "bg-amber", alarm: "bg-alarm" }[tone];
  return (
    <div className="w-full overflow-hidden rounded-full bg-ink-700" style={{ height }}>
      <div className={`${animate ? "bar-grow " : ""}h-full rounded-full ${bg}`} style={{ width: `${Math.max(0, Math.min(100, (value / max) * 100))}%` }} />
    </div>
  );
}

export function confTone(band: string): "volt" | "data" | "amber" {
  return band === "HIGH" ? "volt" : band === "MODERATE" ? "data" : "amber";
}

export function Loading({ text = "Running the pipeline…" }: { text?: string }) {
  return <div className="panel panel-pad flex items-center gap-3 text-sm text-fog-400"><span className="h-2 w-2 rounded-full bg-volt live-dot" />{text}</div>;
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-alarm/50 bg-alarm/10 p-4 text-sm text-fog-100">
      <OctagonAlert className="mt-0.5 h-4 w-4 shrink-0 text-alarm" /> <div>{message}</div>
    </div>
  );
}

export function SafetyBanner({ alerts, status }: { alerts: Alert[]; status: string }) {
  if (!alerts.length) return null;
  const alarm = status === "ALARM";
  return (
    <div role="alert" className={`mb-5 rounded-lg border p-4 ${alarm ? "border-alarm bg-alarm/15" : "border-amber/60 bg-amber/10"}`}>
      <div className="flex items-center gap-2 font-display font-semibold">
        {alarm ? <OctagonAlert className="h-5 w-5 text-alarm" /> : <AlertTriangle className="h-5 w-5 text-amber" />}
        {alarm ? "Safety alert — stop test / inspect battery" : "Safety warning"}
      </div>
      <ul className="mt-2 space-y-1 text-sm">
        {alerts.slice(0, 4).map((a, i) => <li key={i}>{a.message} <span className="text-fog-400">{a.action}</span></li>)}
      </ul>
    </div>
  );
}

export function Disclaimer({ text }: { text: string }) {
  return (
    <p className="mt-10 flex items-start gap-2 border-t border-ink-700 pt-4 text-xs text-fog-500">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {text}
    </p>
  );
}

export function NeedsResult({ result, loading, error, children }: { result: Analysis | null; loading: boolean; error: string | null; children: (r: Analysis) => ReactNode }) {
  if (error) return <ErrorBox message={error} />;
  if (!result) return <Loading text={loading ? "Running the pipeline…" : "Choose a battery on Analyze to begin."} />;
  return <>{children(result)}</>;
}
