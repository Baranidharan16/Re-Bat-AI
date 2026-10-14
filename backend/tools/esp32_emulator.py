"""ESP32 emulator — posts simulated rig readings to the hardware ingest endpoint.

    python tools/esp32_emulator.py --profile RB-C03 --battery-id RB-HW-01 --hz 20

Integration testing only: data arrives via the ESP32 path but is SIMULATED.
It also polls for AI-requested tests and runs them, like the firmware does.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.simulation.battery_sim import BatterySimulator, TestConfig  # noqa: E402
from app.simulation.demo_profiles import build_params  # noqa: E402

CMD_TO_CFG = {
    "PULSE": dict(include_pulse=True, soc_start=0.9, soc_end=0.82, rest_end_s=120),
    "DISCHARGE": dict(include_pulse=True, soc_start=1.0, soc_end=0.0, rest_end_s=300),
    "THERMAL": dict(include_pulse=False, soc_start=0.9, soc_end=0.3, rest_end_s=60),
    "REST": dict(include_pulse=False, soc_start=0.9, soc_end=0.6, rest_end_s=600),
    "CELL_SCAN": dict(include_pulse=False, soc_start=0.9, soc_end=0.75, rest_end_s=60),
    "CYCLE": dict(include_pulse=True, soc_start=1.0, soc_end=0.0, rest_end_s=300),
}


def call(base, path, body=None, method="POST"):
    req = urllib.request.Request(base + path, method=method, headers={"content-type": "application/json"},
                                 data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"{}")


def run(base, bid, profile, cfg_kw, hz, batch=10):
    p = build_params(profile)
    p.seed += int(time.time()) % 997
    df = BatterySimulator(p).run_test(TestConfig(current_a=0.5 * p.nominal_capacity_ah, dt_s=5.0,
                                                 pulse_current_a=2 * p.nominal_capacity_ah, **cfg_kw))
    buf = []
    for k, r in enumerate(df.itertuples()):
        buf.append({"battery_id": bid, "t_s": r.timestamp, "voltage": round(r.voltage, 4), "current": round(r.current, 4),
                    "temperature": None if r.temperature != r.temperature else round(r.temperature, 2),
                    "capacity": round(r.capacity, 5), "cycle_count": int(r.cycle),
                    "cell_v_min": round(r.cell_v_min, 4), "cell_v_max": round(r.cell_v_max, 4),
                    "series_cells": p.series_cells, "nominal_capacity_ah": p.nominal_capacity_ah,
                    "phase": "end" if k == len(df) - 1 else "run"})
        if len(buf) >= batch or k == len(df) - 1:
            call(base, "/api/v1/hardware/ingest", {"readings": buf}); buf = []
            time.sleep(batch / hz)
    print(f"sent {len(df)} readings")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--battery-id", default="RB-HW-01")
    ap.add_argument("--profile", default="RB-B02")
    ap.add_argument("--hz", type=float, default=20)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    run(a.base, a.battery_id, a.profile, CMD_TO_CFG["DISCHARGE"], a.hz)
    while not a.once:
        cmds = call(a.base, f"/api/v1/hardware/{a.battery_id}/commands", method="GET")["commands"]
        for c in cmds:
            print("executing AI-requested test:", c["test_id"])
            run(a.base, a.battery_id, a.profile, CMD_TO_CFG.get(c["cmd"], CMD_TO_CFG["DISCHARGE"]), a.hz)
            call(a.base, f"/api/v1/hardware/{a.battery_id}/commands/{c['id']}/ack?status=done", {})
        time.sleep(3)
