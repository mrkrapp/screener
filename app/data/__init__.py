"""Data layer: live collector + offline sample generator.

The collector calls into `app.exchanges.binance` (lazy ccxt). The sample
generator is pure stdlib and has zero network/external dependencies, so it
runs in any environment.
"""
