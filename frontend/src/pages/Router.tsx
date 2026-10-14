import { useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import { useAnalysis } from "../lib/store";
import type { AppScore } from "../lib/api";
import { Meter, NeedsResult, PageHead } from "../components/ui";

const STATUS_TONE: Record<string, string> = {
  "Highly suitable": "text-volt", Suitable: "text-data", "Conditional — validate": "text-amber", "Not recommended": "text-fog-500", Excluded: "text-alarm",
};

function Row({ a, rank }: { a: AppScore; rank: number }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-t border-ink-700">
      <button className="grid w-full grid-cols-[2rem_1fr_auto] items-center gap-4 px-5 py-4 text-left hover:bg-ink-800 sm:grid-cols-[2rem_14rem_1fr_9rem_1.5rem]" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="num text-fog-500">{rank}</span>
        <span><span className="block">{a.name}</span><span className="block text-2xs text-fog-500">{a.duty}</span></span>
        <span className="hidden sm:block"><Meter value={a.score} tone={a.status === "Excluded" ? "alarm" : "data"} /></span>
        <span className="text-right"><span className="num font-display text-lg font-semibold">{a.score.toFixed(0)}</span><span className={`block text-2xs ${STATUS_TONE[a.status]}`}>{a.status}</span></span>
        <ChevronDown className={`hidden h-4 w-4 text-fog-500 transition-transform sm:block ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="grid gap-4 px-5 pb-5 text-sm sm:grid-cols-2 sm:pl-[4.25rem]">
          <div><div className="mb-1 text-xs text-fog-400">Supports</div><ul className="space-y-1">{a.reasons_for.length ? a.reasons_for.map((x) => <li key={x}><span className="text-volt">+ </span>{x}</li>) : <li className="text-fog-500">No requirement fully met.</li>}</ul></div>
          <div><div className="mb-1 text-xs text-fog-400">Against</div><ul className="space-y-1">{a.reasons_against.length ? a.reasons_against.map((x) => <li key={x}><span className="text-amber">− </span>{x}</li>) : <li className="text-fog-500">Nothing significant.</li>}</ul></div>
          <p className="text-xs text-fog-500 sm:col-span-2">{a.description} Fit {a.fit_score.toFixed(0)} × value tier {a.value_tier} ({a.score.toFixed(0)}).</p>
        </div>
      )}
    </li>
  );
}

export default function Router() {
  const { result, loading, error } = useAnalysis();
  return (
    <NeedsResult result={result} loading={loading} error={error}>
      {(r) => {
        const [top, ...rest] = r.router.ranking;
        const dec = r.router.decision;
        return (
          <>
            <PageHead title="AI second-life router" sub="The fingerprint is matched against each application's requirement profile. A weighted geometric mean means one failed requirement pulls a score down — SOH alone never decides." />

            <section className="panel relative overflow-hidden border-volt/50">
              <div className="absolute inset-y-0 left-0 w-1 bg-volt" aria-hidden />
              <div className="grid gap-6 p-6 lg:grid-cols-[1fr_1.2fr]">
                <div>
                  <div className="text-xs text-fog-400">Best match · rank 1 of {r.router.ranking.length}</div>
                  <h2 className="mt-1 font-display-tight text-3xl font-bold text-volt sm:text-4xl">{top.name}</h2>
                  <div className="mt-3 flex items-baseline gap-3"><span className="num font-display text-5xl font-bold">{top.score.toFixed(0)}</span><span className="text-fog-400">/ 100 · {top.status.toLowerCase()}</span></div>
                  <div className="mt-3 max-w-sm"><Meter value={top.score} height={8} animate /></div>
                  <p className="mt-4 text-sm text-fog-400">{top.description}</p>
                  {dec.id !== top.id && (
                    <div className="mt-4 rounded-md border border-amber/50 bg-amber/10 p-3 text-sm">
                      Routing decision: <strong>{dec.name}</strong>. {dec.kind === "pathway" && dec.id === "further_diagnostics" ? <>Confidence is too low to commit. <Link to="/app/diagnostics" className="text-volt underline">See the recommended test</Link>.</> : dec.kind === "safety" ? "A safety alarm overrides routing." : null}
                    </div>
                  )}
                </div>
                <div className="grid gap-4 text-sm sm:grid-cols-2">
                  <div><div className="mb-2 text-xs text-fog-400">Why it fits</div><ul className="space-y-1.5">{top.reasons_for.map((x) => <li key={x}><span className="text-volt">+ </span>{x}</li>)}</ul></div>
                  <div><div className="mb-2 text-xs text-fog-400">Watch-outs</div><ul className="space-y-1.5">{top.reasons_against.length ? top.reasons_against.map((x) => <li key={x}><span className="text-amber">− </span>{x}</li>) : <li className="text-fog-500">None flagged.</li>}</ul></div>
                </div>
              </div>
            </section>

            <section className="panel mt-4 overflow-hidden">
              <div className="flex items-center justify-between px-5 py-3"><h2 className="h-section">Other applications</h2><span className="text-xs text-fog-400">margin to runner-up {r.router.decision_margin.toFixed(1)} pts</span></div>
              <ol>{rest.map((a, i) => <Row key={a.id} a={a} rank={i + 2} />)}</ol>
            </section>

            <section className="mt-4 grid gap-4 md:grid-cols-2">
              {r.router.pathways.map((p) => (
                <div key={p.id} className="panel panel-pad">
                  <div className="flex items-baseline justify-between"><h3 className="h-section">{p.name}</h3><span className="num font-display text-xl">{p.score.toFixed(0)}</span></div>
                  <div className="mt-2"><Meter value={p.score} tone="amber" height={4} /></div>
                  <p className="mt-2 text-xs text-fog-400">{p.description}</p>
                </div>
              ))}
            </section>
            <p className="mt-4 text-xs text-fog-500">{r.router.method} {r.soh.screening.disclaimer}</p>
          </>
        );
      }}
    </NeedsResult>
  );
}
