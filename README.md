# crypto_screener

Binance USDT-margined perpetual futures screener (MVP).
Pulls 1-minute klines + open interest + funding rate, computes momentum /
volume / volatility / derivatives metrics, scores each symbol, prints a top
table to the console.

> This is an analytical screener. It never opens trades and never produces
> trading advice. Every output is an analytical observation.

## Modes

There are exactly two CLI modes:

| Mode             | Network | ccxt required | What it does                                |
|------------------|---------|---------------|---------------------------------------------|
| `--offline-test` | no      | **no**        | Runs the pipeline on synthetic sample data. |
| `--live`         | yes     | **yes**       | Runs against real Binance USDM via ccxt.    |

The offline mode exists so you can verify the project, the metrics, the
scoring and the console renderer **without** installing ccxt or having
network access.

## Quick start

```bash
# Clone, then from the project root:
python -m app.main --offline-test
```

This works on a clean Python 3.10+ install with **no third-party packages**.
You should see a header `Top movers (offline-test)` followed by the metrics
table for six synthetic scenarios.

### Live mode

```bash
pip install -r requirements.txt
python -m app.main --live
```

If ccxt is **not** installed and you try `--live`, the program prints a
friendly message and exits with status 2, **no traceback**:

```
error: ccxt is required for live mode. Install dependencies with: pip install -r requirements.txt
```

### What if `pip install ccxt` fails?

Some sandboxed networks block PyPI (e.g. Windows `WinError 10013`). You can
still develop and test the entire pipeline using `--offline-test` until you
have network access to install ccxt.

## Project structure

```
app/
├── main.py               # CLI entry — argparse, mode dispatch
├── pipeline.py           # glue: inputs → metrics → scoring → rows
├── config.py             # env-var driven config (.env supported)
├── models/
│   └── market.py         # Candle, MarketScanInput, ScreenerRow dataclasses
├── exchanges/
│   └── binance.py        # ccxt.binanceusdm wrapper (LAZY ccxt import)
├── data/
│   ├── collector.py      # live: builds MarketScanInput[] from exchange
│   └── sample_data.py    # offline: synthetic scenarios, no I/O
├── metrics/
│   ├── price.py          # change_5m / change_15m / change_1h
│   ├── volume.py         # average, relative_volume, volume_z
│   ├── volatility.py     # atr, vol_expansion
│   ├── derivatives.py    # oi_change_pct, derivatives_score
│   └── quality.py        # atr_percent, price_move_atr, quality_score, ...
├── scoring/
│   └── score.py          # compose composite score + signal tags
├── signals/
│   ├── detector.py       # enrich_with_quality — fills quality fields on a row
│   └── context.py        # build_signal_context — direction_hint, reasons, ...
├── output/
│   └── console.py        # plain-stdlib top-table + compact + context renderers
└── charts/
    └── tradingview.py    # CCXT → TradingView symbol + HTML report

tests/
├── test_offline.py       # network-free smoke test (pipeline + CLI)
├── test_tradingview.py   # symbol conversion, URL encoding, HTML report
└── test_signals.py       # quality metrics + signal context builder
```

Separation of concerns is strict:

- **collector** never computes metrics, never scores, never prints
- **metrics** are pure functions of `MarketScanInput`
- **scoring** consumes `ScreenerRow` and only fills `score` + `signals`
- **output** consumes `ScreenerRow[]` and only renders
- **charts** generates HTML separately — never touches metrics or scoring

## Top table columns

The same columns are rendered in both `--live` and `--offline-test` modes:

`symbol · tv_symbol · price · change_5m · change_15m · change_1h ·
rvol · volume_z · atr · vol_exp · oi_change · funding_rate ·
deriv_score · score · quality · trend_align · oi_confirm · pm_atr ·
dol_vol_curr · signals`

The last five columns come from the **signal-quality** layer, see below.

The `tv_symbol` column shows the TradingView ticker the chart helper
derives from the CCXT symbol. Examples:

```
BTC/USDT:USDT  →  BINANCE:BTCUSDT.P
ETH/USDT:USDT  →  BINANCE:ETHUSDT.P
SOL/USDT:USDT  →  BINANCE:SOLUSDT.P
```

## Compact view

`--compact` adds a single-line-per-row summary under the wide table:

```
Compact view (offline-test)
----------------------------------------------------------------------------------------
  VSPIKE/USDT:USDT     score  82.10   TV BINANCE:VSPIKEUSDT.P    [volume_spike, volume_z_outlier]
  MOMNT/USDT:USDT      score  68.40   TV BINANCE:MOMNTUSDT.P     [momentum_move]
  OIUP/USDT:USDT       score  61.20   TV BINANCE:OIUPUSDT.P      [oi_increase, volume_elevated]
  ...
```

## Signal-quality metrics

After the base metrics and the composite anomaly score are computed, the
pipeline runs a second pass that adds **signal-quality** fields to each row.
Code lives in `app/metrics/quality.py` (pure functions) and
`app/signals/detector.py` (the enricher). Nothing here generates buy/sell
recommendations — every field is a descriptive observation.

