"""Freshness must follow the timeframe, not a 15-minute constant (DEF-AUTO-3, §38).

The defect: a fixed 15-minute staleness rule rejected every 30m candidate as
``stale_context``, so a system that advertised 30m ran at 5-15m in practice.
These tests pin the rule per timeframe and pin the router's use of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from trading_bot.research.router_gates import (
    DEFAULT_FRESHNESS_GRACE_BARS,
    STALE_THRESHOLD_MS,
    TIMEFRAME_MS,
    RouterGates,
    stale_threshold_for_timeframe,
    timeframe_ms,
)
from trading_bot.research.strategy_router import (
    PAPER_EXECUTABLE_STATUS_NAMES,
    StrategyRouter,
)

MINUTE_MS = 60_000


@dataclass
class _Context:
    asset: str = "BTC"
    timestamp: int = 10_000_000
    window_end_ts: int = 10_000_000
    data_quality: dict[str, int] = field(default_factory=lambda: {"bars_in_window": 120})
    market_regime: str = "TREND_UP"


def test_the_budget_grows_with_the_timeframe() -> None:
    budgets = {name: stale_threshold_for_timeframe(name) for name in TIMEFRAME_MS}
    assert budgets["1m"] < budgets["5m"] < budgets["15m"] < budgets["30m"] < budgets["1h"]
    assert budgets["30m"] == int(30 * MINUTE_MS * DEFAULT_FRESHNESS_GRACE_BARS)


def test_a_thirty_minute_context_is_fresh_past_fifteen_minutes() -> None:
    """The exact case the old constant got wrong."""
    gates = RouterGates(timeframe="30m")
    assert gates.stale_after_ms() > STALE_THRESHOLD_MS
    context = _Context(
        timestamp=10_000_000, window_end_ts=10_000_000 - 20 * MINUTE_MS
    )
    router = StrategyRouter(gates=gates)
    decision = router.route(context, "TREND_UP", {"s": {"enabled": True, "status": "PAPER_ACTIVE"}})
    assert not decision.is_no_trade
    assert decision.no_trade_reason != "stale_context"


def test_the_same_lag_is_stale_on_a_one_minute_timeframe() -> None:
    context = _Context(timestamp=10_000_000, window_end_ts=10_000_000 - 20 * MINUTE_MS)
    router = StrategyRouter(gates=RouterGates(timeframe="1m"))
    decision = router.route(context, None, {"s": {"enabled": True, "status": "PAPER_ACTIVE"}})
    assert decision.is_no_trade
    assert decision.no_trade_reason == "stale_context"


def test_explicit_milliseconds_win_over_the_timeframe() -> None:
    gates = RouterGates(freshness_ms=1, timeframe=None)
    assert gates.stale_after_ms() == 1
    assert gates.freshness_source == "explicit_ms"


def test_an_undeclared_timeframe_falls_back_to_the_documented_legacy_value() -> None:
    gates = RouterGates()
    assert gates.stale_after_ms() == STALE_THRESHOLD_MS
    assert gates.freshness_source == "legacy_default"


def test_declaring_both_budgets_is_refused() -> None:
    with pytest.raises(ValueError, match="not both"):
        RouterGates(timeframe="5m", freshness_ms=1_000)


def test_an_unknown_timeframe_is_refused_rather_than_assumed() -> None:
    with pytest.raises(ValueError, match="unknown timeframe"):
        RouterGates(timeframe="7m")
    with pytest.raises(ValueError, match="unknown timeframe"):
        stale_threshold_for_timeframe("7m")


def test_a_nonsense_grace_and_budget_are_refused() -> None:
    with pytest.raises(ValueError, match="grace_bars"):
        stale_threshold_for_timeframe("5m", grace_bars=0)
    with pytest.raises(ValueError, match="freshness_ms"):
        RouterGates(freshness_ms=0)


def test_timeframe_ms_is_case_and_space_insensitive() -> None:
    assert timeframe_ms(" 5M ") == 5 * MINUTE_MS
    assert timeframe_ms("nope") is None


def test_the_router_confirmation_gate_speaks_the_lifecycle_vocabulary() -> None:
    """DEF-AUTO-4 — `CONFIRMED` is no longer a status the gate can be satisfied by."""
    assert frozenset({"PAPER_CANDIDATE", "PAPER_ACTIVE"}) == PAPER_EXECUTABLE_STATUS_NAMES
    router = StrategyRouter(gates=RouterGates(timeframe="5m"))
    for status, expected_selected in (
        ("PAPER_ACTIVE", True),
        ("PAPER_CANDIDATE", True),
        ("CONFIRMED", False),
        ("RESEARCH_ONLY", False),
        ("NO_GROSS_EDGE", False),
        ("REJECTED", False),
    ):
        decision = router.route(
            _Context(), "TREND_UP", {"s": {"enabled": True, "status": status, "family": "f"}}
        )
        assert (not decision.is_no_trade) is expected_selected, status
