"""CLI entry-point for crypto_screener.

Usage:
    python -m app.main --offline-test   # synthetic data, no ccxt, no network
    python -m app.main --live           # real Binance USDM data via ccxt

If `--live` is requested but ccxt is missing, we print a friendly error message
and exit with a non-zero status, **without** a traceback.

After the top table is printed, the CLI also (by default) writes a
self-contained TradingView HTML report to
`data/processed/tradingview_report.html` and prints the file path. Disable
via `GENERATE_TRADINGVIEW_REPORT=false` in `.env`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Sequence

from app.config import AppConfig
from app.models import MarketScanInput, ScreenerRow
from app.output import (
    render_compact_view,
    render_signal_context_block,
    render_top_table,
)
from app.pipeline import run_pipeline
from app.signals import build_signal_context


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.main",
        description="Binance USDM perpetual futures screener (MVP).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live",         action="store_true",
                      help="Run against real Binance USDM. Requires ccxt installed.")
    mode.add_argument("--offline-test", action="store_true",
                      help="Run on synthetic sample data. No ccxt, no network.")
    parser.add_argument("--top", type=int, default=None,
                        help="Number of rows to display (overrides SCREENER_TOP_N).")
    parser.add_argument("--no-report", action="store_true",
                        help="Skip writing the TradingView HTML report.")
    parser.add_argument("--compact", action="store_true",
                        help="Also print the single-line compact view.")
    return parser.parse_args(argv)


def _setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def _maybe_write_report(
    rows: List[ScreenerRow],
    *,
    config: AppConfig,
    top: int,
    enabled: bool,
) -> None:
    """Write the HTML TradingView report unless disabled."""
    if not enabled or not config.generate_tradingview_report:
        return
    # Local import — chart layer never touches metrics/scoring.
    from app.charts.tradingview import generate_tradingview_report

    sorted_rows = sorted(rows, key=lambda r: r.score, reverse=True)[:top]
    output_path = generate_tradingview_report(
        sorted_rows,
        output_path=config.tradingview_report_path,
        exchange_prefix=config.tradingview_exchange_prefix,
        interval=config.tradingview_interval,
        top=top,
        title="crypto_screener — TradingView report",
    )
    print(f"TradingView report: {output_path}")


def _print_signal_context(
    rows: List[ScreenerRow],
    *,
    config: AppConfig,
    top: int,
) -> None:
    """Build a SignalContext per top-N row and print the compact block."""
    sorted_rows = sorted(rows, key=lambda r: r.score, reverse=True)[:top]
    contexts = [
        build_signal_context(
            r,
            tradingview_exchange_prefix=config.tradingview_exchange_prefix,
        )
        for r in sorted_rows
    ]
    print()
    print(render_signal_context_block(contexts))


def _run_offline(config: AppConfig, top: int, *, write_report: bool, compact: bool) -> int:
    from app.data.sample_data import build_offline_inputs, list_scenarios

    print(f"# crypto_screener — offline-test mode (top {top})", file=sys.stderr)
    print("# Loaded scenarios:", file=sys.stderr)
    for scenario in list_scenarios():
        print(f"#  - {scenario.symbol:<22} {scenario.label}", file=sys.stderr)

    inputs: List[MarketScanInput] = build_offline_inputs()
    rows: List[ScreenerRow] = run_pipeline(
        inputs,
        funding_threshold=config.signal_funding_abs_threshold,
    )
    print(render_top_table(
        rows, top=top,
        title="Top movers (offline-test)",
        exchange_prefix=config.tradingview_exchange_prefix,
    ))
    if compact:
        print()
        print(render_compact_view(
            rows, top=top,
            title="Compact view (offline-test)",
            exchange_prefix=config.tradingview_exchange_prefix,
        ))
    _print_signal_context(rows, config=config, top=top)
    _maybe_write_report(rows, config=config, top=top, enabled=write_report)
    return 0


def _run_live(config: AppConfig, top: int, *, write_report: bool, compact: bool) -> int:
    from app.data.collector import collect_live_inputs
    from app.exchanges.binance import BinanceConfig, CcxtNotInstalledError

    binance_config = BinanceConfig(
        api_key=config.binance_api_key,
        api_secret=config.binance_api_secret,
    )

    try:
        inputs = collect_live_inputs(
            universe_limit=config.universe_limit,
            candle_limit=config.candle_limit,
            config=binance_config,
        )
    except CcxtNotInstalledError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"error: live collection failed: {exc}", file=sys.stderr)
        return 1

    if not inputs:
        print("warning: collector returned no inputs", file=sys.stderr)

    rows: List[ScreenerRow] = run_pipeline(
        inputs,
        funding_threshold=config.signal_funding_abs_threshold,
    )
    print(render_top_table(
        rows, top=top,
        title="Top movers (live)",
        exchange_prefix=config.tradingview_exchange_prefix,
    ))
    if compact:
        print()
        print(render_compact_view(
            rows, top=top,
            title="Compact view (live)",
            exchange_prefix=config.tradingview_exchange_prefix,
        ))
    _print_signal_context(rows, config=config, top=top)
    _maybe_write_report(rows, config=config, top=top, enabled=write_report)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    config = AppConfig.from_env()
    _setup_logging(config.log_level)
    top = args.top if args.top is not None else config.top_n
    write_report = not args.no_report
    if args.offline_test:
        return _run_offline(config, top, write_report=write_report, compact=args.compact)
    return _run_live(config, top, write_report=write_report, compact=args.compact)


if __name__ == "__main__":
    raise SystemExit(main())
