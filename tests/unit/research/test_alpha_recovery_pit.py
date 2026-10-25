"""ARP-002 §3/§24 — PIT, determinism and simulator-contract tests.

TEST_TARGET == RUNTIME_TARGET: every strategy comes from
``trading_bot.research.alpha_recovery`` and the simulator is the same
``simulate`` the campaign driver calls.
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
from trading_bot.research.alpha_recovery.experiments import (  # noqa: E402
    Exp001PullbackContinuation,
    Exp002VoidRetest,
    Exp003RelativeStrength,
    Exp005PivotFade,
)
from trading_bot.research.alpha_recovery.series import (  # noqa: E402
    atr_series,
    ema_series,
    sma_series,
)
from trading_bot.research.alpha_recovery.simulate import Setup, simulate  # noqa: E402

START_MS = 1_772_323_200_000
STEP_MS = 300_000


def synth(n: int = 260, *, seed: int = 11, trend: float = 0.0015) -> list[OHLCV]:
    price = 100.0
    bars: list[OHLCV] = []
    for i in range(n):
        wobble = math.sin(i / 7.0) * 0.6 + math.sin(i / 2.3) * 0.15
        price = max(5.0, price * (1.0 + trend) + wobble * 0.05)
        high = price + 0.25
        low = price - 0.25
        bars.append(
            OHLCV(
                symbol="X",
                timestamp=START_MS + i * STEP_MS,
                open=price - 0.05,
                high=high,
                low=low,
                close=price,
                volume=10.0 + (i % 13),
            )
        )
    return bars


def test_sma_and_atr_shapes() -> None:
    sma = sma_series([float(i) for i in range(10)], 3)
    assert sma[:2] == [None, None]
    assert sma[2] == pytest.approx(1.0)
    assert sma[9] == pytest.approx(8.0)
    highs = [2.0, 2.0, 2.0]
    lows = [1.0, 1.0, 1.0]
    closes = [1.5, 1.5, 1.5]
    atr = atr_series(highs, lows, closes, 2)
    assert atr[0] is None and atr[1] is None
    assert atr[2] == pytest.approx(1.0)
    ema = ema_series([1.0, 1.0, 1.0, 1.0], 2)
    assert ema[0] is None
    assert ema[3] == pytest.approx(1.0)


def _paired() -> tuple[list[OHLCV], list[OHLCV]]:
    leader = synth(260, seed=3, trend=0.0012)
    laggard = synth(260, seed=5, trend=0.0009)
    return leader, laggard


def _strategies() -> list[object]:
    leader, _ = _paired()
    return [
        Exp001PullbackContinuation(),
        Exp002VoidRetest(),
        Exp003RelativeStrength(leader),
        Exp005PivotFade(),
    ]


def test_entry_is_pit_invariant_to_future_bars() -> None:
    """A decision at bar i must not change when later bars are handed to prepare."""
    bars = synth(260)
    for strategy in _strategies():
        for i in (120, 200, 250):
            cut = synth(260)[: i + 1]
            # Exp003 needs the leader series; re-create with the matching cut.
            if strategy.__class__.__name__ == "Exp003RelativeStrength":
                leader, _ = _paired()
                s_full = Exp003RelativeStrength(leader)
                s_cut = Exp003RelativeStrength(leader[: i + 1])
            else:
                s_full = strategy.__class__()
                s_cut = strategy.__class__()
            s_full.prepare(bars)
            s_cut.prepare(cut)
            assert s_full.entry(i) == s_cut.entry(i), strategy.__class__.__name__


def test_experiments_run_deterministically() -> None:
    bars = synth(260)
    for strategy in _strategies():
        if strategy.__class__.__name__ == "Exp003RelativeStrength":
            continue
        first = simulate(strategy.__class__(), bars, cost_bps_rt=23.559)
        second = simulate(strategy.__class__(), bars, cost_bps_rt=23.559)
        assert json.dumps([t.as_dict() for t in first.trades], sort_keys=True) == json.dumps(
            [t.as_dict() for t in second.trades], sort_keys=True
        )


class _OneShot:
    """Opens once at bar 1 and never again (deterministic simulator contract test)."""

    warmup = 1

    def __init__(self) -> None:
        self._bars: Sequence[OHLCV] = []
        self._fired = False

    def prepare(self, bars: Sequence[OHLCV]) -> None:
        self._bars = bars

    def entry(self, i: int) -> Setup | None:
        if i == 1 and not self._fired:
            self._fired = True
            return Setup(side="long", stop=self._bars[i].close * 0.95, target=self._bars[i].close * 1.10, rule="t")
        return None

    def exit_reason(self, i: int, pos: object) -> str | None:
        return None


def test_stop_first_on_ambiguity_and_cost_math() -> None:
    bars = [
        OHLCV(symbol="X", timestamp=START_MS, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0),
        OHLCV(symbol="X", timestamp=START_MS + STEP_MS, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0),
        OHLCV(symbol="X", timestamp=START_MS + 2 * STEP_MS, open=100.0, high=111.0, low=94.0, close=105.0, volume=1.0),
    ]
    res = simulate(_OneShot(), bars, cost_bps_rt=20.0, notional=500.0)
    assert len(res.trades) == 1
    trade = res.trades[0]
    assert trade.reason == "stop"  # both levels spanned -> stop taken
    assert trade.gross == pytest.approx(500.0 * (95.0 / 100.0 - 1.0), abs=1e-6)
    assert trade.fees == pytest.approx(500.0 * 20.0 / 10000.0, abs=1e-6)
    assert trade.net == pytest.approx(trade.gross - trade.fees, abs=1e-6)


def test_oos_window_is_a_separate_locked_split() -> None:
    from trading_bot.research.alpha_recovery.campaign import SPLIT_WINDOWS

    assert SPLIT_WINDOWS["OOS_LOCK"] == ("W7_2026-09",)
    assert not set(SPLIT_WINDOWS["OOS_LOCK"]) & set(SPLIT_WINDOWS["DEV"])
    assert not set(SPLIT_WINDOWS["OOS_LOCK"]) & set(SPLIT_WINDOWS["VALIDATION"])
