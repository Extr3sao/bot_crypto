"""ARP-006 §10-§13 — EXP-ARP-006 / EXP-ARP-008 daily strategy tests (PIT, next-open)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.research.diversified.daily import (  # noqa: E402
    Exp006LiquidityReversal,
    Exp008Config,
    simulate_exp008,
    tag_trades,
    to_ohlcv,
)
from trading_bot.research.diversified.data import DailyBar  # noqa: E402

DAY = 86_400_000
DAY0 = 1_546_300_800_000
COST = 23.559016994374947


def flat_bar(symbol: str, i: int, close: float) -> DailyBar:
    return DailyBar(symbol=symbol, timestamp=DAY0 + i * DAY, open=close, high=close + 1,
                    low=close - 1, close=close, volume=1.0, quote_volume=1e7)


def bar(symbol: str, i: int, o: float, h: float, low: float, c: float) -> DailyBar:
    return DailyBar(symbol=symbol, timestamp=DAY0 + i * DAY, open=o, high=h, low=low,
                    close=c, volume=1.0, quote_volume=1e7)


def void_then_retest(symbol: str = "BTCUSDT") -> list[DailyBar]:
    out = [flat_bar(symbol, i, 100.0) for i in range(20)]
    out.append(bar(symbol, 20, 100.0, 100.0, 93.0, 94.0))
    out.append(bar(symbol, 21, 94.0, 94.0, 87.0, 88.0))
    out.append(bar(symbol, 22, 88.0, 88.0, 81.0, 82.0))
    out.append(bar(symbol, 23, 83.0, 85.0, 80.0, 84.0))  # retest: high >= band_low (82)
    out.append(bar(symbol, 24, 86.0, 90.0, 84.0, 89.0))
    out.append(bar(symbol, 25, 88.0, 88.0, 60.0, 62.0))  # stop-out so the trade closes
    return out


def first_signal(strat: Exp006LiquidityReversal, bars: list[DailyBar]) -> int:
    strat.prepare(to_ohlcv(bars))
    for i in range(len(bars)):
        if strat.entry(i) is not None:
            return i
    raise AssertionError("no signal produced")


def test_exp006_detects_void_and_signals_on_retest() -> None:
    bars = void_then_retest()
    strat = Exp006LiquidityReversal()
    idx = first_signal(strat, bars)
    setup = strat.entry(idx)
    assert setup is not None
    assert setup.side == "long"  # fade the down-void, never a short
    assert 21 <= idx <= 25  # within the retest window after the void


def test_exp006_fills_at_next_open_and_is_pit_safe() -> None:
    from trading_bot.research.alpha_recovery.daily import simulate_daily

    bars = void_then_retest()
    idx = first_signal(Exp006LiquidityReversal(), bars)
    result = simulate_daily(Exp006LiquidityReversal(), to_ohlcv(bars), cost_bps_rt=COST)
    assert result.trades, "expected a fade trade"
    first = result.trades[0]
    assert first.entry_ts == bars[idx + 1].timestamp  # signal on bar idx -> fill open idx+1
    assert first.entry_ts > bars[idx].timestamp


def test_exp008_enters_and_exits_at_next_open() -> None:
    closes = [10, 10, 10, 11, 12, 13, 9, 8, 7, 7, 7, 7]
    bars = {f"S{i}": [flat_bar(f"S{i}", j, c) for j, c in enumerate(closes)] for i in range(1)}
    sym = "S0"
    bars[sym] = [
        DailyBar(symbol=sym, timestamp=DAY0 + j * DAY, open=c, high=c + 1, low=c - 1,
                 close=c, volume=1.0, quote_volume=1e7)
        for j, c in enumerate(closes)
    ]
    out = simulate_exp008(bars, cost_bps_rt=COST, config=Exp008Config(lookback_days=3, max_hold_days=100))
    trades = out[sym]
    assert trades, "expected a trend trade"
    t = trades[0]
    assert t.entry_ts == DAY0 + 4 * DAY   # long signal at bar 3 -> fill open bar 4
    assert t.exit_ts == DAY0 + 7 * DAY    # flip at bar 6 -> exit open bar 7


def test_exp008_is_deterministic() -> None:
    closes = [10, 11, 12, 11, 13, 12, 14, 15, 14, 16, 15, 17]
    bars = {"S": [flat_bar("S", j, c) for j, c in enumerate(closes)]}
    a = simulate_exp008(bars, cost_bps_rt=COST, config=Exp008Config(lookback_days=2, max_hold_days=5))
    b = simulate_exp008(bars, cost_bps_rt=COST, config=Exp008Config(lookback_days=2, max_hold_days=5))
    assert a["S"] == b["S"]


def test_tag_trades_binds_symbols() -> None:
    from trading_bot.research.alpha_recovery.simulate import Trade

    trade = Trade(side="long", entry_ts=1, exit_ts=2, duration_min=1.0, entry=1.0, exit=2.0,
                  reason="x", mfe_pct=1.0, mae_pct=0.0, notional=500.0, gross=500.0,
                  fees=1.0, net=499.0, rule="r")
    tagged = tag_trades({"BTCUSDT": [trade]})
    assert tagged[0].symbol == "BTCUSDT"
    assert tagged[0].net == 499.0
    assert tagged[0].as_dict()["symbol"] == "BTCUSDT"


def test_to_ohlcv_preserves_timestamps() -> None:
    bars = void_then_retest()
    o = to_ohlcv(bars)
    assert [b.timestamp for b in o] == [b.timestamp for b in bars]
    assert isinstance(o[0], OHLCV)
