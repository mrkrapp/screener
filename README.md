# crypto_screener

Binance USDT-margined perpetual futures screener (MVP).
Pulls closed 1-minute klines + real open-interest history + funding rate, computes momentum /
volume / volatility / derivatives metrics, scores each symbol, prints a top
table to the console.

> This is an analytical screener. It never opens trades and never produces
> trading advice. Every output is an analytical observation.

## Modes

Two scan modes plus three history-only commands:

| Command              | Network | ccxt | What it does                                          |
|----------------------|---------|------|-------------------------------------------------------|
| `--offline-test`     | no      | no   | Runs the pipeline on synthetic sample data.           |
| `--live`             | yes     | yes  | Runs against real Binance USDM via ccxt.              |
| `--evaluate-history` | yes     | yes  | Evaluates pending history only — no new scan/signals. |
| `--history-report`   | no      | no   | Rebuilds the Signal Memory HTML from the existing DB. |
| `--export-history`   | no      | no   | Rebuilds the Signal Memory CSV from the existing DB.  |

The offline mode exists so you can verify the project, the metrics, the
scoring and the console renderer **without** installing ccxt or having
network access. Add `--no-history` to any scan to skip the Signal Memory cycle.

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
├── history/              # Signal Memory: record + evaluate outcomes
│   ├── models.py         # SignalSnapshot / SignalOutcome + vocabulary
│   ├── matcher.py        # fingerprint, snapshot build, de-dup decision
│   ├── evaluator.py      # pure outcome calc (returns, MFE/MAE, labels, reasons)
│   ├── repository.py     # SQLite persistence (snapshots + outcomes)
│   ├── statistics.py     # quality aggregation (by horizon/direction/…)
│   ├── report.py         # Signal Memory HTML report + CSV export
│   ├── service.py        # orchestration (record → evaluate → lifecycle)
│   └── providers.py      # live post-signal candle fetching
├── storage/
│   └── migrations.py     # SQLite schema + indexes (stdlib sqlite3)
├── output/
│   └── console.py        # plain-stdlib top-table + compact + context renderers
└── charts/
    └── tradingview.py    # CCXT → TradingView symbol + HTML report

tests/
├── test_offline.py       # network-free smoke test (pipeline + CLI)
├── test_tradingview.py   # symbol conversion, URL encoding, HTML report
├── test_binance_client.py # liquidity ranking, closed candles, real OI history
├── test_signals.py       # quality metrics + signal context builder
└── test_history.py       # Signal Memory: outcomes, MFE/MAE, SQLite, reports
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
derivatives_score · score · quality · trend_align · oi_confirm · pm_atr ·
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

The file is a single dark master-detail workspace:

- one active TradingView chart occupies the left side
- every top-N market is selectable from the list on the right
- clicking any market immediately replaces the active chart
- search filters the market list
- 5m / 15m / 1h / 4h / 1D interval controls are available
- the external-link icon opens the selected market on TradingView
- `?asset=BINANCE:BTCUSDT.P` restores a selected market when the report opens

Only one TradingView widget exists at a time, so increasing the top-N does not
create dozens of simultaneous chart iframes.

> **Internet required to view charts.** The HTML file itself is static and
> self-contained, but the embedded TradingView widget loads
> `https://s3.tradingview.com/tv.js` in your browser. Without internet the
> page still opens and shows the market list, with a clear chart-unavailable state.

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

## Live data integrity

The live collector deliberately avoids several common sources of false precision:

- the universe is ranked by Binance 24h quote volume, not alphabetically
- inactive, non-linear, non-USDT-settled and expiring markets are excluded
- the current unclosed candle is removed before metrics are calculated
- OI change uses Binance's public OI history endpoint
- missing OI/funding remains `None` and renders as `-`; it is never replaced by zero
- composite scoring rescales available components when derivatives are unavailable
- a symbol with a failed candles request is skipped without stopping the scan

Public market data does not require Binance API keys. Values remain observations
from Binance and CCXT, not guaranteed exchange execution prices.

## Signal Memory (history + outcome evaluation)

The screener remembers the signals it emits and **objectively grades them after
the fact** — did price actually follow through, and which of the stated reasons
held up? This is analytics about signal *quality*; it never opens trades, never
computes account PnL, and never produces buy/sell advice.

### How it works

On every `--live` run (and on `--offline-test`, against a separate test DB):

1. **Record.** Each qualifying top result is frozen into an immutable
   `SignalSnapshot` (price, score, quality, direction hint, reasons, risk notes,
   raw metrics, TradingView link). A `fingerprint` of
   `symbol + direction + sorted(signals) + candle_minute` plus a configurable
   cooldown prevents the same signal being saved twice.
2. **Evaluate.** For every open snapshot the evaluator pulls the *closed*
   candles that followed it and computes, at the **15m / 1h / 4h / 24h**
   horizons:
   - `return_pct` and direction-aware `directional_return_pct`
   - **MFE** (max favourable excursion) and **MAE** (max adverse excursion),
     normalised so MFE is positive when price moved the expected way
   - an `outcome_label` (see below)
   - a matched/failed breakdown of the original `main_reasons`
