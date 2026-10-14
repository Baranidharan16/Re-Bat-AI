"""Smoke + integrity tests.  Run:  cd backend && python -m pytest -q"""
import sqlite3

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.ml.data_ingestion import DataValidationError, validate_and_clean
from app.ml.feature_engineering import Meta, extract_features
from app.simulation.battery_sim import BatteryParams, BatterySimulator, TestConfig


def test_features_from_simulated_test():
    p = BatteryParams("T-1", cycle=800, seed=1)
    df, rep = validate_and_clean(BatterySimulator(p).run_test(TestConfig()), 3)
    f = extract_features(df, Meta(3, 2.5))["features"]
    assert 10 < f["ir_cell_mohm"] < 80            # pulse-derived resistance
    assert abs(f["capacity_est_norm"] - p.soh()) < 0.08
    assert f["dv_dq"] < 0


def test_validation_rejects_missing_current():
    with pytest.raises(DataValidationError):
        validate_and_clean(pd.DataFrame({"timestamp": range(20), "voltage": [11.0] * 20}), 3)


def test_model_split_has_no_battery_leakage():
    from app.ml.predict import get_predictor
    card = get_predictor().card
    assert card["split"]["method"].startswith("battery-level")
    assert card["metrics_test"]["xgboost"]["MAE"] < card["metrics_test"]["baseline_ridge"]["MAE"]


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_demo_analysis_shape(client):
    r = client.get("/api/v1/demo/batteries/RB-C03/analysis").json()
    assert r["data_label"].startswith("DEMO")
    assert r["router"]["ranking"][0]["score"] >= r["router"]["ranking"][-1]["score"]
    ups = next(a for a in r["router"]["ranking"] if a["id"] == "ups_high_power")
    assert ups["score"] < 40                         # high-resistance battery is not routed to UPS


def test_low_confidence_battery_gets_a_test_and_improves(client):
    client.post("/api/v1/demo/batteries/RB-E05/reset")
    before = client.get("/api/v1/demo/batteries/RB-E05/analysis").json()
    assert before["adaptive"]["required"]
    out = client.post("/api/v1/tests/request", json={"battery_id": "RB-E05", "test_id": "full_discharge", "context": "demo"}).json()
    assert out["after"]["soh"]["hi"] - out["after"]["soh"]["lo"] < before["soh"]["hi"] - before["soh"]["lo"]


def test_hardware_ingest_forecast_and_ledger(client):
    p = BatteryParams("RB-T9", cycle=600, seed=9)
    df = BatterySimulator(p).run_test(TestConfig(soc_start=1.0, soc_end=0.6, dt_s=10))
    rows = [{"battery_id": "RB-T9", "t_s": r.timestamp, "voltage": r.voltage, "current": r.current,
             "temperature": r.temperature, "capacity": r.capacity, "cycle_count": int(r.cycle),
             "phase": "end" if i == len(df) - 1 else "run"} for i, r in enumerate(df.itertuples())]
    for i in range(0, len(rows), 100):
        assert client.post("/api/v1/hardware/ingest", json={"readings": rows[i:i + 100]}).status_code == 200
    f = client.get("/api/v1/batteries/RB-T9/forecasts").json()
    assert f and f[0]["is_final"] == 1
    assert client.get("/api/v1/ledger/verify").json()["valid"]
