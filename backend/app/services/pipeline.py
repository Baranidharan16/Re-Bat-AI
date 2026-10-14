"""The RE-BAT AI pipeline. One entry point for every input mode.

Raw data → validation → cleaning → feature engineering → SOH model (+interval,
OOD, SHAP) → RUL → fingerprint → suitability ranking → explanation →
confidence → adaptive-test recommendation.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.config import load_json
from app.ml.data_ingestion import validate_and_clean
from app.ml.feature_engineering import MODEL_FEATURES, Meta, extract_features
from app.ml.predict import get_predictor
from app.ml.rul import estimate_rul
from app.services import adaptive_testing, circular, confidence, explain, fingerprint, forensics, safety, suitability

SOURCE_LABELS = {"SIMULATED": "SIMULATED DATA", "DEMO": "DEMO · SIMULATED BATTERY", "CSV": "CSV UPLOAD",
                 "MANUAL": "MANUAL INPUT", "ESP32": "LIVE · ESP32 HARDWARE", "LIVE_SIM": "LIVE · SIMULATION MODE"}


def clean_json(o):
    if isinstance(o, dict):
        return {k: clean_json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean_json(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def decimate(df: pd.DataFrame, n_max: int = 400) -> list[dict]:
    if df is None or not len(df):
        return []
    step = max(1, len(df) // n_max)
    d = df.iloc[::step]
    return [{"t": float(r.timestamp), "v": float(r.voltage), "i": float(r.current),
             "T": None if pd.isna(r.temperature) else float(r.temperature),
             "q": None if pd.isna(r.capacity) else float(r.capacity)} for r in d.itertuples()]


def screening_label(soh: float) -> dict:
    cfg = load_json("screening.json")
    for r in cfg["ranges"]:
        if r["min"] <= soh <= r["max"] or (r["min"] == 0 and soh < r["max"]):
            return {"range": f"{r['min']}–{r['max']}%", "label": r["label"], "disclaimer": cfg["label"]}
    return {"range": "", "label": "", "disclaimer": cfg["label"]}


def analyze_features(features: dict, info: dict, meta: Meta, *, battery_id: str, source: str,
                     history: list[dict] | None = None, timeseries: pd.DataFrame | None = None,
                     validation: dict | None = None, evidence: list | None = None,
                     extra_alerts: list | None = None, variant: str = "full") -> dict:
    pred = get_predictor()
    X = pd.DataFrame([{k: features.get(k, np.nan) for k in MODEL_FEATURES}]).astype(float)
    out = pred.predict_frame(X, variant)
    soh_v, lo, hi = float(out["soh"][0]), float(out["lo"][0]), float(out["hi"][0])
    ood_score, ood, miss = pred.ood_score(X, variant)
    soh_conf = confidence.soh_confidence(lo, hi, ood)
    soh = {"soh": round(soh_v, 1), "lo": round(lo, 1), "hi": round(hi, 1),
           "baseline_ridge": round(pred.baseline_predict(X), 1) if variant == "full" else None,
           "model_variant": "time-series features" if variant == "full" else "spot measurements (manual)",
           "ood": bool(ood), "ood_score": None if ood_score != ood_score else round(ood_score, 3),
           "missing_fraction": round(miss, 2), "confidence": soh_conf,
           "screening": screening_label(soh_v)}

    cyc = features.get("cycle")
    cyc = None if cyc is None or (isinstance(cyc, float) and math.isnan(cyc)) else float(cyc)
    rul = estimate_rul(history or [], {"cycle": cyc, "soh": soh_v, "lo": lo, "hi": hi})

    alerts = safety.check_test(info, meta.series_cells) + (extra_alerts or [])
    alarm = any(a["level"] == "ALARM" for a in alerts)
    fp = fingerprint.build_fingerprint(meta, features, info, soh, rul, soh_conf, alerts)

    missing_evidence = sum(1 for k in ("ir_cell_mohm", "thermal_response", "capacity_est_norm", "cell_imbalance_mv")
                           if features.get(k) is None or (isinstance(features.get(k), float) and math.isnan(features.get(k))))
    router = suitability.rank(fp["metrics"], missing_evidence,
                             low_confidence=soh_conf["value"] < confidence.CONFIDENCE_BANDS["moderate"])
    overall = confidence.overall_confidence(soh_conf["value"], rul.get("confidence", 50), router["decision_margin"],
                                            router["unverified_top"],
                                            router["ranking"][1]["score"] if len(router["ranking"]) > 1 else 0.0)
    if alarm:
        router["decision"] = {"id": "safety_hold", "name": "Safety Hold — Inspect Battery", "score": None, "kind": "safety"}

    contribs, base = pred.shap(X, variant)
    xai = {"soh": explain.shap_explanation(contribs, base, features),
           "applications": explain.application_explanation(router)}
    sources = adaptive_testing.diagnose(features, soh, ood, rul, router)
    rec = adaptive_testing.recommend(sources, overall["value"], alarm)

    card = pred.card
    measurements = {k: info.get(k) for k in ("ah_discharged", "energy_wh", "i_mean", "i_max", "t_max", "t_start",
                                             "ir_pack_mohm", "ir_source", "n_samples", "rest_after_s",
                                             "charge_duration_s", "coulombic_efficiency")}
    result = {
        "battery_id": battery_id, "source": source, "data_label": SOURCE_LABELS.get(source, source),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "meta": {"series_cells": meta.series_cells, "nominal_capacity_ah": meta.nominal_capacity_ah},
        "model": {"name": card["model_name"] + (" (spot-measurement variant)" if variant == "spot" else ""),
                  "version": card["version"], "status": card["status"],
                  "data_source": card["data_source"]},
        "validation": validation,
        "safety": {"status": "ALARM" if alarm else ("WARNING" if alerts else "OK"), "alerts": alerts,
                   "disclaimer": safety.DISCLAIMER},
        "measurements": measurements,
        "features": {k: features.get(k) for k in MODEL_FEATURES},
        "missing_features": [k for k in MODEL_FEATURES if features.get(k) is None or
                             (isinstance(features.get(k), float) and math.isnan(features.get(k)))],
        "soh": soh, "rul": rul, "fingerprint": fp, "router": router, "explanation": xai,
        "confidence": overall, "adaptive": {"uncertainty_sources": sources, **rec},
        "evidence": evidence or [], "timeseries": decimate(timeseries) if timeseries is not None else [],
    }
    result = clean_json(result)
    # circular economy: REUSE (solar / factory / household / street light) or RECYCLE (minerals back into new cells)
    result["circular"] = clean_json(circular.build(result))
    result["forensics"] = clean_json(forensics.diagnose(result))
    return result


def analyze_timeseries(raw: pd.DataFrame, meta: Meta, **kw) -> tuple[dict, dict, dict, pd.DataFrame]:
    """Returns (result, features, info, cleaned_df)."""
    df, rep = validate_and_clean(raw, meta.series_cells)
    ex = extract_features(df, meta)
    res = analyze_features(ex["features"], ex["info"], meta, timeseries=df, validation=rep.to_dict(), **kw)
    return res, ex["features"], ex["info"], df


def manual_features(inp: dict, meta: Meta) -> tuple[dict, dict]:
    """Manual mode: single measured values → the features they directly determine.
    Everything not supplied stays missing, which the model sees as missing evidence."""
    n, cap = meta.series_cells, meta.nominal_capacity_ah
    f = {k: np.nan for k in MODEL_FEATURES}
    info = {}
    if inp.get("measured_voltage"):
        f["v_cell_mean"] = inp["measured_voltage"] / n
        info["v_cell_min_all"] = info["v_cell_max_all"] = f["v_cell_mean"]
    if inp.get("current"):
        f["c_rate"] = abs(inp["current"]) / cap
    if inp.get("temperature") is not None:
        f["t_mean"] = inp["temperature"]
        info["t_max"] = inp["temperature"] + (inp.get("temperature_rise") or 0)
    if inp.get("temperature_rise") is not None:
        f["t_rise"] = inp["temperature_rise"]
    if inp.get("internal_resistance_mohm"):
        f["ir_cell_mohm"] = inp["internal_resistance_mohm"] / n
        info["ir_source"] = "reported"
        info["ir_pack_mohm"] = inp["internal_resistance_mohm"]
    if inp.get("capacity_ah"):
        # measured full-discharge capacity → equivalent to a full SOC window
        f["capacity_est_norm"] = inp["capacity_ah"] / cap
        f["ah_norm"] = inp["capacity_ah"] / cap
        f["soc_window"] = 1.0
    if inp.get("cycle_count") is not None:
        f["cycle"] = float(inp["cycle_count"])
    return f, info
