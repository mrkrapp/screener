"""Derivatives metrics: OI change + funding score."""

from __future__ import annotations

from typing import Optional


def oi_change_pct(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or previous <= 0:
        return None
    return (current - previous) / previous * 100.0


def derivatives_score(
    oi_change: Optional[float],
    funding_rate: Optional[float],
) -> Optional[float]:
    """Composite 0-100 score reflecting OI and funding pressure.

    Higher when OI is rising on healthy funding; penalized when funding is extreme.
    Notes:
        * `oi_change` is a percentage (e.g. +5.0 means +5%).
        * `funding_rate` is per-funding-interval, e.g. 0.0001 = 0.01%.
    """
    if oi_change is None and funding_rate is None:
        return None

    score = 50.0
    # OI direction: linear bump, capped
    if oi_change is not None:
        score += max(-30.0, min(30.0, oi_change * 2.0))
    # Funding: small positive funding is fine, extreme funding subtracts
    if funding_rate is not None:
        abs_funding = abs(funding_rate) * 100  # to %
        if abs_funding > 0.1:        # > 0.1% per interval — getting hot
            score -= min(20.0, (abs_funding - 0.1) * 100.0)
    return max(0.0, min(100.0, score))
