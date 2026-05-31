"""TradingView helpers.

Three responsibilities, kept independent:

    1. `convert_symbol_to_tradingview` — pure string conversion.
    2. `tradingview_url`               — build the deep-link URL.
    3. `generate_tradingview_report`   — write a self-contained HTML file
                                          with embedded TradingView widgets.

Nothing here computes metrics, scores, or hits the network. The HTML file
itself references `https://s3.tradingview.com/.../tv.js`, which is fetched
by the user's browser only when the file is opened. The Python side is
fully offline-safe.
"""

from __future__ import annotations

import html
import json
import logging
import os
from pathlib import Path
from typing import Iterable, List, Optional, Sequence
from urllib.parse import quote

from app.models import ScreenerRow

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Symbol conversion
# ----------------------------------------------------------------------------

def convert_symbol_to_tradingview(symbol: str, exchange_prefix: str = "BINANCE") -> str:
    """Convert a CCXT-style symbol into a TradingView USDM perpetual ticker.

    Examples:
        BTC/USDT:USDT      → BINANCE:BTCUSDT.P
        ETH/USDT:USDT      → BINANCE:ETHUSDT.P
        SOL/USDT:USDT      → BINANCE:SOLUSDT.P
        BTCUSDT            → BINANCE:BTCUSDT.P   (already collapsed)
        BTC/USDT           → BINANCE:BTCUSDT.P   (spot-style — assume perp)
        BINANCE:BTCUSDT.P  → BINANCE:BTCUSDT.P   (idempotent)

    Empty input returns an empty string.
    """
    if not symbol:
        return ""

    prefix = (exchange_prefix or "BINANCE").strip().upper()
    s = symbol.strip()

    # Already in TradingView form — only normalise casing.
    if ":" in s and (s.upper().endswith(".P") or s.upper().endswith(":P")):
        return s.upper().replace(":P", ".P")

    # Strip the CCXT settlement suffix (`:USDT` etc.)
    if ":" in s:
        head, _, _settle = s.partition(":")
    else:
        head = s

    # Strip the `/` between base and quote
    collapsed = head.replace("/", "").upper()
    if not collapsed:
        return ""

    return f"{prefix}:{collapsed}.P"


def tradingview_url(symbol: str, exchange_prefix: str = "BINANCE") -> str:
    """Return the URL-encoded deep link to TradingView's chart page.

    Example:
        BTC/USDT:USDT → https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT.P
    """
    tv = convert_symbol_to_tradingview(symbol, exchange_prefix)
    if not tv:
        return ""
    # `quote` with empty safe list percent-encodes the colon (`:`).
    return f"https://www.tradingview.com/chart/?symbol={quote(tv, safe='')}"


# ----------------------------------------------------------------------------
# HTML report
# ----------------------------------------------------------------------------

_DARK_CSS = """
:root {
  color-scheme: dark;
  --bg:        #0f1117;
  --panel:     #161922;
  --panel-2:   #1c202b;
  --border:    #262b38;
  --text:      #e5e7eb;
  --muted:     #9ca3af;
  --dim:       #6b7280;
  --accent:    #3b82f6;
  --good:      #22c55e;
  --bad:       #ef4444;
  --warn:      #f59e0b;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  -webkit-font-smoothing: antialiased;
}
header {
  padding: 16px 24px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: baseline;
  gap: 12px;
}
header h1 { margin: 0; font-size: 16px; letter-spacing: 0.04em; }
header .meta { color: var(--muted); font-size: 11px; font-family: monospace; }
main { padding: 16px 24px; display: grid; gap: 16px;
       grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); }
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.card-head {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  display: grid;
  gap: 4px;
}
.card-head .row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.symbol { font-weight: 600; font-size: 14px; }
.tv-symbol {
  color: var(--muted);
  font-family: monospace;
  font-size: 11px;
  background: var(--panel-2);
  padding: 1px 6px;
  border-radius: 3px;
}
.score {
  font-family: monospace;
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--panel-2);
  color: var(--text);
  margin-left: auto;
}
.score.high { color: var(--good); }
.score.low  { color: var(--bad); }
.signals {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.signal {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--panel-2);
  color: var(--muted);
  border: 1px solid var(--border);
}
.signal.warn { color: var(--warn); border-color: rgba(245, 158, 11, 0.4); }
.signal.bad  { color: var(--bad);  border-color: rgba(239, 68, 68, 0.4); }
.signal.good { color: var(--good); border-color: rgba(34, 197, 94, 0.4); }
.open-tv {
  font-size: 11px;
  text-decoration: none;
  color: var(--accent);
  border: 1px solid var(--accent);
  padding: 2px 8px;
  border-radius: 3px;
}
.open-tv:hover { background: rgba(59, 130, 246, 0.15); }
.chart {
  width: 100%;
  aspect-ratio: 16 / 9;
  background: var(--panel-2);
}
footer {
  padding: 12px 24px;
  color: var(--dim);
  font-size: 11px;
  border-top: 1px solid var(--border);
  text-align: center;
}
.empty {
  padding: 48px 24px;
  text-align: center;
  color: var(--muted);
}
"""

# JS that runs once per card. It creates one TradingView widget per card.
# Loaded via the official tv.js library; this requires the browser to be
# online when the user opens the report.
_WIDGET_BOOTSTRAP_TEMPLATE = """
(function () {
  if (!window.TradingView) return;
  var cards = __CARDS__;
  cards.forEach(function (c) {
    new TradingView.widget({
      container_id: c.containerId,
      symbol: c.symbol,
      interval: c.interval,
      timezone: "Etc/UTC",
      theme: "dark",
      style: "1",
      locale: "en",
      toolbar_bg: "#161922",
      enable_publishing: false,
      hide_top_toolbar: false,
      hide_side_toolbar: true,
      allow_symbol_change: true,
      autosize: true,
      studies: ["Volume@tv-basicstudies"]
    });
  });
})();
"""


