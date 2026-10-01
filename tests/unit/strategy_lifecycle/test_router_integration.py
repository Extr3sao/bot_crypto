"""Router integration tests: select_eligible_strategies verdicts (§13/§14)."""

from __future__ import annotations

from types import SimpleNamespace

from trading_bot.research.router_gates import RouterGates
from trading_bot.research.strategy_router import StrategyRouter


def _ctx(asset="BTC", timestamp=1000, window_end=900, bars=120, regime="TREND_UP"):
    return SimpleNamespace(
        asset=asset,
        timestamp=timestamp,
        window_end_ts=window_end,
        data_quality={"bars_in_window": bars},
        market_regime=regime,
    )


def _map(*ids):
    return {
        sid: {"family": "momentum", "regimes": ["TREND_UP", "TREND_DOWN"], "direction": "BOTH", "enabled": True}
        for sid in ids
    }


def _router():
    return StrategyRouter(gates=RouterGates(require_confirmed=False, timeframe="5m"))


def test_multiple_strategies_can_be_eligible_at_once() -> None:
    router = _router()
    selection = router.select_eligible_strategies(
        _ctx(), "TREND_UP", _map("a", "b", "c"), lifecycle={"a": "ACTIVE", "b": "ACTIVE", "c": "ACTIVE"}
    )
    assert set(selection.selected) == {"a", "b", "c"}


def test_paused_strategy_is_not_selected() -> None:
    router = _router()
    selection = router.select_eligible_strategies(
        _ctx(), "TREND_UP", _map("a", "b"), lifecycle={"a": "ACTIVE", "b": "PAUSED"}
    )
    assert selection.selected == ("a",)
    assert "PAUSED" in selection.by_verdict()


def test_degraded_strategy_is_not_selected() -> None:
    router = _router()
    selection = router.select_eligible_strategies(
        _ctx(), "TREND_UP", _map("a"), lifecycle={"a": "DEGRADED"}
    )
    assert selection.selected == ()
    assert "DEGRADED" in selection.by_verdict()


def test_regime_mismatch_verdict() -> None:
    router = _router()
    strategy_map = {"a": {"family": "mean_reversion", "regimes": ["RANGE"], "direction": "BOTH", "enabled": True}}
    selection = router.select_eligible_strategies(
        _ctx(regime="TREND_UP"), "TREND_UP", strategy_map, lifecycle={"a": "ACTIVE"}
    )
    assert selection.selected == ()
    assert "REGIME_MISMATCH" in selection.by_verdict()


def test_insufficient_evidence_verdict() -> None:
    router = _router()
    selection = router.select_eligible_strategies(
        _ctx(),
        "TREND_UP",
        _map("a"),
        lifecycle={"a": "ACTIVE"},
        performance={"a": -5.0},
        min_expectancy_bps=0.0,
    )
    assert selection.selected == ()
    assert "INSUFFICIENT_EVIDENCE" in selection.by_verdict()


def test_risk_and_portfolio_conflicts_take_precedence() -> None:
    router = _router()
    selection = router.select_eligible_strategies(
        _ctx(),
        "TREND_UP",
        _map("a", "b"),
        lifecycle={"a": "ACTIVE", "b": "ACTIVE"},
        risk_blocked={"a"},
        portfolio_rejected={"b"},
    )
    assert selection.selected == ()
    assert set(selection.by_verdict()) >= {"RISK_CONFLICT", "PORTFOLIO_CONFLICT"}


def test_legacy_status_path_still_works() -> None:
    router = StrategyRouter(gates=RouterGates(require_confirmed=True, timeframe="5m"))
    strategy_map = {
        "a": {"family": "momentum", "regimes": ["TREND_UP"], "direction": "BOTH", "enabled": True, "status": "PAPER_ACTIVE"},
        "b": {"family": "momentum", "regimes": ["TREND_UP"], "direction": "BOTH", "enabled": True, "status": "RESEARCH_REQUIRED"},
    }
    selection = router.select_eligible_strategies(_ctx(), "TREND_UP", strategy_map)
    assert selection.selected == ("a",)
    assert "NOT_APPLICABLE" in selection.by_verdict()


def test_selection_trace_is_complete() -> None:
    router = _router()
    selection = router.select_eligible_strategies(
        _ctx(), "TREND_UP", _map("a"), lifecycle={"a": "ACTIVE"}
    )
    assert any("context_fresh" in t for t in selection.trace)
    assert any("a: SELECTED" in t for t in selection.trace)
