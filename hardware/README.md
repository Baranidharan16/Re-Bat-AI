# RE-BAT AI — Test Rig Hardware

## Rig 2.0 (the one we build): ESP32 WebSocket rig — `firmware/rebat_ws_rig/`

| Part | Pin(s) | Notes |
|---|---|---|
| 3S Li-ion holder → BMS → 5 A fuse | — | battery current never goes through breadboard jumpers |
| 0–25 V voltage sensor | S → **GPIO 36 (VP)**, − → GND | screw terminals across the pack (÷5) |
| ACS712 current sensor | OUT → 10k → **GPIO 39 (VN)** → 20k → GND, VCC 5 V | in series with battery + ; zero-calibrated at boot |
| 0.96" OLED | SDA **21**, SCL **22**, VCC 3.3 V | shows V/I/Ah, sensors and the AI verdict |
| MQ gas sensor | AO → 10k → **GPIO 34** → 20k → GND, VCC 5 V | relative alarm (+0.4 V over start) |
| LDR module | AO → **GPIO 35**, VCC 3.3 V | dusk detection for the street light |
| PIR | OUT → **GPIO 27**, VCC 5 V | motion → lamp on |
| IR obstacle sensor | OUT → **GPIO 13**, VCC 3.3 V | LOW = battery in the bay → auto quick test |
| Cell taps | Tap A → 10k → **GPIO 32** → 22k → GND; Tap B → 27k → **GPIO 33** → 10k → GND | per-cell voltage |
| 2-channel relay | IN1 **GPIO 25** (test load), IN2 **GPIO 26** (12 V lamp), VCC 5 V | COM = +BUS, NO = load / lamp |
| Buzzer | **GPIO 14** | alarms and test end |
| DS18B20 (optional) | **GPIO 4** + 4.7k to 3.3 V | set `USE_DS18B20 1` |

Common ground: battery − (BMS P−) joins every GND. Powering the ESP32 from the laptop USB is fine for the demo; keep the
pack's 9–12.6 V rail away from every ESP32 pin.

---

## Rig 1.0 reference design (INA226 / ADS1115) — `firmware/rebat_esp32/`


The rig measures a battery module, applies a controlled load, and streams readings
to the RE-BAT AI backend. The AI can request additional tests; the rig executes them
only within its own hard-wired protection.

```
 Battery module (3S Li-ion, with its BMS)
   │  +                                           ┌──────────── ESP32 DevKit ────────────┐
   ├── Fuse (10 A) ── Contactor/relay ──┬─────────┤ GPIO27  contactor enable              │
   │                                    │         │                                       │
   │                         INA226 shunt (10 mΩ) │ I2C SDA21/SCL22 ── INA226 (V, I)      │
   │                                    │         │                 └─ ADS1115 (cell taps)│
   │                    ┌───────────────┴──────┐  │ GPIO4   DS18B20 ×2 (cell, ambient)    │
   │                    │ R_main 4.7 Ω 50 W    │  │ GPIO25  gate driver → MOSFET main load│
   │                    │ R_pulse 2.2 Ω 50 W   │  │ GPIO26  gate driver → MOSFET pulse    │
   │                    └── MOSFETs (IRLZ44N) ─┘  └───────────────────────────────────────┘
   │  −  ────────────────────────────────── common ground ─────────────────────────────────
   └─ balance taps → dividers (1:2, 1:4, 1:6) → ADS1115 A0–A2  (optional, for cell imbalance)
```

## Bill of materials (prototype)

| Part | Purpose | Notes |
|---|---|---|
| ESP32 DevKit v1 | controller + Wi-Fi | any ESP32-WROOM board |
| INA226 module + 10 mΩ shunt | pack voltage (≤36 V) and current | set `SHUNT_OHM`, `MAX_CURRENT_A` |
| DS18B20 ×2 (waterproof) + 4.7 kΩ | cell surface + ambient temperature | thermal paste/kapton on the cell |
| ADS1115 + precision resistor dividers | per-cell voltages via balance taps | optional; enables imbalance feature |
| 2× logic-level MOSFET (IRLZ44N) + gate drivers/opto | switch main and pulse loads | heatsink required |
| Power resistors 4.7 Ω & 2.2 Ω, 50 W, on heatsink | ≈0.9C main load, ≈2C pulse for a 2.5 Ah 3S pack | size for your pack |
| Relay/contactor + 10 A fuse | disconnect under fault | normally-open, fails safe |
| Battery BMS (must stay in place) | primary over/under-voltage, over-current protection | **never bypass** |

An electronic DC load (e.g. a programmable one) can replace the resistor loads for true constant current;
the AI features are normalised by the *measured* current, so resistor loads also work.

## Firmware

`firmware/rebat_esp32/` — Arduino IDE or PlatformIO.

1. Install libraries: ArduinoJson (v7), INA226 (Rob Tillaart), OneWire, DallasTemperature, Adafruit ADS1X15.
2. Edit `config.h`: Wi-Fi, `API_BASE` (your laptop IP, port 8000), `BATTERY_ID`, cells, nominal Ah.
3. Flash, open Serial Monitor (115200), send `s` to start a standard test — or queue one from the dashboard.

### Protocol run by the firmware

`REST 60 s → PULSE 2C 20 s → REST 30 s → DISCHARGE to 3.0 V/cell (or requested Ah) → REST 180 s → END`

Every reading is sent as:

```json
{"battery_id":"RB-001","t_s":312.0,"voltage":11.72,"current":1.42,"temperature":29.4,
 "capacity":0.124,"internal_resistance":0.042,"cycle_count":185,
 "cell_v_min":3.88,"cell_v_max":3.92,"series_cells":3,"nominal_capacity_ah":2.5,"phase":"run"}
```

`capacity` = Ah discharged so far in this test (coulomb counter). `internal_resistance` = last pulse ΔV/ΔI (Ω).
`phase:"end"` closes the window: the server forecasts it, stores it and anchors it in the ledger.

### Safety behaviour

Firmware opens the loads and the contactor on: cell < 2.5 V or > 4.25 V, current > `MAX_CURRENT_A`,
temperature > 55 °C, or temperature rising > 2 °C/min. The server raises a **SAFETY ALERT**
independently. These software limits are *in addition to* — never instead of — the BMS, fuse and
thermal cut-off. Test only in a ventilated area on a non-flammable surface, with a Class D/ABC
extinguisher nearby, and never leave a discharge unattended.

## No hardware yet?

`python tools/esp32_emulator.py --profile RB-C03` posts simulated readings to the same endpoint
exactly as the ESP32 would (data labelled ESP32 in the backend, but generated by the simulator — use
only for integration testing).
