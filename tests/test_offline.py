"""Network-free smoke test.

Verifies:
    * sample_data builds without crashing
    * pipeline runs and yields one ScreenerRow per scenario
    * console renderer produces a non-empty string with the expected header
    * the CLI exits cleanly with --offline-test
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr

from app.data.sample_data import build_offline_inputs, assert_sane, list_scenarios
from app.output import render_top_table
from app.pipeline import run_pipeline


class OfflineSmokeTest(unittest.TestCase):
    def test_sample_data_is_sane(self) -> None:
        inputs = build_offline_inputs()
        assert_sane(inputs)
        self.assertEqual(len(inputs), len(list_scenarios()))

    def test_pipeline_produces_one_row_per_scenario(self) -> None:
        inputs = build_offline_inputs()
        rows = run_pipeline(inputs)
        self.assertEqual(len(rows), len(inputs))
        for r in rows:
            self.assertGreaterEqual(r.score, 0.0)
            self.assertLessEqual(r.score, 100.0)

    def test_render_top_table_contains_header(self) -> None:
        rows = run_pipeline(build_offline_inputs())
        rendered = render_top_table(rows, top=10)
        self.assertIn("symbol", rendered)
        self.assertIn("derivatives_score", rendered)
        self.assertIn("signals", rendered)

    def test_cli_offline_exits_zero(self) -> None:
        from app.main import main
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main(["--offline-test"])
        self.assertEqual(code, 0)
        self.assertIn("Top movers", buf_out.getvalue())

    def test_cli_live_without_ccxt_gives_friendly_message(self) -> None:
        """If ccxt is missing, --live must NOT raise — it must print a message."""
        try:
            import ccxt  # noqa: F401
            self.skipTest("ccxt is installed in this environment; nothing to test")
        except ImportError:
            pass
        from app.main import main
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main(["--live"])
        self.assertEqual(code, 2)
        self.assertIn("ccxt is required for live mode", buf_err.getvalue())


if __name__ == "__main__":
    unittest.main()
