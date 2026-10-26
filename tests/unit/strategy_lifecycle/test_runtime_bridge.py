"""Unit tests for ``strategy_lifecycle.runtime_bridge`` (WP-STRAT-07).

The bridge is the seam that makes the lifecycle plane reachable from the PAPER
runtime. These tests pin the safety invariants that must hold regardless of the
router behind it:

* only ``PAPER_ACTIVE`` maps to the one executable lifecycle state (``ACTIVE``);
* the mapping can only ever restrict — it never invents eligibility;
* the comparison is deterministic and names every refusal.
"""

from __future__ import annotations

import pytest

from trading_bot.strategy_lifecycle.contracts import LifecycleState
from trading_bot.strategy_lifecycle.runtime_bridge import (
    ADMISSION_TO_LIFECYCLE,
    LifecycleRoutingAdapter,
    StrategyRoutingMode,
    coerce_routing_mode,
    lifecycle_state_for_admission,
)


class _Routed:
    def __init__(self, strategy_id: str, verdict: str) -> None:
        self.strategy_id = strategy_id
        self.verdict = verdict


class _Selection:
    def __init__(self, selected: tuple[str, ...], routed: list[_Routed]) -> None:
        self.selected = selected
        self.routed = tuple(routed)


class _StubRouter:
    def __init__(self, selected: tuple[str, ...], routed: list[_Routed]) -> None:
        self._selected = selected
        self._routed = tuple(routed)
        self.calls = 0

    def select_eligible_strategies(self, *_a: object, **_k: object) -> _Selection:
        self.calls += 1
        return _Selection(self._selected, list(self._routed))


class _Ledger:
    def __init__(self, statuses: dict[str, str]) -> None:
        self._statuses = statuses

    def status_for(self, strategy_id: str) -> str:
        return self._statuses.get(strategy_id, "UNKNOWN")


def test_only_paper_active_maps_to_the_executable_state() -> None:
    # The single most important safety invariant: the bridge cannot widen
    # execution. Exactly one admission status yields the one routable state.
    active = [k for k, v in ADMISSION_TO_LIFECYCLE.items() if v == LifecycleState.ACTIVE.value]
    assert active == ["PAPER_ACTIVE"]
    assert lifecycle_state_for_admission("PAPER_ACTIVE") == "ACTIVE"
    assert lifecycle_state_for_admission("PAPER_CANDIDATE") == "SHADOW"
    assert lifecycle_state_for_admission("PAPER_RETIRED") == "RETIRED"


def test_unknown_admission_fails_closed_to_a_non_routing_state() -> None:
    assert lifecycle_state_for_admission("SOMETHING_NEW") == "DISCOVERED"
    assert lifecycle_state_for_admission(None) == "DISCOVERED"
    # DISCOVERED does not route (router returns NOT_APPLICABLE for it)
    assert LifecycleState.DISCOVERED.value not in {"ACTIVE"}


def test_coerce_routing_mode_parses_and_fails_closed() -> None:
    assert coerce_routing_mode("legacy") is StrategyRoutingMode.LEGACY
    assert coerce_routing_mode(StrategyRoutingMode.SHADOW) is StrategyRoutingMode.SHADOW
    with pytest.raises(ValueError):
        coerce_routing_mode("LIVE")  # there is no LIVE mode
    with pytest.raises(ValueError):
        coerce_routing_mode("nonsense")


def test_lifecycle_map_prefers_override_then_ledger() -> None:
    adapter = LifecycleRoutingAdapter(lifecycle_override={"a": "paused"})
    ledger = _Ledger({"a": "PAPER_ACTIVE", "b": "PAPER_CANDIDATE"})
    mapping = adapter.lifecycle_map({"a": {}, "b": {}}, ledger)
    assert mapping == {"a": "PAUSED", "b": "SHADOW"}


def test_compare_records_differences_and_reason_codes() -> None:
    router = _StubRouter(
        selected=("a",),
        routed=[_Routed("a", "SELECTED"), _Routed("b", "PAUSED")],
    )
    adapter = LifecycleRoutingAdapter()
    ledger = _Ledger({"a": "PAPER_ACTIVE", "b": "PAPER_ACTIVE"})
    comparison = adapter.compare(
        router,
        run_id="run-1",
        context=object(),
        regime="TREND_UP",
        strategy_map={"a": {}, "b": {}},
        ledger=ledger,
        legacy_selected=("b",),
        decision_time_ms=1000,
        asset="BTC",
        timeframe="5m",
        mode=StrategyRoutingMode.SHADOW,
    )
    assert comparison.lifecycle_selected == ("a",)
    assert comparison.legacy_selected == ("b",)
    assert comparison.lifecycle_rejected == {"b": "PAUSED"}
    assert set(comparison.differences) == {"LIFECYCLE_ONLY:a", "LEGACY_ONLY:b"}
    assert "b:PAUSED" in comparison.reason_codes
    assert comparison.config_hash.startswith("sha256:")


def test_compare_is_deterministic_and_mode_sensitive() -> None:
    router = _StubRouter(selected=("a",), routed=[_Routed("a", "SELECTED")])
    adapter = LifecycleRoutingAdapter()
    ledger = _Ledger({"a": "PAPER_ACTIVE"})
    kwargs = dict(
        run_id="run-1",
        context=object(),
        regime=None,
        strategy_map={"a": {}},
        ledger=ledger,
        legacy_selected=("a",),
        decision_time_ms=1,
        asset="BTC",
        timeframe="5m",
    )
    c1 = adapter.compare(router, mode=StrategyRoutingMode.SHADOW, **kwargs)
    c2 = adapter.compare(router, mode=StrategyRoutingMode.SHADOW, **kwargs)
    c3 = adapter.compare(router, mode=StrategyRoutingMode.LIFECYCLE, **kwargs)
    assert c1.config_hash == c2.config_hash
    assert c1.config_hash != c3.config_hash
    assert c1.differences == ("AGREE",)
