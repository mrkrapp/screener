"""Synthetic sample data for offline-test mode.

Builds a small universe of MarketScanInput objects covering distinct scenarios.
Deterministic (seeded) so test output is stable. Zero external dependencies.

Scenarios:
    1. normal_market         — flat price, steady volume.
    2. volume_spike          — last candle's volume is ~5x the running average.
    3. momentum_move         — strong directional drift over the last hour.
    4. volatility_expansion  — large recent candle range vs prior window.
    5. oi_increase           — current OI ~+8% vs prior OI.
    6. extreme_funding       — funding rate well above 0.1% per interval.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Callable, List

from app.models import Candle, MarketScanInput


@dataclass(frozen=True)
class Scenario:
    """A named generator. Useful for printing what's in the offline universe."""

    symbol: str
    label: str
    build: Callable[[], MarketScanInput]


# --- helpers ----------------------------------------------------------------

_BASE_PRICE = 100.0
_BASE_VOLUME = 1_000.0
_DEFAULT_CANDLES = 90


def _build_candles(
    *,
    base_price: float = _BASE_PRICE,
    candles: int = _DEFAULT_CANDLES,
    drift_pct_per_min: float = 0.0,
    noise_pct: float = 0.05,
    base_volume: float = _BASE_VOLUME,
    volume_jitter: float = 0.15,
    volume_spike_last: float = 1.0,
    last_range_multiplier: float = 1.0,
    seed: int = 0,
) -> List[Candle]:
    """Generic candle builder. All "scenarios" tweak just a few knobs."""
    rng = random.Random(seed)
    now = int(time.time()) // 60 * 60   # align to minute
    out: List[Candle] = []
    price = base_price
    for i in range(candles):
        open_time = now - (candles - 1 - i) * 60
        # Drift + noise — multiplicative
        change = drift_pct_per_min / 100 + rng.uniform(-noise_pct, noise_pct) / 100
        next_close = max(0.0001, price * (1 + change))
        candle_range = price * (rng.uniform(0.001, 0.005))
        is_last = (i == candles - 1)
        if is_last:
            candle_range *= last_range_multiplier
        high = max(price, next_close) + candle_range / 2
        low = min(price, next_close) - candle_range / 2
        low = max(0.0001, low)
        volume = base_volume * (1 + rng.uniform(-volume_jitter, volume_jitter))
        if is_last and volume_spike_last != 1.0:
            volume *= volume_spike_last
        out.append(Candle(
            open_time=open_time,
            open=price,
            high=high,
            low=low,
            close=next_close,
            volume=volume,
        ))
        price = next_close
    return out


# --- individual scenarios ---------------------------------------------------

def _normal_market() -> MarketScanInput:
    candles = _build_candles(base_price=200.0, seed=1)
    return MarketScanInput(
        symbol="NORMAL/USDT:USDT",
        candles=candles,
        open_interest_current=10_000.0,
        open_interest_prev=10_050.0,    # essentially flat
        funding_rate=0.00005,            # 0.005% / interval — calm
    )


def _volume_spike() -> MarketScanInput:
    candles = _build_candles(base_price=50.0, seed=2, volume_spike_last=6.0)
    return MarketScanInput(
        symbol="VSPIKE/USDT:USDT",
        candles=candles,
        open_interest_current=8_000.0,
        open_interest_prev=7_900.0,
        funding_rate=0.00012,
    )


def _momentum_move() -> MarketScanInput:
    # +0.08% per minute → ~+5% over the last hour
    candles = _build_candles(base_price=20.0, seed=3, drift_pct_per_min=0.08)
    return MarketScanInput(
        symbol="MOMNT/USDT:USDT",
        candles=candles,
        open_interest_current=15_000.0,
        open_interest_prev=14_500.0,
        funding_rate=0.00025,
    )


def _volatility_expansion() -> MarketScanInput:
    candles = _build_candles(
        base_price=1000.0,
        seed=4,
        last_range_multiplier=4.5,
        volume_spike_last=2.2,
    )
    return MarketScanInput(
        symbol="VOLEX/USDT:USDT",
        candles=candles,
        open_interest_current=12_000.0,
        open_interest_prev=12_050.0,
        funding_rate=0.00008,
    )


def _oi_increase() -> MarketScanInput:
    candles = _build_candles(base_price=5.0, seed=5, drift_pct_per_min=0.02)
    return MarketScanInput(
        symbol="OIUP/USDT:USDT",
        candles=candles,
        open_interest_current=22_000.0,
        open_interest_prev=20_500.0,    # ~ +7.3%
        funding_rate=0.00018,
    )


def _extreme_funding() -> MarketScanInput:
    candles = _build_candles(base_price=2.5, seed=6, drift_pct_per_min=-0.04)
    return MarketScanInput(
        symbol="HOTFND/USDT:USDT",
        candles=candles,
        open_interest_current=9_500.0,
        open_interest_prev=9_400.0,
        funding_rate=0.0018,             # 0.18% / interval — extreme
    )


# --- registry ---------------------------------------------------------------

_SCENARIOS: tuple[Scenario, ...] = (
    Scenario("NORMAL/USDT:USDT",  "normal_market",         _normal_market),
    Scenario("VSPIKE/USDT:USDT",  "volume_spike",          _volume_spike),
    Scenario("MOMNT/USDT:USDT",   "momentum_move",         _momentum_move),
    Scenario("VOLEX/USDT:USDT",   "volatility_expansion",  _volatility_expansion),
    Scenario("OIUP/USDT:USDT",    "oi_increase",           _oi_increase),
    Scenario("HOTFND/USDT:USDT",  "extreme_funding",       _extreme_funding),
)


def list_scenarios() -> tuple[Scenario, ...]:
    """Read-only view of the registered scenarios."""
    return _SCENARIOS


def build_offline_inputs() -> List[MarketScanInput]:
    """Build the offline universe used by `python -m app.main --offline-test`."""
    return [scenario.build() for scenario in _SCENARIOS]


# Backwards-friendly alias.
def assert_sane(inputs: List[MarketScanInput]) -> None:
    """Lightweight sanity check used by the smoke test."""
    assert inputs, "expected at least one offline input"
    for item in inputs:
        assert item.candles, f"{item.symbol}: no candles"
        assert len(item.candles) >= 60, f"{item.symbol}: too few candles ({len(item.candles)})"
        assert math.isfinite(item.funding_rate), f"{item.symbol}: bad funding"
