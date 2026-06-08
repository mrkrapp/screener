"""Outcome evaluation.

Given an immutable :class:`SignalSnapshot` and the *closed* candles that
followed it, compute a :class:`SignalOutcome` per horizon: realised return,
direction-aware return, MFE/MAE, an outcome label, and a matched/failed
breakdown of the original ``main_reasons``.

Hard rules (enforced here):
    * **No look-ahead bias.** Only candles whose close time is ``<= now`` are
      ever considered, and only candles in ``(signal, target]`` feed a horizon.
    * **No un-closed candle** is used as the horizon price.
    * Original snapshot metrics are read-only; nothing here writes back.

The function is pure: callers pass ``now`` and the candle window explicitly, so
the same inputs always yield the same outcome (deterministic, testable).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple

from app.history.models import (
    DIRECTIONAL_HINTS,
    DIRECTION_BEARISH,
    DIRECTION_BULLISH,
    HORIZON_MINUTES,
    LABEL_EXPIRED,
    LABEL_INVALIDATED,
    LABEL_MATCH,
    LABEL_NOT_APPLICABLE,
    LABEL_NO_FOLLOW_THROUGH,
    LABEL_PARTIAL_MATCH,
    LABEL_PENDING,
    LABEL_STRONG_MATCH,
    REASON_FAILED,
    REASON_MATCHED,
    REASON_UNKNOWN,
    SignalOutcome,
    SignalSnapshot,
)
from app.models import Candle

# Default match thresholds (%) per horizon. Overridable via config.
DEFAULT_MATCH_THRESHOLDS = {
    "15m": 0.5,
    "1h": 1.0,
    "4h": 2.0,
    "24h": 3.0,
}

# A candle older than (target + EXPIRY_GRACE * horizon) with no data is expired.
_EXPIRY_GRACE = 2

# 1-minute candle assumed; close time = open_time + this many seconds.
_DEFAULT_CANDLE_SECONDS = 60


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _candle_dt(candle: Candle) -> datetime:
    return datetime.fromtimestamp(candle.open_time, tz=timezone.utc)


def _is_closed(candle: Candle, now: datetime, candle_seconds: int) -> bool:
    """A candle is closed if its *close* time is at or before ``now``."""
    close_dt = _candle_dt(candle) + timedelta(seconds=candle_seconds)
    return close_dt <= now


def _window_after_signal(
    candles: Sequence[Candle],
    *,
    signal_ts: datetime,
    target_ts: datetime,
    now: datetime,
    candle_seconds: int,
) -> List[Candle]:
    """Closed candles strictly after the signal and up to the horizon target.

    Excludes the signal candle itself and any candle not yet closed.
    """
    out: List[Candle] = []
    for c in candles:
        c_dt = _candle_dt(c)
        if c_dt <= signal_ts:
            continue
        if c_dt > target_ts:
            continue
        if not _is_closed(c, now, candle_seconds):
            continue
        out.append(c)
    return out


def _excursions(
    *,
    direction: str,
    entry: float,
    high: float,
    low: float,
) -> Tuple[Optional[float], Optional[float]]:
    """Return ``(mfe_pct, mae_pct)`` normalised to the expected direction.

    For the expected side, MFE is positive when price moved favourably and MAE
    is negative when it moved against. Neutral hints get ``(None, None)``.
    """
    if entry <= 0:
        return None, None
    if direction == DIRECTION_BULLISH:
        mfe = (high - entry) / entry * 100.0
        mae = (low - entry) / entry * 100.0
        return mfe, mae
    if direction == DIRECTION_BEARISH:
        mfe = (entry - low) / entry * 100.0
        mae = (entry - high) / entry * 100.0
        return mfe, mae
    return None, None


def _classify_directional(
    *,
    direction: str,
    return_pct: float,
    directional_return: float,
    mfe: Optional[float],
    mae: Optional[float],
    threshold: float,
) -> Tuple[bool, bool, str]:
    """Return ``(direction_matched, threshold_matched, label)`` for a directional hint."""
    if direction == DIRECTION_BULLISH:
        direction_matched = return_pct > 0
        threshold_matched = return_pct >= threshold
    else:  # bearish
        direction_matched = return_pct < 0
        threshold_matched = return_pct <= -threshold

    abs_mae = abs(mae) if mae is not None else 0.0
    fav = mfe if mfe is not None else 0.0

    if direction_matched and threshold_matched:
        # Strong only when the favourable excursion clearly dominates the
        # adverse one (clean run, little heat against the position).
        if abs_mae <= 1e-9 or fav >= 1.5 * abs_mae:
            return direction_matched, threshold_matched, LABEL_STRONG_MATCH
        return direction_matched, threshold_matched, LABEL_MATCH

    if direction_matched and not threshold_matched:
        # Moved the right way but gave it back -> spike then fade.
        if fav >= threshold and directional_return < 0.5 * threshold:
            return direction_matched, threshold_matched, LABEL_NO_FOLLOW_THROUGH
        return direction_matched, threshold_matched, LABEL_PARTIAL_MATCH

    # Wrong direction overall.
    if abs_mae >= threshold:
        return direction_matched, threshold_matched, LABEL_INVALIDATED
    return direction_matched, threshold_matched, LABEL_NO_FOLLOW_THROUGH


def _analyze_reasons(
    snapshot: SignalSnapshot,
    *,
    direction: str,
    direction_matched: Optional[bool],
    threshold_matched: Optional[bool],
    mfe: Optional[float],
    threshold: float,
) -> Tuple[List[str], List[str]]:
    """Classify each ``main_reason`` as matched / failed (unknown is dropped).

    Heuristic, substring-based — mirrors how the context builder phrases each
    reason. When the underlying fact is unknown (e.g. neutral hint, no data)
    the reason is treated as ``unknown`` and reported in neither list.
    """
    matched: List[str] = []
    failed: List[str] = []

    if direction_matched is None or mfe is None:
        return matched, failed  # nothing decidable yet

    followed_through = bool(threshold_matched) or (mfe is not None and mfe >= threshold)

    for reason in snapshot.main_reasons:
        verdict = _verdict_for_reason(
            reason,
            direction=direction,
            direction_matched=direction_matched,
            followed_through=followed_through,
        )
        if verdict == REASON_MATCHED:
            matched.append(reason)
        elif verdict == REASON_FAILED:
            failed.append(reason)
    return matched, failed


def _verdict_for_reason(
    reason: str,
    *,
    direction: str,
    direction_matched: bool,
    followed_through: bool,
) -> str:
    low = reason.lower()

    # Volume-based confirmations — judged by follow-through.
    if "rvol" in low or "volume confirmation" in low or "dollar volume" in low:
        return REASON_MATCHED if followed_through else REASON_FAILED

    # OI confirmations — directionally specific.
    if "fresh longs" in low:
        if direction == DIRECTION_BULLISH:
            return REASON_MATCHED if direction_matched else REASON_FAILED
        return REASON_UNKNOWN
    if "fresh shorts" in low:
        if direction == DIRECTION_BEARISH:
            return REASON_MATCHED if direction_matched else REASON_FAILED
        return REASON_UNKNOWN

    # Trend alignment — judged by continuation.
    if "trend is aligned" in low:
        return REASON_MATCHED if (direction_matched and followed_through) else REASON_FAILED

    # Funding elevated — a reversal predictor, not a continuation one.
    if "funding" in low:
        # Matched when the move did NOT cleanly follow through (reversal/fade).
        return REASON_FAILED if (direction_matched and followed_through) else REASON_MATCHED

    # Plain price/ATR move statements — continuation.
    if "price moved" in low or "atr" in low or "move is" in low:
        return REASON_MATCHED if (direction_matched and followed_through) else REASON_FAILED

    # Open interest up/down — aligns with direction.
    if "open interest" in low:
        return REASON_MATCHED if direction_matched else REASON_FAILED

    return REASON_UNKNOWN


def evaluate_outcome(
    snapshot: SignalSnapshot,
    horizon: str,
    candles: Sequence[Candle],
    *,
    now: Optional[datetime] = None,
    match_threshold_pct: Optional[float] = None,
    candle_seconds: int = _DEFAULT_CANDLE_SECONDS,
) -> SignalOutcome:
    """Evaluate one snapshot at one horizon.

    Args:
        snapshot: the immutable signal record.
        horizon: one of ``app.history.models.HORIZONS``.
        candles: closed OHLCV covering ``(signal, target]`` (extra candles are
            filtered out safely).
        now: evaluation clock (UTC). Defaults to ``datetime.now(UTC)``.
        match_threshold_pct: override the per-horizon threshold.
        candle_seconds: candle width in seconds (default 60 = 1m).
    """
    now = _ensure_utc(now or datetime.now(timezone.utc))
    signal_ts = _ensure_utc(snapshot.candle_timestamp)
    minutes = HORIZON_MINUTES[horizon]
    target_ts = signal_ts + timedelta(minutes=minutes)
    threshold = (
        match_threshold_pct
        if match_threshold_pct is not None
        else DEFAULT_MATCH_THRESHOLDS.get(horizon, 1.0)
    )
    entry = float(snapshot.price_at_signal)
    direction = snapshot.direction_hint
    is_directional = direction in DIRECTIONAL_HINTS

    base = dict(
        signal_id=snapshot.id,
        horizon=horizon,
        evaluated_at=now,
        target_timestamp=target_ts,
        price_at_signal=entry,
    )

    # Horizon not reached yet -> PENDING (no data peeked at).
    if now < target_ts:
        return SignalOutcome(
            **base,
            outcome_label=LABEL_PENDING,
            notes=["Horizon not reached yet"],
        )

    window = _window_after_signal(
        candles,
        signal_ts=signal_ts,
        target_ts=target_ts,
        now=now,
        candle_seconds=candle_seconds,
    )

    if not window:
        # Target passed but no closed candles available.
        if now >= target_ts + timedelta(minutes=minutes * _EXPIRY_GRACE):
            return SignalOutcome(
                **base,
                outcome_label=LABEL_EXPIRED,
                notes=["No price data available within expiry window"],
            )
        return SignalOutcome(
            **base,
            outcome_label=LABEL_PENDING,
            notes=["Awaiting closed candles for this horizon"],
        )

    if entry <= 0:
        return SignalOutcome(
            **base,
            outcome_label=LABEL_NOT_APPLICABLE,
            notes=["Signal price is non-positive; cannot compute returns"],
        )

    high_after = max(c.high for c in window)
    low_after = min(c.low for c in window)
    # Horizon price = close of the last closed candle at/under the target.
    price_at_horizon = window[-1].close
    return_pct = (price_at_horizon - entry) / entry * 100.0

    mfe, mae = _excursions(
        direction=direction, entry=entry, high=high_after, low=low_after
    )

    if not is_directional:
        # Neutral hint: realised return is recorded, but there is no expected
        # side to "match". Reason analysis still runs on the absolute move.
        matched_reasons, failed_reasons = _analyze_reasons(
            snapshot,
            direction=direction,
            direction_matched=abs(return_pct) >= threshold,
            threshold_matched=abs(return_pct) >= threshold,
            mfe=abs(return_pct),
            threshold=threshold,
        )
        return SignalOutcome(
            **base,
            price_at_horizon=price_at_horizon,
            return_pct=return_pct,
            directional_return_pct=None,
            max_favorable_excursion_pct=None,
            max_adverse_excursion_pct=None,
            high_after_signal=high_after,
            low_after_signal=low_after,
            direction_matched=None,
            threshold_matched=None,
            context_matched=bool(matched_reasons) and not failed_reasons,
            outcome_label=LABEL_NOT_APPLICABLE,
            matched_reasons=matched_reasons,
            failed_reasons=failed_reasons,
            notes=["Neutral direction hint — evaluated by realised move only"],
        )

    directional_return = return_pct if direction == DIRECTION_BULLISH else -return_pct
    direction_matched, threshold_matched, label = _classify_directional(
        direction=direction,
        return_pct=return_pct,
        directional_return=directional_return,
        mfe=mfe,
        mae=mae,
        threshold=threshold,
    )
    matched_reasons, failed_reasons = _analyze_reasons(
        snapshot,
        direction=direction,
        direction_matched=direction_matched,
        threshold_matched=threshold_matched,
        mfe=mfe,
        threshold=threshold,
    )
    context_matched = bool(matched_reasons) and len(matched_reasons) >= len(failed_reasons)

    return SignalOutcome(
        **base,
        price_at_horizon=price_at_horizon,
        return_pct=return_pct,
        directional_return_pct=directional_return,
        max_favorable_excursion_pct=mfe,
        max_adverse_excursion_pct=mae,
        high_after_signal=high_after,
        low_after_signal=low_after,
        direction_matched=direction_matched,
        threshold_matched=threshold_matched,
        context_matched=context_matched,
        outcome_label=label,
        matched_reasons=matched_reasons,
        failed_reasons=failed_reasons,
        notes=[],
    )


def lifecycle_status(outcomes: Sequence[SignalOutcome]) -> str:
    """Derive a snapshot lifecycle status from its per-horizon outcomes."""
    from app.history.models import (
        STATUS_COMPLETED,
        STATUS_EXPIRED,
        STATUS_PARTIALLY_EVALUATED,
        STATUS_TRACKING,
        TERMINAL_LABELS,
    )

    if not outcomes:
        return STATUS_TRACKING
    labels = [o.outcome_label for o in outcomes]
    n_terminal = sum(1 for lbl in labels if lbl in TERMINAL_LABELS)
    n_pending = sum(1 for lbl in labels if lbl == LABEL_PENDING)
    n_expired = sum(1 for lbl in labels if lbl == LABEL_EXPIRED)

    if n_terminal == len(labels):
        if n_expired == len(labels):
            return STATUS_EXPIRED
        return STATUS_COMPLETED
    if n_terminal > 0 and n_pending > 0:
        return STATUS_PARTIALLY_EVALUATED
    return STATUS_TRACKING
