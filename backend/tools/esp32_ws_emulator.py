"""ESP32 WebSocket emulator — behaves like firmware/rebat_ws_rig over the WebSocket connector.

    python tools/esp32_ws_emulator.py                       # battery B, 10x speed
    python tools/esp32_ws_emulator.py --profile RB-F06      # end-of-life battery -> RECYCLE
    python tools/esp32_ws_emulator.py --url ws://192.168.1.10:8000/api/v1/hardware/ws

Sends hello + one reading per (simulated) second with LDR / PIR / IR / relay states, prints the
AI verdict the server pushes back, and obeys dashboard commands (lamp_on, lamp_off, lamp_auto,
start_test, quick_test, stop). Data is SIMULATED — for demos and integration tests only.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import websockets  # noqa: E402  (installed with uvicorn[standard])

from app.simulation.battery_sim import BatterySimulator, TestConfig  # noqa: E402
from app.simulation.demo_profiles import build_params  # noqa: E402


class Rig:
    def __init__(self, a):
        self.a = a
        self.lamp_mode = "auto"
        self.lamp_on = False
        self.night_started = time.time()
        self.last_motion = 0.0
        self.pending = "start_test"
        self.stop = False

    def sensors(self, t: float):
        # a 60 s day/night cycle so the street-light logic is visible in the demo
        dark = (int(time.time() - self.night_started) // 30) % 2 == 0
        ldr = 3300 + random.randint(-60, 60) if dark else 900 + random.randint(-60, 60)
        if random.random() < 0.06:
            self.last_motion = time.time()
        pir = time.time() - self.last_motion < 8
        if self.lamp_mode == "auto":
            self.lamp_on = dark and pir
        else:
            self.lamp_on = self.lamp_mode == "on"
        return {"ldr": ldr, "dark": dark, "pir": pir, "battery_present": True, "lamp_on": self.lamp_on}

    def test_frames(self, quick: bool):
        p = build_params(self.a.profile)
        p.seed += int(time.time()) % 997
        kw = dict(include_pulse=True, soc_start=1.0, soc_end=0.0, rest_end_s=150)
        if quick:
            kw = dict(include_pulse=True, soc_start=0.95, soc_end=0.80, rest_end_s=60)
        return p, BatterySimulator(p).run_test(TestConfig(current_a=0.5 * p.nominal_capacity_ah, dt_s=5.0,
                                                          pulse_current_a=2 * p.nominal_capacity_ah, **kw))


async def reader(ws, rig: Rig):
    async for msg in ws:
        m = json.loads(msg)
        if m.get("type") == "verdict":
            print(f"  AI verdict → {m['pathway']}: {m.get('best') or m.get('headline')} · SOH {m['soh']:.1f}% · block #{m.get('block')}")
        elif m.get("type") == "command":
            cmd = m["cmd"]
            print(f"  command from dashboard: {cmd}")
            if cmd in ("lamp_on", "lamp_off", "lamp_auto"):
                rig.lamp_mode = cmd.split("_")[1]
            elif cmd in ("start_test", "quick_test"):
                rig.pending = cmd
            elif cmd == "stop":
                rig.stop = True
        elif m.get("type") == "ack" and not m.get("ok"):
            print("  server rejected a reading:", m.get("error"))


async def main(a):
    rig = Rig(a)
    async with websockets.connect(a.url, max_size=2 ** 22) as ws:
        print("connected to", a.url)
        await ws.send(json.dumps({"type": "hello", "battery_id": a.battery_id, "firmware": "rebat-ws emulator 2.0", "ip": "emulator"}))
        task = asyncio.create_task(reader(ws, rig))
        while True:
            if rig.pending:
                quick = rig.pending == "quick_test"
                rig.pending, rig.stop = None, False
                p, df = rig.test_frames(quick)
                print(f"running {'quick' if quick else 'full'} test on {a.profile} ({len(df)} samples)")
                for k, r in enumerate(df.itertuples()):
                    if rig.stop or rig.pending:
                        break
                    s = rig.sensors(r.timestamp)
                    msg = {"battery_id": a.battery_id, "t_s": float(r.timestamp), "voltage": round(r.voltage, 4),
                           "current": round(r.current, 4),
                           "temperature": None if r.temperature != r.temperature else round(r.temperature, 2),
                           "capacity": round(r.capacity, 5), "cycle_count": int(r.cycle) if r.cycle == r.cycle else None,
                           "cell_v_min": round(r.cell_v_min, 4), "cell_v_max": round(r.cell_v_max, 4),
                           "series_cells": p.series_cells, "nominal_capacity_ah": p.nominal_capacity_ah,
                           "gas_v": round(0.42 + 0.01 * math.sin(k / 9), 3), "load_on": r.current > 0.05,
                           "rig_state": "DISCHARGE" if r.current > 0.05 else "REST",
                           "phase": "end" if k == len(df) - 1 else "run", **s}
                    await ws.send(json.dumps(msg))
                    await asyncio.sleep(1.0 / a.hz)
                print("test finished")
                if a.once:
                    await asyncio.sleep(2)
                    break
            else:   # idle: sensors only (like the firmware), no test window
                s = rig.sensors(0)
                await ws.send(json.dumps({"type": "status", "battery_id": a.battery_id, "voltage": 11.6, "current": 0.0,
                                          "rig_state": "IDLE", "load_on": False, **s}))
                await asyncio.sleep(1)
        task.cancel()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8000/api/v1/hardware/ws")
    ap.add_argument("--battery-id", default="RB-001")
    ap.add_argument("--profile", default="RB-B02", help="RB-A01 … RB-F06 (F = end of life → recycle)")
    ap.add_argument("--hz", type=float, default=10, help="readings per second (1 = real time)")
    ap.add_argument("--once", action="store_true", help="exit after one test")
    try:
        asyncio.run(main(ap.parse_args()))
    except KeyboardInterrupt:
        pass
