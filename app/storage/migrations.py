"""SQLite schema management for the signal-history store.

Standard-library ``sqlite3`` only — no SQLAlchemy at this stage. The schema is
created idempotently with ``CREATE TABLE IF NOT EXISTS`` so opening an existing
database is a no-op and a fresh path is initialised on first use.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

_SCHEMA_VERSION = 1

_CREATE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS signal_snapshots (
    id                 TEXT PRIMARY KEY,
    fingerprint        TEXT UNIQUE,
    symbol             TEXT NOT NULL,
    exchange           TEXT NOT NULL,
    detected_at        TEXT NOT NULL,
    candle_timestamp   TEXT NOT NULL,
    price_at_signal    REAL NOT NULL,
    score              REAL NOT NULL,
    quality_score      REAL NOT NULL,
    direction_hint     TEXT NOT NULL,
    confidence         TEXT NOT NULL,
    signals_json       TEXT NOT NULL,
    reasons_json       TEXT NOT NULL,
    risks_json         TEXT NOT NULL,
    metrics_json       TEXT NOT NULL,
    tradingview_symbol TEXT NOT NULL,
    tradingview_url    TEXT NOT NULL,
    status             TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
"""

_CREATE_OUTCOMES = """
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id            TEXT NOT NULL,
    horizon              TEXT NOT NULL,
    evaluated_at         TEXT NOT NULL,
    target_timestamp     TEXT NOT NULL,
    price_at_signal      REAL,
    price_at_horizon     REAL,
    return_pct           REAL,
    directional_return_pct REAL,
    mfe_pct              REAL,
    mae_pct              REAL,
    high_after_signal    REAL,
    low_after_signal     REAL,
    direction_matched    INTEGER,
    threshold_matched    INTEGER,
    context_matched      INTEGER,
    outcome_label        TEXT NOT NULL,
    matched_reasons_json TEXT NOT NULL,
    failed_reasons_json  TEXT NOT NULL,
    notes_json           TEXT NOT NULL,
    UNIQUE(signal_id, horizon),
    FOREIGN KEY(signal_id) REFERENCES signal_snapshots(id)
);
"""

_CREATE_META = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_snap_symbol       ON signal_snapshots(symbol);",
    "CREATE INDEX IF NOT EXISTS idx_snap_detected_at  ON signal_snapshots(detected_at);",
    "CREATE INDEX IF NOT EXISTS idx_snap_direction    ON signal_snapshots(direction_hint);",
    "CREATE INDEX IF NOT EXISTS idx_snap_status       ON signal_snapshots(status);",
    "CREATE INDEX IF NOT EXISTS idx_out_label         ON signal_outcomes(outcome_label);",
    "CREATE INDEX IF NOT EXISTS idx_out_signal_hz     ON signal_outcomes(signal_id, horizon);",
)


def connect(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open (creating parent dirs if needed) a SQLite database with sane pragmas.

    ``:memory:`` is passed through untouched so tests can use an in-memory DB.
    """
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables + indexes if they don't already exist. Idempotent."""
    cur = conn.cursor()
    cur.execute(_CREATE_SNAPSHOTS)
    cur.execute(_CREATE_OUTCOMES)
    cur.execute(_CREATE_META)
    for stmt in _INDEXES:
        cur.execute(stmt)
    cur.execute(
        "INSERT OR IGNORE INTO schema_meta(key, value) VALUES('schema_version', ?);",
        (str(_SCHEMA_VERSION),),
    )
    conn.commit()
