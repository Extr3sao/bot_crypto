"""End-to-end: the REAL PAPER runtime, projected by the monitor (WP-TDM-05).

These tests compose the canonical decision path exactly as
``scripts/autonomous_paper.py`` does — ``DecisionEngine``, ``IndependentVerifier``,
``RiskManager``, ``PaperBroker``, ``DecisionTraceStore`` — over deterministic
inputs. They are integration tests of the *runtime*, not mocks of it: the only
substitutions are the market-data reader and the strategy families, which is what
makes the decision reproducible.

Two RFC requirements are exercised here:

* REQ-TDM-001 — running the monitor changes nothing (CURRENT vs PROPOSED);
* REQ-TDM-011 — the five paper states are distinguishable from persisted evidence.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from trading_bot.autonomous.reporting import write_run_report
from trading_bot.monitor.contracts import DecisionStatus, EventType
from trading_bot.monitor.projector import load_run, project_run
from trading_bot.paper.broker import BrokerOrderError

from ..autonomous.helpers import (
    SilentFamily,
    make_admitted_ledger,
    make_ledger,
    make_runtime,
)


def _run(runtime: Any, run_dir: Path, **kwargs: Any) -> Any:
    summary = asyncio.run(runtime.run(**kwargs))
    write_run_report(summary, run_dir)  # the entrypoint does this at finalisation
    return summary


def _projected(run_dir: Path):
    return project_run(load_run(run_dir))


def _events(run_dir: Path, event_type: EventType):
    return [e for e in _projected(run_dir).events if e.event_type is event_type]


class ExplodingBroker:
    """A broker that accepts the order and fails: the 'sent, not filled' case."""

    positions: ClassVar[dict[str, Any]] = {}

    def execute_signal(self, signal: Any) -> Any:
        raise BrokerOrderError("paper venue rejected the order")

    def reconcile_session(self, *args: Any, **kwargs: Any) -> Any:
        return None


# ---------------------------------------------------------------------------
# the five paper states
# ---------------------------------------------------------------------------


def test_no_signal_produces_a_no_proposal_decision_and_no_marker(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        families={"ema_crossover": SilentFamily("ema_crossover")},
    )
    summary = _run(runtime, tmp_path, cycles=1)
    assert summary.totals()["no_trades"] == 1
    events = _projected(tmp_path).events
    assert not [e for e in events if e.event_type is EventType.SIGNAL_DETECTED]
    assert not [e for e in events if e.event_type is EventType.ORDER_FILLED]
    decision = next(e for e in events if e.event_type is EventType.DECISION_REJECTED)
    assert decision.decision_status is DecisionStatus.NO_TRADE
    # a silent family is NO_ALPHA: the router had nothing to propose
    assert "NO_ALPHA" in [r.code for r in decision.reason_codes]
    assert decision.to_dict()["decision_status_label"] == "NO_TRADE"


def test_cost_killed_decision_is_projected_as_shadow(tmp_path: Path) -> None:
    runtime, _scanner, broker = make_runtime(
        run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0)
    )
    _run(runtime, tmp_path, cycles=1)
    assert broker.positions == {}
    decision = next(
        e for e in _projected(tmp_path).events if e.event_type is EventType.DECISION_REJECTED
    )
    assert decision.decision_status is DecisionStatus.SHADOW_OBSERVED
    assert "COST_KILLED" in [r.code for r in decision.reason_codes]
    assert decision.to_dict()["decision_status_label"] == "SHADOW (NO EJECUTADA)"


def test_paper_fill_is_projected_from_the_execution_record(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=300.0)
    )
    summary = _run(runtime, tmp_path, cycles=1)
    assert summary.totals()["paper_trades"] == 1
    assert summary.totals()["orders_created"] == 1
    events = _projected(tmp_path).events
    filled = [e for e in events if e.event_type is EventType.ORDER_FILLED]
    assert len(filled) == 1
    assert filled[0].decision_status is DecisionStatus.EXECUTED_PAPER
    accepted = [e for e in events if e.event_type is EventType.DECISION_ACCEPTED]
    assert accepted and accepted[0].sequence < filled[0].sequence
    assert filled[0].extra["notional_usdt"] is not None


def test_broker_failure_becomes_accepted_then_order_rejected(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_admitted_ledger(gross_bps=300.0),
        broker=ExplodingBroker(),
    )
    summary = _run(runtime, tmp_path, cycles=1)
    assert summary.totals()["orders_created"] == 0, "a failed broker must not count as an order"
    events = _projected(tmp_path).events
    assert [e.event_type for e in events if e.event_type is EventType.ORDER_FILLED] == []
    rejected = [e for e in events if e.event_type is EventType.ORDER_REJECTED]
    assert len(rejected) == 1
    assert rejected[0].decision_status is DecisionStatus.EXECUTION_FAILED
    assert any("broker_error" in str(err) for err in rejected[0].extra["errors"])


def test_trace_without_a_finalised_report_is_not_reported_as_a_fill(tmp_path: Path) -> None:
    """GAP-TDM-02: a running PAPER process has a trace but no RUN_REPORT yet."""
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=300.0)
    )
    asyncio.run(runtime.run(cycles=1))
    # deliberately do NOT write RUN_REPORT.json (the run has not finalised)
    events = _projected(tmp_path).events
    assert [e.event_type for e in events if e.event_type is EventType.ORDER_FILLED] == []
    decision = [e for e in events if e.event_type is EventType.DECISION_ACCEPTED]
    assert decision, "the acceptance itself is evidenced by the trace"
    assert decision[0].decision_status is DecisionStatus.ACCEPTED_NOT_EXECUTED


# ---------------------------------------------------------------------------
# REQ-TDM-001 — the monitor changes nothing
# ---------------------------------------------------------------------------


def _normalise_ids(node: Any) -> Any:
    """Strip the per-run session prefix so two runs are comparable.

    ``decision_id`` is ``<session12>-<ASSET>`` in this runtime, so two runs over
    identical inputs differ only by that prefix. Normalising it is what makes the
    CURRENT vs PROPOSED comparison meaningful instead of trivially false.
    """
    if isinstance(node, dict):
        normalised: dict[str, Any] = {}
        for key, value in node.items():
            if key == "decision_id" and isinstance(value, str) and "-" in value:
                normalised[key] = value.split("-", 1)[-1]
            elif key == "cloid" and isinstance(value, str) and "-" in value:
                # the idempotency key embeds the session-derived decision suffix
                normalised[key] = value.rsplit("-", 1)[0] + "-<decision>"
            else:
                normalised[key] = _normalise_ids(value)
        return normalised
    if isinstance(node, list):
        return [_normalise_ids(item) for item in node]
    return node


def _comparable(summary: Any) -> dict[str, Any]:
    payload = summary.to_dict()
    for key in ("run_id", "started_at_ms", "ended_at_ms"):
        payload.pop(key, None)
    for cycle in payload.get("cycles_detail", []):
        cycle.pop("session_id", None)
        cycle.pop("started_at_ms", None)
        cycle.pop("ended_at_ms", None)
    for execution in payload.get("executions", []):
        execution.pop("run_id", None)
        # the idempotency key embeds the per-run session suffix by construction;
        # it is an ordering artefact, not a decision, so it is not compared here.
        execution.pop("cloid", None)
    payload["pending_decision_ids"] = [
        decision.split("-", 1)[-1] for decision in payload.get("pending_decision_ids", [])
    ]
    return _normalise_ids(payload)


def test_monitor_projection_does_not_change_the_runtime(tmp_path: Path) -> None:
    """CURRENT vs PROPOSED: same inputs, same decisions, same fills, same PnL."""

    def run_once(root: Path) -> tuple[Any, Path]:
        root.mkdir(parents=True, exist_ok=True)
        runtime, _scanner, _broker = make_runtime(
            run_dir=root, ledger=make_admitted_ledger(gross_bps=300.0)
        )
        summary = _run(runtime, root, cycles=1)
        return summary, root

    baseline_summary, baseline_dir = run_once(tmp_path / "current")
    # the monitor reads the baseline exactly as the server would
    baseline_projection = _projected(baseline_dir)
    assert baseline_projection.events

    proposed_summary, proposed_dir = run_once(tmp_path / "proposed")
    proposed_projection = _projected(proposed_dir)

    assert _comparable(baseline_summary) == _comparable(proposed_summary)

    # decisions, reasons and orders are identical
    baseline_rows = [
        (t.decision_id.split("-")[-1], t.mode.value, t.classification, t.reason, t.order_created)
        for t in baseline_summary.cycle_reports[0].assets
    ]
    proposed_rows = [
        (t.decision_id.split("-")[-1], t.mode.value, t.classification, t.reason, t.order_created)
        for t in proposed_summary.cycle_reports[0].assets
    ]
    assert baseline_rows == proposed_rows

    # and the monitor's view of both is the same shape/value per decision
    def decision_view(projection: Any) -> list[tuple[str, str, str, str]]:
        rows = {}
        for event in projection.events:
            rows[(event.decision_id.split("-")[-1], event.event_type.value)] = (
                event.decision_status.value,
                event.reason_summary,
                event.risk_gate,
                event.verification,
            )
        return sorted((k[0], k[1], v[0], v[1]) for k, v in rows.items())

    assert decision_view(baseline_projection) == decision_view(proposed_projection)

    # PnL-bearing evidence is identical
    assert baseline_summary.outcomes == proposed_summary.outcomes
    assert baseline_projection.chain["ok"] is True
    assert proposed_projection.chain["ok"] is True


def test_projection_of_a_real_run_has_no_invalid_records(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=300.0)
    )
    _run(runtime, tmp_path, cycles=1)
    projection = _projected(tmp_path)
    assert projection.invalid_records == 0
    assert projection.chain["ok"] is True
    assert projection.duplicate_decision_ids == ()
    for event in projection.events:
        assert event.observed_market_time_ms is None or (
            event.observed_market_time_ms <= event.decision_time_ms
        )


def test_projection_is_stable_when_re_read_repeatedly(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=300.0)
    )
    _run(runtime, tmp_path, cycles=1)
    first = [e.to_dict() for e in _projected(tmp_path).events]
    for _ in range(3):
        assert [e.to_dict() for e in _projected(tmp_path).events] == first


# ---------------------------------------------------------------------------
# adversarial: future evidence is refused
# ---------------------------------------------------------------------------


def test_a_fabricated_future_timestamp_is_refused(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=300.0)
    )
    _run(runtime, tmp_path, cycles=1)
    path = tmp_path / "traces.jsonl"
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    record["market_time_ms"] = record["decision_time_ms"] + 60_000  # the future
    path.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

    projection = _projected(tmp_path)
    assert projection.chain["ok"] is False
    assert projection.invalid_records == 1
    assert not [e for e in projection.events if e.event_type is EventType.ORDER_FILLED]
    assert any(e.event_type is EventType.PIPELINE_ERROR for e in projection.events)


@pytest.mark.parametrize("field", ["decision_time_ms", "market_time_ms"])
def test_a_truncated_trace_row_is_reported_not_dropped(tmp_path: Path, field: str) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=300.0)
    )
    _run(runtime, tmp_path, cycles=1)
    path = tmp_path / "traces.jsonl"
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    record.pop(field)
    path.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    projection = _projected(tmp_path)
    assert projection.invalid_records == 1
    assert projection.events, "the monitor must show the defect, not an empty screen"
