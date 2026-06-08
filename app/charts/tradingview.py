"""TradingView symbol helpers and an interactive master-detail report."""

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


def convert_symbol_to_tradingview(symbol: str, exchange_prefix: str = "BINANCE") -> str:
    """Convert a CCXT perpetual symbol to a TradingView perpetual ticker."""
    if not symbol:
        return ""

    prefix = (exchange_prefix or "BINANCE").strip().upper()
    value = symbol.strip()
    if ":" in value and value.upper().endswith(".P"):
        return value.upper()

    market = value.partition(":")[0]
    collapsed = market.replace("/", "").upper()
    return f"{prefix}:{collapsed}.P" if collapsed else ""


def tradingview_url(symbol: str, exchange_prefix: str = "BINANCE") -> str:
    tv_symbol = convert_symbol_to_tradingview(symbol, exchange_prefix)
    if not tv_symbol:
        return ""
    return f"https://www.tradingview.com/chart/?symbol={quote(tv_symbol, safe='')}"


_CSS = """
:root {
  color-scheme: dark;
  --bg: #0d1016;
  --panel: #141923;
  --panel-2: #1a2130;
  --line: #283143;
  --text: #e7ebf2;
  --muted: #8e99ab;
  --accent: #4f8cff;
  --good: #2dd4a7;
  --warn: #f0b429;
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, "Segoe UI", Arial, sans-serif;
  letter-spacing: 0;
}
header {
  min-height: 58px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
}
h1 { margin: 0; font-size: 16px; font-weight: 650; }
.meta { color: var(--muted); font: 12px ui-monospace, monospace; }
.workspace {
  height: calc(100vh - 58px);
  min-height: 620px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(330px, 28vw);
}
.chart-pane {
  min-width: 0;
  display: grid;
  grid-template-rows: auto 1fr;
  border-right: 1px solid var(--line);
}
.chart-toolbar {
  min-height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
}
.selected-symbol { font-size: 16px; font-weight: 650; }
.selected-details { margin-top: 4px; color: var(--muted); font-size: 12px; }
.toolbar-actions { display: flex; align-items: center; gap: 8px; }
.intervals {
  display: inline-flex;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 6px;
}
.intervals button, .asset-row {
  font: inherit;
}
.intervals button {
  width: 42px;
  height: 30px;
  border: 0;
  border-right: 1px solid var(--line);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}
.intervals button:last-child { border-right: 0; }
.intervals button.active { background: var(--accent); color: white; }
.open-tv {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  color: var(--accent);
  border: 1px solid var(--line);
  border-radius: 6px;
  text-decoration: none;
}
.chart-frame { position: relative; min-height: 0; background: #10141d; }
#tradingview_chart { position: absolute; inset: 0; }
.chart-status {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--muted);
  background: #10141d;
  z-index: 2;
}
.chart-status.hidden { display: none; }
.asset-pane {
  min-width: 0;
  display: grid;
  grid-template-rows: auto 1fr;
  background: var(--panel);
}
.asset-tools {
  padding: 12px;
  border-bottom: 1px solid var(--line);
}
.asset-tools input {
  width: 100%;
  height: 36px;
  padding: 0 10px;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 6px;
  outline: none;
}
.asset-tools input:focus { border-color: var(--accent); }
.asset-list { overflow: auto; }
.asset-row {
  width: 100%;
  min-height: 72px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  padding: 10px 12px;
  text-align: left;
  color: var(--text);
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--line);
  cursor: pointer;
}
.asset-row:hover { background: var(--panel-2); }
.asset-row.active {
  background: rgba(79, 140, 255, 0.13);
  box-shadow: inset 3px 0 var(--accent);
}
.asset-symbol { overflow: hidden; font-weight: 620; text-overflow: ellipsis; white-space: nowrap; }
.tv-symbol { margin-top: 4px; color: var(--muted); font: 11px ui-monospace, monospace; }
.chips { margin-top: 6px; display: flex; gap: 4px; flex-wrap: wrap; }
.chip {
  padding: 2px 5px;
  color: var(--muted);
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 3px;
  font-size: 10px;
}
.score { color: var(--good); font: 13px ui-monospace, monospace; white-space: nowrap; }
.empty { padding: 48px 20px; color: var(--muted); text-align: center; }
@media (max-width: 800px) {
  header { align-items: flex-start; flex-direction: column; }
  .workspace {
    height: auto;
    min-height: 0;
    grid-template-columns: 1fr;
  }
  .chart-pane { border-right: 0; border-bottom: 1px solid var(--line); }
  .chart-frame { min-height: 430px; }
  .asset-pane { max-height: 520px; }
  .chart-toolbar { align-items: flex-start; flex-direction: column; }
  .toolbar-actions { width: 100%; justify-content: space-between; }
}
"""


