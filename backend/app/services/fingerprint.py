"""Battery Fingerprint — a multidimensional profile built from measurements + model outputs.

Each dimension carries: raw value, unit, a 0–100 score (higher = better for reuse),
a grade, its provenance (measured / model / estimated / not measured).
Thermal, imbalance and resistance scores are percentiles against the reference
(training) population, so they are relative, not absolute certifications.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache

import numpy as np

from app.config import MODEL_DIR


@lru_cache(maxsize=1)
def reference() -> dict:
    p = MODEL_DIR / "feature_reference.json"
    return json.loads(p.read_text()) if p.exists() else {}


def pct_rank(col: str, x: float) -> float | None:
    ref = reference().get(col)
    if not ref or x is None or not math.isfinite(x):
        return None
    return float(np.interp(x, ref, np.linspace(0, 100, len(ref))))


def _f(x):
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def _lin(x, poor, good):
    return float(np.clip((x - poor) / (good - poor), 0, 1) * 100)


def grade(score, labels=("POOR", "MEDIUM", "GOOD")):
    if score is None:
        return "NOT MEASURED"
    return labels[2] if score >= 67 else labels[1] if score >= 40 else labels[0]


def build_fingerprint(meta, features: dict, info: dict, soh: dict, rul: dict, conf: dict, safety: list) -> dict:
    n, cap_nom = meta.series_cells, meta.nominal_capacity_ah
    s = soh["soh"]
    dims = {}

    def add(key, label, value, unit, score, prov, grade_labels=("POOR", "MEDIUM", "GOOD"), display=None):
        dims[key] = {"label": label, "value": value, "unit": unit,
                     "score": None if score is None else round(score, 1),
                     "grade": grade(score, grade_labels), "provenance": prov,
                     "display": display}

    add("soh", "State of Health", round(s, 1), "%", _lin(s, 50, 95), "model")
    r = rul["rul_cycles"]
    add("rul", "Remaining Useful Life", r, "cycles", _lin(r, 0, 2000), "model (prototype)")
    usable_ah = cap_nom * s / 100
    usable_wh = usable_ah * 3.65 * n
    add("capacity", "Usable Capacity", round(usable_ah, 3), "Ah", _lin(s, 50, 95), "model",
        display=f"{usable_ah:.2f} Ah · {usable_wh:.1f} Wh")

    ir_cell = features.get("ir_cell_mohm")
    if _f(ir_cell):
        pr = pct_rank("ir_cell_mohm", ir_cell)
        add("resistance", "Internal Resistance", round(ir_cell * n, 1), "mΩ (pack)", 100 - pr if pr is not None else None,
            "measured" if info.get("ir_source") == "pulse" else "reported", ("HIGH", "MEDIUM", "LOW"),
            display=f"{ir_cell * n:.1f} mΩ pack · {ir_cell:.1f} mΩ/cell")
    else:
        add("resistance", "Internal Resistance", None, "mΩ", None, "not measured")

    # power capability: max C-rate before a cell sags from 3.70 V OCV to 3.00 V
    if _f(ir_cell):
        i_max = 0.70 / (ir_cell / 1000.0)
        c_cap = i_max / max(usable_ah, 1e-3)
        p_max = i_max * 3.0 * n
        score = _lin(math.log10(max(c_cap, 0.1)), math.log10(2), math.log10(15))
        add("power", "Power Capability", round(c_cap, 1), "C (peak)", score, "estimated from IR",
            ("LOW", "MEDIUM", "HIGH"), display=f"{c_cap:.1f}C peak · {p_max:.0f} W")
    else:
        c_cap = None
        add("power", "Power Capability", None, "C", None, "not measured", ("LOW", "MEDIUM", "HIGH"))

    # thermal behaviour
    tr = features.get("thermal_response")
    if _f(tr):
        pr = pct_rank("thermal_response", tr)
        t_score = 100 - pr
        add("thermal", "Thermal Behaviour", round(features.get("t_rise", float("nan")), 2), "°C rise",
            t_score, "measured", display=f"+{features.get('t_rise', 0):.1f} °C · {tr:.1f} °C/(C²·h)")
    else:
        t_score = None
        add("thermal", "Thermal Behaviour", None, "°C", None, "not measured")

    deg = rul.get("degradation_rate_per_100")
    add("degradation", "Degradation Rate", deg, "% SOH / 100 cycles",
        None if deg is None else _lin(deg, 3.0, 0.5), "model (prototype)", ("HIGH", "MODERATE", "LOW"))

    # efficiency: measured coulombic x estimated voltage efficiency at 0.5C
    if _f(ir_cell):
        x = 0.5 * cap_nom * (ir_cell / 1000.0) * 1.6 / 3.7     # 1.6 ≈ ohmic+polarisation factor
        eff = (1 - x) / (1 + x)
        prov = "estimated from IR"
        if _f(info.get("coulombic_efficiency")):
            eff *= min(1.0, info["coulombic_efficiency"])
            prov = "measured CE × estimated VE"
        add("efficiency", "Round-trip Efficiency", round(eff, 3), "", _lin(eff, 0.85, 0.97), prov,
            display=f"{eff * 100:.1f} %")
    else:
        eff = None
        add("efficiency", "Round-trip Efficiency", None, "", None, "not measured")

    imb = features.get("cell_imbalance_mv")
    if _f(imb):
        add("imbalance", "Cell Imbalance", round(imb, 1), "mV", _lin(imb, 150, 15), "measured", ("HIGH", "MEDIUM", "LOW"))
    else:
        add("imbalance", "Cell Imbalance", None, "mV", None, "not measured", ("HIGH", "MEDIUM", "LOW"))

    cyc = features.get("cycle")
    add("cycles", "Cycle Count", int(cyc) if _f(cyc) else None, "cycles", None,
        "reported" if _f(cyc) else "unknown", display=None)
    dvq = features.get("dv_dq")
    add("voltage", "Voltage Behaviour", round(dvq, 3) if _f(dvq) else None, "V/cell per Q/Qnom",
        None if not _f(dvq) else pct_rank("dv_dq", dvq), "measured",   # shallower slope = healthier
        display=None if not _f(dvq) else f"dV/dQ {dvq:.2f} · recovery {features.get('v_recovery_cell_mv', float('nan')):.0f} mV")

    # thermal risk level (fingerprint-level safety indicator)
    alarm = any(a["level"] == "ALARM" for a in safety)
    warn = any(a["level"] == "WARNING" for a in safety)
    if alarm or (t_score is not None and t_score < 10):
        risk = "HIGH"
    elif warn or (t_score is not None and t_score < 35):
        risk = "MEDIUM"
    elif t_score is None:
        risk = "UNKNOWN"
    else:
        risk = "LOW"

    power_level = dims["power"]["grade"]
    metrics = {   # flat values the suitability engine scores against
        "soh": s, "rul_cycles": r, "power_c_capability": c_cap, "ir_cell_mohm": ir_cell if _f(ir_cell) else None,
        "thermal_score": t_score, "thermal_risk_level": risk, "efficiency": eff,
        "degradation_rate": deg, "imbalance_mv": imb if _f(imb) else None, "confidence": conf["value"],
    }
    radar = [{"axis": d["label"].replace("Internal ", "").replace("Round-trip ", ""), "key": k, "score": d["score"]}
             for k, d in dims.items() if k in ("soh", "rul", "resistance", "power", "thermal", "degradation", "efficiency", "imbalance", "voltage")]
    return {"dimensions": dims, "metrics": metrics, "thermal_risk": risk, "power_capability": power_level,
            "radar": radar, "summary": {
                "capacity": dims["capacity"]["grade"], "resistance": dims["resistance"]["grade"],
                "thermal": dims["thermal"]["grade"], "power": power_level, "degradation": dims["degradation"]["grade"]}}
