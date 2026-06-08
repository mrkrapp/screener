"""Signal Memory outputs: a static HTML report and a CSV export.

Both are pure presentation — they read snapshots + outcomes + statistics and
write files. No metrics, no scoring, no network from Python. The HTML embeds
only inline CSS and a tiny vanilla-JS filter; the TradingView links open in the
user's browser. This report is *separate* from the TradingView chart report.
"""

from __future__ import annotations

import csv
import html
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from app.history.models import (
    HORIZONS,
    LABEL_EXPIRED,
    LABEL_INVALIDATED,
    LABEL_MATCH,
    LABEL_NOT_APPLICABLE,
    LABEL_NO_FOLLOW_THROUGH,
    LABEL_PARTIAL_MATCH,
    LABEL_PENDING,
    LABEL_STRONG_MATCH,
    SignalOutcome,
    SignalSnapshot,
)
from app.history.statistics import GroupStats, HistoryStatistics

logger = logging.getLogger(__name__)

_CSV_FIELDS = [
    "signal_id",
    "symbol",
    "detected_at",
    "direction_hint",
    "confidence",
    "score",
    "quality_score",
    "horizon",
    "price_at_signal",
    "price_at_horizon",
    "return_pct",
    "directional_return_pct",
    "mfe_pct",
    "mae_pct",
    "outcome_label",
    "direction_matched",
    "threshold_matched",
]


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def export_history_csv(
    snapshots: Sequence[SignalSnapshot],
    outcomes: Sequence[SignalOutcome],
    *,
    output_path: str | os.PathLike[str],
) -> Path:
    """Write one CSV row per (signal, horizon). Returns the path written."""
    out = Path(output_path)
    _ensure_parent(out)
    snap_by_id = {s.id: s for s in snapshots}

    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for o in outcomes:
            snap = snap_by_id.get(o.signal_id)
            if snap is None:
                continue
            writer.writerow({
                "signal_id": o.signal_id,
                "symbol": snap.symbol,
                "detected_at": snap.detected_at.isoformat(),
                "direction_hint": snap.direction_hint,
                "confidence": snap.confidence,
                "score": f"{snap.score:.2f}",
                "quality_score": f"{snap.quality_score:.2f}",
                "horizon": o.horizon,
                "price_at_signal": _num(o.price_at_signal),
                "price_at_horizon": _num(o.price_at_horizon),
                "return_pct": _num(o.return_pct),
                "directional_return_pct": _num(o.directional_return_pct),
                "mfe_pct": _num(o.max_favorable_excursion_pct),
                "mae_pct": _num(o.max_adverse_excursion_pct),
                "outcome_label": o.outcome_label,
                "direction_matched": _bool_str(o.direction_matched),
                "threshold_matched": _bool_str(o.threshold_matched),
            })
    logger.info("Signal history CSV written to %s (%d rows)", out, len(outcomes))
    return out


def _num(value: Optional[float]) -> str:
    return "" if value is None else f"{value:.4f}"


def _bool_str(value: Optional[bool]) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

_LABEL_TONE = {
    LABEL_STRONG_MATCH: "good",
    LABEL_MATCH: "good",
    LABEL_PARTIAL_MATCH: "warn",
    LABEL_PENDING: "warn",
    LABEL_INVALIDATED: "bad",
    LABEL_NO_FOLLOW_THROUGH: "bad",
    LABEL_NOT_APPLICABLE: "muted",
    LABEL_EXPIRED: "muted",
}

