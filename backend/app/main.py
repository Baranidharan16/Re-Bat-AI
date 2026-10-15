"""RE-BAT AI — FastAPI application.

    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.solar_routes import router as solar_router
from app.config import APP_NAME, APP_VERSION
from app.db import get_con
from app.ml.predict import ModelNotTrainedError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title=f"{APP_NAME} API", version=APP_VERSION,
              description="AI decision engine for second-life EV batteries. Demo outputs are clearly labelled SIMULATED.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.include_router(solar_router)


@app.on_event("startup")
def _startup():
    get_con()
    # warm up the demo batteries in the background so the first page load is instant
    import threading
    from app.services import demo_service
    def warm():
        try:
            for b in demo_service.list_batteries():
                demo_service.analyze(b["battery_id"])
        except Exception:
            logging.getLogger("rebat").exception("demo warm-up failed (model not trained?)")
    threading.Thread(target=warm, daemon=True).start()


@app.on_event("startup")
async def _auto_connect_esp32():
    """Connect to the ESP32 Battery Lab automatically (last working address, or found on the network).
    Set REBAT_ESP32_AUTOSTART=0 to disable."""
    import os
    if os.environ.get("REBAT_ESP32_AUTOSTART", "1") != "0":
        from app.api.routes import bridge
        from app.services.esp32_bridge import load_settings
        await bridge.start(load_settings(), save=False)


@app.on_event("shutdown")
async def _stop_bridge():
    from app.api.routes import bridge
    await bridge.stop()


@app.exception_handler(ModelNotTrainedError)
async def _no_model(_: Request, exc: ModelNotTrainedError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):
    logging.getLogger("rebat").exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": f"Internal error: {type(exc).__name__}: {exc}"})


# Serve the solar twin dashboard
SOLAR_DASHBOARD = Path(__file__).resolve().parents[2] / "rebat_solar" / "frontend" / "solar_twin_dashboard.html"

@app.get("/solar", include_in_schema=False)
@app.get("/solar-twin", include_in_schema=False)
def get_solar_dashboard():
    if SOLAR_DASHBOARD.exists():
        return FileResponse(SOLAR_DASHBOARD)
    return JSONResponse(status_code=404, content={"detail": "Solar dashboard file not found"})

# Serve the built frontend (frontend/dist) when present, so one process runs everything.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path in ("solar", "solar-twin"):
            if SOLAR_DASHBOARD.exists():
                return FileResponse(SOLAR_DASHBOARD)
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")

