"""Signal enrichment + context builder.

`detector` adds quality metrics to an already-scored `ScreenerResult`.
`context` turns the enriched result into a human-readable `SignalContext`.
"""

from app.signals.context import SignalContext, build_signal_context
from app.signals.detector import enrich_with_quality, enrich_many

__all__ = [
    "SignalContext",
    "build_signal_context",
    "enrich_many",
    "enrich_with_quality",
]
