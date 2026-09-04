"""Fixture-only MA-1 end-to-end communication test."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from trading_bot.multi_agent.blackboard import Blackboard
from trading_bot.multi_agent.bus import AgentBus
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
from trading_bot.multi_agent.session import CommunicationSession, SessionStatus

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def test_fixture_agents_communicate_only_through_bus_and_blackboard() -> None:
    trace = TraceContext(
        run_id="e2e-run",
        trace_id="e2e-trace",
        correlation_id="e2e-correlation",
        causation_id="e2e-causation",
    )
    registry = AgentRegistry()
    capabilities = CapabilityRegistry()
    for agent_id, role in (("strategy", AgentRole.RESEARCHER), ("critic", AgentRole.CRITIC)):
        manifest = AgentManifest(
            schema_version="ma-1-v1",
            agent_id=agent_id,
            agent_version="1.0.0",
            role=role,
            description=f"Fixture {agent_id}",
            capabilities=frozenset({AgentCapability.READ, AgentCapability.WRITE}),
            lifecycle_state=AgentLifecycleState.ENABLED,
            created_at=NOW,
        )
        registry.register(manifest)
        capabilities.register_agent(manifest)
        capabilities.register_policy(
            CapabilityPolicy(
                agent_id=agent_id,
                agent_version="1.0.0",
                grants=frozenset({AgentCapability.READ, AgentCapability.WRITE}),
            )
        )

    blackboard = Blackboard(run_id=trace.run_id, trace_id=trace.trace_id)
    bus = AgentBus(
        agent_registry=registry,
        capability_registry=capabilities,
        blackboard=blackboard,
        clock=lambda: NOW,
    )
    side_effects = {"risk": 0, "broker": 0, "live": 0}
    received: list[tuple[str, str]] = []
    bus.register_handler("strategy", lambda message: received.append(("strategy", message.message_id)))
    bus.register_handler("critic", lambda message: received.append(("critic", message.message_id)))

    evidence = AgentEvidence(
        schema_version="ma-1-v1",
        evidence_id="fixture-evidence",
        run_id=trace.run_id,
        producer_agent_id="strategy",
        evidence_type="fixture_observation",
        source_ref="fixture://deterministic-market",
        observed_at=NOW - timedelta(minutes=1),
        available_at=NOW,
        content_hash=sha256(b"fixture-evidence").hexdigest(),
        trace=trace,
    )
    bus.register_evidence(evidence)
    session = CommunicationSession(
        session_id="fixture-session",
        run_id=trace.run_id,
        participants=("strategy", "critic"),
        max_rounds=4,
        bus=bus,
        started_at=NOW,
    )

    def message(message_id: str, sender: str, receiver: str, kind: AgentMessageType) -> AgentMessage:
        return AgentMessage(
            schema_version="ma-1-v1",
            message_id=message_id,
            run_id=trace.run_id,
            trace_id=trace.trace_id,
            sender=sender,
            receiver=receiver,
            message_type=kind,
            claim=message_id,
            evidence_refs=(evidence.evidence_id,),
            confidence=0.9,
            created_at=NOW,
            data_time=NOW - timedelta(seconds=1),
            causation_id="proposal-1" if kind is AgentMessageType.EVIDENCE_RESPONSE else None,
            trace=trace,
        )

    proposal = message("proposal-1", "strategy", "critic", AgentMessageType.PROPOSAL)
    critique = message("critique-1", "critic", "strategy", AgentMessageType.CRITIQUE)
    revision = message("revision-1", "strategy", "critic", AgentMessageType.EVIDENCE_RESPONSE)
    session.send(proposal)
    session.send(critique)
    session.send(revision)
    session.complete("fixture proposal reviewed and revised")

    assert session.state.status is SessionStatus.COMPLETED
    assert session.state.accepted_message_ids == ("proposal-1", "critique-1", "revision-1")
    assert [item.value.message_id for item in blackboard.history] == [
        "proposal-1",
        "critique-1",
        "revision-1",
    ]
    assert [item.topic for item in blackboard.history] == ["proposals", "criticisms", "evidence"]
    assert received == [
        ("critic", "proposal-1"),
        ("strategy", "critique-1"),
        ("critic", "revision-1"),
    ]
    assert side_effects == {"risk": 0, "broker": 0, "live": 0}
