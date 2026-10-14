import { useState } from "react";
import { FlaskConical, RotateCcw } from "lucide-react";
import { useAnalysis } from "../lib/store";
import { api, type TestRec } from "../lib/api";
import { ErrorBox, Meter, NeedsResult, PageHead, confTone } from "../components/ui";

const LOOP = ["AI", "Test request", "Hardware", "New data", "AI"];

function Loop({ step }: { step: number }) {
  return (
    <ol className="flex flex-wrap items-center gap-2 text-sm" aria-label="Closed-loop diagnostic cycle">
      {LOOP.map((s, i) => (
        <li key={i} className="flex items-center gap-2">
          <span className={`rounded-md border px-3 py-1.5 ${i < step ? "border-volt/50 text-volt" : i === step ? "border-volt bg-volt text-ink-950" : "border-ink-600 text-fog-400"}`}>{s}</span>
          {i < LOOP.length - 1 && <span aria-hidden className="text-fog-500">→</span>}
        </li>
      ))}
    </ol>
  );
}

export default function Diagnostics() {
  const { result, loading, error, source, setAnalysis, lastTest, setLastTest, loadDemo } = useAnalysis();
  const [busy, setBusy] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [queued, setQueued] = useState<string | null>(null);

  async function run(t: TestRec) {
    if (!result) return;
    setErr(null); setQueued(null); setBusy(t.id); setStep(1);
    try {
      if (source?.kind === "demo") {
        await new Promise((r) => setTimeout(r, 350)); setStep(2);
        const res = await api.requestTest(result.battery_id, t.id, "demo");
        setStep(3); await new Promise((r) => setTimeout(r, 300));
        setAnalysis(res.after, source); setLastTest(res); setStep(5);
      } else {
        const res = await api.requestTest(result.battery_id, t.id, "live");
        setQueued(res.status === "started" ? "The simulated rig started the test — follow it on Live data; the new forecast replaces this one when the window closes."
          : `Queued as request #${res.request_id}. The ESP32 rig picks it up on its next poll and streams the results back.`);
        setStep(2);
      }
    } catch (e: any) { setErr(e.message); setStep(0); } finally { setBusy(null); }
  }

  return (
    <NeedsResult result={result} loading={loading} error={error}>
      {(r) => {
        const rec = r.adaptive.recommended;
        const tests = [rec, ...r.adaptive.alternatives].filter(Boolean) as TestRec[];
        const comps = r.confidence.components;
        return (
          <>
            <PageHead title="AI diagnostic assistant" sub="When the AI is uncertain, it doesn't guess — it names what is missing and asks for the test that resolves it fastest."
              right={source?.kind === "demo" && r.demo && r.demo.tests_run > 0 ? <button className="btn-ghost" onClick={() => { setLastTest(null); setStep(0); api.demoReset(r.battery_id).then(() => loadDemo(r.battery_id)); }}><RotateCcw className="h-4 w-4" /> Reset battery</button> : undefined} />

            <div className="grid gap-4 lg:grid-cols-[1fr_1.3fr]">
              <section className="panel panel-pad">
                <div className="flex items-baseline justify-between"><h2 className="h-section">Prediction confidence</h2><span className={`num font-display text-3xl font-bold ${confTone(r.confidence.band) === "volt" ? "text-volt" : confTone(r.confidence.band) === "data" ? "text-data" : "text-amber"}`}>{r.confidence.value.toFixed(0)}%</span></div>
                <div className="mt-2"><Meter value={r.confidence.value} tone={confTone(r.confidence.band)} height={8} /></div>
                <dl className="mt-5 space-y-3 text-sm">
                  {[["SOH within ±2.5 pts", comps.soh], ["RUL band tightness", comps.rul], ["Ranking separation", comps.decision_margin]].map(([k, v]) => (
                    <div key={k as string}><div className="flex justify-between"><dt className="text-fog-300">{k}</dt><dd className="num">{(v as number).toFixed(0)}%</dd></div><Meter value={v as number} tone="data" height={3} /></div>
                  ))}
                </dl>
                <p className="mt-4 text-2xs text-fog-500">{r.confidence.formula}. Bands: high ≥ 90, moderate ≥ 75 (configurable).</p>
                <p className="mt-2 text-sm text-fog-400">SOH {r.soh.soh.toFixed(1)}% · interval {r.soh.lo.toFixed(1)}–{r.soh.hi.toFixed(1)}%</p>
              </section>

              <section className="panel panel-pad">
                <h2 className="h-section">{r.adaptive.required ? "Additional test recommended" : r.adaptive.blocked_by_safety ? "Testing blocked by safety alarm" : "No additional test currently required"}</h2>
                {r.adaptive.uncertainty_sources.length > 0 && (
                  <ul className="mt-3 space-y-2 text-sm">
                    {r.adaptive.uncertainty_sources.slice(0, 5).map((u) => (
                      <li key={u.source} className="flex gap-3"><span className="num mt-0.5 w-10 shrink-0 text-2xs text-fog-500">sev {u.severity}</span><span className="text-fog-300">{u.message}</span></li>
                    ))}
                  </ul>
                )}
                {rec && (
                  <div className="mt-5 rounded-md border border-volt/50 bg-volt/5 p-4">
                    <div className="flex items-center gap-2 text-xs text-fog-400"><FlaskConical className="h-4 w-4 text-volt" /> Recommended test</div>
                    <div className="mt-1 font-display text-2xl font-bold">{rec.name}</div>
                    <p className="mt-1 text-sm text-fog-300">{rec.reason}</p>
                    <p className="mt-1 text-xs text-fog-400">{rec.description} About {rec.duration_min} min.</p>
                  </div>
                )}
              </section>
            </div>

            <section className="panel panel-pad mt-4">
              <div className="flex flex-wrap items-center justify-between gap-4"><h2 className="h-section">Closed loop</h2><Loop step={step} /></div>
              {err && <div className="mt-4"><ErrorBox message={err} /></div>}
              {queued && <p className="mt-4 text-sm text-data">{queued}</p>}
              <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {tests.map((t, i) => (
                  <div key={t.id} className={`rounded-md border p-4 ${i === 0 && rec ? "border-volt/60" : "border-ink-700"}`}>
                    <div className="font-medium">{t.name}</div>
                    <div className="mt-1 text-xs text-fog-400">{t.duration_min} min · priority {t.priority.toFixed(1)}</div>
                    <div className="mt-1 text-2xs text-fog-500">resolves: {t.resolves.join(", ").replace(/_/g, " ")}</div>
                    <button className={`${i === 0 && rec ? "btn-primary" : "btn-ghost"} mt-3 w-full justify-center`} disabled={!!busy || r.adaptive.blocked_by_safety} onClick={() => run(t)}>
                      {busy === t.id ? "Running…" : source?.kind === "demo" ? "Request test" : "Send to rig"}
                    </button>
                  </div>
                ))}
                {!tests.length && <p className="text-sm text-fog-400">Nothing left that would meaningfully change this result.</p>}
              </div>
              <p className="mt-4 text-2xs text-fog-500">Demo batteries run the test on the simulator. Real rigs receive the request as a command; the rig's BMS, fuse and firmware limits decide whether it may run.</p>
            </section>

            {lastTest && (
              <section className="panel panel-pad mt-4">
                <h2 className="h-section">Result of {lastTest.test.name}</h2>
                <div className="mt-3 grid gap-4 text-sm sm:grid-cols-3">
                  <div><div className="text-xs text-fog-400">SOH</div><div className="num font-display text-xl">{lastTest.before.soh.soh.toFixed(1)}% → {lastTest.after.soh.soh.toFixed(1)}%</div><div className="text-xs text-fog-500">interval width {(lastTest.before.soh.hi - lastTest.before.soh.lo).toFixed(1)} → {(lastTest.after.soh.hi - lastTest.after.soh.lo).toFixed(1)} pts</div></div>
                  <div><div className="text-xs text-fog-400">Confidence</div><div className="num font-display text-xl">{lastTest.before.confidence.value.toFixed(0)}% → {lastTest.after.confidence.value.toFixed(0)}%</div></div>
                  <div><div className="text-xs text-fog-400">Top application</div><div className="font-display text-xl">{lastTest.before.top} → {lastTest.after.router.ranking[0].short}</div></div>
                </div>
                <p className="mt-3 text-xs text-fog-500">{lastTest.test.rows} new readings ({lastTest.test.data_label.toLowerCase()}). Updated evidence: {lastTest.test.updated_features.join(", ") || "none"}.</p>
              </section>
            )}

            {r.evidence.length > 0 && (
              <section className="panel mt-4 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-ink-800 text-left text-xs text-fog-400"><tr><th className="px-4 py-2 font-medium">Step</th><th className="px-4 py-2 font-medium">Test</th><th className="px-4 py-2 font-medium">Readings</th><th className="px-4 py-2 font-medium">SOH</th><th className="px-4 py-2 font-medium">Confidence</th><th className="px-4 py-2 font-medium">Top application</th></tr></thead>
                  <tbody>{r.evidence.map((e: any) => (
                    <tr key={e.step} className="border-t border-ink-700"><td className="num px-4 py-2">{e.step}</td><td className="px-4 py-2">{e.name}</td><td className="num px-4 py-2">{e.rows}</td>
                      <td className="num px-4 py-2">{e.soh_before !== undefined ? `${e.soh_before} → ${e.soh_after}` : "—"}</td>
                      <td className="num px-4 py-2">{e.confidence_before !== undefined ? `${e.confidence_before} → ${e.confidence_after}` : "—"}</td>
                      <td className="px-4 py-2">{e.top_before ? `${e.top_before} → ${e.top_after}` : "—"}</td></tr>))}</tbody>
                </table>
              </section>
            )}
          </>
        );
      }}
    </NeedsResult>
  );
}
