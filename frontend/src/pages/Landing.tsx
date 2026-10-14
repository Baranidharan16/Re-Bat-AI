import { useEffect, useState } from "react";
import LazyTwin from "../components/LazyTwin";
import { useAnalysis } from "../lib/store";
import { twinFromAnalysis } from "../lib/twin";
import { Link } from "react-router-dom";
import { api, type Analysis } from "../lib/api";
import { Logo } from "../components/Shell";
import { DataBadge, Meter } from "../components/ui";
import { LoopStrip, PathwayChip, ReuseIcon } from "../components/circular";

const FLOW = [
  ["Measure", "The ESP32 rig streams voltage, current, temperature, gas and cell taps over a WebSocket."],
  ["Predict", "XGBoost estimates SOH with a calibrated interval and forecasts remaining useful life."],
  ["Fingerprint", "Resistance, heat under load, power, efficiency, imbalance and ageing rate join the health number."],
  ["Reuse", "Healthy packs are matched to solar storage, factory or home backup, or a rural street light — and sized."],
  ["Recycle", "Weak packs go to material recovery: every mineral is counted and sent back into new EV cells."],
  ["Seal", "Each test is hashed into the ledger — a forensic battery passport from first test to recycling."],
];
const REUSE = [
  ["solar_storage", "Solar energy storage", "Daytime sun for the evening"],
  ["factory_backup", "Factory / industrial backup", "Machines keep running in a power cut"],
  ["household_backup", "Household backup", "Fans and lights during outages"],
  ["street_light", "Rural street light", "Dusk-to-dawn light, LDR + PIR"],
] as const;
const MINERALS = [["Li", "Lithium", "#B6F23A"], ["Ni", "Nickel", "#4FC3E0"], ["Co", "Cobalt", "#7B8CFF"], ["Mn", "Manganese", "#C792EA"], ["C", "Graphite", "#9AA6BD"], ["Cu", "Copper", "#E39B5B"], ["Al", "Aluminium", "#D7DEE8"]];

