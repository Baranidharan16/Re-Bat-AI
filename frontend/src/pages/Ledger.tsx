import { useEffect, useState } from "react";
import { ShieldCheck, ShieldAlert } from "lucide-react";
import { api } from "../lib/api";
import { ErrorBox, PageHead } from "../components/ui";

export default function Ledger() {
  const [blocks, setBlocks] = useState<any[] | null>(null);
  const [bats, setBats] = useState<any[]>([]);
  const [verify, setVerify] = useState<any>(null);
  const [fp, setFp] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const load = () => Promise.all([api.ledger(60), api.batteries()]).then(([b, x]) => { setBlocks(b); setBats(x); }).catch((e) => setErr(e.message));
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);
  useEffect(() => { api.modelFingerprint().then(setFp).catch(() => {}); }, []);

  async function check() {
    setBusy(true);
    try { setVerify(await api.ledgerVerify()); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <>
      <PageHead title="Battery ledger" sub="Every battery gets a passport block: its SOH, RUL, reuse/recycle decision, evidence hash and a SHA-256 fingerprint of the model's hyperparameters and weights. Rig data adds a block per forecast window with a Merkle root of its readings. Blocks are chained by SHA-256 with light proof-of-work."
        right={<button className="btn-primary" disabled={busy} onClick={check}>{busy ? "Verifying…" : "Verify entire chain"}</button>} />
      {err && <div className="mb-4"><ErrorBox message={err} /></div>}
      {verify && (
        <div className={`mb-4 flex items-center gap-3 rounded-lg border p-4 text-sm ${verify.valid ? "border-volt/50 bg-volt/5" : "border-alarm bg-alarm/10"}`}>
          {verify.valid ? <ShieldCheck className="h-5 w-5 text-volt" /> : <ShieldAlert className="h-5 w-5 text-alarm" />}
          {verify.valid ? `All ${verify.n_blocks} blocks verified — every stored reading and forecast matches its hash.`
            : `Tampering detected in ${verify.blocks.filter((b: any) => !b.ok).length} block(s): ${verify.blocks.filter((b: any) => !b.ok).map((b: any) => `#${b.idx} (${b.problems.join(", ")})`).join("; ")}`}
        </div>
      )}

      {fp && (
        <section className="panel panel-pad mb-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 className="h-section">Model fingerprint (in every block)</h2><span className="text-xs text-fog-400">{fp.model} · trained {fp.trained_at?.slice(0, 10)}</span></div>
          <div className="mt-2 break-all font-mono text-xs text-volt">{fp.hash}</div>
          <div className="mt-3 flex flex-wrap gap-2">{Object.entries(fp.hyperparameters).filter(([, v]) => v != null && typeof v !== "object").map(([k, v]) => <span key={k} className="chip border border-ink-600 text-fog-300">{k} = {String(v)}</span>)}</div>
          <p className="mt-2 text-2xs text-fog-500">SHA-256 over hyperparameters, feature list, training metadata and the weights file (weights {fp.weights_sha256.slice(0, 16)}…). Retraining or editing the model changes this hash, so every verdict stays tied to the exact model that made it.</p>
        </section>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_2fr]">
        <section className="panel overflow-hidden">
          <div className="px-4 py-3"><h2 className="h-section">Batteries with stored data</h2></div>
          {!bats.length && <p className="px-4 pb-4 text-sm text-fog-400">No rig data yet — batteries streamed from the ESP32 appear here. Demo, CSV and manual batteries are sealed as passport blocks (right).</p>}
          <ul>{bats.map((b) => (
            <li key={b.battery_id} className="border-t border-ink-700 px-4 py-3 text-sm">
              <div className="flex justify-between"><span className="font-medium">{b.battery_id}</span><span className="text-xs text-fog-400">{b.source === "ESP32" ? "ESP32" : "simulation"}</span></div>
              <div className="num text-xs text-fog-400">{b.n_forecasts} forecasts · {b.n_readings} readings · {b.series_cells}S {b.nominal_capacity_ah} Ah</div>
            </li>))}</ul>
        </section>

        <section className="panel overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ink-800 text-left text-xs text-fog-400"><tr><th className="px-4 py-2.5 font-medium">Block</th><th className="px-4 py-2.5 font-medium">Battery</th><th className="px-4 py-2.5 font-medium">SOH</th><th className="px-4 py-2.5 font-medium">Type · pathway</th><th className="px-4 py-2.5 font-medium">Readings</th><th className="px-4 py-2.5 font-medium">Hash</th></tr></thead>
            <tbody>
              {blocks?.map((b) => (
                <tr key={b.idx} className="border-t border-ink-700 align-top">
                  <td className="num px-4 py-2.5">#{b.idx}<div className="text-2xs text-fog-500">{new Date(b.created_at).toLocaleTimeString()}</div></td>
                  <td className="px-4 py-2.5">{b.payload.battery_id}<div className="text-2xs text-fog-500">{b.payload.source === "ESP32" ? "ESP32" : "simulation"}</div></td>
                  <td className="num px-4 py-2.5">{b.payload.soh?.toFixed(1)}%<div className="text-2xs text-fog-500">conf {b.payload.confidence?.toFixed(0)}%</div></td>
                  <td className="px-4 py-2.5"><span className={`chip border ${b.payload.type === "passport" ? "border-volt/40 text-volt" : "border-data/40 text-data"}`}>{b.payload.type === "passport" ? "passport" : "rig forecast"}</span><div className="mt-0.5 text-2xs text-fog-400">{(b.payload.pathway ?? String(b.payload.decision).replace(/_/g, " ")).toLowerCase()}</div></td>
                  <td className="num px-4 py-2.5">{b.payload.n_leaves}</td>
                  <td className="px-4 py-2.5 text-2xs text-fog-400"><div title={b.block_hash}>{b.block_hash.slice(0, 18)}…</div><div title={b.prev_hash} className="text-fog-500">prev {b.prev_hash.slice(0, 10)}…</div></td>
                </tr>
              ))}
              {blocks && !blocks.length && <tr><td colSpan={6} className="px-4 py-6 text-center text-fog-400">The chain is empty.</td></tr>}
            </tbody>
          </table>
        </section>
      </div>
      <p className="mt-4 text-xs text-fog-500">Single-node, tamper-evident chain. To anchor publicly, publish the head hash to a public blockchain or a timestamping service; the stored structure already supports it.</p>
    </>
  );
}
