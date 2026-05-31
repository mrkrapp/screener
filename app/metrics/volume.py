"""Volume metrics: average, relative volume, z-score."""

from __future__ import annotations

from math import sqrt
from typing import List, Tuple

from app.models import Candle


def latest_volume(candles: List[Candle]) -> float:
    return candles[-1].volume if candles else 0.0


def average_volume(candles: List[Candle], window: int = 20) -> float:
    if len(candles) < 2:
        return 0.0
    history = candles[-window - 1 : -1] if len(candles) > window else candles[:-1]
    if not history:
        return 0.0
    return sum(c.volume for c in history) / len(history)


def _mean_std(values: List[float]) -> Tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / max(1, len(values) - 1)
    return mean, sqrt(var)


def volume_z_score(candles: List[Candle], window: int = 20) -> float:
    """How many standard deviations is the latest volume above its recent mean?"""
    if len(candles) < 3:
        return 0.0
    history = candles[-window - 1 : -1] if len(candles) > window else candles[:-1]
    if len(history) < 2:
        return 0.0
    mean, std = _mean_std([c.volume for c in history])
    if std <= 0:
        return 0.0
    return (candles[-1].volume - mean) / std


def relative_volume(candles: List[Candle], window: int = 20) -> float:
    """Latest volume divided by average over the prior `window` candles."""
    avg = average_volume(candles, window)
    if avg <= 0:
        return 0.0
    return latest_volume(candles) / avg
