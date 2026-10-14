import { useState } from "react";
import { Activity, Atom, Cpu, Layers } from "lucide-react";
import { useAnalysis } from "../lib/store";
import { PageHead } from "../components/ui";
import LazyTwin from "../components/LazyTwin";
import { twinFromAnalysis } from "../lib/twin";
import { PathwayChip } from "../components/circular";

const KEY = "rebat.evmodel";

export default function Explorer() {
  const { result } = useAnalysis();
  const [model, setModel] = useState(() => { try { return localStorage.getItem(KEY) || "tesla_model3_lr"; } catch { return "tesla_model3_lr"; } });
  const pick = (id: string) => { setModel(id); try { localStorage.setItem(KEY, id); } catch { /* ignore */ } };
  const m = result?.measurements ?? {};
  return (
    <>
      <PageHead title="EV battery explorer · digital twin"
        sub="Open a real EV battery pack layer by layer: cover, cooling, busbars, modules, cells, BMS and frame. Tap any part to see what it does and which minerals it holds. The twin colours the cells with the AI's health estimate for the battery you are analysing."
        right={result ? <div className="flex items-center gap-2 text-sm text-fog-400">Twin data: <span className="font-semibold text-fog-100">{result.battery_id}</span><PathwayChip p={result.circular.pathway} /></div> : null} />
      <LazyTwin modelId={model} onModelChange={pick} twin={twinFromAnalysis(result)} height={600}
        live={{ voltage: result?.features.v_cell_mean != null ? Number(result.features.v_cell_mean) * result.meta.series_cells : null,
          current: m.i_mean != null ? Number(m.i_mean) : null, temperature: m.t_max != null ? Number(m.t_max) : null,
          soh: result?.soh.soh, rul: result?.rul.rul_cycles, label: result ? `${result.battery_id} · ${result.data_label.toLowerCase()} · cells coloured by SOH ${result.soh.soh.toFixed(1)}%` : undefined }} />
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {[[Layers, "Exploded view", "Six labelled layers from the top cover to the base frame, as in a real liquid-cooled EV pack. Switch between Tesla (cylindrical 2170), Nissan Leaf (pouch), Tata Nexon EV (LFP prismatic) and our 3-cell rig."],
          [Activity, "Digital twin", "The same model is driven by data: cell colours follow the AI's SOH and cell imbalance, the heat map follows the measured temperature, and current pulses follow the measured load current."],
          [Atom, "Future: minerals", "Each layer's material and every mineral in the cells, scaled to the chosen pack — the grams that go back into a new EV battery after recycling."]].map(([I, t, d]: any) => (
          <div key={t} className="panel panel-pad"><div className="flex items-center gap-2 font-display font-semibold"><I className="h-4 w-4 text-volt" />{t}</div><p className="mt-2 text-sm text-fog-400">{d}</p></div>
        ))}
      </div>
      <p className="mt-4 flex items-center gap-2 text-xs text-fog-500"><Cpu className="h-3.5 w-3.5" />3D layout is illustrative; pack figures are public numbers where available and estimates where marked.</p>
    </>
  );
}
