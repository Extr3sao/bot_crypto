"""Shadow V2 router tests (Track B, ALPHA-DISCOVERY-AND-SHADOW-V2-01)."""

from __future__ import annotations

from typing import Any

import pytest

from trading_bot.shadow.integration import ShadowCaptureHook
from trading_bot.shadow.outcome import ShadowBar, ShadowTrade
from trading_bot.shadow.router import (
    ConditionedShadowMetrics,
    RiskGateRouter,
    ShadowCounters,
)


def _reject_ctx(decision_id: str = "d-1", **over: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "decision_id": decision_id,
        "trace_id": "t-1",
        "run_id": "r-1",
        "asset": "SOL/USDT:USDT",
        "direction": "LONG",
        "strategy_id": "momentum",
        "strategy_version": "1",
        "timeframe": "5m",
        "proposal_ref": "p-1",
        "decision_ref": "dec-1",
        "verifier_ref": "v-1",
        "decision_time": "2026-09-09T10:00:00Z",
        "decision_price": 100.0,
        "entry_reference": 100.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "invalidation": "close below 98",
        "regime_signature": "TRENDING|MEDIUM_VOL",
        "strategy_health_state": "HEALTHY",
        "portfolio_context_ref": "pf-1",
        "correlation_state": "NORMAL",
        "market_data_fingerprint": "md-1",
        "cost_model_sha256": "c-1",
    }
    ctx.update(over)
    return ctx


def _hook(tmp_path) -> ShadowCaptureHook:
    return ShadowCaptureHook(
        captures_path=tmp_path / "shadow" / "captures.jsonl",
        outcomes_path=tmp_path / "shadow" / "outcomes.jsonl",
    )


def _trade(**over: Any) -> ShadowTrade:
    fields: dict[str, Any] = {
        "shadow_candidate_id": "sc-1",
        "decision_id": "d-1",
        "asset": "SOL/USDT:USDT",
        "direction": "LONG",
        "strategy_id": "momentum",
        "timeframe": "5m",
        "risk_rejection_reason": "CONSECUTIVE_LOSS_COOLDOWN",
        "regime_signature": "TRENDING|MEDIUM_VOL",
        "strategy_health_state": "HEALTHY",
        "entry_price": 100.0,
        "exit_price": 103.0,
        "exit_time": "2026-09-09T11:00:00Z",
        "outcome": __import__(
            "trading_bot.shadow.outcome", fromlist=["ShadowTradeOutcome"]
        ).ShadowTradeOutcome.TAKE_PROFIT_HIT,
        "gross_pnl": 3.0,
        "net_pnl": 2.8,
        "r_multiple": 1.4,
        "entry_fee_usdt": 0.1,
        "exit_fee_usdt": 0.1,
        "entry_slippage_usdt": 0.0,
        "exit_slippage_usdt": 0.0,
        "bars_evaluated": 12,
    }
    fields.update(over)
    return ShadowTrade(**fields)


# --------------------------------------------------------------------------
# Router flow
# --------------------------------------------------------------------------


def test_accept_routes_without_capture(tmp_path) -> None:
    router = RiskGateRouter(_hook(tmp_path))
    d = router.decide(verdict="ACCEPT", reason=None, ctx=_reject_ctx())
    assert d.verdict == "ACCEPT"
    assert d.capture_id is None
    assert len(router._hook.captures) == 0


def test_reject_persists_immutable_capture(tmp_path) -> None:
    hook = _hook(tmp_path)
    router = RiskGateRouter(hook)
    d = router.decide(
        verdict="REJECT",
        reason="CONSECUTIVE_LOSS_COOLDOWN",
        ctx=_reject_ctx(),
    )
    assert d.verdict == "REJECT"
    assert d.capture_id is not None
    assert len(hook.captures) == 1
    assert hook.captures.captures[0].risk_rejection_reason == "CONSECUTIVE_LOSS_COOLDOWN"


def test_reject_requires_reason(tmp_path) -> None:
    router = RiskGateRouter(_hook(tmp_path))
    with pytest.raises(ValueError):
        router.decide(verdict="REJECT", reason=None, ctx=_reject_ctx())
    with pytest.raises(ValueError):
        router.decide(verdict="MAYBE", reason="x", ctx=_reject_ctx())


