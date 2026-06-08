"""Aggregate quality statistics over evaluated signals.

Everything is computed from the persisted snapshots + outcomes; this module is
pure (no DB access of its own — callers pass the records in).

Honest small-sample handling: a group with fewer than ``min_sample`` evaluated
directional outcomes is flagged ``insufficient`` and its rates are reported as
``None`` so the UI can print "Insufficient sample: N signals" instead of a
misleading percentage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Dict, List, Optional, Sequence

from app.history.models import (
    DIRECTIONAL_HINTS,
    HORIZONS,
    LABEL_INVALIDATED,
    LABEL_MATCH,
    LABEL_STRONG_MATCH,
    OPEN_STATUSES,
    STATUS_COMPLETED,
    STATUS_EXPIRED,
    SignalOutcome,
    SignalSnapshot,
)

DEFAULT_MIN_SAMPLE = 10

_MATCH_LABELS = frozenset({LABEL_STRONG_MATCH, LABEL_MATCH})

SCORE_BUCKETS = (("60-69", 60, 70), ("70-79", 70, 80), ("80-89", 80, 90), ("90-100", 90, 101))
QUALITY_BUCKETS = (("50-59", 50, 60), ("60-69", 60, 70), ("70-79", 70, 80), ("80-100", 80, 101))


@dataclass
class GroupStats:
    """Aggregated metrics for one slice of the history (a horizon, a symbol…)."""

    key: str
    sample: int = 0
    match_rate: Optional[float] = None
    strong_rate: Optional[float] = None
    invalidation_rate: Optional[float] = None
    avg_return: Optional[float] = None
    avg_directional_return: Optional[float] = None
    avg_mfe: Optional[float] = None
    avg_mae: Optional[float] = None
    profit_factor: Optional[float] = None
    insufficient: bool = True


@dataclass
class HistoryStatistics:
    total_signals: int = 0
    completed_signals: int = 0
    pending_signals: int = 0
    expired_signals: int = 0
    min_sample: int = DEFAULT_MIN_SAMPLE
    overall: GroupStats = field(default_factory=lambda: GroupStats("overall"))
    by_horizon: Dict[str, GroupStats] = field(default_factory=dict)
    by_direction: Dict[str, GroupStats] = field(default_factory=dict)
    by_confidence: Dict[str, GroupStats] = field(default_factory=dict)
    by_signal_label: Dict[str, GroupStats] = field(default_factory=dict)
    by_score_bucket: Dict[str, GroupStats] = field(default_factory=dict)
    by_quality_bucket: Dict[str, GroupStats] = field(default_factory=dict)
    by_symbol: Dict[str, GroupStats] = field(default_factory=dict)
    # Not derivable without intra-window candle timing — see limitations.
    median_time_to_mfe_minutes: Optional[float] = None


def _is_directional_terminal(outcome: SignalOutcome) -> bool:
    """True when the outcome is an evaluated directional result (not pending)."""
    return outcome.direction_matched is not None and outcome.outcome_label in (
        _MATCH_LABELS | {LABEL_INVALIDATED, "PARTIAL_MATCH", "NO_FOLLOW_THROUGH"}
    )


def _avg(values: Sequence[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return mean(vals) if vals else None


def _aggregate(key: str, outcomes: Sequence[SignalOutcome], *, min_sample: int) -> GroupStats:
    directional = [o for o in outcomes if _is_directional_terminal(o)]
    sample = len(directional)
    stats = GroupStats(key=key, sample=sample, insufficient=sample < min_sample)
    if sample == 0:
        return stats

    matches = sum(1 for o in directional if o.outcome_label in _MATCH_LABELS)
    strong = sum(1 for o in directional if o.outcome_label == LABEL_STRONG_MATCH)
    invalid = sum(1 for o in directional if o.outcome_label == LABEL_INVALIDATED)

    stats.match_rate = matches / sample * 100.0
    stats.strong_rate = strong / sample * 100.0
    stats.invalidation_rate = invalid / sample * 100.0
    stats.avg_return = _avg([o.return_pct for o in directional])
    stats.avg_directional_return = _avg([o.directional_return_pct for o in directional])
    stats.avg_mfe = _avg([o.max_favorable_excursion_pct for o in directional])
    stats.avg_mae = _avg([o.max_adverse_excursion_pct for o in directional])
    stats.profit_factor = _profit_factor(directional)
    return stats


def _profit_factor(outcomes: Sequence[SignalOutcome]) -> Optional[float]:
    """Proxy: sum of positive directional returns / abs(sum of negative ones)."""
    gains = sum(o.directional_return_pct for o in outcomes
                if o.directional_return_pct is not None and o.directional_return_pct > 0)
    losses = sum(o.directional_return_pct for o in outcomes
                 if o.directional_return_pct is not None and o.directional_return_pct < 0)
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / abs(losses)


def _bucket(value: Optional[float], buckets) -> Optional[str]:
    if value is None:
        return None
    for label, lo, hi in buckets:
        if lo <= value < hi:
            return label
    return None


def build_statistics(
    snapshots: Sequence[SignalSnapshot],
    outcomes: Sequence[SignalOutcome],
    *,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> HistoryStatistics:
    """Compute the full statistics bundle from snapshots + their outcomes."""
    snap_by_id = {s.id: s for s in snapshots}

    stats = HistoryStatistics(min_sample=min_sample)
    stats.total_signals = len(snapshots)
    stats.completed_signals = sum(1 for s in snapshots if s.status == STATUS_COMPLETED)
    stats.pending_signals = sum(1 for s in snapshots if s.status in OPEN_STATUSES)
    stats.expired_signals = sum(1 for s in snapshots if s.status == STATUS_EXPIRED)

    stats.overall = _aggregate("overall", outcomes, min_sample=min_sample)

    # by horizon
    for hz in HORIZONS:
        group = [o for o in outcomes if o.horizon == hz]
        stats.by_horizon[hz] = _aggregate(hz, group, min_sample=min_sample)

    # grouping helpers keyed off the parent snapshot
    def _group_by(key_fn) -> Dict[str, List[SignalOutcome]]:
        groups: Dict[str, List[SignalOutcome]] = {}
        for o in outcomes:
            snap = snap_by_id.get(o.signal_id)
            if snap is None:
                continue
            keys = key_fn(snap)
            for k in keys:
                if k is None:
                    continue
                groups.setdefault(k, []).append(o)
        return groups

    for key, group in _group_by(lambda s: [s.direction_hint]).items():
        stats.by_direction[key] = _aggregate(key, group, min_sample=min_sample)
    for key, group in _group_by(lambda s: [s.confidence]).items():
        stats.by_confidence[key] = _aggregate(key, group, min_sample=min_sample)
    for key, group in _group_by(lambda s: list(s.signals)).items():
        stats.by_signal_label[key] = _aggregate(key, group, min_sample=min_sample)
    for key, group in _group_by(lambda s: [_bucket(s.score, SCORE_BUCKETS)]).items():
        stats.by_score_bucket[key] = _aggregate(key, group, min_sample=min_sample)
    for key, group in _group_by(lambda s: [_bucket(s.quality_score, QUALITY_BUCKETS)]).items():
        stats.by_quality_bucket[key] = _aggregate(key, group, min_sample=min_sample)
    for key, group in _group_by(lambda s: [s.symbol]).items():
        stats.by_symbol[key] = _aggregate(key, group, min_sample=min_sample)

    return stats


def headline_match_rate(stats: HistoryStatistics, horizon: str = "1h") -> str:
    """A short human string for the run summary, honest about small samples."""
    g = stats.by_horizon.get(horizon)
    if g is None or g.sample == 0:
        return f"Match rate {horizon}: n/a (0 samples)"
    if g.insufficient:
        return f"Match rate {horizon}: insufficient sample ({g.sample})"
    return f"Match rate {horizon}: {g.match_rate:.0f}% ({g.sample} samples)"
