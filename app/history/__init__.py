"""Signal Memory: persist signals, evaluate their outcomes, report on quality.

Public surface used by the CLI and tests. The pieces:

    models      — SignalSnapshot / SignalOutcome + vocabulary constants
    matcher     — fingerprint, snapshot construction, de-dup decision
    evaluator   — pure outcome calculation (returns, MFE/MAE, labels, reasons)
    repository  — SQLite persistence
    statistics  — quality aggregation
    report      — HTML report + CSV export
    service     — orchestration (record → evaluate → lifecycle)
    providers   — live price-window fetching

Nothing here opens trades, computes account PnL, or emits buy/sell advice.
"""

from app.history.evaluator import evaluate_outcome, lifecycle_status
from app.history.matcher import build_snapshot, compute_fingerprint, should_save
from app.history.models import (
    HORIZONS,
    SignalOutcome,
    SignalSnapshot,
)
from app.history.providers import LivePriceProvider
from app.history.repository import SignalRepository
from app.history.report import export_history_csv, generate_history_report
from app.history.service import (
    HistorySettings,
    HistorySummary,
    NullPriceProvider,
    apply_retention,
    evaluate_pending,
    record_new_signals,
)
from app.history.statistics import build_statistics, headline_match_rate

__all__ = [
    "HORIZONS",
    "SignalOutcome",
    "SignalSnapshot",
    "SignalRepository",
    "HistorySettings",
    "HistorySummary",
    "NullPriceProvider",
    "LivePriceProvider",
    "build_snapshot",
    "compute_fingerprint",
    "should_save",
    "evaluate_outcome",
    "lifecycle_status",
    "record_new_signals",
    "evaluate_pending",
    "apply_retention",
    "build_statistics",
    "headline_match_rate",
    "generate_history_report",
    "export_history_csv",
]
