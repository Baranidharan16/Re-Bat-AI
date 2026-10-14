"""Bridge for the team's RMK-REVOLT ESP32 Battery Lab firmware.

That firmware serves its own dashboard and exposes one reading at
    GET http://<esp32-ip>/api/data
    {"battery_v": 3.912, "current_a": -0.512, "temperature_c": 29.4, "gas_v": 0.41,
     "capacity_mah": 123.4, "elapsed_s": 312, "battery_divider": true,
     "ip": "10.55.137.107", "rssi": -58}

The bridge runs inside the RE-BAT AI backend (on the laptop, same Wi-Fi as the
ESP32), polls that endpoint, converts each new sample to the canonical
TelemetryReading and feeds it to the same live pipeline as every other source:
safety check -> AI forecast -> store -> ledger -> dashboard.

No firmware change is needed. The same converter is used by the WebSocket
ingest endpoint, so a future firmware that pushes this JSON over a WebSocket
works too.

Window logic (the ESP32 does not mark test phases):
  * a reading with |current| below the rest threshold counts as rest;
  * after a discharge, once the battery has rested for `rest_close_s`
    (default 120 s), the window is closed with a final forecast — this rest
    gives the model the relaxed voltage it uses for the SOC window;
  * elapsed_s going backwards means the ESP32 rebooted -> the old window closes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import ipaddress
import os
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from app.config import DATA_DIR

SETTINGS_PATH = DATA_DIR / "esp32.json"     # last working address + battery settings (kept between runs)

log = logging.getLogger("rebat.esp32")


@dataclass
class BridgeConfig:
    esp32_url: str = "http://10.55.137.107"
    battery_id: str = "RB-001"
    series_cells: int = 1
    nominal_capacity_ah: float = 2.5
    invert_current: bool = True        # ACS712 reads negative while discharging on the lab rig; flip so + = discharge
    current_offset_a: float = 0.0      # subtract a zero-current offset found during calibration
    rest_threshold_a: float = 0.05
    rest_close_s: float = 120.0
    poll_interval_s: float = 1.0
    cycle_count: int | None = None
    auto_discover: bool = True          # scan the local network if the saved address stops answering


def load_settings() -> BridgeConfig:
    cfg = BridgeConfig()
    try:
        saved = json.loads(SETTINGS_PATH.read_text())
        names = {f.name for f in fields(BridgeConfig)}
        cfg = BridgeConfig(**{k: v for k, v in saved.items() if k in names})
    except (OSError, ValueError, TypeError):
        pass
    if os.environ.get("REBAT_ESP32_URL"):
        cfg.esp32_url = os.environ["REBAT_ESP32_URL"]
    return cfg


def save_settings(cfg: BridgeConfig):
    try:
        SETTINGS_PATH.write_text(json.dumps(asdict(cfg), indent=2))
    except OSError:
        log.warning("could not save ESP32 settings")


def _local_networks(hint_url: str) -> list[ipaddress.IPv4Network]:
    """/24 networks to scan: the saved ESP32's network first, then this computer's own."""
    nets = []
    def add(ip):
        try:
            n = ipaddress.ip_network(f"{ip}/24", strict=False)
            if n.is_private and n not in nets:
                nets.append(n)
        except ValueError:
            pass
    host = hint_url.split("//")[-1].split("/")[0].split(":")[0]
    add(host)
    for probe in ("10.255.255.255", "192.168.255.255", "172.31.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
                sk.connect((probe, 1))       # no packet is sent; picks the outgoing interface
                add(sk.getsockname()[0])
        except OSError:
            pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass
    return [n for n in nets if not str(n).startswith("127.")]


def _is_battery_lab(url: str) -> bool:
    try:
        d = _fetch(url, timeout=0.6)
        return isinstance(d, dict) and "battery_v" in d
    except Exception:
        return False


def discover(hint_url: str) -> str | None:
    """Find an ESP32 Battery Lab on the local network (port 80, /api/data with battery_v)."""
    for net in _local_networks(hint_url):
        hosts = [f"http://{h}" for h in net.hosts()]
        with ThreadPoolExecutor(max_workers=64) as ex:
            for url, ok in zip(hosts, ex.map(_is_battery_lab, hosts)):
                if ok:
                    return url
    return None


@dataclass
class BridgeState:
    running: bool = False
    connected: bool = False
    last_ok: str | None = None
    last_error: str | None = None
    readings_sent: int = 0
    last_raw: dict | None = None
    last_elapsed: float | None = None
    rest_since: float | None = None
    seen_discharge: bool = False
    windows_closed: int = 0
    gas_baseline_v: float | None = None
    gas_samples: list = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    consecutive_failures: int = 0
    discovering: bool = False
    last_discovery: float = 0.0
    discovery_note: str | None = None


def convert(raw: dict, cfg: BridgeConfig, phase: str | None = None) -> dict | None:
    """ESP32 Battery Lab JSON -> canonical TelemetryReading dict (None if unusable)."""
    v = _num(raw.get("battery_v", raw.get("voltage")))
    i = _num(raw.get("current_a", raw.get("current")))
    if v is None or v <= 0 or i is None:
        return None
    i = (i - cfg.current_offset_a) * (-1.0 if cfg.invert_current else 1.0)
    cap_mah = _num(raw.get("capacity_mah"))
    return {
        "battery_id": cfg.battery_id,
        "t_s": _num(raw.get("elapsed_s")),
        "voltage": v,
        "current": i,
        "temperature": _num(raw.get("temperature_c", raw.get("temperature"))),
        "capacity": cap_mah / 1000.0 if cap_mah is not None else None,
        "gas_v": _num(raw.get("gas_v")),
        "cycle_count": cfg.cycle_count,
        "series_cells": cfg.series_cells,
        "nominal_capacity_ah": cfg.nominal_capacity_ah,
        "phase": phase,
        # optional second-life sensors, passed through when the firmware reports them
        **{k: raw[k] for k in ("ldr", "dark", "pir", "battery_present", "lamp_on", "load_on", "rig_state") if raw.get(k) is not None},
    }


def _num(x):
    try:
        f = float(x)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _fetch(url: str, timeout: float = 2.5) -> dict:
    req = urllib.request.Request(url.rstrip("/") + f"/api/data?t={int(time.time() * 1000)}", headers={"Cache-Control": "no-store"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class ESP32Bridge:
    def __init__(self, manager):
        self.manager = manager
        self.cfg = BridgeConfig()
        self.state = BridgeState()
        self.task: asyncio.Task | None = None

    def status(self) -> dict:
        return {"config": asdict(self.cfg), "state": {k: v for k, v in asdict(self.state).items()},
                "source_format": "RMK-REVOLT Battery Lab /api/data (HTTP polling)"}

    async def start(self, cfg: BridgeConfig, save: bool = True):
        await self.stop()
        self.cfg, self.state = cfg, BridgeState(running=True)
        if save:
            save_settings(cfg)
        self.task = asyncio.create_task(self._loop())

    async def find_now(self) -> str | None:
        """Scan the local network right away (dashboard button)."""
        self.state.discovering = True
        try:
            url = await asyncio.to_thread(discover, self.cfg.esp32_url)
        finally:
            self.state.discovering = False
            self.state.last_discovery = time.time()
        if url:
            self.cfg.esp32_url = url
            save_settings(self.cfg)
            self.state.discovery_note = f"Found the ESP32 at {url}"
        else:
            self.state.discovery_note = "No ESP32 Battery Lab found on this network"
        return url

    async def stop(self, close_window: bool = True):
        if self.task:
            self.task.cancel()
            self.task = None
        if self.state.running and close_window:
            await self.close_window("bridge stopped")
        self.state.running = False

    async def close_window(self, reason: str):
        s = self.manager.sessions.get(self.cfg.battery_id)
        if s and len(s.readings) >= 10 and not s.forecasting:
            log.info("closing window for %s (%s)", self.cfg.battery_id, reason)
            await self.manager.forecast(s, final=True)
            self.state.windows_closed += 1
        self.state.seen_discharge = False
        self.state.rest_since = None

    async def handle(self, raw: dict, source: str = "ESP32") -> dict | None:
        """Shared by the poller and the WebSocket endpoint."""
        st = self.state
        el = _num(raw.get("elapsed_s"))
        if el is not None and st.last_elapsed is not None:
            if el == st.last_elapsed:
                return None                       # same sample polled twice
            if el < st.last_elapsed:
                await self.close_window("ESP32 restarted")
        st.last_elapsed = el
        reading = convert(raw, self.cfg)
        if reading is None:
            st.last_error = "reading had no valid battery_v / current_a"
            return None
        # gas sensor baseline (median of first readings) for the relative-rise safety check
        if reading["gas_v"] is not None:
            if len(st.gas_samples) < 10:
                st.gas_samples.append(reading["gas_v"])
                st.gas_baseline_v = sorted(st.gas_samples)[len(st.gas_samples) // 2]
            reading["gas_baseline_v"] = st.gas_baseline_v
        loaded = abs(reading["current"]) > self.cfg.rest_threshold_a
        now = el if el is not None else time.time()
        if loaded and reading["current"] > 0:
            st.seen_discharge, st.rest_since = True, None
        elif not loaded and st.seen_discharge:
            st.rest_since = st.rest_since if st.rest_since is not None else now
            if now - st.rest_since >= self.cfg.rest_close_s:
                reading["phase"] = "end"
                st.seen_discharge, st.rest_since = False, None
                st.windows_closed += 1
        out = await self.manager.ingest(reading, source)
        st.readings_sent += 1
        st.last_raw = raw
        return out

    async def _loop(self):
        st = self.state
        while True:
            try:
                raw = await asyncio.to_thread(_fetch, self.cfg.esp32_url)
                if not st.connected and st.consecutive_failures:
                    log.info("ESP32 connected at %s", self.cfg.esp32_url)
                st.connected, st.last_error, st.consecutive_failures = True, None, 0
                st.last_ok = time.strftime("%H:%M:%S")
                await self.handle(raw)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # network blips must not kill the bridge
                st.connected, st.last_error = False, f"{type(e).__name__}: {e}"
                st.consecutive_failures += 1
                # saved address not answering (IP changed / ESP32 rebooted): look for it on the network
                if (self.cfg.auto_discover and st.consecutive_failures >= 5 and not st.discovering
                        and time.time() - st.last_discovery > 60):
                    await self.find_now()
            await asyncio.sleep(self.cfg.poll_interval_s)
