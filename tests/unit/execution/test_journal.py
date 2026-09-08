from __future__ import annotations

import json

import pytest

from trading_bot.execution import ExecutionJournal, ExecutionReliabilityError, ExecutionState


def _journal() -> ExecutionJournal:
    return ExecutionJournal()


def _created(journal: ExecutionJournal, intent_id: str = "TI-abc123") -> None:
    journal.record(
        intent_id=intent_id,
        client_order_id="CO-abc123",
        new_state=ExecutionState.CREATED,
        reason="intent created",
        timestamp=1.0,
    )


def test_canonical_states_are_complete() -> None:
    expected = {
        "CREATED",
        "SUBMITTING",
        "ACK_UNKNOWN",
        "ACCEPTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCEL_PENDING",
        "CANCELLED",
        "REJECTED",
        "ORPHANED",
        "RECONCILING",
    }
    assert {s.value for s in ExecutionState} == expected


def test_happy_path_transitions() -> None:
    journal = _journal()
    _created(journal)
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="SUBMITTING",
        reason="submitted",
        timestamp=2.0,
    )
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="ACCEPTED",
        reason="venue ack",
        venue_order_id="VO-1",
        timestamp=3.0,
    )
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="FILLED",
        reason="full fill",
        venue_order_id="VO-1",
        timestamp=4.0,
    )
    assert journal.current_state("TI-abc123") == ExecutionState.FILLED
    assert journal.is_terminal("TI-abc123")
    assert len(journal.history("TI-abc123")) == 4


def test_illegal_transition_raises_and_does_not_append() -> None:
    journal = _journal()
    _created(journal)
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="SUBMITTING",
        reason="submitted",
        timestamp=2.0,
    )
    with pytest.raises(ExecutionReliabilityError):
        journal.record(
            intent_id="TI-abc123",
            client_order_id="CO-abc123",
            new_state="CANCELLED",
            reason="illegal skip",
            timestamp=3.0,
        )
    # Append-only: the illegal transition is not recorded.
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="ACCEPTED",
        reason="acked",
        timestamp=4.0,
    )
    assert len(journal.history("TI-abc123")) == 3


def test_ack_unknown_recovery_path() -> None:
    journal = _journal()
    _created(journal)
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="SUBMITTING",
        reason="submitted",
        timestamp=2.0,
    )
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="ACK_UNKNOWN",
        reason="submit timeout",
        timestamp=3.0,
    )
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="ACCEPTED",
        reason="adopted after venue query",
        venue_order_id="VO-9",
        timestamp=4.0,
    )
    assert journal.current_state("TI-abc123") == ExecutionState.ACCEPTED


def test_cancel_requires_pending_before_cancelled() -> None:
    journal = _journal()
    _created(journal)
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="SUBMITTING",
        reason="submitted",
        timestamp=2.0,
    )
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="ACCEPTED",
        reason="ack",
        timestamp=3.0,
    )
    # Cannot jump straight to CANCELLED from ACCEPTED: must go CANCEL_PENDING.
    with pytest.raises(ExecutionReliabilityError):
        journal.record(
            intent_id="TI-abc123",
            client_order_id="CO-abc123",
            new_state="CANCELLED",
            reason="assumed cancel",
            timestamp=4.0,
        )
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="CANCEL_PENDING",
        reason="cancel requested",
        timestamp=4.0,
    )
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="CANCELLED",
        reason="venue confirmed cancel",
        timestamp=5.0,
    )
    assert journal.current_state("TI-abc123") == ExecutionState.CANCELLED


def test_partial_fill_progression() -> None:
    journal = _journal()
    _created(journal)
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="SUBMITTING",
        reason="submitted",
        timestamp=2.0,
    )
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="ACCEPTED",
        reason="ack",
        timestamp=3.0,
    )
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="PARTIALLY_FILLED",
        reason="partial fill",
        timestamp=4.0,
    )
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="FILLED",
        reason="remaining filled",
        timestamp=5.0,
    )
    assert journal.current_state("TI-abc123") == ExecutionState.FILLED


def test_orphan_reconciliation_path() -> None:
    journal = _journal()
    _created(journal)
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="SUBMITTING",
        reason="submitted",
        timestamp=2.0,
    )
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="ACK_UNKNOWN",
        reason="lost ack",
        timestamp=3.0,
    )
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="RECONCILING",
        reason="reconciliation started",
        timestamp=4.0,
    )
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="FILLED",
        reason="adopted venue fill after reconciliation",
        timestamp=5.0,
    )
    assert journal.current_state("TI-abc123") == ExecutionState.FILLED


def test_persistence_is_append_only_jsonl(tmp_path: object) -> None:
    import pathlib

    path = pathlib.Path(str(tmp_path)) / "journal.jsonl"
    journal = ExecutionJournal(path=path)
    _created(journal)
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="SUBMITTING",
        reason="submitted",
        timestamp=2.0,
    )
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["new_state"] == "CREATED"
    assert first["intent_id"] == "TI-abc123"
    assert "evidence_digest" in first


def test_rejected_is_terminal() -> None:
    journal = _journal()
    _created(journal)
    journal.record(
        intent_id="TI-abc123",
        client_order_id="CO-abc123",
        new_state="REJECTED",
        reason="venue rejected",
        timestamp=2.0,
    )
    assert journal.is_terminal("TI-abc123")
    with pytest.raises(ExecutionReliabilityError):
        journal.record(
            intent_id="TI-abc123",
            client_order_id="CO-abc123",
            new_state="ACCEPTED",
            reason="revive",
            timestamp=3.0,
        )