_CSS = """
:root{color-scheme:dark;--bg:#0f1117;--panel:#161922;--panel2:#1c202b;--border:#262b38;
--text:#e5e7eb;--muted:#9ca3af;--dim:#6b7280;--accent:#3b82f6;--good:#22c55e;--bad:#ef4444;--warn:#f59e0b;}
*{box-sizing:border-box;}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);}
header{padding:16px 24px;border-bottom:1px solid var(--border);}
header h1{margin:0 0 4px;font-size:16px;letter-spacing:.04em;}
header .meta{color:var(--muted);font-size:11px;font-family:monospace;}
.summary{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;padding:16px 24px;}
.kpi{background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:10px 12px;}
.kpi .label{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.05em;}
.kpi .value{font-size:18px;font-weight:600;margin-top:2px;}
.filters{display:flex;gap:6px;flex-wrap:wrap;padding:0 24px 12px;}
.filters button{background:var(--panel2);color:var(--muted);border:1px solid var(--border);border-radius:4px;
padding:4px 10px;font-size:11px;cursor:pointer;}
.filters button.active{color:var(--text);border-color:var(--accent);}
main{padding:0 24px 24px;display:grid;gap:12px;}
.signal{background:var(--panel);border:1px solid var(--border);border-radius:6px;overflow:hidden;}
.signal-head{padding:10px 12px;border-bottom:1px solid var(--border);display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
.symbol{font-weight:600;font-size:14px;}
.pill{font-size:10px;padding:1px 6px;border-radius:3px;background:var(--panel2);color:var(--muted);border:1px solid var(--border);font-family:monospace;}
.pill.good{color:var(--good);}.pill.bad{color:var(--bad);}.pill.warn{color:var(--warn);}
.open-tv{margin-left:auto;font-size:11px;text-decoration:none;color:var(--accent);border:1px solid var(--accent);padding:2px 8px;border-radius:3px;}
.signal-body{padding:10px 12px;display:grid;gap:10px;}
.reasons{font-size:11px;color:var(--muted);}
.reasons b{color:var(--text);font-weight:600;}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;}
.cell{background:var(--panel2);border:1px solid var(--border);border-radius:4px;padding:8px;font-size:11px;}
.cell.good{border-color:rgba(34,197,94,.4);}
.cell.bad{border-color:rgba(239,68,68,.4);}
.cell.warn{border-color:rgba(245,158,11,.4);}
.cell.muted{opacity:.6;}
.cell .hz{font-weight:600;font-size:12px;}
.cell .lbl{font-family:monospace;font-size:10px;margin:2px 0;}
.cell .lbl.good{color:var(--good);}.cell .lbl.bad{color:var(--bad);}.cell .lbl.warn{color:var(--warn);}.cell .lbl.muted{color:var(--dim);}
.cell .m{color:var(--muted);}
.cell .matched{color:var(--good);}
.cell .failed{color:var(--bad);}
.timeline{padding:12px 24px;border-top:1px solid var(--border);}
.timeline h2{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin:0 0 8px;}
.timeline ul{list-style:none;margin:0;padding:0;font-size:11px;color:var(--muted);font-family:monospace;}
.timeline li{padding:2px 0;}
footer{padding:12px 24px;color:var(--dim);font-size:11px;border-top:1px solid var(--border);text-align:center;}
.empty{padding:48px;text-align:center;color:var(--muted);}
"""

_FILTER_JS = """
(function(){
  var buttons=document.querySelectorAll('.filters button');
  var cards=document.querySelectorAll('.signal');
  function apply(f){
    cards.forEach(function(c){
      var show=true;
      if(f==='pending')show=c.dataset.status!=='COMPLETED'&&c.dataset.status!=='EXPIRED';
      else if(f==='matched')show=c.dataset.verdict==='matched';
      else if(f==='failed')show=c.dataset.verdict==='failed';
      else if(f==='bullish')show=c.dataset.direction==='BULLISH_MOMENTUM';
      else if(f==='bearish')show=c.dataset.direction==='BEARISH_MOMENTUM';
      c.style.display=show?'':'none';
    });
  }
  buttons.forEach(function(b){
    b.addEventListener('click',function(){
      buttons.forEach(function(x){x.classList.remove('active');});
      b.classList.add('active');
      apply(b.dataset.filter);
    });
  });
})();
"""


def _kpi(label: str, value: str) -> str:
    return f'<div class="kpi"><div class="label">{html.escape(label)}</div><div class="value">{html.escape(value)}</div></div>'


def _fmt_pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:+.2f}%"


def _fmt_rate(g: Optional[GroupStats]) -> str:
    if g is None or g.sample == 0:
        return "n/a"
    if g.insufficient:
        return f"insufficient ({g.sample})"
    return f"{g.match_rate:.0f}% ({g.sample})"


