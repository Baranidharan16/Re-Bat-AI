"""REST + SSE API (v1)."""
from __future__ import annotations

import asyncio
import io
import json
import os
import time
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app import db
from app.config import APP_NAME, APP_VERSION, CONFIDENCE_BANDS, CONFIDENCE_TOLERANCE_PTS, RUL_EOL_SOH, SAFETY, load_json
from app.ml import temporal_model
from app.ml.data_ingestion import DataValidationError, split_tests
from app.ml.feature_engineering import FEATURE_LABELS, MODEL_FEATURES, Meta
from app.ml.predict import ModelNotTrainedError, get_predictor
from app.schemas.models import ManualInput, SimStart, TelemetryBatch, TelemetryReading, TestRequest
from app.services import adaptive_testing, assistant, circular, demo_service, ev_models, forensics, ledger, pipeline
from app.services.live import manager
from app.services.esp32_bridge import BridgeConfig, ESP32Bridge, load_settings
from app.services.esp32_hub import COMMANDS, hub, lan_ips, verdict_message
from pydantic import BaseModel, Field

bridge = ESP32Bridge(manager)
from app.services.suitability import app_config

router = APIRouter(prefix="/api/v1")
DEVICE_KEY = os.environ.get("REBAT_DEVICE_KEY")   # if set, ESP32 must send X-Device-Key


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ system
@router.get("/health")
def health():
    try:
        card = get_predictor().card
        model = {"loaded": True, "status": card["status"]}
    except ModelNotTrainedError as e:
        model = {"loaded": False, "status": str(e)}
    return {"app": APP_NAME, "version": APP_VERSION, "time": _now(), "model": model,
            "live_sessions": len(manager.sessions), "esp32_websocket_rigs": len(hub.rigs)}


@router.get("/model/status")
def model_status():
    p = get_predictor()
    imp = p.global_importance()
    return {"soh_model": p.card, "global_importance": [{"feature": k, "label": FEATURE_LABELS.get(k, k), "gain_share": round(v, 4)}
                                                       for k, v in list(imp.items())[:12]],
            "temporal_model": temporal_model.status(),
            "rul_model": {"name": "Power-law fade fit + population prior", "status": "PROTOTYPE / EXPERIMENTAL",
                          "eol_soh": RUL_EOL_SOH, "note": "Not validated on real ageing data."},
            "router": {"name": "Fingerprint × requirement-profile matcher", "status": "Prototype weights",
                       "evaluation": "Top-1 / Top-3 accuracy pending labelled second-life outcomes"},
            "confidence": {"tolerance_pts": CONFIDENCE_TOLERANCE_PTS, "bands": CONFIDENCE_BANDS},
            "safety_limits": SAFETY}


@router.get("/config/applications")
def config_apps():
    return app_config()


@router.get("/config/tests")
def config_tests():
    return adaptive_testing.catalog()


@router.get("/config/screening")
def config_screening():
    return load_json("screening.json")


# ------------------------------------------------------------------ demo mode
@router.get("/demo/batteries")
def demo_list():
    return demo_service.list_batteries()


@router.get("/demo/batteries/{bid}/analysis")
def demo_analysis(bid: str):
    try:
        return _sealed(demo_service.analyze(bid))
    except KeyError:
        raise HTTPException(404, f"Unknown demo battery {bid}")


def _sealed(res: dict) -> dict:
    """Every analysed battery gets a passport block in the SHA-256 ledger (deduplicated by evidence hash)."""
    try:
        res = dict(res)
        res["passport_block"] = ledger.seal_passport(res)
    except Exception as e:   # the ledger must never block an analysis
        import logging
        logging.getLogger("rebat").warning("passport seal failed: %s", e)
    return res


@router.post("/demo/batteries/{bid}/reset")
def demo_reset(bid: str):
    try:
        demo_service.reset(bid)
        return demo_service.analyze(bid)
    except KeyError:
        raise HTTPException(404, f"Unknown demo battery {bid}")


