"""Minimal env-driven configuration.

We read .env via a small inline parser to avoid forcing `python-dotenv` as a
hard dependency. If python-dotenv is installed we use it for nicer parsing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _maybe_load_dotenv() -> None:
    """Load `.env` from the current working directory if present.

    Supports two paths:
        1. python-dotenv if installed (preferred)
        2. tiny inline parser otherwise

    Existing process env vars always win.
    """
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]
        load_dotenv(dotenv_path=env_path, override=False)
        return
    except ImportError:
        pass
    # Inline fallback parser — handles KEY=VALUE, skips comments / blanks.
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _bool_env(name: str, default: bool) -> bool:
    """Parse a truthy string from env. Accepts true/false/1/0/yes/no, case-insensitive."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class AppConfig:
    binance_api_key: Optional[str]
    binance_api_secret: Optional[str]
    top_n: int
    candle_limit: int
    universe_limit: int
    log_level: str
    # TradingView report settings
    generate_tradingview_report: bool
    tradingview_exchange_prefix: str
    tradingview_interval: str
    tradingview_report_path: str

    @staticmethod
    def from_env() -> "AppConfig":
        _maybe_load_dotenv()
        return AppConfig(
            binance_api_key=os.environ.get("BINANCE_API_KEY") or None,
            binance_api_secret=os.environ.get("BINANCE_API_SECRET") or None,
            top_n=int(os.environ.get("SCREENER_TOP_N", "20")),
            candle_limit=int(os.environ.get("SCREENER_CANDLE_LIMIT", "90")),
            universe_limit=int(os.environ.get("SCREENER_UNIVERSE_LIMIT", "40")),
            log_level=os.environ.get("SCREENER_LOG_LEVEL", "INFO"),
            generate_tradingview_report=_bool_env("GENERATE_TRADINGVIEW_REPORT", True),
            tradingview_exchange_prefix=os.environ.get("TRADINGVIEW_EXCHANGE_PREFIX", "BINANCE"),
            tradingview_interval=os.environ.get("TRADINGVIEW_INTERVAL", "60"),
            tradingview_report_path=os.environ.get(
                "TRADINGVIEW_REPORT_PATH", "data/processed/tradingview_report.html"
            ),
        )
