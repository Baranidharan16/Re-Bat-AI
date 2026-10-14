// Thin typed client for the RE-BAT AI backend. The UI renders only what these calls return.

export type Alert = { level: "ALARM" | "WARNING"; code: string; message: string; action: string; t_s?: number };
export type Criterion = {
  metric: string; label: string; value: number | null; display_value: string; kind: "min" | "max";
  poor: number; good: number; weight: number; weight_norm: number; fit: number; impact: number; verified: boolean; phrase: string;
};
export type AppScore = {
  id: string; name: string; short: string; description: string; duty?: string; score: number; fit_score: number;
  value_tier: number | null; status: string; criteria: Criterion[]; reasons_for: string[]; reasons_against: string[];
  gates_failed: string[]; unverified: number; rank?: number; kind: string;
};
export type Dimension = { label: string; value: number | null; unit: string; score: number | null; grade: string; provenance: string; display: string | null };
export type TestRec = { id: string; name: string; description: string; duration_min: number; priority: number; resolves: string[]; reason: string; hardware_command: Record<string, unknown> };
export type Point = { t: number; v: number; i: number; T: number | null; q: number | null };

export type Mineral = {
  symbol: string; name: string; color: string; critical: boolean; part: string; role: string; recovered_as: string;
  new_battery_use: string; india: string; contained_g: number; share_pct: number; recovery_rate: number; recoverable_g: number;
};
export type MineralReport = {
  chemistry: string; chemistry_label: string; family: string; cell_format: string; cell_format_label: string;
  cell_mass_g: number; cells_series: number; cells_parallel: number; n_cells: number; pack_mass_g: number;
  materials: Mineral[]; non_recovered: { key: string; name: string; color: string; contained_g: number; share_pct: number }[];
  totals: { recoverable_g: number; recoverable_pct_of_pack: number; yield_pct_of_recovered_materials: number; critical_contained_g: number;
            critical_recoverable_g: number; lithium_carbonate_equivalent_g: number };
  closed_loop: { new_cells_equivalent: number; limited_by: string; statement: string };
  process: { step: string; detail: string }[]; policy: string; note: string;
};
export type ReuseOption = {
  id: "solar_storage" | "factory_backup" | "household_backup" | "street_light"; name: string; icon: string; description: string;
  score: number; status: string; router_match: string | null; reasons_for: string[]; reasons_against: string[];
  sizing: Record<string, number | string | null>; formula: string;
};
export type Pathway = "REUSE" | "RECYCLE" | "RETEST" | "HOLD";
export type Circular = {
  pathway: Pathway; headline: string; reason: string;
  reuse: { eligible: boolean; best: string; options: ReuseOption[];
           energy: { capacity_ah: number; capacity_source: string; nominal_v: number; usable_wh: number; efficiency: number; depth_of_discharge: number } };
  recycle: MineralReport & { recommended: boolean };
  loop: { steps: string[]; current: number };
  pack: { chemistry: string; chemistry_label: string; cell_format: string; cell_format_label: string; n_cells: number; pack_mass_g: number };
  parameters: Param[];
  ai: { soh: number; soh_lo: number; soh_hi: number; rul_cycles: number; confidence: number };
};
export type Mechanism = { id: string; name: string; explanation: string; evidence: string; severity: number | null; measured: boolean; level: string };
export type Forensic = {
  passport_id: string; evidence_hash: string; primary: string | null; verdict: string; mechanisms: Mechanism[]; unmeasured: string[];
  anomalies: { level: string; code: string; message: string; t_s?: number | null }[];
  data: { source: string; samples: number | null; validation_warnings: string[]; missing_features: string[]; sealed_in_ledger: boolean; model: string };
};

export type EvPart = { id: string; name: string; role: string; material: string; material_name: string; mass_g: number };
export type EvModel = {
  id: string; name: string; vehicle: string; chemistry: string; cell_format: string; cell_shape: "cylindrical" | "pouch" | "prismatic";
  pack_kwh: number; nominal_v: number | null; cells: number | null; config: string; modules: number | null;
  visual: { modules: [number, number]; cells: [number, number] }; source: string; mass_note: string;
  cell_mass_g: number; pack_mass_g: number; parts: EvPart[]; minerals: MineralReport; pack_metal_totals_g: Record<string, number>; note: string;
};
export type Param = { id: string; name: string; value: number | string | null; unit: string; sensor: string; grade: string; note: string };

