"""Core dataclasses.

The flow is:
    collector  → MarketScanInput[]
    metrics    → MarketScanInput + derived numbers → ScreenerRow
    scoring    → ScreenerRow (fills `score` + `signals`)
    detector   → ScreenerRow (enriched with quality metrics)
    output     → ScreenerRow[] → console table

Keeping these dataclasses immutable (`frozen=True` where reasonable) lets us
pass them between modules without worrying about side-effects.

`ScreenerResult` is an alias of `ScreenerRow` kept for code that references
the spec name. Both refer to the same dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


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
    open_interest_current: Optional[float]
    open_interest_prev: Optional[float]   # real historical OI, never fabricated
    funding_rate: Optional[float]         # per-funding-interval rate (e.g. 0.0001 = 0.01%)


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
    open_interest: Optional[float]
    oi_change: Optional[float]           # %
    funding_rate: Optional[float]        # %
    derivatives_score: Optional[float]   # 0-100 composite from OI + funding
    score: float = 0.0         # 0-100 overall, filled by scoring module
    signals: List[str] = field(default_factory=list)
    # --- Quality metrics (filled by app/signals/detector.enrich_with_quality) ---
    atr_percent: Optional[float] = None
    price_move_atr: Optional[float] = None
    dollar_volume_current: Optional[float] = None
    dollar_volume_avg: Optional[float] = None
    volume_confirmation: Optional[float] = None
    trend_alignment: str = "INSUFFICIENT_DATA"
    oi_confirmation: str = "INSUFFICIENT_DATA"
    funding_pressure: Optional[float] = None
    quality_score: float = 0.0


# Alias kept for code that follows the spec's `ScreenerResult` naming.
ScreenerResult = ScreenerRow
