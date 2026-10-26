"""ARP-005 ALPHA EXPANSION §5/§31 — adversarial PIT tests for HTF construction.

TEST_TARGET == RUNTIME_TARGET: these are exactly the modules the driver
``scripts/alpha_expansion_v1.py`` imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.research.alpha_expansion.htf import (  # noqa: E402
    HOUR_MS,
    assert_pit,
    build_htf_bars,
    completed_bars,
    tf_ms_for,
)

# 2019-01-01 00:00:00 UTC
DAY0 = 1546300800000


def hourly(closes: list[float], *, start: int = DAY0, symbol: str = "X") -> list[OHLCV]:
    return [
        OHLCV(symbol=symbol, timestamp=start + i * HOUR_MS, open=c, high=c + 1.0, low=c - 1.0,
              close=c, volume=1.0)
        for i, c in enumerate(closes)
    ]


def test_tf_ms_guard() -> None:
    assert tf_ms_for(4) == 4 * HOUR_MS
    with pytest.raises(ValueError):
        tf_ms_for(0)
    with pytest.raises(ValueError):
        tf_ms_for(-1)


def test_htf_bucket_alignment_utc() -> None:
    bars = hourly([float(100 + k) for k in range(24)])
    d = build_htf_bars(bars, 24)
    assert len(d) == 1
    assert d[0].open_ms == DAY0  # exactly the UTC day boundary
    assert d[0].open_ms % tf_ms_for(24) == 0
    assert d[0].close_ms == DAY0 + tf_ms_for(24) - 1


def test_htf_partial_bucket_dropped() -> None:
    # 23 hours only -> the day bucket is incomplete and must not be emitted
    bars = hourly([float(100 + k) for k in range(23)])
    assert build_htf_bars(bars, 24) == []
    # 4h bucket with only 3 hours -> dropped
    assert build_htf_bars(hourly([1.0, 2.0, 3.0]), 4) == []


def test_htf_gap_shortens_bucket() -> None:
    bars = hourly([float(100 + k) for k in range(24)])
    # remove one interior hour -> 4h bucket 1 is now incomplete -> 5 x 4h emitted
    holed = [b for b in bars if b.timestamp != DAY0 + 2 * HOUR_MS]
    fours = build_htf_bars(holed, 4)
    assert len(fours) == 5
    # the day bucket is also incomplete now -> dropped
    assert build_htf_bars(holed, 24) == []


def test_htf_close_time_and_availability() -> None:
    bars = hourly([float(100 + k) for k in range(24)])
    d = build_htf_bars(bars, 24)[0]
    # not available one ms before its close, available exactly at its close
    assert completed_bars([d], d.close_ms - 1) == []
    assert completed_bars([d], d.close_ms) == [d]
    with pytest.raises(ValueError):
        assert_pit([d], d.close_ms - 1)
    assert_pit([d], d.close_ms)  # does not raise


def test_htf_tiles_reconstruct_the_same_day() -> None:
    bars = hourly([float(100 + k) for k in range(24)])
    d = build_htf_bars(bars, 24)[0]
    fours = build_htf_bars(bars, 4)
    eights = build_htf_bars(bars, 8)
    assert len(fours) == 6 and len(eights) == 3
    # open/close/reconstruction
    assert fours[0].open == d.open and fours[-1].close == d.close
    assert max(f.high for f in fours) == d.high
    assert min(f.low for f in fours) == d.low
    assert eights[0].open == d.open and eights[-1].close == d.close


def test_htf_ignores_a_trailing_partial_day() -> None:
    # a full day plus 5 extra forming hours: only the complete day is emitted
    bars = hourly([float(100 + k) for k in range(29)])
    assert len(build_htf_bars(bars, 24)) == 1
