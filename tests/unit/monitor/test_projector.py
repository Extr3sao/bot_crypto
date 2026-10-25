"""Projector tests (WP-TDM-01).

Each test writes a run directory with the real ``DecisionTraceStore`` and asserts
what the monitor may and may not claim. The two prohibitions from the RFC that
matter most are pinned here:

* ``DECISION_ACCEPTED`` is never a fill (``test_accepted_without_execution...``);
* a silent strategy is never turned into a rejection
  (``test_no_signal_means_no_decision_event``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.monitor import helpers as h
from trading_bot.autonomous.contracts import DecisionMode
from trading_bot.monitor.contracts import DecisionStatus, EventType
from trading_bot.monitor.projector import (
    ArtifactError,
    discover_runs,
    load_run,
    project_run,
)


def _events(run_dir: Path):
    return project_run(load_run(run_dir)).events


def _by_type(events, event_type: EventType):
    return [e for e in events if e.event_type is event_type]


# ---------------------------------------------------------------------------
# decision taxonomy
# ---------------------------------------------------------------------------


def test_no_trade_becomes_a_rejection_not_a_silence(tmp_path: Path) -> None:
    run_dir = h.write_run(
        tmp_path,
        [
            h.make_trace(
                "dec-btc",
                proposal_payload=h.proposal(gross_bps=-4.56),
                classification="NO_GROSS_EDGE",
            )
        ],
    )
    events = _events(run_dir)
    decisions = _by_type(events, EventType.DECISION_REJECTED)
    assert len(decisions) == 1
    assert decisions[0].decision_status is DecisionStatus.NO_TRADE
    codes = [r.code for r in decisions[0].reason_codes]
    assert "NO_GROSS_EDGE" in codes
    assert decisions[0].risk_gate == "ADVISORY_PASS"


def test_shadow_is_not_a_trade_and_not_a_no_trade(tmp_path: Path) -> None:
    run_dir = h.write_run(
        tmp_path,
        [
            h.make_trace(
                "dec-eth",
                symbol="ETH/USDT",
                asset="ETH",
                mode=DecisionMode.SHADOW_TRADE,
                classification="COST_KILLED",
                reason="gross 1.490bps vs cost 22.833bps",
                no_trade_kind=None,
                proposal_payload=h.proposal(gross_bps=1.49, cost_bps=22.833),
            )
        ],
    )
    events = _events(run_dir)
    assert not _by_type(events, EventType.ORDER_FILLED)
    decision = _by_type(events, EventType.DECISION_REJECTED)[0]
    assert decision.decision_status is DecisionStatus.SHADOW_OBSERVED
    assert "SHADOW" in decision.to_dict()["decision_status_label"]


def test_accepted_without_execution_is_not_a_fill(tmp_path: Path) -> None:
    run_dir = h.write_run(
        tmp_path,
        [
            h.make_trace(
                "dec-paper",
                mode=DecisionMode.TRADE_PAPER,
                classification="PAPER_ADMITTED",
                reason="admitted_candidate_with_positive_net_edge",
                no_trade_kind=None,
                proposal_payload=h.proposal(gross_bps=30.0, cost_bps=10.0),
                risk_payload=h.risk("PASS", advisory=False),
            )
        ],
        executions=[],  # accepted, but nothing was filled
    )
    events = _events(run_dir)
    accepted = _by_type(events, EventType.DECISION_ACCEPTED)
    assert len(accepted) == 1
    assert accepted[0].decision_status is DecisionStatus.ACCEPTED_NOT_EXECUTED
    assert not _by_type(events, EventType.ORDER_FILLED)
    labels = {e.decision_status for e in events}
    assert DecisionStatus.EXECUTED_PAPER not in labels


def test_fill_is_a_separate_event_after_the_acceptance(tmp_path: Path) -> None:
    run_dir = h.write_run(
        tmp_path,
        [
            h.make_trace(
                "dec-filled",
                mode=DecisionMode.TRADE_PAPER,
                classification="PAPER_ADMITTED",
                reason="admitted_candidate_with_positive_net_edge",
                no_trade_kind=None,
                proposal_payload=h.proposal(gross_bps=30.0, cost_bps=10.0),
                risk_payload=h.risk("PASS", advisory=False),
                order_created=True,
            )
        ],
        executions=[h.execution("dec-filled")],
    )
    events = _events(run_dir)
    accepted = _by_type(events, EventType.DECISION_ACCEPTED)[0]
    filled = _by_type(events, EventType.ORDER_FILLED)[0]
    assert accepted.sequence < filled.sequence
    assert accepted.decision_status is DecisionStatus.ACCEPTED_NOT_EXECUTED
    assert filled.decision_status is DecisionStatus.EXECUTED_PAPER
    assert filled.extra["notional_usdt"] == 500.0
    # the fill price is NOT persisted by the runtime; the monitor says so
    assert filled.extra["fill_price"] is None
    assert "FILL_PRICE_NOT_RECORDED" in [r.code for r in filled.reason_codes]


def test_execution_failure_is_reported_as_failed_not_as_no_trade(tmp_path: Path) -> None:
    run_dir = h.write_run(
        tmp_path,
        [
            h.make_trace(
                "dec-err",
                mode=DecisionMode.TRADE_PAPER,
                classification="PAPER_ADMITTED",
                reason="admitted_candidate_with_positive_net_edge",
                no_trade_kind=None,
                proposal_payload=h.proposal(gross_bps=30.0, cost_bps=10.0),
                risk_payload=h.risk("PASS", advisory=False),
                errors=("BTC/USDT: broker_error BrokerOrderError: rejected",),
            )
        ],
        executions=[],
    )
    events = _events(run_dir)
    rejected = _by_type(events, EventType.ORDER_REJECTED)
    assert len(rejected) == 1
    assert rejected[0].decision_status is DecisionStatus.EXECUTION_FAILED
    assert rejected[0].extra["errors"] == [
        "BTC/USDT: broker_error BrokerOrderError: rejected"
    ]


def test_risk_veto_is_attributed_to_the_risk_engine(tmp_path: Path) -> None:
    run_dir = h.write_run(
        tmp_path,
        [
            h.make_trace(
                "dec-veto",
                classification="RISK_VETO",
                reason="risk_veto:max_drawdown",
                proposal_payload=h.proposal(gross_bps=30.0, cost_bps=10.0),
                risk_payload=h.risk(
                    "VETO",
                    advisory=False,
                    rule="max_drawdown",
                    reason="max_drawdown",
                ),
            )
        ],
    )
    event = _by_type(_events(run_dir), EventType.DECISION_REJECTED)[0]
    assert event.source_component == "risk_engine"
    assert event.risk_gate == "VETO"
    veto = next(r for r in event.reason_codes if r.code == "RISK_VETO")
    assert veto.evidence_ref == "trace.risk.risk_rule=max_drawdown"
    # the threshold is genuinely unknown here, so it must not be invented
    assert veto.threshold is None


# ---------------------------------------------------------------------------
# signals and silences
# ---------------------------------------------------------------------------


def test_signal_event_only_for_rows_that_really_emitted_alpha(tmp_path: Path) -> None:
    strategies = (
        h.considered("mean_reversion@5m", emitted=False, selected=False, gross_bps=1.2),
        h.considered("ema_crossover@5m", emitted=True, selected=True, gross_bps=8.0),
    )
    run_dir = h.write_run(
        tmp_path,
        [h.make_trace("dec-1", strategies=strategies, proposal_payload=h.proposal())],
    )
    signals = _by_type(_events(run_dir), EventType.SIGNAL_DETECTED)
    assert [s.strategy_id for s in signals] == ["ema_crossover@5m"]


def test_no_signal_means_no_decision_event_and_no_marker(tmp_path: Path) -> None:
    """A silent strategy must never be turned into a rejection."""
    strategies = (h.considered("trend@5m", emitted=False, selected=False),)
    run_dir = h.write_run(
        tmp_path,
        [
            h.make_trace(
                "dec-silent",
                classification="NO_PROPOSAL",
                reason="router_no_trade",
                no_trade_kind="NO_TRADE_STRATEGIC",
                strategies=strategies,
                proposal_payload=None,
            )
        ],
    )
    events = _events(run_dir)
    assert not _by_type(events, EventType.SIGNAL_DETECTED)
    # the decision itself is still recorded: "no proposal" is a decision, not silence
    decision = _by_type(events, EventType.DECISION_REJECTED)[0]
    assert "NO_PROPOSAL" in [r.code for r in decision.reason_codes]
    assert decision.decision_status is DecisionStatus.NO_TRADE


# ---------------------------------------------------------------------------
# integrity, determinism, read-only
# ---------------------------------------------------------------------------


def test_projection_is_deterministic_and_reuses_event_ids(tmp_path: Path) -> None:
    run_dir = h.write_run(
        tmp_path,
        [
            h.make_trace("dec-1", proposal_payload=h.proposal()),
            h.make_trace("dec-2", symbol="ETH/USDT", asset="ETH", proposal_payload=h.proposal()),
        ],
    )
    first = project_run(load_run(run_dir))
    second = project_run(load_run(run_dir))
    assert [e.event_id for e in first.events] == [e.event_id for e in second.events]
    assert [e.sequence for e in first.events] == [e.sequence for e in second.events]


def test_sequences_are_monotonic_and_contiguous(tmp_path: Path) -> None:
    run_dir = h.write_run(
        tmp_path,
        [h.make_trace(f"dec-{i}", proposal_payload=h.proposal()) for i in range(5)],
    )
    events = _events(run_dir)
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))


def test_events_are_ordered_by_decision_time(tmp_path: Path) -> None:
    run_dir = h.write_run(
        tmp_path,
        [
            h.make_trace("dec-late", decision_time_ms=h.TS0 + 2 * h.BAR_MS, market_time_ms=h.TS0),
            h.make_trace("dec-early", decision_time_ms=h.TS0, market_time_ms=h.TS0),
        ],
    )
    events = _events(run_dir)
    times = [e.decision_time_ms for e in events]
    assert times == sorted(times)
    assert events[0].decision_id == "dec-early"


def test_corrupt_line_is_reported_without_killing_the_view(tmp_path: Path) -> None:
    run_dir = h.write_run(tmp_path, [h.make_trace("dec-ok", proposal_payload=h.proposal())])
    with open(run_dir / "traces.jsonl", "a", encoding="utf-8") as handle:
        handle.write('{"decision_id": "dec-broken", "mode": "NO_TRADE"}\n')
    projection = project_run(load_run(run_dir))
    assert projection.invalid_records == 1
    assert projection.chain["ok"] is False
    assert any(e.event_type is EventType.PIPELINE_ERROR for e in projection.events)
    # the good record is still projected
    assert any(e.decision_id == "dec-ok" for e in projection.events)


def test_tampered_row_breaks_the_chain_but_still_projects(tmp_path: Path) -> None:
    run_dir = h.write_run(tmp_path, [h.make_trace("dec-1", proposal_payload=h.proposal())])
    path = run_dir / "traces.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["reason"] = "tampered reason"
    lines[0] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    projection = project_run(load_run(run_dir))
    assert projection.chain["ok"] is False
    assert projection.invalid_records == 1


def test_duplicate_decision_id_is_flagged(tmp_path: Path) -> None:
    run_dir = h.write_run(
        tmp_path,
        [
            h.make_trace("dec-dup", proposal_payload=h.proposal()),
            h.make_trace("dec-dup", proposal_payload=h.proposal()),
        ],
    )
    projection = project_run(load_run(run_dir))
    assert projection.duplicate_decision_ids == ("dec-dup",)


def test_venue_comes_from_the_run_environment(tmp_path: Path) -> None:
    run_dir = h.write_run(
        tmp_path,
        [h.make_trace("dec-1", proposal_payload=h.proposal())],
        executions=[],
        environment="ccxt:binance",
    )
    assert {e.venue for e in _events(run_dir)} == {"BINANCE"}


def test_venue_is_unknown_rather_than_invented(tmp_path: Path) -> None:
    run_dir = h.write_run(
        tmp_path,
        [h.make_trace("dec-1", proposal_payload=h.proposal())],
        executions=None,
        environment="",
    )
    assert {e.venue for e in _events(run_dir)} == {"UNKNOWN"}


def test_projection_does_not_modify_the_run_directory(tmp_path: Path) -> None:
    run_dir = h.write_run(
        tmp_path,
        [h.make_trace("dec-1", proposal_payload=h.proposal())],
        executions=[],
    )
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in run_dir.iterdir()}
    project_run(load_run(run_dir))
    after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in run_dir.iterdir()}
    assert before == after


def test_missing_run_directory_is_an_artifact_error(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError):
        load_run(tmp_path / "nope")


def test_oversized_trace_file_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = h.write_run(tmp_path, [h.make_trace("dec-1", proposal_payload=h.proposal())])
    from trading_bot.monitor import projector

    monkeypatch.setattr(projector, "MAX_ARTIFACT_BYTES", 10)
    with pytest.raises(ArtifactError, match="too large"):
        projector.load_run(run_dir)


def test_discover_runs_finds_only_run_directories(tmp_path: Path) -> None:
    h.write_run(tmp_path, [h.make_trace("dec-1")], run_id="run-a")
    h.write_run(tmp_path, [h.make_trace("dec-1")], run_id="run-b")
    (tmp_path / "not-a-run").mkdir()
    names = [p.name for p in discover_runs(tmp_path)]
    assert set(names) == {"run-a", "run-b"}
    assert len(names) == 2, "a directory without traces.jsonl is not a run"
    assert discover_runs(tmp_path / "missing") == []


def test_the_directory_name_is_the_run_identity_and_a_mismatch_is_visible(
    tmp_path: Path,
) -> None:
    """Defect found on real evidence: ``RUN_REPORT.run_id`` used to rename the run.

    A run produced by ``make_runtime`` writes ``autonomous-paper-<hash>`` into its
    report while living in a directory the operator addresses by name. The API
    must keep serving the directory name (otherwise ``?run_id=`` filters and
    drilldown disagree with the run list) and expose the disagreement.
    """
    run_dir = h.write_run(tmp_path, [h.make_trace("dec-1")], executions=[], run_id="run-a")
    report = json.loads((run_dir / "RUN_REPORT.json").read_text(encoding="utf-8"))
    report["run_id"] = "autonomous-paper-625d45b77ac0"
    (run_dir / "RUN_REPORT.json").write_text(json.dumps(report), encoding="utf-8")

    artifacts = load_run(run_dir)
    assert artifacts.run_id == "run-a"
    assert artifacts.runtime_run_id == "autonomous-paper-625d45b77ac0"
    assert artifacts.run_id != artifacts.runtime_run_id

    projection = project_run(artifacts)
    assert projection.run_id == "run-a"
    assert {e.run_id for e in projection.events} == {"run-a"}