# ------------------------------------------------------------------ analysis (not persisted)
@router.post("/analyze/manual")
def analyze_manual(inp: ManualInput):
    meta = Meta(inp.series_cells, inp.nominal_capacity_ah)
    f, info = pipeline.manual_features(inp.model_dump(), meta)
    if sum(1 for v in f.values() if v == v) < 2:
        raise HTTPException(422, "Provide at least two measured parameters.")
    return _sealed(pipeline.analyze_features(f, info, meta, battery_id=inp.battery_id, source="MANUAL", variant="spot"))


@router.post("/analyze/csv")
async def analyze_csv(file: UploadFile = File(...), battery_id: str = Form("CSV-001"),
                      series_cells: int = Form(3), nominal_capacity_ah: float = Form(2.5)):
    raw = await file.read()
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(413, "CSV larger than 25 MB")
    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception as e:
        raise HTTPException(422, f"Could not parse CSV: {e}")
    meta = Meta(series_cells, nominal_capacity_ah)
    try:
        from app.ml.data_ingestion import normalise_columns, validate_and_clean
        from app.ml.predict import get_predictor as gp
        from app.ml.feature_engineering import extract_features
        clean, rep = validate_and_clean(df, series_cells)
        tests = list(split_tests(clean))
        history = []
        p = gp()
        for c, g in tests[:-1]:                       # earlier cycles in the file → ageing history
            fx = extract_features(g, meta)["features"]
            o = p.predict_frame(pd.DataFrame([fx]))
            history.append({"cycle": c, "soh": float(o["soh"][0]), "lo": float(o["lo"][0]), "hi": float(o["hi"][0])})
        c_last, g_last = tests[-1]
        ex = extract_features(g_last, meta)
        res = pipeline.analyze_features(ex["features"], ex["info"], meta, battery_id=battery_id, source="CSV",
                                        history=history, timeseries=g_last, validation=rep.to_dict())
        res["csv"] = {"filename": file.filename, "tests_in_file": len(tests), "analysed_cycle": c_last}
        return _sealed(res)
    except DataValidationError as e:
        raise HTTPException(422, {"message": "CSV failed validation", "report": e.report.to_dict()})


@router.get("/samples/csv")
def sample_csv():
    """A simulated test file in the canonical format (for trying the CSV upload)."""
    from app.simulation.battery_sim import BatterySimulator, TestConfig
    from app.simulation.demo_profiles import build_params
    p = build_params("RB-B02"); p.seed = 9
    df = BatterySimulator(p).run_test(TestConfig(current_a=1.25))
    buf = io.StringIO(); df.round(5).to_csv(buf, index=False)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=rebat_sample_SIMULATED.csv"})


# ------------------------------------------------------------------ adaptive testing
@router.post("/tests/request")
async def request_test(req: TestRequest):
    test = next((t for t in adaptive_testing.catalog()["tests"] if t["id"] == req.test_id), None)
    if not test:
        raise HTTPException(404, f"Unknown test {req.test_id}")
    if req.context == "demo":
        try:
            return demo_service.run_requested_test(req.battery_id, req.test_id)
        except KeyError:
            raise HTTPException(404, f"Unknown demo battery {req.battery_id}")
        except PermissionError as e:
            raise HTTPException(409, str(e))
    # live context: queue for the rig (ESP32 polls) or the simulator
    s = manager.sessions.get(req.battery_id)
    if s and s.last_forecast and s.last_forecast["safety"]["status"] == "ALARM":
        raise HTTPException(409, "Safety alarm active — inspect battery before further testing.")
    with db.tx() as con:
        cur = con.execute("INSERT INTO test_requests(battery_id, test_id, status, reason, command_json, created_at) VALUES (?,?,?,?,?,?)",
                          (req.battery_id, req.test_id, "pending", req.reason, json.dumps(test["hardware_command"]), _now()))
        rid = cur.lastrowid
    started = False
    if s and s.source == "LIVE_SIM" and (s.sim_task is None or s.sim_task.done()):
        with db.tx() as con:
            con.execute("UPDATE test_requests SET status='done', updated_at=? WHERE id=?", (_now(), rid))
        profile = "RB-" + s.battery_id.split("-")[1]
        await manager.start_simulation(profile, req.test_id)
        started = True
    return {"request_id": rid, "status": "started" if started else "queued", "test": test,
            "note": "Simulator executes immediately." if started else
                    "Queued — the rig picks it up via GET /api/v1/hardware/{battery_id}/commands. The rig's own protection must enforce limits."}


