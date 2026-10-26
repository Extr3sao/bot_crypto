"""ARP-004 §4/§30 — adversarial PIT and daily-simulator contract tests.

TEST_TARGET == RUNTIME_TARGET: the modules under test are exactly the ones the
driver ``scripts/alpha_recovery_v1_3.py`` imports.
"""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.research.alpha_recovery.daily import (  # noqa: E402
    BARS_PER_DAY_5M,
    MS_PER_5M,
    MS_PER_DAY,
    DailySetup,
    Exp007Config,
    Exp007DailyPivotFade,
    Exp010Config,
    Exp010VolSpikeMR,
    daily_bars_from_5m,
    day_key,
    realized_daily_vol,
    simulate_daily,
)

SYM = "X"


# ------------------------------------------------------------------ builders


def five_min_day(day_index: int, closes: Sequence[float], *, pad: float = 0.5) -> list[OHLCV]:
    """A contiguous run of 5-minute bars for one UTC day (288 closes = complete)."""
    base = day_index * MS_PER_DAY
    return [
        OHLCV(
            symbol=SYM,
            timestamp=base + k * MS_PER_5M,
            open=c,
            high=c + pad,
            low=c - pad,
            close=c,
            volume=1.0,
        )
        for k, c in enumerate(closes)
    ]


def daily_bars(specs: Sequence[tuple[float, float, float, float]]) -> list[OHLCV]:
    """Daily bars directly from (open, high, low, close) tuples, one per UTC day."""
    return [
        OHLCV(symbol=SYM, timestamp=i * MS_PER_DAY, open=o, high=h, low=lo, close=c, volume=1.0)
        for i, (o, h, lo, c) in enumerate(specs)
    ]


# --------------------------------------------------------------- §5 derivation


def test_daily_bars_use_complete_days_only_and_aggregate_correctly() -> None:
    d0 = five_min_day(0, [100.0] * BARS_PER_DAY_5M)
    d1 = five_min_day(1, [100.0 + k for k in range(BARS_PER_DAY_5M)])
    partial = five_min_day(2, [1.0] * 100)  # an incomplete (current) day
    daily = daily_bars_from_5m(d0 + d1 + partial)
    assert len(daily) == 2  # the partial day is never turned into a daily bar
    assert daily[0].timestamp == 0
    assert daily[0].open == pytest.approx(100.0)
    assert daily[0].close == pytest.approx(100.0)
    assert daily[0].high == pytest.approx(100.5)
    assert daily[0].low == pytest.approx(99.5)
    assert daily[1].timestamp == MS_PER_DAY
    assert daily[1].close == pytest.approx(100.0 + (BARS_PER_DAY_5M - 1))
    # no daily bar may straddle two calendar days
    for bar in daily:
        assert bar.timestamp % MS_PER_DAY == 0


def test_a_day_with_a_gap_is_not_treated_as_complete() -> None:
    day = five_min_day(0, [100.0] * BARS_PER_DAY_5M)
    del day[10]  # remove one 5m bar -> no longer a contiguous complete day
    assert daily_bars_from_5m(day) == []


def test_realized_daily_vol_matches_definition() -> None:
    closes = [100.0 * (1.001**k) for k in range(BARS_PER_DAY_5M)]
    vol = realized_daily_vol(five_min_day(0, closes))
    # 287 consecutive returns, each exactly 0.001
    assert vol[0] == pytest.approx(0.001 * math.sqrt(BARS_PER_DAY_5M - 1), rel=1e-9)


# ------------------------------------------------------------- §4 PIT: EXP-007


def test_exp007_entry_is_pit_invariant_to_future_days() -> None:
    """A pivot decision on day D must not change when later days are appended."""
    specs = [(100.0, 102.0, 98.0, 101.0) for _ in range(40)]
    # give some days a wide range so both R1 and S1 can be touched
    specs[25] = (101.0, 115.0, 90.0, 100.0)
    full = daily_bars(specs)
    for i in (18, 25, 32, 38):
        s_full = Exp007DailyPivotFade()
        s_cut = Exp007DailyPivotFade()
        s_full.prepare(full)
        s_cut.prepare(full[: i + 1])
        assert s_full.entry(i) == s_cut.entry(i), i


