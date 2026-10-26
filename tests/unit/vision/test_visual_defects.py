"""Audit defects in the visual analysis, pinned as tests before the fix.

The audit of the rendered chart found three concrete defects, each of which changes what
the model sees:

* **D1 — the volume histogram was drawn twice**, once inside the candle loop and once as
  a full series afterwards. The second pass stacks alpha on the same pixels, so the
  volume panel is darker and blurrier than designed, and the drawing costs double.
* **D2 — the last-price label sat at the right edge of the canvas**; the probe measured
  124 ink pixels in the last three columns, i.e. the label is clipped or touching the
  border. A number the reader cannot finish is worse than no number.
* **D3 — candle resolution was too coarse for a vision model**: 120 candles over 712 px
  is 5.93 px per slot and a 3.80 px body. Structure at sub-pixel width is invisible.

The tests below fail on the audited revision and pass after the fix; the spec version
must move with the pixels, or every stored image hash would describe a drawing nobody can
reproduce anymore.
"""

from __future__ import annotations

import io

import matplotlib.image as mpimg
import pytest

from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision import chart as chart_module
from trading_bot.vision.chart import CHART_SPEC_VERSION, build_figure, render_chart_png

HOUR_MS = 3_600_000
START_MS = 1_770_000_000_000


def bars(count: int, *, drift: float = 0.001) -> list[Bar]:
    out: list[Bar] = []
    price = 100.0
    for i in range(count):
        step = drift if i % 2 == 0 else -drift
        close = price * (1.0 + step)
        out.append(
            Bar(
                ts_ms=START_MS + i * HOUR_MS,
                open=price,
                high=max(price, close) * 1.001,
                low=min(price, close) * 0.999,
                close=close,
                volume=100.0 + (i % 11),
            )
        )
        price = close
    return out


def test_D1_the_volume_histogram_is_drawn_once_per_candle():
    figure, axes = build_figure(bars(40), symbol="BTC/USDT", window_bars=40)
    try:
        volume_axes = axes["volume"]
        rectangles = [
            patch
            for patch in volume_axes.patches
            if isinstance(patch, chart_module.Rectangle)
        ]
        assert len(rectangles) == 40, (
            f"expected one volume bar per candle, found {len(rectangles)} "
            "(the histogram is being drawn more than once)"
        )
    finally:
        figure.clear()


def test_D2_the_last_price_label_is_not_clipped_by_the_canvas():
    image = render_chart_png(bars(60), symbol="BTC/USDT")
    rgb = (mpimg.imread(io.BytesIO(image.png))[:, :, :3] * 255).astype(int)

    for edge, band in (
        ("right", rgb[:, -2:, :]),
        ("left", rgb[:, :2, :]),
        ("top", rgb[:2, :, :]),
        ("bottom", rgb[-2:, :, :]),
    ):
        ink = int((band.sum(axis=2) < 720).sum())
        assert ink == 0, f"the {edge} border carries {ink} ink pixels: a label is clipped"


def test_D2_the_annotation_is_inside_the_figure_box():
    figure, axes = build_figure(bars(60), symbol="BTC/USDT", window_bars=60)
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        renderer = FigureCanvasAgg(figure).get_renderer()
        figure_box = figure.bbox
        assert figure_box.width > 0
        for artist in axes["price"].texts:
            window = artist.get_window_extent(renderer=renderer)
            assert window.x0 >= 0 and window.x1 <= figure_box.x1 + 0.5, (
                f"annotation {artist.get_text()!r} leaves the canvas: "
                f"{window.x0:.1f}..{window.x1:.1f} vs width {figure_box.x1:.1f}"
            )
    finally:
        figure.clear()


def test_D3_candles_are_wide_enough_to_read():
    window = chart_module.DEFAULT_WINDOW_BARS
    axes_px = (0.955 - 0.065) * chart_module.WIDTH_IN * chart_module.DPI
    slot = axes_px / window
    body = slot * 0.64
    assert slot >= 8.0, f"{slot:.2f}px per candle slot is too coarse for a vision model"
    assert body >= 5.0, f"{body:.2f}px candle body is too thin to read"


def test_D3_the_image_stays_within_the_budget_it_declares():
    """Resolution went up, so the declared token estimate must have gone up with it."""
    from trading_bot.vision.settings import load_vision_config

    image = render_chart_png(bars(120), symbol="BTC/USDT")
    rgb = mpimg.imread(io.BytesIO(image.png))
    height, width = rgb.shape[0], rgb.shape[1]
    assert (width, height) == (int(chart_module.WIDTH_IN * chart_module.DPI),
                               int(chart_module.HEIGHT_IN * chart_module.DPI))

    estimate = load_vision_config(env={}).provider.prices.image_tokens_estimate
    # OpenAI bills tiles of 512px; a 1152x768 image is ~6 tiles ~= 1.4k tokens.
    tiles = ((width + 511) // 512) * ((height + 511) // 512)
    assert estimate >= tiles * 170, (
        f"declared {estimate} tokens for a {width}x{height} image ({tiles} tiles)"
    )


def test_the_spec_version_moved_with_the_pixels():
    assert CHART_SPEC_VERSION == "ai-vision-chart/2", (
        "changing the drawing without moving the spec version would orphan every "
        "image hash already written to a ledger"
    )


def test_the_window_label_and_spec_go_into_the_fingerprint():
    image = render_chart_png(bars(60), symbol="ETH/USDT")
    fingerprint = image.fingerprint()

    assert fingerprint["chart_spec_version"] == CHART_SPEC_VERSION
    assert fingerprint["bar_count"] == 60
    assert fingerprint["symbol"] == "ETH/USDT"
    assert fingerprint["bytes"] == image.byte_length > 0


@pytest.mark.parametrize("count", [10, 60, 200])
def test_the_renderer_survives_the_edges_of_its_window(count):
    image = render_chart_png(bars(count), symbol="BTC/USDT", window_bars=max(10, count))

    assert image.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert image.bar_count == count


def test_a_flat_market_still_produces_a_readable_chart():
    """A dead market is the case where a vision model can hallucinate structure."""
    flat = [
        Bar(ts_ms=START_MS + i * HOUR_MS, open=100.0, high=100.0, low=100.0, close=100.0, volume=5.0)
        for i in range(40)
    ]
    image = render_chart_png(flat, symbol="BTC/USDT", window_bars=40)

    assert image.byte_length > 5_000
    rgb = (mpimg.imread(io.BytesIO(image.png))[:, :, :3] * 255).astype(int)
    assert int((rgb.sum(axis=2) < 720).sum()) > 1_000, "an empty image would fool the caller"
