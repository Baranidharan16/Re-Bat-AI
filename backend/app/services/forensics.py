"""Battery forensics.

Two levels:
  diagnose(result)  -> for any analysis: which ageing mechanism dominates, the evidence for it,
                       anomalies from the test, and a hash of the evidence (the "battery passport" ID).
  report(battery_id) -> for batteries streamed from the rig: chain of custody (every stored test
                       window), SOH trajectory, alert history and the ledger integrity check for
                       exactly this battery's blocks.
"""
from __future__ import annotations

import hashlib
import json
import math

from app import db
from app.services import ledger


def _f(x):
    try:
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return None


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def passport_id(battery_id: str) -> str:
    return "BP-" + hashlib.sha256(battery_id.encode()).hexdigest()[:10].upper()


def evidence_hash(result: dict) -> str:
    keep = {"battery_id": result["battery_id"], "source": result["source"], "meta": result["meta"],
            "features": result.get("features"), "soh": [result["soh"]["soh"], result["soh"]["lo"], result["soh"]["hi"]],
            "rul": result["rul"].get("rul_cycles"), "decision": result["router"]["decision"]["id"],
            "model": result["model"]["version"]}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def diagnose(result: dict) -> dict:
    m = result["fingerprint"]["metrics"]
    soh = _f(result["soh"]["soh"]) or 0.0
    ir = _f(m.get("ir_cell_mohm"))
    th = _f(m.get("thermal_score"))
    imb = _f(m.get("imbalance_mv"))
    rate = _f(m.get("degradation_rate"))
    alerts = result["safety"]["alerts"]
    gas = [a for a in alerts if "GAS" in a["code"].upper()]

    mech = [
        {"id": "capacity_fade", "name": "Capacity fade (lithium loss)",
         "explanation": "Lithium gets trapped in surface layers over many cycles, so the cell stores less charge.",
         "evidence": f"SOH {soh:.1f}%", "severity": _clamp((100 - soh) / 45 * 100), "measured": True},
        {"id": "resistance_growth", "name": "Resistance growth",
         "explanation": "Surface films thicken and contacts wear, so the cell heats up and voltage sags under load.",
         "evidence": f"{ir:.0f} mΩ per cell (fresh ≈ 20–30 mΩ)" if ir else "Not measured — needs a pulse test",
         "severity": _clamp((ir - 25) / (125 - 25) * 100) if ir else None, "measured": ir is not None},
        {"id": "thermal_stress", "name": "Thermal stress",
         "explanation": "The cell heats more than expected under load — a sign of damage or poor cooling in its first life.",
         "evidence": f"Thermal score {th:.0f}/100 · risk {str(m.get('thermal_risk_level', '')).lower()}" if th is not None else "No temperature data",
         "severity": _clamp(100 - th) if th is not None else None, "measured": th is not None},
        {"id": "cell_imbalance", "name": "Cell imbalance",
         "explanation": "Cells in the pack have drifted apart; the weakest cell limits the whole pack.",
         "evidence": f"{imb:.0f} mV spread between cells" if imb is not None else "No cell-tap data",
         "severity": _clamp((imb - 10) / (100 - 10) * 100) if imb is not None else None, "measured": imb is not None},
        {"id": "fast_ageing", "name": "Accelerated ageing",
         "explanation": "Capacity is dropping faster per cycle than a normal module.",
         "evidence": f"{rate:.2f} SOH points per 100 cycles" if rate is not None else "Needs ageing history",
         "severity": _clamp((rate - 0.8) / (3.0 - 0.8) * 100) if rate is not None else None, "measured": rate is not None},
        {"id": "venting", "name": "Gas / electrolyte venting",
         "explanation": "Gas near the battery can mean the electrolyte is leaking or decomposing.",
         "evidence": gas[0]["message"] if gas else "No gas rise detected",
         "severity": 100.0 if any(a["level"] == "ALARM" for a in gas) else (60.0 if gas else 0.0), "measured": True},
    ]
    for x in mech:
        s = x["severity"]
        x["severity"] = None if s is None else round(s, 1)
        x["level"] = "not measured" if s is None else "high" if s >= 66 else "medium" if s >= 33 else "low"
    scored = [x for x in mech if x["severity"] is not None]
    primary = max(scored, key=lambda x: x["severity"]) if scored else None
    unmeasured = [x["name"] for x in mech if x["severity"] is None]
    if primary and primary["severity"] < 20:
        verdict = "No significant damage mechanism found. The battery has aged normally."
    elif primary:
        verdict = f"Dominant mechanism: {primary['name'].lower()} ({primary['evidence']})."
    else:
        verdict = "Not enough measurements to attribute the ageing."
    return {
        "passport_id": passport_id(result["battery_id"]),
        "evidence_hash": evidence_hash(result),
        "primary": primary["id"] if primary else None,
        "verdict": verdict,
        "mechanisms": sorted(mech, key=lambda x: -(x["severity"] if x["severity"] is not None else -1)),
        "unmeasured": unmeasured,
        "anomalies": [{"level": a["level"], "code": a["code"], "message": a["message"], "t_s": a.get("t_s")} for a in alerts],
        "data": {"source": result["data_label"], "samples": (result.get("measurements") or {}).get("n_samples"),
                 "validation_warnings": (result.get("validation") or {}).get("warnings", []),
                 "missing_features": result.get("missing_features", []),
                 "sealed_in_ledger": bool(result.get("ledger")), "model": f"{result['model']['name']} {result['model']['version']}"},
    }


