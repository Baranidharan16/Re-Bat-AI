"""Live (real-time, accelerated) sessions for the solar twin, streamed over SSE.

Each session owns a SolarBatterySystem and an asyncio task that advances
simulated time by `speed` sim-seconds per wall-second, `tick_hz` times a second,
and fans the snapshot out to every subscriber queue.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional, Set

from .solar_sim import SolarBatterySystem, SystemConfig

MAX_SESSIONS = 8


class SolarSession:
    def __init__(self, cfg: SystemConfig, speed: float = 600.0, tick_hz: float = 4.0,
                 seed: Optional[int] = None, battery_id: str = "SOLAR-TWIN-01"):
        self.id = uuid.uuid4().hex[:10]
        self.battery_id = battery_id
        self.system = SolarBatterySystem(cfg, seed=seed)
        self.speed = float(speed)
        self.tick_hz = float(tick_hz)
        self.running = True
        self.stopped = False
        self.subscribers: Set[asyncio.Queue] = set()
        self._task: Optional[asyncio.Task] = None
        self._days_sent = 0
        self._events_sent = 0

    # ---------------- pub/sub ----------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    def _publish(self, event: str, data: Dict[str, Any]) -> None:
        for q in list(self.subscribers):
            if q.full():  # slow client: drop oldest
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait({"event": event, "data": data})

    # ---------------- loop ----------------
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        dt_wall = 1.0 / self.tick_hz
        try:
            while not self.stopped:
                await asyncio.sleep(dt_wall)
                if not self.running:
                    continue
                snap = self.system.advance(self.speed * dt_wall)
                self._publish("tick", snap)
                sysm = self.system
                for e in sysm.events:
                    if e["seq"] > self._events_sent:
                        self._publish("log", e)
                if sysm.events:
                    self._events_sent = sysm.events[-1]["seq"]
                if len(sysm.day_summaries) > self._days_sent:
                    for d in sysm.day_summaries[self._days_sent:]:
                        self._publish("day_summary", d)
                    self._days_sent = len(sysm.day_summaries)
        except asyncio.CancelledError:
            pass

    def control(self, action: str, value: Any = None) -> Dict[str, Any]:
        if action == "pause":
            self.running = False
        elif action == "resume":
            self.running = True
        elif action == "speed":
            v = float(value)
            if not 1 <= v <= 86400:
                raise ValueError("speed must be 1..86400 sim-seconds per second")
            self.speed = v
        elif action == "weather":
            self.system.set_weather(str(value))
        elif action == "skip":
            secs = float(value)
            if not 0 < secs <= 30 * 86400:
                raise ValueError("skip must be 0..30 days in seconds")
            self.system.advance(secs, substep=60.0)
        elif action == "stop":
            self.stop()
        else:
            raise ValueError(f"unknown action {action!r}")
        status = self.status()
        self._publish("status", status)
        return status

    def stop(self) -> None:
        self.stopped = True
        if self._task:
            self._task.cancel()
        self._publish("status", self.status())

    def status(self) -> Dict[str, Any]:
        return {"session_id": self.id, "battery_id": self.battery_id, "running": self.running,
                "stopped": self.stopped, "speed": self.speed, "tick_hz": self.tick_hz,
                "weather_setting": self.system.cfg.site.weather,
                "sim_time": self.system.now.isoformat(timespec="seconds")}


class SolarSessionManager:
    def __init__(self) -> None:
        self.sessions: Dict[str, SolarSession] = {}

    def create(self, cfg: SystemConfig, **kw: Any) -> SolarSession:
        live = [s for s in self.sessions.values() if not s.stopped]
        if len(live) >= MAX_SESSIONS:
            oldest = min(live, key=lambda s: s.system.t)
            oldest.stop()
        self.sessions = {k: s for k, s in self.sessions.items() if not s.stopped}
        s = SolarSession(cfg, **kw)
        self.sessions[s.id] = s
        s.start()
        return s

    def get(self, sid: str) -> SolarSession:
        if sid not in self.sessions:
            raise KeyError(sid)
        return self.sessions[sid]

    def list(self) -> List[Dict[str, Any]]:
        return [s.status() for s in self.sessions.values()]


manager = SolarSessionManager()
