"""Real-time stream manager — the same code path for ESP32 hardware and the simulator.

    ESP32 / simulator ──JSON──► ingest() ──► safety check ──► SSE "reading" event
                                   │
                         window full / test end
                                   ▼
                  pipeline (SOH, RUL, fingerprint, ranking, XAI, confidence, next test)
                                   ▼
          persist readings + forecast in SQLite  ──►  ledger block (Merkle root)  ──►  SSE "forecast" event

Readings live only in memory until they have been forecast; only then are they
stored and anchored, so the database holds exclusively forecast real-time data.
"""
from __future__ import annotations

import asyncio
import copy
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd

from app import db
from app.config import LIVE_WINDOW_MAX_READINGS, LIVE_WINDOW_MIN_READINGS
from app.ml.feature_engineering import Meta
from app.services import adaptive_testing, ledger, pipeline, safety

FORECAST_EVERY = 60     # rolling forecast every N new readings while a test runs
AUX_KEYS = ("ldr", "dark", "pir", "battery_present", "lamp_on", "load_on", "rig_state")


def _now():
    return datetime.now(timezone.utc)


@dataclass
class LiveSession:
    battery_id: str
    source: str                       # ESP32 | LIVE_SIM
    meta: Meta
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    readings: list = field(default_factory=list)
    stored_upto: int = 0
    last_forecast_at: int = 0
    last_forecast: dict | None = None
    subscribers: set = field(default_factory=set)
    status: str = "streaming"
    started: float = field(default_factory=time.time)
    last_update: str | None = None
    t0_device: float | None = None
    sim_task: asyncio.Task | None = None
    forecasting: bool = False
    alerts: list = field(default_factory=list)
    test_label: str = "standard_discharge"
    readings_total: int = 0
    last_window: list = field(default_factory=list)   # display copy of the last closed (already stored) window
    aux: dict = field(default_factory=dict)           # latest rig sensors: LDR, PIR, IR battery detect, lamp/load relays

    def summary(self):
        last = self.readings[-1] if self.readings else None
        return {"battery_id": self.battery_id, "session_id": self.session_id, "source": self.source,
                "data_label": pipeline.SOURCE_LABELS.get(self.source), "status": self.status,
                "last_update": self.last_update, "buffer": len(self.readings), "stored": self.stored_upto,
                "readings_total": self.readings_total, "test": self.test_label,
                "meta": {"series_cells": self.meta.series_cells, "nominal_capacity_ah": self.meta.nominal_capacity_ah},
                "latest": last, "has_forecast": self.last_forecast is not None, "aux": self.aux}


