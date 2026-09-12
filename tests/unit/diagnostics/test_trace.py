from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from trading_bot.diagnostics import (
    DecisionTraceEvent,
    TraceReason,
    TraceStage,
    TraceStore,
    trace_id_for,
)


def event(
    *, stage: TraceStage = TraceStage.TRADE_PROPOSAL, event_type: str = "CREATED"
) -> DecisionTraceEvent:
    return DecisionTraceEvent(
        trace_id=trace_id_for("run-1", "proposal-1"),
        run_id="run-1",
        cycle_id="cycle-1",
        proposal_id="proposal-1",
        asset="BTCUSDT",
        strategy="momentum",
        timeframe="5m",
        stage=stage,
        event_type=event_type,
        actor="test",
        timestamp_utc="2026-09-12T00:00:00+00:00",
    )


def test_identity_is_deterministic_and_timestamp_independent() -> None:
    assert trace_id_for("run-1", "proposal-1") == trace_id_for("run-1", "proposal-1")
    assert trace_id_for("run-1", "proposal-1") != trace_id_for("run-1", "proposal-2")


def test_store_is_append_only_idempotent_and_queryable(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "trace.jsonl")
    proposal = event()
    rejected = replace(
        proposal,
        stage=TraceStage.RISK,
        event_type="RISK_REJECT",
        reason_code=TraceReason.MAX_POSITIONS,
        raw_reason="Max open positions reached (1)",
    )
    assert store.append(proposal) is True
    assert store.append(proposal) is False
    assert store.append(rejected) is True
    assert len(store.query(reason=TraceReason.MAX_POSITIONS)) == 1
    assert len(store.query(run_id="run-1", proposal_id="proposal-1")) == 2
    assert store.completeness()["unknown_terminal_state"] == 1


def test_outcome_is_separate_from_decision_and_replay(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "trace.jsonl")
    proposal = event()
    shadow = replace(proposal, stage=TraceStage.SHADOW_CAPTURE, event_type="SHADOW_CAPTURED")
    outcome = replace(
        proposal,
        stage=TraceStage.OUTCOME,
        event_type="OUTCOME_RESOLVED",
        provenance="SHADOW_RESOLVED",
    )
    store.append(proposal)
    store.append(shadow)
    store.append(outcome)
    decision_payload = store.query(trace_id=proposal.trace_id)[0].to_dict()
    assert "gross_return" not in decision_payload["metadata"]
    replay = store.replay(proposal.trace_id)
    assert replay["outcome_available"] is True
    assert replay["terminal_disposition"] == "OUTCOME_RESOLVED"


def test_malformed_trace_identity_fails_loudly() -> None:
    with pytest.raises(ValueError, match="trace_id"):
        DecisionTraceEvent(
            trace_id="wrong",
            run_id="run-1",
            cycle_id="cycle",
            proposal_id="proposal-1",
            asset="BTC",
            strategy="s",
            timeframe="5m",
            stage=TraceStage.TRADE_PROPOSAL,
            event_type="CREATED",
            actor="test",
            timestamp_utc="2026-09-12T00:00:00+00:00",
        )