export type Analysis = {
  battery_id: string; source: string; data_label: string; generated_at: string;
  meta: { series_cells: number; nominal_capacity_ah: number };
  model: { name: string; version: string; status: string; data_source: string };
  validation?: { warnings: string[]; actions: string[]; rows_in: number; rows_out: number } | null;
  safety: { status: "OK" | "WARNING" | "ALARM"; alerts: Alert[]; disclaimer: string };
  measurements: Record<string, number | string | null>;
  features: Record<string, number | null>;
  missing_features: string[];
  soh: { soh: number; lo: number; hi: number; baseline_ridge: number | null; model_variant: string; ood: boolean; missing_fraction: number;
         confidence: { value: number; band: string; sigma: number; notes: string[] }; screening: { range: string; label: string; disclaimer: string } };
  rul: { rul_cycles: number; rul_p10: number; rul_p90: number; eol_soh: number; method: string; cycle_now?: number; cycle_known: boolean;
         degradation_rate_per_100: number | null; capped?: boolean; status: string; confidence: number; n_history?: number;
         trajectory: { cycle: number; p10: number; p50: number; p90: number; forecast: boolean }[];
         history: { cycle: number; soh: number; lo: number; hi: number }[] };
  fingerprint: { dimensions: Record<string, Dimension>; metrics: Record<string, number | string | null>; thermal_risk: string; power_capability: string;
                 radar: { axis: string; key: string; score: number | null }[]; summary: Record<string, string> };
  router: { ranking: AppScore[]; pathways: AppScore[]; decision: { id: string; name: string; score: number | null; kind: string; provisional?: string | null };
            top: string; decision_margin: number; method: string };
  explanation: {
    soh: { method: string; base_value: number; top: { feature: string; label: string; contribution: number; value: number | null; unit: string; measured: boolean }[] };
    applications: { summary: string; recommended: string; contrast: string;
      per_application: Record<string, { name: string; score: number; factors: { label: string; impact: number; fit: number; value: string; requirement: string; verified: boolean }[] }> };
  };
  confidence: { value: number; band: string; components: Record<string, number>; formula: string };
  adaptive: { uncertainty_sources: { source: string; severity: number; message: string }[]; required: boolean; blocked_by_safety: boolean;
              recommended: TestRec | null; alternatives: TestRec[]; message: string };
  evidence: any[];
  timeseries: Point[];
  demo?: { label: string; title: string; story: string; tests_run: number; note: string };
  ledger?: { forecast_id: number; idx: number; block_hash: string; merkle_root: string; stored_readings: number };
  live?: { session_id: string; window_readings: number; final: boolean; test: string };
  csv?: { filename: string; tests_in_file: number; analysed_cycle: number };
  circular: Circular;
  forensics: Forensic;
  passport_block?: { idx: number; block_hash: string; prev_hash: string; merkle_root: string; created_at: string; existing: boolean };
};

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) { super(message); }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "Backend unreachable. Start it with: uvicorn app.main:app --port 8000");
  }
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const d = body?.detail;
    const msg = typeof d === "string" ? d : d?.message ?? `Request failed (${res.status})`;
    throw new ApiError(res.status, msg, d);
  }
  return body as T;
}

