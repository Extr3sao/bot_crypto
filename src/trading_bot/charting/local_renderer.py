"""Local SVG chart renderer used when TradingView is unavailable."""

from __future__ import annotations

from html import escape

from trading_bot.charting.snapshots import ChartSnapshotRequest
from trading_bot.trade_journal.types import ChartSnapshot


def render_local_chart_snapshot(request: ChartSnapshotRequest) -> ChartSnapshot:
    if not request.candles:
        raise ValueError("candles must be non-empty")

    request.output_dir.mkdir(parents=True, exist_ok=True)
    path = request.output_dir / f"{_safe_filename(request.trade_case_id)}.svg"
    svg = _render_svg(request)
    path.write_text(svg, encoding="utf-8")
    return ChartSnapshot(
        snapshot_id=f"local:{request.trade_case_id}:{request.captured_at}",
        trade_case_id=request.trade_case_id,
        provider="local_renderer",
        path=str(path),
        status="fallback",
        captured_at=request.captured_at,
        overlays={
            "entry": request.entry_price,
            "tp": request.tp_price,
            "sl": request.sl_price,
            "zones": [zone.zone_id for zone in request.zones],
        },
    )


def _render_svg(request: ChartSnapshotRequest) -> str:
    width = 1080
    height = 680
    pad_left = 72
    pad_right = 32
    pad_top = 52
    pad_bottom = 72
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    prices = [value for candle in request.candles for value in (candle.high, candle.low)]
    prices.extend([request.entry_price, request.tp_price, request.sl_price])
    for zone in request.zones:
        prices.extend([zone.low, zone.high])
    min_price = min(prices)
    max_price = max(prices)
    span = max(max_price - min_price, 1e-9)
    min_price -= span * 0.06
    max_price += span * 0.06

    def x_for(idx: int) -> float:
        if len(request.candles) == 1:
            return pad_left + plot_w / 2
        return pad_left + (idx / (len(request.candles) - 1)) * plot_w

    def y_for(price: float) -> float:
        return pad_top + ((max_price - price) / (max_price - min_price)) * plot_h

    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>",
        "<rect width='100%' height='100%' fill='#0b0f14'/>",
        f"<text x='{pad_left}' y='32' fill='#f2f4f8' font-family='Consolas, monospace' font-size='22'>{escape(request.symbol)} {escape(request.direction)}</text>",
        f"<text x='{pad_left}' y='{height - 28}' fill='#9aa4b2' font-family='Consolas, monospace' font-size='14'>trade_case_id={escape(request.trade_case_id)}</text>",
        f"<rect x='{pad_left}' y='{pad_top}' width='{plot_w}' height='{plot_h}' fill='#111821' stroke='#2a3441'/>",
    ]

    for zone in request.zones:
        y1 = y_for(zone.high)
        y2 = y_for(zone.low)
        fill = "#1d7f5c" if zone.kind in {"support", "range_low", "accumulation"} else "#8a5c1f"
        parts.append(
            f"<rect x='{pad_left}' y='{min(y1, y2):.2f}' width='{plot_w}' height='{abs(y2 - y1):.2f}' "
            f"fill='{fill}' opacity='0.22'/>"
        )
        parts.append(
            f"<text x='{pad_left + 8}' y='{min(y1, y2) + 16:.2f}' fill='#cfd7e3' "
            f"font-family='Consolas, monospace' font-size='12'>{escape(zone.kind)} {zone.low:.4f}-{zone.high:.4f}</text>"
        )

    candle_w = max(3.0, min(16.0, plot_w / max(len(request.candles), 1) * 0.55))
    for idx, candle in enumerate(request.candles):
        x = x_for(idx)
        color = "#00c48c" if candle.close >= candle.open else "#ff5a5f"
        y_open = y_for(candle.open)
        y_close = y_for(candle.close)
        y_high = y_for(candle.high)
        y_low = y_for(candle.low)
        body_y = min(y_open, y_close)
        body_h = max(abs(y_close - y_open), 1.0)
        parts.append(f"<line x1='{x:.2f}' y1='{y_high:.2f}' x2='{x:.2f}' y2='{y_low:.2f}' stroke='{color}' stroke-width='1.4'/>")
        parts.append(f"<rect x='{x - candle_w / 2:.2f}' y='{body_y:.2f}' width='{candle_w:.2f}' height='{body_h:.2f}' fill='{color}'/>")

    parts.extend(
        [
            _price_line("ENTRY", request.entry_price, y_for(request.entry_price), "#f2f4f8", pad_left, plot_w),
            _price_line("TP", request.tp_price, y_for(request.tp_price), "#00d084", pad_left, plot_w),
            _price_line("SL", request.sl_price, y_for(request.sl_price), "#ff5a5f", pad_left, plot_w),
            "</svg>",
        ]
    )
    return "\n".join(parts)


def _price_line(label: str, price: float, y: float, color: str, x: int, width: int) -> str:
    return (
        f"<g><line x1='{x}' y1='{y:.2f}' x2='{x + width}' y2='{y:.2f}' "
        f"stroke='{color}' stroke-width='1.4' stroke-dasharray='8 6'/>"
        f"<text x='{x + width - 150}' y='{y - 6:.2f}' fill='{color}' "
        f"font-family='Consolas, monospace' font-size='13'>{label} {price:.4f}</text></g>"
    )


def _safe_filename(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    return safe or "chart_snapshot"


__all__ = ["render_local_chart_snapshot"]
