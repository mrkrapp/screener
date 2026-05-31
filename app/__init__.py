"""crypto_screener — Binance USDM perpetual futures screener (MVP).

Pipeline:
    collector  → MarketScanInput[]
    metrics    → ScreenerRow[]
    scoring    → ScreenerRow[] (with score + signals)
    output     → console table

Modes:
    live          — real Binance data via ccxt
    offline-test  — synthetic data, no ccxt, no network
"""

__version__ = "0.1.0"