const json = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  health: () => req<any>("/api/v1/health"),
  modelStatus: () => req<any>("/api/v1/model/status"),
  demoList: () => req<{ battery_id: string; label: string; title: string; story: string }[]>("/api/v1/demo/batteries"),
  demo: (id: string) => req<Analysis>(`/api/v1/demo/batteries/${id}/analysis`),
  demoReset: (id: string) => req<Analysis>(`/api/v1/demo/batteries/${id}/reset`, { method: "POST" }),
  manual: (body: Record<string, unknown>) => req<Analysis>("/api/v1/analyze/manual", json(body)),
  csv: (file: File, meta: { battery_id: string; series_cells: number; nominal_capacity_ah: number }) => {
    const fd = new FormData();
    fd.append("file", file);
    Object.entries(meta).forEach(([k, v]) => fd.append(k, String(v)));
    return req<Analysis>("/api/v1/analyze/csv", { method: "POST", body: fd });
  },
  requestTest: (battery_id: string, test_id: string, context: "demo" | "live") =>
    req<any>("/api/v1/tests/request", json({ battery_id, test_id, context })),
  simStart: (profile_id: string, speed_hz = 8, test_id?: string) => req<any>("/api/v1/live/sim/start", json({ profile_id, speed_hz, test_id })),
  liveStop: (id: string) => req<any>(`/api/v1/live/${id}/stop`, { method: "POST" }),
  liveSessions: () => req<any[]>("/api/v1/live/sessions"),
  ledger: (limit = 50) => req<any[]>(`/api/v1/ledger?limit=${limit}`),
  ledgerVerify: () => req<any>("/api/v1/ledger/verify"),
  batteries: () => req<any[]>("/api/v1/batteries"),
  forecasts: (id: string) => req<any[]>(`/api/v1/batteries/${id}/forecasts`),
  testsCatalog: () => req<any>("/api/v1/config/tests"),
  screening: () => req<any>("/api/v1/config/screening"),
  bridgeStatus: () => req<any>("/api/v1/bridge/status"),
  bridgeStart: (body: Record<string, unknown>) => req<any>("/api/v1/bridge/start", json(body)),
  bridgeDiscover: () => req<any>("/api/v1/bridge/discover", { method: "POST" }),
  bridgeStop: () => req<any>("/api/v1/bridge/stop", { method: "POST" }),
  bridgeCloseWindow: () => req<any>("/api/v1/bridge/close-window", { method: "POST" }),
  circularConfig: () => req<any>("/api/v1/circular/config"),
  setPack: (body: { chemistry: string; cell_format: string }) => req<any>("/api/v1/circular/pack", json(body)),
  minerals: (q: { series_cells: number; nominal_capacity_ah: number; chemistry?: string; cell_format?: string }) =>
    req<MineralReport>(`/api/v1/circular/minerals?${new URLSearchParams(Object.entries(q).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))}`),
  forensics: (id: string) => req<any>(`/api/v1/forensics/${encodeURIComponent(id)}`),
  connectInfo: () => req<any>("/api/v1/hardware/connect-info"),
  evModels: () => req<{ id: string; name: string; vehicle: string; chemistry: string; cell_shape: string; pack_kwh: number; cells: number | null }[]>("/api/v1/ev-models"),
  evModel: (id: string) => req<EvModel>(`/api/v1/ev-models/${id}`),
  chatStatus: () => req<{ provider: string; key_configured: boolean }>("/api/v1/chat/status"),
  chat: (message: string, history: { role: string; text: string }[], context: Record<string, unknown>) =>
    req<{ answer: string; provider: string; online: boolean; note?: string }>("/api/v1/chat", json({ message, history, context })),
  modelFingerprint: () => req<any>("/api/v1/ledger/model-fingerprint"),
  rigs: () => req<{ connected: number; rigs: any[] }>("/api/v1/hardware/rigs"),
  rigCommand: (id: string, cmd: string) => req<any>(`/api/v1/hardware/${encodeURIComponent(id)}/command`, json({ cmd })),
};

/** Live feed for one battery: WebSocket first (reconnects), Server-Sent Events if WebSockets are blocked.
 *  Returns a close function. */
export function openLiveFeed(id: string, on: { event: (e: any) => void; status: (s: "ws" | "sse" | "down") => void }): () => void {
  let closed = false, es: EventSource | null = null, ws: WebSocket | null = null, everOpened = false, timer: number | undefined;
  const path = `/api/v1/live/${encodeURIComponent(id)}`;
  const sse = () => {
    if (closed) return;
    es = new EventSource(`${path}/stream`);
    es.onopen = () => on.status("sse");
    es.onerror = () => on.status("down");
    es.onmessage = (m) => on.event(JSON.parse(m.data));
  };
  const connect = () => {
    if (closed) return;
    try {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}/ws`);
    } catch { sse(); return; }
    ws.onopen = () => { everOpened = true; on.status("ws"); };
    ws.onmessage = (m) => { const e = JSON.parse(m.data); if (e.type !== "keepalive" && e.type !== "error") on.event(e); };
    ws.onclose = () => {
      if (closed) return;
      on.status("down");
      if (everOpened) timer = window.setTimeout(connect, 1500); else sse();
    };
  };
  connect();
  return () => { closed = true; window.clearTimeout(timer); ws?.close(); es?.close(); };
}

export const fmt = {
  n: (x: number | null | undefined, d = 1) => (x === null || x === undefined || Number.isNaN(x) ? "—" : x.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d })),
  int: (x: number | null | undefined) => (x === null || x === undefined ? "—" : Math.round(x).toLocaleString()),
};
