import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { DataBadge, ErrorBox, Loading, Meter, PageHead } from "../components/ui";

function MetricRow({ name, m }: { name: string; m: any }) {
  return (
    <tr className="border-t border-ink-700">
      <td className="px-4 py-2.5">{name}</td>
      <td className="num px-4 py-2.5">{m.MAE?.toFixed(2)}</td><td className="num px-4 py-2.5">{m.RMSE?.toFixed(2)}</td><td className="num px-4 py-2.5">{m.R2?.toFixed(3)}</td><td className="num px-4 py-2.5 text-fog-400">{m.n}</td>
    </tr>
  );
}

export default function Model() {
  const [s, setS] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.modelStatus().then(setS).catch((e) => setErr(e.message)); }, []);
  if (err) return <ErrorBox message={err} />;
  if (!s) return <Loading text="Loading model card…" />;
  const c = s.soh_model, m = c.metrics_test;
  return (
    <>
      <PageHead title="AI engine status" sub="Every number here is read from the model card written by the training script. Nothing is typed in by hand." right={<DataBadge label={c.data_source === "SIMULATED" ? "DEMO MODEL · SIMULATED DATA" : c.data_source} />} />

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="panel panel-pad lg:col-span-2">
          <h2 className="h-section">{c.model_name} <span className="text-fog-400">{c.version}</span></h2>
          <dl className="mt-3 grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
            <div className="flex justify-between"><dt className="text-fog-400">Status</dt><dd>{c.status}</dd></div>
            <div className="flex justify-between"><dt className="text-fog-400">Dataset</dt><dd className="text-right">{c.dataset}</dd></div>
            <div className="flex justify-between"><dt className="text-fog-400">Split</dt><dd className="text-right">{c.split.method}</dd></div>
            <div className="flex justify-between"><dt className="text-fog-400">Batteries train / val / test</dt><dd className="num">{c.split.n_batteries.train} / {c.split.n_batteries.val} / {c.split.n_batteries.test}</dd></div>
            <div className="flex justify-between"><dt className="text-fog-400">Trained</dt><dd className="num">{new Date(c.trained_at).toLocaleString()}</dd></div>
            <div className="flex justify-between"><dt className="text-fog-400">Features</dt><dd className="num">{c.features.length}</dd></div>
          </dl>
          <div className="mt-5 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-fog-400"><tr><th className="px-4 py-2 font-medium">Held-out test batteries</th><th className="px-4 py-2 font-medium">MAE (pts)</th><th className="px-4 py-2 font-medium">RMSE</th><th className="px-4 py-2 font-medium">R²</th><th className="px-4 py-2 font-medium">n</th></tr></thead>
              <tbody>
                <MetricRow name="XGBoost (time-series features)" m={m.xgboost} />
                <MetricRow name="Baseline ridge regression" m={m.baseline_ridge} />
                {c.spot_variant && <MetricRow name="XGBoost spot variant (manual input)" m={c.spot_variant.metrics_test.xgboost} />}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-sm">90 % prediction interval: empirical coverage <span className="num">{(m.interval_90.coverage * 100).toFixed(1)}%</span>, mean width <span className="num">{m.interval_90.mean_width.toFixed(1)}</span> pts (target 90 %).</p>
          <p className="mt-3 rounded-md border border-amber/40 bg-amber/10 p-3 text-sm">{c.caveat}</p>
        </section>

        <section className="panel panel-pad">
          <h2 className="h-section">Most influential features</h2>
          <p className="text-xs text-fog-400">Share of total split gain in the XGBoost model.</p>
          <ul className="mt-4 space-y-2.5 text-sm">
            {s.global_importance.map((g: any) => (
              <li key={g.feature}><div className="flex justify-between"><span>{g.label}</span><span className="num text-fog-400">{(g.gain_share * 100).toFixed(1)}%</span></div><Meter value={g.gain_share * 100} max={s.global_importance[0].gain_share * 100} tone="data" height={3} /></li>
            ))}
          </ul>
        </section>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {[[s.temporal_model.name, s.temporal_model.status, `Input ${s.temporal_model.input}. ${s.temporal_model.fusion}.`],
          [s.rul_model.name, s.rul_model.status, `End of second-life threshold ${s.rul_model.eol_soh}% SOH. ${s.rul_model.note}`],
          [s.router.name, s.router.status, s.router.evaluation]].map(([n, st, d]) => (
          <section key={n} className="panel panel-pad">
            <h3 className="h-section">{n}</h3>
            <div className="mt-1 text-sm text-amber">{st}</div>
            <p className="mt-2 text-sm text-fog-400">{d}</p>
          </section>
        ))}
      </div>

      <section className="panel panel-pad mt-4 text-sm">
        <h3 className="h-section">Replace the demo model with real data</h3>
        <pre className="mt-3 overflow-x-auto rounded-md bg-ink-950 p-3 text-xs text-fog-300">{`cd backend
# 1. turn NASA / CALCE / your rig logs into a features file (see app/ml/data_ingestion.py loaders)
# 2. train with a battery-level split and regenerate this card
python -m app.ml.train_model --features data/my_features.csv --source EXPERIMENTAL --dataset-name "Lab rig 2026"
python -m app.ml.evaluate_model --features data/my_features.csv`}</pre>
      </section>
    </>
  );
}
