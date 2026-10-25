"""ARP-006 §14-§18 — broader-universe cross-sectional rotation tests."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.diversified.data import DailyBar  # noqa: E402
from trading_bot.research.diversified.xsec import (  # noqa: E402
    XsecUniverseConfig,
    simulate_universe_xsec,
    xsec_universe_configs,
)

DAY = 86_400_000
DAY0 = 1_546_300_800_000
COST = 23.559016994374947
FP = "test-fp"


def series(symbol: str, closes: list[float]) -> list[DailyBar]:
    return [
        DailyBar(symbol=symbol, timestamp=DAY0 + i * DAY, open=c, high=c, low=c, close=c,
                 volume=1.0, quote_volume=1e7)
        for i, c in enumerate(closes)
    ]


def test_rotation_goes_long_the_factor_leader() -> None:
    a = series("A", [100.0 * (1.01 ** i) for i in range(80)])  # steeper
    b = series("B", [100.0 * (1.001 ** i) for i in range(80)])
    cfg = XsecUniverseConfig("trailing_return", 2, False, 1, 5, min_members=2)
    trades, _ = simulate_universe_xsec({"A": a, "B": b}, {"A": DAY0, "B": DAY0}, FP,
                                       config=cfg, cost_bps_rt=COST)
    assert trades
    assert trades[0].symbol == "A"
    assert trades[0].side == "long"


def test_min_members_blocks_a_too_small_universe() -> None:
    a = series("A", [100.0 * (1.01 ** i) for i in range(80)])
    b = series("B", [100.0 * (1.001 ** i) for i in range(80)])
    cfg = XsecUniverseConfig("trailing_return", 2, False, 1, 5, min_members=3)
    trades, _ = simulate_universe_xsec({"A": a, "B": b}, {"A": DAY0, "B": DAY0}, FP,
                                       config=cfg, cost_bps_rt=COST)
    assert trades == []


def test_fill_is_at_next_open_and_pit_safe() -> None:
    a = series("A", [100.0 + i for i in range(80)])
    b = series("B", [100.0 + 0.5 * i for i in range(80)])
    cfg = XsecUniverseConfig("trailing_return", 2, False, 1, 5, min_members=2)
    trades, _ = simulate_universe_xsec({"A": a, "B": b}, {"A": DAY0, "B": DAY0}, FP,
                                       config=cfg, cost_bps_rt=COST)
    t = trades[0]
    assert t.entry_ts > DAY0  # never the decision bar itself
    assert t.entry_ts % DAY == 0
    assert t.exit_ts >= t.entry_ts


def test_determinism() -> None:
    a = series("A", [100.0 * (1.01 ** i) for i in range(80)])
    b = series("B", [100.0 * (1.001 ** i) for i in range(80)])
    cfg = xsec_universe_configs()["EXP-ARP-016"]
    cfg = XsecUniverseConfig(cfg.ranking_feature, 5, cfg.ascending, 3, 10, min_members=2)
    r1, _ = simulate_universe_xsec({"A": a, "B": b}, {"A": DAY0, "B": DAY0}, FP, config=cfg, cost_bps_rt=COST)
    r2, _ = simulate_universe_xsec({"A": a, "B": b}, {"A": DAY0, "B": DAY0}, FP, config=cfg, cost_bps_rt=COST)
    assert [t.as_dict() for t in r1] == [t.as_dict() for t in r2]


def test_subset_restricts_the_corpus() -> None:
    a = series("A", [100.0 * (1.01 ** i) for i in range(80)])
    b = series("B", [100.0 * (1.001 ** i) for i in range(80)])
    cfg = XsecUniverseConfig("trailing_return", 2, False, 1, 5, min_members=2)
    both, _ = simulate_universe_xsec({"A": a, "B": b}, {"A": DAY0, "B": DAY0}, FP,
                                     config=cfg, cost_bps_rt=COST)
    only_b, _ = simulate_universe_xsec({"A": a, "B": b}, {"A": DAY0, "B": DAY0}, FP,
                                       config=cfg, cost_bps_rt=COST, subset=["B"])
    assert both and both[0].symbol == "A"
    # a single-asset subset cannot satisfy min_members=2 -> no trades
    assert only_b == []
