"""Signal context builder.

Takes an enriched `ScreenerResult` and produces a `SignalContext` — a
compact human-readable summary with `direction_hint`, `confidence`,
`main_reasons`, `risk_notes`, the TradingView symbol/URL, and a one-line
`compact_summary` suitable for console output or future Telegram alerts.

`direction_hint` describes market behaviour, **not** a trade recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.charts.tradingview import convert_symbol_to_tradingview, tradingview_url
from app.metrics.quality import (
    TREND_BEARISH_ALIGNED,
    TREND_BULLISH_ALIGNED,
    TREND_MIXED_ALIGNMENT,
    OI_FRESH_LONGS,
    OI_FRESH_SHORTS,
)
from app.models import ScreenerResult


# direction_hint vocabulary — descriptive only.
DIR_BULLISH_MOMENTUM = "BULLISH_MOMENTUM"
DIR_BEARISH_MOMENTUM = "BEARISH_MOMENTUM"
DIR_VOLUME_ONLY = "VOLUME_ONLY"
DIR_DERIVATIVES_ANOMALY = "DERIVATIVES_ANOMALY"
DIR_VOLATILITY_BREAKOUT = "VOLATILITY_BREAKOUT"
DIR_MIXED = "MIXED"
DIR_NEUTRAL = "NEUTRAL"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"


@dataclass
class SignalContext:
    """Compact narrative around one screener result.

    All fields are presentation-layer; no calculations live on this object.
    """

    symbol: str
    score: float
    quality_score: float
    direction_hint: str
    confidence: str
    main_reasons: List[str] = field(default_factory=list)
    risk_notes: List[str] = field(default_factory=list)
    tradingview_symbol: str = ""
    tradingview_url: str = ""
    compact_summary: str = ""


def _funding_rate_raw(result: ScreenerResult) -> Optional[float]:
    """ScreenerResult stores funding as percent — convert back to raw rate."""
    if result.funding_rate is None:
        return None
    return result.funding_rate / 100.0


def _direction_hint(result: ScreenerResult) -> str:
    ch_1h = result.change_1h
    rvol = result.relative_volume
    oi_ch = result.oi_change
    derivs = result.derivatives_score
    vol_exp = result.vol_expansion
    funding_raw = _funding_rate_raw(result)

    # Detect conflicting strong signals → MIXED
    conflicts = 0
    if ch_1h is not None and oi_ch is not None:
        if ch_1h > 1 and oi_ch < -1:
            conflicts += 1
        if ch_1h < -1 and oi_ch < -1:
            conflicts += 1
    if funding_raw is not None and ch_1h is not None and abs(funding_raw) > 0.0007 and ch_1h > 2:
        conflicts += 1
    if rvol is not None and ch_1h is not None and rvol > 2.5 and abs(ch_1h) < 1:
        conflicts += 1
    if result.trend_alignment == TREND_MIXED_ALIGNMENT and ch_1h is not None and abs(ch_1h) > 1.5:
        conflicts += 1

    # Order of evaluation matters — first matching wins.
    if (
        ch_1h is not None and ch_1h > 2
        and rvol is not None and rvol > 2
        and (oi_ch is None or oi_ch >= 0)
    ):
        return DIR_MIXED if conflicts >= 2 else DIR_BULLISH_MOMENTUM
    if (
        ch_1h is not None and ch_1h < -2
        and rvol is not None and rvol > 2
        and (oi_ch is None or oi_ch >= 0)
    ):
        return DIR_MIXED if conflicts >= 2 else DIR_BEARISH_MOMENTUM
    if rvol is not None and rvol > 2.5 and ch_1h is not None and abs(ch_1h) < 1:
        return DIR_VOLUME_ONLY
    if derivs is not None and derivs > 70 and ch_1h is not None and abs(ch_1h) < 2:
        return DIR_DERIVATIVES_ANOMALY
    if vol_exp is not None and vol_exp > 1.5 and ch_1h is not None and abs(ch_1h) > 1.5:
        return DIR_MIXED if conflicts >= 2 else DIR_VOLATILITY_BREAKOUT
    if conflicts >= 1:
        return DIR_MIXED
    return DIR_NEUTRAL


def _main_reasons(result: ScreenerResult) -> List[str]:
    reasons: List[str] = []
    ch_1h = result.change_1h
    ch_15m = result.change_15m
    rvol = result.relative_volume
    oi_ch = result.oi_change
    vol_exp = result.vol_expansion
    derivs = result.derivatives_score
    funding_raw = _funding_rate_raw(result)

    if rvol is not None and rvol > 1.5:
        reasons.append(f"RVOL is {rvol:.1f}x above normal")
    if ch_1h is not None and abs(ch_1h) > 1:
        reasons.append(f"Price moved {ch_1h:+.2f}% over 1h")
    if ch_15m is not None and abs(ch_15m) > 0.7:
        reasons.append(f"Price moved {ch_15m:+.2f}% over 15m")
    if vol_exp is not None and vol_exp > 1.2:
        reasons.append(f"ATR expansion is {vol_exp:.1f}x")
    if oi_ch is not None and abs(oi_ch) > 1:
        direction = "increased" if oi_ch > 0 else "decreased"
        reasons.append(f"Open interest {direction} {oi_ch:+.1f}%")
    if funding_raw is not None and abs(funding_raw) > 0.0003:
        reasons.append(f"Funding rate is elevated at {funding_raw * 100:+.4f}%")
    if derivs is not None and derivs > 50:
        reasons.append(f"Derivatives score is {derivs:.0f}")
    if result.price_move_atr is not None and result.price_move_atr > 1:
        reasons.append(f"Move is {result.price_move_atr:.1f} ATR")
    if result.volume_confirmation is not None and result.volume_confirmation > 3:
        reasons.append(f"Volume confirmation is {result.volume_confirmation:.1f}")
    if result.dollar_volume_current is not None and result.dollar_volume_avg is not None:
        if result.dollar_volume_avg > 0 and result.dollar_volume_current >= result.dollar_volume_avg * 1.5:
            reasons.append("Dollar volume is elevated")
    if result.trend_alignment in (TREND_BULLISH_ALIGNED, TREND_BEARISH_ALIGNED):
        reasons.append("Trend is aligned across 5m/15m/1h")
    if result.oi_confirmation == OI_FRESH_LONGS:
        reasons.append("OI confirms fresh longs")
    elif result.oi_confirmation == OI_FRESH_SHORTS:
        reasons.append("OI confirms fresh shorts")
    if result.quality_score > 65:
        reasons.append(f"Signal quality is {result.quality_score:.0f}")
    return reasons


def _risk_notes(result: ScreenerResult) -> List[str]:
    notes: List[str] = []
    ch_1h = result.change_1h
    rvol = result.relative_volume
    oi_ch = result.oi_change
    vol_exp = result.vol_expansion
    funding_raw = _funding_rate_raw(result)

    if funding_raw is not None and funding_raw > 0.0007:
        notes.append("Funding is elevated; long side may be crowded")
    if funding_raw is not None and funding_raw < -0.0007:
        notes.append("Negative funding is elevated; short side may be crowded")
    if ch_1h is not None and oi_ch is not None and ch_1h > 2 and oi_ch < -1:
        notes.append("Price is rising while OI is falling; move may be short covering")
    if ch_1h is not None and oi_ch is not None and ch_1h < -2 and oi_ch < -1:
        notes.append(
            "Price is falling while OI is falling; move may be long liquidation or position unwind"
        )
    if rvol is not None and ch_1h is not None and rvol > 2.5 and abs(ch_1h) < 1:
        notes.append("Volume spike without strong price follow-through")
    if vol_exp is not None and vol_exp > 2:
        notes.append("Volatility is highly expanded; chase risk is higher")
    if result.trend_alignment == TREND_MIXED_ALIGNMENT:
        notes.append("Short-term timeframes are not aligned")
    if result.quality_score < 45:
        notes.append("Signal quality is low despite anomaly score")
    return notes


def _confidence(result: ScreenerResult, n_reasons: int) -> str:
    if result.score >= 75 and result.quality_score >= 70 and n_reasons >= 3:
        return CONFIDENCE_HIGH
    if result.score >= 60 and result.quality_score >= 55 and n_reasons >= 2:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _compact_summary(
    *,
    symbol: str,
    direction_hint: str,
    score: float,
    quality_score: float,
    reasons: List[str],
    confidence: str,
) -> str:
    """One-line summary for console output and future Telegram alerts."""
    if reasons:
        # Take the 3 most salient short reasons.
        short = ", ".join(reasons[:3])
    else:
        short = "No strong context"
    return (
        f"{symbol} | {direction_hint} | Score {score:.0f} | Quality {quality_score:.0f}"
        f" | {short} | {confidence}"
    )


def build_signal_context(
    result: ScreenerResult,
    tradingview_exchange_prefix: str = "BINANCE",
) -> SignalContext:
    """Produce a `SignalContext` for one enriched screener result."""
    direction = _direction_hint(result)
    reasons = _main_reasons(result)
    risks = _risk_notes(result)
    conf = _confidence(result, len(reasons))
    tv_symbol = convert_symbol_to_tradingview(result.symbol, tradingview_exchange_prefix)
    tv_url = tradingview_url(result.symbol, tradingview_exchange_prefix)
    summary = _compact_summary(
        symbol=result.symbol,
        direction_hint=direction,
        score=result.score,
        quality_score=result.quality_score,
        reasons=reasons,
        confidence=conf,
    )
    return SignalContext(
        symbol=result.symbol,
        score=result.score,
        quality_score=result.quality_score,
        direction_hint=direction,
        confidence=conf,
        main_reasons=reasons,
        risk_notes=risks,
        tradingview_symbol=tv_symbol,
        tradingview_url=tv_url,
        compact_summary=summary,
    )
