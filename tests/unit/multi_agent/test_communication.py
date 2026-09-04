"""MA-1 communication runtime tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from trading_bot.multi_agent.blackboard import Blackboard
from trading_bot.multi_agent.bus import AgentBus
from trading_bot.multi_agent.communication_errors import (
    DuplicateMessageConflictError,
    EvidenceMissingError,
    ExpiredMessageError,
    InvalidMessageError,
    ReplyCorrelationError,
    SessionMaxRoundsError,
    SessionTerminatedError,
    SessionTimeoutError,
    TraceMismatchError,
    UnauthorizedTopicError,
    UnknownReceiverError,
    UnknownSenderError,
)
from trading_bot.multi_agent.contracts import (
    AgentCapability,
    AgentEvidence,
    AgentLifecycleState,
    AgentManifest,
    AgentMessage,
    AgentMessageType,
    AgentRole,
    TraceContext,
)
from trading_bot.multi_agent.registry import AgentRegistry, CapabilityPolicy, CapabilityRegistry
from trading_bot.multi_agent.session import (
    CommunicationReplay,
    CommunicationSession,
    SessionStatus,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
TRACE = TraceContext(
    run_id="run-1",
    trace_id="trace-1",
    correlation_id="corr-1",
    causation_id="cause-1",
)


def _manifest(agent_id: str) -> AgentManifest:
    return AgentManifest(
        schema_version="ma-1-v1",
        agent_id=agent_id,
        agent_version="1.0.0",
        role=AgentRole.RESEARCHER,
        description=f"Fixture {agent_id}",
        capabilities=frozenset({AgentCapability.READ, AgentCapability.WRITE}),
        created_at=NOW,
        lifecycle_state=AgentLifecycleState.ENABLED,
    )


def _runtime() -> tuple[AgentBus, Blackboard]:
    agents = AgentRegistry()
    capabilities = CapabilityRegistry()
    for agent_id in ("strategy", "critic", "observer"):
        manifest = _manifest(agent_id)
        agents.register(manifest)
        capabilities.register_agent(manifest)
        capabilities.register_policy(
            CapabilityPolicy(
                agent_id=agent_id,
                agent_version=manifest.agent_version,
                grants=frozenset({AgentCapability.READ, AgentCapability.WRITE}),
            )
        )
    blackboard = Blackboard(run_id=TRACE.run_id, trace_id=TRACE.trace_id)
    return AgentBus(
        agent_registry=agents,
        capability_registry=capabilities,
        blackboard=blackboard,
        clock=lambda: NOW,
    ), blackboard


def _message(
    message_id: str,
    sender: str = "strategy",
    receiver: str = "critic",
    message_type: AgentMessageType = AgentMessageType.OBSERVATION,
    **kwargs: object,
) -> AgentMessage:
    return AgentMessage(
        schema_version="ma-1-v1",
        message_id=message_id,
        run_id=TRACE.run_id,
        trace_id=TRACE.trace_id,
        sender=sender,
        receiver=receiver,
        message_type=message_type,
        claim="fixture claim",
        confidence=0.8,
        created_at=NOW,
        data_time=NOW - timedelta(seconds=1),
        trace=TRACE,
        **kwargs,
    )


def _evidence() -> AgentEvidence:
    return AgentEvidence(
        schema_version="ma-1-v1",
        evidence_id="ev-1",
        run_id=TRACE.run_id,
        producer_agent_id="strategy",
        evidence_type="fixture",
        source_ref="fixture://market",
        observed_at=NOW - timedelta(minutes=1),
        available_at=NOW,
        content_hash=sha256(b"fixture").hexdigest(),
        trace=TRACE,
    )


def test_bus_direct_route_publish_subscription_and_traceable_blackboard() -> None:
    bus, blackboard = _runtime()
    delivered: list[str] = []
    bus.register_handler("critic", lambda message: delivered.append(message.message_id))
    bus.subscribe("observer", "market_state", lambda message: delivered.append(f"sub:{message.message_id}"))

    accepted = bus.direct_route(_message("m-1"))

    assert accepted.message_id == "m-1"
    assert delivered == ["sub:m-1", "m-1"]
    assert blackboard.read("market_state")[0].value == accepted
    assert blackboard.history[0].producer == "strategy"
    assert blackboard.history[0].version == 1
    assert blackboard.history[0].trace == TRACE


def test_bus_broadcast_delivers_to_all_handlers_once() -> None:
    bus, _ = _runtime()
    delivered: list[str] = []
    bus.register_handler("critic", lambda message: delivered.append(message.receiver))
    bus.register_handler("observer", lambda message: delivered.append(message.receiver))

    messages = bus.broadcast(_message("m-broadcast", receiver="observer"))

    assert [message.receiver for message in messages] == ["critic", "observer"]
    assert delivered == ["critic", "observer"]
    assert len(bus.accepted_messages) == 2


def test_bus_request_reply_correlation_and_duplicate_idempotency() -> None:
    bus, _ = _runtime()
    request = _message(
        "request-1",
        message_type=AgentMessageType.EVIDENCE_REQUEST,
        requires_response=True,
    )
    bus.register_evidence(_evidence())
    bus.request(request)
    reply = _message(
        "reply-1",
        sender="critic",
        receiver="strategy",
        message_type=AgentMessageType.EVIDENCE_RESPONSE,
        causation_id="request-1",
        evidence_refs=("ev-1",),
    )
    assert bus.reply(reply, request_id="request-1") == reply
    assert bus.publish(request) == request
    with pytest.raises(DuplicateMessageConflictError):
        bus.publish(request.model_copy(update={"claim": "changed"}))
    with pytest.raises(ReplyCorrelationError):
        bus.reply(reply.model_copy(update={"message_id": "reply-2"}), request_id="missing")


def test_bus_rejects_identity_capability_evidence_trace_and_expiry_fail_closed() -> None:
    bus, _ = _runtime()
    with pytest.raises(UnknownSenderError):
        bus.publish(_message("unknown-sender", sender="missing"))
    with pytest.raises(UnknownReceiverError):
        bus.publish(_message("unknown-receiver", receiver="missing"))

    bus.capability_registry.deny("strategy", "1.0.0", AgentCapability.WRITE)
    with pytest.raises(UnauthorizedTopicError):
        bus.publish(_message("unauthorized"))
    with pytest.raises(UnauthorizedTopicError):
        bus.publish(_message("bad-topic"), topic="risk_flags")

    bus, _ = _runtime()
    with pytest.raises(EvidenceMissingError):
        bus.publish(_message("missing-evidence", message_type=AgentMessageType.PROPOSAL))
    bus.register_evidence(_evidence())
    proposal = _message(
        "proposal-1",
        message_type=AgentMessageType.PROPOSAL,
        evidence_refs=("ev-1",),
    )
    assert bus.publish(proposal) == proposal
    with pytest.raises(TraceMismatchError):
        bus.publish(proposal.model_copy(update={"message_id": "trace-bad", "trace_id": "other"}))
    with pytest.raises(ExpiredMessageError):
        bus.publish(_message("expired", expires_at=NOW))
    with pytest.raises(InvalidMessageError):
        bus.publish(object())  # type: ignore[arg-type]
    with pytest.raises(UnknownReceiverError):
        bus.register_handler("missing", lambda _: None)


def test_blackboard_rejects_unbound_evidence_and_is_append_only() -> None:
    _, blackboard = _runtime()
    with pytest.raises(ValueError):
        blackboard.publish(
            artifact_id="bad",
            topic="proposals",
            producer="strategy",
            timestamp=NOW,
            trace=TRACE,
            value={"mutable": []},
            evidence_refs=("not-bound",),
        )
    artifact = blackboard.publish(
        artifact_id="artifact-1",
        topic="decision_state",
        producer="strategy",
        timestamp=NOW,
        trace=TRACE,
        value={"mutable": []},
    )
    artifact.value["mutable"].append("outside")  # type: ignore[index]
    assert blackboard.get("artifact-1").value == {"mutable": []}
    assert blackboard.publish(
        artifact_id="artifact-1",
        topic="decision_state",
        producer="strategy",
        timestamp=NOW,
        trace=TRACE,
        value={"mutable": []},
    ).version == artifact.version


def test_session_completes_and_replays_same_state() -> None:
    bus, _ = _runtime()
    session = CommunicationSession(
        session_id="session-1",
        run_id=TRACE.run_id,
        participants=("strategy", "critic"),
        max_rounds=3,
        bus=bus,
        started_at=NOW,
    )
    bus.register_evidence(_evidence())
    session.send(_message("proposal", message_type=AgentMessageType.PROPOSAL, evidence_refs=("ev-1",)))
    session.send(_message("critique", sender="critic", receiver="strategy", message_type=AgentMessageType.CRITIQUE, evidence_refs=("ev-1",)))
    session.complete("fixture dialogue completed")
    replay = CommunicationReplay.replay(session, bus.accepted_messages)
    assert session.state.status is SessionStatus.COMPLETED
    assert replay == session.state
    assert replay.accepted_message_ids == ("proposal", "critique")


def test_session_failure_is_terminal_and_blocks_follow_up_messages() -> None:
    bus, _ = _runtime()
    session = CommunicationSession(
        session_id="failed",
        run_id=TRACE.run_id,
        participants=("strategy", "critic"),
        max_rounds=3,
        bus=bus,
        started_at=NOW,
    )
    session.fail("fixture failure")
    assert session.state.status is SessionStatus.FAILED
    with pytest.raises(SessionTerminatedError):
        session.send(_message("after-failure"))
    assert len(bus.accepted_messages) == 0


def test_session_timeout_and_max_rounds_terminate_without_side_effects() -> None:
    bus, blackboard = _runtime()
    timeout_session = CommunicationSession(
        session_id="timeout",
        run_id=TRACE.run_id,
        participants=("strategy", "critic"),
        max_rounds=3,
        bus=bus,
        started_at=NOW,
        timeout=timedelta(seconds=1),
    )
    with pytest.raises(SessionTimeoutError):
        timeout_session.send(_message("too-late"), now=NOW + timedelta(seconds=1))
    assert timeout_session.state.status is SessionStatus.TIMEOUT

    max_session = CommunicationSession(
        session_id="max",
        run_id=TRACE.run_id,
        participants=("strategy", "critic"),
        max_rounds=1,
        bus=bus,
        started_at=NOW,
    )
    max_session.send(_message("one"))
    with pytest.raises(SessionMaxRoundsError):
        max_session.send(_message("two"))
    assert max_session.state.status is SessionStatus.MAX_ROUNDS
    assert len(blackboard.history) == 1
    assert max_session.state.accepted_message_ids == ("one",)
