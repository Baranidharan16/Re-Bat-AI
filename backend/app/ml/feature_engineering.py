"""Phase 3 — Feature engineering.

Turns one canonical test time series into a flat feature vector. Every feature is
normalised per cell / per nominal Ah so the same model works for a 1-cell lab test,
the 3S ESP32 rig, or a larger module.

Missing sensors produce NaN (XGBoost handles them natively) and are reported, which
the confidence + adaptive-testing layers use to decide what to measure next.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.simulation.battery_sim import soc_from_ocv

# Features consumed by the SOH model (order matters for the saved model).
MODEL_FEATURES = [
    "v_cell_mean", "v_cell_min", "v_cell_max", "v_cell_std",
    "c_rate", "t_mean", "t_rise", "t_rise_rate", "thermal_response",
    "dv_dq", "dv_dt", "discharge_duration_s", "ah_norm", "energy_norm",
    "ir_cell_mohm", "v_recovery_cell_mv",
    "soc_start_est", "soc_end_est", "soc_window", "capacity_est_norm",
    "cycle", "cell_imbalance_mv",
]

# Scalar features a user can type in (MANUAL mode) — used by the spot-measurement model
SPOT_FEATURES = ["c_rate", "t_mean", "t_rise", "ir_cell_mohm", "capacity_est_norm", "cycle"]

FEATURE_LABELS = {
    "v_cell_mean": "Mean cell voltage", "v_cell_min": "Min cell voltage", "v_cell_max": "Max cell voltage",
    "v_cell_std": "Voltage spread (std)", "c_rate": "Test C-rate", "t_mean": "Mean temperature",
    "t_rise": "Temperature rise", "t_rise_rate": "Temperature rise rate", "thermal_response": "Thermal response",
    "dv_dq": "Voltage slope dV/dQ", "dv_dt": "Voltage slope dV/dt", "discharge_duration_s": "Discharge duration",
    "ah_norm": "Discharged charge (norm.)", "energy_norm": "Discharged energy (norm.)",
    "ir_cell_mohm": "Internal resistance", "v_recovery_cell_mv": "Voltage recovery after load",
    "soc_start_est": "Start SOC (OCV)", "soc_end_est": "End SOC (OCV)", "soc_window": "Tested SOC window",
    "capacity_est_norm": "OCV-window capacity estimate", "cycle": "Cycle count",
    "cell_imbalance_mv": "Cell imbalance",
}

# features whose absence the adaptive-testing engine can fix with a specific test
FEATURE_SOURCES = {
    "ir_cell_mohm": "pulse", "v_recovery_cell_mv": "rest",
    "t_rise": "temperature", "t_rise_rate": "temperature", "thermal_response": "temperature", "t_mean": "temperature",
    "capacity_est_norm": "window", "soc_start_est": "rest", "soc_end_est": "rest",
    "cell_imbalance_mv": "cell_voltages", "cycle": "metadata",
}


@dataclass
class Meta:
    series_cells: int = 3
    nominal_capacity_ah: float = 2.5


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous True runs as (start, end_inclusive)."""
    runs, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        elif not m and start is not None:
            runs.append((start, i - 1)); start = None
    if start is not None:
        runs.append((start, len(mask) - 1))
    return runs


