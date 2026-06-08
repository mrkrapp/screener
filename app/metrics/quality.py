"""Signal-quality metrics.

These metrics describe how clean a screener row is — they do not replace
the composite score. They answer "is the move supported by volume / OI /
volatility?", not "is this a buy?".

Every function is a pure derivation of already-computed fields.
"""

from __future__ import annotations

from typing import Optional

# String labels for trend / OI confirmation. Keeping them as module-level
# constants avoids typos at the call sites and lets tests assert on them.
TREND_BULLISH_ALIGNED = "BULLISH_ALIGNED"
TREND_BEARISH_ALIGNED = "BEARISH_ALIGNED"
TREND_MIXED_ALIGNMENT = "MIXED_ALIGNMENT"
TREND_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

OI_FRESH_LONGS = "FRESH_LONGS"
OI_FRESH_SHORTS = "FRESH_SHORTS"
OI_SHORT_COVERING = "SHORT_COVERING"
OI_LONG_UNWIND = "LONG_UNWIND"
OI_NO_CLEAR = "NO_CLEAR_OI_CONFIRMATION"
OI_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# ---------------------------------------------------------------------------
# 1. ATR percent
# ---------------------------------------------------------------------------

def atr_percent(atr: Optional[float], price: Optional[float]) -> Optional[float]:
    """Return ATR as a percent of price. None when either input is missing or price == 0."""
    if atr is None or price is None or price == 0:
        return None
    return atr / price * 100.0


# ---------------------------------------------------------------------------
# 2. Price move in ATR
# ---------------------------------------------------------------------------

def price_move_in_atr(change_1h: Optional[float], atr_pct: Optional[float]) -> Optional[float]:
    """`abs(change_1h)` expressed as multiples of ATR%.

    +2% on BTC and +2% on a very volatile asset are not the same. This helper
    normalises the move by the asset's own volatility.
    """
    if change_1h is None or atr_pct is None or atr_pct == 0:
        return None
    return abs(change_1h) / atr_pct


# ---------------------------------------------------------------------------
# 3. Dollar volume
# ---------------------------------------------------------------------------

def dollar_volume(price: Optional[float], volume: Optional[float]) -> Optional[float]:
    """`price * volume`. None if either side is missing."""
    if price is None or volume is None:
        return None
    return price * volume


# ---------------------------------------------------------------------------
# 4. Volume confirmation
# ---------------------------------------------------------------------------

def volume_confirmation(relative_volume: Optional[float], change_1h: Optional[float]) -> Optional[float]:
    """Combine RVOL and price move into a single confirmation index.

    Price + volume together is stronger than either alone.
    """
    if relative_volume is None or change_1h is None:
        return None
    return relative_volume * abs(change_1h)


# ---------------------------------------------------------------------------
# 5. Trend alignment label
# ---------------------------------------------------------------------------

def trend_alignment_label(
    change_5m: Optional[float],
    change_15m: Optional[float],
    change_1h: Optional[float],
) -> str:
    """Classify how 5m / 15m / 1h price changes line up."""
    if change_5m is None or change_15m is None or change_1h is None:
        return TREND_INSUFFICIENT_DATA
    if change_5m > 0 and change_15m > 0 and change_1h > 0:
        return TREND_BULLISH_ALIGNED
    if change_5m < 0 and change_15m < 0 and change_1h < 0:
        return TREND_BEARISH_ALIGNED
    return TREND_MIXED_ALIGNMENT


# ---------------------------------------------------------------------------
# 6. OI confirmation label
# ---------------------------------------------------------------------------

def oi_confirmation_label(change_1h: Optional[float], oi_change: Optional[float]) -> str:
    """Classify whether OI movement confirms the price move.

    Rules (from spec):
        price up = change_1h > 1
        price down = change_1h < -1
        OI up = oi_change > 1
        OI down = oi_change < -1
    """
    if change_1h is None or oi_change is None:
        return OI_INSUFFICIENT_DATA
    price_up = change_1h > 1
    price_down = change_1h < -1
    oi_up = oi_change > 1
    oi_down = oi_change < -1
    if price_up and oi_up:
        return OI_FRESH_LONGS
    if price_down and oi_up:
        return OI_FRESH_SHORTS
    if price_up and oi_down:
        return OI_SHORT_COVERING
    if price_down and oi_down:
        return OI_LONG_UNWIND
    return OI_NO_CLEAR


# ---------------------------------------------------------------------------
# 7. Funding pressure
# ---------------------------------------------------------------------------

def funding_pressure(
    funding_rate: Optional[float],
    funding_threshold: Optional[float],
) -> Optional[float]:
    """How many funding thresholds the current rate is at, in absolute terms."""
    if funding_rate is None or funding_threshold is None or funding_threshold == 0:
        return None
    return abs(funding_rate) / funding_threshold


# ---------------------------------------------------------------------------
# 8. Quality score
# ---------------------------------------------------------------------------

def quality_score(
    *,
    trend_alignment: str,
    volume_confirmation_value: Optional[float],
    price_move_atr: Optional[float],
    oi_confirmation: str,
    funding_pressure_value: Optional[float],
    vol_expansion: Optional[float],
    relative_volume: Optional[float],
    change_1h: Optional[float],
) -> float:
    """0-100 cleanliness score. Independent from composite score.

    Positive contributions are alignment-, volume-, ATR-, and OI-based.
    Negative contributions are funding overheat, volatility extension and
    volume spikes without price follow-through.
    """
    score = 50.0
    # + Trend aligned across timeframes
    if trend_alignment in (TREND_BULLISH_ALIGNED, TREND_BEARISH_ALIGNED):
        score += 15.0
    # + Volume confirms the move
    if volume_confirmation_value is not None and volume_confirmation_value >= 3:
        score += 15.0
    # + Move is meaningful relative to ATR
    if price_move_atr is not None and price_move_atr >= 1:
        score += 10.0
    # + OI confirms direction (fresh positions outweigh covering/unwind)
    if oi_confirmation in (OI_FRESH_LONGS, OI_FRESH_SHORTS):
        score += 15.0
    elif oi_confirmation in (OI_SHORT_COVERING, OI_LONG_UNWIND):
        score += 5.0
    # - Funding overheated
    if funding_pressure_value is not None and funding_pressure_value > 1:
        score -= 10.0
    # - Volatility highly expanded
    if vol_expansion is not None and vol_expansion > 2:
        score -= 10.0
    # - Volume spike without price follow-through
    if (
        relative_volume is not None
        and change_1h is not None
        and relative_volume > 2.5
        and abs(change_1h) < 1
    ):
        score -= 10.0
    return max(0.0, min(100.0, score))
