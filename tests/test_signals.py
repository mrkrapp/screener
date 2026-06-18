"""Offline smoke tests for the signal-quality layer.

No network, no ccxt — just the metric functions, the detector and the
context builder.
"""

from __future__ import annotations

import math
import unittest

from app.charts.tradingview import convert_symbol_to_tradingview
from app.metrics import quality as q
from app.models import ScreenerResult, ScreenerRow
from app.signals import build_signal_context, enrich_with_quality
from app.signals.context import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    DIR_BEARISH_MOMENTUM,
    DIR_BULLISH_MOMENTUM,
    DIR_NEUTRAL,
    DIR_VOLUME_ONLY,
)
from app.scoring.score import compute_score


def _row(**overrides) -> ScreenerRow:
    """Build a baseline ScreenerRow with sane defaults for tests."""
    base = dict(
        symbol="BTC/USDT:USDT",
        price=30_000.0,
        change_5m=0.0,
        change_15m=0.0,
        change_1h=0.0,
        volume_current=100.0,
        volume_avg=100.0,
        relative_volume=1.0,
        volume_z=0.0,
        atr=300.0,
        vol_expansion=1.0,
        open_interest=1_000_000.0,
        oi_change=0.0,
        funding_rate=0.0,           # percent — 0.01 means 0.01%
        derivatives_score=50.0,
        score=50.0,
    )
    base.update(overrides)
    return ScreenerRow(**base)


class TestQualityMetrics(unittest.TestCase):
    """Each metric in `app.metrics.quality` must behave per spec."""

    def test_atr_percent_basic(self):
        self.assertAlmostEqual(q.atr_percent(300, 30_000), 1.0)
        self.assertIsNone(q.atr_percent(None, 30_000))
        self.assertIsNone(q.atr_percent(300, 0))

    def test_price_move_in_atr(self):
        # 2% move on 1% ATR == 2x ATR
        self.assertAlmostEqual(q.price_move_in_atr(2.0, 1.0), 2.0)
        # sign should be discarded
        self.assertAlmostEqual(q.price_move_in_atr(-2.0, 1.0), 2.0)
        self.assertIsNone(q.price_move_in_atr(None, 1.0))
        self.assertIsNone(q.price_move_in_atr(2.0, 0))

    def test_dollar_volume(self):
        self.assertAlmostEqual(q.dollar_volume(100.0, 10.0), 1000.0)
        self.assertIsNone(q.dollar_volume(None, 10.0))

    def test_volume_confirmation_combines_rvol_and_move(self):
        self.assertAlmostEqual(q.volume_confirmation(3.0, -2.0), 6.0)
        self.assertIsNone(q.volume_confirmation(None, 1.0))

    def test_trend_alignment_labels(self):
        self.assertEqual(q.trend_alignment_label(0.5, 0.6, 1.0), q.TREND_BULLISH_ALIGNED)
        self.assertEqual(q.trend_alignment_label(-0.5, -0.6, -1.0), q.TREND_BEARISH_ALIGNED)
        self.assertEqual(q.trend_alignment_label(0.5, -0.2, 1.0), q.TREND_MIXED_ALIGNMENT)
        self.assertEqual(q.trend_alignment_label(None, -0.2, 1.0), q.TREND_INSUFFICIENT_DATA)

    def test_oi_confirmation_labels(self):
        self.assertEqual(q.oi_confirmation_label(2.0, 2.0), q.OI_FRESH_LONGS)
        self.assertEqual(q.oi_confirmation_label(-2.0, 2.0), q.OI_FRESH_SHORTS)
        self.assertEqual(q.oi_confirmation_label(2.0, -2.0), q.OI_SHORT_COVERING)
        self.assertEqual(q.oi_confirmation_label(-2.0, -2.0), q.OI_LONG_UNWIND)
        self.assertEqual(q.oi_confirmation_label(0.5, 0.5), q.OI_NO_CLEAR)
        self.assertEqual(q.oi_confirmation_label(None, 2.0), q.OI_INSUFFICIENT_DATA)

    def test_funding_pressure(self):
        self.assertAlmostEqual(q.funding_pressure(0.0006, 0.0003), 2.0)
        self.assertAlmostEqual(q.funding_pressure(-0.0006, 0.0003), 2.0)
        self.assertIsNone(q.funding_pressure(0.0006, 0))
        self.assertIsNone(q.funding_pressure(None, 0.0003))

    def test_quality_score_clean_aligned_bull(self):
        score = q.quality_score(
            trend_alignment=q.TREND_BULLISH_ALIGNED,
            volume_confirmation_value=6.0,
            price_move_atr=2.0,
            oi_confirmation=q.OI_FRESH_LONGS,
            funding_pressure_value=0.5,
            vol_expansion=1.2,
            relative_volume=2.0,
            change_1h=3.0,
        )
        # base 50 + 15 + 15 + 10 + 15 == 105 → clamped to 100
        self.assertEqual(score, 100.0)

    def test_quality_score_penalises_no_followthrough(self):
        score = q.quality_score(
            trend_alignment=q.TREND_INSUFFICIENT_DATA,
            volume_confirmation_value=0.0,
            price_move_atr=0.0,
            oi_confirmation=q.OI_INSUFFICIENT_DATA,
            funding_pressure_value=2.0,           # -10
            vol_expansion=3.0,                    # -10
            relative_volume=3.0,                  # -10 (with abs(change_1h)<1)
            change_1h=0.2,
        )
        self.assertEqual(score, 20.0)

    def test_quality_score_is_clamped(self):
        score = q.quality_score(
            trend_alignment=q.TREND_INSUFFICIENT_DATA,
            volume_confirmation_value=None,
            price_move_atr=None,
            oi_confirmation=q.OI_INSUFFICIENT_DATA,
            funding_pressure_value=100.0,
            vol_expansion=100.0,
            relative_volume=100.0,
            change_1h=0.0,
        )
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)


