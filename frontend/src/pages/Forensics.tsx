import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { FileSearch, ShieldAlert, ShieldCheck } from "lucide-react";
import { useAnalysis } from "../lib/store";
import { api, type Mechanism } from "../lib/api";
import { Meter, NeedsResult, PageHead } from "../components/ui";
import { PathwayChip } from "../components/circular";

const tip = { contentStyle: { background: "#121D31", border: "1px solid #2A3B5C", borderRadius: 6, fontSize: 12 }, labelStyle: { color: "#8A9AB5" } };

function MechRow({ m }: { m: Mechanism }) {
  const tone = m.severity == null ? "data" : m.severity >= 66 ? "alarm" : m.severity >= 33 ? "amber" : "volt";
  return (
    <li className="border-t border-ink-700 px-5 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium">{m.name}</span>
        <span className={`chip border ${m.severity == null ? "border-ink-600 text-fog-500" : tone === "alarm" ? "border-alarm/50 text-alarm" : tone === "amber" ? "border-amber/50 text-amber" : "border-volt/40 text-volt"}`}>{m.level}</span>
      </div>
      <div className="mt-2 grid items-center gap-3 sm:grid-cols-[1fr_3rem]">
        {m.severity == null ? <div className="h-1.5 rounded-full border border-dashed border-ink-600" /> : <Meter value={m.severity} tone={tone as any} height={6} />}
        <span className="num text-right text-sm text-fog-300">{m.severity == null ? "—" : m.severity.toFixed(0)}</span>
      </div>
      <div className="mt-2 text-sm text-fog-300">{m.evidence}</div>
      <div className="text-xs text-fog-500">{m.explanation}</div>
    </li>
  );
}

