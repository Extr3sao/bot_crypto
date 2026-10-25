"""Risk must be OBSERVABLE for every decision that carries a proposal (§12).

The rule under test: the deterministic ``RiskManager`` is consulted for
SHADOW and for rejected (NO_TRADE) candidates too, through the SAME
authoritative component the PAPER path uses — and its verdict is recorded with
``risk_evaluated`` / ``risk_rule`` / ``risk_inputs`` so nobody can claim a
review happened when it did not.

A verdict nobody produced is ``NOT_EVALUATED``: it is NEVER reported as
``APPROVED``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from trading_bot.autonomous.contracts import (
    DecisionMode,
    NoTradeKind,
    RiskReview,
    RiskState,
    RiskVerdict,
)
from trading_bot.autonomous.decision import no_trade_kind_for

from .helpers import (
    TS0,
    BoomReader,
    FakeSnapshot,
    SilentFamily,
    make_admitted_ledger,
    make_ledger,
    make_runtime,
)


def _run(runtime: Any, **kwargs: Any) -> Any:
    return asyncio.run(runtime.run(**kwargs))


# -- contract level ---------------------------------------------------------


def test_a_pass_nobody_produced_is_not_evaluated_never_approved() -> None:
    review = RiskReview(verdict=RiskVerdict.PASS)
    assert review.evaluated is False
    assert review.state is RiskState.NOT_EVALUATED
    assert review.state is not RiskState.APPROVED
    assert review.to_dict()["risk_result"] == "NOT_EVALUATED"


def test_an_evaluated_review_must_name_the_rule_it_applied() -> None:
    with pytest.raises(ValueError, match="must name the rule"):
        RiskReview(verdict=RiskVerdict.PASS, evaluated=True)
    with pytest.raises(ValueError, match="cannot be NOT_APPLICABLE"):
        RiskReview(verdict=RiskVerdict.NOT_APPLICABLE, evaluated=True, rule="x")


def test_a_veto_must_state_its_reason() -> None:
    with pytest.raises(ValueError, match="must state its reason"):
        RiskReview(verdict=RiskVerdict.VETO)


def test_state_is_derived_from_verdict_and_evaluation() -> None:
    assert (
        RiskReview(verdict=RiskVerdict.PASS, evaluated=True, rule="r").state
        is RiskState.APPROVED
    )
    assert (
        RiskReview(verdict=RiskVerdict.VETO, reason="why", evaluated=True, rule="r").state
        is RiskState.VETOED
    )
    assert RiskReview(verdict=RiskVerdict.NOT_APPLICABLE).state is RiskState.NOT_APPLICABLE


# -- runtime level ----------------------------------------------------------


def test_shadow_decision_is_risk_reviewed_advisory(tmp_path: Path) -> None:
    """A SHADOW candidate still gets a real, recorded risk verdict."""
    runtime, _scanner, broker = make_runtime(run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0))
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.SHADOW_TRADE
    assert row.risk_evaluated is True
    assert row.risk_state == RiskState.APPROVED.value
    assert row.risk_rule == "all_limits_pass"
    assert broker.positions == {}  # advisory: nothing was executed

    trace = runtime.trace_store.read()[0]
    risk = trace.risk
    assert risk["risk_evaluated"] is True
    assert risk["risk_result"] == "APPROVED"
    assert risk["risk_rule"] == "all_limits_pass"
    assert risk["advisory"] is True
    assert risk["binding"] is False
    assert risk["risk_inputs"]["advisory"] is True
    assert risk["risk_inputs"]["kill_switch_enabled"] is True
    assert risk["risk_inputs"]["notional_usdt"] > 0
    assert trace.order_created is False
    assert totals_count(summary, "risk_APPROVED") == 1


def totals_count(summary: Any, key: str) -> int:
    return int(summary.totals()[key])


def test_advisory_veto_does_not_block_a_shadow_decision(tmp_path: Path) -> None:
    """The advisory verdict is informative: SHADOW places no order anyway."""
    runtime, _scanner, broker = make_runtime(run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0))
    runtime._risk.activate_kill_switch("test")
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.risk_state == RiskState.VETOED.value
    assert row.risk_rule == "kill_switch"
    assert row.risk_evaluated is True
    assert row.mode is DecisionMode.SHADOW_TRADE  # not downgraded: no order either way
    assert row.order_created is False
    assert broker.positions == {}
    assert totals_count(summary, "risk_VETOED") == 1


def test_no_proposal_is_not_applicable_and_not_evaluated(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=4.0),
        families={"ema_crossover": SilentFamily("ema_crossover")},
    )
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.risk_state == RiskState.NOT_APPLICABLE.value
    assert row.risk_evaluated is False
    assert totals_count(summary, "risk_NOT_APPLICABLE") == 1
    assert totals_count(summary, "risk_APPROVED") == 0


def test_rejected_candidate_keeps_its_advisory_risk_verdict(tmp_path: Path) -> None:
    """A NO_TRADE_STRATEGIC decision can still show what risk WOULD have said."""
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_ledger(gross_bps=-4.56)
    )
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.mode is DecisionMode.NO_TRADE
    assert row.no_trade_kind == NoTradeKind.NO_TRADE_STRATEGIC.value
    # Risk passed: the blocker was the edge, not risk. Both are observable.
    assert row.risk_state == RiskState.APPROVED.value
    assert row.risk_evaluated is True


# -- NO_TRADE classification ------------------------------------------------


def test_no_trade_classification_matrix() -> None:
    assert no_trade_kind_for("NO_GROSS_EDGE") is NoTradeKind.NO_TRADE_STRATEGIC
    assert no_trade_kind_for("COST_KILLED") is NoTradeKind.NO_TRADE_STRATEGIC
    assert no_trade_kind_for("NOT_ADMITTED") is NoTradeKind.NO_TRADE_STRATEGIC
    assert no_trade_kind_for("NO_ALPHA") is NoTradeKind.NO_TRADE_STRATEGIC
    assert no_trade_kind_for("RISK_VETO") is NoTradeKind.NO_TRADE_RISK
    assert no_trade_kind_for("AGENT_VETO") is NoTradeKind.NO_TRADE_CONFLICT
    assert no_trade_kind_for("VERIFIER_FAIL") is NoTradeKind.NO_TRADE_CONFLICT
    assert no_trade_kind_for("NO_MARKET_DATA") is NoTradeKind.NO_TRADE_DATA
    assert no_trade_kind_for("CONTEXT_ERROR") is NoTradeKind.NO_TRADE_DATA
    with pytest.raises(ValueError):
        no_trade_kind_for("PAPER_ADMITTED")


def test_runtime_classifies_risk_veto_as_no_trade_risk(tmp_path: Path) -> None:
    runtime, _scanner, broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=50.0)
    )
    runtime._risk.activate_kill_switch("test")
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.classification == "RISK_VETO"
    assert row.no_trade_kind == NoTradeKind.NO_TRADE_RISK.value
    assert row.risk_state == RiskState.VETOED.value
    assert broker.positions == {}


def test_runtime_classifies_missing_snapshot_as_no_trade_data(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=4.0),
        assets=("BTC", "ETH"),
        snapshots=[FakeSnapshot(symbol="BTC/USDT", timestamp=TS0)],
    )
    summary = _run(runtime, cycles=1)
    rows = {r.asset: r for r in summary.cycle_reports[0].assets}
    assert rows["ETH"].no_trade_kind == NoTradeKind.NO_TRADE_DATA.value
    assert rows["ETH"].failure_kind is None


def test_a_provider_outage_is_a_runtime_failure_not_a_no_trade(tmp_path: Path) -> None:
    """An incident must never be filed as a trading decision (§4)."""
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0), reader=BoomReader()
    )
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.failure_kind == "PROVIDER_FAILURE"
    assert row.no_trade_kind is None
    assert row.risk_evaluated is False
    totals = summary.totals()
    assert totals["runtime_failures"] == 1
    assert totals["no_trades"] == 0
    assert totals["no_trade_NO_TRADE_STRATEGIC"] == 0
    # Every asset-cycle evaluation is exactly one of the four honest buckets.
    assert (
        totals["paper_trades"]
        + totals["shadow_trades"]
        + totals["no_trades"]
        + totals["runtime_failures"]
        == totals["asset_cycle_evaluations"]
    )


def test_admitted_and_unadmitted_paths_share_one_risk_engine(tmp_path: Path) -> None:
    """The runtime must not build a second, shadow-only risk authority."""
    runtime, _scanner, _broker = make_runtime(run_dir=tmp_path)
    calls: list[str] = []
    original = runtime._risk.check_signal

    def spy(signal: Any) -> Any:
        calls.append(signal.symbol)
        return original(signal)

    runtime._risk.check_signal = spy  # type: ignore[method-assign]
    _run(runtime, cycles=1)
    assert calls, "the canonical RiskManager was never consulted"
    trace = runtime.trace_store.read()[0]
    assert trace.risk["source"] == "RiskManager.check_signal"


def test_risk_inputs_are_reproducible_from_the_trace(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0))
    _run(runtime, cycles=1)
    inputs = runtime.trace_store.read()[0].risk["risk_inputs"]
    for key in (
        "decision_id",
        "symbol",
        "strategy_id",
        "side",
        "entry_reference",
        "horizon_minutes",
        "advisory",
        "kill_switch_enabled",
        "equity",
        "open_positions",
        "trades_today",
    ):
        assert key in inputs, key