def _classify_signal(signal: str) -> str:
    """Pick a CSS tone for a signal string."""
    s = signal.lower()
    if "extreme" in s or "outlier" in s:
        return "warn"
    if s.startswith("oi_decrease") or "selloff" in s:
        return "bad"
    if "spike" in s or "expansion" in s or "momentum" in s or s.startswith("oi_increase"):
        return "good"
    return ""


def _classify_score(score: float) -> str:
    if score >= 70:
        return "high"
    if score <= 30:
        return "low"
    return ""


def _build_card_html(
    *,
    container_id: str,
    row: ScreenerRow,
    tv_symbol: str,
    open_url: str,
) -> str:
    """Render the HTML for one card."""
    signal_chips = "".join(
        f'<span class="signal {_classify_signal(sig)}">{html.escape(sig)}</span>'
        for sig in row.signals
    ) or '<span class="signal">no signals</span>'
    score_class = _classify_score(row.score)
    return f"""\
<article class="card">
  <div class="card-head">
    <div class="row">
      <span class="symbol">{html.escape(row.symbol)}</span>
      <span class="tv-symbol">{html.escape(tv_symbol)}</span>
      <span class="score {score_class}">score {row.score:.1f}</span>
    </div>
    <div class="row signals">{signal_chips}</div>
    <div class="row">
      <a class="open-tv" target="_blank" rel="noopener noreferrer" href="{html.escape(open_url)}">Open TradingView</a>
    </div>
  </div>
  <div class="chart" id="{html.escape(container_id)}"></div>
</article>"""


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def generate_tradingview_report(
    rows: Sequence[ScreenerRow],
    *,
    output_path: str | os.PathLike[str] = "data/processed/tradingview_report.html",
    exchange_prefix: str = "BINANCE",
    interval: str = "60",
    top: Optional[int] = None,
    title: str = "TradingView report",
) -> Path:
    """Write a self-contained HTML report with one TradingView widget per row.

    Args:
        rows: ScreenerRow objects, typically the already-sorted top-N.
        output_path: Destination path (relative paths are resolved against cwd).
        exchange_prefix: TradingView exchange prefix (e.g. "BINANCE").
        interval: TradingView interval value, e.g. "60" = 1h, "15" = 15m.
        top: Optional slice limit; when None all rows are rendered.
        title: Page title.

    Returns:
        The resolved Path of the file written.
    """
    rendered_rows: List[ScreenerRow] = list(rows)
    if top is not None:
        rendered_rows = rendered_rows[:top]

    out = Path(output_path)
    _ensure_parent_dir(out)

    # Empty state — still produce a file so the user has something to open.
    if not rendered_rows:
        body = f"""<header><h1>{html.escape(title)}</h1></header>
<div class="empty">No rows in top results — nothing to chart.</div>"""
        out.write_text(_html_shell(title=title, head_extras="", body=body, scripts=""), encoding="utf-8")
        logger.info("TradingView report (empty state) written to %s", out)
        return out

    cards_html: List[str] = []
    bootstrap_cards: List[dict] = []
    for i, row in enumerate(rendered_rows):
        tv_symbol = convert_symbol_to_tradingview(row.symbol, exchange_prefix)
        if not tv_symbol:
            continue
        container_id = f"tv_chart_{i}"
        cards_html.append(_build_card_html(
            container_id=container_id,
            row=row,
            tv_symbol=tv_symbol,
            open_url=tradingview_url(row.symbol, exchange_prefix),
        ))
        bootstrap_cards.append({
            "containerId": container_id,
            "symbol": tv_symbol,
            "interval": interval,
        })

    body = f"""<header>
  <h1>{html.escape(title)}</h1>
  <span class="meta">exchange={html.escape(exchange_prefix)} · interval={html.escape(interval)} · rows={len(bootstrap_cards)}</span>
</header>
<main>
{chr(10).join(cards_html)}
</main>
<footer>Charts are streamed from TradingView. Open this file in a browser with internet access.</footer>"""

    scripts = f"""<script src="https://s3.tradingview.com/tv.js"></script>
<script>{_WIDGET_BOOTSTRAP_TEMPLATE.replace("__CARDS__", json.dumps(bootstrap_cards))}</script>"""

    out.write_text(_html_shell(title=title, head_extras="", body=body, scripts=scripts), encoding="utf-8")
    logger.info("TradingView report written to %s (%d cards)", out, len(bootstrap_cards))
    return out


def _html_shell(*, title: str, head_extras: str, body: str, scripts: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{_DARK_CSS}</style>
  {head_extras}
</head>
<body>
{body}
{scripts}
</body>
</html>"""


# ----------------------------------------------------------------------------
# Public helper for the console layer
# ----------------------------------------------------------------------------

def annotate_rows_with_tv_symbol(rows: Iterable[ScreenerRow], exchange_prefix: str = "BINANCE") -> List[tuple[ScreenerRow, str]]:
    """Convenience: pair each row with its TradingView symbol.

    Useful for renderers that want to print `tv_symbol` alongside the row
    without us mutating `ScreenerRow`.
    """
    return [(r, convert_symbol_to_tradingview(r.symbol, exchange_prefix)) for r in rows]
