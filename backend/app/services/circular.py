"""Circular-economy engine: REUSE or RECYCLE.

Takes a finished analysis (SOH, RUL, fingerprint, router scores, safety) and decides
the pathway of the battery:

  REUSE    -> solar energy storage | factory / industrial backup | household backup | rural street light
              (ranked by the AI router scores, sized from the measured capacity)
  RECYCLE  -> material recovery: every mineral in the battery, grams contained and
              recoverable, and how they go back into a new EV cell (closed loop)
  RETEST   -> the AI is not confident yet: run the recommended test first
  HOLD     -> safety alarm: inspect before anything else

All composition figures are typical values for the configured chemistry and cell format.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from app.config import DATA_DIR, load_json

PACK_PATH = DATA_DIR / "pack_profile.json"      # chemistry + cell format of the battery on the rig
ATOMIC = {"Li": 6.94, "Ni": 58.693, "Co": 58.933, "Mn": 54.938, "Al": 26.982, "Fe": 55.845, "P": 30.974, "O": 15.999}
LI_TO_LCE = 5.323                                # g Li2CO3 per g Li


def cfg() -> dict:
    return load_json("circular.json")


def pack_profile() -> dict:
    c = cfg()
    prof = dict(c["default_pack"])
    try:
        saved = json.loads(PACK_PATH.read_text())
        if saved.get("chemistry") in c["chemistries"]:
            prof["chemistry"] = saved["chemistry"]
        if saved.get("cell_format") in c["cell_formats"]:
            prof["cell_format"] = saved["cell_format"]
        if saved.get("cell_mass_g"):
            prof["cell_mass_g"] = float(saved["cell_mass_g"])
    except (OSError, ValueError, TypeError):
        pass
    return prof


def save_pack_profile(prof: dict) -> dict:
    c = cfg()
    if prof.get("chemistry") not in c["chemistries"]:
        raise ValueError(f"chemistry must be one of {', '.join(c['chemistries'])}")
    if prof.get("cell_format") not in c["cell_formats"]:
        raise ValueError(f"cell_format must be one of {', '.join(c['cell_formats'])}")
    out = {"chemistry": prof["chemistry"], "cell_format": prof["cell_format"]}
    if prof.get("cell_mass_g"):
        out["cell_mass_g"] = float(prof["cell_mass_g"])
    PACK_PATH.write_text(json.dumps(out, indent=2))
    return out


def _f(x):
    try:
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------- minerals
def minerals(series_cells: int, nominal_capacity_ah: float, chemistry: str | None = None,
             cell_format: str | None = None, cell_mass_g: float | None = None,
             total_cell_mass_g: float | None = None, n_cells_override: int | None = None) -> dict:
    """Every material in the pack: share of mass, grams contained and recoverable."""
    c = cfg()
    prof = pack_profile()
    chem_id = chemistry or prof["chemistry"]
    fmt_id = cell_format or prof["cell_format"]
    chem, fmt = c["chemistries"][chem_id], c["cell_formats"][fmt_id]
    mass = float(cell_mass_g or (prof.get("cell_mass_g") if not cell_format else None) or fmt["cell_mass_g"])
    parallel = max(1, round(nominal_capacity_ah / fmt["cell_ah"]))
    n_cells = max(1, int(series_cells)) * parallel
    total = mass * n_cells
    if total_cell_mass_g:                      # whole EV pack: mass known (or estimated) directly
        total = float(total_cell_mass_g)
        n_cells = int(n_cells_override or max(1, round(total / mass)))
        parallel = 1
    mk = fmt["makeup"]

    formula = chem["cathode"]
    molar = sum(ATOMIC[e] * n for e, n in formula.items())
    grams: dict[str, float] = {}
    parts: dict[str, str] = {}
    for e, n in formula.items():
        grams[e] = grams.get(e, 0.0) + total * mk["cathode"] * ATOMIC[e] * n / molar
        parts[e] = "Cathode"
    grams["C"] = total * mk["graphite"]
    grams["Cu"] = total * mk["copper_foil"]
    grams["Al"] = grams.get("Al", 0.0) + total * (mk["aluminium_foil"] + mk["aluminium_case"])
    parts["Al"] = "Cathode foil" + (" / casing" if mk["aluminium_case"] else "") + (" / cathode" if "Al" in formula else "")
    if mk["steel_can"]:
        grams["Fe"] = grams.get("Fe", 0.0) + total * mk["steel_can"] * 0.98      # nickel-plated steel can
        parts["Fe"] = "Cathode + steel can" if "Fe" in formula else "Steel can"

    mats, rec_yield = c["materials"], c["recovery_yield"]
    rows = []
    for sym, g in grams.items():
        if sym == "O":
            continue
        m = mats[sym]
        y = rec_yield[sym]
        role = "Steel can that holds the cylindrical cell" if parts.get(sym) == "Steel can" else m["role"]
        rows.append({"symbol": sym, "name": m["name"], "color": m["color"], "critical": m["critical"],
                     "part": parts.get(sym, m["part"]), "role": role, "recovered_as": m["recovered_as"],
                     "new_battery_use": m["new_battery_use"], "india": m["india"],
                     "contained_g": round(g, 2), "share_pct": round(100 * g / total, 2),
                     "recovery_rate": y, "recoverable_g": round(g * y, 2)})
    rows.sort(key=lambda r: -r["contained_g"])

    nr = c["non_recovered"]
    other = [{"key": "O", "name": nr["O"]["name"], "color": nr["O"]["color"], "contained_g": round(grams.get("O", 0.0), 2)},
             {"key": "electrolyte", "name": nr["electrolyte"]["name"], "color": nr["electrolyte"]["color"], "contained_g": round(total * mk["electrolyte"], 2)},
             {"key": "other", "name": nr["other"]["name"], "color": nr["other"]["color"], "contained_g": round(total * mk["other"], 2)}]
    for o in other:
        o["share_pct"] = round(100 * o["contained_g"] / total, 2)

    crit = [r for r in rows if r["critical"]]
    recoverable = sum(r["recoverable_g"] for r in rows)
    li = next((r for r in rows if r["symbol"] == "Li"), None)
    cathode_metals = [s for s in formula if s not in ("O", "P")]
    limiting = min(cathode_metals, key=lambda s: rec_yield[s])
    return {
        "chemistry": chem_id, "chemistry_label": chem["label"], "family": chem["family"],
        "cell_format": fmt_id, "cell_format_label": fmt["label"],
        "cell_mass_g": mass, "cells_series": int(series_cells), "cells_parallel": parallel, "n_cells": n_cells,
        "pack_mass_g": round(total, 1),
        "materials": rows, "non_recovered": other,
        "totals": {
            "recoverable_g": round(recoverable, 1),
            "recoverable_pct_of_pack": round(100 * recoverable / total, 1),
            "yield_pct_of_recovered_materials": round(100 * recoverable / sum(r["contained_g"] for r in rows), 1),
            "critical_contained_g": round(sum(r["contained_g"] for r in crit), 1),
            "critical_recoverable_g": round(sum(r["recoverable_g"] for r in crit), 1),
            "lithium_carbonate_equivalent_g": round((li["recoverable_g"] if li else 0) * LI_TO_LCE, 1),
        },
        "closed_loop": {
            "new_cells_equivalent": round(n_cells * rec_yield[limiting], 1),
            "limited_by": c["materials"][limiting]["name"],
            "statement": f"Recovered cathode metals are enough for about {n_cells * rec_yield[limiting]:.1f} of the "
                         f"{n_cells} original cells' worth of new cathode (limited by {c['materials'][limiting]['name'].lower()} yield).",
        },
        "process": c["process"], "policy": c["policy"],
        "note": "Typical composition for this chemistry and cell format (±20 %). Weigh a teardown sample to calibrate.",
    }


# ----------------------------------------------------------------------------- reuse sizing
def _capacity_ah(result: dict) -> tuple[float, str]:
    nominal = float(result["meta"]["nominal_capacity_ah"])
    est = _f((result.get("features") or {}).get("capacity_est_norm"))
    if est and 0.2 < est < 1.3:
        return nominal * est, "estimated full capacity from the test"
    return nominal * float(result["soh"]["soh"]) / 100.0, "nominal capacity × SOH"


def _ceil(x: float) -> int:
    return max(1, math.ceil(x - 1e-9))


def reuse_options(result: dict, chem: dict) -> tuple[list[dict], dict]:
    c = cfg()["reuse"]
    series = int(result["meta"]["series_cells"])
    cap_ah, cap_src = _capacity_ah(result)
    v_nom = chem["cell_nominal_v"] * series
    m = result["fingerprint"]["metrics"]
    eff = _f(m.get("efficiency")) or c["default_efficiency"]
    eff = min(max(eff, 0.6), 0.99)
    usable = cap_ah * v_nom * c["depth_of_discharge"] * eff
    usable = max(usable, 0.01)
    c_rate = _f(m.get("power_c_capability"))
    peak_w = c_rate * cap_ah * v_nom if c_rate else None
    rul = _f(result["rul"].get("rul_cycles")) or 0.0
    scores = {a["id"]: a for a in result["router"]["ranking"]}

    def app(ids):
        best = max((scores[i] for i in ids if i in scores), key=lambda a: a["score"], default=None)
        return best

    s = c["solar"]
    panel_w = usable / (s["peak_sun_hours"] * s["panel_derate"])
    solar_app = app(["solar_storage"])
    f = c["factory"]
    fac_app = app(["ups_high_power", "commercial_storage", "microgrid", "telecom_backup"])
    h = c["household"]
    home_app = app(["residential_backup"])
    sl = c["street_light"]
    sl_app = app(["low_power_stationary"])

    def base(id_, name, icon, a, desc):
        return {"id": id_, "name": name, "icon": icon, "description": desc,
                "score": round(a["score"], 1) if a else 0.0, "status": a["status"] if a else "Not scored",
                "router_match": a["name"] if a else None,
                "reasons_for": (a or {}).get("reasons_for", [])[:3], "reasons_against": (a or {}).get("reasons_against", [])[:3]}

    opts = [
        {**base("solar_storage", "Solar energy storage", "sun", solar_app,
                "Stores daytime solar for evening use. One gentle cycle a day, so long life matters most."),
         "sizing": {"usable_wh": round(usable, 1), "panel_w": round(panel_w, 1),
                    "panel_w_standard": next((p for p in (5, 10, 20, 30, 40, 50, 75, 100, 150, 200, 300, 500, 1000, 2000, 5000) if p >= panel_w), round(panel_w)),
                    "home_daily_wh": s["home_daily_wh"], "autonomy_days": round(usable / s["home_daily_wh"], 2),
                    "modules_for_one_day": _ceil(s["home_daily_wh"] / usable),
                    "years_at_one_cycle_per_day": round(rul / 365, 1),
                    "charge_setting": f"CC/CV {chem['cell_full_v'] * series:.1f} V"},
         "formula": "usable Wh = capacity Ah × nominal V × 0.8 DoD × efficiency;  panel W = usable Wh ÷ (5 sun-hours × 0.75)"},
        {**base("factory_backup", "Factory / industrial backup", "factory", fac_app,
                "Keeps machines, lighting or a control room running through a power cut. Needs power and a cool, stable battery."),
         "sizing": {"usable_wh": round(usable, 1), "load_w": f["load_w"], "peak_power_w": round(peak_w, 0) if peak_w else None,
                    "runtime_min_at_load": round(60 * usable / f["load_w"], 1), "target_minutes": f["target_minutes"],
                    "modules_for_target": _ceil(f["load_w"] * f["target_minutes"] / 60 / usable)},
         "formula": "runtime = usable Wh ÷ load W;  modules = load W × minutes ÷ 60 ÷ usable Wh"},
        {**base("household_backup", "Household power backup", "home", home_app,
                "Runs fans and lights at home during an outage. Occasional deep discharge, kept indoors."),
         "sizing": {"usable_wh": round(usable, 1), "load_w": h["load_w"], "runtime_h_at_load": round(usable / h["load_w"], 2),
                    "target_hours": h["target_hours"], "modules_for_target": _ceil(h["load_w"] * h["target_hours"] / usable)},
         "formula": "runtime h = usable Wh ÷ (fan + lights W)"},
        {**base("street_light", "Rural street light", "lamp", sl_app,
                "Lights a village street from dusk to dawn. LDR switches it on at dusk, PIR brightens it when someone passes."),
         "sizing": {"usable_wh": round(usable, 1), "lamp_w": sl["lamp_w"], "night_hours": sl["night_hours"],
                    "nights_always_on": round(usable / (sl["lamp_w"] * sl["night_hours"]), 2),
                    "nights_smart": round(usable / (sl["lamp_w"] * sl["night_hours"] * sl["smart_duty"]), 2),
                    "hours_of_light": round(usable / sl["lamp_w"], 1), "smart_duty": sl["smart_duty"]},
         "formula": "nights = usable Wh ÷ (lamp W × 12 h × duty);  smart duty 30 % with LDR + PIR"},
    ]
    opts.sort(key=lambda o: -o["score"])
    energy = {"capacity_ah": round(cap_ah, 3), "capacity_source": cap_src, "nominal_v": round(v_nom, 2),
              "usable_wh": round(usable, 1), "efficiency": round(eff, 3), "depth_of_discharge": c["depth_of_discharge"]}
    return opts, energy


# ----------------------------------------------------------------------------- measured parameters
def _grade(v, good, poor, higher_better=True):
    if v is None:
        return "not measured"
    if higher_better:
        return "good" if v >= good else "poor" if v <= poor else "watch"
    return "good" if v <= good else "poor" if v >= poor else "watch"


def parameters(result: dict, energy: dict) -> list[dict]:
    """The 8–10 hardware measurements behind the recommendation, each graded for second-life use."""
    meas, feat = result.get("measurements") or {}, result.get("features") or {}
    m = result["fingerprint"]["metrics"]
    series = int(result["meta"]["series_cells"])
    v_cell = _f(feat.get("v_cell_mean"))
    i_mean = _f(meas.get("i_mean"))
    ir = _f(meas.get("ir_pack_mohm"))
    ir_cell = _f(m.get("ir_cell_mohm"))
    t_max = _f(meas.get("t_max"))
    t_rise = _f(feat.get("t_rise"))
    imb = _f(m.get("imbalance_mv"))
    eff = _f(m.get("efficiency"))
    gas_alerts = [a for a in result["safety"]["alerts"] if "GAS" in a["code"].upper()]
    cap_ratio = energy["capacity_ah"] / float(result["meta"]["nominal_capacity_ah"])
    rows = [
        ("voltage", "Pack voltage", v_cell * series if v_cell else None, "V", "INA219 / voltage sensor",
         _grade(v_cell, 3.6, 3.3) if v_cell else "not measured", "Mean cell voltage under test; low means a weak or deeply discharged pack."),
        ("current", "Test current", i_mean, "A", "ACS712 / INA219", "good" if i_mean else "not measured",
         "Load current used for the capacity and resistance measurement."),
        ("power", "Power delivered", (i_mean * v_cell * series) if (i_mean and v_cell) else None, "W", "V × I",
         "good" if i_mean else "not measured", "Average power during the test."),
        ("capacity", "Capacity", energy["capacity_ah"], "Ah", "Coulomb counting",
         _grade(cap_ratio, 0.8, 0.6), f"{cap_ratio * 100:.0f}% of the {result['meta']['nominal_capacity_ah']} Ah label."),
        ("energy", "Usable energy", energy["usable_wh"], "Wh", "Ah × V × DoD × efficiency", _grade(cap_ratio, 0.8, 0.6),
         "Energy available to a second-life application."),
        ("resistance", "Internal resistance", ir, "mΩ", "Load pulse ΔV/ΔI", _grade(ir_cell, 60, 150, False),
         f"{ir_cell:.0f} mΩ per cell — decides peak power (factory backup needs low resistance)." if ir_cell else "Needs a pulse test."),
        ("temperature", "Max temperature", t_max, "°C", "DS18B20", _grade(t_max, 40, 55, False),
         f"Rise {t_rise:.1f} °C under load." if t_rise is not None else "No temperature sensor data."),
        ("imbalance", "Cell imbalance", imb, "mV", "Cell taps", _grade(imb, 30, 80, False),
         "Spread between the strongest and weakest cell."),
        ("efficiency", "Efficiency", eff * 100 if eff else None, "%", "Energy out ÷ energy in", _grade(eff, 0.95, 0.88) if eff else "not measured",
         "Round-trip efficiency; matters most for daily solar cycling."),
        ("gas", "Gas / venting", "alert" if gas_alerts else "normal", "", "MQ gas sensor", "poor" if gas_alerts else "good",
         gas_alerts[0]["message"] if gas_alerts else "No rise above the start-of-test baseline."),
    ]
    return [{"id": i, "name": n, "value": (round(v, 2) if isinstance(v, float) else v), "unit": u, "sensor": src,
             "grade": g, "note": note} for i, n, v, u, src, g, note in rows]


# ----------------------------------------------------------------------------- pathway
def build(result: dict) -> dict:
    c = cfg()
    meta = result["meta"]
    min_ = minerals(meta["series_cells"], meta["nominal_capacity_ah"])
    chem = c["chemistries"][min_["chemistry"]]
    opts, energy = reuse_options(result, chem)
    best = opts[0]
    soh = float(result["soh"]["soh"])
    dec = result["router"]["decision"]
    safety = result["safety"]["status"]
    conf = float(result["confidence"]["value"])

    if safety == "ALARM":
        pathway, headline = "HOLD", "Safety hold — inspect before reuse or recycling"
        reason = "A safety alarm was raised during the test. Isolate the battery; if damage is confirmed it goes to certified recycling."
    elif soh < 60 or (best["score"] < 50 and conf >= 60) or (dec["id"] == "recycling" and conf >= 60):
        pathway, headline = "RECYCLE", "Recycle — recover the minerals"
        why = []
        if soh < 60:
            why.append(f"SOH {soh:.0f}% is below the 60% second-life limit")
        if best["score"] < 50:
            why.append(f"no reuse application scores above 50 (best: {best['name']} {best['score']:.0f})")
        if dec["id"] == "recycling" and not why:
            why.append("the AI router chose material recovery")
        reason = "; ".join(why)
        reason = reason[:1].upper() + reason[1:] + ". Its lithium, nickel, cobalt and manganese go back into new EV cells."
    elif dec["id"] == "further_diagnostics" or conf < 60:
        pathway = "RETEST"
        headline = f"Provisional reuse: {best['name']} — confirm with one more test" if best["score"] >= 50 else "Not decided yet — run one more test"
        reason = (f"AI confidence is {conf:.0f}% — too low to commit. Run the recommended test before choosing reuse or recycling"
                  + (" (the test may still be in progress)." if result.get("source") in ("ESP32", "LIVE_SIM") else "."))
    else:
        pathway, headline = "REUSE", f"Reuse — {best['name']}"
        rul = int(_f(result["rul"].get("rul_cycles")) or 0)
        reason = (f"{best['name']} scores {best['score']:.0f}/100 for this battery: SOH {soh:.0f}%, "
                  f"{rul} cycles of remaining life (about {rul / 365:.1f} years at one cycle a day).")

    loop = c["loop"]
    stage = {"REUSE": 3, "RETEST": 2, "HOLD": 2, "RECYCLE": 5}[pathway]
    return {
        "pathway": pathway, "headline": headline, "reason": reason,
        "reuse": {"eligible": pathway in ("REUSE", "RETEST"), "best": best["id"], "options": opts, "energy": energy},
        "recycle": {"recommended": pathway == "RECYCLE", **min_},
        "loop": {"steps": loop, "current": stage},
        "parameters": parameters(result, energy),
        "ai": {"soh": result["soh"]["soh"], "soh_lo": result["soh"]["lo"], "soh_hi": result["soh"]["hi"],
               "rul_cycles": result["rul"]["rul_cycles"], "confidence": conf},
        "pack": {"chemistry": min_["chemistry"], "chemistry_label": min_["chemistry_label"],
                 "cell_format": min_["cell_format"], "cell_format_label": min_["cell_format_label"],
                 "n_cells": min_["n_cells"], "pack_mass_g": min_["pack_mass_g"]},
    }
