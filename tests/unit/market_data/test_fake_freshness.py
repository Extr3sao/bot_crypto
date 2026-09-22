"""RUN-OP-004 — fake market data freshness (DEF-OP-003-FAKE-EPOCH).

Reproducer + permanent regression:

The baseline ``make_flat_ohlcv`` anchored every synthetic candle at the
fixed epoch ``1_700_000_000_000`` (Nov 2023). The canonical decision cycle
feeds that history to the router, whose freshness gate
(``STALE_THRESHOLD_MS = 15 min``) rejects every context as
``stale_context`` - so even a correctly parsed universe never reaches
strategy generation with the fake provider.

Contract enforced here:

- default generation is FRESH relative to the run (no fixed historical epoch);
- timestamps remain ordered with the declared candle spacing (60s);
- an injectable ``now_ms`` makes output fully deterministic (no time race).

FAIL BEFORE FIX (baseline): newest timestamp is Nov 2023, ~3 years stale.
"""

from __future__ import annotations

import itertools
import time

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.market_data.fake import build_demo_fetcher, make_flat_ohlcv

BAR_MS = 60_000


def _now_ms() -> int:
    return int(time.time() * 1000)


def test_default_anchor_is_fresh_relative_to_run() -> None:
    rows = make_flat_ohlcv("BTC/USDT", 5, last_close=100.0)
    newest = rows[-1].timestamp
    now = _now_ms()
    assert newest <= now + 60_000, f"newest {newest} is in the future beyond tolerance"
    assert newest >= now - 5 * 60_000, (
        f"newest {newest} is stale (now={now}); fake data must be fresh relative to the run"
    )


def test_explicit_now_ms_is_deterministic() -> None:
    anchor = 1_800_000_000_000
    rows = make_flat_ohlcv("BTC/USDT", 5, last_close=100.0, now_ms=anchor)
    assert [r.timestamp for r in rows] == [
        anchor - 4 * BAR_MS,
        anchor - 3 * BAR_MS,
        anchor - 2 * BAR_MS,
        anchor - 1 * BAR_MS,
        anchor,
    ]


def test_explicit_now_ms_repeatable() -> None:
    anchor = 1_800_000_000_000
    a = make_flat_ohlcv("BTC/USDT", 20, last_close=100.0, now_ms=anchor)
    b = make_flat_ohlcv("BTC/USDT", 20, last_close=100.0, now_ms=anchor)
    assert [r.timestamp for r in a] == [r.timestamp for r in b]


def test_timestamps_ordered_with_correct_spacing() -> None:
    for kwargs in ({"last_close": 100.0}, {"last_close": 100.0, "now_ms": 1_800_000_000_000}):
        rows = make_flat_ohlcv("BTC/USDT", 100, **kwargs)
        for prev, curr in itertools.pairwise(rows):
            assert curr.timestamp - prev.timestamp == BAR_MS
        assert rows[-1].timestamp > rows[0].timestamp


def test_build_demo_fetcher_default_is_fresh() -> None:
    settings = load_settings(config_dir="config")
    source = build_demo_fetcher(settings)
    now = _now_ms()
    for symbol, bars in source.ohlcv_by_symbol.items():
        newest = bars[-1].timestamp
        assert newest >= now - 10 * 60_000, f"{symbol} newest {newest} is stale (now={now})"


def test_build_demo_fetcher_threads_single_anchor() -> None:
    """All seeded symbols share the same deterministic anchor (one clock)."""
    settings = load_settings(config_dir="config")
    anchor = 1_800_000_000_000
    source = build_demo_fetcher(settings, now_ms=anchor)
    newest_by_symbol = {
        symbol: bars[-1].timestamp for symbol, bars in source.ohlcv_by_symbol.items()
    }
    assert newest_by_symbol, "no seeded symbols"
    assert set(newest_by_symbol.values()) == {anchor}


@pytest.mark.parametrize("n", [1, 2, 22, 100])
def test_single_bar_anchor(n: int) -> None:
    anchor = 1_800_000_000_000
    rows = make_flat_ohlcv("BTC/USDT", n, last_close=100.0, now_ms=anchor)
    assert rows[0].timestamp == anchor - (n - 1) * BAR_MS
    assert rows[-1].timestamp == anchor
