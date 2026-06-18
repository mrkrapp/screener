"""TradingView symbol helpers and an interactive chart workspace."""

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
  --bg: #090d14;
  --surface: #101725;
  --surface-2: #151e2e;
  --surface-3: #1b2638;
  --line: #253248;
  --line-soft: rgba(108, 127, 158, 0.18);
  --text: #f1f5fb;
  --muted: #8b98ad;
  --dim: #647188;
  --blue: #4387ff;
  --green: #20d39b;
  --red: #ff5e72;
  --yellow: #f1b941;
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0;
  overflow: hidden;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, "Segoe UI", Arial, sans-serif;
  letter-spacing: 0;
}
button, input { font: inherit; }
.workspace {
  height: 100vh;
  min-height: 640px;
  display: grid;
  grid-template-columns: minmax(0, 69%) minmax(380px, 31%);
  background: var(--bg);
}
.chart-side {
  min-width: 0;
  display: grid;
  grid-template-rows: 70px minmax(0, 1fr);
  border-right: 1px solid var(--line);
}
.chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 11px 16px 11px 20px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
}
.market-heading { min-width: 0; }
.market-line {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}
.market-name {
  overflow: hidden;
  font-size: 17px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.market-badge {
  padding: 3px 7px;
  border: 1px solid var(--line);
  border-radius: 4px;
  color: var(--muted);
  background: var(--surface-2);
  font: 10px ui-monospace, monospace;
}
.market-subline {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-top: 5px;
}
.market-price { font: 16px ui-monospace, monospace; }
.market-change { font: 13px ui-monospace, monospace; }
.positive { color: var(--green); }
.negative { color: var(--red); }
.chart-actions { display: flex; align-items: center; gap: 9px; }
.intervals {
  display: inline-flex;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg);
}
.intervals button {
  width: 42px;
  height: 31px;
  border: 0;
  border-right: 1px solid var(--line);
  color: var(--muted);
  background: transparent;
  cursor: pointer;
}
.intervals button:last-child { border-right: 0; }
.intervals button:hover { color: var(--text); background: var(--surface-3); }
.intervals button.active { color: white; background: var(--blue); }
.icon-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 33px;
  height: 33px;
  color: var(--blue);
  border: 1px solid var(--line);
  border-radius: 6px;
  text-decoration: none;
}
.icon-link:hover { background: var(--surface-3); }
.chart-frame {
  position: relative;
  min-height: 0;
  background: #0b0f16;
}
#tradingview_chart { position: absolute; inset: 0; }
.chart-status {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: grid;
  place-items: center;
  color: var(--muted);
  background: #0b0f16;
}
.chart-status.hidden { display: none; }
.details-side {
  position: relative;
  min-width: 0;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  background: var(--surface);
}
.details-head {
  padding: 15px 17px 13px;
  border-bottom: 1px solid var(--line);
}
.selector-button {
  width: 100%;
  min-height: 48px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 8px 11px;
  color: var(--text);
  text-align: left;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 7px;
  cursor: pointer;
}
.selector-button:hover { border-color: #3b4c68; }
.selector-title { font-weight: 650; }
.selector-meta {
  display: block;
  margin-top: 3px;
  color: var(--muted);
  font: 11px ui-monospace, monospace;
}
.selector-chevron { color: var(--muted); font-size: 14px; }
.asset-picker {
  position: absolute;
  top: 73px;
  left: 12px;
  right: 12px;
  z-index: 20;
  overflow: hidden;
  background: var(--surface-2);
  border: 1px solid #35445e;
  border-radius: 7px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.45);
}
.asset-picker[hidden] { display: none; }
.picker-search { padding: 10px; border-bottom: 1px solid var(--line); }
.picker-search input {
  width: 100%;
  height: 36px;
  padding: 0 10px;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 5px;
  outline: none;
}
.picker-search input:focus { border-color: var(--blue); }
.asset-list { max-height: min(560px, calc(100vh - 160px)); overflow: auto; }
.asset-row {
  width: 100%;
  min-height: 58px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  padding: 9px 11px;
  color: var(--text);
  text-align: left;
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--line-soft);
  cursor: pointer;
}
.asset-row:hover { background: var(--surface-3); }
.asset-row.active {
  background: rgba(67, 135, 255, 0.13);
  box-shadow: inset 3px 0 var(--blue);
}
.asset-symbol { font-weight: 620; }
.asset-tv { margin-top: 3px; color: var(--muted); font: 10px ui-monospace, monospace; }
.asset-score { color: var(--green); font: 12px ui-monospace, monospace; }
.tabs {
  display: flex;
  overflow-x: auto;
  padding: 0 12px;
  border-bottom: 1px solid var(--line);
}
.tabs button {
  position: relative;
  flex: 1 0 auto;
  height: 46px;
  padding: 0 12px;
  color: var(--muted);
  background: transparent;
  border: 0;
  cursor: pointer;
}
.tabs button:hover { color: var(--text); }
.tabs button.active { color: var(--text); }
.tabs button.active::after {
  position: absolute;
  right: 8px;
  bottom: 0;
  left: 8px;
  height: 2px;
  content: "";
  background: var(--blue);
}
.tab-content { min-height: 0; overflow: auto; padding: 15px 17px 28px; }
.tab-panel[hidden] { display: none; }
.score-strip {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}
.score-tile {
  min-width: 0;
  padding: 10px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 6px;
}
.score-label {
  overflow: hidden;
  color: var(--muted);
  font-size: 10px;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}
