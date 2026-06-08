"""History layer data models.

Two immutable-by-convention records:

    * ``SignalSnapshot`` — the frozen context of a signal at detection time.
      Only its ``status`` is allowed to change over the lifecycle (we expose a
      small ``with_status`` helper rather than mutating in place).
    * ``SignalOutcome`` — the objective result of one snapshot at one horizon.

Plus the vocabulary constants (horizons, lifecycle statuses, outcome labels,
direction groups) shared by the evaluator / repository / report.

All timestamps in this layer are timezone-aware UTC ``datetime`` objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Horizons
# ---------------------------------------------------------------------------

HORIZON_15M = "15m"
HORIZON_1H = "1h"
HORIZON_4H = "4h"
HORIZON_24H = "24h"

# Ordered tuple — iteration order is stable for reports / CSV.
HORIZONS: Tuple[str, ...] = (HORIZON_15M, HORIZON_1H, HORIZON_4H, HORIZON_24H)

HORIZON_MINUTES: Dict[str, int] = {
    HORIZON_15M: 15,
    HORIZON_1H: 60,
    HORIZON_4H: 240,
    HORIZON_24H: 1440,
}

# ---------------------------------------------------------------------------
# Direction groups (mirrors app.signals.context vocabulary)
# ---------------------------------------------------------------------------

DIRECTION_BULLISH = "BULLISH_MOMENTUM"
DIRECTION_BEARISH = "BEARISH_MOMENTUM"
# Direction hints with a well-defined favorable side.
DIRECTIONAL_HINTS = frozenset({DIRECTION_BULLISH, DIRECTION_BEARISH})

# ---------------------------------------------------------------------------
# Lifecycle status (on the snapshot)
# ---------------------------------------------------------------------------

STATUS_NEW = "NEW"
STATUS_TRACKING = "TRACKING"
STATUS_PARTIALLY_EVALUATED = "PARTIALLY_EVALUATED"
STATUS_COMPLETED = "COMPLETED"
STATUS_EXPIRED = "EXPIRED"
STATUS_DATA_ERROR = "DATA_ERROR"

OPEN_STATUSES = frozenset({STATUS_NEW, STATUS_TRACKING, STATUS_PARTIALLY_EVALUATED})

# ---------------------------------------------------------------------------
# Outcome labels (on each outcome row)
# ---------------------------------------------------------------------------

LABEL_STRONG_MATCH = "STRONG_MATCH"
LABEL_MATCH = "MATCH"
LABEL_PARTIAL_MATCH = "PARTIAL_MATCH"
LABEL_NO_FOLLOW_THROUGH = "NO_FOLLOW_THROUGH"
LABEL_INVALIDATED = "INVALIDATED"
LABEL_EXPIRED = "EXPIRED"
LABEL_PENDING = "PENDING"
LABEL_NOT_APPLICABLE = "NOT_APPLICABLE"

# Labels that represent a finished evaluation (no longer pending).
TERMINAL_LABELS = frozenset({
    LABEL_STRONG_MATCH,
    LABEL_MATCH,
    LABEL_PARTIAL_MATCH,
    LABEL_NO_FOLLOW_THROUGH,
    LABEL_INVALIDATED,
    LABEL_EXPIRED,
    LABEL_NOT_APPLICABLE,
})

# Reason-analysis verdicts.
REASON_MATCHED = "matched"
REASON_FAILED = "failed"
REASON_UNKNOWN = "unknown"


@dataclass(frozen=True)
class SignalSnapshot:
    """Immutable record of a signal at the moment it was detected.

    Built once from a ``ScreenerResult`` + ``SignalContext`` and never changed
    afterwards except for ``status`` (via :meth:`with_status`).
    """

    id: str
    symbol: str
    exchange: str
    detected_at: datetime
    candle_timestamp: datetime
    price_at_signal: float
    score: float
    quality_score: float
    direction_hint: str
    confidence: str
    signals: List[str] = field(default_factory=list)
    main_reasons: List[str] = field(default_factory=list)
    risk_notes: List[str] = field(default_factory=list)
    change_5m: Optional[float] = None
    change_15m: Optional[float] = None
    change_1h: Optional[float] = None
    relative_volume: Optional[float] = None
    volume_z: Optional[float] = None
    atr: Optional[float] = None
    atr_percent: Optional[float] = None
    price_move_atr: Optional[float] = None
    vol_expansion: Optional[float] = None
    open_interest: Optional[float] = None
    oi_change_pct: Optional[float] = None
    funding_rate: Optional[float] = None
    derivatives_score: float = 0.0
    trend_alignment: str = "INSUFFICIENT_DATA"
    oi_confirmation: str = "INSUFFICIENT_DATA"
    tradingview_symbol: str = ""
    tradingview_url: str = ""
    status: str = STATUS_NEW

    def with_status(self, status: str) -> "SignalSnapshot":
        """Return a copy with a new lifecycle status (the only mutable field)."""
        return replace(self, status=status)


@dataclass(frozen=True)
class SignalOutcome:
    """Objective result of one snapshot evaluated at one horizon."""

    signal_id: str
    horizon: str
    evaluated_at: datetime
    target_timestamp: datetime
    price_at_signal: float
    price_at_horizon: Optional[float] = None
    return_pct: Optional[float] = None
    directional_return_pct: Optional[float] = None
    max_favorable_excursion_pct: Optional[float] = None
    max_adverse_excursion_pct: Optional[float] = None
    high_after_signal: Optional[float] = None
    low_after_signal: Optional[float] = None
    direction_matched: Optional[bool] = None
    threshold_matched: Optional[bool] = None
    context_matched: Optional[bool] = None
    outcome_label: str = LABEL_PENDING
    matched_reasons: List[str] = field(default_factory=list)
    failed_reasons: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def is_pending(self) -> bool:
        return self.outcome_label == LABEL_PENDING