| Field                    | Meaning                                                                                  |
|--------------------------|------------------------------------------------------------------------------------------|
| `quality_score` (0–100)  | Composite quality reading: trend alignment, volume confirmation, OI confirmation, etc.   |
| `trend_alignment`        | `BULLISH_ALIGNED` / `BEARISH_ALIGNED` / `MIXED_ALIGNMENT` / `INSUFFICIENT_DATA`           |
| `oi_confirmation`        | `FRESH_LONGS` / `FRESH_SHORTS` / `SHORT_COVERING` / `LONG_UNWIND` / …                     |
| `price_move_atr`         | Magnitude of the 1h price move expressed in ATR multiples                                |
| `volume_confirmation`    | `relative_volume * abs(change_1h)` — high when both move together                        |
| `funding_pressure`       | `abs(funding_rate) / SIGNAL_FUNDING_ABS_THRESHOLD` — `>1` means elevated                 |
| `dollar_volume_current`  | Approximate dollar turnover this candle                                                  |

### Signal context block

After the compact view, the CLI prints a short **Signal context** block —
one `compact_summary` line per top-N coin, plus an optional `Risks:` line:

```
Signal context
----------------------------------------------------------------------------------------
  VSPIKE/USDT:USDT | VOLUME_ONLY | Score 82 | Quality 71 | RVOL is 3.4x above normal, ... | MEDIUM
    Risks: Volume spike without strong price follow-through
  MOMNT/USDT:USDT | BULLISH_MOMENTUM | Score 68 | Quality 65 | Price moved +2.30% over 1h, ... | MEDIUM
```

`direction_hint` is one of `BULLISH_MOMENTUM`, `BEARISH_MOMENTUM`,
`VOLUME_ONLY`, `DERIVATIVES_ANOMALY`, `VOLATILITY_BREAKOUT`, `MIXED`,
`NEUTRAL`. **It describes recent market behaviour, not a trade idea.**
`confidence` is one of `HIGH`, `MEDIUM`, `LOW` and reflects how many
quality conditions agree.

## TradingView HTML report

After the top table is printed, the CLI writes a self-contained HTML report:

```
TradingView report: data/processed/tradingview_report.html
```

The file is a single HTML page styled with a dark terminal theme. It
contains one card per row from the top-N. Each card shows:

- the CCXT `symbol` and the derived `tv_symbol`
- the composite `score`
- the analytical `signals` tags
- an **Open TradingView** button — opens `https://www.tradingview.com/chart/?symbol=…`
- an embedded TradingView chart widget for that ticker

> **Internet required to view charts.** The HTML file itself is static and
> self-contained, but the embedded TradingView widget loads
> `https://s3.tradingview.com/tv.js` in your browser. Without internet the
> page still opens — you just see empty chart panels.

### Disabling the report

Add the following to `.env`:

```
GENERATE_TRADINGVIEW_REPORT=false
```

Or skip it once via `--no-report`:

```
python -m app.main --offline-test --no-report
```

When disabled, no file is written and no path is printed.

### Empty state

If the pipeline returns zero rows the report file is still produced but
contains a small `nothing to chart` placeholder instead of widgets.

## Environment variables

All optional (read from `.env` if present, or from process env). See
`.env.example` for the full list:

| Variable                       | Default                                   | Purpose                                  |
|--------------------------------|-------------------------------------------|------------------------------------------|
| `BINANCE_API_KEY`              | —                                         | Optional. Public endpoints don't need it.|
| `BINANCE_API_SECRET`           | —                                         | Optional.                                |
| `SCREENER_TOP_N`               | `20`                                      | Rows to print.                           |
| `SCREENER_CANDLE_LIMIT`        | `90`                                      | 1-minute candles per symbol.             |
| `SCREENER_UNIVERSE_LIMIT`      | `40`                                      | Symbols to scan in live mode.            |
| `SCREENER_LOG_LEVEL`           | `INFO`                                    | DEBUG / INFO / WARNING / ERROR.          |
| `GENERATE_TRADINGVIEW_REPORT`  | `true`                                    | Set false/0/no to skip the HTML report.  |
| `TRADINGVIEW_EXCHANGE_PREFIX`  | `BINANCE`                                 | Exchange prefix used in the TV ticker.   |
| `TRADINGVIEW_INTERVAL`         | `60`                                      | "1", "5", "15", "60", "240", "D".        |
| `TRADINGVIEW_REPORT_PATH`      | `data/processed/tradingview_report.html`  | Where to write the HTML.                 |
| `SIGNAL_FUNDING_ABS_THRESHOLD` | `0.0003`                                  | Reference funding rate for `funding_pressure`. |

## Smoke test (offline)

The repository includes a no-network test:

```bash
python -m unittest tests.test_offline
```

This verifies that:

1. Sample data builds without crashing
2. The pipeline produces one row per scenario
3. The console renderer outputs the expected header
4. `python -m app.main --offline-test` exits with status 0
5. `python -m app.main --live` (when ccxt is missing) exits with status 2
   and prints the friendly error string

## Offline scenarios

`app/data/sample_data.py` generates six deterministic scenarios so the
output is stable from run to run:

| Symbol               | Scenario                  |
|----------------------|---------------------------|
| `NORMAL/USDT:USDT`   | normal_market             |
| `VSPIKE/USDT:USDT`   | volume_spike              |
| `MOMNT/USDT:USDT`    | momentum_move             |
| `VOLEX/USDT:USDT`    | volatility_expansion      |
| `OIUP/USDT:USDT`     | oi_increase               |
| `HOTFND/USDT:USDT`   | extreme_funding           |

Each scenario stresses a different subset of the metrics so you can verify
end-to-end behaviour with one command.

## What this MVP intentionally does NOT include

No Telegram. No database. No dashboard. No Docker. No Bybit. No trading or
order placement. No paid APIs.
