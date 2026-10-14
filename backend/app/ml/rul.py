"""Layer 3 — Remaining Useful Life (PROTOTYPE / EXPERIMENTAL).

Method (stated plainly so nobody mistakes it for a validated RUL model):
  SOH(n) = 100 - A * (n/1000)^B   (empirical power-law fade, Wang/Spotnitz style)

* >= 3 history points spanning >= 150 cycles: weighted fit to the battery's own
  SOH estimates; uncertainty by Monte-Carlo resampling each point within its
  prediction interval (300 refits).
* fewer points: population-conditioned prior — exponents B fitted on the
  training population, A solved so each curve passes through the current
  estimate; spread of the population gives the band.
RUL = cycles until SOH crosses the second-life end-of-life threshold.
Power laws do not capture knee-point acceleration, so the upper band is optimistic
for batteries near a knee. Validate against real ageing data before relying on it.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from app.config import MODEL_DIR, RUL_EOL_SOH

B_BOUNDS = (0.35, 1.6)
RUL_CAP = 6000  # beyond this a power-law extrapolation is not meaningful


def _curve(n, A, B):
    return 100.0 - A * np.power(np.maximum(n, 0) / 1000.0, B)


def _cross(A, B, eol):
    if A <= 0:
        return np.inf
    return 1000.0 * ((100.0 - eol) / A) ** (1.0 / B)


@lru_cache(maxsize=1)
def population_exponents() -> np.ndarray:
    path = MODEL_DIR / "population_curves.csv"
    if not path.exists():
        return np.array([0.6, 0.7, 0.8])
    pop = pd.read_csv(path)
    Bs = []
    for _, g in pop.groupby("battery_id"):
        g = g[g.cycle_true > 50]
        if len(g) < 5:
            continue
        try:
            (A, B), _ = curve_fit(_curve, g.cycle_true, g.soh_true, p0=(15, 0.7),
                                  bounds=([0.1, B_BOUNDS[0]], [200, B_BOUNDS[1]]), maxfev=4000)
            Bs.append(B)
        except Exception:
            continue
    return np.array(Bs) if Bs else np.array([0.6, 0.7, 0.8])


def estimate_rul(history: list[dict], current: dict, eol: float = RUL_EOL_SOH, seed: int = 0) -> dict:
    """history/current items: {cycle, soh, lo, hi}. cycle may be None if unknown."""
    rng = np.random.default_rng(seed)
    pts = [h for h in history if h.get("cycle") is not None and np.isfinite(h.get("cycle", np.nan))]
    cur_cycle = current.get("cycle")
    cycle_known = cur_cycle is not None and np.isfinite(cur_cycle)
    if cycle_known:
        pts = pts + [current]
    pts = sorted(pts, key=lambda p: p["cycle"])
    soh_now = float(current["soh"])

    if soh_now <= eol:
        return {"rul_cycles": 0, "rul_p10": 0, "rul_p90": 0, "method": "below_threshold", "eol_soh": eol,
                "degradation_rate_per_100": None, "trajectory": [], "history": _hist(pts), "cycle_known": cycle_known,
                "status": "PROTOTYPE", "confidence": 100.0}

    method = "population_prior"
    samples_A, samples_B = [], []
    if len(pts) >= 3 and (pts[-1]["cycle"] - pts[0]["cycle"]) >= 150:
        method = "battery_history_fit"
        c = np.array([p["cycle"] for p in pts], float)
        y = np.array([p["soh"] for p in pts], float)
        sig = np.array([max((p["hi"] - p["lo"]) / 3.29, 0.3) for p in pts], float)
        for _ in range(300):
            ys = y + rng.normal(0, sig)
            try:
                (A, B), _ = curve_fit(_curve, c, ys, p0=(15, 0.7), sigma=sig,
                                      bounds=([0.01, B_BOUNDS[0]], [300, B_BOUNDS[1]]), maxfev=3000)
                samples_A.append(A); samples_B.append(B)
            except Exception:
                continue
    if len(samples_A) < 50:
        method = "population_prior"
        samples_A, samples_B = [], []
        Bs = population_exponents()
        n_ref = cur_cycle if cycle_known and cur_cycle > 20 else None
        sig_now = max((current["hi"] - current["lo"]) / 3.29, 0.3)
        for _ in range(400):
            B = float(rng.choice(Bs))
            s = soh_now + rng.normal(0, sig_now)
            s = min(s, 99.5)
            if n_ref is None:
                # unknown age: place the battery on the curve where it would have this SOH
                A = float(rng.uniform(10, 25))
            else:
                A = (100 - s) / (n_ref / 1000.0) ** B
            samples_A.append(A); samples_B.append(B)

    A = np.array(samples_A); B = np.array(samples_B)
    if not cycle_known or method == "population_prior" and (cur_cycle is None or cur_cycle <= 20):
        # equivalent cycle position on each sampled curve
        n_now = 1000.0 * np.power(np.clip(100 - soh_now, 0.05, None) / A, 1.0 / B)
    else:
        n_now = np.full_like(A, float(cur_cycle))
    cross = np.array([_cross(a, b, eol) for a, b in zip(A, B)])
    rul = np.clip(cross - n_now, 0, RUL_CAP)
    p10, p50, p90 = np.percentile(rul, [10, 50, 90])
    rate = A * B * np.power(np.maximum(n_now, 1) / 1000.0, B - 1)   # dSOH/dn in %-points per 1000 cycles
    rate_per_100 = float(np.median(rate) / 10.0)

    n0 = float(np.median(n_now))
    grid = np.linspace(0, n0 + max(p90, 200) * 1.15, 60)
    curves = np.array([_curve(grid, a, b) for a, b in zip(A, B)])
    traj = [{"cycle": int(g), "p10": float(np.percentile(curves[:, k], 10)),
             "p50": float(np.percentile(curves[:, k], 50)), "p90": float(np.percentile(curves[:, k], 90)),
             "forecast": bool(g >= n0)} for k, g in enumerate(grid)]
    rel = (p90 - p10) / max(p50, 1)
    conf = float(np.clip(100 * np.exp(-rel), 5, 99))
    return {"rul_cycles": int(round(p50, -1)), "rul_p10": int(round(p10, -1)), "rul_p90": int(round(p90, -1)),
            "eol_soh": eol, "method": method, "cycle_now": int(round(n0)), "cycle_known": cycle_known,
            "degradation_rate_per_100": round(rate_per_100, 3), "trajectory": traj, "history": _hist(pts),
            "n_history": len(pts), "capped": bool(p50 >= RUL_CAP), "status": "PROTOTYPE", "confidence": round(conf, 1)}


def _hist(pts):
    return [{"cycle": int(p["cycle"]), "soh": round(float(p["soh"]), 2), "lo": round(float(p["lo"]), 2),
             "hi": round(float(p["hi"]), 2)} for p in pts]