.score-value { margin-top: 5px; font: 18px ui-monospace, monospace; }
.section { margin-top: 17px; }
.section:first-child { margin-top: 0; }
.section-title {
  margin-bottom: 8px;
  color: var(--muted);
  font-size: 10px;
  font-weight: 650;
  text-transform: uppercase;
}
.metric-list {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 6px;
}
.metric-row {
  min-height: 39px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 7px 10px;
  border-bottom: 1px solid var(--line-soft);
}
.metric-row:last-child { border-bottom: 0; }
.metric-name { color: var(--muted); font-size: 12px; }
.metric-value {
  overflow: hidden;
  font: 12px ui-monospace, monospace;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.signal-list { display: flex; flex-wrap: wrap; gap: 6px; }
.signal-chip {
  padding: 5px 7px;
  color: #bfd0ec;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 4px;
  font-size: 11px;
}
.empty-note {
  padding: 26px 12px;
  color: var(--muted);
  text-align: center;
  border: 1px dashed var(--line);
  border-radius: 6px;
}
.disclaimer {
  margin-top: 18px;
  color: var(--dim);
  font-size: 10px;
  line-height: 1.5;
}
@media (max-width: 900px) {
  body { overflow: auto; }
  .workspace {
    height: auto;
    min-height: 100vh;
    grid-template-columns: 1fr;
  }
  .chart-side {
    min-height: 570px;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .details-side { min-height: 560px; }
  .asset-picker { max-height: 70vh; }
}
@media (max-width: 560px) {
  .chart-side { min-height: 520px; grid-template-rows: auto minmax(390px, 1fr); }
  .chart-header { align-items: flex-start; flex-direction: column; }
  .chart-actions { width: 100%; justify-content: space-between; }
  .score-strip { grid-template-columns: 1fr 1fr; }
}
"""


def _row_payload(row: ScreenerRow, *, exchange_prefix: str) -> dict:
    tv_symbol = convert_symbol_to_tradingview(row.symbol, exchange_prefix)
    return {
        "symbol": row.symbol,
        "tvSymbol": tv_symbol,
        "url": tradingview_url(row.symbol, exchange_prefix),
        "price": row.price,
        "score": row.score,
        "quality": row.quality_score,
        "change5m": row.change_5m,
        "change15m": row.change_15m,
        "change1h": row.change_1h,
        "volumeCurrent": row.volume_current,
        "volumeAverage": row.volume_avg,
        "relativeVolume": row.relative_volume,
        "volumeZ": row.volume_z,
        "atr": row.atr,
        "atrPercent": row.atr_percent,
        "priceMoveAtr": row.price_move_atr,
        "volExpansion": row.vol_expansion,
        "openInterest": row.open_interest,
        "oiChange": row.oi_change,
        "fundingRate": row.funding_rate,
        "derivativesScore": row.derivatives_score,
        "trendAlignment": row.trend_alignment,
        "oiConfirmation": row.oi_confirmation,
        "fundingPressure": row.funding_pressure,
        "dollarVolume": row.dollar_volume_current,
        "signals": list(row.signals),
    }


def _asset_rows(items: Sequence[dict]) -> str:
    return "\n".join(
        f"""<button class="asset-row" type="button" data-index="{index}">
  <span>
    <span class="asset-symbol">{html.escape(str(item["symbol"]))}</span>
    <span class="asset-tv">{html.escape(str(item["tvSymbol"]))}</span>
  </span>
  <span class="asset-score">{float(item["score"]):.1f}</span>
</button>"""
        for index, item in enumerate(items)
    )


def generate_tradingview_report(
    rows: Sequence[ScreenerRow],
    *,
    output_path: str | os.PathLike[str] = "data/processed/tradingview_report.html",
    exchange_prefix: str = "BINANCE",
    interval: str = "60",
    top: Optional[int] = None,
    title: str = "crypto_screener — TradingView workspace",
) -> Path:
    """Create a chart-first workspace with analytics for every selected asset."""
    rendered_rows = list(rows)
    if top is not None:
        rendered_rows = rendered_rows[:top]

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    if not rendered_rows:
        output.write_text(
            _shell(
                title,
                '<div class="empty-note">No rows in top results — nothing to chart.</div>',
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

    body = f"""<main class="workspace">
  <section class="chart-side">
    <header class="chart-header">
      <div class="market-heading">
        <div class="market-line">
          <span class="market-name" id="market_name">Loading market</span>
          <span class="market-badge">USDT PERP</span>
        </div>
        <div class="market-subline">
          <span class="market-price" id="market_price">—</span>
          <span class="market-change" id="market_change">—</span>
        </div>
      </div>
      <div class="chart-actions">
        <div class="intervals" aria-label="Chart interval">
          <button type="button" data-interval="5">5m</button>
          <button type="button" data-interval="15">15m</button>
          <button type="button" data-interval="60" class="active">1h</button>
          <button type="button" data-interval="240">4h</button>
          <button type="button" data-interval="D">1D</button>
        </div>
        <a class="icon-link" id="open_tv" href="#" target="_blank" rel="noopener noreferrer"
           title="Open in TradingView" aria-label="Open in TradingView">↗</a>
      </div>
    </header>
    <div class="chart-frame">
      <div class="chart-status" id="chart_status">Loading TradingView chart…</div>
      <div id="tradingview_chart"></div>
    </div>
  </section>

  <aside class="details-side">
    <div class="details-head">
      <button class="selector-button" id="selector_button" type="button" aria-expanded="false">
        <span>
          <span class="selector-title" id="selector_title">Select market</span>
          <span class="selector-meta" id="selector_meta">{html.escape(exchange_prefix)} · {len(items)} markets</span>
        </span>
        <span class="selector-chevron">⌄</span>
      </button>
    </div>

    <div class="asset-picker" id="asset_picker" hidden>
      <div class="picker-search">
        <input id="asset_search" type="search" placeholder="Search symbol…" aria-label="Search symbol">
      </div>
      <div class="asset-list" id="asset_list">
        {_asset_rows(items)}
      </div>
    </div>

    <nav class="tabs" aria-label="Asset analytics">
      <button type="button" class="active" data-tab="overview">Overview</button>
      <button type="button" data-tab="structure">Structure</button>
      <button type="button" data-tab="derivatives">Derivatives</button>
      <button type="button" data-tab="signals">Signals</button>
    </nav>

    <div class="tab-content">
      <section class="tab-panel" data-panel="overview">
        <div class="score-strip">
          <div class="score-tile"><div class="score-label">Composite</div><div class="score-value" id="score_value">—</div></div>
          <div class="score-tile"><div class="score-label">Quality</div><div class="score-value" id="quality_value">—</div></div>
          <div class="score-tile"><div class="score-label">Derivatives</div><div class="score-value" id="derivatives_value">—</div></div>
        </div>
        <div class="section">
          <div class="section-title">Price movement</div>
          <div class="metric-list" id="overview_metrics"></div>
        </div>
        <div class="section">
          <div class="section-title">Volume</div>
          <div class="metric-list" id="volume_metrics"></div>
        </div>
      </section>

      <section class="tab-panel" data-panel="structure" hidden>
        <div class="section">
          <div class="section-title">Market structure</div>
          <div class="metric-list" id="structure_metrics"></div>
        </div>
        <div class="section">
          <div class="section-title">Volatility</div>
          <div class="metric-list" id="volatility_metrics"></div>
        </div>
      </section>

      <section class="tab-panel" data-panel="derivatives" hidden>
        <div class="section">
          <div class="section-title">Positioning</div>
          <div class="metric-list" id="derivative_metrics"></div>
        </div>
      </section>

      <section class="tab-panel" data-panel="signals" hidden>
        <div class="section">
          <div class="section-title">Detected observations</div>
          <div class="signal-list" id="signal_list"></div>
        </div>
        <p class="disclaimer">Analytical observations only. This screen does not provide financial advice or place trades.</p>
      </section>
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

  const byId = (id) => document.getElementById(id);
  const picker = byId("asset_picker");
  const pickerButton = byId("selector_button");
  const chart = byId("tradingview_chart");
  const status = byId("chart_status");

  const number = (value, digits = 2) =>
    value === null || value === undefined || Number.isNaN(value)
      ? "—"
      : Number(value).toLocaleString(undefined, {{ maximumFractionDigits: digits }});
  const signed = (value, digits = 2, suffix = "%") =>
    value === null || value === undefined
      ? "—"
      : `${{value >= 0 ? "+" : ""}}${{Number(value).toFixed(digits)}}${{suffix}}`;
  const metricRow = (name, value, tone = "") =>
    `<div class="metric-row"><span class="metric-name">${{name}}</span><span class="metric-value ${{tone}}">${{value}}</span></div>`;

  function fillMetrics(asset) {{
    byId("score_value").textContent = number(asset.score, 1);
    byId("quality_value").textContent = number(asset.quality, 1);
    byId("derivatives_value").textContent = number(asset.derivativesScore, 1);

    byId("overview_metrics").innerHTML = [
      metricRow("Change 5m", signed(asset.change5m), asset.change5m >= 0 ? "positive" : "negative"),
      metricRow("Change 15m", signed(asset.change15m), asset.change15m >= 0 ? "positive" : "negative"),
      metricRow("Change 1h", signed(asset.change1h), asset.change1h >= 0 ? "positive" : "negative"),
      metricRow("Move in ATR", asset.priceMoveAtr == null ? "—" : `${{number(asset.priceMoveAtr)}}x`)
    ].join("");
    byId("volume_metrics").innerHTML = [
      metricRow("Relative volume", `${{number(asset.relativeVolume)}}x`),
      metricRow("Volume z-score", number(asset.volumeZ)),
      metricRow("Current volume", number(asset.volumeCurrent, 0)),
      metricRow("Dollar volume", asset.dollarVolume == null ? "—" : `$${{number(asset.dollarVolume, 0)}}`)
    ].join("");
    byId("structure_metrics").innerHTML = [
      metricRow("Trend alignment", asset.trendAlignment || "—"),
      metricRow("OI confirmation", asset.oiConfirmation || "—"),
      metricRow("TradingView market", asset.tvSymbol)
    ].join("");
    byId("volatility_metrics").innerHTML = [
      metricRow("ATR", number(asset.atr, 6)),
      metricRow("ATR %", asset.atrPercent == null ? "—" : `${{number(asset.atrPercent)}}%`),
      metricRow("Volatility expansion", `${{number(asset.volExpansion)}}x`)
    ].join("");
    byId("derivative_metrics").innerHTML = [
      metricRow("Open interest", number(asset.openInterest, 0)),
      metricRow("OI change", signed(asset.oiChange), asset.oiChange >= 0 ? "positive" : "negative"),
      metricRow("Funding rate", signed(asset.fundingRate, 4), asset.fundingRate >= 0 ? "positive" : "negative"),
      metricRow("Funding pressure", asset.fundingPressure == null ? "—" : `${{number(asset.fundingPressure)}}x`),
      metricRow("Derivatives score", number(asset.derivativesScore, 1))
    ].join("");
    byId("signal_list").innerHTML = asset.signals.length
      ? asset.signals.map((signal) => `<span class="signal-chip">${{signal}}</span>`).join("")
      : '<div class="empty-note">No strong observations for this market.</div>';
  }}

  function renderChart() {{
    const token = ++renderToken;
    const asset = assets[selectedIndex];
    if (!asset) return;

    byId("market_name").textContent = asset.symbol;
    byId("market_price").textContent = `$${{number(asset.price, 8)}}`;
    const change = byId("market_change");
    change.textContent = signed(asset.change1h);
    change.className = `market-change ${{asset.change1h >= 0 ? "positive" : "negative"}}`;
    byId("selector_title").textContent = asset.symbol;
    byId("selector_meta").textContent = `${{asset.tvSymbol}} · Score ${{number(asset.score, 1)}}`;
    byId("open_tv").href = asset.url;
    fillMetrics(asset);

    document.querySelectorAll(".asset-row").forEach((row) => {{
      row.classList.toggle("active", Number(row.dataset.index) === selectedIndex);
    }});

    status.textContent = "Loading TradingView chart…";
    status.classList.remove("hidden");
    chart.replaceChildren();
    const container = document.createElement("div");
    container.id = `tv_active_${{token}}`;
    container.style.width = "100%";
    container.style.height = "100%";
    chart.appendChild(container);

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
      studies: ["Volume@tv-basicstudies"]
    }});
    window.setTimeout(() => {{
      if (token === renderToken) status.classList.add("hidden");
    }}, 1800);
  }}

  function selectAsset(index) {{
    selectedIndex = index;
    picker.hidden = true;
    pickerButton.setAttribute("aria-expanded", "false");
    renderChart();
    const url = new URL(window.location.href);
    url.searchParams.set("asset", assets[index].tvSymbol);
    history.replaceState({{ asset: assets[index].tvSymbol }}, "", url);
  }}

  pickerButton.addEventListener("click", () => {{
    picker.hidden = !picker.hidden;
    pickerButton.setAttribute("aria-expanded", String(!picker.hidden));
    if (!picker.hidden) byId("asset_search").focus();
  }});
  byId("asset_list").addEventListener("click", (event) => {{
    const row = event.target.closest(".asset-row");
    if (row) selectAsset(Number(row.dataset.index));
  }});
  byId("asset_search").addEventListener("input", (event) => {{
    const query = event.target.value.trim().toLowerCase();
    document.querySelectorAll(".asset-row").forEach((row) => {{
      const asset = assets[Number(row.dataset.index)];
      row.hidden = !(`${{asset.symbol}} ${{asset.tvSymbol}}`.toLowerCase().includes(query));
    }});
  }});
  document.addEventListener("click", (event) => {{
    if (!picker.hidden && !picker.contains(event.target) && !pickerButton.contains(event.target)) {{
      picker.hidden = true;
      pickerButton.setAttribute("aria-expanded", "false");
    }}
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
  document.querySelector(".tabs").addEventListener("click", (event) => {{
    const button = event.target.closest("button[data-tab]");
    if (!button) return;
    document.querySelectorAll(".tabs button").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelectorAll(".tab-panel").forEach((panel) => {{
      panel.hidden = panel.dataset.panel !== button.dataset.tab;
    }});
  }});
  document.addEventListener("keydown", (event) => {{
    if (event.key === "Escape") {{
      picker.hidden = true;
      pickerButton.setAttribute("aria-expanded", "false");
    }}
  }});

  const requested = new URL(window.location.href).searchParams.get("asset");
  const requestedIndex = assets.findIndex((asset) => asset.tvSymbol === requested);
  if (requestedIndex >= 0) selectedIndex = requestedIndex;
  renderChart();
}})();
</script>"""

    output.write_text(_shell(title, body, script), encoding="utf-8")
    logger.info("TradingView workspace written to %s (%d markets)", output, len(items))
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
