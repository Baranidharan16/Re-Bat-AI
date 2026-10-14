import { Link } from "react-router-dom";
import { useAnalysis } from "../lib/store";
import { fmt } from "../lib/api";
import Gauge from "../components/Gauge";
import { ParamGrid, PATHWAY_STYLE, PathwayIcon, ReuseIcon } from "../components/circular";
import LazyTwin from "../components/LazyTwin";
import { twinFromAnalysis } from "../lib/twin";
import { Grade, Meter, NeedsResult, PageHead, RiskChip, Stat, confTone } from "../components/ui";

export default function Overview() {
  const { result, loading, error } = useAnalysis();
  return (
    <NeedsResult result={result} loading={loading} error={error}>
      {(r) => {
        const top = r.router.ranking[0];
        const dec = r.router.decision;
        const fp = r.fingerprint;
        return (
          <>
            <PageHead title="Second-life battery intelligence" sub={r.demo?.story ?? `Source: ${r.data_label.toLowerCase()}`} />

            <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
              <div className="panel panel-pad flex flex-col items-center">
                <Gauge soh={r.soh.soh} lo={r.soh.lo} hi={r.soh.hi} />
                <div className="text-center text-xs text-fog-400">State of health · {r.soh.model_variant}</div>
              </div>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <Stat label="Remaining useful life" value={r.rul.capped ? `${fmt.int(r.rul.rul_cycles)}+` : fmt.int(r.rul.rul_cycles)} unit="cycles"
                  sub={`to ${r.rul.eol_soh}% SOH · ${fmt.int(r.rul.rul_p10)}–${fmt.int(r.rul.rul_p90)} (P10–P90) · prototype`} />
                <div className="panel panel-pad">
                  <div className="text-xs text-fog-400">Thermal risk</div>
                  <div className="mt-2"><RiskChip risk={fp.thermal_risk} /></div>
                  <div className="mt-2 text-xs text-fog-400">{fp.dimensions.thermal.display ?? "no temperature data"}</div>
                </div>
                <div className="panel panel-pad">
                  <div className="text-xs text-fog-400">Power capability</div>
                  <div className="mt-2"><Grade g={fp.power_capability} invert /></div>
                  <div className="mt-2 text-xs text-fog-400">{fp.dimensions.power.display ?? "needs a pulse test"}</div>
                </div>
                <div className="panel panel-pad">
                  <div className="text-xs text-fog-400">AI confidence</div>
                  <div className={`mt-1 font-display text-2xl font-semibold num ${confTone(r.confidence.band) === "volt" ? "text-volt" : confTone(r.confidence.band) === "data" ? "text-data" : "text-amber"}`}>{r.confidence.value.toFixed(0)}%</div>
                  <div className="mt-2"><Meter value={r.confidence.value} tone={confTone(r.confidence.band)} /></div>
                  <div className="mt-1 text-xs text-fog-400">{r.confidence.band.toLowerCase()}</div>
                </div>
                <Link to="/app/circular" className={`panel panel-pad block hover:bg-ink-800 sm:col-span-2 xl:col-span-4 ${PATHWAY_STYLE[r.circular.pathway].border}`}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className={`flex items-center gap-2 font-display text-2xl font-bold ${PATHWAY_STYLE[r.circular.pathway].text}`}><PathwayIcon p={r.circular.pathway} className="h-6 w-6" />{r.circular.headline}</div>
                    <span className="text-xs text-data">Reuse or recycle →</span>
                  </div>
                  <p className="mt-1 text-sm text-fog-300">{r.circular.reason}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {r.circular.reuse.options.map((o) => <span key={o.id} className={`chip border ${o.id === r.circular.reuse.best && r.circular.reuse.eligible ? "border-volt/50 text-volt" : "border-ink-600 text-fog-400"}`}><ReuseIcon id={o.id} className="h-3 w-3" />{o.name} {o.score.toFixed(0)}</span>)}
                    <span className="chip border border-data/40 text-data">Critical minerals {r.circular.recycle.totals.critical_recoverable_g.toFixed(1)} g</span>
                  </div>
                </Link>
                <div className="panel panel-pad sm:col-span-2 xl:col-span-4">
                  <div className="text-xs text-fog-400">Router decision (application match)</div>
                  <div className="mt-1 flex flex-wrap items-baseline gap-x-3">
                    <span className={`font-display text-2xl font-bold ${dec.kind === "second_life" ? "text-volt" : dec.kind === "safety" ? "text-alarm" : "text-amber"}`}>{dec.name}</span>
                    {dec.score !== null && <span className="num text-fog-400">{dec.score.toFixed(0)}/100</span>}
                  </div>
                  {dec.provisional && <div className="mt-1 text-sm text-fog-400">Provisional best match: {dec.provisional} — confirm with the recommended test first.</div>}
                  <div className="mt-1 text-xs text-fog-500">Screening context: {r.soh.screening.label} ({r.soh.screening.range}). {r.soh.screening.disclaimer}</div>
                </div>
              </div>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-[1.15fr_1fr]">
              <div>
                <div className="mb-2 flex items-center justify-between"><h2 className="h-section">Digital twin</h2><Link to="/app/explorer" className="text-xs text-data hover:underline">Open 3D explorer</Link></div>
                <LazyTwin modelId="nissan_leaf_40" compact height={380} initialTab="monitoring" twin={twinFromAnalysis(r)} />
              </div>
              <div className="panel panel-pad">
                <div className="flex items-center justify-between"><h2 className="h-section">Measured parameters</h2><Link to="/app/circular" className="text-xs text-data hover:underline">Recommendation</Link></div>
                <div className="mt-3"><ParamGrid params={r.circular.parameters} compact /></div>
                <p className="mt-3 text-xs text-fog-500">The 3D pack is coloured by this battery's SOH and cell imbalance (green = healthy, red = weak). {r.passport_block ? `Sealed in ledger block #${r.passport_block.idx}.` : r.ledger ? `Sealed in ledger block #${r.ledger.idx}.` : ""}</p>
              </div>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-3">
              <div className="panel panel-pad">
                <div className="flex items-center justify-between"><h2 className="h-section">Battery fingerprint</h2><Link to="/app/fingerprint" className="text-xs text-data hover:underline">Details</Link></div>
                <dl className="mt-4 space-y-3 text-sm">
                  {[["Capacity", fp.summary.capacity, false], ["Resistance", fp.summary.resistance, false], ["Thermal", fp.summary.thermal, false],
                    ["Power", fp.summary.power, true], ["Degradation", fp.summary.degradation, false]].map(([k, g, inv]) => (
                    <div key={k as string} className="flex items-center justify-between"><dt className="text-fog-300">{k}</dt><dd><Grade g={g as string} invert={inv as boolean} /></dd></div>
                  ))}
                </dl>
              </div>

              <div className="panel panel-pad">
                <div className="flex items-center justify-between"><h2 className="h-section">Second-life ranking</h2><Link to="/app/router" className="text-xs text-data hover:underline">Router</Link></div>
                <ol className="mt-4 space-y-3">
                  {r.router.ranking.slice(0, 5).map((a, i) => (
                    <li key={a.id}>
                      <div className="flex justify-between text-sm"><span className={i === 0 ? "text-volt" : "text-fog-300"}><span className="num mr-2 text-fog-500">{i + 1}</span>{a.short}</span><span className="num">{a.score.toFixed(0)}</span></div>
                      <div className="mt-1"><Meter value={a.score} tone={a.status === "Excluded" ? "alarm" : i === 0 ? "volt" : "data"} height={4} /></div>
                    </li>
                  ))}
                </ol>
              </div>

              <div className="panel panel-pad">
                <div className="flex items-center justify-between"><h2 className="h-section">Why {top.short.toLowerCase()}?</h2><Link to="/app/explain" className="text-xs text-data hover:underline">Explain</Link></div>
                <ul className="mt-4 space-y-2 text-sm">
                  {top.reasons_for.slice(0, 4).map((x) => <li key={x} className="flex gap-2"><span className="text-volt">+</span>{x}</li>)}
                  {top.reasons_against.slice(0, 2).map((x) => <li key={x} className="flex gap-2 text-fog-400"><span className="text-amber">−</span>{x}</li>)}
                </ul>
                <div className="mt-5 border-t border-ink-700 pt-4 text-sm">
                  {r.adaptive.recommended
                    ? <>Next test: <Link to="/app/diagnostics" className="text-volt hover:underline">{r.adaptive.recommended.name}</Link><div className="mt-1 text-xs text-fog-400">{r.adaptive.recommended.reason}</div></>
                    : <span className="text-fog-400">{r.adaptive.message}</span>}
                </div>
              </div>
            </div>
          </>
        );
      }}
    </NeedsResult>
  );
}
