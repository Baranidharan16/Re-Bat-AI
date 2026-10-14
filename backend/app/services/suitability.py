"""Layer 4 — Application suitability engine (Second-Life Router).

Compares the battery fingerprint against application requirement profiles
(config_files/applications.json) using a transparent multi-criteria model:

  fit_i   = smoothstep((x_i − poor_i) / (good_i − poor_i))   ∈ [0.02, 1]
  score   = 100 · Π fit_i ^ (w_i / Σw)                        (weighted geometric mean)
  gates   : hard exclusions (e.g. HIGH thermal risk) cap the score at 15

The geometric mean means one badly-failed requirement drags the score down even
if everything else is excellent — "SOH 80 % = solar" cannot happen.
Missing measurements get a neutral fit (0.5) and are flagged "unverified".

Why not a learned ranker yet? There is no labelled dataset of real second-life
deployment outcomes; training on invented labels would fabricate accuracy.
`app.ml.evaluate_model.ranking_metrics` is ready for Top-1/Top-3 evaluation once
outcome labels exist, and a learned model can replace `score_application`.
"""
from __future__ import annotations

import math
from functools import lru_cache

from app.config import load_json

METRIC_LABELS = {
    "soh": ("State of health", "%"), "rul_cycles": ("Remaining useful life", "cycles"),
    "power_c_capability": ("Peak power capability", "C"), "ir_cell_mohm": ("Internal resistance", "mΩ/cell"),
    "thermal_score": ("Thermal behaviour score", "/100"), "efficiency": ("Round-trip efficiency", ""),
    "degradation_rate": ("Degradation rate", "%/100 cyc"), "imbalance_mv": ("Cell imbalance", "mV"),
    "confidence": ("AI confidence", "%"), "decision_margin": ("Gap between top options", "pts"),
    "missing_evidence": ("Unmeasured key parameters", ""),
}


@lru_cache(maxsize=1)
def app_config() -> dict:
    return load_json("applications.json")


def _smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def _fmt(metric, x):
    if x is None:
        return "not measured"
    if metric == "efficiency":
        return f"{x * 100:.1f}%"
    unit = METRIC_LABELS.get(metric, ("", ""))[1]
    if isinstance(x, float):
        return f"{x:.1f} {unit}".strip() if abs(x) < 1000 else f"{x:,.0f} {unit}".strip()
    return f"{x} {unit}".strip()


def _phrase(metric, fit, x, good, kind):
    label = METRIC_LABELS.get(metric, (metric, ""))[0]
    if x is None:
        return f"{label} not measured — assumed neutral"
    if fit >= 0.99:
        return f"{label} {_fmt(metric, x)} meets the {'≥' if kind == 'min' else '≤'}{_fmt(metric, good)} target"
    if fit >= 0.6:
        return f"{label} {_fmt(metric, x)} is close to the {'≥' if kind == 'min' else '≤'}{_fmt(metric, good)} target"
    return f"{label} {_fmt(metric, x)} vs {'≥' if kind == 'min' else '≤'}{_fmt(metric, good)} needed"


def score_application(app: dict, m: dict) -> dict:
    crits, wsum, logsum, unverified = [], 0.0, 0.0, 0
    for c in app["criteria"]:
        x = m.get(c["metric"])
        if x is None or (isinstance(x, float) and math.isnan(x)):
            fit, x_val = 0.5, None
            unverified += 1
        else:
            x_val = float(x)
            t = (x_val - c["poor"]) / (c["good"] - c["poor"])   # works for both kinds (good<poor for 'max')
            fit = max(0.02, _smooth(t))
        w = c["weight"]
        wsum += w
        logsum += w * math.log(fit)
        crits.append({"metric": c["metric"], "label": METRIC_LABELS.get(c["metric"], (c["metric"],))[0],
                      "value": x_val, "display_value": _fmt(c["metric"], x_val), "kind": c["kind"],
                      "poor": c["poor"], "good": c["good"], "weight": w, "fit": round(fit, 3),
                      "verified": x_val is not None,
                      "phrase": _phrase(c["metric"], fit, x_val, c["good"], c["kind"])})
    fit_score = 100 * math.exp(logsum / wsum)
    tier = app.get("value_tier")
    vf = app_config().get("value_factor", {}).get(str(tier), 1.0) if tier else 1.0
    score = fit_score * vf
    for c in crits:
        c["weight_norm"] = round(c["weight"] / wsum, 3)
        c["impact"] = round(c["weight_norm"] * (c["fit"] - 0.5) * 2, 3)   # signed, for the XAI bars
    failed_gates = []
    for g in app.get("gates", []):
        v = m.get(g["metric"])
        if g["op"] == "ne":
            ok = v != g["value"]
        elif g["op"] == "not_in":
            ok = v not in g["value"]
        else:
            ok = v == g["value"]
        if not ok:
            failed_gates.append(g["reason"])
    if failed_gates:
        score = min(score, 15.0)
    bands = app_config()["status_bands"]
    if failed_gates:
        status = "Excluded"
    elif score >= bands["highly_suitable"]:
        status = "Highly suitable"
    elif score >= bands["suitable"]:
        status = "Suitable"
    elif score >= bands["conditional"]:
        status = "Conditional — validate"
    else:
        status = "Not recommended"
    pros = [c["phrase"] for c in sorted(crits, key=lambda c: -c["impact"]) if c["fit"] >= 0.75][:4]
    cons = [c["phrase"] for c in sorted(crits, key=lambda c: c["impact"]) if c["fit"] < 0.5 or not c["verified"]][:4]
    cons = failed_gates + cons
    return {"id": app["id"], "name": app["name"], "short": app["short"], "description": app["description"],
            "duty": app.get("duty"), "score": round(score, 1), "fit_score": round(fit_score, 1),
            "value_tier": tier, "value_factor": vf, "status": status, "criteria": crits,
            "reasons_for": pros, "reasons_against": cons, "gates_failed": failed_gates, "unverified": unverified}


def rank(metrics: dict, missing_evidence: int, low_confidence: bool = False) -> dict:
    cfg = app_config()
    apps = sorted((score_application(a, metrics) for a in cfg["second_life"]), key=lambda r: -r["score"])
    margin = apps[0]["score"] - apps[1]["score"] if len(apps) > 1 else 100.0
    pm = dict(metrics, decision_margin=margin, missing_evidence=missing_evidence)
    pathways = [score_application(p, pm) for p in cfg["pathways"]]
    for p in pathways:
        p["kind"] = "pathway"
    for i, a in enumerate(apps):
        a["kind"] = "second_life"; a["rank"] = i + 1
    best = apps[0]
    recyc = next(p for p in pathways if p["id"] == "recycling")
    diag = next(p for p in pathways if p["id"] == "further_diagnostics")
    # routing decision: which pathway wins overall
    provisional = None
    if recyc["score"] > max(best["score"], 50):
        decision = recyc
    elif diag["score"] >= 50 and (best["score"] < 50 or (low_confidence and diag["score"] >= 80)):
        decision = diag
        provisional = best["name"] if best["score"] >= 50 else None
    elif best["score"] < 50:
        decision = recyc if recyc["score"] >= diag["score"] else diag
    else:
        decision = best
    return {"ranking": apps, "pathways": pathways, "decision": {"id": decision["id"], "name": decision["name"],
            "score": decision["score"], "kind": decision.get("kind"), "provisional": provisional},
            "top": best["id"],
            "decision_margin": round(margin, 1), "unverified_top": best["unverified"],
            "method": "score = 100·Π fit_i^(w_i/Σw) × value factor(tier); hard gates cap at 15. Prototype weights in applications.json."}