def _rate_attr(g: Optional[GroupStats], attr: str) -> str:
    """Format a percentage attribute of a GroupStats, honest about samples."""
    if g is None or g.sample == 0:
        return "n/a"
    if g.insufficient:
        return f"insuff ({g.sample})"
    value = getattr(g, attr)
    return "—" if value is None else f"{value:.0f}%"


def _verdict_for_card(outcomes: Sequence[SignalOutcome]) -> str:
    """Coarse per-card verdict used by the filter buttons."""
    labels = {o.outcome_label for o in outcomes}
    if labels & {LABEL_STRONG_MATCH, LABEL_MATCH}:
        return "matched"
    if labels & {LABEL_INVALIDATED, LABEL_NO_FOLLOW_THROUGH}:
        return "failed"
    return "pending"


def _outcome_cell(horizon: str, outcome: Optional[SignalOutcome]) -> str:
    if outcome is None:
        return (
            f'<div class="cell muted"><div class="hz">{horizon}</div>'
            f'<div class="lbl muted">no data</div></div>'
        )
    tone = _LABEL_TONE.get(outcome.outcome_label, "muted")
    matched = "".join(f'<div class="matched">✓ {html.escape(r)}</div>' for r in outcome.matched_reasons)
    failed = "".join(f'<div class="failed">✗ {html.escape(r)}</div>' for r in outcome.failed_reasons)
    return (
        f'<div class="cell {tone}">'
        f'<div class="hz">{horizon}</div>'
        f'<div class="lbl {tone}">{html.escape(outcome.outcome_label)}</div>'
        f'<div class="m">ret {_fmt_pct(outcome.return_pct)}</div>'
        f'<div class="m">dir {_fmt_pct(outcome.directional_return_pct)}</div>'
        f'<div class="m">MFE {_fmt_pct(outcome.max_favorable_excursion_pct)}</div>'
        f'<div class="m">MAE {_fmt_pct(outcome.max_adverse_excursion_pct)}</div>'
        f'{matched}{failed}'
        f'</div>'
    )


def _signal_card(snapshot: SignalSnapshot, outcomes: Sequence[SignalOutcome]) -> str:
    by_hz: Dict[str, SignalOutcome] = {o.horizon: o for o in outcomes}
    cells = "".join(_outcome_cell(hz, by_hz.get(hz)) for hz in HORIZONS)
    signals = " ".join(f'<span class="pill">{html.escape(s)}</span>' for s in snapshot.signals)
    reasons = "".join(f"<li>{html.escape(r)}</li>" for r in snapshot.main_reasons)
    risks = "".join(f"<li>{html.escape(r)}</li>" for r in snapshot.risk_notes)
    risk_block = f'<div class="reasons"><b>Risks:</b><ul>{risks}</ul></div>' if risks else ""
    open_tv = (
        f'<a class="open-tv" target="_blank" rel="noopener noreferrer" '
        f'href="{html.escape(snapshot.tradingview_url)}">Open TradingView</a>'
        if snapshot.tradingview_url else ""
    )
    return (
        f'<div class="signal" data-status="{html.escape(snapshot.status)}" '
        f'data-direction="{html.escape(snapshot.direction_hint)}" '
        f'data-verdict="{_verdict_for_card(outcomes)}">'
        f'<div class="signal-head">'
        f'<span class="symbol">{html.escape(snapshot.symbol)}</span>'
        f'<span class="pill">{html.escape(snapshot.direction_hint)}</span>'
        f'<span class="pill">{html.escape(snapshot.confidence)}</span>'
        f'<span class="pill">score {snapshot.score:.0f}</span>'
        f'<span class="pill">quality {snapshot.quality_score:.0f}</span>'
        f'<span class="pill">{html.escape(snapshot.tradingview_symbol)}</span>'
        f'<span class="pill {_LABEL_TONE.get(snapshot.status, "muted")}">{html.escape(snapshot.status)}</span>'
        f'{open_tv}'
        f'</div>'
        f'<div class="signal-body">'
        f'<div class="reasons">{snapshot.detected_at.strftime("%Y-%m-%d %H:%M UTC")} · '
        f'entry {snapshot.price_at_signal:.6g}</div>'
        f'<div class="reasons">{signals}</div>'
        f'<div class="reasons"><b>Reasons:</b><ul>{reasons}</ul></div>'
        f'{risk_block}'
        f'<div class="grid">{cells}</div>'
        f'</div>'
        f'</div>'
    )


