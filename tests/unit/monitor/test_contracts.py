"""Contract tests for ``TradingDecisionEventV1`` (WP-TDM-01).

These are the tests that make the RFC's prohibitions executable: an acceptance can
never be serialised as a fill, a future observation can never be packaged, and an
unknown state can never be emitted silently.
"""

from __future__ import annotations

import pytest

from trading_bot.monitor.contracts import (
    DECISION_STATUS_LABELS,
    EVENT_TYPE_LABELS,
    SEVERITY_ORDER,
    DecisionStatus,
    EventType,
    MonitorContractError,
    ReasonCode,
    TemporalEvidenceError,
    TradingDecisionEventV1,
    iso_utc,
    reason_for,
)

EVENT_ID = "6f1b2f4a-1111-5222-8333-444455556666"


def make_event(**overrides: object) -> TradingDecisionEventV1:
    payload: dict[str, object] = {
        "event_id": EVENT_ID,
        "run_id": "run-a",
        "sequence": 1,
        "decision_id": "dec-1",
        "event_type": EventType.DECISION_REJECTED,
        "decision_status": DecisionStatus.NO_TRADE,
        "symbol": "BTC/USDT",
        "timeframe": "5m",
        "mode": "NO_TRADE",
        "observed_market_time": iso_utc(1_000),
        "observed_market_time_ms": 1_000,
        "decision_time": iso_utc(2_000),
        "decision_time_ms": 2_000,
        "emitted_at": iso_utc(2_100),
        "reason_codes": (reason_for("NO_GROSS_EDGE", measured_value=-4.56, threshold=0.0, unit="bps"),),
        "reason_summary": "NO_TRADE · NO_GROSS_EDGE",
    }
    payload.update(overrides)
    return TradingDecisionEventV1(**payload)  # type: ignore[arg-type]


def test_round_trip_preserves_every_field() -> None:
    event = make_event()
    rebuilt = TradingDecisionEventV1.from_dict(event.to_dict())
    assert rebuilt.to_dict() == event.to_dict()


def test_schema_version_is_enforced_on_read() -> None:
    payload = make_event().to_dict()
    payload["schema_version"] = "2.0"
    with pytest.raises(MonitorContractError, match="unsupported schema_version"):
        TradingDecisionEventV1.from_dict(payload)


def test_event_id_must_be_a_uuid() -> None:
    with pytest.raises(MonitorContractError, match="event_id must be a UUID"):
        make_event(event_id="dec-1")


def test_sequence_must_be_positive() -> None:
    with pytest.raises(MonitorContractError, match="sequence"):
        make_event(sequence=0)


def test_future_market_observation_is_rejected() -> None:
    with pytest.raises(TemporalEvidenceError):
        make_event(observed_market_time_ms=2_001, decision_time_ms=2_000)


@pytest.mark.parametrize("event_type", list(EventType))
def test_every_event_type_has_accessible_copy(event_type: EventType) -> None:
    entry = EVENT_TYPE_LABELS[event_type]
    assert entry["text"] and entry["icon"] and entry["tone"]
    # colour/icon is never the only carrier: text is mandatory and distinct
    assert entry["text"] != ""


def test_every_decision_status_has_an_explicit_label() -> None:
    labels = [DECISION_STATUS_LABELS[status] for status in DecisionStatus]
    assert all(labels)
    assert len(set(labels)) == len(labels), "each status must read differently in the UI"


def test_acceptance_cannot_be_serialised_as_a_fill() -> None:
    with pytest.raises(MonitorContractError, match="DECISION_ACCEPTED"):
        make_event(
            event_type=EventType.DECISION_ACCEPTED,
            decision_status=DecisionStatus.EXECUTED_PAPER,
        )


def test_fill_requires_the_executed_status() -> None:
    with pytest.raises(MonitorContractError, match="ORDER_FILLED"):
        make_event(
            event_type=EventType.ORDER_FILLED,
            decision_status=DecisionStatus.ACCEPTED_NOT_EXECUTED,
        )


def test_unknown_event_type_is_not_silently_accepted() -> None:
    payload = make_event().to_dict()
    payload["event_type"] = "ORDER_FILLED_GUESSED"
    with pytest.raises(ValueError):
        TradingDecisionEventV1.from_dict(payload)


def test_reason_short_text_is_bounded() -> None:
    with pytest.raises(MonitorContractError, match="short_text"):
        ReasonCode(code="X", short_text="a" * 161, component="test")


def test_reason_severity_is_constrained() -> None:
    with pytest.raises(MonitorContractError, match="severity"):
        ReasonCode(code="X", short_text="ok", component="test", severity="LOUD")
    assert set(SEVERITY_ORDER) == {"INFO", "WARN", "ERROR", "CRITICAL"}


def test_unknown_reason_code_is_preserved_not_dropped() -> None:
    reason = reason_for("SOMETHING_NEW_FROM_THE_FUTURE")
    assert reason.code == "SOMETHING_NEW_FROM_THE_FUTURE"
    assert "no catalogado" in reason.short_text


def test_reason_keeps_measured_value_and_threshold_when_known() -> None:
    reason = reason_for("NO_GROSS_EDGE", measured_value=-4.56, threshold=0.0, unit="bps")
    assert reason.measured_value == -4.56
    assert reason.threshold == 0.0
    assert reason.unit == "bps"


def test_reason_leaves_threshold_unknown_instead_of_inventing_it() -> None:
    reason = reason_for("RISK_VETO")
    assert reason.threshold is None
    assert reason.measured_value is None


def test_iso_utc_is_always_zulu() -> None:
    assert iso_utc(0) == "1970-01-01T00:00:00.000Z"
    assert iso_utc(None) is None


def test_summary_length_is_bounded() -> None:
    with pytest.raises(MonitorContractError, match="reason_summary"):
        make_event(reason_summary="x" * 400)
