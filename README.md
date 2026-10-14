# RE-BAT AI 3.0 — Reuse or Recycle, decided live, with a 3D digital twin

> **RMK-REVOLT**: An innovative EV battery circularity initiative focused on assessing, monitoring, and repurposing used lithium-ion EV batteries for high-value second-life applications.

AI decision engine for retired EV lithium-ion batteries. An ESP32 rig streams the battery over a **WebSocket**;
the AI predicts SOH and remaining life, builds a battery **fingerprint**, and decides the battery's next life:

* **REUSE** — solar energy storage · factory / industrial backup · household backup · rural street light
  (each scored by the AI router and sized from the measured capacity: panel watts, backup minutes, nights of light)
* **RECYCLE** — every mineral inside the battery (Li, Ni, Co, Mn, graphite, Cu, Al, Fe/P for LFP) with grams
  contained and recoverable, and how it goes back into a **new EV cell** — the closed loop that cuts import dependence
* **RETEST** when the AI is not confident yet, **HOLD** on a safety alarm

Every test window is sealed in a hash-chained ledger, which powers the **battery forensics** page:
ageing mechanism, anomalies, evidence hash, chain of custody and tamper check.

```
ESP32 rig ══ WebSocket ══► FastAPI ─► safety ─► features ─► XGBoost SOH (+interval, OOD, TreeSHAP) ─► RUL
   ▲  (verdict + commands)       │                                                         │
   └─────────────────────────────┤        fingerprint ─► router ─► REUSE / RECYCLE engine ◄┘
                                 ▼                                   │            │
             React dashboard ◄─ WebSocket/SSE ◄──────────────── sizing      minerals + closed loop
                                 │
                 SQLite ─► ledger block (Merkle root, SHA-256 chain) ─► forensics / battery passport
```

## What is new in 3.0

| Feature | Where |
|---|---|
| **3D EV battery explorer / digital twin** (three.js): tap to explode the pack into top cover, cooling plate, busbars, modules, BMS and base frame; module zoom; cut-away cell; power flow; thermal map + coolant flow; minerals per part | page **3D battery twin**, landing page, overview, live page — `frontend/src/three/PackViewer.ts` |
| Real EV packs to explore: Tesla Model 3 LR (4,416 × 2170), Nissan Leaf 40 kWh (192 pouch), Tata Nexon EV 45 kWh (LFP prismatic), our 3-cell rig | `backend/app/config_files/ev_models.json`, `GET /api/v1/ev-models/{id}` |
| Digital twin: cells coloured by the AI's SOH and cell imbalance, heat map from measured temperature, pulses from measured current, red pulse on safety alarm | `frontend/src/lib/twin.ts` |
| Reuse recommendation from the **10 measured parameters** (voltage, current, power, capacity, energy, resistance, temperature, imbalance, efficiency, gas) + SOH, RUL | page **Reuse recommendation**, `circular.parameters()` |
| **AI battery assistant** (Google Gemini; offline answers without a key or internet) | chat button on every dashboard page — `services/assistant.py`, `POST /api/v1/chat` |
| **Passport block for every battery** in the SHA-256 ledger, with a fingerprint of the model's hyperparameters + weights | `ledger.seal_passport()`, `GET /api/v1/ledger/model-fingerprint`, page **Battery ledger** |

### Gemini key

Put the key in `backend/.env` (already done in this folder, see `.env.example`):
```
GEMINI_API_KEY=your-key
```
`.env` is git-ignored — never commit or share it. Without a key or internet the assistant answers from the battery data (offline mode).

## What is new in 2.0

| Feature | Where |
|---|---|
| Reuse / recycle pathway for every analysis (demo, CSV, manual, live) | `backend/app/services/circular.py`, page **Reuse or recycle** |
| Mineral breakdown per element, chemistry/cell-format selector, closed loop | `config_files/circular.json`, page **Battery minerals** |
| Battery forensics: mechanisms, anomalies, evidence hash, custody, tamper check | `services/forensics.py`, page **Battery forensics** |
| ESP32 WebSocket connector: hello, telemetry, idle status, AI verdict to the OLED, dashboard commands | `api/routes.py` (`/api/v1/hardware/ws`), `services/esp32_hub.py` |
| Live dashboard over WebSocket (SSE fallback) + street-light panel (LDR, PIR, IR, lamp) | page **Live ESP32** |
| New firmware for the actual rig (ACS712, voltage sensor, OLED, MQ, LDR, PIR, IR, 2 relays) | `firmware/rebat_ws_rig/` |
| WebSocket emulator (no hardware needed) | `backend/tools/esp32_ws_emulator.py` |
| Battery F — end of life → RECYCLE demo | `simulation/demo_profiles.py` |

## Run it

**One command** (needs Python 3.10+; Node 18+ only if you want to rebuild the UI):