# ------------------------------------------------------------------ hardware (ESP32)
def _check_key(key):
    if DEVICE_KEY and key != DEVICE_KEY:
        raise HTTPException(401, "Invalid device key")


@router.post("/hardware/ingest")
async def hw_ingest(body: TelemetryReading | TelemetryBatch, x_device_key: str | None = Header(None)):
    _check_key(x_device_key)
    items = body.readings if isinstance(body, TelemetryBatch) else [body]
    last = None
    for r in items:
        last = await manager.ingest(r.model_dump(), "ESP32")
    return {"accepted": len(items), **(last or {})}


@router.get("/hardware/{bid}/commands")
def hw_commands(bid: str, x_device_key: str | None = Header(None)):
    _check_key(x_device_key)
    rows = db.query("SELECT id, test_id, command_json, created_at FROM test_requests WHERE battery_id=? AND status='pending' ORDER BY id", (bid,))
    with db.tx() as con:
        for r in rows:
            con.execute("UPDATE test_requests SET status='sent', updated_at=? WHERE id=?", (_now(), r["id"]))
    return {"commands": [{"id": r["id"], "test_id": r["test_id"], **json.loads(r["command_json"])} for r in rows]}


@router.post("/hardware/{bid}/commands/{cid}/ack")
def hw_ack(bid: str, cid: int, status: str = "done", x_device_key: str | None = Header(None)):
    _check_key(x_device_key)
    if status not in ("done", "cancelled", "refused_by_safety"):
        raise HTTPException(422, "status must be done | cancelled | refused_by_safety")
    with db.tx() as con:
        con.execute("UPDATE test_requests SET status=?, updated_at=? WHERE id=? AND battery_id=?", (status, _now(), cid, bid))
    return {"ok": True}


# ------------------------------------------------------------------ live
@router.post("/live/sim/start")
async def live_sim_start(req: SimStart):
    try:
        s = await manager.start_simulation(req.profile_id, req.test_id, req.speed_hz)
    except KeyError:
        raise HTTPException(404, f"Unknown profile {req.profile_id}")
    return s.summary()


@router.post("/live/{bid}/stop")
def live_stop(bid: str):
    try:
        return manager.stop(bid).summary()
    except KeyError:
        raise HTTPException(404, "No such session")


@router.get("/live/sessions")
def live_sessions():
    return [s.summary() for s in manager.sessions.values()]


@router.get("/live/{bid}/latest")
def live_latest(bid: str):
    s = manager.sessions.get(bid)
    if s is None:
        raise HTTPException(404, "No live session for this battery")
    return {"session": s.summary(), "readings": (s.readings or s.last_window)[-600:], "forecast": s.last_forecast, "alerts": s.alerts}


@router.get("/live/{bid}/stream")
async def live_stream(bid: str, request: Request):
    s = manager.sessions.get(bid)
    if s is None:
        raise HTTPException(404, "No live session for this battery")
    q: asyncio.Queue = asyncio.Queue(maxsize=2000)
    s.subscribers.add(q)

    async def gen():
        try:
            snap = {"type": "snapshot", "session": s.summary(), "readings": [
                {k: r.get(k) for k in ("t_s", "voltage", "current", "temperature", "capacity", "cycle_count",
                                       "internal_resistance", "cell_v_min", "cell_v_max", "gas_v")} for r in (s.readings or s.last_window)[-600:]],
                    "forecast": s.last_forecast, "alerts": s.alerts}
            yield f"data: {json.dumps(pipeline.clean_json(snap))}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(pipeline.clean_json(ev))}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            s.subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ stored (real-time) records
@router.get("/batteries")
def batteries():
    return db.query("SELECT b.*, (SELECT COUNT(*) FROM forecasts f WHERE f.battery_id=b.battery_id) AS n_forecasts,"
                    " (SELECT COUNT(*) FROM readings r WHERE r.battery_id=b.battery_id) AS n_readings FROM batteries b ORDER BY created_at DESC")


