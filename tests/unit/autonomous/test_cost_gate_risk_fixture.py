"""CONTROLLED DETERMINISTIC FIXTURE — candidate → cost gate → proposal → Risk.

This file is explicitly NOT market evidence. Every bar, snapshot, family and
ledger entry below is written by hand so the pipeline can be exercised
end-to-end deterministically:

    candidate → cost-aware decision → TradeProposal → deterministic Risk
    → TRADE_PAPER / SHADOW_TRADE / NO_TRADE

Nothing here is read from a research artifact, and no number produced here may
be reported as an observation about the market. Its only job is to prove the
WIRING: a candidate that really clears the cost barrier reaches the canonical
risk engine, and the engine's verdict decides.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from trading_bot.autonomous.contracts import (
    AdmissionStatus,
    DecisionMode,
    RiskReview,
    RiskState,
    RiskVerdict,
    VerificationResult,
    VerifierVerdict,
)
from trading_bot.autonomous.decision import DecisionEngine, DecisionRequest
from trading_bot.autonomous.runtime import AssetCycleReport

from .helpers import StaticFamily, make_admitted_ledger, make_ledger, make_runtime
from .test_contracts import _proposal


def _run(runtime: Any, **kwargs: Any) -> Any:
    return asyncio.run(runtime.run(**kwargs))


def _assert_cost_gate_passed(row: AssetCycleReport) -> None:
    """The candidate cleared the gate: gross > 0 and net > 0."""
    assert row.expected_gross_edge_bps is not None and row.expected_gross_edge_bps > 0
    assert row.expected_cost_bps is not None and row.expected_cost_bps > 0
    assert row.expected_net_edge_bps is not None and row.expected_net_edge_bps > 0


def test_fixture_cost_gate_pass_reaches_risk_and_becomes_paper(tmp_path: Any) -> None:
    runtime, _scanner, broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_admitted_ledger(gross_bps=50.0),
        families={"ema_crossover": StaticFamily()},
    )
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]

    # 1) cost-aware decision: gross - cost = net, and net is positive
    _assert_cost_gate_passed(row)
    # 2) a TradeProposal exists and is persisted with its economics
    trace = runtime.trace_store.read()[0]
    assert trace.proposal is not None
    assert trace.proposal["expected_net_edge_bps"] == pytest.approx(
        trace.proposal["expected_gross_edge_bps"] - trace.proposal["expected_cost_bps"]
    )
    # 3) the deterministic risk engine really ran and approved
    assert row.risk_evaluated is True
    assert row.risk_state == RiskState.APPROVED.value
    assert row.risk_rule == "all_limits_pass"
    assert trace.risk["risk_inputs"]["advisory"] is False
    assert trace.risk["binding"] is True
    # 4) and only then was a PAPER order created
    assert row.mode is DecisionMode.TRADE_PAPER
    assert row.order_created is True
    broker_state = broker.extract_state()
    assert broker_state["fills_opened"] >= 1


def test_fixture_cost_gate_pass_but_risk_veto_places_nothing(tmp_path: Any) -> None:
    runtime, _scanner, broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_admitted_ledger(gross_bps=50.0),
        families={"ema_crossover": StaticFamily()},
    )
    runtime._risk.activate_kill_switch("fixture")
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]

    _assert_cost_gate_passed(row)  # the economics were fine
    assert row.risk_evaluated is True
    assert row.risk_state == RiskState.VETOED.value
    assert row.risk_rule == "kill_switch"
    assert row.mode is DecisionMode.NO_TRADE
    assert row.classification == "RISK_VETO"
    assert row.order_created is False
    assert broker.positions == {}
    assert summary.totals()["orders_created"] == 0


def test_fixture_positive_gross_that_does_not_clear_cost_is_shadow(tmp_path: Any) -> None:
    """A positive gross edge alone must NOT become a trade."""
    runtime, _scanner, broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=1.0),  # gross > 0, far below ~20 bps of cost
        families={"ema_crossover": StaticFamily()},
    )
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.expected_gross_edge_bps is not None and row.expected_gross_edge_bps > 0
    assert row.expected_net_edge_bps is not None and row.expected_net_edge_bps <= 0
    assert row.mode is DecisionMode.SHADOW_TRADE
    assert row.classification == "COST_KILLED"
    assert row.order_created is False
    assert broker.positions == {}


def _request(*, advisory: bool, admitted: bool) -> DecisionRequest:
    ledger = make_admitted_ledger(gross_bps=50.0) if admitted else make_ledger(gross_bps=50.0)
    entry = ledger.entry("ema_crossover@5m")
    proposal = _proposal(
        strategy_id="ema_crossover@5m",
        expected_gross_edge_bps=50.0,
        expected_cost_bps=21.0,
        expected_net_edge_bps=29.0,
        admission_status=entry.status,
    )
    return DecisionRequest(
        run_id="run-1",
        decision_id="d-1",
        asset="BTC",
        symbol="BTC/USDT",
        market_time_ms=1_000,
        decision_time_ms=2_000,
        regime="RANGE",
        admission=entry,
        proposal=proposal,
        verification=VerificationResult(decision_id="d-1", verdict=VerifierVerdict.PASS),
        risk=RiskReview(
            verdict=RiskVerdict.PASS,
            reason="risk_approved",
            evaluated=True,
            rule="all_limits_pass",
            advisory=advisory,
        ),
    )


def test_advisory_risk_can_never_sit_on_an_order_authorising_packet() -> None:
    """Fail closed: marking the review advisory must not bypass the gate."""
    with pytest.raises(ValueError, match="advisory risk review"):
        DecisionEngine().decide(_request(advisory=True, admitted=True))
    # The same packet with a BINDING review is legal and produces the order.
    result = DecisionEngine().decide(_request(advisory=False, admitted=True))
    assert result.mode is DecisionMode.TRADE_PAPER
    assert result.order_authorised is True


def test_advisory_risk_is_legal_where_no_order_can_follow() -> None:
    result = DecisionEngine().decide(_request(advisory=True, admitted=False))
    assert result.mode is DecisionMode.SHADOW_TRADE
    assert result.order_authorised is False


def test_evidence_identity_is_timeframe_aware(tmp_path: Any) -> None:
    """30m research evidence must not be reused as if it were 5m evidence."""
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=8.91, timeframe="30m"),  # measured on 30m only
        timeframe="5m",
    )
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.strategies_considered == ()
    assert row.expected_gross_edge_bps is None
    assert row.classification == "NO_ALPHA"


def test_expected_edge_carries_historical_estimate_provenance(tmp_path: Any) -> None:
    """The prior edge is a HISTORICAL_ESTIMATE with source/sample/period/status."""
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=4.0, timeframe="5m", status="COST_KILLED"),
        families={"ema_crossover": StaticFamily()},
    )
    _run(runtime, cycles=1)
    evidence = runtime.trace_store.read()[0].proposal["edge_evidence"]
    assert evidence["evidence_class"] == "HISTORICAL_ESTIMATE"
    assert evidence["source_doc"]
    assert evidence["sample_trades"] > 0
    assert evidence["period"]
    assert evidence["timeframe"] == "5m"
    assert evidence["status"] == "COST_KILLED"


def test_admission_status_comes_from_the_ledger_not_the_proposal(tmp_path: Any) -> None:
    """A proposal cannot promote itself; the ledger wins (recomputed)."""
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0)
    )
    _run(runtime, cycles=1)
    proposal = runtime.trace_store.read()[0].proposal
    assert proposal["admission_status"] == AdmissionStatus.COST_KILLED.value
    assert replace(_proposal(), strategy_id=proposal["strategy_id"]) is not None
