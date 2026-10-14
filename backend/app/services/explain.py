"""Explainable AI layer.

Two kinds of explanation, both computed — never hand-written per battery:
  1. SOH model: exact TreeSHAP contributions from the XGBoost point model
     (SOH points each feature pushed the prediction up/down from the base value).
  2. Application ranking: per-criterion fit and signed impact from the
     suitability engine, plus a generated natural-language rationale.
"""
from __future__ import annotations

import math

from app.ml.feature_engineering import FEATURE_LABELS

UNITS = {"ir_cell_mohm": "mΩ/cell", "t_rise": "°C", "t_mean": "°C", "cycle": "", "c_rate": "C",
         "capacity_est_norm": "×Qnom", "ah_norm": "×Qnom", "discharge_duration_s": "s", "cell_imbalance_mv": "mV",
         "v_recovery_cell_mv": "mV", "thermal_response": "°C/(C²h)"}


def shap_explanation(contribs: dict, base: float, features: dict, top_k: int = 10) -> dict:
    items = []
    for k, c in contribs.items():
        v = features.get(k)
        items.append({"feature": k, "label": FEATURE_LABELS.get(k, k), "contribution": round(c, 3),
                      "value": None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 4),
                      "unit": UNITS.get(k, ""), "measured": not (v is None or (isinstance(v, float) and math.isnan(v)))})
    items.sort(key=lambda d: -abs(d["contribution"]))
    return {"method": "TreeSHAP (XGBoost pred_contribs) — exact for the tree ensemble",
            "base_value": round(base, 2), "top": items[:top_k], "all": items}


def application_explanation(router: dict) -> dict:
    apps = router["ranking"]
    best = apps[0]
    worst = min(apps, key=lambda a: a["score"])
    second = apps[1] if len(apps) > 1 else None

    pos = [c for c in sorted(best["criteria"], key=lambda c: -c["impact"]) if c["fit"] >= 0.7][:3]
    neg_w = [c for c in sorted(worst["criteria"], key=lambda c: c["impact"]) if c["fit"] < 0.5][:2]

    def lower(s):
        if not s or (len(s) > 1 and s[1].isupper()):
            return s
        return s[0].lower() + s[1:]

    text = f"{best['name']} ranks highest ({best['score']:.0f}/100)"
    if pos:
        text += ": " + _join([lower(c["phrase"]) for c in pos[:2]])
    text += "."
    if worst["id"] != best["id"]:
        if worst["gates_failed"]:
            text += f" {worst['name']} is excluded: {lower(worst['gates_failed'][0])}."
        elif neg_w:
            text += (f" {worst['name']} scores lowest ({worst['score']:.0f}) — "
                     + _join([lower(c["label"]) + f" {c['display_value']} falls short of {_fmt_req(c)}" for c in neg_w]) + ".")
    if second and best["score"] - second["score"] < 5 and second["score"] >= 80:
        text += f" {second['name']} is equally well suited ({second['score']:.0f}) — either is a sound route."
    elif second and best["score"] - second["score"] < 5:
        text += f" {second['name']} is a close alternative ({second['score']:.0f}); additional testing could separate them."
    unv = [c["label"] for c in best["criteria"] if not c["verified"]]
    if unv:
        text += " Not yet measured: " + ", ".join(lower(u) for u in unv) + " (scored neutral)."

    per_app = {a["id"]: {"name": a["name"], "score": a["score"],
                         "factors": [{"label": c["label"], "impact": c["impact"], "fit": c["fit"],
                                      "value": c["display_value"], "requirement": _fmt_req(c), "verified": c["verified"]}
                                     for c in sorted(a["criteria"], key=lambda c: -abs(c["impact"]))]}
               for a in apps + router["pathways"]}
    return {"summary": text, "recommended": best["id"], "contrast": worst["id"], "per_application": per_app,
            "method": "Per-criterion fit × weight from the suitability engine (impact = weight·(2·fit−1))."}


def _fmt_req(c):
    good = c["good"]
    if c["metric"] == "efficiency":
        g = f"{good * 100:.0f}%"
    else:
        g = f"{good:g}"
    return ("≥ " if c["kind"] == "min" else "≤ ") + g


def _join(parts):
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]