@router.get("/batteries/{bid}/forecasts")
def battery_forecasts(bid: str, limit: int = 50):
    return db.query("SELECT id, created_at, source, cycle, soh, soh_lo, soh_hi, confidence, rul_cycles, top_application,"
                    " decision, safety_status, n_readings, is_final, block_index FROM forecasts WHERE battery_id=? ORDER BY id DESC LIMIT ?",
                    (bid, limit))


@router.get("/ledger")
def ledger_list(limit: int = 50, battery_id: str | None = None):
    return ledger.list_blocks(limit, battery_id)


@router.get("/ledger/model-fingerprint")
def ledger_model_fp():
    """Hash of the SOH model's hyperparameters + weights, stamped into every block."""
    return ledger.model_fingerprint()


@router.get("/ledger/verify")
def ledger_verify():
    return ledger.verify()


# ------------------------------------------------------------------ circular economy + forensics
class PackProfile(BaseModel):
    chemistry: str = "NMC532"
    cell_format: str = "cylindrical_18650"
    cell_mass_g: float | None = Field(None, gt=0, lt=100000)


@router.get("/circular/config")
def circular_config():
    c = circular.cfg()
    return {"pack": circular.pack_profile(),
            "chemistries": {k: v["label"] for k, v in c["chemistries"].items()},
            "cell_formats": {k: {"label": v["label"], "cell_mass_g": v["cell_mass_g"], "cell_ah": v["cell_ah"]} for k, v in c["cell_formats"].items()},
            "loop": c["loop"], "process": c["process"], "policy": c["policy"], "reuse_assumptions": c["reuse"]}