3. **Lifecycle.** The snapshot status walks
   `NEW → TRACKING → PARTIALLY_EVALUATED → COMPLETED` (or `EXPIRED` /
   `DATA_ERROR`). Past metrics are never rewritten — only the status changes.
4. **Report.** A separate `signal_history_report.html` and a
   `signal_history.csv` are regenerated, and a one-line summary is printed.

**No look-ahead bias:** only candles whose *close* is at or before "now" are
ever read, and an unclosed candle is never used as the horizon price.

### Outcome labels

| Label               | Meaning                                                            |
|---------------------|--------------------------------------------------------------------|
| `STRONG_MATCH`      | Right direction, threshold hit, MFE clearly dominates MAE.         |
| `MATCH`             | Right direction, threshold hit.                                    |
| `PARTIAL_MATCH`     | Right direction, threshold not reached.                            |
| `NO_FOLLOW_THROUGH` | Favourable excursion that gave it all back / faded.                |
| `INVALIDATED`       | Wrong direction; adverse move exceeded the threshold.             |
| `PENDING`           | Horizon not reached yet.                                           |
| `EXPIRED`           | Horizon long past with no price data.                             |
| `NOT_APPLICABLE`    | Neutral hint (no expected side) — graded by realised move only.    |

### Lifecycle

```
NEW ──▶ TRACKING ──▶ PARTIALLY_EVALUATED ──▶ COMPLETED
              │                 │
              └──────▶ EXPIRED ◀┘        (DATA_ERROR on evaluation failure)
```

### Statistics

The report's summary shows totals, pending/completed counts, and per-horizon
match / strong-match / invalidation rates plus average MFE/MAE. Breakdowns are
also computed by direction, confidence, signal label, score bucket, quality
bucket and symbol. Any group with fewer than `min_sample` (10) evaluated
directional outcomes is shown as **"insufficient sample: N"** rather than a
misleading percentage.

> Known limitation: `median_time_to_mfe` is not computed — the evaluator stores
> the window extreme, not the candle index at which it occurred.

### Commands

```bash
python -m app.main --live               # scan + record + evaluate + reports
python -m app.main --evaluate-history   # evaluate pending only (needs ccxt)
python -m app.main --history-report     # rebuild HTML from the DB
python -m app.main --export-history     # rebuild CSV from the DB
python -m app.main --live --no-history  # scan but skip the memory cycle
```

Offline-test mode writes to *separate* `*_offline` files so synthetic history
never mixes with live history.

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
| `SIGNAL_HISTORY_ENABLED`       | `true`                                    | Master switch for Signal Memory.         |
| `SIGNAL_HISTORY_DB_PATH`       | `data/signals/signal_history.db`          | SQLite history database.                 |
| `SIGNAL_HISTORY_REPORT_PATH`   | `data/processed/signal_history_report.html` | Signal Memory HTML report.             |
| `SIGNAL_HISTORY_EXPORT_PATH`   | `data/signals/exports/signal_history.csv` | Signal Memory CSV export.                |
| `SIGNAL_HISTORY_COOLDOWN_MINUTES` | `60`                                   | De-dup window for recording a signal.    |
| `SIGNAL_HISTORY_MIN_SCORE`     | `60`                                      | Min score to record a signal.            |
| `SIGNAL_HISTORY_MIN_QUALITY`   | `50`                                      | Min quality to record a signal.          |
| `SIGNAL_MATCH_15M_PCT`         | `0.5`                                     | 15m match threshold (%).                 |
| `SIGNAL_MATCH_1H_PCT`          | `1.0`                                     | 1h match threshold (%).                  |
| `SIGNAL_MATCH_4H_PCT`          | `2.0`                                     | 4h match threshold (%).                  |
| `SIGNAL_MATCH_24H_PCT`         | `3.0`                                     | 24h match threshold (%).                 |
| `SIGNAL_HISTORY_RETENTION_DAYS`| `180`                                     | Prune history older than this.           |

## Smoke test (offline)

The repository includes no-network tests:

```bash
python -m unittest discover -s tests        # everything
python -m unittest tests.test_offline       # pipeline + CLI
python -m unittest tests.test_signals        # quality + signal context
python -m unittest tests.test_history        # Signal Memory
```

`tests.test_offline` verifies that:

1. Sample data builds without crashing
2. The pipeline produces one row per scenario
3. The console renderer outputs the expected header
4. `python -m app.main --offline-test` exits with status 0
5. `python -m app.main --live` (when ccxt is missing) exits with status 2
   and prints the friendly error string

`tests.test_history` covers fingerprint/de-dup, immutable snapshots, bullish &
bearish outcomes, MFE/MAE, pending vs expired horizons, closed-vs-unclosed
candles, outcome labels, matched/failed reasons, SQLite insert/upsert, CSV +
HTML generation, offline/live DB separation, division-by-zero and missing-data
guards, and timezone-aware timestamps.

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