def test_exp007_uses_only_the_prior_day_pivot() -> None:
    cfg = Exp007Config(atr_period=2)
    specs = [(100.0, 101.0, 99.0, 100.0) for _ in range(20)]
    specs[4] = (100.0, 110.0, 95.0, 105.0)  # prior day H=110 L=95 C=105 -> PP=103.33
    # day 5 opens below S1 so it touches S1 -> long fade
    specs[5] = (95.0, 96.0, 90.0, 92.0)
    bars = daily_bars(specs)
    strat = Exp007DailyPivotFade(cfg)
    strat.prepare(bars)
    pp = (110.0 + 95.0 + 105.0) / 3.0
    s1 = 2.0 * pp - 110.0
    setup = strat.entry(5)
    assert setup is not None
    assert setup.side == "long"
    assert setup.target == pytest.approx(pp)
    assert setup.stop is not None and setup.stop < s1
    # touching BOTH levels in one day is skipped (frozen tie-break)
    specs[5] = (95.0, 120.0, 85.0, 92.0)
    strat.prepare(daily_bars(specs))
    assert strat.entry(5) is None


# ------------------------------------------------------------- §4 PIT: EXP-010


def _exp010_series() -> tuple[list[OHLCV], dict[int, float]]:
    specs = [(100.0, 100.5, 99.5, 100.0) for _ in range(6)]
    specs[3] = (100.0, 100.5, 99.5, 100.0)
    specs[4] = (100.0, 79.5, 78.5, 79.0)  # a large down day
    specs[5] = (79.0, 79.5, 78.5, 79.2)
    vols = {0: 0.010, 1: 0.011, 2: 0.009, 3: 0.010, 4: 0.100, 5: 0.011}
    return daily_bars(specs), vols


def _exp010_cfg() -> Exp010Config:
    return Exp010Config(atr_period=2, vol_lookback_days=3, vol_z_entry=1.0, ret_atr=0.5)


def test_exp010_signal_and_pit_invariance() -> None:
    bars, vols = _exp010_series()
    strat = Exp010VolSpikeMR(vols, _exp010_cfg())
    strat.prepare(bars)
    setup = strat.entry(4)
    assert setup is not None and setup.side == "long"  # fade the spike down day

    # appending a later, wildly different day must not change the day-4 decision
    future = [
        OHLCV(
            symbol=SYM,
            timestamp=6 * MS_PER_DAY,
            open=79.0,
            high=200.0,
            low=1.0,
            close=2.0,
            volume=1.0,
        ),
        OHLCV(
            symbol=SYM, timestamp=7 * MS_PER_DAY, open=2.0, high=2.0, low=1.0, close=1.0, volume=1.0
        ),
    ]
    s_cut = Exp010VolSpikeMR(vols, _exp010_cfg())
    s_cut.prepare(bars[:5])
    assert s_cut.entry(4) == setup
    s_alt = Exp010VolSpikeMR({**vols, 6: 99.0, 7: 0.4}, _exp010_cfg())
    s_alt.prepare(bars + future)
    assert s_alt.entry(4) == setup


