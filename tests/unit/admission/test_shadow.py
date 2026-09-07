"""ADMISSION-FOUNDATION-01 shadow-plane tests (§10-§15, ADM-11..15)."""

from __future__ import annotations

import pytest

from trading_bot.admission import (
    DuplicateShadowTradeError,
    ShadowIsolationError,
    ShadowPlane,
    ShadowTrade,
    assert_no_execution_authority,
)

COSTS = {"taker_fee_rate": 0.0005, "slippage_rate": 0.0002}


class FakeBroker:
    """An object WITH execution authority — must be rejected by the plane."""

    def place_order(self, *a: object, **k: object) -> None:  # pragma: no cover
        raise AssertionError("never called")


class FakeRiskManager:
    def evaluate_risk(self, *a: object, **k: object) -> None:  # pragma: no cover
        raise AssertionError("never called")


BARS = [
    ("2026-09-07T17:05:00+00:00", 101.0, 99.0, 100.5),
    ("2026-09-07T17:10:00+00:00", 103.0, 99.5, 102.0),
    ("2026-09-07T17:15:00+00:00", 104.0, 100.0, 103.5),
]


def test_shadow_rejects_broker_and_risk_objects() -> None:
    with pytest.raises(ShadowIsolationError):
        assert_no_execution_authority(FakeBroker())
    with pytest.raises(ShadowIsolationError):
        assert_no_execution_authority(FakeRiskManager())


def test_shadow_plane_rejects_authority_objects_at_entry() -> None:
    plane = ShadowPlane()
    with pytest.raises(ShadowIsolationError):
        plane.evaluate_rejected_decision(
            source_decision_id="d1",
            asset="SOL/USDT:USDT",
            direction="LONG",
            strategy="momentum",
            entry_time="2026-09-07T17:00:00+00:00",
            entry_price=100.0,
            stop_price=98.0,
            take_profit_price=104.0,
            bars_after_entry=FakeBroker(),  # type: ignore[arg-type]
            cost_assumptions=COSTS,
            risk_rejection_reason="MAX_POSITIONS",
            market_data_fingerprint="fp",
        )


def test_counterfactual_trade_lifecycle_and_labels() -> None:
    plane = ShadowPlane()
    t = plane.evaluate_rejected_decision(
        source_decision_id="decision:xyz",
        asset="SOL/USDT:USDT",
        direction="LONG",
        strategy="momentum",
        entry_time="2026-09-07T17:00:00+00:00",
        entry_price=100.0,
        stop_price=98.0,
        take_profit_price=104.0,
        bars_after_entry=BARS,
        cost_assumptions=COSTS,
        risk_rejection_reason="MAX_POSITIONS",
        market_data_fingerprint="fp-001",
    )
    assert "SHADOW_ONLY" in t.labels
    assert "COUNTERFACTUAL" in t.labels
    assert "EXCLUDED_FROM_POC01_PNL" in t.labels
    assert "EXCLUDED_FROM_POC01_FREQUENCY" in t.labels
    assert t.risk_rejection_reason == "MAX_POSITIONS"
    assert t.exit_price == 104.0  # TP hit on bar 3
    assert t.outcome == "win"
    assert t.net_pnl < t.gross_pnl  # costs subtracted from gross


def test_sl_first_on_ambiguous_bar() -> None:
    from trading_bot.admission.shadow import simulate_sl_tp_exit

    # both SL and TP touchable in one bar -> conservative SL wins
    _ts, px = simulate_sl_tp_exit(
        direction="LONG", entry_price=100.0, stop_price=98.0,
        take_profit_price=104.0,
        bars_after_entry=[("t1", 104.0, 97.0, 100.0)],
    )
    assert px == 98.0


def test_duplicate_prevention() -> None:
    plane = ShadowPlane()
    kwargs = dict(
        asset="SOL/USDT:USDT", direction="LONG", strategy="momentum",
        entry_time="2026-09-07T17:00:00+00:00", entry_price=100.0,
        stop_price=98.0, take_profit_price=104.0,
        bars_after_entry=BARS, cost_assumptions=COSTS,
        risk_rejection_reason="MAX_POSITIONS", market_data_fingerprint="fp",
    )
    plane.evaluate_rejected_decision(source_decision_id="decision:dup", **kwargs)
    with pytest.raises(DuplicateShadowTradeError):
        plane.evaluate_rejected_decision(source_decision_id="decision:dup", **kwargs)


def test_shadow_accounting_isolated() -> None:
    plane = ShadowPlane()
    ledger = plane.ledger
    for i, reason in enumerate(["MAX_POSITIONS", "MAX_POSITIONS", "CONSECUTIVE_LOSS_COOLDOWN"]):
        plane.evaluate_rejected_decision(
            source_decision_id=f"decision:{i}",
            asset="SOL/USDT:USDT",
            direction="LONG",
            strategy="momentum",
            entry_time="2026-09-07T17:00:00+00:00",
            entry_price=100.0,
            stop_price=98.0,
            take_profit_price=104.0,
            bars_after_entry=BARS,
            cost_assumptions=COSTS,
            risk_rejection_reason=reason,
            market_data_fingerprint="fp",
        )
    a = ledger.accounting()
    assert a["shadow_trades"] == 3
    assert a["shadow_wins"] == 3
    assert a["shadow_net_pnl"] == a["by_risk_rejection_reason"]["MAX_POSITIONS"]["net_pnl"] + \
        a["by_risk_rejection_reason"]["CONSECUTIVE_LOSS_COOLDOWN"]["net_pnl"]
    assert "excluded from POC01 PnL" in a["note"]
    # isolated namespace: nothing here can reach a campaign object
    assert not hasattr(ledger, "paper_broker")
    assert not hasattr(ledger, "risk_manager")


def test_shadow_ledger_persists_without_authority_surface(tmp_path) -> None:
    plane = ShadowPlane()
    plane.evaluate_rejected_decision(
        source_decision_id="decision:save",
        asset="SOL/USDT:USDT", direction="LONG", strategy="momentum",
        entry_time="2026-09-07T17:00:00+00:00", entry_price=100.0,
        stop_price=98.0, take_profit_price=104.0,
        bars_after_entry=BARS, cost_assumptions=COSTS,
        risk_rejection_reason="CONSECUTIVE_LOSS_COOLDOWN",
        market_data_fingerprint="fp",
    )
    p = tmp_path / "shadow.json"
    plane.ledger.save(str(p))
    import json

    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["accounting"]["shadow_trades"] == 1
    assert payload["trades"][0]["labels"][0] == "SHADOW_ONLY"


def test_shadow_trade_immutable() -> None:
    t = ShadowTrade(
        shadow_trade_id="s1", source_decision_id="d1", asset="SOL", direction="LONG",
        strategy="momentum", hypothetical_entry_time="t0", hypothetical_entry_price=100.0,
        sl_tp_policy_ref="ref", cost_assumptions={}, exit_time="t1", exit_price=101.0,
        outcome="win", gross_pnl=1.0, net_pnl=0.9, risk_rejection_reason="MAX_POSITIONS",
        market_data_fingerprint="fp",
    )
    with pytest.raises(AttributeError):  # frozen dataclass raises on mutation
        t.net_pnl = 99.0  # type: ignore[misc]
