"""Layer — confidence estimation (separate from the prediction itself).

SOH confidence = P(|true − predicted| ≤ tolerance) under a Gaussian whose spread
matches the conformalised 90 % interval. Out-of-distribution inputs are
down-weighted. Bands are configurable (config.CONFIDENCE_BANDS), not universal.
"""
from __future__ import annotations

import math

from app.config import CONFIDENCE_BANDS, CONFIDENCE_TOLERANCE_PTS


def band(c: float) -> str:
    if c >= CONFIDENCE_BANDS["high"]:
        return "HIGH"
    if c >= CONFIDENCE_BANDS["moderate"]:
        return "MODERATE"
    return "LOW"


def soh_confidence(lo: float, hi: float, ood: bool, tol: float = CONFIDENCE_TOLERANCE_PTS) -> dict:
    sigma = max((hi - lo) / (2 * 1.645), 1e-3)
    c = 100 * math.erf(tol / (sigma * math.sqrt(2)))
    notes = [f"Probability that true SOH is within ±{tol} pts of the estimate, from the calibrated 90% interval."]
    if ood:
        c *= 0.75
        notes.append("Input is outside the training distribution — confidence reduced by 25 %.")
    return {"value": round(c, 1), "band": band(c), "sigma": round(sigma, 2), "notes": notes}


def overall_confidence(soh_c: float, rul_c: float, margin: float, unverified: int, second_score: float = 0.0) -> dict:
    # A close race only lowers confidence when the runner-up is not itself highly suitable
    margin_c = 100.0 if second_score >= 80 else 100 * min(1.0, max(margin, 0) / 10.0) ** 0.5
    penalty = 1.0 - 0.04 * min(unverified, 5)
    value = (0.6 * soh_c + 0.15 * rul_c + 0.25 * margin_c) * penalty
    return {
        "value": round(value, 1), "band": band(value),
        "components": {"soh": round(soh_c, 1), "rul": round(rul_c, 1), "decision_margin": round(margin_c, 1),
                       "unverified_criteria_penalty": round(1 - penalty, 2)},
        "formula": "(0.60·SOH + 0.15·RUL + 0.25·ranking-margin confidence) × (1 − 0.04·unverified criteria)",
    }
