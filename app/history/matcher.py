"""Snapshot construction, fingerprinting and de-duplication.

The matcher answers two questions:

    1. *What* immutable snapshot represents this freshly detected signal?
       -> :func:`build_snapshot`
    2. *Should* we persist it, or is it a duplicate / below the quality bar?
       -> :func:`should_save`

It performs no I/O — the repository supplies the list of recent snapshots so
this module stays pure and unit-testable.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple

from app.history.models import SignalSnapshot, STATUS_NEW
from app.models import ScreenerResult
from app.signals.context import SignalContext


def compute_fingerprint(
    symbol: str,
    direction_hint: str,
    signals: Sequence[str],
    candle_timestamp: datetime,
) -> str:
    """Stable identity for "the same signal".

    ``fingerprint = sha256(symbol | direction | sorted(signals) | candle_ts)``.
    Two runs over the *same* candle that produce the same direction and signal
    set collapse to one fingerprint, so re-running the screener never doubles
    up history.
    """
    parts = [
        symbol.strip(),
        direction_hint.strip(),
        "|".join(sorted(s.strip() for s in signals)),
        _iso_minute(candle_timestamp),
    ]
    raw = "::".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _iso_minute(dt: datetime) -> str:
    """Normalise a timestamp to UTC minute resolution for fingerprinting."""
    dt = _ensure_utc(dt)
    return dt.strftime("%Y-%m-%dT%H:%M")


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_snapshot(
    result: ScreenerResult,
    context: SignalContext,
    *,
    exchange: str,
    candle_timestamp: datetime,
    detected_at: Optional[datetime] = None,
    snapshot_id: Optional[str] = None,
) -> SignalSnapshot:
    """Freeze a ``ScreenerResult`` + ``SignalContext`` into a ``SignalSnapshot``.

    The snapshot copies *values* (never references the live row) so later
    re-scoring of the same symbol can never rewrite history.
    """
    detected = _ensure_utc(detected_at or datetime.now(timezone.utc))
    candle_ts = _ensure_utc(candle_timestamp)
    sid = snapshot_id or uuid.uuid4().hex

    return SignalSnapshot(
        id=sid,
        symbol=result.symbol,
        exchange=exchange,
        detected_at=detected,
        candle_timestamp=candle_ts,
        price_at_signal=float(result.price),
        score=float(result.score),
        quality_score=float(result.quality_score),
        direction_hint=context.direction_hint,
        confidence=context.confidence,
        signals=list(result.signals),
        main_reasons=list(context.main_reasons),
        risk_notes=list(context.risk_notes),
        change_5m=result.change_5m,
        change_15m=result.change_15m,
        change_1h=result.change_1h,
        relative_volume=result.relative_volume,
        volume_z=result.volume_z,
        atr=result.atr,
        atr_percent=result.atr_percent,
        price_move_atr=result.price_move_atr,
        vol_expansion=result.vol_expansion,
        open_interest=result.open_interest,
        oi_change_pct=result.oi_change,
        funding_rate=result.funding_rate,
        derivatives_score=result.derivatives_score,
        trend_alignment=result.trend_alignment,
        oi_confirmation=result.oi_confirmation,
        tradingview_symbol=context.tradingview_symbol,
        tradingview_url=context.tradingview_url,
        status=STATUS_NEW,
    )


def should_save(
    snapshot: SignalSnapshot,
    *,
    recent_snapshots: Sequence[SignalSnapshot],
    cooldown_minutes: int,
    min_score: float,
    min_quality: float,
) -> Tuple[bool, str]:
    """Decide whether ``snapshot`` is worth persisting.

    Saves when **all** of:
        * score >= ``min_score``
        * quality_score >= ``min_quality``
        * no equivalent signal for this symbol within ``cooldown_minutes`` —
          *unless* the direction or signal set materially changed.

    ``recent_snapshots`` should already be scoped to the same symbol; any other
    symbols are ignored defensively.

    Returns ``(save?, reason)`` — ``reason`` is a short human-readable string
    for the run summary / logs.
    """
    if snapshot.score < min_score:
        return False, f"score {snapshot.score:.1f} < min {min_score:.0f}"
    if snapshot.quality_score < min_quality:
        return False, f"quality {snapshot.quality_score:.1f} < min {min_quality:.0f}"

    cutoff = snapshot.detected_at - timedelta(minutes=cooldown_minutes)
    new_signals = frozenset(snapshot.signals)
    for prev in recent_snapshots:
        if prev.symbol != snapshot.symbol:
            continue
        if _ensure_utc(prev.detected_at) < cutoff:
            continue  # outside cooldown window
        # Within cooldown: only allow if something material changed.
        direction_changed = prev.direction_hint != snapshot.direction_hint
        signals_changed = frozenset(prev.signals) != new_signals
        if not direction_changed and not signals_changed:
            return False, f"cooldown: duplicate within {cooldown_minutes}m"
    return True, "saved"
