import { Link } from "react-router-dom";
import { Recycle, RotateCcw } from "lucide-react";
import { useAnalysis } from "../lib/store";
import { fmt } from "../lib/api";
import { Meter, NeedsResult, PageHead } from "../components/ui";
import { CompositionBar, LoopStrip, ParamGrid, PATHWAY_STYLE, PathwayIcon, ReuseIcon, sizingLines } from "../components/circular";

const STATUS_TONE: Record<string, string> = {
  "Highly suitable": "text-volt", Suitable: "text-data", "Conditional — validate": "text-amber", "Not recommended": "text-fog-500", Excluded: "text-alarm",
};

export default function Circular() {
  const { result, loading, error } = useAnalysis();
  return (
    <NeedsResult result={result} loading={loading} error={error}>
      {(r) => {
        const c = r.circular;
        const st = PATHWAY_STYLE[c.pathway];
        const best = c.reuse.options.find((o) => o.id === c.reuse.best)!;
        const rec = c.recycle;
        const crit = rec.materials.filter((m) => m.critical && m.symbol !== "C");
        return (
          <>
            <PageHead title="Reuse recommendation" sub="Ten measurements from the ESP32 rig go into the XGBoost model, which estimates SOH and RUL. The router then scores solar storage, factory backup, household backup and a rural street light. A battery too weak for any of them goes to recycling, so its minerals end up in a new EV battery." />

            <section className={`panel relative overflow-hidden ${st.border}`}>
              <div className={`absolute inset-y-0 left-0 w-1 ${c.pathway === "REUSE" ? "bg-volt" : c.pathway === "RECYCLE" ? "bg-data" : c.pathway === "RETEST" ? "bg-amber" : "bg-alarm"}`} aria-hidden />
              <div className="grid gap-6 p-6 lg:grid-cols-[1.2fr_1fr]">
                <div>
                  <div className={`flex items-center gap-2 text-xs ${st.text}`}><PathwayIcon p={c.pathway} className="h-4 w-4" /> AI pathway decision</div>
                  <h2 className={`mt-1 font-display-tight text-3xl font-bold sm:text-4xl ${st.text}`}>{c.headline}</h2>
                  <p className="mt-3 max-w-xl text-fog-300">{c.reason}</p>
                  <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm text-fog-400">
                    <span>SOH <span className="num font-semibold text-fog-100">{r.soh.soh.toFixed(1)}%</span> ({r.soh.lo.toFixed(1)}–{r.soh.hi.toFixed(1)})</span>
                    <span>RUL <span className="num font-semibold text-fog-100">{r.rul.capped ? `${fmt.int(r.rul.rul_cycles)}+` : fmt.int(r.rul.rul_cycles)}</span> cycles</span>
                    <span>Confidence <span className="num font-semibold text-fog-100">{r.confidence.value.toFixed(0)}%</span></span>
                    <span>{c.pack.chemistry_label} · {c.pack.n_cells} × {c.pack.cell_format_label}</span>
                  </div>
                  {c.pathway === "RETEST" && <Link to="/app/diagnostics" className="btn-ghost mt-4">See the recommended test</Link>}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className={`rounded-lg border p-4 ${c.pathway === "REUSE" || c.pathway === "RETEST" ? "border-volt/60 bg-volt/5" : "border-ink-600 opacity-70"}`}>
                    <div className="flex items-center gap-2 text-sm text-volt"><RotateCcw className="h-4 w-4" />Reuse</div>
                    <div className="mt-2 font-display text-lg font-semibold">{best.name}</div>
                    <div className="num mt-1 text-3xl font-bold">{best.score.toFixed(0)}<span className="ml-1 text-sm font-normal text-fog-400">/100</span></div>
                    <div className="mt-2"><Meter value={best.score} height={4} /></div>
                    <div className="mt-2 text-2xs text-fog-400">best of 4 reuse applications</div>
                  </div>
                  <div className={`rounded-lg border p-4 ${c.pathway === "RECYCLE" ? "border-data/60 bg-data/5" : "border-ink-600"}`}>
                    <div className="flex items-center gap-2 text-sm text-data"><Recycle className="h-4 w-4" />Recycle</div>
                    <div className="mt-2 font-display text-lg font-semibold">{fmt.n(rec.totals.critical_recoverable_g, 1)} g critical minerals</div>
                    <div className="mt-1 text-sm text-fog-300">{crit.map((m) => `${m.symbol} ${fmt.n(m.recoverable_g, 1)} g`).join(" · ")}</div>
                    <div className="mt-2 text-2xs text-fog-400">{c.pathway === "RECYCLE" ? "recommended now" : "available at end of life"} · <Link to="/app/minerals" className="text-data hover:underline">all minerals</Link></div>
                  </div>
                </div>
              </div>
              <div className="border-t border-ink-700 px-6 py-4"><LoopStrip steps={c.loop.steps} current={c.loop.current} /></div>
            </section>

            <section className="panel panel-pad mt-4">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div><h2 className="h-section">1 · Measured by the hardware</h2><p className="text-xs text-fog-400">Each value is graded for second-life use: good · watch · poor. Hover for what it means.</p></div>
                <div className="flex gap-6 text-sm">
                  <div><div className="text-2xs text-fog-400">2 · AI: SOH</div><div className="num font-display text-2xl font-bold">{c.ai.soh.toFixed(1)}%</div></div>
                  <div><div className="text-2xs text-fog-400">AI: RUL</div><div className="num font-display text-2xl font-bold">{fmt.int(c.ai.rul_cycles)}<span className="ml-1 text-xs font-normal text-fog-400">cycles</span></div></div>
                  <div><div className="text-2xs text-fog-400">Confidence</div><div className="num font-display text-2xl font-bold">{c.ai.confidence.toFixed(0)}%</div></div>
                </div>
              </div>
              <div className="mt-4"><ParamGrid params={c.parameters} /></div>
              <p className="mt-3 text-xs text-fog-500">What each application needs most — solar: long RUL + high efficiency · factory backup: low resistance (peak power) + cool running · household: safe thermal behaviour + capacity · street light: any healthy capacity, low power.</p>
            </section>

            <div className="mt-6 flex items-end justify-between gap-4">
              <h2 className="h-section">3 · Reuse applications, scored and sized</h2>
              <span className="text-xs text-fog-400">Usable energy {fmt.n(c.reuse.energy.usable_wh, 1)} Wh = {fmt.n(c.reuse.energy.capacity_ah, 2)} Ah × {fmt.n(c.reuse.energy.nominal_v, 1)} V × {c.reuse.energy.depth_of_discharge} DoD × {fmt.n(c.reuse.energy.efficiency, 2)} efficiency</span>
            </div>
            <div className="mt-3 grid gap-4 md:grid-cols-2">
              {c.reuse.options.map((o, i) => (
                <section key={o.id} className={`panel panel-pad ${i === 0 && c.reuse.eligible ? "border-volt/50" : ""}`}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-center gap-3">
                      <span className={`flex h-10 w-10 items-center justify-center rounded-md ${i === 0 && c.reuse.eligible ? "bg-volt/15 text-volt" : "bg-ink-700 text-fog-300"}`}><ReuseIcon id={o.id} /></span>
                      <div>
                        <h3 className="font-display text-lg font-semibold">{o.name}</h3>
                        <div className={`text-2xs ${STATUS_TONE[o.status] ?? "text-fog-400"}`}>{o.status}{o.router_match && o.router_match !== o.name ? ` · scored as ${o.router_match}` : ""}</div>
                      </div>
                    </div>
                    <div className="num font-display text-3xl font-bold">{o.score.toFixed(0)}</div>
                  </div>
                  <div className="mt-3"><Meter value={o.score} tone={i === 0 && c.reuse.eligible ? "volt" : o.score < 50 ? "amber" : "data"} height={5} /></div>
                  <p className="mt-3 text-sm text-fog-400">{o.description}</p>
                  <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                    {sizingLines(o).map(([k, v]) => (<div key={k}><dt className="text-2xs text-fog-500">{k}</dt><dd className="num text-fog-100">{v}</dd></div>))}
                  </dl>
                  {(o.reasons_for.length > 0 || o.reasons_against.length > 0) && (
                    <ul className="mt-4 space-y-1 border-t border-ink-700 pt-3 text-xs">
                      {o.reasons_for.slice(0, 2).map((x) => <li key={x}><span className="text-volt">+ </span>{x}</li>)}
                      {o.reasons_against.slice(0, 2).map((x) => <li key={x} className="text-fog-400"><span className="text-amber">− </span>{x}</li>)}
                    </ul>
                  )}
                  <p className="mt-3 text-2xs text-fog-500">{o.formula}</p>
                </section>
              ))}
            </div>

            <section className="panel panel-pad mt-6">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="h-section">What this battery is made of</h2>
                  <p className="mt-1 text-sm text-fog-400">{rec.n_cells} cells · {fmt.n(rec.pack_mass_g, 0)} g · {rec.chemistry_label}. {rec.closed_loop.statement}</p>
                </div>
                <Link to="/app/minerals" className="btn-ghost">Mineral breakdown</Link>
              </div>
              <div className="mt-4"><CompositionBar m={rec} /></div>
              <p className="mt-3 text-xs text-fog-500">{rec.policy}</p>
            </section>
          </>
        );
      }}
    </NeedsResult>
  );
}