def test_exp010_zscore_window_requires_day_contiguity() -> None:
    specs = [(100.0, 100.5, 99.5, 100.0) for _ in range(10)]
    specs[6] = (100.0, 79.5, 78.5, 79.0)
    amps = [0.010, 0.011, 0.009, 0.012, 0.010, 0.011, 0.500, 0.011, 0.010, 0.010]
    control = daily_bars(specs)
    cvols = {day_key(b.timestamp): a for b, a in zip(control, amps, strict=True)}
    s_ok = Exp010VolSpikeMR(cvols, _exp010_cfg())
    s_ok.prepare(control)
    assert s_ok.entry(6) is not None  # contiguous lookback -> signal fires

    # leave a one-day hole before index 6 -> the trailing window is not contiguous
    holed = list(control)
    for k in range(5, 10):
        b = holed[k]
        holed[k] = OHLCV(
            symbol=SYM,
            timestamp=(k + 2) * MS_PER_DAY,
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            volume=b.volume,
        )
    hvols = {day_key(b.timestamp): a for b, a in zip(holed, amps, strict=True)}
    s_hole = Exp010VolSpikeMR(hvols, _exp010_cfg())
    s_hole.prepare(holed)
    assert s_hole.entry(6) is None


# ------------------------------------------------------- §30 simulator contract


class _OneShot:
    """Signals once at a chosen bar, then never again."""

    warmup = 1

    def __init__(self, at: int = 0, max_hold: int = 3) -> None:
        self.at = at
        self.max_hold = max_hold
        self._bars: Sequence[OHLCV] = ()
        self._fired = False

    def prepare(self, bars: Sequence[OHLCV]) -> None:
        self._bars = bars

    def entry(self, i: int) -> DailySetup | None:
        if i == self.at and not self._fired:
            self._fired = True
            return DailySetup(
                side="long",
                rule="t",
                max_hold_days=self.max_hold,
                stop=self._bars[i].close * 0.90,
                target=self._bars[i].close * 1.10,
            )
        return None


def test_daily_entry_fills_at_next_open_not_signal_close() -> None:
    bars = daily_bars(
        [(100.0, 101.0, 99.0, 100.0), (105.0, 108.0, 104.0, 106.0), (106.0, 107.0, 100.0, 101.0)]
    )
    res = simulate_daily(_OneShot(0, max_hold=1), bars, cost_bps_rt=0.0)
    assert len(res.trades) == 1
    assert res.trades[0].entry == pytest.approx(105.0)  # open of bar 1, not close of bar 0


def test_daily_stop_first_on_intrabar_ambiguity() -> None:
    bars = daily_bars(
        [(100.0, 101.0, 99.0, 100.0), (105.0, 130.0, 80.0, 120.0), (120.0, 121.0, 119.0, 120.0)]
    )
    res = simulate_daily(_OneShot(0), bars, cost_bps_rt=20.0, notional=500.0)
    t = res.trades[0]
    assert t.reason == "stop"  # both stop and target inside bar 1 -> stop wins
    assert t.fees == pytest.approx(500.0 * 20.0 / 10000.0, abs=1e-6)
    assert t.net == pytest.approx(t.gross - t.fees, abs=1e-6)


def test_daily_max_hold_forces_exit() -> None:
    # a flat market that never hits stop/target -> force close on the hold limit
    bars = daily_bars([(100.0, 101.0, 99.0, 100.0)] + [(100.0, 101.0, 99.0, 100.0)] * 6)
    res = simulate_daily(_OneShot(0), bars, cost_bps_rt=0.0)
    t = res.trades[0]
    assert t.reason == "window_expiry"
    assert t.duration_min == pytest.approx(2 * 1440.0)  # entry day + one more


def test_daily_simulation_is_deterministic() -> None:
    specs = [
        (100.0, 101.0, 99.0, 100.0),
        (100.0, 102.0, 98.0, 101.0),
        (101.0, 103.0, 99.0, 100.0),
        (100.0, 101.0, 95.0, 96.0),
        (96.0, 98.0, 94.0, 97.0),
    ]
    bars = daily_bars(specs)
    a = simulate_daily(_OneShot(0), bars, cost_bps_rt=23.559)
    b = simulate_daily(_OneShot(0), bars, cost_bps_rt=23.559)
    assert json.dumps([t.as_dict() for t in a.trades], sort_keys=True) == json.dumps(
        [t.as_dict() for t in b.trades], sort_keys=True
    )
