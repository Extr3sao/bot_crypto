"""Property tests for MA-0 contract invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trading_bot.multi_agent.contracts import (
    AgentMessage,
    AgentMessageType,
    TradeDirection,
    TradeProposal,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _message(confidence: float) -> dict[str, object]:
    return {
        "schema_version": "ma-0-v1",
        "message_id": "property-message",
        "run_id": "run-1",
        "trace_id": "trace-1",
        "sender": "agent-a",
        "receiver": "agent-b",
        "message_type": AgentMessageType.OBSERVATION,
        "claim": "property claim",
        "confidence": confidence,
        "created_at": NOW,
        "data_time": NOW - timedelta(seconds=1),
    }


@given(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
def test_valid_confidence_round_trips(value: float) -> None:
    message = AgentMessage(**_message(value))
    assert message.confidence == value
    assert AgentMessage.model_validate(message.model_dump()) == message


@given(st.one_of(st.floats(max_value=-0.000001), st.floats(min_value=1.000001)))
def test_out_of_range_confidence_is_never_accepted(value: float) -> None:
    with pytest.raises(ValueError):
        AgentMessage(**_message(value))


def test_no_trade_round_trips_as_a_first_class_direction() -> None:
    proposal = TradeProposal(
        schema_version="ma-0-v1",
        proposal_id="property-proposal",
        run_id="run-1",
        trace_id="trace-1",
        asset="BTC/USDT",
        direction=TradeDirection.NO_TRADE,
        strategy="property",
        timeframe="5m",
        regime="RANGE",
        invalidation="property complete",
        confidence=0.5,
        data_time=NOW - timedelta(minutes=1),
        created_at=NOW,
    )
    rebuilt = TradeProposal.model_validate(proposal.model_dump())
    assert rebuilt.direction is TradeDirection.NO_TRADE
    assert rebuilt == proposal