def test_router_end_to_end_capture_then_pit_resolution(tmp_path) -> None:
    hook = _hook(tmp_path)
    router = RiskGateRouter(hook)
    d = router.decide(
        verdict="REJECT",
        reason="MAX_POSITIONS",
        ctx=_reject_ctx(decision_id="d-e2e"),
    )
    assert d.capture_id is not None
    bars = [
        ShadowBar(time="2026-09-09T10:05:00Z", high=101.0, low=99.5, close=100.5),
        ShadowBar(time="2026-09-09T10:10:00Z", high=104.5, low=100.0, close=104.2),
    ]
    trades = hook.resolve_pending({"d-e2e": bars}, quantity_by_decision={"d-e2e": 2.0})
    assert len(trades) == 1
    t = trades[0]
    assert t.decision_id == "d-e2e"
    assert t.exit_price is not None and t.net_pnl != 0.0
    assert len(hook.outcomes.trades) == 1


# --------------------------------------------------------------------------
# Conditioned metrics (B2/D1)
# --------------------------------------------------------------------------


def test_conditioned_metrics_by_reason_and_regime() -> None:
    t1 = _trade()
    t2 = _trade(
        shadow_candidate_id="sc-2",
        decision_id="d-2",
        regime_signature="RANGE|LOW_VOL",
        net_pnl=-1.0,
        r_multiple=-0.5,
    )
    m = ConditionedShadowMetrics([t1, t2])
    by_rr = m.by_condition("risk_rejection_reason")
    assert by_rr[("CONSECUTIVE_LOSS_COOLDOWN",)]["candidates"] == 2
    assert by_rr[("CONSECUTIVE_LOSS_COOLDOWN",)]["wins"] == 1
    assert by_rr[("CONSECUTIVE_LOSS_COOLDOWN",)]["losses"] == 1
    assert abs(by_rr[("CONSECUTIVE_LOSS_COOLDOWN",)]["expectancy_net"] - 0.9) < 1e-9

    by_regime = m.by_condition("regime_signature")
    assert by_regime[("TRENDING|MEDIUM_VOL",)]["wins"] == 1
    assert by_regime[("RANGE|LOW_VOL",)]["losses"] == 1


def test_conditioned_metrics_rejects_unknown_dimension() -> None:
    m = ConditionedShadowMetrics([_trade()])
    with pytest.raises(ValueError):
        m.by_condition("not_a_field")


def test_conditioned_metrics_handles_still_open() -> None:
    st = __import__(
        "trading_bot.shadow.outcome", fromlist=["ShadowTradeOutcome"]
    ).ShadowTradeOutcome
    t_open = _trade(
        shadow_candidate_id="sc-3",
        decision_id="d-3",
        outcome=st.STILL_OPEN,
        exit_price=None,
        exit_time=None,
        r_multiple=None,
        net_pnl=0.0,
        gross_pnl=0.0,
    )
    m = ConditionedShadowMetrics([t_open])
    row = m.by_condition("strategy_health_state")[("HEALTHY",)]
    assert row["resolved"] == 0
    assert row["r_multiples_mean"] is None


# --------------------------------------------------------------------------
# Counters (read-only projection)
# --------------------------------------------------------------------------


def test_shadow_counters_projection(tmp_path) -> None:
    hook = _hook(tmp_path)
    router = RiskGateRouter(hook)
    router.decide(verdict="REJECT", reason="MAX_POSITIONS", ctx=_reject_ctx(decision_id="d-a"))
    router.decide(verdict="REJECT", reason="MAX_POSITIONS", ctx=_reject_ctx(decision_id="d-b"))
    counters = ShadowCounters(hook).snapshot()
    assert counters["captures_total"] == 2
    assert counters["resolved_total"] == 0
    assert counters["pending_total"] == 2
    assert counters["captures_by_reason"] == {"MAX_POSITIONS": 2}
    assert counters["paper_contamination"] == 0


# --------------------------------------------------------------------------
# Isolation surface
# --------------------------------------------------------------------------


def test_router_module_imports_only_shadow_surface() -> None:
    """AST check: the router may not import PaperBroker/portfolio/risk."""
    import ast
    from pathlib import Path

    src = Path("src/trading_bot/shadow/router.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    for module in imported:
        assert "paper_broker" not in module
        assert "portfolio" not in module
        assert not module.startswith("trading_bot.risk")
