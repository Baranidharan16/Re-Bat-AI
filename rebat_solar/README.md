# RE-BAT AI · Solar twin module

A software model of a solar panel charging a **retired EV battery that the RE-BAT rig has already measured**, which then runs a street light at night. It runs live (accelerated time) and also projects the battery's whole second life.

```
Sun → PV panel → MPPT charge controller → second-life pack → LED street light
```

## What's in the box

| File | Purpose |
|---|---|
| `backend/app/services/solar_sim.py` | The physics model (reference implementation) |
| `backend/app/services/solar_live.py` | Live sessions that advance in accelerated real time and stream over SSE |
| `backend/app/api/solar_routes.py` | FastAPI router: `/solar/...` endpoints |
| `backend/solar_demo_server.py` | Runs the module alone and serves the dashboard |
| `backend/tests/test_solar_twin.py` | 6 tests: energy balance, CV limit, LVD, thermal derate, ageing, API |
| `frontend/solar_twin_dashboard.html` | Single-file live dashboard (open it straight in a browser) |
| `frontend/solar_twin_engine.js` | Browser port of `solar_sim.py` (already inlined in the dashboard) |

## Run it

```bash
cd backend
pip install fastapi uvicorn pytest httpx
python solar_demo_server.py        # → http://localhost:8000   (API docs: /docs)
pytest -q tests                    # 6 passed
```

Or just double-click `frontend/solar_twin_dashboard.html`. It runs entirely in the browser.

## Plug into the main RE-BAT AI backend

1. Copy `solar_sim.py` and `solar_live.py` into `backend/app/services/` and `solar_routes.py` into `backend/app/api/`.
2. In `app/main.py`:
   ```python
   from app.api.solar_routes import router as solar_router
   app.include_router(solar_router)
   ```
3. Feeding the twin into the XGBoost pipeline: `GET /solar/sessions/{id}/telemetry` returns a reading in the canonical schema (`timestamp, voltage, current, temperature, capacity, cycle, internal_resistance, cell_v_min, cell_v_max`). **Check two things in `data_ingestion.py`**: the current here is *charge-positive*, and `capacity` is the pack's present full capacity in Ah. Adjust the alias/sign mapping if your ingestion expects otherwise.

## API

| Method & path | Purpose |
|---|---|
| `GET /solar/presets` | 3 ready systems (EV module street light, rig 18650 bench demo, LFP household) |
| `POST /solar/sessions` | `{preset, config:{pack:{…rig measurements…}}, speed}` starts a live session |
| `GET /solar/sessions/{id}/stream` | SSE: `snapshot`, `tick`, `log`, `day_summary`, `status` |
| `POST /solar/sessions/{id}/control` | `pause`, `resume`, `speed`, `weather`, `skip`, `stop` |
| `GET /solar/sessions/{id}/telemetry` | Canonical RE-BAT reading |
| `POST /solar/lifetime` | Projection to end of second life, 3 charging scenarios |

Rig measurements go in `config.pack`: `chemistry`, `series_cells`, `nominal_capacity_ah`, `measured_capacity_ah`, `internal_resistance_mohm`, `cell_spread_mv`, `cycle_count`, `initial_soc`.

## The models (for the judges' questions)

| Part | Model |
|---|---|
| Sun position | Declination + hour angle at latitude 13.08° N |
| Irradiance | Haurwitz clear-sky GHI × cloud index (Ornstein–Uhlenbeck process per weather type; Chennai seasonal weather incl. NE monsoon) |
| Panel | P = P_STC · G/1000 · (1 + γ(T_cell − 25)) · derate, T_cell from NOCT |
| Controller | MPPT 96 %, CC at 0.3 C → CV (4.10 V/cell NMC, 3.50 V/cell LFP), taper cut-off, derates above 40 °C, stops at 45 °C, low-voltage disconnect at 10 % SOC, reconnect at 25 % |
| Battery | OCV(SOC) table × cells + measured DC resistance, coulomb counting, lumped thermal model with sun-heated enclosure |
| Ageing | Cycle fade per equivalent full cycle (Arrhenius, C-rate stress, knee below 70 % SOH) + calendar fade (Arrhenius, SOC stress); resistance grows with fade |

**Limitation to say out loud:** the ageing coefficients are literature-order values, not fitted to your pack. Re-measure capacity on the rig every few months and enter the new number; the twin recalibrates from that.