def _row_payload(
    row: ScreenerRow,
    *,
    exchange_prefix: str,
) -> dict:
    tv_symbol = convert_symbol_to_tradingview(row.symbol, exchange_prefix)
    return {
        "symbol": row.symbol,
        "tvSymbol": tv_symbol,
        "url": tradingview_url(row.symbol, exchange_prefix),
        "price": row.price,
        "score": row.score,
        "quality": row.quality_score,
        "change1h": row.change_1h,
        "signals": list(row.signals),
    }


def _asset_rows(items: Sequence[dict]) -> str:
    rows: List[str] = []
    for index, item in enumerate(items):
        chips = "".join(
            f'<span class="chip">{html.escape(str(signal))}</span>'
            for signal in item["signals"]
        ) or '<span class="chip">no signals</span>'
        rows.append(
            f"""<button class="asset-row" type="button" data-index="{index}">
  <span>
    <span class="asset-symbol">{html.escape(str(item["symbol"]))}</span>
    <span class="tv-symbol">{html.escape(str(item["tvSymbol"]))}</span>
    <span class="chips">{chips}</span>
  </span>
  <span class="score">{float(item["score"]):.1f}</span>
</button>"""
        )
    return "\n".join(rows)


def generate_tradingview_report(
    rows: Sequence[ScreenerRow],
    *,
    output_path: str | os.PathLike[str] = "data/processed/tradingview_report.html",
    exchange_prefix: str = "BINANCE",
    interval: str = "60",
    top: Optional[int] = None,
    title: str = "crypto_screener — TradingView report",
) -> Path:
    """Create a report with one chart and a selectable row for every asset."""
    rendered_rows = list(rows)
    if top is not None:
        rendered_rows = rendered_rows[:top]

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    if not rendered_rows:
        output.write_text(
            _shell(
                title,
                f'<header><h1>{html.escape(title)}</h1></header>'
                '<div class="empty">No rows in top results — nothing to chart.</div>',
                "",
            ),
            encoding="utf-8",
        )
        return output

    items = [
        _row_payload(row, exchange_prefix=exchange_prefix)
        for row in rendered_rows
        if convert_symbol_to_tradingview(row.symbol, exchange_prefix)
    ]
    safe_json = json.dumps(items, ensure_ascii=False).replace("<", "\\u003c")
    body = f"""<header>
  <h1>{html.escape(title)}</h1>
  <span class="meta">{html.escape(exchange_prefix)} · {len(items)} markets · click any asset</span>
</header>
<main class="workspace">
  <section class="chart-pane">
    <div class="chart-toolbar">
      <div>
        <div class="selected-symbol" id="selected_symbol">Select a market</div>
        <div class="selected-details" id="selected_details"></div>
      </div>
      <div class="toolbar-actions">
        <div class="intervals" aria-label="Chart interval">
          <button type="button" data-interval="5">5m</button>
          <button type="button" data-interval="15">15m</button>
          <button type="button" data-interval="60" class="active">1h</button>
          <button type="button" data-interval="240">4h</button>
          <button type="button" data-interval="D">1D</button>
        </div>
        <a class="open-tv" id="open_tv" href="#" target="_blank" rel="noopener noreferrer"
           title="Open in TradingView" aria-label="Open in TradingView">↗</a>
      </div>
    </div>
    <div class="chart-frame">
      <div class="chart-status" id="chart_status">Loading chart…</div>
      <div id="tradingview_chart"></div>
    </div>
  </section>
  <aside class="asset-pane">
    <div class="asset-tools">
      <input id="asset_search" type="search" placeholder="Search symbol…" aria-label="Search symbol">
    </div>
    <div class="asset-list" id="asset_list">
      {_asset_rows(items)}
    </div>
  </aside>
</main>"""

    script = f"""<script src="https://s3.tradingview.com/tv.js"></script>
<script>
(() => {{
  const assets = {safe_json};
  const defaultInterval = {json.dumps(interval)};
  let selectedIndex = 0;
  let selectedInterval = defaultInterval;
  let renderToken = 0;

  const list = document.getElementById("asset_list");
  const status = document.getElementById("chart_status");
  const chart = document.getElementById("tradingview_chart");
  const name = document.getElementById("selected_symbol");
  const details = document.getElementById("selected_details");
  const openLink = document.getElementById("open_tv");

  function renderChart() {{
    const token = ++renderToken;
    const asset = assets[selectedIndex];
    if (!asset) return;
    name.textContent = asset.symbol;
    details.textContent = `${{asset.tvSymbol}} · Score ${{asset.score.toFixed(1)}} · Quality ${{asset.quality.toFixed(1)}} · 1h ${{asset.change1h >= 0 ? "+" : ""}}${{asset.change1h.toFixed(2)}}%`;
    openLink.href = asset.url;
    status.textContent = "Loading chart…";
    status.classList.remove("hidden");
    chart.replaceChildren();
    const container = document.createElement("div");
    container.id = `tv_active_${{token}}`;
    container.style.width = "100%";
    container.style.height = "100%";
    chart.appendChild(container);

    document.querySelectorAll(".asset-row").forEach((row) => {{
      row.classList.toggle("active", Number(row.dataset.index) === selectedIndex);
    }});

    if (!window.TradingView) {{
      status.textContent = "TradingView is unavailable. Check browser internet access.";
      return;
    }}
    new TradingView.widget({{
      container_id: container.id,
      symbol: asset.tvSymbol,
      interval: selectedInterval,
      timezone: "Etc/UTC",
      theme: "dark",
      style: "1",
      locale: "en",
      enable_publishing: false,
      allow_symbol_change: false,
      hide_side_toolbar: false,
      autosize: true,
      studies: ["Volume@tv-basicstudies"],
      onChartReady: () => {{
        if (token === renderToken) status.classList.add("hidden");
      }}
    }});
    window.setTimeout(() => {{
      if (token === renderToken) status.classList.add("hidden");
    }}, 2500);
  }}

  function selectAsset(index) {{
    selectedIndex = index;
    renderChart();
    const asset = assets[index];
    const url = new URL(window.location.href);
    url.searchParams.set("asset", asset.tvSymbol);
    history.replaceState({{ asset: asset.tvSymbol }}, "", url);
  }}

  list.addEventListener("click", (event) => {{
    const row = event.target.closest(".asset-row");
    if (row) selectAsset(Number(row.dataset.index));
  }});

  document.querySelector(".intervals").addEventListener("click", (event) => {{
    const button = event.target.closest("button[data-interval]");
    if (!button) return;
    selectedInterval = button.dataset.interval;
    document.querySelectorAll(".intervals button").forEach((item) => {{
      item.classList.toggle("active", item === button);
    }});
    renderChart();
  }});

  document.getElementById("asset_search").addEventListener("input", (event) => {{
    const query = event.target.value.trim().toLowerCase();
    document.querySelectorAll(".asset-row").forEach((row) => {{
      const asset = assets[Number(row.dataset.index)];
      row.hidden = !(`${{asset.symbol}} ${{asset.tvSymbol}}`.toLowerCase().includes(query));
    }});
  }});

  const requested = new URL(window.location.href).searchParams.get("asset");
  const requestedIndex = assets.findIndex((asset) => asset.tvSymbol === requested);
  if (requestedIndex >= 0) selectedIndex = requestedIndex;
  renderChart();
}})();
</script>"""
    output.write_text(_shell(title, body, script), encoding="utf-8")
    logger.info("TradingView report written to %s (%d selectable markets)", output, len(items))
    return output


def _shell(title: str, body: str, scripts: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{_CSS}</style>
</head>
<body>
{body}
{scripts}
</body>
</html>"""


def annotate_rows_with_tv_symbol(
    rows: Iterable[ScreenerRow],
    exchange_prefix: str = "BINANCE",
) -> List[tuple[ScreenerRow, str]]:
    return [(row, convert_symbol_to_tradingview(row.symbol, exchange_prefix)) for row in rows]
