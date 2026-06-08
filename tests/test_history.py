"""Offline unit tests for the Signal Memory (history) layer.

No network, no ccxt. Covers fingerprint/dedup, immutable snapshots, bullish &
bearish outcomes, MFE/MAE, pending horizons, closed-vs-unclosed candles,
outcome labels, matched/failed reasons, SQLite insert/upsert, CSV export, HTML
generation, offline/live DB separation, division-by-zero and missing-data
guards, and timezone-aware timestamps.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from typing import List

from app.config import AppConfig
from app.history.evaluator import evaluate_outcome, lifecycle_status
from app.history.matcher import build_snapshot, compute_fingerprint, should_save
from app.history.models import (
    DIRECTION_BEARISH,
    DIRECTION_BULLISH,
    HORIZONS,
    LABEL_EXPIRED,
    LABEL_INVALIDATED,
    LABEL_MATCH,
    LABEL_PENDING,
    LABEL_STRONG_MATCH,
    STATUS_NEW,
    SignalSnapshot,
)
from app.history.report import export_history_csv, generate_history_report
from app.history.repository import SignalRepository
from app.history.statistics import build_statistics
from app.models import Candle, ScreenerResult
from app.signals import build_signal_context, enrich_with_quality

UTC = timezone.utc


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _dt(minutes_ago: int = 0) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes_ago)


def _candles_path(
    *,
    start_ts: int,
    minutes: int,
    start_price: float,
    end_price: float,
    high_pad: float = 0.001,
    low_pad: float = 0.001,
) -> List[Candle]:
    """Build `minutes` 1-minute candles linearly from start_price to end_price."""
    out: List[Candle] = []
    for i in range(minutes):
        frac = (i + 1) / minutes
        close = start_price + (end_price - start_price) * frac
        prev = start_price + (end_price - start_price) * (i / minutes)
        hi = max(prev, close) * (1 + high_pad)
        lo = min(prev, close) * (1 - low_pad)
        out.append(Candle(
            open_time=start_ts + (i + 1) * 60,
            open=prev, high=hi, low=lo, close=close, volume=1000.0,
        ))
    return out


def _snapshot(
    *,
    direction: str = DIRECTION_BULLISH,
    price: float = 100.0,
    candle_ts: datetime,
    reasons=None,
) -> SignalSnapshot:
    return SignalSnapshot(
        id="sig-" + direction[:4].lower() + "-" + str(int(candle_ts.timestamp())),
        symbol="BTC/USDT:USDT",
        exchange="BINANCE",
        detected_at=candle_ts,
        candle_timestamp=candle_ts,
        price_at_signal=price,
        score=80.0,
        quality_score=72.0,
        direction_hint=direction,
        confidence="HIGH",
        signals=["momentum_move", "volume_spike"],
        main_reasons=reasons or [
            "RVOL is 3.0x above normal",
            "OI confirms fresh longs",
            "Trend is aligned across 5m/15m/1h",
        ],
        risk_notes=[],
        tradingview_symbol="BINANCE:BTCUSDT.P",
        tradingview_url="https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT.P",
        status=STATUS_NEW,
    )


# --------------------------------------------------------------------------- #
# fingerprint & dedup
# --------------------------------------------------------------------------- #

class TestFingerprint(unittest.TestCase):
    def test_same_inputs_same_fingerprint(self):
        ts = _dt(0)
        a = compute_fingerprint("BTC/USDT:USDT", "BULLISH_MOMENTUM", ["b", "a"], ts)
        b = compute_fingerprint("BTC/USDT:USDT", "BULLISH_MOMENTUM", ["a", "b"], ts)
        self.assertEqual(a, b)  # signal order must not matter

    def test_different_direction_changes_fingerprint(self):
        ts = _dt(0)
        a = compute_fingerprint("BTC/USDT:USDT", "BULLISH_MOMENTUM", ["a"], ts)
        b = compute_fingerprint("BTC/USDT:USDT", "BEARISH_MOMENTUM", ["a"], ts)
        self.assertNotEqual(a, b)


class TestShouldSave(unittest.TestCase):
    def test_below_thresholds_rejected(self):
        snap = _snapshot(candle_ts=_dt(0))
        low = snap  # score 80 / quality 72
        ok, _ = should_save(low, recent_snapshots=[], cooldown_minutes=60,
                            min_score=90, min_quality=50)
        self.assertFalse(ok)

    def test_duplicate_within_cooldown_rejected(self):
        ts = _dt(5)
        prev = _snapshot(candle_ts=ts)
        new = _snapshot(candle_ts=_dt(0))
        ok, reason = should_save(new, recent_snapshots=[prev], cooldown_minutes=60,
                                min_score=60, min_quality=50)
        self.assertFalse(ok)
        self.assertIn("cooldown", reason)

    def test_changed_direction_allowed_within_cooldown(self):
        prev = _snapshot(direction=DIRECTION_BULLISH, candle_ts=_dt(5))
        new = _snapshot(direction=DIRECTION_BEARISH, candle_ts=_dt(0))
        ok, _ = should_save(new, recent_snapshots=[prev], cooldown_minutes=60,
                            min_score=60, min_quality=50)
        self.assertTrue(ok)


# --------------------------------------------------------------------------- #
# immutable snapshot from real ScreenerResult
# --------------------------------------------------------------------------- #

class TestBuildSnapshot(unittest.TestCase):
    def test_snapshot_is_immutable_except_status(self):
        result = ScreenerResult(
            symbol="ETH/USDT:USDT", price=2000.0,
            change_5m=0.5, change_15m=0.7, change_1h=2.0,
            volume_current=100.0, volume_avg=100.0, relative_volume=3.0,
            volume_z=2.0, atr=20.0, vol_expansion=1.2,
            open_interest=1_000.0, oi_change=2.0, funding_rate=0.0,
            derivatives_score=60.0, score=78.0,
        )
        result = enrich_with_quality(result, funding_threshold=0.0003)
        ctx = build_signal_context(result)
        ts = _dt(0)
        snap = build_snapshot(result, ctx, exchange="BINANCE", candle_timestamp=ts)
        self.assertEqual(snap.symbol, "ETH/USDT:USDT")
        self.assertEqual(snap.status, STATUS_NEW)
        # frozen dataclass -> cannot mutate
        with self.assertRaises(Exception):
            snap.price_at_signal = 1.0  # type: ignore[misc]
        # status change yields a new object, original untouched
        updated = snap.with_status("TRACKING")
        self.assertEqual(snap.status, STATUS_NEW)
        self.assertEqual(updated.status, "TRACKING")


# --------------------------------------------------------------------------- #
# outcome evaluation
# --------------------------------------------------------------------------- #

class TestEvaluateOutcome(unittest.TestCase):
    def test_bullish_strong_match(self):
        signal_ts = _dt(120)  # 2h ago
        snap = _snapshot(direction=DIRECTION_BULLISH, price=100.0, candle_ts=signal_ts)
        start_ts = int(signal_ts.timestamp())
        candles = _candles_path(start_ts=start_ts, minutes=120,
                                start_price=100.0, end_price=103.0,
                                high_pad=0.0005, low_pad=0.0002)
        now = signal_ts + timedelta(minutes=125)
        out = evaluate_outcome(snap, "1h", candles, now=now)
        self.assertGreater(out.return_pct, 0)
        self.assertTrue(out.direction_matched)
        self.assertTrue(out.threshold_matched)
        self.assertIn(out.outcome_label, (LABEL_STRONG_MATCH, LABEL_MATCH))
        self.assertGreater(out.max_favorable_excursion_pct, 0)
        self.assertGreaterEqual(out.max_adverse_excursion_pct, -1.0)
        self.assertTrue(out.matched_reasons)

    def test_bearish_match_directional_return_positive(self):
        signal_ts = _dt(120)
        snap = _snapshot(
            direction=DIRECTION_BEARISH, price=100.0, candle_ts=signal_ts,
            reasons=["OI confirms fresh shorts", "Trend is aligned across 5m/15m/1h"],
        )
        start_ts = int(signal_ts.timestamp())
        candles = _candles_path(start_ts=start_ts, minutes=120,
                                start_price=100.0, end_price=97.0,
                                high_pad=0.0002, low_pad=0.0005)
        now = signal_ts + timedelta(minutes=125)
        out = evaluate_outcome(snap, "1h", candles, now=now)
        self.assertLess(out.return_pct, 0)
        # directional return must be positive for a correct bearish call
        self.assertGreater(out.directional_return_pct, 0)
        self.assertTrue(out.direction_matched)
        self.assertGreater(out.max_favorable_excursion_pct, 0)

    def test_invalidated_when_wrong_direction(self):
        signal_ts = _dt(120)
        snap = _snapshot(direction=DIRECTION_BULLISH, price=100.0, candle_ts=signal_ts)
        start_ts = int(signal_ts.timestamp())
        # bullish call, price falls hard -> invalidated at 1h
        candles = _candles_path(start_ts=start_ts, minutes=120,
                                start_price=100.0, end_price=96.0,
                                high_pad=0.0002, low_pad=0.0005)
        now = signal_ts + timedelta(minutes=125)
        out = evaluate_outcome(snap, "1h", candles, now=now)
        self.assertFalse(out.direction_matched)
        self.assertEqual(out.outcome_label, LABEL_INVALIDATED)
        self.assertTrue(out.failed_reasons)

    def test_pending_when_horizon_not_reached(self):
        signal_ts = _dt(5)  # only 5 minutes ago
        snap = _snapshot(price=100.0, candle_ts=signal_ts)
        out = evaluate_outcome(snap, "1h", [], now=datetime.now(UTC))
        self.assertEqual(out.outcome_label, LABEL_PENDING)
        self.assertIsNone(out.return_pct)

    def test_expired_when_no_data_long_after_target(self):
        signal_ts = _dt(60 * 24 * 3)  # 3 days ago
        snap = _snapshot(price=100.0, candle_ts=signal_ts)
        out = evaluate_outcome(snap, "1h", [], now=datetime.now(UTC))
        self.assertEqual(out.outcome_label, LABEL_EXPIRED)

    def test_unclosed_candle_is_ignored(self):
        signal_ts = _dt(20)
        snap = _snapshot(price=100.0, candle_ts=signal_ts)
        start_ts = int(signal_ts.timestamp())
        # one candle whose close is in the future relative to now
        future_open = int((datetime.now(UTC) + timedelta(minutes=2)).timestamp())
        candles = [Candle(open_time=future_open, open=100, high=110, low=100,
                          close=110, volume=1.0)]
        out = evaluate_outcome(snap, "15m", candles, now=datetime.now(UTC))
        # target (15m) has passed but the only candle is unclosed -> not used
        self.assertIsNone(out.price_at_horizon)

    def test_division_by_zero_guard(self):
        signal_ts = _dt(120)
        snap = _snapshot(price=0.0, candle_ts=signal_ts)
        start_ts = int(signal_ts.timestamp())
        candles = _candles_path(start_ts=start_ts, minutes=70,
                                start_price=1.0, end_price=2.0)
        now = signal_ts + timedelta(minutes=125)
        out = evaluate_outcome(snap, "1h", candles, now=now)
        self.assertEqual(out.outcome_label, "NOT_APPLICABLE")

    def test_timestamps_are_timezone_aware(self):
        signal_ts = _dt(120)
        snap = _snapshot(price=100.0, candle_ts=signal_ts)
        start_ts = int(signal_ts.timestamp())
        candles = _candles_path(start_ts=start_ts, minutes=70,
                                start_price=100.0, end_price=101.5)
        now = signal_ts + timedelta(minutes=125)
        out = evaluate_outcome(snap, "1h", candles, now=now)
        self.assertIsNotNone(out.evaluated_at.tzinfo)
        self.assertIsNotNone(out.target_timestamp.tzinfo)


class TestLifecycle(unittest.TestCase):
    def test_all_pending_is_tracking(self):
        signal_ts = _dt(1)
        snap = _snapshot(candle_ts=signal_ts)
        outs = [evaluate_outcome(snap, hz, [], now=datetime.now(UTC)) for hz in HORIZONS]
        self.assertEqual(lifecycle_status(outs), "TRACKING")


# --------------------------------------------------------------------------- #
# repository (SQLite)
# --------------------------------------------------------------------------- #

class TestRepository(unittest.TestCase):
    def test_insert_and_dedup(self):
        import dataclasses
        with SignalRepository(":memory:") as repo:
            snap = _snapshot(candle_ts=_dt(0))
            self.assertTrue(repo.insert_snapshot(snap))
            # Different id but identical fingerprint inputs -> UNIQUE(fingerprint)
            # rejects it, proving de-dup is by fingerprint, not primary key.
            dup = dataclasses.replace(snap, id="different-id")
            self.assertFalse(repo.insert_snapshot(dup))
            self.assertEqual(repo.count_snapshots(), 1)

    def test_outcome_upsert_is_idempotent(self):
        with SignalRepository(":memory:") as repo:
            signal_ts = _dt(120)
            snap = _snapshot(candle_ts=signal_ts)
            repo.insert_snapshot(snap)
            start_ts = int(signal_ts.timestamp())
            candles = _candles_path(start_ts=start_ts, minutes=70,
                                    start_price=100.0, end_price=102.0)
            now = signal_ts + timedelta(minutes=125)
            out = evaluate_outcome(snap, "1h", candles, now=now)
            repo.upsert_outcome(out)
            repo.upsert_outcome(out)  # second time must not duplicate
            stored = repo.get_outcomes_for_signal(snap.id)
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0].horizon, "1h")

    def test_status_update_and_open_query(self):
        with SignalRepository(":memory:") as repo:
            snap = _snapshot(candle_ts=_dt(0))
            repo.insert_snapshot(snap)
            self.assertEqual(len(repo.get_open_snapshots()), 1)
            repo.update_status(snap.id, "COMPLETED")
            self.assertEqual(len(repo.get_open_snapshots()), 0)


# --------------------------------------------------------------------------- #
# exports
# --------------------------------------------------------------------------- #

class TestExports(unittest.TestCase):
    def _populate(self, repo: SignalRepository):
        signal_ts = _dt(120)
        snap = _snapshot(candle_ts=signal_ts)
        repo.insert_snapshot(snap)
        start_ts = int(signal_ts.timestamp())
        candles = _candles_path(start_ts=start_ts, minutes=120,
                                start_price=100.0, end_price=103.0)
        now = signal_ts + timedelta(minutes=125)
        for hz in HORIZONS:
            repo.upsert_outcome(evaluate_outcome(snap, hz, candles, now=now))
        return snap

    def test_csv_export(self):
        with tempfile.TemporaryDirectory() as d:
            with SignalRepository(":memory:") as repo:
                self._populate(repo)
                snaps = repo.get_all_snapshots()
                outs = repo.get_all_outcomes()
            path = os.path.join(d, "history.csv")
            export_history_csv(snaps, outs, output_path=path)
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("signal_id", content)
            self.assertIn("BTC/USDT:USDT", content)
            # one header + 4 horizon rows
            self.assertEqual(content.strip().count("\n"), 4)

    def test_html_report(self):
        with tempfile.TemporaryDirectory() as d:
            with SignalRepository(":memory:") as repo:
                self._populate(repo)
                snaps = repo.get_all_snapshots()
                outs = repo.get_all_outcomes()
            stats = build_statistics(snaps, outs, min_sample=10)
            path = os.path.join(d, "report.html")
            generate_history_report(snaps, outs, stats, output_path=path)
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("Signal Memory", content)
            self.assertIn("BTC/USDT:USDT", content)
            self.assertIn("Open TradingView", content)

    def test_html_report_empty_state(self):
        with tempfile.TemporaryDirectory() as d:
            stats = build_statistics([], [], min_sample=10)
            path = os.path.join(d, "empty.html")
            generate_history_report([], [], stats, output_path=path)
            with open(path, encoding="utf-8") as fh:
                self.assertIn("No signals recorded yet", fh.read())


# --------------------------------------------------------------------------- #
# statistics + offline/live separation
# --------------------------------------------------------------------------- #

class TestStatistics(unittest.TestCase):
    def test_insufficient_sample_flagged(self):
        signal_ts = _dt(120)
        snap = _snapshot(candle_ts=signal_ts)
        start_ts = int(signal_ts.timestamp())
        candles = _candles_path(start_ts=start_ts, minutes=120,
                                start_price=100.0, end_price=103.0)
        now = signal_ts + timedelta(minutes=125)
        outs = [evaluate_outcome(snap, hz, candles, now=now) for hz in HORIZONS]
        stats = build_statistics([snap], outs, min_sample=10)
        self.assertEqual(stats.total_signals, 1)
        # a single signal is below the min sample of 10
        self.assertTrue(stats.by_horizon["1h"].insufficient)


class TestOfflineLiveSeparation(unittest.TestCase):
    def test_offline_paths_are_distinct(self):
        cfg = AppConfig.from_env()
        db, report, csv_path = cfg.offline_history_paths()
        self.assertNotEqual(db, cfg.signal_history_db_path)
        self.assertIn("_offline", db)
        self.assertIn("_offline", report)
        self.assertIn("_offline", csv_path)


if __name__ == "__main__":
    unittest.main()
