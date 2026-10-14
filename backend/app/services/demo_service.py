"""Demo-mode orchestration: builds batteries A–E, runs them through the real
pipeline, and executes AI-requested diagnostic tests on the simulator.

Demo results are kept in memory only (not written to the ledger): only real-time
stream data is persisted, as required.
"""
from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.ml.data_ingestion import validate_and_clean
from app.ml.feature_engineering import MODEL_FEATURES, Meta, extract_features
from app.ml.predict import get_predictor
from app.services import adaptive_testing, pipeline
from app.simulation.battery_sim import BatterySimulator
from app.simulation.demo_profiles import (PROFILES, DemoState, build_params, history_tests, initial_test,
                                          sim_config_for_test)

_lock = threading.Lock()
_states: dict[str, DemoState] = {}


def _history_points(p, cycles):
    pred = get_predictor()
    pts = []
    for c, f in history_tests(p, cycles):
        out = pred.predict_frame(pd.DataFrame([{k: f.get(k, np.nan) for k in MODEL_FEATURES}]))
        pts.append({"cycle": c, "soh": float(out["soh"][0]), "lo": float(out["lo"][0]), "hi": float(out["hi"][0])})
    return pts


def _init(bid: str) -> DemoState:
    prof = PROFILES[bid]
    p = build_params(bid)
    meta = Meta(p.series_cells, p.nominal_capacity_ah)
    raw = initial_test(p, prof)
    df, rep = validate_and_clean(raw, meta.series_cells)
    ex = extract_features(df, meta)
    st = DemoState(battery_id=bid, profile=prof, params=p, meta=meta,
                   sensors={"temp": prof["test"].get("has_temp_sensor", True),
                            "cells": prof["test"].get("has_cell_voltages", True),
                            "ambient_c": prof["test"].get("ambient_c", 25)},
                   features=ex["features"], info=ex["info"], timeseries=df,
                   history=_history_points(p, prof["history"]))
    st.evidence.append({"step": 0, "test": "initial_test", "name": "Initial screening test",
                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "rows": int(len(df)), "validation": rep.to_dict()})
    st.info["validation"] = rep.to_dict()
    return st


def get_state(bid: str) -> DemoState:
    if bid not in PROFILES:
        raise KeyError(bid)
    with _lock:
        if bid not in _states:
            _states[bid] = _init(bid)
        return _states[bid]


def reset(bid: str):
    with _lock:
        _states.pop(bid, None)
        for k in [k for k in _cache if k.startswith(bid + ":")]:
            _cache.pop(k)
    return get_state(bid)


_cache: dict[str, dict] = {}


def analyze(bid: str) -> dict:
    """Pipeline output for the battery's current evidence (memoised until a test changes it)."""
    st = get_state(bid)
    key = f"{bid}:{st.tests_run}"
    if key in _cache:
        return _cache[key]
    res = pipeline.analyze_features(st.features, st.info, st.meta, battery_id=bid, source="DEMO",
                                    history=st.history, timeseries=st.timeseries,
                                    validation=st.info.get("validation"), evidence=st.evidence)
    res["demo"] = {"label": st.profile["label"], "title": st.profile["title"], "story": st.profile["story"],
                   "tests_run": st.tests_run,
                   "note": "Simulated battery. Ground-truth physics parameters stay hidden from the model."}
    _cache[key] = res
    return res


def list_batteries() -> list[dict]:
    return [{"battery_id": k, "label": v["label"], "title": v["title"], "story": v["story"]} for k, v in PROFILES.items()]


def run_requested_test(bid: str, test_id: str) -> dict:
    """AI → TEST REQUEST → (simulated) HARDWARE → DATA → AI."""
    st = get_state(bid)
    test = next((t for t in adaptive_testing.catalog()["tests"] if t["id"] == test_id), None)
    if test is None:
        raise ValueError(f"Unknown test '{test_id}'")
    before = analyze(bid)
    if before["safety"]["status"] == "ALARM":
        raise PermissionError("Safety alarm active — inspect the battery before further electrical testing.")
    p = copy.deepcopy(st.params)
    p.seed = st.params.seed + 1000 + st.tests_run
    adv = test["sim"].get("advance_cycles", 0)
    if adv:
        st.params.cycle += adv
        p.cycle = st.params.cycle
    cfg = sim_config_for_test(test, p, st.sensors)
    raw = BatterySimulator(p).run_test(cfg)
    if st.profile.get("unknown_cycle"):
        raw["cycle"] = np.nan
    df, rep = validate_and_clean(raw, st.meta.series_cells)
    ex = extract_features(df, st.meta)
    merged, changed = adaptive_testing.merge_evidence(st.features, ex["features"], test_id)
    st.features = merged
    info = dict(st.info)
    for k, v in ex["info"].items():
        if v is not None and not (isinstance(v, float) and np.isnan(v)) and k != "missing_features":
            if k.startswith("t_") or k == "dTdt_max":
                if "t_rise" in changed or "thermal_response" in changed:
                    info[k] = v
            elif k in ("ir_pack_mohm", "ir_source"):
                if "ir_cell_mohm" in changed:
                    info[k] = v
            else:
                info[k] = v
    st.info = info
    if test_id in ("full_discharge", "extended_cycle", "thermal_observation"):
        st.timeseries = df
    if test_id == "thermal_observation":
        st.sensors["temp"] = True
    if test_id == "cell_balance_scan":
        st.sensors["cells"] = True
    st.tests_run += 1
    st.evidence.append({"step": st.tests_run, "test": test_id, "name": test["name"],
                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "rows": int(len(df)), "updated_features": changed,
                        "soh_before": before["soh"]["soh"], "confidence_before": before["confidence"]["value"],
                        "top_before": before["router"]["ranking"][0]["short"]})
    after = analyze(bid)
    st.evidence[-1].update(soh_after=after["soh"]["soh"], confidence_after=after["confidence"]["value"],
                           top_after=after["router"]["ranking"][0]["short"])
    after["evidence"] = st.evidence
    return {"before": {"soh": before["soh"], "confidence": before["confidence"],
                       "top": before["router"]["ranking"][0]["short"],
                       "recommended_test": (before["adaptive"]["recommended"] or {}).get("id")},
            "test": {"id": test_id, "name": test["name"], "rows": int(len(df)), "updated_features": changed,
                     "data_label": "SIMULATED HARDWARE EXECUTION"},
            "after": after}
