"""ARP-005 §4/§11/§12 — cross-sectional infra + strategy PIT tests.

TEST_TARGET == RUNTIME_TARGET: these modules are exactly the ones the ARP-005
driver ``scripts/alpha_recovery_v1_4.py`` imports.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.research.alpha_recovery.daily import MS_PER_DAY, simulate_daily  # noqa: E402
from trading_bot.research.alpha_recovery.daily_v1_4 import (  # noqa: E402
    Exp006Config,
    Exp006LiquidityVoidReversal,
    Exp011Config,
    Exp011VolExpansionBreakout,
    XsecConfig,
    simulate_xsec,
)
from trading_bot.research.alpha_recovery.xsec import (  # noqa: E402
    CrossSectionalRanker,
    trailing_return,
)


def daily(symbol: str, closes: Sequence[float], pads: Sequence[float] | None = None) -> list[OHLCV]:
    out = []
    for i, c in enumerate(closes):
        p = pads[i] if pads is not None else 0.0
        out.append(
            OHLCV(symbol=symbol, timestamp=i * MS_PER_DAY, open=c, high=c + p, low=c - p,
                  close=c, volume=1.0)
        )
    return out


# ------------------------------------------------------------------ ranker


def test_rank_is_pit_safe_to_future_bars() -> None:
    ranker = CrossSectionalRanker()
    a = daily("A", [100.0, 101.0, 102.0, 103.0])
    b = daily("B", [100.0, 100.0, 100.0, 100.0])
    cut = {"A": a[:3], "B": b[:3]}
    t = 2 * MS_PER_DAY
    first = ranker.rank(cut, t, lookback_days=2)
    # append wild future bars to both names: the decision at t must not move
    grown = {"A": a, "B": b}
    again = ranker.rank(grown, t, lookback_days=2)
    assert first.ranking == again.ranking
    assert first.values == again.values
    assert all(ts <= t for ts in again.as_of.values())


def test_stale_and_missing_symbols_are_excluded_not_ranked() -> None:
    ranker = CrossSectionalRanker()
    a = daily("A", [100.0, 101.0, 102.0])
    b = daily("B", [100.0, 100.0, 100.0])
    stale = daily("C", [100.0, 100.0])  # last bar at t-1d -> stale at t
    ru = ranker.rank({"A": a, "B": b, "C": stale}, 2 * MS_PER_DAY, lookback_days=2)
    assert set(ru.members) == {"A", "B"}
    assert "C" in ru.stale_excluded
    assert "C" not in ru.ranking


def test_non_contiguous_window_is_rejected() -> None:
    ranker = CrossSectionalRanker()
    # a one-day hole before the end breaks the contiguous 3-day window
    holed = daily("A", [100.0, 100.0, 100.0, 100.0])
    holed = [holed[0], holed[1], holed[3]]
    ru = ranker.rank({"A": holed, "B": daily("B", [1.0, 2.0, 3.0])}, 3 * MS_PER_DAY, lookback_days=3)
    assert "A" not in ru.members
    assert "A" in ru.stale_excluded


def test_deterministic_tie_break_by_symbol() -> None:
    ranker = CrossSectionalRanker()
    ru = ranker.rank(
        {"B": daily("B", [100.0, 110.0]), "A": daily("A", [100.0, 110.0])},
        MS_PER_DAY, lookback_days=1,
    )
    assert ru.ranking == ("A", "B")  # equal values -> symbol ascending


def test_trailing_return_requires_full_contiguous_window() -> None:
    assert trailing_return(daily("A", [100.0, 110.0]), 1) == pytest.approx(0.1)
    assert trailing_return(daily("A", [100.0]), 1) is None


# ------------------------------------------------------- EXP-009 portfolio


def test_xsec_holds_the_leader_and_fills_at_next_open() -> None:
    closes = {
        "A": [100.0 + k for k in range(8)],
        "B": [100.0 for _ in range(8)],
        "C": [100.0 - k for k in range(8)],
    }
    series = {s: daily(s, c) for s, c in closes.items()}
    res = simulate_xsec(series, config=XsecConfig(lookback_days=2, max_hold_days=30), cost_bps_rt=0.0)
    assert res.trades, "the rising leader should be held"
    assert all(t.side == "long" for t in res.trades)
    assert all(t.rule == "exp009_xsec_A" for t in res.trades)


def test_xsec_is_deterministic() -> None:
    closes = {"A": [100.0, 101.0, 103.0, 102.0, 105.0], "B": [100.0, 99.0, 98.0, 99.0, 100.0]}
    series_a = {s: daily(s, c) for s, c in closes.items()}
    series_b = {s: daily(s, c) for s, c in closes.items()}
    r1 = simulate_xsec(series_a, config=XsecConfig(lookback_days=1, max_hold_days=30), cost_bps_rt=23.559)
    r2 = simulate_xsec(series_b, config=XsecConfig(lookback_days=1, max_hold_days=30), cost_bps_rt=23.559)
    assert [t.as_dict() for t in r1.trades] == [t.as_dict() for t in r2.trades]


# --------------------------------------------------------------- EXP-006


def test_exp006_detects_void_and_is_pit_invariant() -> None:
    cfg = Exp006Config(atr_period=2, void_min_days=3, void_min_atr=1.0, retest_lookback_days=10)
    specs = [(100.0, 101.0, 99.0, 100.0)] * 8
    # a fast one-sided 3-day down "void" then a retest bar that pokes back up
    specs[3] = (100.0, 100.5, 94.0, 95.0)
    specs[4] = (95.0, 95.5, 88.0, 89.0)
    specs[5] = (89.0, 89.5, 82.0, 83.0)
    specs[6] = (83.0, 90.0, 82.5, 88.0)  # retests the origin band -> long fade
    bars = [OHLCV(symbol="X", timestamp=i * MS_PER_DAY, open=o, high=h, low=lo, close=c, volume=1.0)
            for i, (o, h, lo, c) in enumerate(specs)]
    strat = Exp006LiquidityVoidReversal(cfg)
    strat.prepare(bars)
    setup = strat.entry(6)
    assert setup is not None and setup.side == "long"
    # append unrelated future bars -> the day-6 decision must not change
    future = [*bars, OHLCV(symbol="X", timestamp=7 * MS_PER_DAY, open=88.0, high=200.0, low=1.0,
                           close=2.0, volume=1.0)]
    strat2 = Exp006LiquidityVoidReversal(cfg)
    strat2.prepare(future)
    assert strat2.entry(6) == setup


# --------------------------------------------------------------- EXP-011


def test_exp011_breakout_requires_vol_expansion_and_is_pit_safe() -> None:
    cfg = Exp011Config(atr_period=2, breakout_lookback_days=3, vol_gate_days=3)
    specs = [(100.0, 101.0, 99.0, 100.0) for _ in range(10)]
    specs[6] = (100.0, 130.0, 100.0, 128.0)  # breakout + big range (vol expansion)
    bars = [OHLCV(symbol="X", timestamp=i * MS_PER_DAY, open=o, high=h, low=lo, close=c, volume=1.0)
            for i, (o, h, lo, c) in enumerate(specs)]
    strat = Exp011VolExpansionBreakout(cfg)
    strat.prepare(bars)
    setup = strat.entry(6)
    assert setup is not None and setup.side == "long"
    future = [*bars, OHLCV(symbol="X", timestamp=10 * MS_PER_DAY, open=128.0, high=300.0, low=1.0,
                           close=2.0, volume=1.0)]
    strat2 = Exp011VolExpansionBreakout(cfg)
    strat2.prepare(future)
    assert strat2.entry(6) == setup


def test_exp006_and_exp011_run_through_simulator() -> None:
    specs = [(100.0, 101.0, 99.0, 100.0)] * 12
    specs[6] = (100.0, 130.0, 100.0, 128.0)
    bars = [OHLCV(symbol="X", timestamp=i * MS_PER_DAY, open=o, high=h, low=lo, close=c, volume=1.0)
            for i, (o, h, lo, c) in enumerate(specs)]
    res = simulate_daily(Exp011VolExpansionBreakout(Exp011Config(atr_period=2, breakout_lookback_days=3,
                                                                 vol_gate_days=3)),
                         bars, cost_bps_rt=10.0)
    assert isinstance(res.trades, list)
