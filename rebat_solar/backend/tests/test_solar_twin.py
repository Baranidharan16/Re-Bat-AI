import math

from fastapi.testclient import TestClient

from app.services.solar_sim import (PRESETS, SolarBatterySystem, SystemConfig, compare_lifetime,
                                    project_lifetime)


def run_days(cfg, days=3, seed=1):
    s = SolarBatterySystem(cfg, seed=seed)
    for _ in range(days * 24 * 6):
        s.advance(600)
        snap = s.snapshot()
        b = snap["battery"]
        assert 0.0 <= b["soc"] <= 1.0
        assert math.isfinite(b["voltage_v"]) and b["voltage_v"] > 0
        assert snap["power"]["pv_w"] <= snap["power"]["pv_available_w"] + 1e-6
        assert snap["power"]["load_w"] <= snap["power"]["load_demand_w"] + 1e-6
    return s


def test_energy_balance_closes():
    s = run_days(SystemConfig(), 3)
    t = s.totals
    cap = s.cfg.pack.nominal_capacity_ah
    # PV harvested (after MPPT) = load from PV + charge;  load = PV-to-load + discharge
    eta = s.cfg.ctrl.mppt_eff
    pv_to_load = t["load_wh"] - t["discharge_wh"]
    assert abs(t["pv_wh"] * eta - (pv_to_load + t["charge_wh"])) < 0.5
    assert t["unmet_wh"] >= -1e-6
    assert s.soh < s.soh0  # it ages


def test_cv_limit_respected():
    cfg = SystemConfig()
    cfg.site.weather = "clear"
    s = run_days(cfg, 2)
    v_cell_max = max(d["soc_max"] for d in s.day_summaries)
    assert v_cell_max <= s.soc_cv + 1e-3


def test_lvd_sheds_load_when_undersized():
    cfg = SystemConfig.from_dict({"panel": {"rated_w": 5}, "load": {"led_w": 40},
                                  "site": {"weather": "monsoon"}, "pack": {"initial_soc": 0.3}})
    s = run_days(cfg, 3)
    assert s.totals["unmet_wh"] > 0
    assert min(d["soc_min"] for d in s.day_summaries) >= cfg.ctrl.soc_lvd - 0.02
    assert any("Low-voltage disconnect" in e["msg"] for e in s.events)


def test_hot_box_derates_charging():
    cfg = SystemConfig.from_dict({"site": {"enclosure_solar_gain_c": 25, "weather": "clear"}})
    s = run_days(cfg, 2)
    assert any(d["t_batt_max"] > cfg.ctrl.t_derate_start for d in s.day_summaries)


def test_lifetime_monotonic_and_presets():
    for key, p in PRESETS.items():
        r = project_lifetime(SystemConfig.from_dict(p["config"]), max_years=4)
        sohs = [w["soh"] for w in r["weekly"]]
        assert all(a >= b - 1e-9 for a, b in zip(sohs, sohs[1:])), key
    c = compare_lifetime(SystemConfig(), max_years=8)
    assert c["gentle"]["v_cv_cell"] < c["standard"]["v_cv_cell"]
    assert c["shaded_gentle"]["years_to_eol"] >= c["standard"]["years_to_eol"]


def test_api_session_and_lifetime():
    from solar_demo_server import app
    with TestClient(app) as client:
        assert "ev_module_streetlight" in client.get("/solar/presets").json()
        r = client.post("/solar/sessions", json={"preset": "ev_module_streetlight",
                                                 "config": {"pack": {"measured_capacity_ah": 20}}})
        assert r.status_code == 200
        sid = r.json()["session_id"]
        assert abs(r.json()["config"]["pack"]["measured_capacity_ah"] - 20) < 1e-9
        assert client.post(f"/solar/sessions/{sid}/control",
                           json={"action": "skip", "value": 7200}).status_code == 200
        tel = client.get(f"/solar/sessions/{sid}/telemetry").json()
        for k in ("timestamp", "voltage", "current", "temperature", "capacity", "cycle",
                  "internal_resistance", "cell_v_min", "cell_v_max"):
            assert k in tel
        bad = client.post("/solar/sessions", json={"config": {"pack": {"chemistry": "XYZ"}}})
        assert bad.status_code == 422
        lt = client.post("/solar/lifetime", json={"preset": "rig_cell_demo", "max_years": 2})
        assert lt.status_code == 200 and "gentle" in lt.json()
        client.post(f"/solar/sessions/{sid}/control", json={"action": "stop"})
