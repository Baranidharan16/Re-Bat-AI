import type { Analysis } from "./api";
import type { Twin } from "../three/PackViewer";

/** Digital-twin inputs from an analysis: health colours the cells, temperature drives the heat map, current the power flow. */
export function twinFromAnalysis(a: Analysis | null): Twin {
  if (!a) return {};
  const m = a.measurements ?? {};
  return {
    soh: a.soh.soh,
    tempC: m.t_max != null ? Number(m.t_max) : null,
    currentA: m.i_mean != null ? Number(m.i_mean) : 1,
    imbalanceMv: (a.fingerprint.metrics.imbalance_mv as number | null) ?? null,
    alarm: a.safety.status === "ALARM",
  };
}

/** Compact battery summary sent to the AI assistant. */
export function chatContext(a: Analysis | null, extra: Record<string, unknown> = {}) {
  if (!a) return extra;
  const c = a.circular;
  return {
    battery_id: a.battery_id, source: a.data_label, series_cells: a.meta.series_cells, nominal_capacity_ah: a.meta.nominal_capacity_ah,
    soh: a.soh.soh, soh_lo: a.soh.lo, soh_hi: a.soh.hi, rul_cycles: a.rul.rul_cycles, confidence: a.confidence.value,
    safety: a.safety.status, alerts: a.safety.alerts.map((x) => x.message),
    circular: { pathway: c?.pathway, headline: c?.headline, reason: c?.reason,
      reuse_options: c?.reuse.options.map((o) => ({ name: o.name, score: o.score, status: o.status, sizing: o.sizing })) },
    parameters: c?.parameters, chemistry_label: c?.pack.chemistry_label,
    minerals: c?.recycle.materials.map((m) => ({ name: m.name, symbol: m.symbol, contained_g: m.contained_g, recoverable_g: m.recoverable_g, part: m.part })),
    minerals_totals: c?.recycle.totals, forensic_verdict: a.forensics?.verdict, passport_id: a.forensics?.passport_id,
    passport_block: a.passport_block ?? a.ledger, top_shap_drivers: a.explanation.soh.top.slice(0, 5).map((t) => ({ label: t.label, contribution: t.contribution })),
    model: a.model, ...extra,
  };
}