class LiveManager:
    def __init__(self):
        self.sessions: dict[str, LiveSession] = {}
        self.lock = asyncio.Lock()

    # -------------------------------------------------------------- sessions
    def get_or_create(self, battery_id: str, source: str, meta: Meta | None = None) -> LiveSession:
        s = self.sessions.get(battery_id)
        if s is None or (s.status in ("complete", "stopped") and s.sim_task is None and source == "ESP32"):
            s = LiveSession(battery_id=battery_id, source=source, meta=meta or Meta())
            self.sessions[battery_id] = s
            with db.tx() as con:
                con.execute("INSERT OR IGNORE INTO batteries(battery_id, series_cells, nominal_capacity_ah, nominal_voltage, source, created_at)"
                            " VALUES (?,?,?,?,?,?)", (battery_id, s.meta.series_cells, s.meta.nominal_capacity_ah,
                                                      3.7 * s.meta.series_cells, source, _now().isoformat(timespec="seconds")))
        return s

    async def publish(self, s: LiveSession, event: dict):
        dead = []
        for q in list(s.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            s.subscribers.discard(q)

    # -------------------------------------------------------------- ingest
    async def ingest(self, r: dict, source: str) -> dict:
        meta = Meta(int(r.get("series_cells") or 3), float(r.get("nominal_capacity_ah") or 2.5))
        s = self.get_or_create(r["battery_id"], source, meta)
        ts = r.get("timestamp")
        t_dev = _to_seconds(ts)
        if t_dev is None:
            t_dev = time.time()
        if s.t0_device is None or not s.readings:
            s.t0_device = t_dev - (r.get("t_s") or 0.0)
        row = {"battery_id": s.battery_id, "session_id": s.session_id,
               "device_ts": ts if isinstance(ts, str) else None,
               "t_s": float(r["t_s"]) if r.get("t_s") is not None else round(t_dev - s.t0_device, 3),
               "voltage": float(r["voltage"]), "current": float(r["current"]),
               "temperature": _f(r.get("temperature")), "capacity": _f(r.get("capacity")),
               "cycle_count": _f(r.get("cycle_count")), "internal_resistance": _f(r.get("internal_resistance")),
               "cell_v_min": _f(r.get("cell_v_min")), "cell_v_max": _f(r.get("cell_v_max")),
               "gas_v": _f(r.get("gas_v")), "gas_baseline_v": _f(r.get("gas_baseline_v"))}
        aux = {k: r.get(k) for k in AUX_KEYS if r.get(k) is not None}
        if aux:
            s.aux = {**s.aux, **aux, "at": _now().isoformat(timespec="seconds")}
        if s.readings and row["t_s"] <= s.readings[-1]["t_s"]:
            row["t_s"] = s.readings[-1]["t_s"] + 0.001
        s.readings.append(row)
        s.readings_total += 1
        s.status = "streaming"
        s.last_update = _now().isoformat(timespec="seconds")
        alerts = safety.check_reading(row, s.meta.series_cells)
        if alerts:
            s.alerts = (s.alerts + [dict(a, t_s=row["t_s"]) for a in alerts])[-20:]
        await self.publish(s, {"type": "reading", "reading": {**_public(row), **aux}, "alerts": alerts, "session": s.summary()})

        phase = (r.get("phase") or "").lower()
        n_new = len(s.readings) - s.last_forecast_at
        n_loaded = sum(1 for x in s.readings[-400:] if x["current"] > 0.05) if n_new >= FORECAST_EVERY else 0
        should = (phase == "end" and len(s.readings) >= 10) or \
                 (n_new >= FORECAST_EVERY and n_loaded >= LIVE_WINDOW_MIN_READINGS + 25) or \
                 len(s.readings) >= LIVE_WINDOW_MAX_READINGS
        if should and not s.forecasting:
            await self.forecast(s, final=(phase == "end" or len(s.readings) >= LIVE_WINDOW_MAX_READINGS))
        return {"accepted": True, "buffer": len(s.readings), "alerts": alerts}

    async def update_aux(self, battery_id: str, msg: dict):
        """Idle rig status (sensors only): updates the dashboard without opening a test window."""
        s = self.sessions.get(battery_id) or self.get_or_create(battery_id, "ESP32")
        aux = {k: msg.get(k) for k in AUX_KEYS if msg.get(k) is not None}
        for k in ("voltage", "current"):
            if msg.get(k) is not None:
                aux[f"idle_{k}"] = msg[k]
        s.aux = {**s.aux, **aux, "at": _now().isoformat(timespec="seconds")}
        s.last_update = s.aux["at"]
        await self.publish(s, {"type": "aux", "aux": s.aux, "session": s.summary()})

    # -------------------------------------------------------------- forecast + persist
    async def forecast(self, s: LiveSession, final: bool = False):
        s.forecasting = True
        try:
            window = list(s.readings)
            history = _history(s.battery_id)
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _run_pipeline, s, window, history)
            if result is None:
                return
            stored = window[s.stored_upto:]
            fid, block = await loop.run_in_executor(None, _persist, s, result, stored, final)
            s.stored_upto = len(window)
            s.last_forecast_at = len(window)
            result["ledger"] = {"forecast_id": fid, **block, "stored_readings": len(stored)}
            result["live"] = {"session_id": s.session_id, "window_readings": len(window), "final": final,
                              "test": s.test_label}
            s.last_forecast = result
            await self.publish(s, {"type": "forecast", "result": result, "session": s.summary()})
            if final:
                # next test starts a fresh window (already stored)
                s.last_window = window[-600:]
                s.readings, s.stored_upto, s.last_forecast_at, s.t0_device = [], 0, 0, None
                s.status = "idle"
                await self.publish(s, {"type": "status", "session": s.summary()})
        finally:
            s.forecasting = False

    # -------------------------------------------------------------- simulator
    async def start_simulation(self, profile_id: str, test_id: str | None = None, speed_hz: float = 8.0) -> LiveSession:
        from app.simulation.demo_profiles import PROFILES, build_params, sim_config_for_test
        from app.simulation.battery_sim import BatterySimulator, TestConfig
        if profile_id not in PROFILES:
            raise KeyError(profile_id)
        bid = "LIVE-" + profile_id.split("-")[1]
        p = build_params(profile_id)
        p.battery_id = bid
        prof = PROFILES[profile_id]
        s = self.sessions.get(bid)
        if s and s.sim_task and not s.sim_task.done():
            return s
        s = self.get_or_create(bid, "LIVE_SIM", Meta(p.series_cells, p.nominal_capacity_ah))
        s.source = "LIVE_SIM"
        sensors = {"temp": prof["test"].get("has_temp_sensor", True), "cells": prof["test"].get("has_cell_voltages", True),
                   "ambient_c": prof["test"].get("ambient_c", 25)}
        if test_id:
            test = next(t for t in adaptive_testing.catalog()["tests"] if t["id"] == test_id)
            cfg = sim_config_for_test(test, p, sensors)
            label = test_id
        else:
            base = dict(prof["test"])
            base.setdefault("pulse_current_a", 2 * p.nominal_capacity_ah)
            cfg = TestConfig(**{**base, "dt_s": 5.0, "rest_end_s": max(base.get("rest_end_s", 180), 0)})
            label = "standard_discharge"
        p.seed += int(time.time()) % 1000
        df = BatterySimulator(copy.deepcopy(p)).run_test(cfg)
        if prof.get("unknown_cycle"):
            df["cycle"] = float("nan")
        s.test_label = label
        s.readings, s.stored_upto, s.last_forecast_at, s.t0_device = [], 0, 0, None
        s.status = "streaming"
        s.sim_task = asyncio.create_task(self._play(s, df, speed_hz, profile_id))
        return s

    async def _play(self, s: LiveSession, df: pd.DataFrame, speed_hz: float, profile_id: str):
        try:
            start = _now()
            n = len(df)
            for k, r in enumerate(df.itertuples()):
                if s.status == "stopped":
                    break
                reading = {"battery_id": s.battery_id, "timestamp": (start + timedelta(seconds=float(r.timestamp))).isoformat(),
                           "t_s": float(r.timestamp), "voltage": round(r.voltage, 4), "current": round(r.current, 4),
                           "temperature": None if pd.isna(r.temperature) else round(r.temperature, 2),
                           "capacity": round(r.capacity, 5), "internal_resistance": None,
                           "cycle_count": None if pd.isna(r.cycle) else int(r.cycle),
                           "cell_v_min": None if pd.isna(r.cell_v_min) else round(r.cell_v_min, 4),
                           "cell_v_max": None if pd.isna(r.cell_v_max) else round(r.cell_v_max, 4),
                           "series_cells": s.meta.series_cells, "nominal_capacity_ah": s.meta.nominal_capacity_ah,
                           "phase": "end" if k == n - 1 else "run"}
                await self.ingest(reading, "LIVE_SIM")
                await asyncio.sleep(1.0 / speed_hz)
            # execute any AI-requested test that is queued for this battery
            pending = db.query("SELECT * FROM test_requests WHERE battery_id=? AND status='pending' ORDER BY id LIMIT 1",
                               (s.battery_id,))
            s.sim_task = None
            if pending and s.status != "stopped":
                with db.tx() as con:
                    con.execute("UPDATE test_requests SET status='done', updated_at=? WHERE id=?",
                                (_now().isoformat(timespec="seconds"), pending[0]["id"]))
                await self.start_simulation(profile_id, pending[0]["test_id"], speed_hz)
            elif s.status != "stopped":
                s.status = "complete"
                await self.publish(s, {"type": "status", "session": s.summary()})
        except asyncio.CancelledError:
            pass

    def stop(self, battery_id: str):
        s = self.sessions.get(battery_id)
        if not s:
            raise KeyError(battery_id)
        s.status = "stopped"
        if s.sim_task:
            s.sim_task.cancel()
            s.sim_task = None
        return s


