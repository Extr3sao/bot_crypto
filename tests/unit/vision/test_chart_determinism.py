"""The image is evidence: the same bars must always produce the same bytes.

If these tests break, every hash in the decision ledger becomes a claim about a picture
nobody can reproduce, and "the model saw this chart" stops being checkable.
"""

from __future__ import annotations

import pytest

from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.chart import (
    CHART_SPEC_VERSION,
    InsufficientBarsError,
    render_chart_png,
    window_fingerprint,
)


def make_bars(
    count: int,
    *,
    start: int = 1_770_000_000_000,
    step_ms: int = 3_600_000,
    drift: float = 0.001,
    alternate: bool = True,
) -> list[Bar]:
    """A synthetic series. ``alternate`` gives both up and down candles, which is what a
    real window looks like and what the colour check needs."""
    bars: list[Bar] = []
    price = 100.0
    for i in range(count):
        open_price = price
        step = drift if (not alternate or i % 2 == 0) else -drift
        close = price * (1.0 + step)
        high = max(open_price, close) * 1.001
        low = min(open_price, close) * 0.999
        bars.append(
            Bar(
                ts_ms=start + i * step_ms,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=float(100 + i % 17),
            )
        )
        price = close
    return bars


def test_the_same_window_renders_byte_identical_png():
    bars = make_bars(60)
    first = render_chart_png(bars, symbol="BTC/USDT")
    second = render_chart_png(bars, symbol="BTC/USDT")

    assert first.png == second.png
    assert first.sha256 == second.sha256
    assert len(first.sha256) == 64


def test_a_different_window_is_a_different_image():
    bars = make_bars(60)
    base = render_chart_png(bars[:50], symbol="BTC/USDT")
    extended = render_chart_png(bars[:51], symbol="BTC/USDT")

    assert base.sha256 != extended.sha256
    assert extended.last_ts_ms == bars[50].ts_ms
    assert base.last_ts_ms == bars[49].ts_ms


def test_only_the_tail_of_a_long_history_is_drawn():
    """A 5 000-bar history and its last 120 bars must be the same picture.

    Otherwise the image would depend on how much history the caller happened to load,
    and two runs over the same window could disagree.
    """
    bars = make_bars(400)
    long_history = render_chart_png(bars, symbol="BTC/USDT", window_bars=120)
    just_tail = render_chart_png(bars[-120:], symbol="BTC/USDT", window_bars=120)

    assert long_history.sha256 == just_tail.sha256
    assert long_history.bar_count == 120


def test_the_image_never_contains_a_bar_the_decision_could_not_see():
    bars = make_bars(80)
    at_decision = render_chart_png(bars[:60], symbol="BTC/USDT")
    with_future = render_chart_png(bars[:70], symbol="BTC/USDT")

    assert at_decision.last_ts_ms == bars[59].ts_ms
    assert with_future.last_ts_ms == bars[69].ts_ms
    assert at_decision.sha256 != with_future.sha256


def test_the_png_is_a_real_png_and_carries_the_spec_version():
    image = render_chart_png(make_bars(40), symbol="ETH/USDT")

    assert image.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert image.byte_length > 8_000
    fingerprint = image.fingerprint()
    assert fingerprint["chart_spec_version"] == CHART_SPEC_VERSION
    assert fingerprint["bar_count"] == 40
    assert fingerprint["symbol"] == "ETH/USDT"
    assert fingerprint["sha256"] == image.sha256


def test_the_image_has_both_candle_colours_and_volume_ink():
    """A blank or monochrome chart would be a silent failure of the whole experiment."""
    import matplotlib.image as mpimg
    import numpy as np

    image = render_chart_png(make_bars(80), symbol="BTC/USDT")
    import io

    rgb = (mpimg.imread(io.BytesIO(image.png))[:, :, :3] * 255).astype(int)

    def share(colour: tuple[int, int, int], tolerance: int = 25) -> float:
        return float(
            (np.abs(rgb - np.array(colour)).sum(axis=2) < tolerance).mean()
        )

    assert share((31, 143, 78)) > 0.0005, "no green (up) candles drawn"
    assert share((179, 38, 30)) > 0.0005, "no red (down) candles drawn"
    assert share((224, 123, 0)) > 0.0003, "EMA 20 missing"
    assert share((26, 79, 214)) > 0.0003, "EMA 50 missing"


def test_too_few_bars_is_an_error_not_an_empty_chart():
    with pytest.raises(InsufficientBarsError):
        render_chart_png(make_bars(5), symbol="BTC/USDT")


def test_a_non_finite_price_is_refused():
    bars = make_bars(30)
    bars[10] = Bar(
        ts_ms=bars[10].ts_ms, open=float("nan"), high=101.0, low=99.0, close=100.0, volume=1.0
    )

    with pytest.raises(ValueError, match="not finite"):
        render_chart_png(bars, symbol="BTC/USDT")


def test_an_impossible_ohlc_bar_is_refused():
    bars = make_bars(30)
    bars[5] = Bar(ts_ms=bars[5].ts_ms, open=100.0, high=99.0, low=98.0, close=99.5, volume=1.0)

    with pytest.raises(ValueError, match="high is below"):
        render_chart_png(bars, symbol="BTC/USDT")


def test_window_fingerprint_tracks_the_numbers_in_the_picture():
    bars = make_bars(50)
    assert window_fingerprint(bars, window_bars=30) == window_fingerprint(bars, window_bars=30)
    assert window_fingerprint(bars, window_bars=30) != window_fingerprint(bars, window_bars=31)
