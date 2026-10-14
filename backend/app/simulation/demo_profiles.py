"""DEMO MODE — six simulated batteries (A–F) + their simulated maintenance history.

Only the *latent physics parameters* are defined here. Every number the UI shows
(SOH, RUL, fingerprint, ranking, confidence, recommended test) is produced by
running simulated test data through the real pipeline.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

import numpy as np

from app.ml.feature_engineering import Meta, extract_features
from app.simulation.battery_sim import BatteryParams, BatterySimulator, TestConfig

PROFILES = {
    "RB-A01": dict(label="Battery A", title="Healthy", story="Lightly used module, full diagnostic data.",
                   params=dict(fade_a=0.11, fade_b=0.70, cycle=450, r0_cell=0.013, h_th=0.28, seed=101),
                   test=dict(current_a=1.25, include_pulse=True, has_temp_sensor=True, has_cell_voltages=True, ambient_c=25),
                   history=[60, 150, 250, 350]),
    "RB-B02": dict(label="Battery B", title="Moderately degraded", story="Typical retired EV module, full diagnostic data.",
                   params=dict(fade_a=0.17, fade_b=0.70, cycle=1500, r0_cell=0.014, h_th=0.25, seed=202),
                   test=dict(current_a=1.25, include_pulse=True, has_temp_sensor=True, has_cell_voltages=True, ambient_c=26),
                   history=[300, 600, 900, 1200]),
    "RB-C03": dict(label="Battery C", title="High resistance", story="Similar SOH to B but resistance-dominant ageing.",
                   params=dict(fade_a=0.15, fade_b=0.70, cycle=1250, r0_cell=0.015, r_extra=2.6, h_th=0.25, seed=303),
                   test=dict(current_a=1.25, include_pulse=True, has_temp_sensor=True, has_cell_voltages=True, ambient_c=25),
                   history=[250, 500, 750, 1000]),
    "RB-D04": dict(label="Battery D", title="Thermally stressed", story="Similar SOH, but heats up abnormally under load.",
                   params=dict(fade_a=0.15, fade_b=0.70, cycle=1300, r0_cell=0.015, h_th=0.10, extra_heat_w=0.55, c_th=125, seed=404,
                               archetype="thermal"),
                   test=dict(current_a=2.0, include_pulse=True, has_temp_sensor=True, has_cell_voltages=True, ambient_c=30),
                   history=[300, 600, 900, 1150]),
    "RB-E05": dict(label="Battery E", title="Low confidence / ambiguous",
                   story="Unknown history, short partial test, no pulse, no temperature or cell-tap sensors.",
                   params=dict(fade_a=0.16, fade_b=0.70, cycle=1400, r0_cell=0.016, h_th=0.25, seed=505),
                   test=dict(current_a=1.25, soc_start=0.80, soc_end=0.64, include_pulse=False, has_temp_sensor=False,
                             has_cell_voltages=False, rest_end_s=0.0, ambient_c=25),
                   history=[], unknown_cycle=True),
    "RB-F06": dict(label="Battery F", title="End of life",
                   story="Heavily aged module: low capacity, high resistance. Too weak for reuse, so it goes to material recovery.",
                   params=dict(fade_a=0.22, fade_b=0.70, cycle=2600, r0_cell=0.018, r_extra=1.0, h_th=0.18, seed=606),
                   test=dict(current_a=0.75, include_pulse=True, has_temp_sensor=True, has_cell_voltages=True, ambient_c=27),
                   history=[600, 1200, 1800, 2300]),
}


@dataclass
class DemoState:
    battery_id: str
    profile: dict
    params: BatteryParams
    meta: Meta
    sensors: dict
    features: dict = field(default_factory=dict)
    info: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    timeseries: object = None
    tests_run: int = 0


def build_params(bid: str) -> BatteryParams:
    prof = PROFILES[bid]
    return BatteryParams(battery_id=bid, **prof["params"])


def initial_test(state_params: BatteryParams, prof: dict):
    sim = BatterySimulator(state_params)
    cfg = TestConfig(**{**dict(pulse_current_a=2 * state_params.nominal_capacity_ah), **prof["test"]})
    df = sim.run_test(cfg)
    if prof.get("unknown_cycle"):
        df["cycle"] = np.nan
    return df


def history_tests(p: BatteryParams, cycles: list[int]):
    """Earlier maintenance checks (simulated): full discharge with pulse at older cycles."""
    sim = BatterySimulator(copy.deepcopy(p))
    out = []
    for c in cycles:
        df = sim.run_test(TestConfig(current_a=0.5 * p.nominal_capacity_ah, include_pulse=True,
                                     pulse_current_a=2 * p.nominal_capacity_ah), cycle=c)
        out.append((c, extract_features(df, Meta(p.series_cells, p.nominal_capacity_ah))["features"]))
    return out


def sim_config_for_test(test: dict, p: BatteryParams, sensors: dict) -> TestConfig:
    s = test["sim"]
    soc_start = 0.92 if s.get("soc_start") == "keep" else float(s.get("soc_start", 1.0))
    soc_end = max(0.0, soc_start - s["window"]) if "window" in s else float(s.get("soc_end", 0.0))
    return TestConfig(
        kind=test["id"], current_a=s.get("c_rate", 0.5) * p.nominal_capacity_ah,
        soc_start=soc_start, soc_end=soc_end, include_pulse=s.get("include_pulse", False),
        pulse_current_a=2 * p.nominal_capacity_ah, rest_end_s=s.get("rest_end_s", 120),
        has_temp_sensor=sensors["temp"] or s.get("force_temp", False),
        has_cell_voltages=sensors["cells"] or s.get("force_cells", False),
        include_charge=s.get("include_charge", False), ambient_c=sensors.get("ambient_c", 25),
        dt_s=5.0)
