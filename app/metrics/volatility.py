"""Volatility metrics: ATR + range expansion."""

from __future__ import annotations

from typing import List

from app.models import Candle


def true_range(prev_close: float, candle: Candle) -> float:
    """Standard true range = max(H-L, |H-prevClose|, |L-prevClose|)."""
    return max(
        candle.high - candle.low,
        abs(candle.high - prev_close),
        abs(candle.low - prev_close),
    )


def atr(candles: List[Candle], window: int = 14) -> float:
    """Simple moving ATR over the last `window` candles (excluding the latest)."""
    if len(candles) < window + 1:
        return 0.0
    sample = candles[-window - 1 : -1]
    trs: List[float] = []
    for i in range(1, len(sample)):
        trs.append(true_range(sample[i - 1].close, sample[i]))
    if not trs:
        return 0.0
    return sum(trs) / len(trs)


def vol_expansion(candles: List[Candle], window: int = 20) -> float:
    """Latest candle range divided by average range of the prior window.

    >1.0 means the latest candle is expanding vs recent history.
    """
    if len(candles) < window + 1:
        return 0.0
    history = candles[-window - 1 : -1]
    avg_range = sum((c.high - c.low) for c in history) / max(1, len(history))
    if avg_range <= 0:
        return 0.0
    latest_range = candles[-1].high - candles[-1].low
    return latest_range / avg_range
