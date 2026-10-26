"""Fail-closed hardening suite — GATE STRAT-HARDEN-002.

Covers the three lifecycle defects the independent verifier raised as
P2-disconnected / P0-on-wire:

* DEF-VERIFY-001 — ``register()`` accepted an arbitrary initial state.
* DEF-VERIFY-002 — the promotion gate ignored the health verdict.
* DEF-VERIFY-003 — the router was permissive when lifecycle evidence was
  missing (absence of evidence selected a strategy).

The mandatory principle: UNKNOWN / INVALID / MISSING STATE -> DENY / ABSTAIN.
Every test here asserts a REFUSAL; if one ever stops refusing, the lifecycle
plane has a false-success bug.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from trading_bot.research.router_gates import RouterGates
from trading_bot.research.strategy_router import StrategyRouter
from trading_bot.strategy_lifecycle.config import LifecyclePolicy
from trading_bot.strategy_lifecycle.contracts import (
    ContextKey,
    HealthState,
    LifecycleState,
    LifecycleStateError,
    RationaleCode,
)
from trading_bot.strategy_lifecycle.lifecycle import (
    ControllerInputs,
    StrategyLifecycleController,
)
from trading_bot.strategy_lifecycle.registry import DynamicStrategyRegistry

from ._helpers import cell, descriptor, health

POLICY = LifecyclePolicy(minimum_samples=100, minimum_regime_samples=30)


# --------------------------------------------------------------------------- #
# DEF-VERIFY-001 — registration must fail closed
# --------------------------------------------------------------------------- #


def test_registration_refuses_every_authorising_initial_state() -> None:
    reg = DynamicStrategyRegistry()
    for state in (
        LifecycleState.ACTIVE,
        LifecycleState.ELIGIBLE,
        LifecycleState.DEGRADED,
        LifecycleState.THROTTLED,
        LifecycleState.PAUSED,
        LifecycleState.RETIRED,
    ):
        with pytest.raises(LifecycleStateError):
            reg.register(descriptor(f"x-{state.value}", state=state))
    assert reg.strategy_ids() == []


def test_registration_has_no_implicit_default() -> None:
    """A descriptor that claims an unlisted state is refused, never defaulted."""
    reg = DynamicStrategyRegistry()
    # SHADOW is the only 'late' entry state and it is allowed; ACTIVE is not.
    reg.register(descriptor("shadow-ok", state=LifecycleState.SHADOW))
    assert reg.state_of("shadow-ok") is LifecycleState.SHADOW
    with pytest.raises(LifecycleStateError):
        reg.register(descriptor("active-bad", state=LifecycleState.ACTIVE))


def test_reregistration_cannot_change_state() -> None:
    """Duplicate registration with a different state is refused (use apply())."""
    reg = DynamicStrategyRegistry()
    reg.register(descriptor("dup", state=LifecycleState.SHADOW))
    with pytest.raises(ValueError):
        reg.register(descriptor("dup", state=LifecycleState.ELIGIBLE))


# --------------------------------------------------------------------------- #
# DEF-VERIFY-002 — the promotion gate honours the health verdict
# --------------------------------------------------------------------------- #


def _ctrl_inputs(state: LifecycleState, *, health_state: HealthState) -> ControllerInputs:
    return ControllerInputs(
        descriptor=descriptor("mom", state=state),
        context=ContextKey("mom", "BTC", "5m", "TREND_UP"),
        cells={"medium": cell(strategy_id="mom", regime="TREND_UP")},
        health=health(health_state, strategy_id="mom"),
        regime_cell=cell(strategy_id="mom", regime="TREND_UP"),
        now_ms=1_000_000,
        verification_passed=True,
    )


@pytest.mark.parametrize("hs", [HealthState.DEGRADED, HealthState.CRITICAL])
def test_degraded_or_critical_health_blocks_promotion(hs: HealthState) -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(_ctrl_inputs(LifecycleState.SHADOW, health_state=hs))
    assert d.to_state is LifecycleState.SHADOW
    assert d.promotion is None
    assert RationaleCode.HEALTH_DEGRADED.value in d.reason_codes


def test_eligible_degraded_health_cannot_activate() -> None:
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(_ctrl_inputs(LifecycleState.ELIGIBLE, health_state=HealthState.CRITICAL))
    assert d.to_state is LifecycleState.SHADOW
    assert RationaleCode.HEALTH_DEGRADED.value in d.reason_codes


def test_healthy_passing_cell_still_promotes() -> None:
    """The health refusal must not overshoot: HEALTHY + passing cell promotes."""
    c = StrategyLifecycleController(policy=POLICY)
    d = c.evaluate(_ctrl_inputs(LifecycleState.SHADOW, health_state=HealthState.HEALTHY))
    assert d.to_state is LifecycleState.ELIGIBLE
    assert d.promotion is not None


# --------------------------------------------------------------------------- #
# DEF-VERIFY-003 — selection must fail closed
# --------------------------------------------------------------------------- #


def _ctx(asset: str = "BTC", regime: str = "TREND_UP") -> SimpleNamespace:
    return SimpleNamespace(
        asset=asset,
        timestamp=1000,
        window_end_ts=900,
        data_quality={"bars_in_window": 120},
        market_regime=regime,
    )


def _map(*ids: str) -> dict[str, dict[str, object]]:
    return {
        sid: {
            "family": "momentum",
            "regimes": ["TREND_UP", "TREND_DOWN"],
            "direction": "BOTH",
            "enabled": True,
        }
        for sid in ids
    }


def _permissive_router() -> StrategyRouter:
    return StrategyRouter(gates=RouterGates(require_confirmed=False, timeframe="5m"))


def test_unknown_strategy_is_not_selected_when_lifecycle_map_is_provided() -> None:
    router = _permissive_router()
    selection = router.select_eligible_strategies(_ctx(), "TREND_UP", _map("a"), lifecycle={})
    assert selection.selected == ()
    assert "UNKNOWN_STRATEGY" in selection.by_verdict()


def test_partial_lifecycle_map_fails_closed() -> None:
    """A registered SHADOW strategy is refused; the unregistered one is too."""
    router = _permissive_router()
    selection = router.select_eligible_strategies(
        _ctx(), "TREND_UP", _map("shadow", "unregistered"), lifecycle={"shadow": "SHADOW"}
    )
    assert selection.selected == ()
    by = selection.by_verdict()
    assert by.get("UNKNOWN_STRATEGY") == ["unregistered"]
    assert "NOT_APPLICABLE" in by  # the SHADOW one


def test_missing_health_for_supplied_health_plane_fails_closed() -> None:
    router = _permissive_router()
    selection = router.select_eligible_strategies(
        _ctx(),
        "TREND_UP",
        _map("a"),
        lifecycle={"a": "ACTIVE"},
        health={},  # health plane in play, but no verdict for 'a'
    )
    assert selection.selected == ()
    assert "INSUFFICIENT_EVIDENCE" in selection.by_verdict()


def test_invalid_lifecycle_state_value_does_not_route() -> None:
    router = _permissive_router()
    selection = router.select_eligible_strategies(
        _ctx(), "TREND_UP", _map("a"), lifecycle={"a": "TOTALLY_MADE_UP"}
    )
    assert selection.selected == ()
    assert "NOT_APPLICABLE" in selection.by_verdict()


def test_legacy_path_is_unchanged_when_no_lifecycle_map_is_supplied() -> None:
    """With lifecycle=None the explicit legacy contract still governs."""
    router = StrategyRouter(gates=RouterGates(require_confirmed=True, timeframe="5m"))
    strategy_map = {
        "a": {
            "family": "momentum",
            "regimes": ["TREND_UP"],
            "direction": "BOTH",
            "enabled": True,
            "status": "PAPER_ACTIVE",
        }
    }
    selection = router.select_eligible_strategies(_ctx(), "TREND_UP", strategy_map)
    assert selection.selected == ("a",)


def test_disabled_strategy_is_never_selected_even_with_active_lifecycle() -> None:
    router = _permissive_router()
    strategy_map = _map("a")
    strategy_map["a"]["enabled"] = False
    selection = router.select_eligible_strategies(
        _ctx(), "TREND_UP", strategy_map, lifecycle={"a": "ACTIVE"}
    )
    assert selection.selected == ()
    assert "REJECTED" in selection.by_verdict()
