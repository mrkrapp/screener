"""Plain-stdlib console table renderer (no extra dependencies)."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from app.charts.tradingview import convert_symbol_to_tradingview
from app.models import ScreenerRow


# (header label, width, format function)
def _columns() -> Sequence[Tuple[str, int, str]]:
    return (
        ("symbol",            12, "{:<12}"),
        ("tv_symbol",         24, "{:<24}"),
        ("price",             12, "{:>12.6g}"),
        ("change_5m",         10, "{:>+10.2f}"),
        ("change_15m",        11, "{:>+11.2f}"),
        ("change_1h",         10, "{:>+10.2f}"),
        ("volume_current",    16, "{:>16.2f}"),
        ("volume_avg",        14, "{:>14.2f}"),
        ("relative_volume",   16, "{:>16.2f}"),
        ("volume_z",           9, "{:>+9.2f}"),
        ("atr",               10, "{:>10.4f}"),
        ("vol_expansion",     13, "{:>13.2f}"),
        ("open_interest",     14, "{:>14.2f}"),
        ("oi_change",         10, "{:>+10.2f}"),
        ("funding_rate",      12, "{:>+12.4f}"),
        ("derivatives_score", 18, "{:>18.2f}"),
        ("score",              8, "{:>8.2f}"),
        ("signals",           40, "{:<40}"),
    )


def render_top_table(
    rows: Iterable[ScreenerRow],
    *,
    top: int = 20,
    title: str = "Top movers",
    exchange_prefix: str = "BINANCE",
) -> str:
    """Render the top-N rows by score into a printable string.

    Includes the `tv_symbol` column populated from the chart helper.
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
        values = (
            r.symbol,
            tv,
            r.price,
            r.change_5m,
            r.change_15m,
            r.change_1h,
            r.volume_current,
            r.volume_avg,
            r.relative_volume,
            r.volume_z,
            r.atr,
            r.vol_expansion,
            r.open_interest,
            r.oi_change,
            r.funding_rate,
            r.derivatives_score,
            r.score,
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