def _timeline(snapshots: Sequence[SignalSnapshot], outcomes: Sequence[SignalOutcome]) -> str:
    events = []
    for s in snapshots:
        events.append((s.detected_at, f"NEW · {s.symbol} {s.direction_hint} (score {s.score:.0f})"))
    for o in outcomes:
        if o.outcome_label not in (LABEL_PENDING,):
            events.append((o.evaluated_at, f"{o.outcome_label} · {o.signal_id[:8]} @ {o.horizon}"))
    events.sort(key=lambda e: e[0], reverse=True)
    items = "".join(
        f'<li>{dt.strftime("%Y-%m-%d %H:%M")} — {html.escape(msg)}</li>'
        for dt, msg in events[:30]
    )
    return f'<div class="timeline"><h2>Recent activity</h2><ul>{items}</ul></div>'


def generate_history_report(
    snapshots: Sequence[SignalSnapshot],
    outcomes: Sequence[SignalOutcome],
    statistics: HistoryStatistics,
    *,
    output_path: str | os.PathLike[str],
    title: str = "Signal Memory",
) -> Path:
    """Write the self-contained Signal Memory HTML report. Returns the path."""
    out = Path(output_path)
    _ensure_parent(out)

    outcomes_by_signal: Dict[str, List[SignalOutcome]] = {}
    for o in outcomes:
        outcomes_by_signal.setdefault(o.signal_id, []).append(o)

    h1 = statistics.by_horizon.get("1h")
    summary = "".join([
        _kpi("Total signals", str(statistics.total_signals)),
        _kpi("Completed", str(statistics.completed_signals)),
        _kpi("Pending", str(statistics.pending_signals)),
        _kpi("Match rate 1h", _fmt_rate(h1)),
        _kpi("Strong 1h", _rate_attr(h1, "strong_rate")),
        _kpi("Invalidated 1h", _rate_attr(h1, "invalidation_rate")),
        _kpi("Avg MFE 1h", _fmt_pct(h1.avg_mfe if h1 else None)),
        _kpi("Avg MAE 1h", _fmt_pct(h1.avg_mae if h1 else None)),
    ])

    filters = (
        '<div class="filters">'
        '<button class="active" data-filter="all">All</button>'
        '<button data-filter="pending">Pending</button>'
        '<button data-filter="matched">Matched</button>'
        '<button data-filter="failed">Failed</button>'
        '<button data-filter="bullish">Bullish</button>'
        '<button data-filter="bearish">Bearish</button>'
        '</div>'
    )

    if not snapshots:
        body_cards = '<div class="empty">No signals recorded yet — run the screener to populate history.</div>'
    else:
        body_cards = "".join(
            _signal_card(s, outcomes_by_signal.get(s.id, [])) for s in snapshots
        )

    timeline = _timeline(snapshots, outcomes) if snapshots else ""

    body = (
        f'<header><h1>{html.escape(title)}</h1>'
        f'<span class="meta">total={statistics.total_signals} · completed={statistics.completed_signals} '
        f'· pending={statistics.pending_signals} · min_sample={statistics.min_sample}</span></header>'
        f'<div class="summary">{summary}</div>'
        f'{filters}'
        f'<main>{body_cards}</main>'
        f'{timeline}'
        f'<footer>Analytical signal memory — descriptive only, not trading advice.</footer>'
    )

    doc = (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{html.escape(title)}</title><style>{_CSS}</style></head>'
        f'<body>{body}<script>{_FILTER_JS}</script></body></html>'
    )
    out.write_text(doc, encoding="utf-8")
    logger.info("Signal history report written to %s (%d signals)", out, len(snapshots))
    return out
