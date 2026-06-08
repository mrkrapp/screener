"""Concrete :class:`PriceProvider` implementations.

``LivePriceProvider`` wraps the ccxt-backed ``BinanceClient`` to fetch the
closed candles that followed a signal. It uses 5-minute candles so a 24h window
is ~288 candles (one polite request) while still capturing intraday extremes
for MFE/MAE. ccxt stays lazily imported inside the client.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from app.exchanges.binance import BinanceClient
from app.models import Candle

logger = logging.getLogger(__name__)

# 5-minute evaluation candles.
_EVAL_TIMEFRAME = "5m"
_EVAL_CANDLE_SECONDS = 300


class LivePriceProvider:
    """Fetches post-signal candles from Binance USDM via ``BinanceClient``."""

    candle_seconds = _EVAL_CANDLE_SECONDS

    def __init__(self, client: BinanceClient) -> None:
        self._client = client

    def get_window(self, symbol: str, start: datetime, end: datetime) -> List[Candle]:
        start = _ensure_utc(start)
        end = _ensure_utc(end)
        since_ts = int(start.timestamp())
        span_minutes = max(1, int((end - start).total_seconds() // 60))
        # +2 candles of headroom so the horizon close is included.
        limit = min(1000, span_minutes // 5 + 2)
        try:
            candles = self._client.fetch_candles_range(
                symbol,
                since_ts=since_ts,
                timeframe=_EVAL_TIMEFRAME,
                limit=limit,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Window fetch failed for %s: %s", symbol, exc)
            return []
        end_ts = int(end.timestamp())
        return [c for c in candles if start.timestamp() <= c.open_time <= end_ts]


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
