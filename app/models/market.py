"""Core dataclasses.

The flow is:
    collector  → MarketScanInput[]
    metrics    → MarketScanInput + derived numbers → ScreenerRow
    scoring    → ScreenerRow (fills `score` + `signals`)
    output     → ScreenerRow[] → console table

Keeping these dataclasses immutable (`frozen=True` where reasonable) lets us
pass them between modules without worrying about side-effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Candle:
    """A single OHLCV bar. Timestamps are unix seconds (UTC)."""

    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class MarketScanInput:
    """Raw per-symbol payload the collector returns.

    Candles are ascending by time (oldest first, latest last).
    We expect at least ~60 minutes of 1-minute candles for stable metrics.
    """

    symbol: str
    candles: List[Candle]
    # Derivatives snapshot
    open_interest_current: float
    open_interest_prev: float   # roughly 1h prior, for OI change %
    funding_rate: float           # per-funding-interval rate (e.g. 0.0001 = 0.01%)


@dataclass
class ScreenerRow:
    """Final row rendered in the top table.

    Mutable so we can populate `score` and `signals` after metrics run.
    """

    symbol: str
    price: float
    change_5m: float           # %
    change_15m: float          # %
    change_1h: float           # %
    volume_current: float
    volume_avg: float
    relative_volume: float     # current / avg
    volume_z: float            # z-score vs rolling history
    atr: float                 # average true range over recent window
    vol_expansion: float       # latest range / avg range
    open_interest: float
    oi_change: float           # %
    funding_rate: float        # %
    derivatives_score: float   # 0-100 composite from OI + funding
    score: float = 0.0         # 0-100 overall, filled by scoring module
    signals: List[str] = field(default_factory=list)
