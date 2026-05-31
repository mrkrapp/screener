"""Tests for the TradingView chart module.

All tests run offline, with no third-party dependencies beyond stdlib.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.charts.tradingview import (
    convert_symbol_to_tradingview,
    generate_tradingview_report,
    tradingview_url,
)
from app.data.sample_data import build_offline_inputs
from app.models import ScreenerRow
from app.pipeline import run_pipeline


class SymbolConversionTest(unittest.TestCase):
    def test_ccxt_perp_to_tradingview(self) -> None:
        self.assertEqual(
            convert_symbol_to_tradingview("BTC/USDT:USDT"),
            "BINANCE:BTCUSDT.P",
        )
        self.assertEqual(
            convert_symbol_to_tradingview("ETH/USDT:USDT"),
            "BINANCE:ETHUSDT.P",
        )
        self.assertEqual(
            convert_symbol_to_tradingview("SOL/USDT:USDT"),
            "BINANCE:SOLUSDT.P",
        )

    def test_alternate_prefix(self) -> None:
        self.assertEqual(
            convert_symbol_to_tradingview("BTC/USDT:USDT", "BYBIT"),
            "BYBIT:BTCUSDT.P",
        )

    def test_spot_style_assumed_perp(self) -> None:
        self.assertEqual(convert_symbol_to_tradingview("BTC/USDT"), "BINANCE:BTCUSDT.P")
        self.assertEqual(convert_symbol_to_tradingview("BTCUSDT"), "BINANCE:BTCUSDT.P")

    def test_idempotent(self) -> None:
        self.assertEqual(
            convert_symbol_to_tradingview("BINANCE:BTCUSDT.P"),
            "BINANCE:BTCUSDT.P",
        )

    def test_empty(self) -> None:
        self.assertEqual(convert_symbol_to_tradingview(""), "")


class UrlTest(unittest.TestCase):
    def test_url_is_percent_encoded(self) -> None:
        url = tradingview_url("BTC/USDT:USDT")
        # Colon between BINANCE and BTCUSDT.P must be %3A in the query.
        self.assertEqual(
            url,
            "https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT.P",
        )

    def test_url_empty_when_symbol_empty(self) -> None:
        self.assertEqual(tradingview_url(""), "")


class ReportGenerationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = run_pipeline(build_offline_inputs())

    def test_generates_file_with_widgets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_tradingview_report(
                self.rows,
                output_path=os.path.join(tmp, "report.html"),
                top=5,
            )
            self.assertTrue(path.exists())
            content = path.read_text(encoding="utf-8")
            self.assertIn("crypto_screener", content)
            self.assertIn("tv.js", content)
            self.assertIn("TradingView.widget", content)
            self.assertIn("BINANCE:", content)
            self.assertIn("Open TradingView", content)

    def test_empty_rows_produces_empty_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_tradingview_report(
                [],
                output_path=os.path.join(tmp, "empty.html"),
                top=5,
            )
            self.assertTrue(path.exists())
            content = path.read_text(encoding="utf-8")
            # No widget script when there's nothing to chart.
            self.assertNotIn("TradingView.widget", content)
            self.assertIn("nothing to chart", content)

    def test_url_html_escaped(self) -> None:
        # Build a row whose symbol would contain HTML-special chars.
        row = ScreenerRow(
            symbol="WEIRD/USDT:USDT",
            price=1.0, change_5m=0, change_15m=0, change_1h=0,
            volume_current=0, volume_avg=0, relative_volume=0, volume_z=0,
            atr=0, vol_expansion=0,
            open_interest=0, oi_change=0, funding_rate=0,
            derivatives_score=0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_tradingview_report(
                [row],
                output_path=os.path.join(tmp, "weird.html"),
                top=1,
            )
            content = path.read_text(encoding="utf-8")
            # Should not contain unescaped angle brackets from the symbol slot.
            self.assertNotIn("<WEIRD", content)


class CliIntegrationTest(unittest.TestCase):
    """The CLI must (a) print the path when enabled and (b) skip when disabled."""

    def test_cli_writes_report_when_enabled(self) -> None:
        import io
        from contextlib import redirect_stdout, redirect_stderr
        from app.main import main

        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report.html")
            os.environ["TRADINGVIEW_REPORT_PATH"] = target
            os.environ["GENERATE_TRADINGVIEW_REPORT"] = "true"
            buf = io.StringIO()
            try:
                with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                    code = main(["--offline-test"])
            finally:
                del os.environ["TRADINGVIEW_REPORT_PATH"]
                del os.environ["GENERATE_TRADINGVIEW_REPORT"]
            self.assertEqual(code, 0)
            self.assertTrue(Path(target).exists())
            self.assertIn("TradingView report:", buf.getvalue())

    def test_cli_skips_report_when_disabled(self) -> None:
        import io
        from contextlib import redirect_stdout, redirect_stderr
        from app.main import main

        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report.html")
            os.environ["TRADINGVIEW_REPORT_PATH"] = target
            os.environ["GENERATE_TRADINGVIEW_REPORT"] = "false"
            buf = io.StringIO()
            try:
                with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                    code = main(["--offline-test"])
            finally:
                del os.environ["TRADINGVIEW_REPORT_PATH"]
                del os.environ["GENERATE_TRADINGVIEW_REPORT"]
            self.assertEqual(code, 0)
            self.assertFalse(Path(target).exists())
            self.assertNotIn("TradingView report:", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
