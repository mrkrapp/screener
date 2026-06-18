"""Live data collector — uses the Binance USDM client to assemble
`MarketScanInput[]` for the scoring pipeline.

ccxt is **not** imported here directly. We only construct/use `BinanceClient`,
which lazy-imports ccxt on first call. If ccxt is missing, the friendly
`CcxtNotInstalledError` propagates up and the CLI prints a clear message.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.exchanges.binance import BinanceClient, BinanceConfig
from app.models import MarketScanInput

logger = logging.getLogger(__name__)


def collect_live_inputs(
    *,
    symbols: Optional[List[str]] = None,
    universe_limit: int = 40,
    candle_limit: int = 90,
    config: Optional[BinanceConfig] = None,
) -> List[MarketScanInput]:
    """Pull live data from Binance USDM and build the scan inputs.

    Args:
        symbols: Optional explicit list of ccxt symbols (e.g. ["BTC/USDT:USDT", ...]).
        universe_limit: When `symbols` is None, the top-N by reported 24h
            quote volume. Kept conservative to stay polite with rate limits.
        candle_limit: Number of 1-minute candles to fetch per symbol.
        config: Optional BinanceConfig (api keys not required for public data).
    """
    client = BinanceClient(config)
    if symbols is None:
        symbols = client.list_perp_symbols(limit=universe_limit)
        logger.info("Discovered %d active USDM perp symbols", len(symbols))

    results: List[MarketScanInput] = []
    for symbol in symbols:
        try:
            candles = client.fetch_candles(symbol, timeframe="1m", limit=candle_limit)
        except Exception as exc:  # noqa: BLE001 — defensive — partial failures shouldn't kill the run
            logger.warning("Skipping %s: candles fetch failed (%s)", symbol, exc)
            continue
        if len(candles) < 60:
            logger.debug("Skipping %s: only %d candles", symbol, len(candles))
            continue

        oi_current = client.fetch_open_interest(symbol)
        oi_prev = client.fetch_open_interest_previous(symbol, timeframe="1h")

        funding = client.fetch_funding_rate(symbol)

        results.append(MarketScanInput(
            symbol=symbol,
            candles=candles,
            open_interest_current=oi_current,
            open_interest_prev=oi_prev,
            funding_rate=funding,
        ))
    return results
