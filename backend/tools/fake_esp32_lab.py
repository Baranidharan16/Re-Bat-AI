"""Stand-in for the RMK-REVOLT ESP32 Battery Lab (SIMULATED data) — for rehearsal and testing.

    python tools/fake_esp32_lab.py --port 8081 --speed 10
    then in the dashboard: Live data → ESP32 Battery Lab → address http://localhost:8081

Serves GET /api/data in exactly the firmware's format:
    {"battery_v", "current_a", "temperature_c", "gas_v", "capacity_mah", "elapsed_s",
     "battery_divider", "ip", "rssi"}
Current is negative while discharging (ACS712 orientation on the lab rig), like the real board.
--speed N advances N simulated seconds per real second so a whole test fits in a demo.
--gas-event T makes the gas sensor rise after T simulated seconds (to show the safety alert).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.simulation.battery_sim import BatteryParams, BatterySimulator, TestConfig  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8081)
ap.add_argument("--speed", type=float, default=10.0)
ap.add_argument("--cycle", type=int, default=900)
ap.add_argument("--gas-event", type=float, default=None)
args = ap.parse_args()

p = BatteryParams("LAB", series_cells=1, nominal_capacity_ah=2.5, cycle=args.cycle, seed=7)
df = BatterySimulator(p).run_test(TestConfig(current_a=1.25, pulse_current_a=5.0, dt_s=1.0, rest_end_s=180, soc_start=1.0, soc_end=0.55))
t = df["timestamp"].to_numpy()
T0 = time.time()
rng = np.random.default_rng(1)


def sample():
    el = (time.time() - T0) * args.speed
    k = int(np.searchsorted(t, min(el, t[-1])))
    k = min(k, len(df) - 1)
    r = df.iloc[k]
    gas = 0.42 + rng.normal(0, 0.01)
    if args.gas_event is not None and el > args.gas_event:
        gas += min(1.2, (el - args.gas_event) / 200)
    return {"battery_v": round(float(r.voltage), 3), "current_a": round(-float(r.current), 3),
            "temperature_c": None if np.isnan(r.temperature) else round(float(r.temperature), 2),
            "gas_v": round(gas, 3), "capacity_mah": round(float(r.capacity) * 1000, 2),
            "elapsed_s": int(t[k]), "battery_divider": True, "ip": "127.0.0.1", "rssi": -55}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/data"):
            body = json.dumps(sample()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
            self.wfile.write(b"Fake RMK-REVOLT Battery Lab (SIMULATED). Data at /api/data\n")

    def log_message(self, *a):
        pass


print(f"Fake ESP32 Battery Lab on http://localhost:{args.port}  (test length {t[-1]:.0f} s simulated, x{args.speed})")
ThreadingHTTPServer(("0.0.0.0", args.port), H).serve_forever()
