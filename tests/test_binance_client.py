from __future__ import annotations

import unittest

from app.exchanges.binance import BinanceClient


class FakeExchange:
    def __init__(self) -> None:
        self.markets = {
            "AAA/USDT:USDT": {
                "active": True,
                "type": "swap",
                "quote": "USDT",
                "settle": "USDT",
                "linear": True,
                "expiry": None,
            },
            "BBB/USDT:USDT": {
                "active": True,
                "type": "swap",
                "quote": "USDT",
                "settle": "USDT",
                "linear": True,
                "expiry": None,
            },
            "OLD/USDT:USDT": {
                "active": False,
                "type": "swap",
                "quote": "USDT",
                "settle": "USDT",
                "linear": True,
                "expiry": None,
            },
        }

    def load_markets(self):
        return self.markets

    def fetch_tickers(self, symbols):
        return {
            "AAA/USDT:USDT": {"quoteVolume": 100.0},
            "BBB/USDT:USDT": {"quoteVolume": 1_000.0},
        }

    def fetch_ohlcv(self, symbol, timeframe="1m", limit=90, **kwargs):
        return [
            [0, 10, 11, 9, 10, 100],
            [60_000, 10, 11, 9, 10, 100],
            [120_000, 10, 11, 9, 10, 100],
        ]

    def milliseconds(self):
        return 150_000

    def fetch_open_interest_history(self, symbol, timeframe="1h", limit=2):
        return [
            {"timestamp": 1, "openInterestAmount": 100.0},
            {"timestamp": 2, "openInterestAmount": 110.0},
        ]


class BinanceClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = BinanceClient()
        self.client._exchange = FakeExchange()

    def test_universe_is_ranked_by_quote_volume(self):
        symbols = self.client.list_perp_symbols(limit=2)
        self.assertEqual(symbols, ["BBB/USDT:USDT", "AAA/USDT:USDT"])

    def test_unclosed_candle_is_dropped(self):
        candles = self.client.fetch_candles("AAA/USDT:USDT", timeframe="1m")
        self.assertEqual([c.open_time for c in candles], [0, 60])

    def test_previous_open_interest_uses_real_history(self):
        previous = self.client.fetch_open_interest_previous("AAA/USDT:USDT")
        self.assertEqual(previous, 100.0)


if __name__ == "__main__":
    unittest.main()
