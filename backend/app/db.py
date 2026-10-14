"""SQLite persistence. Only REAL-TIME stream data (ESP32 or live simulation) is
stored, and only after it has been forecast; each stored window is anchored in
the hash-chained ledger (app.services.ledger).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager

from app.config import DB_PATH

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS batteries (
    battery_id TEXT PRIMARY KEY,
    series_cells INTEGER NOT NULL,
    nominal_capacity_ah REAL NOT NULL,
    nominal_voltage REAL,
    chemistry TEXT DEFAULT 'Li-ion',
    source TEXT NOT NULL,                 -- ESP32 | LIVE_SIM
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battery_id TEXT NOT NULL REFERENCES batteries(battery_id),
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    cycle REAL,
    soh REAL, soh_lo REAL, soh_hi REAL,
    confidence REAL,
    rul_cycles INTEGER,
    top_application TEXT,
    decision TEXT,
    safety_status TEXT,
    n_readings INTEGER,
    is_final INTEGER DEFAULT 0,
    block_index INTEGER,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battery_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    forecast_id INTEGER NOT NULL REFERENCES forecasts(id),
    device_ts TEXT,
    t_s REAL NOT NULL,
    voltage REAL NOT NULL, current REAL NOT NULL, temperature REAL,
    capacity REAL, cycle_count REAL, internal_resistance REAL,
    cell_v_min REAL, cell_v_max REAL,
    gas_v REAL,
    leaf_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_readings_forecast ON readings(forecast_id);
CREATE TABLE IF NOT EXISTS ledger_blocks (
    idx INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    merkle_root TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    nonce INTEGER NOT NULL,
    block_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS test_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battery_id TEXT NOT NULL,
    test_id TEXT NOT NULL,
    status TEXT NOT NULL,                 -- pending | sent | done | cancelled
    reason TEXT,
    command_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
"""


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


_con: sqlite3.Connection | None = None


def get_con() -> sqlite3.Connection:
    global _con
    if _con is None:
        _con = connect()
        _con.executescript(SCHEMA)
        cols = {r[1] for r in _con.execute("PRAGMA table_info(readings)")}
        if "gas_v" not in cols:   # migrate databases created before the gas sensor was supported
            _con.execute("ALTER TABLE readings ADD COLUMN gas_v REAL")
            _con.commit()
    return _con


@contextmanager
def tx():
    with _lock:
        con = get_con()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise


def query(sql: str, args=()) -> list[dict]:
    with _lock:
        return [dict(r) for r in get_con().execute(sql, args).fetchall()]


def dumps(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), default=str)
