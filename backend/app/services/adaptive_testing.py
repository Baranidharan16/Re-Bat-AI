"""Adaptive testing engine — "when the AI is uncertain, it asks for the next test".

1. Diagnose *why* the result is uncertain (missing sensors, narrow SOC window,
   wide SOH interval, out-of-distribution input, short ageing history, close
   ranking that hinges on an unmeasured criterion).
2. Score each catalogued test by the severity of the uncertainty it resolves per
   unit time:  priority = Σ severity_resolved / sqrt(duration_h + 0.25).
3. Recommend the best test (required when overall confidence is below the
   HIGH band or a severity-3 source exists).

Closing the loop (AI → TEST REQUEST → HARDWARE → DATA → AI) is done by
`merge_evidence`: the new test's features override the earlier evidence only
for the quantities that test actually measures.
"""
from __future__ import annotations

import math
from functools import lru_cache

from app.config import CONFIDENCE_BANDS, load_json

METRIC_TO_SOURCE = {"power_c_capability": "power_uncertain", "ir_cell_mohm": "ir_missing",
                    "thermal_score": "temp_missing", "efficiency": "efficiency_unmeasured",
                    "imbalance_mv": "imbalance_missing", "degradation_rate": "rul_history_short",
                    "rul_cycles": "rul_history_short"}


@lru_cache(maxsize=1)
def catalog() -> dict:
    return load_json("diagnostic_tests.json")


def _nan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def diagnose(features: dict, soh: dict, ood: bool, rul: dict, router: dict) -> list[dict]:
    src = catalog()["uncertainty_sources"]
    found = {}

    def add(key, extra=None, boost=0):
        sev = src[key]["severity"] + boost
        if key not in found or found[key]["severity"] < sev:
            found[key] = {"source": key, "severity": sev, "message": src[key]["message"] + (f" {extra}" if extra else "")}

    if _nan(features.get("ir_cell_mohm")):
        add("ir_missing")
    if _nan(features.get("thermal_response")):
        add("temp_missing")
    elif (features.get("discharge_duration_s") or 0) < 900:
        add("thermal_uncertain")
    w = features.get("soc_window")
    if _nan(features.get("capacity_est_norm")) or _nan(w) or w < 0.5:
        add("capacity_window", f"(tested window ≈ {w * 100:.0f}% SOC)" if not _nan(w) else None)
    if _nan(features.get("soc_end_est")):
        add("no_rest")
    width = soh["hi"] - soh["lo"]
    if width > 7:
        add("soh_interval_wide", f"(90% interval {soh['lo']:.1f}–{soh['hi']:.1f}%, width {width:.1f} pts)",
            boost=1 if width > 12 else 0)
    if ood:
        add("ood")
    if rul.get("method") == "population_prior":
        add("rul_history_short")
    if _nan(features.get("cell_imbalance_mv")):
        add("imbalance_missing")
    # ranking hinges on an unmeasured criterion?
    apps = router["ranking"]
    if len(apps) > 1 and router["decision_margin"] < 8:
        a, b = apps[0], apps[1]
        diffs = {}
        for ca in a["criteria"]:
            if not ca["verified"]:
                diffs[ca["metric"]] = diffs.get(ca["metric"], 0) + ca["weight_norm"]
        for cb in b["criteria"]:
            if not cb["verified"]:
                diffs[cb["metric"]] = diffs.get(cb["metric"], 0) + cb["weight_norm"]
        for m, wgt in sorted(diffs.items(), key=lambda kv: -kv[1])[:2]:
            if m in METRIC_TO_SOURCE:
                add(METRIC_TO_SOURCE[m], f"It affects the close call between {a['short']} and {b['short']}.", boost=1)
    return sorted(found.values(), key=lambda d: -d["severity"])


def recommend(sources: list[dict], overall_conf: float, has_safety_alarm: bool) -> dict:
    tests = catalog()["tests"]
    by_src = {s["source"]: s for s in sources}
    scored = []
    for t in tests:
        resolved = [by_src[r] for r in t["resolves"] if r in by_src]
        if not resolved:
            continue
        gain = sum(r["severity"] for r in resolved)
        pr = gain / math.sqrt(t["duration_min"] / 60 + 0.25)
        scored.append({"id": t["id"], "name": t["name"], "description": t["description"],
                       "duration_min": t["duration_min"], "priority": round(pr, 2),
                       "resolves": [r["source"] for r in resolved],
                       "reason": resolved[0]["message"] if resolved else "",
                       "hardware_command": t["hardware_command"]})
    scored.sort(key=lambda s: -s["priority"])
    max_sev = max((s["severity"] for s in sources), default=0)
    required = (overall_conf < CONFIDENCE_BANDS["high"] or max_sev >= 3) and bool(scored)
    if has_safety_alarm:
        return {"required": False, "blocked_by_safety": True, "recommended": None, "alternatives": scored[:3],
                "message": "Safety alarm active — no further electrical testing until the battery is inspected."}
    return {"required": required, "blocked_by_safety": False,
            "recommended": scored[0] if required else None,
            "alternatives": scored[1:4] if required else scored[:3],
            "message": ("Additional test recommended." if required else "No additional test currently required.")}


def merge_evidence(prev: dict, new: dict, test_id: str) -> tuple[dict, list[str]]:
    """Combine features of an earlier test with a newly requested one."""
    t = next((t for t in catalog()["tests"] if t["id"] == test_id), None)
    overrides = set(t["overrides"]) if t else set()
    merged, changed = dict(prev), []
    for k, v in new.items():
        if _nan(v):
            continue
        # only quantities this test is designed to measure replace earlier evidence;
        # mixing e.g. a pulse test's tiny SOC window into a capacity estimate would be inconsistent
        if k in overrides or (k == "cycle" and _nan(prev.get(k))):
            if _nan(prev.get(k)) or abs(float(prev[k]) - float(v)) > 1e-9:
                changed.append(k)
            merged[k] = v
    return merged, changed