def _f(x):
    if x is None:
        return None
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def _to_seconds(ts):
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts) / (1000.0 if ts > 1e11 else 1.0)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _public(row):
    return {k: row[k] for k in ("t_s", "voltage", "current", "temperature", "capacity", "cycle_count",
                                "internal_resistance", "cell_v_min", "cell_v_max", "device_ts", "gas_v")}


def _history(battery_id: str) -> list[dict]:
    rows = db.query("SELECT cycle, soh, soh_lo, soh_hi FROM forecasts WHERE battery_id=? AND cycle IS NOT NULL "
                    "AND is_final = 1 ORDER BY id", (battery_id,))
    by_cycle = {}
    for r in rows:
        by_cycle[r["cycle"]] = {"cycle": r["cycle"], "soh": r["soh"], "lo": r["soh_lo"], "hi": r["soh_hi"]}
    pts = sorted(by_cycle.values(), key=lambda p: p["cycle"])
    return pts[:-1] if pts else []     # current cycle is supplied separately


def _run_pipeline(s: LiveSession, window: list, history: list):
    df = pd.DataFrame([{"timestamp": r["t_s"], "voltage": r["voltage"], "current": r["current"],
                        "temperature": r["temperature"], "capacity": r["capacity"], "cycle": r["cycle_count"],
                        "internal_resistance": r["internal_resistance"], "cell_v_min": r["cell_v_min"],
                        "cell_v_max": r["cell_v_max"]} for r in window])
    try:
        res, *_ = pipeline.analyze_timeseries(df, s.meta, battery_id=s.battery_id, source=s.source,
                                              history=history, extra_alerts=s.alerts[-5:])
        return res
    except Exception as e:   # a malformed window must not kill the stream
        import logging
        logging.getLogger("rebat.live").warning("forecast skipped for %s: %s", s.battery_id, e)
        return None


