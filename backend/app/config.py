"""Central configuration for RE-BAT AI.

All thresholds here are PROTOTYPE values chosen for screening/demo purposes.
They are not industry certification limits and are meant to be tuned.
"""
from __future__ import annotations

import json
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
CONFIG_DIR = BACKEND_DIR / "app" / "config_files"
MODEL_DIR = BACKEND_DIR / "artifacts"
DB_PATH = DATA_DIR / "rebat.sqlite3"

DATA_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)

APP_NAME = "RE-BAT AI"
APP_VERSION = "3.0.0"

# ---- Pack defaults (match the ESP32 demo rig: 3S Li-ion module) -------------
DEFAULT_SERIES_CELLS = 3
DEFAULT_NOMINAL_CAPACITY_AH = 2.5
DEFAULT_NOMINAL_VOLTAGE = 11.1

# ---- Confidence ---------------------------------------------------------------
# Confidence = P(|true SOH - predicted SOH| <= tolerance), derived from the
# conformalised prediction interval. Tolerance is in SOH percentage points.
CONFIDENCE_TOLERANCE_PTS = 2.5
CONFIDENCE_BANDS = {"high": 90.0, "moderate": 75.0}  # configurable, not universal

# ---- RUL ----------------------------------------------------------------------
# Second-life end-of-useful-life threshold used for the RUL estimate.
RUL_EOL_SOH = 60.0

# ---- Live streaming ------------------------------------------------------------
LIVE_WINDOW_MIN_READINGS = 30     # loaded (discharging) samples needed before a rolling forecast
LIVE_WINDOW_MAX_READINGS = 6000   # hard cap: a window this long is forecast and closed

# ---- Safety limits (per cell) ---------------------------------------------------
SAFETY = {
    "cell_v_min": 2.5,
    "cell_v_max": 4.25,
    "temp_warn_c": 50.0,
    "temp_alarm_c": 60.0,
    "dTdt_alarm_c_per_min": 2.0,
    # gas sensor (e.g. MQ-5) rise above its own start-of-test baseline; uncalibrated, relative only
    "gas_rise_warn_v": 0.4,
    "gas_rise_alarm_v": 0.8,
    "current_abs_max_a": 10.0,
}


def load_json(name: str):
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)
