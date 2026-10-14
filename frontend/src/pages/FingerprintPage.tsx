import { PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer } from "recharts";
import { useAnalysis } from "../lib/store";
import { Grade, Meter, NeedsResult, PageHead, RiskChip } from "../components/ui";

const INVERT = new Set(["power"]);
const ORDER = ["soh", "rul", "capacity", "resistance", "power", "thermal", "degradation", "efficiency", "imbalance", "voltage", "cycles"];

export default function FingerprintPage() {
  const { result, loading, error } = useAnalysis();
  return (
    <NeedsResult result={result} loading={loading} error={error}>
      {(r) => {
        const fp = r.fingerprint;
        const radar = fp.radar.map((d) => ({ axis: d.axis, score: d.score ?? 0, missing: d.score === null }));
        return (
          <>
            <PageHead title="Battery fingerprint" sub="Beyond a single health percentage. Scores are 0–100 where higher is better for reuse; resistance, thermal and imbalance are percentiles of the reference population." />
            <div className="grid gap-4 lg:grid-cols-[1fr_1.25fr]">
              <div className="panel panel-pad">
                <div className="flex items-center justify-between">
                  <h2 className="h-section">{r.battery_id}</h2>
                  <span className="text-xs text-fog-400">thermal risk <RiskChip risk={fp.thermal_risk} /></span>
                </div>
                <ResponsiveContainer width="100%" height={360}>
                  <RadarChart data={radar} outerRadius="72%">
                    <PolarGrid stroke="#2A3B5C" />
                    <PolarAngleAxis dataKey="axis" tick={({ payload, x, y, textAnchor }: any) => {
                      const m = radar.find((d) => d.axis === payload.value)?.missing;
                      return <text x={x} y={y} textAnchor={textAnchor} fontSize={11} fill={m ? "#66779A" : "#B7C3D6"}>{payload.value}{m ? " (n/m)" : ""}</text>;
                    }} />
                    <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                    <Radar dataKey="score" stroke="#B6F23A" fill="#B6F23A" fillOpacity={0.18} strokeWidth={2} isAnimationActive />
                  </RadarChart>
                </ResponsiveContainer>
                <p className="text-xs text-fog-500">n/m = not measured; plotted at zero and scored neutral by the router.</p>
              </div>

              <div className="panel overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-ink-800 text-left text-xs text-fog-400">
                    <tr><th className="px-4 py-2.5 font-medium">Dimension</th><th className="px-4 py-2.5 font-medium">Measured / predicted</th><th className="w-32 px-4 py-2.5 font-medium">Score</th><th className="px-4 py-2.5 font-medium">Grade</th></tr>
                  </thead>
                  <tbody>
                    {ORDER.filter((k) => fp.dimensions[k]).map((k) => {
                      const d = fp.dimensions[k];
                      const val = d.display ?? (d.value === null ? "—" : `${typeof d.value === "number" ? d.value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : d.value} ${d.unit}`);
                      return (
                        <tr key={k} className="border-t border-ink-700 align-top">
                          <td className="px-4 py-3"><div>{d.label}</div><div className="text-2xs text-fog-500">{d.provenance}</div></td>
                          <td className="num px-4 py-3 text-fog-300">{val}</td>
                          <td className="px-4 py-3">{d.score === null ? <span className="text-xs text-fog-500">—</span> : <><div className="num text-xs">{d.score.toFixed(0)}</div><Meter value={d.score} tone="data" height={4} /></>}</td>
                          <td className="px-4 py-3">{d.score === null && d.value !== null ? <span className="text-xs text-fog-500">—</span> : <Grade g={d.grade} invert={INVERT.has(k)} />}</td>
                        </tr>
                      );
                    })}
                    <tr className="border-t border-ink-700"><td className="px-4 py-3">Confidence</td><td className="num px-4 py-3 text-fog-300">{r.confidence.value.toFixed(0)}% overall · SOH ±{(r.soh.hi - r.soh.lo).toFixed(1)} pts</td><td className="px-4 py-3"><Meter value={r.confidence.value} tone="volt" height={4} /></td><td className="px-4 py-3"><Grade g={r.confidence.band} /></td></tr>
                  </tbody>
                </table>
              </div>
            </div>
          </>
        );
      }}
    </NeedsResult>
  );
}
