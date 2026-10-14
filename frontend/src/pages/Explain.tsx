import { useEffect, useState } from "react";
import { useAnalysis } from "../lib/store";
import { NeedsResult, PageHead } from "../components/ui";

function Diverging({ value, max, pos = "bg-volt", neg = "bg-amber" }: { value: number; max: number; pos?: string; neg?: string }) {
  const w = Math.min(50, (Math.abs(value) / (max || 1)) * 50);
  return (
    <div className="relative h-3 w-full rounded-sm bg-ink-800">
      <div className="absolute inset-y-0 left-1/2 w-px bg-ink-600" />
      <div className={`absolute inset-y-0 rounded-sm ${value >= 0 ? pos : neg}`} style={value >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} />
    </div>
  );
}

export default function Explain() {
  const { result, loading, error } = useAnalysis();
  const [app, setApp] = useState<string | null>(null);
  useEffect(() => { setApp(null); }, [result?.battery_id, result?.generated_at]);
  return (
    <NeedsResult result={result} loading={loading} error={error}>
      {(r) => {
        const ex = r.explanation;
        const sel = app ?? ex.applications.recommended;
        const pa = ex.applications.per_application[sel];
        const shapMax = Math.max(...ex.soh.top.map((t) => Math.abs(t.contribution)));
        return (
          <>
            <PageHead title="Why did the AI choose this?" sub="Two layers of explanation, both computed from this battery's data: requirement fit for the routing decision, and TreeSHAP for the health estimate." />

            <div className="panel panel-pad">
              <p className="max-w-4xl font-display text-xl leading-snug">{ex.applications.summary}</p>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <section className="panel panel-pad">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2 className="h-section">Requirement fit</h2>
                  <select aria-label="Application" className="input w-auto" value={sel} onChange={(e) => setApp(e.target.value)}>
                    {Object.entries(ex.applications.per_application).map(([id, a]) => <option key={id} value={id}>{a.name} ({a.score.toFixed(0)})</option>)}
                  </select>
                </div>
                <p className="mt-1 text-xs text-fog-400">Bar = weight × (2·fit − 1). Right helps the score, left hurts it.</p>
                <ul className="mt-4 space-y-3">
                  {pa.factors.map((f) => (
                    <li key={f.label} className="grid grid-cols-[9.5rem_1fr] items-center gap-3 text-sm">
                      <div><div className={f.verified ? "" : "text-fog-500"}>{f.label}</div><div className="text-2xs text-fog-500">{f.value} · needs {f.requirement}</div></div>
                      <Diverging value={f.impact} max={0.5} />
                    </li>
                  ))}
                </ul>
              </section>

              <section className="panel panel-pad">
                <h2 className="h-section">What drove the SOH estimate</h2>
                <p className="mt-1 text-xs text-fog-400">{ex.soh.method}. Starting from the population average of {ex.soh.base_value.toFixed(1)}%, each measurement moved the estimate by the amount shown (SOH points).</p>
                <ul className="mt-4 space-y-3">
                  {ex.soh.top.slice(0, 9).map((t) => (
                    <li key={t.feature} className="grid grid-cols-[9.5rem_1fr_3.5rem] items-center gap-3 text-sm">
                      <div><div className={t.measured ? "" : "text-fog-500"}>{t.label}</div><div className="text-2xs text-fog-500">{t.measured ? `${t.value} ${t.unit}` : "not measured"}</div></div>
                      <Diverging value={t.contribution} max={shapMax} pos="bg-data" neg="bg-amber" />
                      <span className={`num text-right text-xs ${t.contribution >= 0 ? "text-data" : "text-amber"}`}>{t.contribution >= 0 ? "+" : ""}{t.contribution.toFixed(2)}</span>
                    </li>
                  ))}
                </ul>
                <div className="mt-4 border-t border-ink-700 pt-3 text-xs text-fog-400">Base {ex.soh.base_value.toFixed(1)} + contributions = {r.soh.soh.toFixed(1)}% predicted.</div>
              </section>
            </div>
          </>
        );
      }}
    </NeedsResult>
  );
}
