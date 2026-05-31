"""Chart-rendering layer.

Currently only TradingView is supported. The module is kept separate from
metrics/scoring/console output so chart code can never accidentally affect
the analytical pipeline.
"""

from app.charts.tradingview import (
    convert_symbol_to_tradingview,
    generate_tradingview_report,
    tradingview_url,
)

__all__ = [
    "convert_symbol_to_tradingview",
    "generate_tradingview_report",
    "tradingview_url",
]
