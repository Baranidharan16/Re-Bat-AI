import { ArrowRight, Factory, FlaskConical, House, Lightbulb, Recycle, RotateCcw, ShieldAlert, Sun } from "lucide-react";
import type { Mineral, MineralReport, Pathway, ReuseOption } from "../lib/api";
import { fmt } from "../lib/api";

export const PATHWAY_STYLE: Record<Pathway, { text: string; border: string; bg: string; label: string }> = {
  REUSE: { text: "text-volt", border: "border-volt/50", bg: "bg-volt/10", label: "Reuse" },
  RECYCLE: { text: "text-data", border: "border-data/50", bg: "bg-data/10", label: "Recycle" },
  RETEST: { text: "text-amber", border: "border-amber/50", bg: "bg-amber/10", label: "Retest first" },
  HOLD: { text: "text-alarm", border: "border-alarm/60", bg: "bg-alarm/10", label: "Safety hold" },
};

export function PathwayIcon({ p, className = "h-5 w-5" }: { p: Pathway; className?: string }) {
  const I = p === "REUSE" ? RotateCcw : p === "RECYCLE" ? Recycle : p === "RETEST" ? FlaskConical : ShieldAlert;
  return <I className={className} aria-hidden />;
}

export function PathwayChip({ p }: { p: Pathway }) {
  const s = PATHWAY_STYLE[p];
  return <span className={`chip border ${s.border} ${s.bg} ${s.text}`}><PathwayIcon p={p} className="h-3 w-3" />{s.label}</span>;
}

export function ReuseIcon({ id, className = "h-5 w-5" }: { id: ReuseOption["id"]; className?: string }) {
  const I = id === "solar_storage" ? Sun : id === "factory_backup" ? Factory : id === "household_backup" ? House : Lightbulb;
  return <I className={className} aria-hidden />;
}

/** The closed loop: EV → test → second life → recycle → minerals → new EV cell → back to EV. */
export function LoopStrip({ steps, current, compact }: { steps: string[]; current: number; compact?: boolean }) {
  return (
    <div>
      <ol className="flex flex-wrap items-center gap-y-2">
        {steps.map((s, i) => {
          const done = i < current, now = i === current;
          return (
            <li key={s} className="flex items-center">
              <span className={`rounded-md border px-2.5 py-1.5 ${compact ? "text-2xs" : "text-xs"} ${now ? "border-volt bg-volt text-ink-950 font-semibold" : done ? "border-volt/40 text-volt" : "border-ink-600 text-fog-400"}`}>
                {s}
              </span>
              {i < steps.length - 1 && <ArrowRight className={`mx-1 h-3.5 w-3.5 ${i < current ? "text-volt/70" : "text-ink-600"}`} aria-hidden />}
            </li>
          );
        })}
      </ol>
      <div className="mt-2 flex items-center gap-2 text-2xs text-fog-500"><RotateCcw className="h-3 w-3" aria-hidden />New EV cell goes back into a vehicle — the loop closes.</div>
    </div>
  );
}

