"""CLI entry-point for crypto_screener.

Usage:
    python -m app.main --offline-test      # synthetic data, no ccxt, no network
    python -m app.main --live              # real Binance USDM data via ccxt
    python -m app.main --evaluate-history  # only evaluate pending history
    python -m app.main --history-report    # rebuild the HTML report from the DB
    python -m app.main --export-history    # rebuild the CSV export from the DB

If `--live` is requested but ccxt is missing, we print a friendly error message
and exit with a non-zero status, **without** a traceback.

After the top table, the CLI (by default) writes the TradingView HTML report
and runs the Signal Memory cycle (record new signals, evaluate pending ones,
rebuild the signal-history report + CSV). A history failure is logged but never
breaks the core screener output.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import Dict, List, Sequence, Tuple

from app.config import AppConfig
from app.models import MarketScanInput, ScreenerRow
from app.output import (
    render_compact_view,
    render_signal_context_block,
    render_top_table,
)
from app.pipeline import run_pipeline
from app.signals import build_signal_context
from app.signals.context import SignalContext

logger = logging.getLogger(__name__)


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
    mode.add_argument("--evaluate-history", action="store_true",
                      help="Evaluate pending history only — no new scan, no new signals.")
    mode.add_argument("--history-report", action="store_true",
                      help="Rebuild the Signal Memory HTML report from the existing DB.")
    mode.add_argument("--export-history", action="store_true",
                      help="Rebuild the Signal Memory CSV export from the existing DB.")
    parser.add_argument("--top", type=int, default=None,
                        help="Number of rows to display (overrides SCREENER_TOP_N).")
    parser.add_argument("--no-report", action="store_true",
                        help="Skip writing the TradingView HTML report.")
    parser.add_argument("--no-history", action="store_true",
                        help="Skip the Signal Memory cycle for this run.")
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


# ---------------------------------------------------------------------------
# TradingView report
# ---------------------------------------------------------------------------

def _maybe_write_report(
    rows: List[ScreenerRow],
    *,
    config: AppConfig,
    top: int,
    enabled: bool,
) -> None:
    if not enabled or not config.generate_tradingview_report:
        return
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


# ---------------------------------------------------------------------------
# Signal context (console)
# ---------------------------------------------------------------------------

def _build_contexts(
    rows: List[ScreenerRow], *, config: AppConfig, top: int
) -> List[Tuple[ScreenerRow, SignalContext]]:
    sorted_rows = sorted(rows, key=lambda r: r.score, reverse=True)[:top]
    return [
        (r, build_signal_context(r, tradingview_exchange_prefix=config.tradingview_exchange_prefix))
        for r in sorted_rows
    ]


def _print_signal_context(pairs: List[Tuple[ScreenerRow, SignalContext]]) -> None:
    print()
    print(render_signal_context_block([ctx for _, ctx in pairs]))


# ---------------------------------------------------------------------------
# Signal Memory
# ---------------------------------------------------------------------------

def _history_settings(config: AppConfig):
    from app.history import HistorySettings

    return HistorySettings(
        exchange=config.tradingview_exchange_prefix,
        cooldown_minutes=config.signal_history_cooldown_minutes,
        min_score=config.signal_history_min_score,
        min_quality=config.signal_history_min_quality,
        match_thresholds=config.history_match_thresholds(),
        retention_days=config.signal_history_retention_days,
    )


def _candle_timestamp_map(inputs: Sequence[MarketScanInput]) -> Dict[str, datetime]:
    out: Dict[str, datetime] = {}
    for item in inputs:
        if item.candles:
            out[item.symbol] = datetime.fromtimestamp(
                item.candles[-1].open_time, tz=timezone.utc
            )
    return out


def _run_history_cycle(
    *,
    config: AppConfig,
    pairs: List[Tuple[ScreenerRow, SignalContext]],
    candle_ts: Dict[str, datetime],
    offline: bool,
    price_provider,
) -> None:
    """Record + evaluate + rebuild outputs. Never raises — logs and prints instead."""
    if offline:
        db_path, report_path, export_path = config.offline_history_paths()
        title = "Signal Memory (offline-test)"
    else:
        db_path = config.signal_history_db_path
        report_path = config.signal_history_report_path
        export_path = config.signal_history_export_path
        title = "Signal Memory"

    now = datetime.now(timezone.utc)
    candidates = [
        (row, ctx, candle_ts.get(row.symbol, now))
        for row, ctx in pairs
    ]

    try:
        from app.history import SignalRepository
        from app.history.service import run_full_cycle

        with SignalRepository(db_path) as repo:
            summary, stats = run_full_cycle(
                repo,
                settings=_history_settings(config),
                candidates=candidates,
                price_provider=price_provider,
                now=now,
                create_new=True,
                evaluate=True,
                rebuild_outputs=True,
                report_path=report_path,
                export_path=export_path,
                report_title=title,
            )
        _print_history_summary(summary, stats, report_path)
    except Exception as exc:  # noqa: BLE001 — history must never break the screener
        logger.warning("Signal Memory cycle failed: %s", exc)
        print(f"warning: signal history skipped ({exc})", file=sys.stderr)


def _print_history_summary(summary, stats, report_path: str) -> None:
    from app.history import headline_match_rate

    print()
    print("Signal Memory:")
    print(f"  New: {summary.new}")
    print(f"  Updated: {summary.updated}")
    print(f"  Completed: {summary.completed}")
    print(f"  Pending: {summary.pending}")
    print(f"  {headline_match_rate(stats, '1h')}")
    print(f"Signal history report: {report_path}")


# ---------------------------------------------------------------------------
# Scan modes
# ---------------------------------------------------------------------------

def _run_offline(config: AppConfig, top: int, *, write_report: bool,
                 compact: bool, history: bool) -> int:
    from app.data.sample_data import build_offline_inputs, list_scenarios

    print(f"# crypto_screener — offline-test mode (top {top})", file=sys.stderr)
    print("# Loaded scenarios:", file=sys.stderr)
    for scenario in list_scenarios():
        print(f"#  - {scenario.symbol:<22} {scenario.label}", file=sys.stderr)

    inputs: List[MarketScanInput] = build_offline_inputs()
    rows: List[ScreenerRow] = run_pipeline(
        inputs, funding_threshold=config.signal_funding_abs_threshold,
    )
    print(render_top_table(
        rows, top=top, title="Top movers (offline-test)",
        exchange_prefix=config.tradingview_exchange_prefix,
    ))
    pairs = _build_contexts(rows, config=config, top=top)
    if compact:
        print()
        print(render_compact_view(
            rows, top=top, title="Compact view (offline-test)",
            exchange_prefix=config.tradingview_exchange_prefix,
        ))
    _print_signal_context(pairs)
    _maybe_write_report(rows, config=config, top=top, enabled=write_report)

    if history and config.signal_history_enabled:
        from app.history import NullPriceProvider
        _run_history_cycle(
            config=config, pairs=pairs,
            candle_ts=_candle_timestamp_map(inputs),
            offline=True, price_provider=NullPriceProvider(),
        )
    return 0


def _run_live(config: AppConfig, top: int, *, write_report: bool,
              compact: bool, history: bool) -> int:
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
        inputs, funding_threshold=config.signal_funding_abs_threshold,
    )
    print(render_top_table(
        rows, top=top, title="Top movers (live)",
        exchange_prefix=config.tradingview_exchange_prefix,
    ))
    pairs = _build_contexts(rows, config=config, top=top)
    if compact:
        print()
        print(render_compact_view(
            rows, top=top, title="Compact view (live)",
            exchange_prefix=config.tradingview_exchange_prefix,
        ))
    _print_signal_context(pairs)
    _maybe_write_report(rows, config=config, top=top, enabled=write_report)

    if history and config.signal_history_enabled:
        from app.exchanges.binance import BinanceClient
        from app.history import LivePriceProvider
        provider = LivePriceProvider(BinanceClient(binance_config))
        _run_history_cycle(
            config=config, pairs=pairs,
            candle_ts=_candle_timestamp_map(inputs),
            offline=False, price_provider=provider,
        )
    return 0


# ---------------------------------------------------------------------------
# History-only commands
# ---------------------------------------------------------------------------

def _cmd_evaluate_history(config: AppConfig) -> int:
    """Evaluate pending history without scanning or creating new signals."""
    from app.exchanges.binance import BinanceClient, BinanceConfig, CcxtNotInstalledError
    from app.history import LivePriceProvider, SignalRepository
    from app.history.service import run_full_cycle

    try:
        provider = LivePriceProvider(BinanceClient(BinanceConfig(
            api_key=config.binance_api_key, api_secret=config.binance_api_secret,
        )))
        with SignalRepository(config.signal_history_db_path) as repo:
            summary, stats = run_full_cycle(
                repo, settings=_history_settings(config),
                candidates=(), price_provider=provider,
                create_new=False, evaluate=True, rebuild_outputs=True,
                report_path=config.signal_history_report_path,
                export_path=config.signal_history_export_path,
            )
        _print_history_summary(summary, stats, config.signal_history_report_path)
        return 0
    except CcxtNotInstalledError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"error: history evaluation failed: {exc}", file=sys.stderr)
        return 1


def _cmd_history_report(config: AppConfig) -> int:
    """Rebuild the HTML report from the existing DB (no evaluation)."""
    from app.history import SignalRepository
    from app.history.service import run_full_cycle

    try:
        with SignalRepository(config.signal_history_db_path) as repo:
            _, _ = run_full_cycle(
                repo, settings=_history_settings(config),
                candidates=(), create_new=False, evaluate=False, rebuild_outputs=True,
                report_path=config.signal_history_report_path,
                export_path=None,
            )
        print(f"Signal history report: {config.signal_history_report_path}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"error: report build failed: {exc}", file=sys.stderr)
        return 1


def _cmd_export_history(config: AppConfig) -> int:
    """Rebuild the CSV export from the existing DB (no evaluation)."""
    from app.history import SignalRepository
    from app.history.service import run_full_cycle

    try:
        with SignalRepository(config.signal_history_db_path) as repo:
            _, _ = run_full_cycle(
                repo, settings=_history_settings(config),
                candidates=(), create_new=False, evaluate=False, rebuild_outputs=True,
                report_path=None,
                export_path=config.signal_history_export_path,
            )
        print(f"Signal history export: {config.signal_history_export_path}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"error: export failed: {exc}", file=sys.stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    config = AppConfig.from_env()
    _setup_logging(config.log_level)
    top = args.top if args.top is not None else config.top_n
    write_report = not args.no_report
    history = not args.no_history

    if args.evaluate_history:
        return _cmd_evaluate_history(config)
    if args.history_report:
        return _cmd_history_report(config)
    if args.export_history:
        return _cmd_export_history(config)
    if args.offline_test:
        return _run_offline(config, top, write_report=write_report,
                            compact=args.compact, history=history)
    return _run_live(config, top, write_report=write_report,
                     compact=args.compact, history=history)


if __name__ == "__main__":
    raise SystemExit(main())