export default function Forensics() {
  const { result, loading, error } = useAnalysis();
  const [rep, setRep] = useState<any>(null);
  const [repErr, setRepErr] = useState<string | null>(null);
  useEffect(() => {
    if (!result) return;
    setRep(null); setRepErr(null);
    api.forensics(result.battery_id).then(setRep).catch((e) => setRepErr(e.message));
  }, [result?.battery_id, result?.generated_at]);

  return (
    <NeedsResult result={result} loading={loading} error={error}>
      {(r) => {
        const f = r.forensics;
        return (
          <>
            <PageHead title="Battery forensics" sub="Why this battery aged, what happened during its tests, and proof that its record has not been changed. Every rig test is sealed in the hash-chained ledger." right={<PathwayChip p={r.circular.pathway} />} />

            <section className="panel overflow-hidden">
              <div className="grid gap-6 p-6 md:grid-cols-[1.3fr_1fr]">
                <div>
                  <div className="flex items-center gap-2 text-xs text-fog-400"><FileSearch className="h-4 w-4" />Forensic verdict</div>
                  <h2 className="mt-1 font-display text-2xl font-bold">{f.verdict}</h2>
                  {f.unmeasured.length > 0 && <p className="mt-2 text-sm text-fog-400">Not measured in this test: {f.unmeasured.join(", ").toLowerCase()}.</p>}
                </div>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                  <div><dt className="text-2xs text-fog-500">Battery passport</dt><dd className="font-display text-lg font-semibold text-volt">{f.passport_id}</dd></div>
                  <div><dt className="text-2xs text-fog-500">Data source</dt><dd>{f.data.source}</dd></div>
                  <div className="col-span-2"><dt className="text-2xs text-fog-500">Evidence hash (SHA-256 of measurements + verdict)</dt><dd className="break-all font-mono text-2xs text-fog-300">{f.evidence_hash}</dd></div>
                  <div><dt className="text-2xs text-fog-500">Sealed in ledger</dt><dd>{f.data.sealed_in_ledger && r.ledger ? <>Block #{r.ledger.idx}</> : "not this result (demo / CSV / manual)"}</dd></div>
                  <div><dt className="text-2xs text-fog-500">Model</dt><dd className="text-fog-300">{f.data.model}</dd></div>
                </dl>
              </div>
            </section>

            <div className="mt-4 grid gap-4 lg:grid-cols-[1.2fr_1fr]">
              <section className="panel overflow-hidden">
                <div className="px-5 py-4"><h2 className="h-section">Ageing mechanisms</h2><p className="text-xs text-fog-400">Severity 0–100 from the measured fingerprint. Highest first.</p></div>
                <ul>{f.mechanisms.map((m) => <MechRow key={m.id} m={m} />)}</ul>
              </section>
              <div className="space-y-4">
                <section className="panel panel-pad">
                  <h2 className="h-section">Anomalies during the test</h2>
                  {f.anomalies.length === 0 ? <p className="mt-3 text-sm text-fog-400">None — voltage, temperature, gas and current stayed inside limits.</p> : (
                    <ul className="mt-3 space-y-2 text-sm">{f.anomalies.map((a, i) => (
                      <li key={i} className="flex gap-2"><ShieldAlert className={`mt-0.5 h-4 w-4 shrink-0 ${a.level === "ALARM" ? "text-alarm" : "text-amber"}`} />{a.message}{a.t_s != null && <span className="text-fog-500"> · t = {(a.t_s / 60).toFixed(1)} min</span>}</li>
                    ))}</ul>
                  )}
                </section>
                <section className="panel panel-pad">
                  <h2 className="h-section">Data quality</h2>
                  <dl className="mt-3 space-y-2 text-sm">
                    <div className="flex justify-between"><dt className="text-fog-400">Samples analysed</dt><dd className="num">{f.data.samples ?? "—"}</dd></div>
                    <div className="flex justify-between"><dt className="text-fog-400">Missing model inputs</dt><dd className="num">{f.data.missing_features.length}</dd></div>
                    <div className="flex justify-between"><dt className="text-fog-400">Validation warnings</dt><dd className="num">{f.data.validation_warnings.length}</dd></div>
                  </dl>
                  {f.data.validation_warnings.slice(0, 3).map((w) => <p key={w} className="mt-2 text-xs text-amber">{w}</p>)}
                </section>
              </div>
            </div>

            <section className="panel mt-4 overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
                <div><h2 className="h-section">Chain of custody</h2><p className="text-xs text-fog-400">Every stored rig test for {r.battery_id}, with its ledger block.</p></div>
                {rep && (rep.integrity.chain_valid && rep.integrity.blocks_ok === rep.integrity.blocks_checked
                  ? <span className="chip border border-volt/50 bg-volt/10 text-volt"><ShieldCheck className="h-3.5 w-3.5" />{rep.integrity.blocks_ok}/{rep.integrity.blocks_checked} blocks verified</span>
                  : <span className="chip border border-alarm bg-alarm/10 text-alarm"><ShieldAlert className="h-3.5 w-3.5" />tampering detected</span>)}
              </div>
              {repErr && <p className="border-t border-ink-700 px-5 py-4 text-sm text-fog-400">{repErr} <Link to="/app/live" className="text-data hover:underline">Stream it from the ESP32 rig</Link> to build a custody record.</p>}
              {rep && (
                <div className="grid gap-0 border-t border-ink-700 lg:grid-cols-[1fr_1.2fr]">
                  <ol className="space-y-0 p-5">
                    {rep.custody.map((e: any, i: number) => (
                      <li key={i} className="relative border-l border-ink-600 pb-4 pl-4 last:pb-0">
                        <span className="absolute -left-[5px] top-1 h-2.5 w-2.5 rounded-full bg-volt" />
                        <div className="text-sm font-medium">{e.event}</div>
                        <div className="text-xs text-fog-400">{e.detail}</div>
                        <div className="text-2xs text-fog-500">{new Date(e.at).toLocaleString()}</div>
                      </li>
                    ))}
                  </ol>
                  <div className="border-t border-ink-700 p-5 lg:border-l lg:border-t-0">
                    <div className="text-sm">SOH across stored tests <span className="text-fog-400">· {rep.n_forecasts} forecasts · {rep.n_readings} readings</span></div>
                    <ResponsiveContainer width="100%" height={200}>
                      <LineChart data={rep.soh_trend.map((p: any, i: number) => ({ ...p, i: i + 1 }))} margin={{ top: 10, right: 8, bottom: 0, left: -10 }}>
                        <CartesianGrid strokeDasharray="2 4" />
                        <XAxis dataKey="i" />
                        <YAxis domain={["auto", "auto"]} width={40} />
                        <Tooltip {...tip} formatter={(v: any) => `${Number(v).toFixed(1)} %`} labelFormatter={(l) => `forecast ${l}`} />
                        <Line dataKey="soh" stroke="#B6F23A" dot={false} strokeWidth={2} isAnimationActive={false} />
                        <Line dataKey="lo" stroke="#2E7F96" dot={false} strokeDasharray="3 3" isAnimationActive={false} />
                        <Line dataKey="hi" stroke="#2E7F96" dot={false} strokeDasharray="3 3" isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                    <div className="mt-3 max-h-48 overflow-y-auto text-xs">
                      <table className="w-full"><thead className="text-left text-fog-500"><tr><th className="py-1 font-medium">Block</th><th className="font-medium">SOH</th><th className="font-medium">Pathway</th><th className="font-medium">Hash</th></tr></thead>
                        <tbody>{[...rep.timeline].reverse().slice(0, 12).map((e: any) => (
                          <tr key={e.id} className="border-t border-ink-700"><td className="num py-1">#{e.block_index}</td><td className="num">{e.soh?.toFixed(1)}%</td><td>{e.pathway?.toLowerCase() ?? "—"}</td><td className="font-mono text-fog-500">{e.block_hash?.slice(0, 12)}…</td></tr>
                        ))}</tbody></table>
                    </div>
                  </div>
                </div>
              )}
            </section>
          </>
        );
      }}
    </NeedsResult>
  );
}
