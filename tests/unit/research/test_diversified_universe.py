"""ARP-006 §2-§9 — PIT dynamic-universe tests (listing, liquidity, sync, fail-closed).

TEST_TARGET == RUNTIME_TARGET: exactly the modules the driver imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.diversified.data import DailyBar  # noqa: E402
from trading_bot.research.diversified.universe import (  # noqa: E402
    DynamicAssetUniverse,
    UniverseConfig,
    UniverseError,
)

DAY = 86_400_000
DAY0 = 1_546_300_800_000
FP = "test-fingerprint"


def bars(symbol: str, n: int, *, start: int = 0, price: float = 100.0,
         quote_volume: float = 5_000_000.0, gaps: tuple[int, ...] = ()) -> list[DailyBar]:
    out = []
    for i in range(n):
        if i in gaps:
            continue
        out.append(DailyBar(symbol=symbol, timestamp=DAY0 + (start + i) * DAY, open=price,
                            high=price + 1, low=price - 1, close=price, volume=1.0,
                            quote_volume=quote_volume))
    return out


def universe(corpus: dict, listing: dict, **kw) -> DynamicAssetUniverse:
    return DynamicAssetUniverse(corpus, listing, FP, UniverseConfig(**kw))


def test_not_yet_listed_asset_is_excluded() -> None:
    T = DAY0 + 100 * DAY
    uv = universe({"A": bars("A", 100), "B": bars("B", 100)},
                  {"A": DAY0, "B": DAY0 + 200 * DAY}, min_history_days=10)
    snap = uv.snapshot(T)
    assert "A" in snap.eligible_assets
    assert snap.listing_state["B"] == "NOT_YET_LISTED"
    assert snap.exclusion_reasons["B"] == "not_yet_listed"


def test_low_liquidity_asset_is_excluded() -> None:
    T = DAY0 + 100 * DAY
    uv = universe({"A": bars("A", 100), "B": bars("B", 100, quote_volume=10.0)},
                  {"A": DAY0, "B": DAY0}, min_history_days=10, min_median_quote_volume=1e6)
    snap = uv.snapshot(T)
    assert "A" in snap.eligible_assets
    assert snap.exclusion_reasons["B"] == "liquidity_below_floor"
    assert snap.liquidity_metric["B"] == 10.0


def test_unsynchronized_asset_is_excluded() -> None:
    T = DAY0 + 100 * DAY
    # B's last bar is 3 days before A's -> not synchronized at the feature time.
    uv = universe({"A": bars("A", 100), "B": bars("B", 97)},
                  {"A": DAY0, "B": DAY0}, min_history_days=10, max_stale_days=10)
    snap = uv.snapshot(T)
    assert "A" in snap.eligible_assets
    assert snap.exclusion_reasons["B"] == "unsynchronized_feature_time"
    assert snap.feature_time == DAY0 + 99 * DAY


def test_duplicate_bar_excludes_symbol() -> None:
    T = DAY0 + 100 * DAY
    dup = bars("B", 100)
    dup.append(dup[-1])  # duplicate timestamp
    uv = universe({"A": bars("A", 100), "B": dup}, {"A": DAY0, "B": DAY0}, min_history_days=10)
    snap = uv.snapshot(T)
    assert snap.exclusion_reasons["B"] == "duplicate_bar"


def test_insufficient_history_excludes_symbol() -> None:
    T = DAY0 + 100 * DAY
    uv = universe({"A": bars("A", 100), "B": bars("B", 5)},
                  {"A": DAY0, "B": DAY0}, min_history_days=60)
    snap = uv.snapshot(T)
    assert snap.exclusion_reasons["B"] == "insufficient_history"
    assert snap.history_available["B"] == 5


def test_gap_ratio_excludes_symbol() -> None:
    T = DAY0 + 100 * DAY
    gappy = bars("B", 40, gaps=tuple(range(10, 25)))
    uv = universe({"A": bars("A", 100), "B": gappy}, {"A": DAY0, "B": DAY0},
                  min_history_days=10, max_gap_ratio=0.05)
    snap = uv.snapshot(T)
    assert snap.exclusion_reasons["B"] == "data_quality_gap_ratio"


def test_future_data_is_never_read() -> None:
    T = DAY0 + 50 * DAY
    uv = universe({"A": bars("A", 100)}, {"A": DAY0}, min_history_days=10)
    snap = uv.snapshot(T)
    assert snap.feature_time <= snap.decision_time
    assert snap.history_available["A"] == 51


def test_feature_time_cannot_exceed_decision_time() -> None:
    import dataclasses

    import pytest

    uv = universe({"A": bars("A", 10)}, {"A": DAY0}, min_history_days=1)
    snap = uv.snapshot(DAY0 + 9 * DAY)
    with pytest.raises(UniverseError):
        dataclasses.replace(snap, feature_time=snap.decision_time + 1)


def test_no_eligible_assets_is_a_blocked_snapshot() -> None:
    uv = universe({"A": bars("A", 5)}, {"A": DAY0}, min_history_days=60)
    snap = uv.snapshot(DAY0 + 10 * DAY)
    assert snap.eligible_assets == ()
    assert snap.blocked_reason == "no_eligible_assets"


def test_size_series_is_monotone_with_listings() -> None:
    uv = universe({"A": bars("A", 200), "B": bars("B", 200, start=100)},
                  {"A": DAY0, "B": DAY0 + 100 * DAY}, min_history_days=10)
    sizes = uv.size_series([DAY0 + 50 * DAY, DAY0 + 150 * DAY])
    assert sizes == [1, 2]
