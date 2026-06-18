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

        Filters to swap markets matching `quote`, then ranks by reported 24h
        quote volume. Symbols with missing ticker volume remain eligible but
        sort behind markets with verified liquidity.
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
            if market.get("linear") is False:
                continue
            if market.get("expiry") is not None:
                continue
            symbols.append(symbol)
        try:
            tickers = exchange.fetch_tickers(symbols)
        except Exception:
            tickers = {}
        symbols.sort(
            key=lambda item: (
                _ticker_quote_volume(tickers.get(item)),
                item,
            ),
            reverse=True,
        )
        if limit is not None:
            symbols = symbols[:limit]
        return symbols

    def fetch_candles(self, symbol: str, *, timeframe: str = "1m", limit: int = 90) -> List[Candle]:
        """Fetch the most recent `limit` 1-minute candles for `symbol`."""
        exchange = self._exchange_or_create()
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        candles = [
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
        now_seconds = int(exchange.milliseconds() // 1000)
        candle_seconds = _timeframe_seconds(timeframe)
        return [
            candle
            for candle in candles
            if candle.open_time + candle_seconds <= now_seconds
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

    def fetch_open_interest(self, symbol: str) -> Optional[float]:
        """Latest open interest in contracts. Missing data stays ``None``."""
        exchange = self._exchange_or_create()
        try:
            data = exchange.fetch_open_interest(symbol)
        except Exception:
            return None
        return _open_interest_value(data)

    def fetch_open_interest_previous(
        self,
        symbol: str,
        *,
        timeframe: str = "1h",
    ) -> Optional[float]:
        """Return the previous completed OI history point.

        Binance exposes this through the public open-interest history endpoint.
        We deliberately return ``None`` when history is unavailable instead of
        fabricating a change from the current value.
        """
        exchange = self._exchange_or_create()
        try:
            history = exchange.fetch_open_interest_history(
                symbol,
                timeframe=timeframe,
                limit=2,
            )
        except Exception:
            return None
        if not isinstance(history, list) or len(history) < 2:
            return None
        ordered = sorted(history, key=lambda item: item.get("timestamp") or 0)
        return _open_interest_value(ordered[-2])

    def fetch_funding_rate(self, symbol: str) -> Optional[float]:
        """Latest funding rate. Missing data stays ``None``."""
        exchange = self._exchange_or_create()
        try:
            data = exchange.fetch_funding_rate(symbol)
        except Exception:
            return None
        if isinstance(data, dict):
            value = data.get("fundingRate")
            return _safe_float(value)
        return None

    def server_time(self) -> int:
        """Useful for sanity-checking connectivity."""
        exchange = self._exchange_or_create()
        try:
            return int(exchange.milliseconds() // 1000)
        except Exception:
            return int(time.time())


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ticker_quote_volume(ticker: Any) -> float:
    if not isinstance(ticker, dict):
        return -1.0
    value = ticker.get("quoteVolume")
    parsed = _safe_float(value)
    if parsed is not None:
        return parsed
    info = ticker.get("info")
    if isinstance(info, dict):
        parsed = _safe_float(info.get("quoteVolume"))
        if parsed is not None:
            return parsed
    return -1.0


def _open_interest_value(data: Any) -> Optional[float]:
    if not isinstance(data, dict):
        return None
    for key in (
        "openInterestAmount",
        "openInterest",
        "baseVolume",
        "sumOpenInterest",
    ):
        parsed = _safe_float(data.get(key))
        if parsed is not None:
            return parsed
    info = data.get("info")
    if isinstance(info, dict):
        for key in ("openInterest", "sumOpenInterest"):
            parsed = _safe_float(info.get(key))
            if parsed is not None:
                return parsed
    return None


def _timeframe_seconds(timeframe: str) -> int:
    units = {"m": 60, "h": 3600, "d": 86400}
    try:
        return int(timeframe[:-1]) * units[timeframe[-1].lower()]
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"Unsupported timeframe: {timeframe!r}") from None