class TestEnrichWithQuality(unittest.TestCase):
    """`enrich_with_quality` must populate every quality field."""

    def test_enrich_populates_all_fields(self):
        row = _row(
            change_5m=0.6, change_15m=0.7, change_1h=2.0,
            relative_volume=3.0, atr=300.0,
            oi_change=2.0,
            funding_rate=0.06,    # percent → raw 0.0006
        )
        enriched = enrich_with_quality(row, funding_threshold=0.0003)
        # ATR% = 300 / 30000 * 100 == 1.0
        self.assertAlmostEqual(enriched.atr_percent, 1.0)
        # 2% move on 1% ATR
        self.assertAlmostEqual(enriched.price_move_atr, 2.0)
        # 30000 * 100
        self.assertAlmostEqual(enriched.dollar_volume_current, 3_000_000.0)
        self.assertAlmostEqual(enriched.dollar_volume_avg, 3_000_000.0)
        self.assertAlmostEqual(enriched.volume_confirmation, 6.0)
        self.assertEqual(enriched.trend_alignment, q.TREND_BULLISH_ALIGNED)
        self.assertEqual(enriched.oi_confirmation, q.OI_FRESH_LONGS)
        # 0.0006 / 0.0003 == 2.0
        self.assertAlmostEqual(enriched.funding_pressure, 2.0)
        self.assertGreater(enriched.quality_score, 50.0)


