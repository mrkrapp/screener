"""Binance USDM Futures wrapper.

Design rule: ccxt is imported **only inside functions/methods** so that
this module is importable even when ccxt is missing. The collector will
catch the ImportError from `BinanceClient(...)` construction and the CLI
turns it into a friendly message.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, List, Optional

from app.models import Candle


class CcxtNotInstalledError(ImportError):
    """Raised when ccxt is required for the requested operation."""


@dataclass
class BinanceConfig:
    """Construction-time settings. None of these contain secrets in MVP."""

    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    timeout_ms: int = 10_000
    rate_limit: bool = True


def _import_ccxt() -> Any:
    """Lazy import — runs only when a method that needs ccxt is called."""
    try:
        import ccxt  # type: ignore[import-not-found]
    except ImportError as exc:
        raise CcxtNotInstalledError(
            "ccxt is required for live mode. "
            "Install dependencies with: pip install -r requirements.txt"
        ) from exc
    return ccxt


class BinanceClient:
    """Thin facade over ccxt.binanceusdm. Only the methods we need."""

    def __init__(self, config: Optional[BinanceConfig] = None) -> None:
        self._config = config or BinanceConfig()
        self._exchange: Any = None  # populated on first call

    # ---- internals ---------------------------------------------------------

    def _exchange_or_create(self) -> Any:
        if self._exchange is not None:
            return self._exchange
        ccxt = _import_ccxt()
        cls = ccxt.binanceusdm  # USDM perpetual futures
        params: dict[str, Any] = {
            "enableRateLimit": self._config.rate_limit,
            "timeout": self._config.timeout_ms,
            "options": {"defaultType": "future"},
        }
        if self._config.api_key and self._config.api_secret:
            params["apiKey"] = self._config.api_key
            params["secret"] = self._config.api_secret
        self._exchange = cls(params)
        return self._exchange

    # ---- public API --------------------------------------------------------

    def list_perp_symbols(self, *, quote: str = "USDT", limit: Optional[int] = None) -> List[str]:
        """Return active linear USDT-margined perpetuals.

        Filters to swap markets matching `quote`. Sorted alphabetically.
        """
        exchange = self._exchange_or_create()
        exchange.load_markets()
        symbols: List[str] = []
        for symbol, market in exchange.markets.items():
            if not market.get("active"):
                continue
            if market.get("type") != "swap":
                continue
            if market.get("quote") != quote:
                continue
            if market.get("settle") != quote:
                continue
            symbols.append(symbol)
        symbols.sort()
        if limit is not None:
            symbols = symbols[:limit]
        return symbols

    def fetch_candles(self, symbol: str, *, timeframe: str = "1m", limit: int = 90) -> List[Candle]:
        """Fetch the most recent `limit` 1-minute candles for `symbol`."""
        exchange = self._exchange_or_create()
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        # ccxt returns ms timestamps; we store seconds.
        return [
            Candle(
                open_time=int(row[0] // 1000),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in raw
        ]

    def fetch_candles_range(
        self,
        symbol: str,
        *,
        since_ts: int,
        timeframe: str = "5m",
        limit: int = 500,
    ) -> List[Candle]:
        """Fetch candles starting at ``since_ts`` (unix seconds).

        Used by the history layer to evaluate what happened after a signal.
        ccxt expects ``since`` in milliseconds.
        """
        exchange = self._exchange_or_create()
        raw = exchange.fetch_ohlcv(
            symbol, timeframe=timeframe, since=int(since_ts) * 1000, limit=limit
        )
        return [
            Candle(
                open_time=int(row[0] // 1000),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in raw
        ]

    def fetch_open_interest(self, symbol: str) -> float:
        """Latest open interest in contracts. Returns 0.0 on failure."""
        exchange = self._exchange_or_create()
        # ccxt exposes fetch_open_interest for binanceusdm.
        try:
            data = exchange.fetch_open_interest(symbol)
        except Exception:
            return 0.0
        if isinstance(data, dict):
            value = data.get("openInterestAmount") or data.get("openInterest") or 0.0
            return float(value) if value is not None else 0.0
        return 0.0

    def fetch_funding_rate(self, symbol: str) -> float:
        """Latest funding rate (per-interval, e.g. 0.0001). 0.0 on failure."""
        exchange = self._exchange_or_create()
        try:
            data = exchange.fetch_funding_rate(symbol)
        except Exception:
            return 0.0
        if isinstance(data, dict):
            value = data.get("fundingRate") or 0.0
            return float(value) if value is not None else 0.0
        return 0.0

    def server_time(self) -> int:
        """Useful for sanity-checking connectivity."""
        exchange = self._exchange_or_create()
        try:
            return int(exchange.milliseconds() // 1000)
        except Exception:
            return int(time.time())
