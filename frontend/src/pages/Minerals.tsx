import { useEffect, useState } from "react";
import { ArrowDown, Recycle } from "lucide-react";
import { useAnalysis } from "../lib/store";
import { api, fmt, type MineralReport } from "../lib/api";
import { ErrorBox, NeedsResult, PageHead } from "../components/ui";
import { CompositionBar, ElementTile, LoopStrip, PathwayChip } from "../components/circular";

export default function Minerals() {
  const { result, loading, error } = useAnalysis();
  const [cfg, setCfg] = useState<any>(null);
  const [chem, setChem] = useState<string | null>(null);
  const [fmtId, setFmtId] = useState<string | null>(null);
  const [alt, setAlt] = useState<MineralReport | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => { api.circularConfig().then(setCfg).catch((e) => setErr(e.message)); }, []);
  useEffect(() => {
    if (!result || !chem || !fmtId) { setAlt(null); return; }
    if (chem === result.circular.pack.chemistry && fmtId === result.circular.pack.cell_format) { setAlt(null); return; }
    api.minerals({ series_cells: result.meta.series_cells, nominal_capacity_ah: result.meta.nominal_capacity_ah, chemistry: chem, cell_format: fmtId })
      .then(setAlt).catch((e) => setErr(e.message));
  }, [chem, fmtId, result]);

  async function useForRig() {
    if (!chem || !fmtId) return;
    try { await api.setPack({ chemistry: chem, cell_format: fmtId }); setSaved("Saved — new analyses and the live rig use this chemistry."); }
    catch (e: any) { setErr(e.message); }
  }

  return (
    <NeedsResult result={result} loading={loading} error={error}>
      {(r) => {
        const m = alt ?? r.circular.recycle;
        const curChem = chem ?? r.circular.pack.chemistry, curFmt = fmtId ?? r.circular.pack.cell_format;
        const critical = m.materials.filter((x) => x.critical);
        const others = m.materials.filter((x) => !x.critical);
        return (
          <>
            <PageHead title="Battery minerals" sub="Every material inside this battery, how much of it can be recovered, and where it goes in a new EV cell. Recovering these at home cuts India's import dependence for lithium, nickel, cobalt, manganese and graphite."
              right={<PathwayChip p={r.circular.pathway} />} />
            {err && <div className="mb-4"><ErrorBox message={err} /></div>}

            <section className="panel panel-pad">
              <div className="grid gap-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
                <div><label className="label" htmlFor="chem">Chemistry</label>
                  <select id="chem" className="input" value={curChem} onChange={(e) => { setChem(e.target.value); setFmtId(curFmt); setSaved(null); }}>
                    {cfg && Object.entries(cfg.chemistries).map(([k, v]) => <option key={k} value={k}>{v as string}</option>)}
                  </select></div>
                <div><label className="label" htmlFor="fmt">Cell format</label>
                  <select id="fmt" className="input" value={curFmt} onChange={(e) => { setFmtId(e.target.value); setChem(curChem); setSaved(null); }}>
                    {cfg && Object.entries(cfg.cell_formats).map(([k, v]: [string, any]) => <option key={k} value={k}>{v.label} · {v.cell_mass_g} g · {v.cell_ah} Ah</option>)}
                  </select></div>
                <button className="btn-ghost" onClick={useForRig} disabled={!alt}>Use for this rig</button>
              </div>
              {saved && <p className="mt-2 text-xs text-volt">{saved}</p>}
              {alt && <p className="mt-2 text-xs text-amber">Showing a what-if for {alt.chemistry_label}. The AI analysis used {r.circular.pack.chemistry_label}.</p>}

              <div className="mt-6 grid gap-6 lg:grid-cols-4">
                <div><div className="text-xs text-fog-400">Pack</div><div className="num font-display text-2xl font-bold">{fmt.n(m.pack_mass_g, 0)} g</div><div className="text-xs text-fog-400">{m.n_cells} cells ({m.cells_series}S{m.cells_parallel}P) · {m.cell_format_label}</div></div>
                <div><div className="text-xs text-fog-400">Recoverable materials</div><div className="num font-display text-2xl font-bold text-data">{fmt.n(m.totals.recoverable_g, 1)} g</div><div className="text-xs text-fog-400">{m.totals.recoverable_pct_of_pack}% of the pack · {m.totals.yield_pct_of_recovered_materials}% yield</div></div>
                <div><div className="text-xs text-fog-400">Critical minerals recovered</div><div className="num font-display text-2xl font-bold text-amber">{fmt.n(m.totals.critical_recoverable_g, 1)} g</div><div className="text-xs text-fog-400">of {fmt.n(m.totals.critical_contained_g, 1)} g contained</div></div>
                <div><div className="text-xs text-fog-400">Lithium carbonate equivalent</div><div className="num font-display text-2xl font-bold text-volt">{fmt.n(m.totals.lithium_carbonate_equivalent_g, 1)} g</div><div className="text-xs text-fog-400">battery-grade lithium salt</div></div>
              </div>
              <div className="mt-6"><CompositionBar m={m} height={34} /></div>
            </section>

            <h2 className="h-section mt-8">Critical minerals</h2>
            <p className="mt-1 text-sm text-fog-400">The materials India imports for EV batteries, mostly refined in China.</p>
            <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{critical.map((x) => <ElementTile key={x.symbol} x={x} highlight />)}</div>

            <h2 className="h-section mt-8">Other recovered materials</h2>
            <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{others.map((x) => <ElementTile key={x.symbol} x={x} />)}</div>

            <section className="mt-8 grid gap-4 lg:grid-cols-[1fr_1.1fr]">
              <div className="panel panel-pad">
                <h2 className="h-section flex items-center gap-2"><Recycle className="h-5 w-5 text-data" />How the minerals come out</h2>
                <ol className="mt-4 space-y-0">
                  {m.process.map((p, i) => (
                    <li key={p.step}>
                      <div className="flex gap-3">
                        <span className="num flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-data/50 text-xs text-data">{i + 1}</span>
                        <div><div className="font-medium">{p.step}</div><div className="text-sm text-fog-400">{p.detail}</div></div>
                      </div>
                      {i < m.process.length - 1 && <ArrowDown className="my-1 ml-1.5 h-4 w-4 text-ink-600" aria-hidden />}
                    </li>
                  ))}
                </ol>
              </div>
              <div className="panel panel-pad">
                <h2 className="h-section">Closed loop: back into a new EV battery</h2>
                <div className="mt-4 flex items-baseline gap-3">
                  <span className="num font-display text-5xl font-bold text-volt">{fmt.n(m.closed_loop.new_cells_equivalent, 1)}</span>
                  <span className="text-fog-300">new cells' worth of cathode metals from {m.n_cells} old cells</span>
                </div>
                <p className="mt-2 text-sm text-fog-400">{m.closed_loop.statement}</p>
                <div className="mt-5"><LoopStrip steps={r.circular.loop.steps} current={r.circular.pathway === "RECYCLE" ? 6 : r.circular.loop.current} compact /></div>
                <p className="mt-5 border-t border-ink-700 pt-4 text-xs text-fog-400">{m.policy}</p>
                <p className="mt-2 text-xs text-fog-500">{m.note}</p>
              </div>
            </section>
          </>
        );
      }}
    </NeedsResult>
  );
}