def _persist(s: LiveSession, res: dict, stored: list, final: bool) -> tuple[int, dict]:
    top = res["router"]["ranking"][0]["id"]
    with db.tx() as con:
        cur = con.execute(
            "INSERT INTO forecasts(battery_id, session_id, created_at, source, cycle, soh, soh_lo, soh_hi, confidence,"
            " rul_cycles, top_application, decision, safety_status, n_readings, is_final, result_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (s.battery_id, s.session_id, _now().isoformat(timespec="seconds"), s.source, res["features"].get("cycle"),
             res["soh"]["soh"], res["soh"]["lo"], res["soh"]["hi"], res["confidence"]["value"], res["rul"]["rul_cycles"],
             top, res["router"]["decision"]["id"], res["safety"]["status"], len(stored), int(final), db.dumps({k: v for k, v in res.items() if k != "timeseries"})))
        fid = cur.lastrowid
        leaves = []
        for r in stored:
            leaf = ledger.reading_leaf(r)
            leaves.append(leaf)
            con.execute("INSERT INTO readings(battery_id, session_id, forecast_id, device_ts, t_s, voltage, current, temperature,"
                        " capacity, cycle_count, internal_resistance, cell_v_min, cell_v_max, gas_v, leaf_hash)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r["battery_id"], r["session_id"], fid, r["device_ts"], r["t_s"], r["voltage"], r["current"],
                         r["temperature"], r["capacity"], r["cycle_count"], r["internal_resistance"], r["cell_v_min"],
                         r["cell_v_max"], r.get("gas_v"), leaf))
        payload = {"type": "forecast", "battery_id": s.battery_id, "session_id": s.session_id, "forecast_id": fid,
                   "source": s.source, "soh": res["soh"]["soh"], "soh_interval": [res["soh"]["lo"], res["soh"]["hi"]],
                   "confidence": res["confidence"]["value"], "rul_cycles": res["rul"]["rul_cycles"],
                   "top_application": top, "decision": res["router"]["decision"]["id"],
                   "safety": res["safety"]["status"], "model": f"{res['model']['name']} {res['model']['version']}",
                   "pathway": (res.get("circular") or {}).get("pathway"),
                   "evidence_hash": (res.get("forensics") or {}).get("evidence_hash"),
                   "model_fingerprint": ledger.model_fingerprint()["hash"]}
        block = ledger.append_block(con, payload, leaves)
        con.execute("UPDATE forecasts SET block_index=? WHERE id=?", (block["idx"], fid))
    return fid, block


manager = LiveManager()