export default function Landing() {
  const { result } = useAnalysis();
  const [ev, setEv] = useState("tesla_model3_lr");
  const [cmp, setCmp] = useState<Analysis[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    Promise.all(["RB-B02", "RB-C03", "RB-F06"].map(api.demo)).then(setCmp).catch((e) => setErr(e.message));
  }, []);

  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
        <Logo />
        <nav className="flex items-center gap-5 text-sm text-fog-400">
          <Link to="/app/model" className="hover:text-fog-100">AI engine</Link>
          <Link to="/app/live" className="hover:text-fog-100">Live rig</Link>
          <Link to="/app/live" className="btn-ghost">Live ESP32</Link>
          <Link to="/app/analyze" className="btn-primary">Analyze battery</Link>
        </nav>
      </header>

      <section className="mx-auto grid max-w-7xl gap-12 px-6 pb-20 pt-10 lg:grid-cols-[1.05fr_1fr] lg:pt-16">
        <div>
          <h1 className="font-display-tight text-5xl font-extrabold leading-[0.95] sm:text-7xl">
            From battery health<br />to second life.
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-fog-300">
            An AI-powered battery intelligence platform that predicts health, forecasts degradation and decides each retired
            EV battery's future: <span className="text-volt">reuse</span> it for solar, backup power or rural street lights — or
            <span className="text-data"> recycle</span> it so its lithium, nickel and cobalt go back into a new EV battery.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/app/analyze" className="btn-primary px-5 py-2.5">Analyze battery</Link>
            <Link to="/app/live" className="btn-ghost px-5 py-2.5">Open live ESP32 data</Link>
          </div>
          <p className="mt-10 max-w-md text-sm text-fog-400">
            Test. Predict. Reuse or recycle. Repeat. When the AI is uncertain, it doesn't guess — it asks for the next diagnostic test.
          </p>
        </div>

        <div className="panel overflow-hidden">
          <div className="flex items-center justify-between border-b border-ink-700 px-5 py-3">
            <div>
              <div className="font-display font-semibold">Three retired modules, three futures</div>
              <div className="text-xs text-fog-400">Decided by the live engine: reuse where it fits, recycle when it doesn't</div>
            </div>
            <DataBadge label="DEMO · SIMULATED" />
          </div>
          {err && <div className="p-5 text-sm text-alarm">{err}</div>}
          {!cmp && !err && <div className="p-5 text-sm text-fog-400">Running three batteries through the pipeline…</div>}
          {cmp?.map((a) => {
            const c = a.circular;
            const best = c.reuse.options.find((o) => o.id === c.reuse.best)!;
            return (
              <Link to="/app/circular" key={a.battery_id} className="block border-b border-ink-700 px-5 py-4 last:border-0 hover:bg-ink-800">
                <div className="flex items-baseline justify-between gap-4">
                  <div className="flex items-center gap-2">
                    <span className="font-display font-semibold">{a.demo?.label}</span>
                    <span className="text-sm text-fog-400">{a.demo?.title.toLowerCase()}</span>
                  </div>
                  <div className="num text-sm">SOH <span className="font-display text-xl font-bold">{a.soh.soh.toFixed(1)}%</span></div>
                </div>
                <div className="mt-2 flex items-center gap-2"><PathwayChip p={c.pathway} />
                  <span className={`text-sm ${c.pathway === "RECYCLE" ? "text-data" : "text-volt"}`}>{c.pathway === "RECYCLE" ? `${c.recycle.totals.critical_recoverable_g.toFixed(1)} g of Li, Ni, Co, Mn, graphite back into new cells` : best.name}</span>
                </div>
                {c.pathway === "RECYCLE" ? (
                  <div className="mt-3 flex h-2 overflow-hidden rounded-full">{c.recycle.materials.map((m) => <div key={m.symbol} style={{ width: `${m.share_pct}%`, background: m.color }} />)}<div className="flex-1 bg-ink-700" /></div>
                ) : (
                  <div className="mt-3 grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1"><Meter value={best.score} /><span className="num text-sm text-fog-300">{best.score.toFixed(0)}</span></div>
                )}
              </Link>
            );
          })}
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 pb-16">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="font-display-tight text-4xl font-extrabold">Inside an EV battery.</h2>
            <p className="mt-2 max-w-2xl text-fog-400">Tap the pack to explode it into its layers, open a module, cut a cell in half, watch current and coolant flow, and see every mineral it holds — a live digital twin of the battery on our rig.</p>
          </div>
          <Link to="/app/explorer" className="btn-ghost">Open full explorer</Link>
        </div>
        <LazyTwin modelId={ev} onModelChange={setEv} twin={twinFromAnalysis(result)} height={540} />
      </section>

      <section className="border-y border-ink-700 bg-ink-950">
        <div className="mx-auto max-w-7xl px-6 py-14">
          <h2 className="font-display text-2xl font-bold">How a battery is routed</h2>
          <ol className="mt-8 grid gap-px overflow-hidden rounded-lg border border-ink-700 bg-ink-700 sm:grid-cols-2 lg:grid-cols-6">
            {FLOW.map(([t, d], i) => (
              <li key={t} className="bg-ink-950 p-5">
                <div className="flex items-center gap-2 text-xs text-fog-500"><span className="num">{i + 1}</span>{i < FLOW.length - 1 && <span aria-hidden className="h-px flex-1 bg-ink-600" />}</div>
                <div className="mt-3 font-display text-lg font-semibold">{t}</div>
                <p className="mt-2 text-sm leading-relaxed text-fog-400">{d}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 py-16">
        <h2 className="font-display-tight text-4xl font-extrabold">Reuse. Recycle. Repeat.</h2>
        <div className="mt-8 grid gap-4 lg:grid-cols-2">
          <div className="panel panel-pad border-volt/40">
            <div className="font-display text-lg font-semibold text-volt">Reuse — second life</div>
            <ul className="mt-4 grid gap-3 sm:grid-cols-2">
              {REUSE.map(([id, n, d]) => (
                <li key={id} className="flex gap-3"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-volt/10 text-volt"><ReuseIcon id={id} className="h-4 w-4" /></span><div><div className="text-sm font-medium">{n}</div><div className="text-xs text-fog-400">{d}</div></div></li>
              ))}
            </ul>
            <p className="mt-4 text-xs text-fog-500">Each one is scored by the AI and sized from the measured capacity: panel watts, backup minutes, nights of light.</p>
          </div>
          <div className="panel panel-pad border-data/40">
            <div className="font-display text-lg font-semibold text-data">Recycle — minerals back into EV cells</div>
            <div className="mt-4 flex flex-wrap gap-2">
              {MINERALS.map(([sym, n, col]) => (
                <div key={sym} className="flex h-16 w-16 flex-col items-center justify-center rounded-md border-2" style={{ borderColor: col }}>
                  <span className="font-display-tight text-xl font-bold leading-none" style={{ color: col }}>{sym}</span><span className="mt-0.5 text-[9px] uppercase text-fog-400">{n}</span>
                </div>
              ))}
            </div>
            <p className="mt-4 text-xs text-fog-500">India imports battery-grade lithium, cobalt and nickel, and their refining is concentrated in China. Every pack RE-BAT routes to recycling shows the grams it returns.</p>
          </div>
        </div>
        <div className="panel panel-pad mt-4"><LoopStrip steps={["EV use", "Collected", "RE-BAT tested", "Second life", "Retest", "Recycled", "Minerals", "New EV cell"]} current={-1} /></div>
      </section>

      <section className="mx-auto grid max-w-7xl gap-10 px-6 pb-16 md:grid-cols-3">
        <div>
          <h3 className="font-display text-lg font-semibold">The problem</h3>
          <p className="mt-2 text-fog-300">EV batteries leave vehicles at roughly 70–80 % capacity — long before their useful value is spent. Many end up dumped, and the minerals inside them are imported.</p>
        </div>
        <div>
          <h3 className="font-display text-lg font-semibold text-fog-400">The usual approach</h3>
          <p className="mt-2 text-fog-400">Grade on a single health percentage. Two modules at 80 % get the same fate, even when one overheats under load.</p>
        </div>
        <div>
          <h3 className="font-display text-lg font-semibold text-volt">RE-BAT AI</h3>
          <p className="mt-2 text-fog-300">Read the whole battery fingerprint, reuse it where it fits, recycle it when it doesn't — and keep a forensic record of every step.</p>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 pb-20">
        <blockquote className="max-w-4xl font-display text-3xl font-semibold leading-tight sm:text-4xl">
          Every battery gets a next life: reuse when it is strong enough, recycling when it is not.
        </blockquote>
        <p className="mt-6 max-w-2xl text-fog-400">
          We move from battery health estimation to application-aware second-life intelligence — an AI decision engine
          for second-life EV batteries, built to plug straight into an ESP32 test rig.
        </p>
      </section>

      <footer className="border-t border-ink-700">
        <div className="mx-auto max-w-7xl px-6 py-6 text-xs text-fog-500">
          AI recommendations are screening/decision-support outputs. Final battery reuse requires validated electrical, thermal,
          mechanical and safety testing. Demo batteries and the shipped model use simulated data.
        </div>
      </footer>
    </div>
  );
}