@router.post("/circular/pack")
def circular_pack(p: PackProfile):
    """Chemistry + cell format of the battery on the rig (used for the mineral estimate)."""
    try:
        return circular.save_pack_profile(p.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/circular/minerals")
def circular_minerals(series_cells: int = 3, nominal_capacity_ah: float = 2.5, chemistry: str | None = None,
                      cell_format: str | None = None, cell_mass_g: float | None = None):
    c = circular.cfg()
    if chemistry and chemistry not in c["chemistries"]:
        raise HTTPException(422, f"Unknown chemistry {chemistry}")
    if cell_format and cell_format not in c["cell_formats"]:
        raise HTTPException(422, f"Unknown cell format {cell_format}")
    if not (1 <= series_cells <= 400) or not (0 < nominal_capacity_ah <= 2000):
        raise HTTPException(422, "series_cells 1–400, nominal_capacity_ah 0–2000")
    return circular.minerals(series_cells, nominal_capacity_ah, chemistry, cell_format, cell_mass_g)


@router.get("/forensics/{bid}")
def forensic_report(bid: str):
    """Chain of custody, SOH trend, alerts and ledger integrity for a battery streamed from the rig."""
    try:
        return pipeline.clean_json(forensics.report(bid))
    except KeyError:
        raise HTTPException(404, "No stored rig data for this battery. Demo, CSV and manual analyses are not stored.")


# ------------------------------------------------------------------ EV pack explorer (3D digital twin data)
@router.get("/ev-models")
def ev_model_list():
    return ev_models.catalog()


@router.get("/ev-models/{mid}")
def ev_model(mid: str):
    try:
        return ev_models.report(mid)
    except KeyError:
        raise HTTPException(404, f"Unknown EV model {mid}")


# ------------------------------------------------------------------ AI battery assistant
class ChatTurn(BaseModel):
    role: str = Field("user", pattern="^(user|assistant)$")
    text: str = Field("", max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    context: dict = Field(default_factory=dict)


@router.get("/chat/status")
def chat_status():
    return assistant.status()


@router.post("/chat")
async def chat(req: ChatRequest):
    """Ask about the battery open in the dashboard. Gemini when a key is configured, offline answers otherwise."""
    if len(json.dumps(req.context, default=str)) > 60000:
        raise HTTPException(413, "Context too large")
    return await asyncio.to_thread(assistant.ask, req.message, [h.model_dump() for h in req.history], req.context)


# ------------------------------------------------------------------ RMK-REVOLT ESP32 Battery Lab bridge
class BridgeStart(BaseModel):
    esp32_url: str = Field("http://10.55.137.107", description="Address of the ESP32 Battery Lab page")
    battery_id: str = Field("RB-001", min_length=1, max_length=64)
    series_cells: int = Field(1, ge=1, le=400)
    nominal_capacity_ah: float = Field(2.5, gt=0)
    invert_current: bool = True
    current_offset_a: float = 0.0
    rest_close_s: float = Field(120.0, ge=10, le=3600)
    poll_interval_s: float = Field(1.0, ge=0.2, le=10)
    cycle_count: int | None = Field(None, ge=0)


@router.post("/bridge/start")
async def bridge_start(req: BridgeStart):
    url = req.esp32_url.strip()
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    await bridge.start(BridgeConfig(**{**req.model_dump(), "esp32_url": url, "auto_discover": bridge.cfg.auto_discover}))
    return bridge.status()


@router.post("/bridge/discover")
async def bridge_discover():
    """Scan the local Wi-Fi network for the ESP32 Battery Lab and connect to it."""
    if not bridge.state.running:
        await bridge.start(load_settings())
    url = await bridge.find_now()
    if not url:
        raise HTTPException(404, "No ESP32 Battery Lab found on this network. Check that the ESP32 is powered and on the same Wi-Fi as this computer.")
    return bridge.status()


@router.post("/bridge/stop")
async def bridge_stop():
    await bridge.stop()
    return bridge.status()


@router.post("/bridge/close-window")
async def bridge_close_window():
    """End the current test now: final AI forecast, store, seal in the ledger."""
    await bridge.close_window("closed from dashboard")
    return bridge.status()


@router.get("/bridge/status")
def bridge_status():
    return bridge.status()


@router.get("/hardware/connect-info")
def hw_connect_info(request: Request):
    """What to put in the ESP32 firmware, and which rigs are connected right now."""
    port = request.url.port or 8000
    ips = lan_ips()
    return {"websocket_path": "/api/v1/hardware/ws", "http_ingest_path": "/api/v1/hardware/ingest",
            "lan_ips": ips, "port": port,
            "websocket_urls": [f"ws://{ip}:{port}/api/v1/hardware/ws" for ip in ips],
            "firmware_settings": {"WS_HOST": ips[0] if ips else "<laptop-ip>", "WS_PORT": port, "WS_PATH": "/api/v1/hardware/ws"},
            "commands": COMMANDS, "hub": hub.status(), "device_key_required": bool(DEVICE_KEY)}


@router.get("/hardware/rigs")
def hw_rigs():
    return hub.status()


class RigCommand(BaseModel):
    cmd: str = Field(..., description=" | ".join(COMMANDS))


@router.post("/hardware/{bid}/command")
async def hw_command(bid: str, c: RigCommand):
    """Send a command to the ESP32 over its WebSocket (lamp on/off/auto, start/stop test, load)."""
    if c.cmd not in COMMANDS:
        raise HTTPException(422, f"cmd must be one of: {', '.join(COMMANDS)}")
    s = manager.sessions.get(bid)
    if c.cmd in ("lamp_on", "load_on", "start_test", "quick_test") and s and s.last_forecast \
            and s.last_forecast["safety"]["status"] == "ALARM":
        raise HTTPException(409, "Safety alarm active — inspect the battery first.")
    ok = await hub.send(bid, {"type": "command", "cmd": c.cmd, "at": _now()})
    if not ok:
        raise HTTPException(409, f"No ESP32 connected over WebSocket for battery {bid}. "
                                 f"Flash the WebSocket firmware and point it at ws://<laptop-ip>:8000/api/v1/hardware/ws.")
    return {"sent": True, "cmd": c.cmd, "description": COMMANDS[c.cmd]}


@router.websocket("/hardware/ws")
async def hardware_ws(ws: WebSocket):
    """ESP32 connector (push). The board opens one WebSocket and streams every reading.

    Accepts three message shapes:
      {"type":"hello","battery_id":..,"firmware":..,"ip":..}         – identifies the rig
      canonical TelemetryReading JSON (voltage, current, ...)          – preferred
      RMK-REVOLT Battery Lab JSON (battery_v, current_a, ...)          – converted with the bridge settings
    Replies: ack per reading, a verdict after every AI forecast, and dashboard commands."""
    if DEVICE_KEY and ws.query_params.get("key") != DEVICE_KEY:
        await ws.close(code=4401)
        return
    await ws.accept()
    from dataclasses import replace
    rig = hub.add(ws, f"{ws.client.host}:{ws.client.port}" if ws.client else "?")
    local = ESP32Bridge(manager)            # own window/rest state per connection
    local.cfg = replace(bridge.cfg)
    local.state.running = True
    await ws.send_text(json.dumps({"type": "welcome", "server": f"{APP_NAME} {APP_VERSION}", "commands": list(COMMANDS)}))
    try:
        while True:
            msg = await ws.receive_text()
            rig.last_msg_at = time.time()
            rig.messages += 1
            try:
                raw = json.loads(msg)
                kind = raw.get("type")
                if kind == "hello":
                    rig.battery_id = str(raw.get("battery_id") or rig.battery_id)
                    rig.firmware, rig.device_ip = raw.get("firmware"), raw.get("ip")
                    local.cfg.battery_id = rig.battery_id
                    await ws.send_text(json.dumps({"type": "hello_ack", "battery_id": rig.battery_id}))
                    continue
                if kind == "status":
                    rig.battery_id = str(raw.get("battery_id") or rig.battery_id)
                    await manager.update_aux(rig.battery_id, raw)
                    rig.aux = manager.sessions[rig.battery_id].aux
                    continue
                if kind in ("ping", "event"):
                    await ws.send_text(json.dumps({"type": "pong", "t": time.time()}))
                    continue
                if "battery_v" in raw:
                    if "battery_id" in raw:
                        local.cfg.battery_id = str(raw["battery_id"])
                    for k in ("series_cells", "nominal_capacity_ah"):
                        if k in raw:
                            setattr(local.cfg, k, type(getattr(local.cfg, k))(raw[k]))
                    out = await local.handle(raw, "ESP32")
                    bid = local.cfg.battery_id
                else:
                    tr = TelemetryReading(**{k: v for k, v in raw.items() if k != "type"})
                    out = await manager.ingest(tr.model_dump(), "ESP32")
                    bid = tr.battery_id
                rig.battery_id = bid
                s = manager.sessions.get(bid)
                if s:
                    rig.aux = s.aux
                await ws.send_text(json.dumps({"type": "ack", "ok": True, "buffer": (out or {}).get("buffer"),
                                               "alerts": [a["code"] for a in (out or {}).get("alerts", [])]}))
                fc = s.last_forecast if s else None
                fid = ((fc or {}).get("ledger") or {}).get("forecast_id")
                if fc and fid != rig.last_verdict_id:
                    rig.last_verdict_id = fid
                    await ws.send_text(json.dumps(pipeline.clean_json(verdict_message(fc))))
            except Exception as e:  # bad message: report, keep the socket open
                await ws.send_text(json.dumps({"type": "ack", "ok": False, "error": str(e)[:200]}))
    except WebSocketDisconnect:
        await local.close_window("WebSocket closed")
    finally:
        hub.remove(ws)


@router.websocket("/live/{bid}/ws")
async def live_ws(ws: WebSocket, bid: str):
    """Dashboard live feed over WebSocket (same events as the SSE stream: snapshot, reading, forecast, status)."""
    await ws.accept()
    s = manager.sessions.get(bid)
    if s is None:
        await ws.send_text(json.dumps({"type": "error", "detail": "No live session for this battery"}))
        await ws.close(code=4404)
        return
    q: asyncio.Queue = asyncio.Queue(maxsize=2000)
    s.subscribers.add(q)
    try:
        snap = {"type": "snapshot", "session": s.summary(), "readings": [
            {k: r.get(k) for k in ("t_s", "voltage", "current", "temperature", "capacity", "cycle_count",
                                   "internal_resistance", "cell_v_min", "cell_v_max", "gas_v")} for r in (s.readings or s.last_window)[-600:]],
                "forecast": s.last_forecast, "alerts": s.alerts}
        await ws.send_text(json.dumps(pipeline.clean_json(snap)))
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=15)
                await ws.send_text(json.dumps(pipeline.clean_json(ev)))
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"type": "keepalive"}))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        s.subscribers.discard(q)
