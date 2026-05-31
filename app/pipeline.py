"""Pipeline glue: raw inputs → metrics → scored rows.

Kept separate from the CLI and from each metric module so individual modules
stay testable in isolation.
"""

from __future__ import annotations

from typing import List

from app.metrics import derivatives, price, volatility, volume
from app.models import MarketScanInput, ScreenerRow
from app.scoring import score_row


def build_row(item: MarketScanInput) -> ScreenerRow:
    """Run every metric family for a single input."""
    candles = item.candles
    oi_change = derivatives.oi_change_pct(item.open_interest_current, item.open_interest_prev)
    funding_pct = item.funding_rate * 100.0    # convert to %
    row = ScreenerRow(
        symbol=item.symbol,
        price=price.latest_price(candles),
        change_5m=price.change_5m(candles),
        change_15m=price.change_15m(candles),
        change_1h=price.change_1h(candles),
        volume_current=volume.latest_volume(candles),
        volume_avg=volume.average_volume(candles),
        relative_volume=volume.relative_volume(candles),
        volume_z=volume.volume_z_score(candles),
        atr=volatility.atr(candles),
        vol_expansion=volatility.vol_expansion(candles),
        open_interest=item.open_interest_current,
        oi_change=oi_change,
        funding_rate=funding_pct,
        derivatives_score=derivatives.derivatives_score(oi_change, item.funding_rate),
    )
    return score_row(row)


def run_pipeline(inputs: List[MarketScanInput]) -> List[ScreenerRow]:
    """Apply `build_row` to every input. Side-effect free."""
    return [build_row(i) for i in inputs]
