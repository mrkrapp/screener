"""Plain-stdlib console table renderer (no extra dependencies)."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from app.charts.tradingview import convert_symbol_to_tradingview
from app.models import ScreenerRow
from app.signals.context import SignalContext


def _fmt_opt_float(value, spec: str = "{:.2f}") -> str:
    if value is None:
        return "-"
    return spec.format(value)


# (header label, width, format function). `{:<` means left-justified, anything
# else is right-justified for the header to match.
def _columns() -> Sequence[Tuple[str, int, str]]:
    return (
        ("symbol",            12, "{:<12}"),
        ("tv_symbol",         24, "{:<24}"),
        ("price",             12, "{:>12.6g}"),
        ("change_5m",         10, "{:>+10.2f}"),
        ("change_15m",        11, "{:>+11.2f}"),
        ("change_1h",         10, "{:>+10.2f}"),
        ("rvol",               7, "{:>7.2f}"),
        ("volume_z",           8, "{:>+8.2f}"),
        ("atr",               10, "{:>10.4f}"),
        ("vol_exp",            8, "{:>8.2f}"),
        ("oi_change",         10, "{:>+10.2f}"),
        ("funding_rate",      12, "{:>+12.4f}"),
        ("deriv_score",       11, "{:>11.2f}"),
        ("score",              8, "{:>8.2f}"),
        # --- Quality columns (Part 4) ---
        ("quality",            8, "{:>8.2f}"),
        ("trend_align",       17, "{:<17}"),
        ("oi_confirm",        24, "{:<24}"),
        ("pm_atr",             7, "{:>7}"),       # may be None → printed as string
        ("dol_vol_curr",      14, "{:>14}"),      # may be None → printed as string
        ("signals",           28, "{:<28}"),
    )


def render_top_table(
    rows: Iterable[ScreenerRow],
    *,
    top: int = 20,
    title: str = "Top movers",
    exchange_prefix: str = "BINANCE",
) -> str:
    """Render the top-N rows by score into a printable string.

    Includes the `tv_symbol`, `quality_score`, `trend_alignment`,
    `oi_confirmation`, `price_move_atr`, and `dollar_volume_current` columns.
    """
    sorted_rows = sorted(rows, key=lambda r: r.score, reverse=True)[:top]

    cols = _columns()
    header = " ".join(label.ljust(width) if fmt.startswith("{:<") else label.rjust(width)
                       for label, width, fmt in cols)
    sep = "-" * len(header)

    lines: List[str] = [title, sep, header, sep]
    if not sorted_rows:
        lines.append("(no rows)")
        lines.append(sep)
        return "\n".join(lines)

    for r in sorted_rows:
        tv = convert_symbol_to_tradingview(r.symbol, exchange_prefix)
        # Quality fields may be None; pre-format them to fixed-width strings.
        pm_atr_s = _fmt_opt_float(r.price_move_atr, "{:.2f}")
        dv_curr_s = _fmt_opt_float(r.dollar_volume_current, "{:.0f}")
        values = (
            r.symbol,
            tv,
            r.price,
            r.change_5m,
            r.change_15m,
            r.change_1h,
            r.relative_volume,
            r.volume_z,
            r.atr,
            r.vol_expansion,
            r.oi_change,
            r.funding_rate,
            r.derivatives_score,
            r.score,
            r.quality_score,
            r.trend_alignment,
            r.oi_confirmation,
            pm_atr_s,
            dv_curr_s,
            ",".join(r.signals) if r.signals else "-",
        )
        formatted = " ".join(fmt.format(value) for (_, _, fmt), value in zip(cols, values))
        lines.append(formatted)
    lines.append(sep)
    return "\n".join(lines)


def render_compact_view(
    rows: Iterable[ScreenerRow],
    *,
    top: int = 20,
    title: str = "Compact view",
    exchange_prefix: str = "BINANCE",
) -> str:
    """Single-line-per-row compact summary suitable for terminals.

    Format per row:
        BTC/USDT:USDT     score 72.4  TV BINANCE:BTCUSDT.P     [volume_spike, momentum_move]
    """
    sorted_rows = sorted(rows, key=lambda r: r.score, reverse=True)[:top]

    lines: List[str] = [title, "-" * 88]
    if not sorted_rows:
        lines.append("(no rows)")
        return "\n".join(lines)

    for r in sorted_rows:
        tv = convert_symbol_to_tradingview(r.symbol, exchange_prefix)
        sig = ", ".join(r.signals) if r.signals else "-"
        lines.append(
            f"  {r.symbol:<20} score {r.score:>6.2f}   TV {tv:<24} [{sig}]"
        )
    return "\n".join(lines)


def render_signal_context_block(
    contexts: Iterable[SignalContext],
    *,
    title: str = "Signal context",
) -> str:
    """Render each context's `compact_summary` and (if any) its risk notes.

    At most two lines per coin. Intentionally compact for terminal use.
    """
    lines: List[str] = [title, "-" * 88]
    contexts = list(contexts)
    if not contexts:
        lines.append("(no contexts)")
        return "\n".join(lines)
    for ctx in contexts:
        lines.append(f"  {ctx.compact_summary}")
        if ctx.risk_notes:
            joined = "; ".join(ctx.risk_notes)
            lines.append(f"    Risks: {joined}")
    return "\n".join(lines)
