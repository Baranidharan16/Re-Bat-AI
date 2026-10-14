"""Safety screening of measurements. Runs before (and independent of) the AI.

The software never declares a battery safe. It only raises alerts when limits
are crossed; hardware protection (BMS, fuse, thermal cut-off) must act on its own.
"""
from __future__ import annotations

import math

from app.config import SAFETY

STOP = "Stop test / inspect battery."
DISCLAIMER = ("AI recommendations are screening/decision-support outputs. Final battery reuse requires "
              "validated electrical, thermal, mechanical and safety testing.")


def _alert(level, code, message, action=STOP):
    return {"level": level, "code": code, "message": message, "action": action}


def check_reading(r: dict, series_cells: int) -> list[dict]:
    """Per-sample check used on the live stream."""
    out = []
    v = r.get("voltage")
    if v is not None and series_cells:
        vc = v / series_cells
        if vc < SAFETY["cell_v_min"]:
            out.append(_alert("ALARM", "UNDER_VOLTAGE", f"Average cell voltage {vc:.2f} V below {SAFETY['cell_v_min']} V."))
        if vc > SAFETY["cell_v_max"]:
            out.append(_alert("ALARM", "OVER_VOLTAGE", f"Average cell voltage {vc:.2f} V above {SAFETY['cell_v_max']} V."))
    for key in ("cell_v_min", "cell_v_max"):
        x = r.get(key)
        if x is not None and not (isinstance(x, float) and math.isnan(x)):
            if x < SAFETY["cell_v_min"] or x > SAFETY["cell_v_max"]:
                out.append(_alert("ALARM", "CELL_VOLTAGE", f"A cell reads {x:.3f} V (limits {SAFETY['cell_v_min']}–{SAFETY['cell_v_max']} V)."))
    T = r.get("temperature")
    if T is not None and not (isinstance(T, float) and math.isnan(T)):
        if T >= SAFETY["temp_alarm_c"]:
            out.append(_alert("ALARM", "OVER_TEMPERATURE", f"Temperature {T:.1f} °C ≥ {SAFETY['temp_alarm_c']} °C."))
        elif T >= SAFETY["temp_warn_c"]:
            out.append(_alert("WARNING", "HIGH_TEMPERATURE", f"Temperature {T:.1f} °C ≥ {SAFETY['temp_warn_c']} °C.",
                              "Reduce load and monitor; stop if temperature keeps rising."))
    g, g0 = r.get("gas_v"), r.get("gas_baseline_v")
    if g is not None and g0 is not None:
        rise = g - g0
        if rise >= SAFETY["gas_rise_alarm_v"]:
            out.append(_alert("ALARM", "GAS_RISE", f"Gas sensor {g:.2f} V, +{rise:.2f} V above its start value — possible electrolyte venting."))
        elif rise >= SAFETY["gas_rise_warn_v"]:
            out.append(_alert("WARNING", "GAS_RISE", f"Gas sensor rising: +{rise:.2f} V above its start value (uncalibrated MQ-5).",
                              "Ventilate and watch closely; stop the test if it keeps rising."))
    I = r.get("current")
    if I is not None and abs(I) > SAFETY["current_abs_max_a"]:
        out.append(_alert("ALARM", "OVER_CURRENT", f"Current {I:.2f} A exceeds rig limit {SAFETY['current_abs_max_a']} A."))
    return out


def check_test(info: dict, series_cells: int) -> list[dict]:
    """Whole-test check from extracted feature info."""
    out = []
    vmin, vmax = info.get("v_cell_min_all"), info.get("v_cell_max_all")
    if vmin is not None and vmin < SAFETY["cell_v_min"]:
        out.append(_alert("ALARM", "UNDER_VOLTAGE", f"Pack fell to {vmin:.2f} V/cell during test."))
    if vmax is not None and vmax > SAFETY["cell_v_max"]:
        out.append(_alert("ALARM", "OVER_VOLTAGE", f"Pack reached {vmax:.2f} V/cell during test."))
    tmax = info.get("t_max")
    if tmax is not None and math.isfinite(tmax):
        if tmax >= SAFETY["temp_alarm_c"]:
            out.append(_alert("ALARM", "OVER_TEMPERATURE", f"Peak temperature {tmax:.1f} °C."))
        elif tmax >= SAFETY["temp_warn_c"]:
            out.append(_alert("WARNING", "HIGH_TEMPERATURE", f"Peak temperature {tmax:.1f} °C.",
                              "Inspect cooling and cell condition before further high-rate tests."))
    d = info.get("dTdt_max")
    if d is not None and math.isfinite(d) and d >= SAFETY["dTdt_alarm_c_per_min"]:
        out.append(_alert("ALARM", "FAST_TEMPERATURE_RISE", f"Temperature rose at {d:.1f} °C/min."))
    return out