```bash
./run.sh          # macOS / Linux
run.bat           # Windows
```

Open **http://localhost:8000** (API docs at `/docs`). The built dashboard ships in `frontend/dist`, so Node
is optional. On first start `app.ml.bootstrap` checks the shipped model and retrains it (≈1–2 min) if your
xgboost / scikit-learn versions differ.

**Manual / development mode**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.ml.generate_dataset      # simulated training data  (optional: shipped)
python -m app.ml.train_model           # baseline + XGBoost + spot model + conformal intervals
python -m pytest -q                    # 6 integration tests
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

cd ../frontend && npm install && npm run dev            # http://localhost:5173 (proxies /api)
```

## Connect the ESP32 over WebSocket (new firmware)

1. Laptop and ESP32 on the **same Wi-Fi** (phone hotspot is easiest). Start RE-BAT AI (`run.bat` / `./run.sh`).
2. Open **Live ESP32**. The *ESP32 WebSocket connector* panel shows the address to use, e.g.
   `ws://192.168.1.10:8000/api/v1/hardware/ws`.
3. In `firmware/rebat_ws_rig/config.h` set `WIFI_SSID`, `WIFI_PASSWORD`, `WS_HOST` (the laptop IP from step 2).
   Install the libraries listed at the top of `rebat_ws_rig.ino`, select **ESP32 Dev Module**, flash.
4. The panel turns green: "Rig RB-001 connected". Press **Quick test (2 min)** (or put a battery in the bay — the IR
   sensor starts it). Readings stream live; every forecast is routed to REUSE or RECYCLE, sealed in the ledger, and
   the verdict appears on the ESP32's OLED. **Street light auto / Lamp on / Lamp off / Stop all** go straight to the board.
5. Allow port 8000 in the Windows firewall the first time (Private network).

No board? `python backend/tools/esp32_ws_emulator.py` (add `--profile RB-F06` for an end-of-life battery that goes to recycling).

### WebSocket protocol (`/api/v1/hardware/ws`)

| Direction | Message |
|---|---|
| ESP32 → server | `{"type":"hello","battery_id":"RB-001","firmware":"rebat-ws 2.0","ip":"…"}` |
| ESP32 → server | telemetry: `{"battery_id","t_s","voltage","current","temperature","capacity","internal_resistance","cell_v_min","cell_v_max","gas_v","phase","ldr","dark","pir","battery_present","lamp_on","load_on","rig_state"}` |
| ESP32 → server | idle sensors: `{"type":"status","battery_id",…,"ldr","dark","pir","battery_present","lamp_on"}` (no test window) |
| server → ESP32 | `{"type":"ack","ok":true,"buffer":57}` per reading |
| server → ESP32 | `{"type":"verdict","pathway":"REUSE","best":"Solar energy storage","soh":77.0,"rul_cycles":1690,"block":12,…}` after each forecast |
| server → ESP32 | `{"type":"command","cmd":"lamp_on"}` — `start_test`, `quick_test`, `stop`, `lamp_on`, `lamp_off`, `lamp_auto`, `load_on`, `load_off` |

REST helpers: `GET /api/v1/hardware/connect-info`, `GET /api/v1/hardware/rigs`, `POST /api/v1/hardware/{id}/command`,
`GET /api/v1/circular/minerals`, `POST /api/v1/circular/pack`, `GET /api/v1/forensics/{id}`, dashboard feed `WS /api/v1/live/{id}/ws`.

## Older ESP32 Battery Lab firmware (HTTP polling)

Your existing ESP32 page (`http://<esp32-ip>/`) keeps working unchanged. RE-BAT AI reads the same
`GET /api/data` JSON it uses (`battery_v, current_a, temperature_c, gas_v, capacity_mah, elapsed_s`)
and runs it through the full AI pipeline.

1. Put the laptop and the ESP32 on the **same Wi-Fi** (phone hotspot is easiest).
2. Start RE-BAT AI (`./run.sh` or `run.bat`). The browser opens on **Live ESP32** and the backend
   connects to the ESP32 by itself — first at `http://10.55.137.107`, and if that address does not
   answer it scans the Wi-Fi network for the ESP32 and remembers the address it finds
   (`backend/data/esp32.json`). Nothing has to be typed.
3. Battery details (ID, cells in series, nominal capacity, cycle count) are under **Settings** on the
   Live ESP32 page; they are saved too. The top bar shows the ESP32 status on every page.
4. Run your discharge. The AI forecasts every ~60 readings; after a discharge the test closes itself
   after 120 s of rest (or press **End test now**) with a final forecast that is stored and sealed.

Notes
- *Flip sign* is on by default because the ACS712 on the lab rig reads negative while discharging.
  If the Current tile shows a negative value during discharge, untick it and reconnect.
