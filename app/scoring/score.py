"""Composite score + signal derivation.

The score is a pure function of the metrics already computed in the row.
We never make trading decisions — these are observational tags only.
"""

from __future__ import annotations

from typing import List

from app.models import ScreenerRow


def derive_signals(row: ScreenerRow) -> List[str]:
    """Map raw metrics to short neutral tags.

    Tags are analytical observations only — never trade advice.
    """
    signals: List[str] = []

    if row.relative_volume >= 3.0:
        signals.append("volume_spike")
    elif row.relative_volume >= 1.5:
        signals.append("volume_elevated")

    if row.volume_z >= 2.5:
        signals.append("volume_z_outlier")

    if abs(row.change_15m) >= 3.0 or abs(row.change_1h) >= 5.0:
        signals.append("momentum_move")

    if row.vol_expansion >= 1.8:
        signals.append("range_expansion")

    if row.oi_change >= 3.0:
        signals.append("oi_increase")
    elif row.oi_change <= -3.0:
        signals.append("oi_decrease")

    abs_funding = abs(row.funding_rate)
    if abs_funding >= 0.1:        # %
        signals.append("extreme_funding")

    return signals


def compute_score(row: ScreenerRow) -> float:
    """Blend the metrics into a 0-100 composite score.

    Weighting reflects MVP priorities:
        momentum 30 · relative volume 20 · range expansion 15 · derivatives 25 · z-score 10
    """
    momentum_component = min(40.0, abs(row.change_1h) * 3.0)
    rvol_component = min(20.0, (row.relative_volume - 1.0) * 10.0) if row.relative_volume > 1.0 else 0.0
    expansion_component = min(15.0, (row.vol_expansion - 1.0) * 15.0) if row.vol_expansion > 1.0 else 0.0
    deriv_component = row.derivatives_score * 0.25      # 0-25
    z_component = min(10.0, max(0.0, row.volume_z * 4.0))

    raw = momentum_component + rvol_component + expansion_component + deriv_component + z_component
    return max(0.0, min(100.0, raw))


def score_row(row: ScreenerRow) -> ScreenerRow:
    """Populate `score` and `signals` in place and return the same row."""
    row.signals = derive_signals(row)
    row.score = compute_score(row)
    return row
