"""Physics-inspired Li-ion module simulator (SIMULATED / DEMO DATA ONLY).

This is NOT a validated electrochemical model. It is an equivalent-circuit
(OCV + R0 + one RC branch) model with a lumped thermal node and an empirical
ageing law, used to:
  * generate a labelled demo training dataset when no real dataset is loaded,
  * drive the live-stream simulator in the same JSON format the ESP32 sends,
  * execute "requested diagnostic tests" in demo mode.

Every record it produces is tagged source="SIMULATED".
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd


def ocv_cell(soc: np.ndarray | float) -> np.ndarray | float:
    """Open-circuit voltage of a generic NMC/graphite cell vs SOC (0..1)."""
    s = np.clip(soc, 0.0, 1.0)
    return 3.45 + 0.60 * s + 0.15 * s ** 2 - 0.25 * np.exp(-25.0 * s)


_SOC_GRID = np.linspace(0.0, 1.0, 2001)
_OCV_GRID = ocv_cell(_SOC_GRID)


def soc_from_ocv(v_cell: float) -> float:
    """Inverse OCV lookup (fresh-cell curve)."""
    return float(np.interp(v_cell, _OCV_GRID, _SOC_GRID))


@dataclass
class BatteryParams:
    battery_id: str
    series_cells: int = 3
    nominal_capacity_ah: float = 2.5
    # ageing law: SOH = 1 - a*(n/1000)^b - knee term
    fade_a: float = 0.15
    fade_b: float = 0.7
    knee_cycle: float = 2200.0
    knee_k: float = 0.08
    # resistance
    r0_cell: float = 0.014          # ohm per cell when new
    r_growth: float = 1.6            # relative growth per unit capacity loss/0.2
    r_extra: float = 1.0             # multiplicative anomaly (high-resistance batteries)
    rc_ratio: float = 0.6            # polarisation resistance / R0
    tau_s: float = 40.0              # RC time constant
    # thermal
    c_th: float = 140.0              # J/K for the module
    h_th: float = 0.25               # W/K to ambient
    extra_heat_w: float = 0.0        # parasitic heat (thermally stressed cells)
    # imbalance
    imbalance_base: float = 0.005
    imbalance_growth: float = 0.06
    cycle: int = 0
    seed: int = 0
    archetype: str = "normal"

    def soh(self, cycle: Optional[float] = None) -> float:
        n = self.cycle if cycle is None else cycle
        loss = self.fade_a * (max(n, 0) / 1000.0) ** self.fade_b
        if n > self.knee_cycle:
            loss += self.knee_k * ((n - self.knee_cycle) / 1000.0) ** 2 * 4
        return float(np.clip(1.0 - loss, 0.30, 1.0))

    def r_cell(self, cycle: Optional[float] = None) -> float:
        loss = 1.0 - self.soh(cycle)
        return self.r0_cell * (1.0 + self.r_growth * loss / 0.2) * self.r_extra

    def to_dict(self):
        return asdict(self)


@dataclass
class TestConfig:
    """Describes one diagnostic test the rig can perform."""
    kind: str = "standard_discharge"   # standard_discharge | pulse | full_discharge | thermal_observation | extended_cycle
    current_a: float = 1.25
    soc_start: float = 1.0
    soc_end: float = 0.0
    include_pulse: bool = True
    pulse_current_a: float = 5.0
    pulse_s: float = 20.0
    rest_start_s: float = 60.0
    rest_end_s: float = 180.0
    dt_s: float = 10.0
    ambient_c: float = 25.0
    has_temp_sensor: bool = True
    has_cell_voltages: bool = True
    include_charge: bool = False


class BatterySimulator:
    """Generates time series exactly in the column format the ESP32 rig produces."""

    def __init__(self, params: BatteryParams):
        self.p = params
        self.rng = np.random.default_rng(params.seed)

    # ------------------------------------------------------------------
    def run_test(self, cfg: TestConfig, cycle: Optional[int] = None) -> pd.DataFrame:
        p, rng = self.p, self.rng
        n_cyc = p.cycle if cycle is None else cycle
        soh = p.soh(n_cyc)
        n = p.series_cells
        loss = 1 - soh
        spread = p.imbalance_base + p.imbalance_growth * loss
        cap = p.nominal_capacity_ah * soh * (1 + rng.normal(0, spread, n))
        r_cell = p.r_cell(n_cyc) * (1 + rng.normal(0, 0.05 + spread, n)).clip(0.7, None)
        r_pol = r_cell * p.rc_ratio * (1 + 1.5 * loss)
        soc = np.clip(cfg.soc_start + rng.normal(0, 0.01, n), 0.02, 1.0)
        vp = np.zeros(n)
        temp = cfg.ambient_c + rng.normal(0, 0.3)
        q_ah = 0.0
        t = 0.0
        rows = []

        def step(i_a: float, dt: float):
            nonlocal soc, vp, temp, q_ah, t
            soc = soc - i_a * dt / 3600.0 / cap
            vp = vp + (i_a * r_pol - vp) * (1 - np.exp(-dt / p.tau_s))
            heat = (i_a ** 2) * r_cell.sum() + (i_a ** 2) * r_pol.sum() * 0.5 + p.extra_heat_w * (1 + 4 * loss) * (abs(i_a) > 0)
            temp = temp + dt * (heat - p.h_th * (temp - cfg.ambient_c)) / p.c_th
            q_ah += i_a * dt / 3600.0
            t += dt

        def record(i_a: float):
            v_cells = ocv_cell(soc) - i_a * r_cell - vp
            v_cells = v_cells + rng.normal(0, 0.002, n)
            row = {
                "timestamp": round(t, 2),
                "voltage": float(v_cells.sum() + rng.normal(0, 0.005)),
                "current": float(i_a + rng.normal(0, 0.01)) if i_a != 0 else float(rng.normal(0, 0.003)),
                "temperature": float(temp + rng.normal(0, 0.1)) if cfg.has_temp_sensor else np.nan,
                "capacity": round(q_ah, 5),
                "cycle": int(n_cyc),
                "internal_resistance": np.nan,
                "cell_v_min": float(v_cells.min()) if cfg.has_cell_voltages else np.nan,
                "cell_v_max": float(v_cells.max()) if cfg.has_cell_voltages else np.nan,
            }
            rows.append(row)
            return v_cells

        dt = cfg.dt_s
        # optional charge phase (for coulombic/energy efficiency)
        if cfg.include_charge:
            ic = -cfg.current_a
            while soc.max() < cfg.soc_start - 1e-3 and t < 6 * 3600:
                v = record(ic)
                if v.max() > 4.2:
                    break
                step(ic, dt)
        # rest
        for _ in range(int(cfg.rest_start_s / 2)):
            record(0.0)
            step(0.0, 2.0)
        # pulse (sampled finely so the step response is visible)
        if cfg.include_pulse:
            for _ in range(int(cfg.pulse_s / 1.0)):
                step(cfg.pulse_current_a, 1.0)
                record(cfg.pulse_current_a)
            for _ in range(15):
                step(0.0, 2.0)
                record(0.0)
        # constant-current discharge
        i = cfg.current_a
        max_t = t + 8 * 3600
        while t < max_t:
            step(i, dt)
            v = record(i)
            if v.min() <= 3.0 or soc.min() <= cfg.soc_end:
                break
        # end rest / recovery
        for _ in range(int(cfg.rest_end_s / 5)):
            step(0.0, 5.0)
            record(0.0)

        df = pd.DataFrame(rows)
        return df

    # ------------------------------------------------------------------
    def history(self, cycles: list[int], cfg_factory) -> list[tuple[int, pd.DataFrame]]:
        out = []
        for c in cycles:
            out.append((c, self.run_test(cfg_factory(c), cycle=c)))
        return out


# ----------------------------------------------------------------------
# Random population for the demo training dataset
# ----------------------------------------------------------------------
ARCHETYPES = ["normal", "normal", "normal", "fast_fade", "high_resistance", "thermal", "early_knee"]


def random_battery(idx: int, rng: np.random.Generator) -> BatteryParams:
    arch = ARCHETYPES[idx % len(ARCHETYPES)]
    p = BatteryParams(
        battery_id=f"SIM-{idx:03d}",
        nominal_capacity_ah=float(rng.choice([2.0, 2.5, 3.0])),
        fade_a=float(rng.uniform(0.10, 0.20)),
        fade_b=float(rng.uniform(0.55, 0.85)),
        knee_cycle=float(rng.uniform(1800, 3200)),
        knee_k=float(rng.uniform(0.04, 0.12)),
        r0_cell=float(rng.uniform(0.011, 0.018)),
        r_growth=float(rng.uniform(1.0, 2.2)),
        c_th=float(rng.uniform(120, 170)),
        h_th=float(rng.uniform(0.2, 0.32)),
        tau_s=float(rng.uniform(25, 60)),
        seed=int(rng.integers(0, 1_000_000)),
        archetype=arch,
    )
    if arch == "fast_fade":
        p.fade_a *= 1.5
    elif arch == "high_resistance":
        p.r_extra = float(rng.uniform(1.8, 2.8))
    elif arch == "thermal":
        p.h_th = float(rng.uniform(0.08, 0.14))
        p.extra_heat_w = float(rng.uniform(0.3, 0.9))
    elif arch == "early_knee":
        p.knee_cycle = float(rng.uniform(900, 1500))
    return p


def random_test_config(rng: np.random.Generator, nominal_capacity: float) -> TestConfig:
    partial = rng.random() < 0.55
    soc_start = float(rng.uniform(0.55, 1.0)) if partial else 1.0
    soc_end = float(soc_start - rng.uniform(0.08, soc_start - 0.05)) if partial else 0.0
    c_rate = float(rng.uniform(0.3, 1.0))
    return TestConfig(
        kind="standard_discharge",
        current_a=round(c_rate * nominal_capacity, 3),
        soc_start=soc_start,
        soc_end=soc_end,
        include_pulse=bool(rng.random() < 0.7),
        pulse_current_a=round(2.0 * nominal_capacity, 3),
        dt_s=float(rng.choice([5.0, 10.0, 15.0])),
        ambient_c=float(rng.uniform(20, 32)),
        has_temp_sensor=bool(rng.random() < 0.9),
        has_cell_voltages=bool(rng.random() < 0.5),
        rest_end_s=float(rng.choice([0.0, 60.0, 180.0, 300.0], p=[0.2, 0.2, 0.4, 0.2])),
    )
