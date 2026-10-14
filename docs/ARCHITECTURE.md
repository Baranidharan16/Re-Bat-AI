# RE-BAT AI — Architecture & Implementation Log

## A. Architecture

Three tiers, one data path for every input mode:

| Tier | Responsibility |
|---|---|
| **Rig** (ESP32) | Measure V, I, T, cell taps; run REST→PULSE→DISCHARGE→REST; enforce its own safety limits; post JSON; poll for AI test requests |
| **Backend** (FastAPI) | Ingest → validate → features → models → fingerprint → router → XAI → confidence → adaptive test; SSE stream; persist forecast windows; ledger |
| **Dashboard** (React) | Renders only backend output; demo / CSV / manual / live selection; request tests |

Key engineering decisions

1. **One canonical time-series schema** (`timestamp, voltage, current, temperature, capacity, cycle,
   internal_resistance, cell_v_min, cell_v_max`). The ESP32, the simulator, CSV and public datasets all map
   onto it, so the AI never changes when the source does.
2. **Features normalised per cell and per nominal Ah** → one model serves a 1-cell lab test or a 3S/96S module.
3. **Missing sensors are NaN, not zero.** XGBoost handles them; the confidence and adaptive-testing layers
   read them as "evidence still missing".
4. **Uncertainty is learned, then calibrated**: multi-quantile XGBoost + split-conformal correction on
   validation batteries; coverage reported on test batteries.
5. **Routing is a transparent requirement matcher, not a fake classifier.** There is no labelled dataset of
   second-life outcomes, so training a ranker would fabricate accuracy. The engine is a weighted geometric
   mean of per-requirement fits on ML outputs; it can be replaced by a learned model once outcomes exist.
6. **Storage only after forecast.** Live readings stay in memory until their window is forecast; then the
   readings + forecast are written in one transaction with a ledger block.

## B. Folder structure

```
backend/
  app/
    main.py                 FastAPI app, error handlers, serves frontend/dist
    config.py               thresholds (confidence bands, EOL, safety limits, live windows)
    db.py                   SQLite schema + helpers
    config_files/           applications.json · diagnostic_tests.json · screening.json
    api/routes.py           REST + SSE endpoints
    schemas/models.py       Pydantic contracts (TelemetryReading = ESP32 payload)
    ml/
      data_ingestion.py     validation, cleaning, aliases, NASA/own-data loaders
      feature_engineering.py 22 model features + SPOT_FEATURES + info
      generate_dataset.py   simulated training population
      train_model.py        baseline + XGBoost point/quantile + conformal + OOD + spot variant
      evaluate_model.py     MAE/RMSE/R², interval coverage, Top-1/Top-3 helper
      predict.py            SOHPredictor (variants, OOD, TreeSHAP)
      rul.py                prototype RUL with Monte-Carlo band
      temporal_model.py     1D-CNN architecture, resampler, fusion, training (torch optional)
      bootstrap.py          ensure a compatible model exists
    services/
      pipeline.py           orchestrates every layer → one result object
      fingerprint.py · suitability.py · explain.py · confidence.py
      adaptive_testing.py · safety.py · demo_service.py · live.py · ledger.py
    simulation/battery_sim.py · demo_profiles.py
  tools/esp32_emulator.py   posts simulated rig data through the hardware endpoint
  tests/test_pipeline.py
  artifacts/                trained models + model_card.json + reference distributions
frontend/src/{pages,components,lib}
firmware/rebat_esp32/{rebat_esp32.ino,config.h}
hardware/README.md
```

## C. Technology stack

Python 3.10+, FastAPI, Pydantic 2, NumPy/Pandas/SciPy, scikit-learn, XGBoost (TreeSHAP via `pred_contribs`),
SQLite (WAL), Server-Sent Events · React 18 + TypeScript, Vite, Tailwind, Recharts, lucide-react ·
ESP32 Arduino (ArduinoJson, INA226, DallasTemperature, ADS1X15). PyTorch optional for the CNN.

## D. Database schema (SQLite)

| Table | Contents |
|---|---|
| `batteries` | battery_id, series_cells, nominal_capacity_ah, nominal_voltage, chemistry, source (ESP32/LIVE_SIM) |
| `forecasts` | per forecast window: SOH + interval, confidence, RUL, top application, decision, safety status, n_readings, is_final, block_index, full result JSON |
| `readings` | every stored real-time sample, linked to its forecast, with its SHA-256 leaf hash |
| `ledger_blocks` | idx, created_at, prev_hash, merkle_root, payload_hash, payload_json, nonce, block_hash |
| `test_requests` | AI-requested tests for rigs: pending → sent → done / cancelled / refused_by_safety |

Demo, CSV and manual analyses are **not** persisted.

## E. API (v1)

