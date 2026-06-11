# crypto_screener — guidance for Claude Code

Binance USDT-margined perpetual futures **screener** (MVP) + **Signal Memory**
(history/outcome-evaluation layer). Analytical only — see hard constraints below.

Repo: https://github.com/mrkrapp/screener.git (root `main` branch).

## Quick orientation

- `python -m app.main --offline-test` — synthetic data, no ccxt/network. Use this
  to sanity-check changes.
- `python -m app.main --live` — real Binance USDM via ccxt.
- `python -m app.main --evaluate-history / --history-report / --export-history` —
  history-only commands (see README "Signal Memory" section).
- `python -m unittest discover -s tests` — full test suite.
- **No Python interpreter is available on this machine** (`python`/`py` resolve to
  the MS Store stub). Tests are written but cannot be executed here — verify by
  careful static review and tell the user to run `unittest` themselves.

The [README.md](README.md) is kept up to date and is the primary reference for
architecture, project structure, env vars, columns, Signal Memory design,
lifecycle diagram, outcome labels, etc. Read it before making structural changes.

## Architecture patterns to follow

- Strict separation of concerns: `collector` (I/O) → `metrics` (pure functions of
  `MarketScanInput`) → `scoring` → `signals` (quality/context enrichment) →
  `output` (rendering only) → `charts`/`history` (separate side outputs).
- `app/history/` dependency direction: `models` (no deps) ← `matcher` /
  `evaluator` / `statistics` / `report` (pure) ← `repository` (SQLite via
  `app/storage/migrations.py`) ← `service` (orchestration) ← `providers`
  (ccxt-backed live price fetch).
- ccxt is always **lazy-imported** inside functions/methods, never at module top
  level (`CcxtNotInstalledError` friendly-exit pattern in `app/exchanges/binance.py`
  and `app/main.py`).
- Config: all thresholds/paths go through `app/config.py` (`AppConfig.from_env()`),
  never hardcoded. New env vars must be added to `.env.example` + README table.
- Dataclasses + type hints throughout. `SignalSnapshot`/`SignalOutcome` are frozen;
  use `dataclasses.replace()` / `with_status()` for "updates".
- Any history-layer call from `app/main.py` is wrapped in try/except — a history
  failure must never break the core screener output (logs `warning:` to stderr).

## Hard constraints (do not violate)

These came from the user's original Signal Memory spec and remain in force for
all future work on this project:

- No look-ahead bias; never use unclosed candles as a price source.
- Never modify a signal's original recorded metrics — only `status` may change
  post-creation (lifecycle).
- Never declare success from a brief touch — MFE/MAE are stored separately from
  final `return_pct`/`directional_return_pct`.
- Never treat neutral direction hints (`VOLUME_ONLY`, `DERIVATIVES_ANOMALY`,
  `MIXED`, `NEUTRAL`) as bullish/bearish.
- Never mix offline and live history databases (`_with_suffix` gives offline runs
  `*_offline` DB/report/CSV paths).
- Never auto-delete history without the configured retention policy
  (`SIGNAL_HISTORY_RETENTION_DAYS`, default 180; `apply_retention` is a no-op when
  `retention_days <= 0`).
- No Telegram, no Bybit, no order placement/trading functions, no real PnL, no
  buy/sell recommendations. Everything is descriptive/analytical.
- Keep modularity, type hints, dataclasses; don't add SQLAlchemy/ORM — stdlib
  `sqlite3` only.
- A history-module error must never stop the main screener — log and continue.

## Status

- Sprint A (signal-quality columns + "Signal context" block, `.env`/README, offline
  tests) — done, committed `4a57d7a`.
- Sprint B (Signal Memory: `app/history/`, `app/storage/`, SQLite persistence,
  outcome evaluation, statistics, HTML report + CSV export, new CLI commands,
  `.env`/README, `tests/test_history.py`) — done, committed `866ad29`. Both pushed
  to `origin/main`.
- Outstanding/known limitations: `median_time_to_mfe` not computed (documented in
  README); reason-matching is heuristic/substring-based against
  `app.signals.context` text; live evaluation needs ccxt + network; tests unverified
  by execution due to no local interpreter.
