"""Phase 2 — Dataset ingestion: validation + cleaning into the canonical schema.

Canonical time-series schema (one row per sample, one DataFrame per test):
    timestamp [s], voltage [V pack], current [A, +discharge], temperature [degC],
    capacity [Ah cumulative], cycle [int], internal_resistance [ohm, optional],
    cell_v_min / cell_v_max [V, optional]

Loaders for public datasets map their native format onto this schema so the same
feature engineering + model code is used for demo, CSV, ESP32 and public data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

CANONICAL = ["timestamp", "voltage", "current", "temperature", "capacity", "cycle",
             "internal_resistance", "cell_v_min", "cell_v_max"]
REQUIRED = ["timestamp", "voltage", "current"]

ALIASES = {
    "time": "timestamp", "t": "timestamp", "time_s": "timestamp", "test_time": "timestamp",
    "voltage_measured": "voltage", "v": "voltage", "volt": "voltage", "voltage_v": "voltage",
    "current_measured": "current", "i": "current", "current_a": "current",
    "temperature_measured": "temperature", "temp": "temperature", "temp_c": "temperature", "t_c": "temperature",
    "cycle_count": "cycle", "cycle_index": "cycle", "cycle_number": "cycle",
    "ir": "internal_resistance", "resistance": "internal_resistance", "r_int": "internal_resistance",
    "capacity_ah": "capacity", "discharge_capacity": "capacity",
}


@dataclass
class ValidationReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rows_in: int = 0
    rows_out: int = 0
    actions: list[str] = field(default_factory=list)

    def to_dict(self):
        return self.__dict__


class DataValidationError(ValueError):
    def __init__(self, report: ValidationReport):
        super().__init__("; ".join(report.errors))
        self.report = report


def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    for c in df.columns:
        key = str(c).strip().lower().replace(" ", "_").replace("(", "").replace(")", "")
        rename[c] = ALIASES.get(key, key)
    return df.rename(columns=rename)


def _parse_timestamp(series: pd.Series) -> pd.Series:
    if np.issubdtype(series.dtype, np.number):
        return series.astype(float)
    parsed = pd.to_datetime(series, errors="coerce", utc=True)
    if parsed.notna().mean() > 0.9:
        return (parsed - parsed.dropna().iloc[0]).dt.total_seconds()
    return pd.to_numeric(series, errors="coerce")


def validate_and_clean(df: pd.DataFrame, series_cells: int = 3) -> tuple[pd.DataFrame, ValidationReport]:
    rep = ValidationReport(rows_in=len(df))
    df = normalise_columns(df.copy())
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        rep.ok = False
        rep.errors.append(f"Missing required column(s): {', '.join(missing)}. Required: {REQUIRED}")
        raise DataValidationError(rep)

    df["timestamp"] = _parse_timestamp(df["timestamp"])
    for c in CANONICAL:
        if c == "timestamp":
            continue
        if c not in df.columns:
            df[c] = np.nan
            if c in ("temperature", "capacity", "cycle"):
                rep.warnings.append(f"Column '{c}' not provided — related features will be missing (lower confidence).")
        else:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    before = len(df)
    df = df.dropna(subset=["timestamp", "voltage", "current"])
    if len(df) < before:
        rep.actions.append(f"Dropped {before - len(df)} rows with unparsable timestamp/voltage/current.")

    df = df.sort_values("timestamp").drop_duplicates("timestamp")
    df["timestamp"] = df["timestamp"] - df["timestamp"].iloc[0] if len(df) else df["timestamp"]

    # physical plausibility (per cell)
    vc = df["voltage"] / series_cells
    bad = (vc < 1.5) | (vc > 4.6)
    if bad.any():
        rep.actions.append(f"Removed {int(bad.sum())} rows with implausible voltage for a {series_cells}S pack.")
        df = df[~bad]
    if "temperature" in df and df["temperature"].notna().any():
        badt = (df["temperature"] < -40) | (df["temperature"] > 120)
        if badt.any():
            df.loc[badt, "temperature"] = np.nan
            rep.actions.append(f"Nulled {int(badt.sum())} implausible temperature readings.")

    # sign convention: discharge must be positive
    dv = df["voltage"].diff()
    loaded = df["current"].abs() > 0.05
    if loaded.sum() > 5 and (df.loc[loaded, "current"] < 0).mean() > 0.6 and (dv[loaded] < 0).mean() > 0.5:
        df["current"] = -df["current"]
        rep.actions.append("Flipped current sign (detected negative-discharge convention).")

    # coulomb counting when capacity column absent
    if df["capacity"].isna().all() and len(df) > 1:
        dt = df["timestamp"].diff().fillna(0).clip(lower=0)
        df["capacity"] = (df["current"].clip(lower=0) * dt / 3600.0).cumsum()
        rep.actions.append("Derived cumulative discharge capacity by coulomb counting.")

    # resistance given in mOhm?
    if df["internal_resistance"].notna().any() and df["internal_resistance"].median() > 2:
        df["internal_resistance"] = df["internal_resistance"] / 1000.0
        rep.actions.append("Converted internal_resistance from mOhm to Ohm.")

    if len(df) < 10:
        rep.ok = False
        rep.errors.append(f"Only {len(df)} valid rows after cleaning — at least 10 are needed.")
        raise DataValidationError(rep)
    if df["current"].clip(lower=0).max() < 0.05:
        rep.warnings.append("No discharge current detected — capacity/curve features will be unreliable.")

    rep.rows_out = len(df)
    return df[CANONICAL].reset_index(drop=True), rep


def split_tests(df: pd.DataFrame) -> Iterable[tuple[int, pd.DataFrame]]:
    """A CSV may contain several cycles; yield one DataFrame per cycle."""
    if "cycle" in df and df["cycle"].notna().any() and df["cycle"].nunique() > 1:
        for c, g in df.groupby("cycle"):
            yield int(c), g.reset_index(drop=True)
    else:
        c = int(df["cycle"].dropna().iloc[0]) if df["cycle"].notna().any() else 0
        yield c, df


# ---------------------------------------------------------------------------
# Public dataset adapters (for real training data). These map native formats to
# the canonical schema. They are untested against every file variant — check the
# validation report after loading.
# ---------------------------------------------------------------------------

def load_nasa_mat(path: str | Path, nominal_capacity_ah: float = 2.0):
    """NASA PCoE battery ageing (.mat, e.g. B0005.mat). Yields (meta, df, soh)."""
    from scipy.io import loadmat
    path = Path(path)
    m = loadmat(path)
    key = [k for k in m.keys() if not k.startswith("__")][0]
    cycles = m[key][0, 0]["cycle"][0]
    k = 0
    for c in cycles:
        if str(c["type"][0]) != "discharge":
            continue
        d = c["data"][0, 0]
        cap = float(d["Capacity"][0][0])
        df = pd.DataFrame({
            "timestamp": d["Time"][0],
            "voltage": d["Voltage_measured"][0],
            "current": -d["Current_measured"][0],
            "temperature": d["Temperature_measured"][0],
            "cycle": k,
        })
        k += 1
        meta = {"battery_id": f"NASA-{path.stem}", "series_cells": 1, "nominal_capacity_ah": nominal_capacity_ah,
                "source": "NASA_PCOE"}
        yield meta, df, 100.0 * cap / nominal_capacity_ah


def load_canonical_csv_folder(folder: str | Path):
    """Own experimental data: one CSV per test with a sidecar `labels.csv`
    (columns: file, battery_id, soh, series_cells, nominal_capacity_ah)."""
    folder = Path(folder)
    labels = pd.read_csv(folder / "labels.csv")
    for _, r in labels.iterrows():
        df = pd.read_csv(folder / r["file"])
        meta = {"battery_id": r["battery_id"], "series_cells": int(r.get("series_cells", 3)),
                "nominal_capacity_ah": float(r.get("nominal_capacity_ah", 2.5)), "source": "EXPERIMENTAL"}
        yield meta, df, float(r["soh"])