/** Whole-battery composition: every material as a share of pack mass. */
export function CompositionBar({ m, height = 28 }: { m: MineralReport; height?: number }) {
  const parts = [...m.materials.map((x) => ({ key: x.symbol, name: x.name, color: x.color, share: x.share_pct, g: x.contained_g, rec: true })),
    ...m.non_recovered.map((x) => ({ key: x.key, name: x.name, color: x.color, share: x.share_pct, g: x.contained_g, rec: false }))];
  return (
    <div>
      <div className="flex w-full overflow-hidden rounded-md border border-ink-600" style={{ height }} role="img"
        aria-label={`Battery composition: ${parts.map((p) => `${p.name} ${p.share.toFixed(1)}%`).join(", ")}`}>
        {parts.map((p) => (
          <div key={p.key} className="bar-grow relative h-full" title={`${p.name}: ${p.share.toFixed(1)} % · ${fmt.n(p.g, 1)} g`}
            style={{ width: `${p.share}%`, background: p.color, backgroundImage: p.rec ? undefined : "repeating-linear-gradient(135deg, rgba(255,255,255,.06) 0 4px, transparent 4px 8px)" }}>
            {p.share > 6 && <span className={`absolute inset-0 flex items-center justify-center text-2xs font-semibold ${p.rec ? "text-ink-950" : "text-fog-300"}`}>{p.rec ? p.key : ""}</span>}
          </div>
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-2xs text-fog-400">
        {parts.map((p) => (
          <li key={p.key} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: p.color }} />{p.name} <span className="num text-fog-300">{p.share.toFixed(1)}%</span>{!p.rec && <span className="text-fog-500">(not recovered)</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Periodic-table style tile for one material. */
export function ElementTile({ x, highlight }: { x: Mineral; highlight?: boolean }) {
  return (
    <div className={`panel flex flex-col p-4 ${highlight ? "border-data/60" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-md border-2" style={{ borderColor: x.color }}>
          <span className="font-display-tight text-2xl font-bold leading-none" style={{ color: x.color }}>{x.symbol}</span>
          <span className="mt-0.5 text-[8px] uppercase text-fog-400">{x.name}</span>
        </div>
        <div className="text-right">
          <div className="num font-display text-2xl font-bold">{fmt.n(x.recoverable_g, x.recoverable_g < 10 ? 2 : 1)}<span className="ml-1 text-xs font-normal text-fog-400">g</span></div>
          <div className="text-2xs text-fog-400">recoverable of {fmt.n(x.contained_g, 1)} g · {(x.recovery_rate * 100).toFixed(0)}% yield</div>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="chip border border-ink-600 text-fog-300">{x.part}</span>
        {x.critical && <span className="chip border border-amber/50 bg-amber/10 text-amber">critical mineral</span>}
        <span className="chip border border-ink-600 text-fog-400 num">{x.share_pct.toFixed(1)}% of pack</span>
      </div>
      <p className="mt-3 text-sm text-fog-300">{x.role}.</p>
      <dl className="mt-3 space-y-1.5 border-t border-ink-700 pt-3 text-xs">
        <div className="flex gap-2"><dt className="w-24 shrink-0 text-fog-500">Recovered as</dt><dd className="text-fog-300">{x.recovered_as}</dd></div>
        <div className="flex gap-2"><dt className="w-24 shrink-0 text-fog-500">Goes back into</dt><dd className="text-volt">{x.new_battery_use}</dd></div>
        <div className="flex gap-2"><dt className="w-24 shrink-0 text-fog-500">India supply</dt><dd className="text-fog-400">{x.india}</dd></div>
      </dl>
    </div>
  );
}

/** Key sizing numbers for a reuse option, in plain words. */
export function sizingLines(o: ReuseOption): [string, string][] {
  const z = o.sizing as Record<string, any>;
  switch (o.id) {
    case "solar_storage":
      return [["Stores per day", `${fmt.n(z.usable_wh, 1)} Wh`], ["Solar panel", `${z.panel_w_standard} W (needs ${fmt.n(z.panel_w, 1)} W)`],
        [`Home load ${z.home_daily_wh} Wh/day`, `${fmt.n(z.autonomy_days, 2)} days · ${z.modules_for_one_day} module(s) for 1 day`],
        ["Life at 1 cycle/day", `≈ ${fmt.n(z.years_at_one_cycle_per_day, 1)} years`], ["Charge setting", String(z.charge_setting)]];
    case "factory_backup":
      return [["Usable energy", `${fmt.n(z.usable_wh, 1)} Wh`], [`Runtime at ${z.load_w} W`, `${fmt.n(z.runtime_min_at_load, 1)} min`],
        [`For ${z.target_minutes} min at ${z.load_w} W`, `${z.modules_for_target} module(s)`], ["Peak power", z.peak_power_w ? `${fmt.int(z.peak_power_w)} W` : "needs pulse test"]];
    case "household_backup":
      return [["Usable energy", `${fmt.n(z.usable_wh, 1)} Wh`], [`Fan + lights (${z.load_w} W)`, `${fmt.n(z.runtime_h_at_load, 2)} h`],
        [`For a ${z.target_hours} h power cut`, `${z.modules_for_target} module(s)`]];
    default:
      return [["Usable energy", `${fmt.n(z.usable_wh, 1)} Wh`], [`${z.lamp_w} W lamp, always on`, `${fmt.n(z.nights_always_on, 2)} nights`],
        ["Smart LDR + PIR", `${fmt.n(z.nights_smart, 2)} nights`], ["Hours of light", `${fmt.n(z.hours_of_light, 1)} h`]];
  }
}

const GRADE_CLS: Record<string, string> = {
  good: "border-volt/40 text-volt", watch: "border-amber/50 text-amber", poor: "border-alarm/60 text-alarm", "not measured": "border-ink-600 text-fog-500",
};

/** The 8–10 hardware measurements behind the recommendation, graded for second-life use. */
export function ParamGrid({ params, compact }: { params: import("../lib/api").Param[]; compact?: boolean }) {
  return (
    <div className={`grid gap-2.5 ${compact ? "grid-cols-2 xl:grid-cols-3" : "grid-cols-2 md:grid-cols-5"}`}>
      {params.map((p) => (
        <div key={p.id} className="rounded-md border border-ink-700 bg-ink-900/40 px-3 py-2.5" title={p.note}>
          <div className="truncate text-2xs text-fog-400">{p.name}</div>
          <div className="mt-0.5 flex items-baseline justify-between gap-2">
            <span className="num font-display text-lg font-semibold">{p.value == null ? "—" : typeof p.value === "number" ? fmt.n(p.value, Math.abs(p.value) >= 100 ? 0 : p.value < 10 ? 2 : 1) : p.value}<span className="ml-1 text-xs font-normal text-fog-400">{p.unit}</span></span>
            <span className={`chip shrink-0 border px-1.5 py-0 text-[10px] ${GRADE_CLS[p.grade] ?? GRADE_CLS["not measured"]}`}>{p.grade}</span>
          </div>
          {!compact && <div className="mt-0.5 text-[10px] leading-tight text-fog-500">{p.sensor}</div>}
        </div>
      ))}
    </div>
  );
}
