from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from trading_bot.demo.paper_multi_agent import (
    DecisionToCandidateAdapter,
    _proposal_set,
    run_fixture_demo,
)
from trading_bot.multi_agent.decision import DecisionEngine


def _selected_fixture() -> tuple[
    object,
    dict[str, object],
    dict[str, object],
    tuple[object, ...],
    object,
    dict[str, float],
    datetime,
]:
    now = datetime.fromtimestamp(1_786_010_740_000 / 1000, tz=UTC)
    bars = __import__("trading_bot.demo.paper_multi_agent", fromlist=["_bars"])._bars(
        "SOL", timestamp=1_786_010_680_000, shape="down"
    )
    proposals, evidence, assessments, board, reports, prices = _proposal_set(
        asset="SOL",
        bars=bars,
        now=now,
        run_id="adapter-run",
        trace_id="adapter-trace",
        directions=("LONG",),
    )
    package = DecisionEngine(run_id="adapter-run").decide(
        snapshot=board.snapshot(),
        proposals=proposals,
        evidence_registry=evidence,
        reports=reports,
        assessments=assessments,
        now=now,
    )
    return package, proposals, evidence, reports, board, prices, now


def test_verified_selected_adapts_to_existing_candidate_type() -> None:
    package, proposals, evidence, reports, board, prices, now = _selected_fixture()
    adapted = DecisionToCandidateAdapter().adapt(
        package,
        proposals=proposals,
        evidence_registry=evidence,
        reports=reports,
        now=now,
        prices=prices,
        snapshot=board.snapshot(),
    )
    assert adapted is not None
    assert adapted.candidate.asset == "SOL"
    assert adapted.candidate.strategy_id == "momentum"
    assert adapted.verification.verdict.value == "VERIFIED"
    assert not hasattr(adapted.candidate, "notional_usdt")


def test_no_trade_package_never_adapts() -> None:
    result = run_fixture_demo(output_dir=Path("/tmp/demo-paper-adapter-no-trade"))
    no_trade = next(item for item in result.state.decisions if item["outcome"] == "NO_TRADE")
    assert no_trade["verifier"] == "VERIFIED"
    assert no_trade["package"]["selected_candidate_id"] is None


def test_foreign_run_package_fails_closed_at_adapter() -> None:
    package, proposals, evidence, reports, board, prices, now = _selected_fixture()
    foreign_package = package.model_copy(update={"run_id": "foreign-run"})
    adapted = DecisionToCandidateAdapter().adapt(
        foreign_package,
        proposals=proposals,
        evidence_registry=evidence,
        reports=reports,
        now=now,
        prices=prices,
        snapshot=board.snapshot(),
    )
    assert adapted is None


def test_tampered_selected_evidence_fails_closed_at_adapter() -> None:
    package, proposals, evidence, reports, board, prices, now = _selected_fixture()
    selected_id = package.selected_candidate_id
    assert selected_id is not None
    selected = next(item for item in package.candidate_set if item.final_proposal_id == selected_id)
    stripped = selected.model_copy(update={"supporting_evidence_refs": ()})
    tampered = package.model_copy(
        update={
            "candidate_set": (stripped,),
            "selected_candidate_id": selected_id,
            "rejected_alternatives": (),
        }
    )
    adapted = DecisionToCandidateAdapter().adapt(
        tampered,
        proposals=proposals,
        evidence_registry=evidence,
        reports=reports,
        now=now,
        prices=prices,
        snapshot=board.snapshot(),
    )
    assert adapted is None


def test_fixture_risk_rejection_has_zero_additional_broker_side_effects(tmp_path: Path) -> None:
    result = run_fixture_demo(output_dir=tmp_path)
    assert result.state.risk_rejects >= 1
    assert result.state.broker_calls == result.state.paper_trades
    assert result.state.live_calls == 0
