"""
SQLite store — makes re-runs idempotent and gives ``--since-last`` a memory.

The old pipeline wrote a fresh CSV every run, so re-running (or resuming after a
credit cap) duplicated rows and lost anything not in the latest pass. Here a
port call is keyed on ``(uuid, arrival_date)`` and UPSERTed, so the same call
seen twice updates in place instead of duplicating.

Two tables:
  * ``port_calls``       — one row per reconstructed call (the CSV, durably).
  * ``draught_snapshots``— Phase 0 forward-only capture: every live draught
                           reading for a hull near a port. This is the history
                           that compounds and cannot be backfilled, so it lives
                           in its own append-only table.

Pure stdlib (sqlite3); no external dependency.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS port_calls (
    uuid            TEXT NOT NULL,
    arrival_date    TEXT NOT NULL,          -- YYYY-MM-DD, from arrival_utc
    port            TEXT,
    vessel_name     TEXT,
    mmsi            TEXT,
    imo             TEXT,
    type_specific   TEXT,
    size_class      TEXT,
    dwt             TEXT,
    gross_tonnage   TEXT,
    length_m        TEXT,
    breadth_m       TEXT,
    year_built      TEXT,
    arrival_utc     TEXT,
    departure_utc   TEXT,
    days_in_port    REAL,
    arrived_anchored TEXT,
    grain_flag      TEXT,
    grain_confidence TEXT,
    min_dist_nm     REAL,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (uuid, arrival_date)
);

CREATE INDEX IF NOT EXISTS idx_calls_port ON port_calls(port);
CREATE INDEX IF NOT EXISTS idx_calls_arrival ON port_calls(arrival_utc);

-- Phase 0 live draught capture. Append-only; forward-only history.
CREATE TABLE IF NOT EXISTS draught_snapshots (
    uuid            TEXT NOT NULL,
    captured_at     TEXT NOT NULL,          -- ISO UTC of our capture
    port_key        TEXT,
    mmsi            TEXT,
    imo             TEXT,
    name            TEXT,
    draught_m       REAL,
    nav_status      TEXT,
    speed_kn        REAL,
    lat             REAL,
    lon             REAL,
    destination     TEXT,
    origin_port     TEXT,
    eta             TEXT,
    source          TEXT,                   -- e.g. 'vessel_pro'
    PRIMARY KEY (uuid, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_draught_uuid ON draught_snapshots(uuid);
CREATE INDEX IF NOT EXISTS idx_draught_port ON draught_snapshots(port_key);
"""

# Map a call dict (FIELDS keys, using the CSV's "_min_dist_nm") to columns.
_CALL_COLS = ["uuid", "arrival_date", "port", "vessel_name", "mmsi", "imo",
              "type_specific", "size_class", "dwt", "gross_tonnage",
              "length_m", "breadth_m", "year_built", "arrival_utc",
              "departure_utc", "days_in_port", "arrived_anchored",
              "grain_flag", "grain_confidence", "min_dist_nm"]


def connect(db_path: str = config.DB_PATH) -> sqlite3.Connection:
    """Open (creating parent dir + schema) and return a connection."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _arrival_date(call: dict) -> str:
    return (call.get("arrival_utc") or "")[:10]


def upsert_call(conn: sqlite3.Connection, call: dict) -> None:
    """Insert or replace a single port call, keyed (uuid, arrival_date)."""
    row = {
        "uuid": call.get("uuid", ""),
        "arrival_date": _arrival_date(call),
        "port": call.get("port", ""),
        "vessel_name": call.get("vessel_name", ""),
        "mmsi": _s(call.get("mmsi")),
        "imo": _s(call.get("imo")),
        "type_specific": call.get("type_specific", ""),
        "size_class": call.get("size_class", ""),
        "dwt": _s(call.get("dwt")),
        "gross_tonnage": _s(call.get("gross_tonnage")),
        "length_m": _s(call.get("length_m")),
        "breadth_m": _s(call.get("breadth_m")),
        "year_built": _s(call.get("year_built")),
        "arrival_utc": call.get("arrival_utc", ""),
        "departure_utc": call.get("departure_utc", ""),
        "days_in_port": _num(call.get("days_in_port")),
        "arrived_anchored": call.get("arrived_anchored", ""),
        "grain_flag": call.get("grain_flag", ""),
        "grain_confidence": call.get("grain_confidence", ""),
        # tolerate both the CSV key (_min_dist_nm) and a plain one.
        "min_dist_nm": _num(call.get("_min_dist_nm", call.get("min_dist_nm"))),
    }
    placeholders = ",".join("?" for _ in _CALL_COLS)
    conn.execute(
        f"INSERT OR REPLACE INTO port_calls ({','.join(_CALL_COLS)}, updated_at) "
        f"VALUES ({placeholders}, CURRENT_TIMESTAMP)",
        [row[c] for c in _CALL_COLS],
    )


def upsert_calls(conn: sqlite3.Connection, calls: Iterable[dict]) -> int:
    n = 0
    for c in calls:
        if not c.get("uuid"):
            continue
        upsert_call(conn, c)
        n += 1
    conn.commit()
    return n


def record_draught(conn: sqlite3.Connection, snap: dict) -> None:
    """Append a live draught snapshot (idempotent on (uuid, captured_at))."""
    cols = ["uuid", "captured_at", "port_key", "mmsi", "imo", "name",
            "draught_m", "nav_status", "speed_kn", "lat", "lon",
            "destination", "origin_port", "eta", "source"]
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT OR IGNORE INTO draught_snapshots ({','.join(cols)}) "
        f"VALUES ({placeholders})",
        [snap.get(c) for c in cols],
    )


def latest_arrival_date(conn: sqlite3.Connection,
                        port_label: Optional[str] = None) -> Optional[str]:
    """Most recent arrival_date on record — the anchor for ``--since-last``."""
    if port_label:
        cur = conn.execute(
            "SELECT MAX(arrival_date) FROM port_calls WHERE port = ?",
            (port_label,))
    else:
        cur = conn.execute("SELECT MAX(arrival_date) FROM port_calls")
    val = cur.fetchone()[0]
    return val or None


def known_call_keys(conn: sqlite3.Connection) -> set:
    """Set of (uuid, arrival_date) already stored — for cheap dedup."""
    return {(r["uuid"], r["arrival_date"])
            for r in conn.execute(
                "SELECT uuid, arrival_date FROM port_calls")}


def export_csv(conn: sqlite3.Connection, path: str = config.CSV_PATH) -> int:
    """Dump port_calls to the flat CSV the analysts already read."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT * FROM port_calls ORDER BY port, arrival_utc").fetchall()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=config.FIELDS)
        w.writeheader()
        for r in rows:
            d = dict(r)
            d["_min_dist_nm"] = d.pop("min_dist_nm", "")
            w.writerow({k: d.get(k, "") for k in config.FIELDS})
    return len(rows)


def _s(v) -> str:
    return "" if v is None else str(v)


def _num(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None