def extract_features(df: pd.DataFrame, meta: Meta) -> dict:
    n = meta.series_cells
    cap_nom = meta.nominal_capacity_ah
    t = df["timestamp"].to_numpy(float)
    v = df["voltage"].to_numpy(float)
    i = df["current"].to_numpy(float)
    T = df["temperature"].to_numpy(float)
    f: dict = {k: np.nan for k in MODEL_FEATURES}
    info: dict = {}

    loaded = i > 0.05
    runs = _runs(loaded)
    if not runs:
        f["cycle"] = float(df["cycle"].dropna().iloc[0]) if df["cycle"].notna().any() else np.nan
        return {"features": f, "info": {"warning": "no discharge segment"}}
    lengths = [t[e] - t[s] for s, e in runs]
    main_idx = int(np.argmax(lengths))
    ms, me = runs[main_idx]

    # ---------------- pulse / internal resistance -----------------------------
    ir_ohm = np.nan
    pulse_dv = np.nan
    for k, (s, e) in enumerate(runs):
        dur = t[e] - t[s]
        if k != main_idx and dur <= 90 and s > 0 and not loaded[s - 1]:
            dI = i[s] - i[s - 1]
            if dI > 0.2:
                pulse_dv = v[s - 1] - v[s]
                ir_ohm = pulse_dv / dI
                break
    if np.isnan(ir_ohm) and ms > 0 and not loaded[ms - 1]:
        dI = i[ms] - i[ms - 1]
        if dI > 0.2 and (t[ms] - t[ms - 1]) <= 2.5:
            ir_ohm = (v[ms - 1] - v[ms]) / dI   # step into the main discharge
    if np.isnan(ir_ohm) and df["internal_resistance"].notna().any():
        ir_ohm = float(df["internal_resistance"].median())   # reported by hardware/BMS
        info["ir_source"] = "reported"
    elif not np.isnan(ir_ohm):
        info["ir_source"] = "pulse"
    f["ir_cell_mohm"] = ir_ohm / n * 1000 if not np.isnan(ir_ohm) else np.nan
    info["ir_pack_mohm"] = ir_ohm * 1000 if not np.isnan(ir_ohm) else np.nan

    # ---------------- main discharge statistics --------------------------------
    sl = slice(ms, me + 1)
    vc = v[sl] / n
    tm = t[sl]
    im = i[sl]
    f["v_cell_mean"] = float(np.mean(vc)); f["v_cell_min"] = float(np.min(vc))
    f["v_cell_max"] = float(np.max(vc)); f["v_cell_std"] = float(np.std(vc))
    i_mean = float(np.mean(im))
    f["c_rate"] = i_mean / cap_nom
    dur = float(tm[-1] - tm[0]) if len(tm) > 1 else 0.0
    f["discharge_duration_s"] = dur
    dt = np.diff(t, prepend=t[0])
    ah_main = float(np.sum(np.clip(im, 0, None) * dt[sl]) / 3600.0)
    wh_main = float(np.sum(np.clip(im, 0, None) * v[sl] * dt[sl]) / 3600.0)
    f["ah_norm"] = ah_main / cap_nom
    f["energy_norm"] = wh_main / (cap_nom * 3.6 * n)
    info.update(ah_discharged=ah_main, energy_wh=wh_main, i_mean=i_mean, i_max=float(np.max(i)))

    # voltage slopes in the middle 60 % of the discharge
    if len(vc) >= 8:
        q = np.cumsum(np.clip(im, 0, None) * dt[sl]) / 3600.0 / cap_nom
        a, b = int(len(vc) * 0.2), int(len(vc) * 0.8)
        if b - a >= 4 and q[b] - q[a] > 1e-4:
            f["dv_dq"] = float(np.polyfit(q[a:b], vc[a:b], 1)[0])
            f["dv_dt"] = float(np.polyfit(tm[a:b] / 3600.0, vc[a:b], 1)[0])

    # ---------------- OCV based SOC window -----------------------------------
    pre = np.where(~loaded[:ms])[0]
    if len(pre) and (t[ms] - t[pre[-1]]) < 30 and (t[pre[-1]] - t[pre[0]]) >= 20:
        # use the last rest sample before main discharge (pulse rest counts)
        f["soc_start_est"] = soc_from_ocv(v[pre[-1]] / n)
    post = np.arange(me + 1, len(v))
    post = post[~loaded[post]] if len(post) else post
    if len(post) >= 3 and (t[post[-1]] - t[post[0]]) >= 30:
        f["soc_end_est"] = soc_from_ocv(v[post[-1]] / n)
        f["v_recovery_cell_mv"] = (v[post[-1]] - v[me]) / n * 1000
        info["rest_after_s"] = float(t[post[-1]] - t[post[0]])
    if not np.isnan(f["soc_start_est"]) and not np.isnan(f["soc_end_est"]):
        w = f["soc_start_est"] - f["soc_end_est"]
        f["soc_window"] = w
        # pulse charge removed between start-OCV sample and main discharge
        if w > 0.15:
            ah_total = float(np.sum(np.clip(i[pre[-1]:me + 1], 0, None) * dt[pre[-1]:me + 1]) / 3600.0)
            f["capacity_est_norm"] = ah_total / w / cap_nom

    # ---------------- thermal ----------------------------------------------------
    if np.isfinite(T).sum() >= 5:
        Tm = T[sl]
        T0 = np.nanmedian(T[: max(ms, 1)]) if ms > 0 and np.isfinite(T[:ms]).any() else Tm[np.isfinite(Tm)][0]
        f["t_mean"] = float(np.nanmean(Tm))
        tmax = float(np.nanmax(T))
        f["t_rise"] = tmax - T0
        f["t_rise_rate"] = f["t_rise"] / max(dur / 60.0, 1.0)
        c2h = float(np.sum((np.clip(im, 0, None) / cap_nom) ** 2 * dt[sl]) / 3600.0)
        f["thermal_response"] = f["t_rise"] / c2h if c2h > 1e-3 else np.nan
        info.update(t_max=tmax, t_start=float(T0))
        # dT/dt peak for safety (degC/min) — slope over 60 s windows on a uniform grid
        ok = np.isfinite(T)
        if ok.sum() > 5 and t[ok][-1] - t[ok][0] > 120:
            grid = np.arange(t[ok][0], t[ok][-1], 10.0)
            Tg = pd.Series(np.interp(grid, t[ok], T[ok])).rolling(3, min_periods=1, center=True).mean().to_numpy()
            dTdt = (Tg[6:] - Tg[:-6]) / 60.0 * 60.0
            info["dTdt_max"] = float(np.max(dTdt)) if len(dTdt) else np.nan

    # ---------------- imbalance / cycle / charge --------------------------------
    if df["cell_v_max"].notna().any() and df["cell_v_min"].notna().any():
        spread = (df["cell_v_max"] - df["cell_v_min"]).to_numpy(float)
        f["cell_imbalance_mv"] = float(np.nanmedian(spread[sl])) * 1000   # mid-discharge spread
    if df["cycle"].notna().any():
        f["cycle"] = float(df["cycle"].dropna().iloc[-1])
    chg = i < -0.05
    if chg.any():
        info["charge_duration_s"] = float(np.sum(dt[chg]))
        ah_in = float(np.sum(-i[chg] * dt[chg]) / 3600.0)
        info["coulombic_efficiency"] = ah_main / ah_in if ah_in > 0 else np.nan

    info["n_samples"] = int(len(df))
    info["v_cell_min_all"] = float(np.min(v) / n)
    info["v_cell_max_all"] = float(np.max(v) / n)
    info["missing_features"] = [k for k in MODEL_FEATURES if not np.isfinite(f[k])]
    return {"features": f, "info": info}


def features_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)[MODEL_FEATURES].astype(float)