- The MQ-5 gas output is used as a **relative** safety signal: +0.4 V above its start value warns,
  +0.8 V raises a safety alarm (uncalibrated; tune in `backend/app/config.py`).
- The rig has no pulse load or cell taps yet, so internal resistance and cell imbalance are reported as
  "not measured" and the AI will recommend a pulse test — expected with this hardware.
- No ESP32 at hand? `python backend/tools/fake_esp32_lab.py --port 8081 --speed 10` serves the same
  `/api/data` format with simulated data; connect to `http://localhost:8081`.
- Firmware that pushes instead of being polled can stream the same JSON to the WebSocket
  `ws://<laptop-ip>:8000/api/v1/hardware/ws` (add `"battery_id"` to each message).

## Demo script for judges (5 minutes)

1. **Landing** — three retired modules, three futures: B → solar storage, C → rural street light, F → recycle.
2. **Live ESP32** — the rig is connected over WebSocket. Press **Quick test**: V, I, temperature, gas stream live;
   cover the LDR and walk past the PIR — the street light switches on. The AI verdict appears on the dashboard and the OLED.
3. **Reuse or recycle** — the pathway, why, and the four reuse applications with sizing (panel watts, backup minutes,
   nights of light).
4. **Battery minerals** — switch to Battery F: every element as a tile, grams recoverable, India supply note, how it is
   recovered and how many new cells' worth of cathode it makes.
5. **Battery forensics** — ageing mechanism, evidence hash, chain of custody, all ledger blocks verified.
6. **Diagnostic assistant** — Battery E (low confidence) → RETEST: the AI asks for the next test instead of guessing.

## Current model (DEMO — simulated data)

Held-out **test batteries** (battery-level split 58/13/13 modules, 390 test records):

| Model | MAE (SOH pts) | RMSE | R² |
|---|---|---|---|
| XGBoost, time-series features | 1.13 | 1.62 | 0.984 |
| Baseline ridge regression | 2.62 | 3.51 | 0.922 |
| XGBoost spot variant (manual input) | 3.33 | 4.83 | 0.852 |

Conformal 90 % interval: empirical coverage 86.2 %, mean width 5.9 pts.
These numbers prove the pipeline works on **simulated** batteries only — they are not evidence of accuracy
on real retired EV packs. Train on NASA/CALCE/your rig data before drawing conclusions.

> 📖 **Comprehensive ML Model Documentation**: For full mathematical formulations, feature engineering definitions, Split-Conformal calibration details, archetype benchmarks, and TreeSHAP explainability, see [MODEL_README.md](MODEL_README.md).

## What is real, what is simulated

| Component | Status |
|---|---|
| Ingestion, validation, cleaning, feature engineering | Working (CSV, manual, ESP32 JSON, simulator) |
| SOH model (XGBoost + quantile + conformal + OOD + TreeSHAP) | Working; **trained on simulated data** |
| Baseline model, battery-level split, evaluation | Working |
| Temporal 1D-CNN + fusion | Architecture + training code; **not trained** (PyTorch optional) |
| RUL | Power-law fit / population prior with Monte-Carlo band — **prototype** |
| Fingerprint, router, explanations, confidence, adaptive testing | Working, computed per battery |
| Router weights | **Prototype** — no labelled second-life outcomes exist yet (Top-1/Top-3 eval code ready) |
| Live stream (SSE), rolling + final forecasts, storage after forecast, ledger + verify | Working |
| Reuse/recycle pathway, sizing, forensics | Working, computed per battery; reuse thresholds are prototype values |
| Mineral composition | Typical published shares per chemistry/cell format (±20 %) — calibrate with a teardown |
| ESP32 WebSocket connector + emulator | Working and tested with the emulator and automated tests |
| `firmware/rebat_ws_rig` (2.0 rig) | Written for the actual parts list; **not compiled/flashed here** — compile in Arduino IDE first |
| `firmware/rebat_esp32` (1.0 reference) | Written for INA226 + DS18B20 + ADS1115; not flashed/tested |
| Demo batteries A–E and live simulation | **Simulated** (equivalent-circuit + thermal + ageing model) |

## Repository

```
backend/   FastAPI app, ML pipeline, simulator, services, tests, trained artifacts
frontend/  React + TypeScript + Tailwind + Recharts dashboard (dist/ prebuilt)
firmware/  ESP32 Arduino sketch (rebat_esp32/)
hardware/  wiring, BOM, safety notes
docs/      ARCHITECTURE.md — architecture, schema, API, ML pipeline, router logic, phase log
```

## Safety

AI recommendations are screening/decision-support outputs. Final battery reuse requires validated
electrical, thermal, mechanical and safety testing. The rig's BMS, fuse and thermal cut-off must stay in
place; software limits are an extra layer, never a replacement.