class TestBuildSignalContext(unittest.TestCase):
    """`build_signal_context` should produce a usable SignalContext."""

    def test_bullish_momentum_path(self):
        row = enrich_with_quality(
            _row(
                change_5m=0.6, change_15m=0.7, change_1h=3.0,
                relative_volume=3.0, atr=300.0, oi_change=2.0,
                funding_rate=0.0,
                score=80.0,
            ),
            funding_threshold=0.0003,
        )
        ctx = build_signal_context(row)
        self.assertEqual(ctx.direction_hint, DIR_BULLISH_MOMENTUM)
        self.assertIn(ctx.confidence, (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM))
        self.assertTrue(ctx.main_reasons, "expected non-empty main_reasons")
        # Compact summary contains symbol, direction, score, quality, confidence
        for needle in (row.symbol, DIR_BULLISH_MOMENTUM, "Score", "Quality", ctx.confidence):
            self.assertIn(needle, ctx.compact_summary)

    def test_bearish_momentum_path(self):
        row = enrich_with_quality(
            _row(
                change_5m=-0.6, change_15m=-0.7, change_1h=-3.0,
                relative_volume=3.0, atr=300.0, oi_change=2.0,
                funding_rate=0.0,
                score=70.0,
            ),
            funding_threshold=0.0003,
        )
        ctx = build_signal_context(row)
        self.assertEqual(ctx.direction_hint, DIR_BEARISH_MOMENTUM)
        self.assertIn(DIR_BEARISH_MOMENTUM, ctx.compact_summary)

    def test_volume_only_path(self):
        row = enrich_with_quality(
            _row(
                change_5m=0.1, change_15m=0.1, change_1h=0.2,
                relative_volume=3.5, atr=300.0, oi_change=0.0,
                funding_rate=0.0,
                score=55.0,
            ),
            funding_threshold=0.0003,
        )
        ctx = build_signal_context(row)
        self.assertEqual(ctx.direction_hint, DIR_VOLUME_ONLY)

    def test_neutral_when_nothing_is_strong(self):
        row = enrich_with_quality(
            _row(score=20.0),
            funding_threshold=0.0003,
        )
        ctx = build_signal_context(row)
        self.assertEqual(ctx.direction_hint, DIR_NEUTRAL)
        self.assertEqual(ctx.confidence, CONFIDENCE_LOW)

    def test_compact_summary_contains_expected_parts(self):
        row = enrich_with_quality(
            _row(
                change_5m=0.6, change_15m=0.7, change_1h=3.0,
                relative_volume=3.0, atr=300.0, oi_change=2.0,
                score=72.0,
            ),
            funding_threshold=0.0003,
        )
        ctx = build_signal_context(row)
        # Pipe-separated layout
        parts = [p.strip() for p in ctx.compact_summary.split("|")]
        self.assertGreaterEqual(len(parts), 5)
        self.assertEqual(parts[0], row.symbol)
        self.assertTrue(parts[2].startswith("Score "))
        self.assertTrue(parts[3].startswith("Quality "))

    def test_tradingview_symbol_format(self):
        row = enrich_with_quality(_row(), funding_threshold=0.0003)
        ctx = build_signal_context(row, tradingview_exchange_prefix="BINANCE")
        # Direct helper sanity check.
        self.assertEqual(
            convert_symbol_to_tradingview("BTC/USDT:USDT", "BINANCE"),
            "BINANCE:BTCUSDT.P",
        )
        self.assertEqual(ctx.tradingview_symbol, "BINANCE:BTCUSDT.P")
        self.assertIn("BINANCE", ctx.tradingview_url)
        self.assertIn("BTCUSDT.P", ctx.tradingview_url)


class TestScreenerResultAlias(unittest.TestCase):
    def test_screener_result_is_alias_of_screener_row(self):
        self.assertIs(ScreenerResult, ScreenerRow)


class TestPartialDerivativesScoring(unittest.TestCase):
    def test_missing_derivatives_are_not_treated_as_zero_score(self):
        row = _row(
            change_1h=2.0,
            relative_volume=2.0,
            vol_expansion=1.5,
            volume_z=1.0,
            derivatives_score=None,
        )
        raw_available = 6.0 + 10.0 + 7.5 + 4.0
        self.assertAlmostEqual(compute_score(row), raw_available * 110.0 / 85.0)


if __name__ == "__main__":
    unittest.main()
