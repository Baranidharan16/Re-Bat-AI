"""REST + SSE endpoints for the solar → second-life battery twin.

Mount in app/main.py:

    from app.api.solar_routes import router as solar_router
    app.include_router(solar_router)
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.solar_live import manager
from app.services.solar_sim import PRESETS, SystemConfig, compare_lifetime, project_lifetime

router = APIRouter(prefix="/solar", tags=["solar twin"])


class SessionCreate(BaseModel):
    preset: Optional[str] = Field(None, description="key from GET /solar/presets")
    config: Optional[Dict[str, Any]] = Field(
        None, description="partial SystemConfig; overrides the preset. "
                          "Put the rig measurements under config.pack")
    speed: float = Field(600.0, ge=1, le=86400, description="sim-seconds per wall-second")
    tick_hz: float = Field(4.0, ge=0.5, le=20)
    seed: Optional[int] = 7
    battery_id: str = "SOLAR-TWIN-01"


class ControlBody(BaseModel):
    action: str = Field(..., description="pause | resume | speed | weather | skip | stop")
    value: Optional[Any] = None


class LifetimeBody(BaseModel):
    preset: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    max_years: float = Field(15.0, gt=0, le=30)
    compare: bool = True


def _build_config(preset: Optional[str], overrides: Optional[Dict[str, Any]]) -> SystemConfig:
    base: Dict[str, Any] = {}
    if preset:
        if preset not in PRESETS:
            raise HTTPException(404, f"unknown preset {preset!r}")
        base = json.loads(json.dumps(PRESETS[preset]["config"]))
    for section, values in (overrides or {}).items():
        if isinstance(values, dict):
            base.setdefault(section, {}).update(values)
    try:
        return SystemConfig.from_dict(base)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))


@router.get("/presets")
def presets() -> Dict[str, Any]:
    return PRESETS


@router.post("/sessions")
async def create_session(body: SessionCreate) -> Dict[str, Any]:
    cfg = _build_config(body.preset, body.config)
    s = manager.create(cfg, speed=body.speed, tick_hz=body.tick_hz, seed=body.seed,
                       battery_id=body.battery_id)
    return {**s.status(), "config": cfg.to_dict(), "snapshot": s.system.snapshot()}


@router.get("/sessions")
def list_sessions() -> Any:
    return manager.list()


def _session(sid: str):
    try:
        return manager.get(sid)
    except KeyError:
        raise HTTPException(404, "session not found")


@router.get("/sessions/{sid}/latest")
def latest(sid: str) -> Dict[str, Any]:
    s = _session(sid)
    return {"status": s.status(), "snapshot": s.system.snapshot(), "events": s.system.events[-30:],
            "days": s.system.day_summaries[-14:]}


@router.get("/sessions/{sid}/telemetry")
def telemetry(sid: str) -> Dict[str, Any]:
    """Current state in RE-BAT's canonical schema (feed to /hardware/ingest or the pipeline)."""
    s = _session(sid)
    return s.system.canonical_reading(s.battery_id)


@router.post("/sessions/{sid}/control")
async def control(sid: str, body: ControlBody) -> Dict[str, Any]:
    s = _session(sid)
    try:
        return s.control(body.action, body.value)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/sessions/{sid}/stream")
async def stream(sid: str, request: Request) -> StreamingResponse:
    s = _session(sid)
    q = s.subscribe()

    async def gen():
        try:
            first = {"status": s.status(), "config": s.system.cfg.to_dict(),
                     "snapshot": s.system.snapshot(), "events": s.system.events[-30:],
                     "days": s.system.day_summaries[-14:]}
            yield f"event: snapshot\ndata: {json.dumps(first)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"
                if msg["event"] == "status" and msg["data"].get("stopped"):
                    break
        finally:
            s.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/lifetime")
async def lifetime(body: LifetimeBody) -> Dict[str, Any]:
    cfg = _build_config(body.preset, body.config)
    if body.compare:
        return await run_in_threadpool(compare_lifetime, cfg, body.max_years)
    return {"standard": await run_in_threadpool(project_lifetime, cfg, body.max_years)}