def report(battery_id: str) -> dict:
    bat = db.query("SELECT * FROM batteries WHERE battery_id=?", (battery_id,))
    if not bat:
        raise KeyError(battery_id)
    rows = db.query("SELECT id, session_id, created_at, source, cycle, soh, soh_lo, soh_hi, confidence, rul_cycles,"
                    " top_application, decision, safety_status, n_readings, is_final, block_index, result_json"
                    " FROM forecasts WHERE battery_id=? ORDER BY id", (battery_id,))
    events, alerts, pathways = [], [], []
    last = None
    for r in rows:
        res = json.loads(r.pop("result_json"))
        circ = res.get("circular") or {}
        pw = circ.get("pathway")
        pathways.append(pw)
        for a in (res.get("safety") or {}).get("alerts", []):
            alerts.append({"at": r["created_at"], **{k: a.get(k) for k in ("level", "code", "message")}})
        events.append({**r, "pathway": pw, "headline": circ.get("headline")})
        last = res
    blocks = {b["idx"]: b for b in ledger.list_blocks(limit=1000, battery_id=battery_id)}
    v = ledger.verify()
    mine = [b for b in v["blocks"] if b["idx"] in blocks]
    for e in events:
        b = blocks.get(e["block_index"])
        e["block_hash"] = b["block_hash"] if b else None
    n_readings = db.query("SELECT COUNT(*) AS n FROM readings WHERE battery_id=?", (battery_id,))[0]["n"]
    custody = [{"at": bat[0]["created_at"], "event": "First seen", "detail": f"{bat[0]['source']} · {bat[0]['series_cells']}S {bat[0]['nominal_capacity_ah']} Ah"}]
    prev_pw = None
    for e in events:
        if e["is_final"]:
            custody.append({"at": e["created_at"], "event": "Test completed",
                            "detail": f"SOH {e['soh']:.1f}% · {e['n_readings']} readings sealed in block #{e['block_index']}"})
        if e["pathway"] and e["pathway"] != prev_pw:
            custody.append({"at": e["created_at"], "event": f"Routed: {e['pathway'].lower()}", "detail": e["headline"] or ""})
            prev_pw = e["pathway"]
    return {
        "battery_id": battery_id, "passport_id": passport_id(battery_id), "battery": bat[0],
        "n_forecasts": len(events), "n_readings": n_readings,
        "timeline": events[-50:], "custody": custody[-30:], "alerts": alerts[-30:],
        "soh_trend": [{"at": e["created_at"], "soh": e["soh"], "lo": e["soh_lo"], "hi": e["soh_hi"], "final": bool(e["is_final"])} for e in events],
        "integrity": {"chain_valid": v["valid"], "blocks_checked": len(mine),
                      "blocks_ok": sum(1 for b in mine if b["ok"]),
                      "problems": [b for b in mine if not b["ok"]], "head": v["head"]},
        "latest": diagnose(last) if last else None,
    }
