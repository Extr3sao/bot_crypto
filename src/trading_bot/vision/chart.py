"""chart — the image the model actually sees, rendered deterministically.

RFC-AI-VISION-001 / vertical slice. The point of this module is that the picture is
an *input*, not a decoration: it is built from the same ``Bar`` objects the
deterministic lane trades, it never contains a bar the decision could not have seen,
and the same bars always produce the same bytes.

Why byte-identical matters: the decision ledger stores the SHA-256 of the PNG. If the
renderer were free to change fonts, paddings or metadata between runs, the ledger
would be a claim about an image that no longer exists, and the "the model saw this"
evidence would be unfalsifiable.

What is drawn (and deliberately nothing else):

* candles for the window, oldest on the left, newest on the right;
* volume bars sharing the x axis;
* EMA(20) and EMA(50) — computed from the window only;
* the last close as a labelled horizontal level;
* a UTC window label and the bar count.

Anything the model is expected to know but that is not in the pixels (symbol, open
position, equity, risk budget) travels in the text prompt, which is hashed next to the
image so the pair can be replayed.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import matplotlib

matplotlib.use("Agg")  # no display, no GUI toolkit, no Tk dependency

from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.transforms import blended_transform_factory

#: Bumped whenever a pixel changes. The ledger records it so a decision taken on an
#: older rendering can be told apart from one taken after a chart redesign.
CHART_SPEC_VERSION = "ai-vision-chart/1"

#: Bars per image. 120 hours is five days of 1h bars: enough structure for a
#: discretionary read, small enough that candle bodies stay legible at 800x500.
DEFAULT_WINDOW_BARS = 120

#: Fixed geometry. Changing these changes every hash, so they are part of the spec.
WIDTH_IN = 8.0
HEIGHT_IN = 5.0
DPI = 100

_UP = "#1f8f4e"
_DOWN = "#b3261e"
_WICK_UP = "#14663a"
_WICK_DOWN = "#7f1d1a"
_EMA_FAST = "#e07b00"
_EMA_SLOW = "#1a4fd6"
_GRID = "#d9dde3"
_TEXT = "#22262b"


@dataclass(frozen=True, slots=True)
class ChartImage:
    """The rendered bytes plus everything needed to prove which image they are."""

    png: bytes
    sha256: str
    symbol: str
    timeframe: str
    bar_count: int
    first_ts_ms: int
    last_ts_ms: int
    spec_version: str = CHART_SPEC_VERSION

    @property
    def byte_length(self) -> int:
        return len(self.png)

    def fingerprint(self) -> dict[str, Any]:
        """JSON-safe identity of this image, for the ledger."""
        return {
            "sha256": self.sha256,
            "bytes": self.byte_length,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bar_count": self.bar_count,
            "first_open_utc": _utc_iso(self.first_ts_ms),
            "last_open_utc": _utc_iso(self.last_ts_ms),
            "chart_spec_version": self.spec_version,
        }


class InsufficientBarsError(ValueError):
    """Raised when the window has too few bars to draw a meaningful chart."""


def _utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _field(bar: Any, name: str) -> float:
    """Read a bar field from an attribute or a mapping, and require it to be finite."""
    value = bar[name] if isinstance(bar, dict) else getattr(bar, name)
    out = float(value)
    if out != out or out in (float("inf"), float("-inf")):
        raise ValueError(f"bar field {name!r} is not finite: {value!r}")
    return out


def _bars_of(bars: Sequence[Any]) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for bar in bars:
        row = {name: _field(bar, name) for name in ("open", "high", "low", "close", "volume")}
        row["ts_ms"] = float(_field(bar, "ts_ms"))
        if row["high"] < max(row["open"], row["close"]) - 1e-12:
            raise ValueError("bar high is below its open/close")
        if row["low"] > min(row["open"], row["close"]) + 1e-12:
            raise ValueError("bar low is above its open/close")
        out.append(row)
    return out


def _ema(values: list[float], span: int) -> list[float]:
    """EMA seeded with the first value, which is what a charting package shows."""
    if not values:
        return []
    alpha = 2.0 / (span + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1.0 - alpha) * out[-1])
    return out


def render_chart_png(
    bars: Sequence[Any],
    *,
    symbol: str,
    timeframe: str = "1h",
    window_bars: int = DEFAULT_WINDOW_BARS,
) -> ChartImage:
    """Render the last ``window_bars`` bars to a deterministic PNG.

    ``bars`` must be ordered oldest to newest and must contain no future bar: the
    caller passes ``bars[:i + 1]`` at decision time. Only the tail is drawn when the
    history is longer than the window.
    """
    if window_bars < 10:
        raise InsufficientBarsError(f"window_bars={window_bars} is too small to plot")
    rows = _bars_of(bars)
    if len(rows) < 10:
        raise InsufficientBarsError(f"need at least 10 bars, got {len(rows)}")
    window = rows[-window_bars:]

    times = [datetime.fromtimestamp(row["ts_ms"] / 1000.0, tz=UTC) for row in window]
    opens = [row["open"] for row in window]
    highs = [row["high"] for row in window]
    lows = [row["low"] for row in window]
    closes = [row["close"] for row in window]
    volumes = [row["volume"] for row in window]
    xs = list(range(len(window)))

    ema_fast = _ema(closes, 20)
    ema_slow = _ema(closes, 50)

    fig = Figure(figsize=(WIDTH_IN, HEIGHT_IN), dpi=DPI, facecolor="white")
    try:
        grid = fig.add_gridspec(
            2, 1, height_ratios=(4.0, 1.0), hspace=0.06, left=0.065, right=0.955,
            top=0.90, bottom=0.10,
        )
        price_ax = fig.add_subplot(grid[0])
        vol_ax = fig.add_subplot(grid[1], sharex=price_ax)

        for x, o, h, low_px, c in zip(xs, opens, highs, lows, closes, strict=True):
            up = c >= o
            body_color = _UP if up else _DOWN
            wick_color = _WICK_UP if up else _WICK_DOWN
            price_ax.vlines(x, low_px, h, color=wick_color, linewidth=0.9, zorder=2)
            bottom, height = (o, c - o) if c >= o else (c, o - c)
            price_ax.add_patch(
                Rectangle(
                    (x - 0.32, bottom), 0.64, max(height, 1e-9),
                    facecolor=body_color, edgecolor=wick_color, linewidth=0.6, zorder=3,
                )
            )
            vol_ax.bar(x, volumes[x], width=0.64, color=body_color, alpha=0.55, linewidth=0)

        price_ax.plot(xs, ema_fast, color=_EMA_FAST, linewidth=1.2, label="EMA 20", zorder=4)
        price_ax.plot(xs, ema_slow, color=_EMA_SLOW, linewidth=1.2, label="EMA 50", zorder=4)

        last = closes[-1]
        price_ax.axhline(last, color=_TEXT, linewidth=0.8, linestyle=(0, (4, 3)), zorder=1)
        price_ax.annotate(
            f"{last:,.2f}",
            xy=(1.0, last),
            xycoords=blended_transform_factory(price_ax.transAxes, price_ax.transData),
            xytext=(3, 0),
            textcoords="offset points",
            va="center",
            ha="left",
            fontsize=8,
            color=_TEXT,
            annotation_clip=False,
        )

        pad = (max(highs) - min(lows)) * 0.04 or max(abs(last) * 1e-4, 1e-6)
        price_ax.set_ylim(min(lows) - pad, max(highs) + pad)
        price_ax.set_xlim(-0.8, len(window) - 0.2)
        price_ax.grid(True, color=_GRID, linewidth=0.6, alpha=0.9)
        price_ax.set_axisbelow(True)
        for spine in ("top", "left", "right"):
            price_ax.spines[spine].set_visible(False)
        price_ax.spines["bottom"].set_color(_GRID)
        price_ax.yaxis.tick_right()
        price_ax.tick_params(axis="both", labelsize=7, colors=_TEXT, length=2)
        price_ax.tick_params(axis="x", labelbottom=False)
        price_ax.legend(
            loc="upper left", fontsize=7, frameon=False, ncol=2, handlelength=1.4,
            labelcolor=_TEXT,
        )

        vol_ax.bar(xs, volumes, width=0.64, color=_GRID, linewidth=0.3, edgecolor="#b9c0c9")
        vol_ax.set_ylim(0, max(volumes) * 1.12 if volumes and max(volumes) > 0 else 1.0)
        vol_ax.grid(True, axis="y", color=_GRID, linewidth=0.6, alpha=0.9)
        vol_ax.set_axisbelow(True)
        for spine in ("top", "left", "right"):
            vol_ax.spines[spine].set_visible(False)
        vol_ax.spines["bottom"].set_color(_GRID)
        vol_ax.yaxis.tick_right()
        vol_ax.tick_params(axis="y", labelsize=7, colors=_TEXT, length=2)
        vol_ax.tick_params(axis="x", labelsize=7, colors=_TEXT, length=2)
        vol_ax.set_ylabel("vol", fontsize=7, color=_TEXT)

        tick_idx = sorted({round(i * (len(window) - 1) / 5) for i in range(6)})
        vol_ax.set_xticks(tick_idx)
        vol_ax.set_xticklabels([times[i].strftime("%m-%d\n%H:%M") for i in tick_idx])

        fig.suptitle(
            f"{symbol}  {timeframe}  |  last {len(window)} bars  "
            f"{times[0].strftime('%Y-%m-%d %H:%M')} to {times[-1].strftime('%Y-%m-%d %H:%M')} UTC",
            fontsize=9,
            color=_TEXT,
            x=0.065,
            ha="left",
        )

        buf = io.BytesIO()
        # A fixed metadata value keeps the PNG bytes independent of the local
        # matplotlib build; the spec version is the honest identity of the drawing.
        fig.savefig(
            buf,
            format="png",
            dpi=DPI,
            facecolor="white",
            metadata={"Software": CHART_SPEC_VERSION, "Creation Time": None},
        )
    finally:
        fig.clear()

    png = buf.getvalue()
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("renderer did not produce a PNG")
    return ChartImage(
        png=png,
        sha256=hashlib.sha256(png).hexdigest(),
        symbol=symbol,
        timeframe=timeframe,
        bar_count=len(window),
        first_ts_ms=int(window[0]["ts_ms"]),
        last_ts_ms=int(window[-1]["ts_ms"]),
    )


def window_fingerprint(bars: Sequence[Any], *, window_bars: int = DEFAULT_WINDOW_BARS) -> str:
    """Hash of the numbers that go into the picture, independent of the drawing.

    Useful to prove the chart contained exactly the intended window: two calls with
    the same fingerprint must render the same image.
    """
    window = list(bars)[-window_bars:]
    payload = json.dumps(
        [
            [int(_field(b, "ts_ms"))]
            + [round(_field(b, name), 8) for name in ("open", "high", "low", "close", "volume")]
            for b in window
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
