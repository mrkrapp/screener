"""Price-change metrics.

Operates on 1-minute candles assumed to be ordered oldest → latest.
"""

from __future__ import annotations

from typing import List

from app.models import Candle


def _safe_pct(curr: float, prev: float) -> float:
    if prev <= 0:
        return 0.0
    return (curr - prev) / prev * 100.0


def latest_price(candles: List[Candle]) -> float:
    """Latest close. Returns 0.0 if no candles."""
    if not candles:
        return 0.0
    return candles[-1].close


def change_pct(candles: List[Candle], minutes_back: int) -> float:
    """Percent change between the latest close and the close `minutes_back` ago.

    With 1-minute candles, `minutes_back` is the number of candles to look back.
    """
    if len(candles) < minutes_back + 1:
        return 0.0
    return _safe_pct(candles[-1].close, candles[-1 - minutes_back].close)


def change_5m(candles: List[Candle]) -> float:
    return change_pct(candles, 5)


def change_15m(candles: List[Candle]) -> float:
    return change_pct(candles, 15)


def change_1h(candles: List[Candle]) -> float:
    return change_pct(candles, 60)
