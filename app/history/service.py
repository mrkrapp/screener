"""History orchestration: record new signals, evaluate pending ones, update
lifecycle, and (re)build the report + CSV.

This is the only history module that touches the repository and (optionally) a
price provider. It is deliberately defensive: any failure is caught by the
caller (``app.main``) so a history error never breaks the core screener.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Protocol, Sequence, Tuple

from app.history.evaluator import evaluate_outcome, lifecycle_status
from app.history.matcher import build_snapshot, should_save
from app.history.models import (
    HORIZONS,
    HORIZON_MINUTES,
    SignalSnapshot,
    STATUS_DATA_ERROR,
)
from app.history.repository import SignalRepository
from app.models import Candle, ScreenerResult
from app.signals.context import SignalContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HistorySettings:
    """Subset of AppConfig the history layer needs (keeps it decoupled)."""

    exchange: str = "BINANCE"
    cooldown_minutes: int = 60
    min_score: float = 60.0
    min_quality: float = 50.0
    match_thresholds: dict = field(default_factory=lambda: {
        "15m": 0.5, "1h": 1.0, "4h": 2.0, "24h": 3.0,
    })
    retention_days: int = 180
    min_sample: int = 10


@dataclass
class HistorySummary:
    new: int = 0
    updated: int = 0
    completed: int = 0
    pending: int = 0
    evaluated: int = 0
    errors: int = 0


class PriceProvider(Protocol):
    """Supplies the closed candles that followed a signal."""

    candle_seconds: int

    def get_window(self, symbol: str, start: datetime, end: datetime) -> List[Candle]:
        ...


class NullPriceProvider:
    """No future data — every not-yet-reached horizon stays PENDING.

    Used in offline-test mode, where all signals are detected "now" and so
    nothing can be evaluated until real time passes.
    """

    candle_seconds = 60

    def get_window(self, symbol: str, start: datetime, end: datetime) -> List[Candle]:
        return []


def record_new_signals(
    repo: SignalRepository,
    candidates: Sequence[Tuple[ScreenerResult, SignalContext, datetime]],
    *,
    settings: HistorySettings,
    now: Optional[datetime] = None,
) -> int:
    """Persist qualifying new snapshots. Returns the number actually saved."""
    now = now or datetime.now(timezone.utc)
    saved = 0
    cutoff = now - timedelta(minutes=settings.cooldown_minutes)
    for result, context, candle_ts in candidates:
        snapshot = build_snapshot(
            result, context,
            exchange=settings.exchange,
            candle_timestamp=candle_ts,
            detected_at=now,
        )
        recent = repo.recent_snapshots_for_symbol(snapshot.symbol, since=cutoff)
        ok, reason = should_save(
            snapshot,
            recent_snapshots=recent,
            cooldown_minutes=settings.cooldown_minutes,
            min_score=settings.min_score,
            min_quality=settings.min_quality,
        )
        if not ok:
            logger.debug("Skip %s: %s", snapshot.symbol, reason)
            continue
        if repo.insert_snapshot(snapshot):
            saved += 1
            logger.debug("Saved snapshot %s (%s)", snapshot.symbol, snapshot.id[:8])
    return saved


def evaluate_pending(
    repo: SignalRepository,
    *,
    settings: HistorySettings,
    price_provider: PriceProvider,
    now: Optional[datetime] = None,
) -> HistorySummary:
    """Re-evaluate every open snapshot across all horizons. Updates lifecycle."""
    now = now or datetime.now(timezone.utc)
    summary = HistorySummary()
    open_snapshots = repo.get_open_snapshots()

    for snapshot in open_snapshots:
        summary.evaluated += 1
        try:
            candles = _fetch_window(snapshot, price_provider, now=now)
            outcomes = []
            for hz in HORIZONS:
                outcome = evaluate_outcome(
                    snapshot, hz, candles,
                    now=now,
                    match_threshold_pct=settings.match_thresholds.get(hz),
                    candle_seconds=getattr(price_provider, "candle_seconds", 60),
                )
                repo.upsert_outcome(outcome)
                outcomes.append(outcome)
            new_status = lifecycle_status(outcomes)
            if new_status != snapshot.status:
                repo.update_status(snapshot.id, new_status)
            _tally(summary, new_status)
        except Exception as exc:  # noqa: BLE001 — a bad symbol mustn't abort the rest
            summary.errors += 1
            logger.warning("Evaluation failed for %s: %s", snapshot.symbol, exc)
            repo.update_status(snapshot.id, STATUS_DATA_ERROR)
    return summary


def _tally(summary: HistorySummary, status: str) -> None:
    from app.history.models import (
        OPEN_STATUSES,
        STATUS_COMPLETED,
    )
    summary.updated += 1
    if status == STATUS_COMPLETED:
        summary.completed += 1
    elif status in OPEN_STATUSES:
        summary.pending += 1


def _fetch_window(
    snapshot: SignalSnapshot,
    provider: PriceProvider,
    *,
    now: datetime,
) -> List[Candle]:
    """Fetch candles from the signal up to min(now, last horizon target)."""
    start = snapshot.candle_timestamp
    max_minutes = max(HORIZON_MINUTES.values())
    end = min(now, start + timedelta(minutes=max_minutes))
    if end <= start:
        return []
    return provider.get_window(snapshot.symbol, start, end)


def apply_retention(repo: SignalRepository, *, settings: HistorySettings,
                    now: Optional[datetime] = None) -> int:
    """Delete snapshots older than the retention window. Returns count removed."""
    if settings.retention_days <= 0:
        return 0
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=settings.retention_days)
    return repo.delete_snapshots_before(cutoff)


def run_full_cycle(
    repo: SignalRepository,
    *,
    settings: HistorySettings,
    candidates: Sequence[Tuple[ScreenerResult, SignalContext, datetime]] = (),
    price_provider: Optional[PriceProvider] = None,
    now: Optional[datetime] = None,
    create_new: bool = True,
    evaluate: bool = True,
    rebuild_outputs: bool = True,
    report_path: Optional[str] = None,
    export_path: Optional[str] = None,
    report_title: str = "Signal Memory",
):
    """End-to-end history pass. Returns ``(summary, statistics)``.

    Steps (each optional via flags):
        1. record qualifying new snapshots
        2. evaluate every open snapshot across horizons + update lifecycle
        3. apply retention
        4. rebuild statistics, HTML report and CSV export
    """
    from app.history.report import export_history_csv, generate_history_report
    from app.history.statistics import build_statistics

    now = now or datetime.now(timezone.utc)
    provider = price_provider or NullPriceProvider()
    summary = HistorySummary()

    if create_new and candidates:
        summary.new = record_new_signals(repo, candidates, settings=settings, now=now)

    if evaluate:
        eval_summary = evaluate_pending(repo, settings=settings, price_provider=provider, now=now)
        summary.updated = eval_summary.updated
        summary.completed = eval_summary.completed
        summary.pending = eval_summary.pending
        summary.evaluated = eval_summary.evaluated
        summary.errors = eval_summary.errors

    apply_retention(repo, settings=settings, now=now)

    snapshots = repo.get_all_snapshots()
    outcomes = repo.get_all_outcomes()
    statistics = build_statistics(snapshots, outcomes, min_sample=settings.min_sample)

    if rebuild_outputs:
        if report_path:
            generate_history_report(
                snapshots, outcomes, statistics,
                output_path=report_path, title=report_title,
            )
        if export_path:
            export_history_csv(snapshots, outcomes, output_path=export_path)

    return summary, statistics
