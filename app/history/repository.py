"""SQLite persistence for snapshots and outcomes.

Thin data-access layer — it serialises/deserialises the history dataclasses to
the two tables defined in ``app.storage.migrations``. No business logic lives
here (de-dup decisions are the matcher's job; this layer only enforces the
``fingerprint`` UNIQUE constraint via ``INSERT OR IGNORE``).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Union

from app.history.matcher import compute_fingerprint
from app.history.models import (
    OPEN_STATUSES,
    SignalOutcome,
    SignalSnapshot,
)
from app.storage.migrations import connect, ensure_schema

# Metric fields stored together in ``metrics_json`` (no dedicated column).
_METRIC_FIELDS = (
    "change_5m",
    "change_15m",
    "change_1h",
    "relative_volume",
    "volume_z",
    "atr",
    "atr_percent",
    "price_move_atr",
    "vol_expansion",
    "open_interest",
    "oi_change_pct",
    "funding_rate",
    "derivatives_score",
    "trend_alignment",
    "oi_confirmation",
)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_bool(value: Optional[int]) -> Optional[bool]:
    if value is None:
        return None
    return bool(value)


def _from_bool(value: Optional[bool]) -> Optional[int]:
    if value is None:
        return None
    return 1 if value else 0


class SignalRepository:
    """Owns one SQLite connection. Use as a context manager or call ``close()``."""

    def __init__(self, db_path: Union[str, Path]) -> None:
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection = connect(self.db_path)
        ensure_schema(self._conn)

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def __enter__(self) -> "SignalRepository":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- snapshots -----------------------------------------------------------

    def insert_snapshot(self, snapshot: SignalSnapshot) -> bool:
        """Insert a snapshot. Returns True if a new row was written.

        De-dup is enforced by the ``fingerprint`` UNIQUE constraint: a repeated
        fingerprint is ignored and returns False.
        """
        fingerprint = compute_fingerprint(
            snapshot.symbol,
            snapshot.direction_hint,
            snapshot.signals,
            snapshot.candle_timestamp,
        )
        now_iso = _iso(datetime.now(timezone.utc))
        metrics = {f: getattr(snapshot, f) for f in _METRIC_FIELDS}
        cur = self._conn.execute(
            """
            INSERT OR IGNORE INTO signal_snapshots (
                id, fingerprint, symbol, exchange, detected_at, candle_timestamp,
                price_at_signal, score, quality_score, direction_hint, confidence,
                signals_json, reasons_json, risks_json, metrics_json,
                tradingview_symbol, tradingview_url, status, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                snapshot.id,
                fingerprint,
                snapshot.symbol,
                snapshot.exchange,
                _iso(snapshot.detected_at),
                _iso(snapshot.candle_timestamp),
                snapshot.price_at_signal,
                snapshot.score,
                snapshot.quality_score,
                snapshot.direction_hint,
                snapshot.confidence,
                json.dumps(snapshot.signals),
                json.dumps(snapshot.main_reasons),
                json.dumps(snapshot.risk_notes),
                json.dumps(metrics),
                snapshot.tradingview_symbol,
                snapshot.tradingview_url,
                snapshot.status,
                now_iso,
                now_iso,
            ),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def update_status(self, signal_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE signal_snapshots SET status = ?, updated_at = ? WHERE id = ?",
            (status, _iso(datetime.now(timezone.utc)), signal_id),
        )
        self._conn.commit()

    def get_snapshot(self, signal_id: str) -> Optional[SignalSnapshot]:
        row = self._conn.execute(
            "SELECT * FROM signal_snapshots WHERE id = ?", (signal_id,)
        ).fetchone()
        return self._row_to_snapshot(row) if row else None

    def get_open_snapshots(self) -> List[SignalSnapshot]:
        placeholders = ",".join("?" for _ in OPEN_STATUSES)
        rows = self._conn.execute(
            f"SELECT * FROM signal_snapshots WHERE status IN ({placeholders}) "
            "ORDER BY detected_at ASC",
            tuple(OPEN_STATUSES),
        ).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    def get_all_snapshots(self, *, limit: Optional[int] = None) -> List[SignalSnapshot]:
        sql = "SELECT * FROM signal_snapshots ORDER BY detected_at DESC"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        rows = self._conn.execute(sql).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    def recent_snapshots_for_symbol(
        self, symbol: str, *, since: datetime
    ) -> List[SignalSnapshot]:
        rows = self._conn.execute(
            "SELECT * FROM signal_snapshots WHERE symbol = ? AND detected_at >= ? "
            "ORDER BY detected_at DESC",
            (symbol, _iso(since)),
        ).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    def count_snapshots(self) -> int:
        return int(
            self._conn.execute("SELECT COUNT(*) AS n FROM signal_snapshots").fetchone()["n"]
        )

    def delete_snapshots_before(self, cutoff: datetime) -> int:
        """Retention helper — delete snapshots (and their outcomes) older than cutoff."""
        ids = [
            r["id"]
            for r in self._conn.execute(
                "SELECT id FROM signal_snapshots WHERE detected_at < ?", (_iso(cutoff),)
            ).fetchall()
        ]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        self._conn.execute(
            f"DELETE FROM signal_outcomes WHERE signal_id IN ({placeholders})", tuple(ids)
        )
        self._conn.execute(
            f"DELETE FROM signal_snapshots WHERE id IN ({placeholders})", tuple(ids)
        )
        self._conn.commit()
        return len(ids)

    # -- outcomes ------------------------------------------------------------

    def upsert_outcome(self, outcome: SignalOutcome) -> None:
        """Insert or replace the outcome for a (signal_id, horizon) pair."""
        self._conn.execute(
            """
            INSERT INTO signal_outcomes (
                signal_id, horizon, evaluated_at, target_timestamp,
                price_at_signal, price_at_horizon, return_pct, directional_return_pct,
                mfe_pct, mae_pct, high_after_signal, low_after_signal,
                direction_matched, threshold_matched, context_matched,
                outcome_label, matched_reasons_json, failed_reasons_json, notes_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(signal_id, horizon) DO UPDATE SET
                evaluated_at = excluded.evaluated_at,
                target_timestamp = excluded.target_timestamp,
                price_at_signal = excluded.price_at_signal,
                price_at_horizon = excluded.price_at_horizon,
                return_pct = excluded.return_pct,
                directional_return_pct = excluded.directional_return_pct,
                mfe_pct = excluded.mfe_pct,
                mae_pct = excluded.mae_pct,
                high_after_signal = excluded.high_after_signal,
                low_after_signal = excluded.low_after_signal,
                direction_matched = excluded.direction_matched,
                threshold_matched = excluded.threshold_matched,
                context_matched = excluded.context_matched,
                outcome_label = excluded.outcome_label,
                matched_reasons_json = excluded.matched_reasons_json,
                failed_reasons_json = excluded.failed_reasons_json,
                notes_json = excluded.notes_json
            """,
            (
                outcome.signal_id,
                outcome.horizon,
                _iso(outcome.evaluated_at),
                _iso(outcome.target_timestamp),
                outcome.price_at_signal,
                outcome.price_at_horizon,
                outcome.return_pct,
                outcome.directional_return_pct,
                outcome.max_favorable_excursion_pct,
                outcome.max_adverse_excursion_pct,
                outcome.high_after_signal,
                outcome.low_after_signal,
                _from_bool(outcome.direction_matched),
                _from_bool(outcome.threshold_matched),
                _from_bool(outcome.context_matched),
                outcome.outcome_label,
                json.dumps(outcome.matched_reasons),
                json.dumps(outcome.failed_reasons),
                json.dumps(outcome.notes),
            ),
        )
        self._conn.commit()

    def get_outcomes_for_signal(self, signal_id: str) -> List[SignalOutcome]:
        rows = self._conn.execute(
            "SELECT * FROM signal_outcomes WHERE signal_id = ? ORDER BY target_timestamp ASC",
            (signal_id,),
        ).fetchall()
        return [self._row_to_outcome(r) for r in rows]

    def get_all_outcomes(self) -> List[SignalOutcome]:
        rows = self._conn.execute(
            "SELECT * FROM signal_outcomes ORDER BY signal_id, target_timestamp"
        ).fetchall()
        return [self._row_to_outcome(r) for r in rows]

    # -- row mapping ---------------------------------------------------------

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> SignalSnapshot:
        metrics = json.loads(row["metrics_json"]) if row["metrics_json"] else {}
        return SignalSnapshot(
            id=row["id"],
            symbol=row["symbol"],
            exchange=row["exchange"],
            detected_at=_parse_dt(row["detected_at"]),
            candle_timestamp=_parse_dt(row["candle_timestamp"]),
            price_at_signal=row["price_at_signal"],
            score=row["score"],
            quality_score=row["quality_score"],
            direction_hint=row["direction_hint"],
            confidence=row["confidence"],
            signals=json.loads(row["signals_json"]) if row["signals_json"] else [],
            main_reasons=json.loads(row["reasons_json"]) if row["reasons_json"] else [],
            risk_notes=json.loads(row["risks_json"]) if row["risks_json"] else [],
            change_5m=metrics.get("change_5m"),
            change_15m=metrics.get("change_15m"),
            change_1h=metrics.get("change_1h"),
            relative_volume=metrics.get("relative_volume"),
            volume_z=metrics.get("volume_z"),
            atr=metrics.get("atr"),
            atr_percent=metrics.get("atr_percent"),
            price_move_atr=metrics.get("price_move_atr"),
            vol_expansion=metrics.get("vol_expansion"),
            open_interest=metrics.get("open_interest"),
            oi_change_pct=metrics.get("oi_change_pct"),
            funding_rate=metrics.get("funding_rate"),
            derivatives_score=metrics.get("derivatives_score"),
            trend_alignment=metrics.get("trend_alignment", "INSUFFICIENT_DATA"),
            oi_confirmation=metrics.get("oi_confirmation", "INSUFFICIENT_DATA"),
            tradingview_symbol=row["tradingview_symbol"],
            tradingview_url=row["tradingview_url"],
            status=row["status"],
        )

    @staticmethod
    def _row_to_outcome(row: sqlite3.Row) -> SignalOutcome:
        return SignalOutcome(
            signal_id=row["signal_id"],
            horizon=row["horizon"],
            evaluated_at=_parse_dt(row["evaluated_at"]),
            target_timestamp=_parse_dt(row["target_timestamp"]),
            price_at_signal=row["price_at_signal"],
            price_at_horizon=row["price_at_horizon"],
            return_pct=row["return_pct"],
            directional_return_pct=row["directional_return_pct"],
            max_favorable_excursion_pct=row["mfe_pct"],
            max_adverse_excursion_pct=row["mae_pct"],
            high_after_signal=row["high_after_signal"],
            low_after_signal=row["low_after_signal"],
            direction_matched=_to_bool(row["direction_matched"]),
            threshold_matched=_to_bool(row["threshold_matched"]),
            context_matched=_to_bool(row["context_matched"]),
            outcome_label=row["outcome_label"],
            matched_reasons=json.loads(row["matched_reasons_json"]) if row["matched_reasons_json"] else [],
            failed_reasons=json.loads(row["failed_reasons_json"]) if row["failed_reasons_json"] else [],
            notes=json.loads(row["notes_json"]) if row["notes_json"] else [],
        )
