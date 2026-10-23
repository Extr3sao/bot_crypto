"""ARP-005 ALPHA EXPANSION §9-§11 — cross-sectional synchronization / fail-closed tests.

TEST_TARGET == RUNTIME_TARGET: exactly the modules the driver imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.research.alpha_expansion.strategies import (  # noqa: E402
    RotationConfig,
    simulate_xsec_rotation,
)
from trading_bot.research.alpha_expansion.xsec import (  # noqa: E402
    CrossSectionalError,
    CrossSectionalSnapshot,
    CrossSectionalSnapshotBuilder,
    SnapshotRequest,
)

DAY = 86_400_000
DAY0 = 1546300800000


def daily(
    symbol: str, closes: list[float], *, start_day: int = 0, gaps: tuple[int, ...] = ()
) -> list[OHLCV]:
    out = []
    for i, c in enumerate(closes):
        if i in gaps:
            continue
        out.append(
            OHLCV(
                symbol=symbol,
                timestamp=DAY0 + (start_day + i) * DAY,
                open=c,
                high=c + 1,
                low=c - 1,
                close=c,
                volume=1.0,
            )
        )
    return out


def req(decision_day: int, *, window: int = 1, ascending: bool = False) -> SnapshotRequest:
    return SnapshotRequest(
        decision_time=DAY0 + decision_day * DAY,
        ranking_feature="trailing_return",
        ranking_window=window,
        ascending=ascending,
    )


# ------------------------------------------------------------ synchronization


def test_different_asset_timestamps_exclude_the_laggard() -> None:
    b = CrossSectionalSnapshotBuilder(min_members=2)
    snap = b.build(
        {
            "A": daily("A", [100.0, 110.0, 121.0]),
            "B": daily("B", [100.0, 105.0, 111.0]),
            "C": daily("C", [100.0, 100.0]),  # one day behind
        },
        req(2),
    )
    assert snap.feature_time == DAY0 + 2 * DAY
    assert set(snap.eligible_assets) == {"A", "B"}
    assert "C" not in snap.eligible_assets
    assert snap.exclusion_reasons["C"] == "unsynchronized"
    assert snap.is_tradeable


def test_stale_asset_is_excluded() -> None:
    b = CrossSectionalSnapshotBuilder(min_members=2)
    stale = daily("C", [100.0, 100.0])
    stale[-1] = OHLCV(
        symbol="C", timestamp=DAY0 + DAY, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0
    )  # one day behind
    snap = b.build(
        {
            "A": daily("A", [100.0, 110.0, 121.0]),
            "B": daily("B", [100.0, 105.0, 111.0]),
            "C": stale,
        },
        req(2),
    )
    assert "C" not in snap.eligible_assets
    assert snap.exclusion_reasons["C"] in {"stale", "unsynchronized"}


def test_future_asset_bar_is_never_read() -> None:
    b = CrossSectionalSnapshotBuilder()
    series = {
        "A": daily("A", [100.0, 110.0, 121.0, 999.0]),
        "B": daily("B", [100.0, 100.0, 100.0, 1.0]),
    }
    snap = b.build(series, req(2))
    assert snap.feature_time <= snap.decision_time
    # values reflect bars up to day 2 only; the day-3 bar cannot move them
    assert snap.values["A"] == pytest.approx(121.0 / 110.0 - 1.0)


def test_duplicate_asset_bar_excludes_symbol() -> None:
    b = CrossSectionalSnapshotBuilder()
    dup = daily("D", [100.0, 100.0, 100.0])
    dup_with_dup = [
        *dup,
        OHLCV(
            symbol="D",
            timestamp=dup[-1].timestamp,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=1.0,
        ),
    ]
    snap = b.build({"A": daily("A", [1.0, 2.0, 3.0]), "D": dup_with_dup}, req(2))
    assert "D" not in snap.eligible_assets
    assert snap.exclusion_reasons["D"] == "duplicate_bar"


def test_missing_history_is_insufficient() -> None:
    b = CrossSectionalSnapshotBuilder()
    # both assets are synchronized at day 2; B lacks the window-4 contiguous history
    snap = b.build(
        {"A": daily("A", [1.0, 2.0, 3.0]), "B": daily("B", [1.0, 2.0, 3.0])},
        req(2, window=4),
    )
    assert "B" not in snap.eligible_assets
    assert snap.exclusion_reasons["B"] == "insufficient_history"


def test_ties_break_deterministically_by_symbol() -> None:
    b = CrossSectionalSnapshotBuilder()
    snap = b.build({"B": daily("B", [100.0, 110.0]), "A": daily("A", [100.0, 110.0])}, req(1))
    assert snap.ranking() == ("A", "B")
    assert snap.ranks == {"A": 1, "B": 2}


def test_asset_joining_and_leaving_the_universe() -> None:
    b = CrossSectionalSnapshotBuilder()
    a, bb = daily("A", [100.0, 101.0, 102.0, 103.0]), daily("B", [100.0, 101.0, 102.0, 103.0])
    c = daily("C", [50.0, 51.0, 52.0])  # C present days 0-2 only
    snap_join = b.build({"A": a, "B": bb, "C": c}, req(2))
    assert "C" in snap_join.eligible_assets  # synchronized at day 2
    # C leaves: A,B have day 3 but C's last bar is day 2 -> unsynchronized
    snap_leave = b.build({"A": a, "B": bb, "C": c}, req(3))
    assert "C" not in snap_leave.eligible_assets
    assert snap_leave.exclusion_reasons["C"] == "unsynchronized"


def test_insufficient_universe_is_blocked_fail_closed() -> None:
    b = CrossSectionalSnapshotBuilder(min_members=3)
    snap = b.build({"A": daily("A", [1.0, 2.0]), "B": daily("B", [1.0, 2.0])}, req(1))
    assert snap.min_members == 3
    assert snap.ranks == {}
    assert snap.eligible_assets == ()
    assert not snap.is_tradeable
    assert snap.blocked_reason == "insufficient_universe"


# ------------------------------------------------------------------- contract


def test_snapshot_enforces_feature_time_not_after_decision_time() -> None:
    with pytest.raises(CrossSectionalError):
        CrossSectionalSnapshot(
            decision_time=DAY0,
            assets=("A",),
            feature_time=DAY0 + DAY,
            ranking_feature="trailing_return",
            ranking_window=1,
            ranks={},
            eligible_assets=(),
            excluded_assets=(),
            exclusion_reasons={},
            values={},
            min_members=2,
        )


def test_snapshot_requires_permutation_ranks() -> None:
    with pytest.raises(CrossSectionalError):
        CrossSectionalSnapshot(
            decision_time=DAY0 + DAY,
            assets=("A", "B"),
            feature_time=DAY0,
            ranking_feature="trailing_return",
            ranking_window=1,
            ranks={"A": 2, "B": 2},
            eligible_assets=("A", "B"),
            excluded_assets=(),
            exclusion_reasons={},
            values={"A": 1.0, "B": 1.0},
            min_members=2,
        )


def test_deterministic_rankings_across_calls() -> None:
    b = CrossSectionalSnapshotBuilder()
    series = {"A": daily("A", [3.0, 2.0, 1.0]), "B": daily("B", [1.0, 2.0, 3.0])}
    s1 = b.build(series, req(2))
    s2 = b.build({k: list(v) for k, v in series.items()}, req(2))
    assert s1.ranking() == s2.ranking()
    assert s1.ranks == s2.ranks


# ------------------------------------------------------------- strategy PIT


def test_rotation_entries_are_never_at_or_after_the_last_calendar_day() -> None:
    cfg = RotationConfig("trailing_return", 1, False, 1, 30)
    series = {
        "A": daily("A", [100.0, 101.0, 103.0, 102.0, 105.0]),
        "B": daily("B", [100.0, 99.0, 98.0, 99.0, 100.0]),
    }
    res = simulate_xsec_rotation(series, config=cfg, cost_bps_rt=23.559)
    # a fill can never occur on the very first bar (that would be a same-bar decision)
    assert all(t.entry_ts >= DAY0 + DAY for t in res.trades)
    # determinism across two identical calls
    res2 = simulate_xsec_rotation(series, config=cfg, cost_bps_rt=23.559)
    assert [t.as_dict() for t in res.trades] == [t.as_dict() for t in res2.trades]
