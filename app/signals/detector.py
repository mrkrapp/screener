"""Signal detector.

Takes a `ScreenerResult` (already populated with base metrics and composite
score) and fills the signal-quality fields by delegating to
`app/metrics/quality.py`.

The detector does NOT compute base metrics or scores — those are owned by
`app.metrics` and `app.scoring`. The detector does NOT format any output —
that's `app.output` and `app.signals.context`.
"""

from __future__ import annotations

from typing import Iterable, List

from app.metrics import quality as q
from app.models import ScreenerResult


def enrich_with_quality(
    result: ScreenerResult,
    *,
    funding_threshold: float,
) -> ScreenerResult:
    """Populate quality fields on `result` in place and return it."""
    # Note: ScreenerResult.funding_rate is stored in percent (e.g. 0.0100 means
    # 0.01%). The spec's funding_threshold is in raw rate units (0.0003 etc.).
    # Convert percent → raw rate by dividing by 100.
    funding_rate_raw = (result.funding_rate / 100.0) if result.funding_rate is not None else None

    atr_pct = q.atr_percent(result.atr, result.price)
    pm_atr = q.price_move_in_atr(result.change_1h, atr_pct)
    dv_curr = q.dollar_volume(result.price, result.volume_current)
    dv_avg = q.dollar_volume(result.price, result.volume_avg)
    vol_conf = q.volume_confirmation(result.relative_volume, result.change_1h)
    trend = q.trend_alignment_label(result.change_5m, result.change_15m, result.change_1h)
    oi_conf = q.oi_confirmation_label(result.change_1h, result.oi_change)
    fund_pres = q.funding_pressure(funding_rate_raw, funding_threshold)
    qs = q.quality_score(
        trend_alignment=trend,
        volume_confirmation_value=vol_conf,
        price_move_atr=pm_atr,
        oi_confirmation=oi_conf,
        funding_pressure_value=fund_pres,
        vol_expansion=result.vol_expansion,
        relative_volume=result.relative_volume,
        change_1h=result.change_1h,
    )

    result.atr_percent = atr_pct
    result.price_move_atr = pm_atr
    result.dollar_volume_current = dv_curr
    result.dollar_volume_avg = dv_avg
    result.volume_confirmation = vol_conf
    result.trend_alignment = trend
    result.oi_confirmation = oi_conf
    result.funding_pressure = fund_pres
    result.quality_score = qs
    return result


def enrich_many(
    results: Iterable[ScreenerResult],
    *,
    funding_threshold: float,
) -> List[ScreenerResult]:
    """Apply `enrich_with_quality` across a sequence. Returns the same list."""
    return [enrich_with_quality(r, funding_threshold=funding_threshold) for r in results]
