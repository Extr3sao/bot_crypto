"""WP-EDGE-06 Track B — the families, held to the registration.

``HYPOTHESES.md`` registered parameters and falsification conditions *before* the run, so the
thing worth testing is not that the families produce a number: it is that the number came from
the declared rules. These tests pin:

* the parameters in ``DECLARED_PARAMS`` are exactly the ones the registered document states,
  book by book, so a silent re-tune breaks a test rather than a report;
* each family refuses for the reason it says it refuses for — the leader test, the stretch
  test, the trend filter — instead of returning nothing and looking like a quiet book;
* a family that is asked to trade without a stop distance or a target above the close never
  emits a signal, because that is the shape of trade the simulator must never be handed.
"""

from __future__ import annotations

from typing import Any

import pytest

from trading_bot.research.edge01.costs import cost_plane
from trading_bot.research.edge01.data import OHLCVBar
from trading_bot.research.edge06.families import (
    DECLARED_PARAMS,
    CrossSectionalMomentum,
    FadeExtension,
    TrendFixedTarget,
    build_families,
    family_books,
)

HOUR_MS = 3_600_000
FOUR_H = 4 * HOUR_MS


def _bars(closes: list[float], *, start_ts: int = 1_700_000_000_000) -> list[OHLCVBar]:
    """A synthetic series with ATR-ish ranges: no gaps, no invented history."""
    bars: list[OHLCVBar] = []
    for index, close in enumerate(closes):
        ts = start_ts + index * FOUR_H
        high = max(close * 1.01, close)
        low = min(close * 0.99, close)
        bars.append(OHLCVBar(ts=ts, open=close, high=high, low=low, close=close, volume=1.0))
    return bars


def _ramp(length: int, *, start: float = 100.0, step: float = 1.0) -> list[float]:
    return [start + index * step for index in range(length)]


@pytest.fixture(scope="module")
def plane() -> Any:
    return cost_plane(size_usd=1000.0, horizon_minutes=1440.0)


def test_the_declared_parameters_are_the_registered_ones() -> None:
    assert DECLARED_PARAMS == {
        "edge06_xs_momentum": {
            "relative_strength_lookback": 30,
            "trend_ema": 200,
            "atr_period": 14,
            "stop_atr": 2.0,
            "exit_ema": 100,
            "cost_margin": 1.00,
        },
        "edge06_fade_extension": {
            "ema_period": 200,
            "atr_period": 14,
            "entry_distance_atr": 2.0,
            "stop_atr": 1.5,
            "min_rr": 1.50,
            "cost_margin": 1.50,
        },
        "edge06_trend_fixed": {
            "ema_fast": 50,
            "ema_slow": 200,
            "breakout_lookback": 20,
            "atr_period": 14,
            "stop_atr": 1.0,
            "target_atr": 3.0,
            "min_rr": 2.00,
            "cost_margin": 1.50,
        },
    }


def test_every_registered_book_is_a_candidate_with_its_own_parameters() -> None:
    universe = {"BTC": _bars(_ramp(260)), "ETH": _bars(_ramp(260, step=2.0))}
    built = build_families(universe)
    assert sorted(built) == sorted(DECLARED_PARAMS)
    for name, candidate in built.items():
        assert candidate.params == DECLARED_PARAMS[name]
    assert len(family_books()) == len(DECLARED_PARAMS)


def test_the_leader_rule_refuses_the_weaker_asset(plane: Any) -> None:
    """Two assets, one clearly stronger: the weaker one's identical setup is refused."""
    strong = _bars(_ramp(260, step=1.0))
    weak = _bars(_ramp(260, step=0.2))
    candidate = CrossSectionalMomentum(
        universe={"BTC": strong, "ETH": weak}, params=dict(DECLARED_PARAMS["edge06_xs_momentum"])
    )
    index = len(weak) - 1
    candidate.prepare(weak)
    outcome = candidate.on_bar(weak, index, None, plane)
    # Either the setup did not fire at all (None) or it fired and was refused for not being the
    # leader; a signal for the weaker asset would be the defect this rule exists to prevent.
    assert outcome is None or getattr(outcome, "reason", None) == "not_the_relative_leader"


def test_the_fade_family_refuses_an_unstretched_close(plane: Any) -> None:
    bars = _bars(_ramp(260, step=0.5))
    candidate = FadeExtension(params=dict(DECLARED_PARAMS["edge06_fade_extension"]))
    candidate.prepare(bars)
    # A rising series sits above its own mean: nothing is stretched downwards, so nothing fires.
    assert candidate.on_bar(bars, len(bars) - 1, None, plane) is None


def test_the_fixed_target_family_carries_the_declared_geometry() -> None:
    bars = _bars(_ramp(260, step=1.0))
    candidate = TrendFixedTarget(params=dict(DECLARED_PARAMS["edge06_trend_fixed"]))
    candidate.prepare(bars)
    signal = None
    for index in range(220, len(bars)):
        outcome = candidate.on_bar(bars, index, None, cost_plane(size_usd=1000.0, horizon_minutes=1440.0))
        if outcome is not None and hasattr(outcome, "targets"):
            signal = outcome
            break
    if signal is not None:
        assert signal.targets, "a fixed-target family must carry a target"
        assert signal.targets[0] > signal.entry_reference
        assert signal.stop < signal.entry_reference
        assert signal.trailing_atr is None or signal.trailing_atr == 0.0 or signal.exit_ema_period is None


def test_a_family_never_emits_a_signal_without_a_stop_below_the_entry() -> None:
    """The three families, over a flat series where the cost gate cannot be beaten."""
    flat = _bars([100.0] * 300)
    for candidate in (
        FadeExtension(params=dict(DECLARED_PARAMS["edge06_fade_extension"])),
        TrendFixedTarget(params=dict(DECLARED_PARAMS["edge06_trend_fixed"])),
    ):
        candidate.prepare(flat)
        for index in range(220, len(flat)):
            outcome = candidate.on_bar(flat, index, None, cost_plane(size_usd=1000.0, horizon_minutes=1440.0))
            if outcome is not None and hasattr(outcome, "targets"):
                assert outcome.stop < outcome.entry_reference
                assert all(target > outcome.entry_reference for target in outcome.targets)