| Method & path | Purpose |
|---|---|
| `GET /health`, `GET /model/status` | liveness; model card, importance, sub-model status |
| `GET /config/applications · /config/tests · /config/screening` | requirement profiles, test catalog, screening ranges |
| `GET /demo/batteries`, `GET /demo/batteries/{id}/analysis`, `POST …/reset` | demo mode |
| `POST /analyze/manual`, `POST /analyze/csv`, `GET /samples/csv` | ephemeral analyses |
| `POST /tests/request` `{battery_id,test_id,context}` | demo: run on simulator, return before/after; live: queue for rig or start simulator |
| `POST /hardware/ingest` (single or `{"readings":[…]}`) | ESP32 telemetry (optional `X-Device-Key`) |
| `GET /hardware/{id}/commands`, `POST /hardware/{id}/commands/{cid}/ack` | rig command channel |
| `POST /live/sim/start`, `POST /live/{id}/stop`, `GET /live/sessions`, `GET /live/{id}/latest` | live sessions |
| `GET /live/{id}/stream` | SSE: `snapshot`, `reading`, `forecast`, `status` events |
| `GET /batteries`, `GET /batteries/{id}/forecasts` | stored real-time history |
| `GET /ledger`, `GET /ledger/verify` | blocks; full recomputation (detects edits to readings, forecasts or blocks) |
| `POST /bridge/start · /bridge/stop · /bridge/close-window`, `GET /bridge/status` | poll the RMK-REVOLT ESP32 Battery Lab (`GET <esp32>/api/data`) and feed it to the live pipeline |
| `WS /hardware/ws` | push ingest: Battery Lab JSON or canonical TelemetryReading, one message per reading |

## F. ML pipeline

Raw → `validate_and_clean` (aliases, units, sign, plausibility, coulomb counting) → `extract_features`
→ SOH model (point + 5/50/95 % quantiles + conformal q̂ + IsolationForest/missing-fraction OOD) →
RUL (history fit or population prior, 300–400 Monte-Carlo curves) → fingerprint → router → TreeSHAP +
requirement explanations → confidence → adaptive test.

Training: battery-level `GroupShuffleSplit` 70/15/15 (asserted leakage-free), early stopping on validation
batteries, conformal calibration on validation batteries, metrics on test batteries, model card written by code.

## G. Features (22)

Cell voltage mean/min/max/std · test C-rate · mean temperature · temperature rise · rise rate · thermal
response (°C per C²·h) · dV/dQ and dV/dt (middle 60 % of discharge) · discharge duration · Ah and Wh
discharged (normalised) · pulse DC resistance per cell · voltage recovery after load · start/end SOC from
relaxed OCV · SOC window · OCV-window capacity estimate · cycle count · mid-discharge cell imbalance.
Info (not model inputs): pack IR, peak dT/dt, charge duration, coulombic efficiency, sample counts.

## H. Application suitability logic

For each application *a* with criteria *i* (metric, kind min/max, poor, good, weight):

```
fit_i  = max(0.02, smoothstep((x_i − poor_i)/(good_i − poor_i)))      missing x_i → 0.5, flagged unverified
score_a = 100 · exp(Σ w_i ln fit_i / Σ w_i) × value_factor(tier_a)     tiers 1/2/3 → 0.80/0.93/1.00
gates   : thermal_risk HIGH (all) or MEDIUM (indoor, telecom, high-power) → score ≤ 15, "Excluded"
```

Pathways: *Further diagnostics* (low confidence, small margin, missing evidence) and *Recycling* (low SOH,
short RUL, poor thermal, high IR). Decision: recycling if it beats every reuse option; further diagnostics
if no reuse option ≥ 50 or confidence is low and the pathway ≥ 80 (best reuse shown as provisional);
safety alarm → "Safety hold". SOH screening ranges are shown as context only.

## I. Frontend architecture

`AnalysisProvider` holds the current analysis (demo/CSV/manual/live) → all pages render it.
Pages: Landing · Analyze · Overview · Live (SSE) · Health & RUL · Fingerprint · Router · Why (XAI) ·
Diagnostic assistant · Ledger · Model status. No value is computed or hard-coded in the UI.

---

## Phase log

| Phase | Delivered | Still simulated / next |
|---|---|---|
| 1 Architecture | modular backend/frontend/firmware layout, config files | — |
| 2 Ingestion | canonical schema, validation report, aliases, NASA + own-data loaders | test loaders on real files |
| 3 Features | 22 normalised features + info, missing-aware | add charge-side ICA features |
| 4 Baseline | ridge pipeline, MAE 2.62 on test batteries | — |
| 5 XGBoost | point + multi-quantile + conformal + OOD + spot variant, MAE 1.13 | trained on **simulated** data |
| 6 Temporal | 1D-CNN, resampler, fusion, train script | not trained (needs torch + real data) |
| 7 RUL | power-law fit / population prior, MC band | prototype; validate on ageing data |
| 8 Fingerprint | 11 dimensions with provenance + radar | percentiles vs simulated population |
| 9 Router | 7 applications + 2 pathways, gates, value tiers | weights need expert/field calibration |
| 10 XAI | TreeSHAP + requirement impacts + generated rationale | — |
| 11 Confidence | interval-derived, OOD-penalised, composite | calibrate tolerance with real data |
| 12 Adaptive testing | source diagnosis, priority, evidence merge, closed loop | real rig execution |
| 13 REST API | full v1 API, errors, OpenAPI at /docs | auth beyond device key |
| 14 Live | SSE, rolling/final forecasts, store-after-forecast, ledger | — |
| 15 Frontend | 11 pages | — |
| 16 Hardware | firmware, wiring, BOM, emulator; bridge to the team's ESP32 Battery Lab (HTTP poll + WebSocket), MQ-5 gas safety signal | calibrate ACS712 and gas thresholds on the real rig |
