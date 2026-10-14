import { Area, CartesianGrid, ComposedChart, ErrorBar, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { useAnalysis } from "../lib/store";
import { fmt, type Analysis } from "../lib/api";
import Gauge from "../components/Gauge";
import { Grade, NeedsResult, PageHead, RiskChip, Stat } from "../components/ui";

const tip = { contentStyle: { background: "#121D31", border: "1px solid #2A3B5C", borderRadius: 6, fontSize: 12 }, labelStyle: { color: "#8A9AB5" } };

export function RulChart({ r, height = 300 }: { r: Analysis; height?: number }) {
  const traj = r.rul.trajectory.map((p) => ({ cycle: p.cycle, band: [p.p10, p.p90], p50: p.p50 }));
  const hist = r.rul.history.map((h) => ({ cycle: h.cycle, soh: h.soh, err: [h.soh - h.lo, h.hi - h.soh] }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart margin={{ top: 22, right: 16, bottom: 16, left: 0 }}>
        <CartesianGrid strokeDasharray="2 4" />
        <XAxis dataKey="cycle" type="number" domain={[0, "dataMax"]} allowDuplicatedCategory={false}
          label={{ value: r.rul.cycle_known ? "Cycle" : "Equivalent cycle", position: "insideBottom", offset: -8, fill: "#66779A", fontSize: 11 }} />
        <YAxis domain={[Math.min(55, r.rul.eol_soh - 5), 100]} tickFormatter={(x) => `${Number(x).toFixed(0)}%`} width={44} allowDecimals={false} />
        <Tooltip {...tip} formatter={(v: any) => (Array.isArray(v) ? `${v[0].toFixed(1)}–${v[1].toFixed(1)}%` : `${Number(v).toFixed(1)}%`)} />
        <Area data={traj} dataKey="band" stroke="none" fill="#4FC3E0" fillOpacity={0.15} name="P10–P90" isAnimationActive={false} />
        <Line data={traj} dataKey="p50" stroke="#4FC3E0" strokeWidth={2} dot={false} name="Forecast (median)" isAnimationActive={false} />
        <Scatter data={hist} dataKey="soh" fill="#B6F23A" name="Model estimate">
          <ErrorBar dataKey="err" stroke="#B6F23A" width={4} direction="y" />
        </Scatter>
        <ReferenceLine y={r.rul.eol_soh} stroke="#F2B33D" strokeDasharray="4 4" label={{ value: `EOL ${r.rul.eol_soh}%`, fill: "#F2B33D", fontSize: 11, position: "insideTopRight" }} />
        {r.rul.cycle_now !== undefined && <ReferenceLine x={r.rul.cycle_now} stroke="#8A9AB5" strokeDasharray="2 3" label={{ value: "now", fill: "#8A9AB5", fontSize: 11, position: "top" }} />}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export default function Health() {
  const { result, loading, error } = useAnalysis();
  return (
    <NeedsResult result={result} loading={loading} error={error}>
      {(r) => {
        const ts = r.timeseries.filter((p) => p.i > 0.05).map((p) => ({ q: p.q, v: p.v / r.meta.series_cells }));
        const tt = r.timeseries.filter((p) => p.T !== null).map((p) => ({ t: p.t / 60, T: p.T }));
        return (
          <>
            <PageHead title="AI health analysis" sub="State of health from the XGBoost model with a conformal 90 % interval; remaining life from a prototype degradation fit." />
            <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
              <div className="panel panel-pad flex flex-col items-center">
                <Gauge soh={r.soh.soh} lo={r.soh.lo} hi={r.soh.hi} />
                <dl className="mt-2 w-full space-y-1.5 text-xs">
                  <div className="flex justify-between"><dt className="text-fog-400">SOH confidence (±2.5 pts)</dt><dd className="num">{r.soh.confidence.value.toFixed(0)}% · {r.soh.confidence.band.toLowerCase()}</dd></div>
                  {r.soh.baseline_ridge !== null && <div className="flex justify-between"><dt className="text-fog-400">Baseline ridge model</dt><dd className="num">{r.soh.baseline_ridge.toFixed(1)}%</dd></div>}
                  <div className="flex justify-between"><dt className="text-fog-400">In training distribution</dt><dd>{r.soh.ood ? <span className="text-amber">no</span> : "yes"}</dd></div>
                  <div className="flex justify-between"><dt className="text-fog-400">Missing inputs</dt><dd className="num">{(r.soh.missing_fraction * 100).toFixed(0)}%</dd></div>
                </dl>
              </div>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <Stat label="Remaining useful life" value={(r.rul.capped ? "≥" : "") + fmt.int(r.rul.rul_cycles)} unit="cycles" sub={`P10 ${fmt.int(r.rul.rul_p10)} · P90 ${fmt.int(r.rul.rul_p90)}`} />
                <Stat label="Degradation rate" value={fmt.n(r.rul.degradation_rate_per_100, 2)} unit="% / 100 cyc" sub={<Grade g={r.fingerprint.dimensions.degradation.grade} />} />
                <div className="panel panel-pad"><div className="text-xs text-fog-400">Thermal risk</div><div className="mt-2"><RiskChip risk={r.fingerprint.thermal_risk} /></div><div className="mt-2 text-xs text-fog-400">{r.fingerprint.dimensions.thermal.display ?? "not measured"}</div></div>
                <div className="panel panel-pad"><div className="text-xs text-fog-400">Power capability</div><div className="mt-2"><Grade g={r.fingerprint.power_capability} invert /></div><div className="mt-2 text-xs text-fog-400">{r.fingerprint.dimensions.power.display ?? "not measured"}</div></div>
                <div className="panel panel-pad sm:col-span-2 xl:col-span-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h2 className="h-section">SOH trajectory and RUL forecast</h2>
                    <span className="text-xs text-fog-400">Method: {r.rul.method.replace(/_/g, " ")} · {r.rul.status.toLowerCase()} · {r.rul.n_history ?? 0} ageing points</span>
                  </div>
                  <RulChart r={r} />
                </div>
              </div>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <div className="panel panel-pad">
                <h2 className="h-section">Discharge curve</h2>
                <p className="text-xs text-fog-400">Cell voltage against charge removed — the slope (dV/dQ) is one of the model's strongest SOH signals.</p>
                {ts.length ? (
                  <ResponsiveContainer width="100%" height={240}>
                    <LineChart data={ts} margin={{ top: 10, right: 16, bottom: 16, left: 0 }}>
                      <CartesianGrid strokeDasharray="2 4" />
                      <XAxis dataKey="q" type="number" tickFormatter={(x) => x.toFixed(2)} label={{ value: "Ah discharged", position: "insideBottom", offset: -8, fill: "#66779A", fontSize: 11 }} />
                      <YAxis domain={["auto", "auto"]} unit=" V" width={52} tickFormatter={(x) => x.toFixed(2)} />
                      <Tooltip {...tip} formatter={(v: any) => `${Number(v).toFixed(3)} V/cell`} labelFormatter={(l) => `${Number(l).toFixed(3)} Ah`} />
                      <Line dataKey="v" stroke="#4FC3E0" dot={false} strokeWidth={2} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : <p className="mt-6 text-sm text-fog-500">No time series for this input (manual entry).</p>}
              </div>
              <div className="panel panel-pad">
                <h2 className="h-section">Temperature during test</h2>
                <p className="text-xs text-fog-400">Heating per unit load feeds the thermal score and the safety screen.</p>
                {tt.length ? (
                  <ResponsiveContainer width="100%" height={240}>
                    <LineChart data={tt} margin={{ top: 10, right: 16, bottom: 16, left: 0 }}>
                      <CartesianGrid strokeDasharray="2 4" />
                      <XAxis dataKey="t" type="number" tickFormatter={(x) => x.toFixed(0)} label={{ value: "minutes", position: "insideBottom", offset: -8, fill: "#66779A", fontSize: 11 }} />
                      <YAxis domain={["auto", "auto"]} unit="°" width={40} />
                      <Tooltip {...tip} formatter={(v: any) => `${Number(v).toFixed(1)} °C`} labelFormatter={(l) => `${Number(l).toFixed(1)} min`} />
                      <Line dataKey="T" stroke="#F2B33D" dot={false} strokeWidth={2} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : <p className="mt-6 text-sm text-fog-500">No temperature sensor data — request a thermal observation run.</p>}
              </div>
            </div>
          </>
        );
      }}
    </NeedsResult>
  );
}
