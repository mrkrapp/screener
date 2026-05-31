"""Derivatives metrics: OI change + funding score."""

from __future__ import annotations


def oi_change_pct(current: float, previous: float) -> float:
    if previous <= 0:
        return 0.0
    return (current - previous) / previous * 100.0


def derivatives_score(oi_change: float, funding_rate: float) -> float:
    """Composite 0-100 score reflecting OI and funding pressure.

    Higher when OI is rising on healthy funding; penalized when funding is extreme.
    Notes:
        * `oi_change` is a percentage (e.g. +5.0 means +5%).
        * `funding_rate` is per-funding-interval, e.g. 0.0001 = 0.01%.
    """
    score = 50.0
    # OI direction: linear bump, capped
    score += max(-30.0, min(30.0, oi_change * 2.0))
    # Funding: small positive funding is fine, extreme funding subtracts
    abs_funding = abs(funding_rate) * 100  # to %
    if abs_funding > 0.1:        # > 0.1% per interval — getting hot
        score -= min(20.0, (abs_funding - 0.1) * 100.0)
    return max(0.0, min(100.0, score))
