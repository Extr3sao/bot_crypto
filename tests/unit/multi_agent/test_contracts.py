"""MA-0A contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from pydantic import ValidationError

from trading_bot.multi_agent.contracts import (
    AgentCapability,
    AgentEvidence,
    AgentManifest,
    AgentMessage,
    AgentMessageType,
    AgentRole,
    DeclaredCapabilities,
    ForbiddenAction,
    TraceContext,
    TradeDirection,
    TradeProposal,
    TradeProposalStatus,
    VerificationMetadata,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
TRACE = TraceContext(
    run_id="run-1",
    trace_id="trace-1",
    correlation_id="corr-1",
    causation_id="cause-1",
)


def _manifest() -> AgentManifest:
    return AgentManifest(
        schema_version="ma-0-v1",
        agent_id="momentum-expert",
        agent_version="1.0.0",
        role=AgentRole.STRATEGY_EXPERT,
        description="Deterministic momentum specialist.",
        capabilities=frozenset({AgentCapability.READ}),
        input_contracts=("AssetContext",),
        output_contracts=("TradeProposal",),
        allowed_tools=("indicator_registry",),
        forbidden_actions=frozenset(ForbiddenAction),
        created_at=NOW,
    )


def test_manifest_is_strict_frozen_and_versioned() -> None:
    manifest = _manifest()
    assert manifest.agent_id == "momentum-expert"
    assert manifest.model_config["extra"] == "forbid"
    with pytest.raises((ValidationError, TypeError)):
        manifest.agent_id = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        AgentManifest(**{**manifest.model_dump(), "unknown": True})


def test_manifest_rejects_naive_and_empty_identity() -> None:
    with pytest.raises(ValidationError):
        AgentManifest(**{**_manifest().model_dump(), "created_at": datetime(2026, 9, 4)})
    with pytest.raises(ValidationError):
        AgentManifest(**{**_manifest().model_dump(), "agent_id": ""})


def test_capability_declarations_are_not_permissions() -> None:
    declaration = DeclaredCapabilities(
        capabilities=frozenset(
            {
                AgentCapability.PRODUCTION_ACTION,
                AgentCapability.RISK_OVERRIDE,
                AgentCapability.DIRECT_BROKER_ACCESS,
            }
        )
    )
    assert len(declaration.capabilities) == 3


def test_forbidden_capabilities_remain_declarative_only() -> None:
    for capability in (
        AgentCapability.PRODUCTION_ACTION,
        AgentCapability.RISK_OVERRIDE,
        AgentCapability.DIRECT_BROKER_ACCESS,
    ):
        declaration = DeclaredCapabilities(capabilities=frozenset({capability}))
        assert capability in declaration.capabilities


def test_message_validates_identity_confidence_and_point_in_time() -> None:
    message = AgentMessage(
        schema_version="ma-0-v1",
        message_id="msg-1",
        run_id="run-1",
        trace_id="trace-1",
        sender="momentum-expert",
        receiver="risk-critic",
        message_type=AgentMessageType.OBSERVATION,
        claim="Momentum is positive.",
        evidence_refs=("ev-1",),
        confidence=0.75,
        created_at=NOW,
        data_time=NOW - timedelta(minutes=1),
        trace=TRACE,
    )
    assert message.model_dump()["message_type"] == AgentMessageType.OBSERVATION
    for confidence in (-0.01, 1.01):
        with pytest.raises(ValidationError):
            AgentMessage(
                **{**message.model_dump(), "confidence": confidence}
            )
    with pytest.raises(ValidationError):
        AgentMessage(**{**message.model_dump(), "sender": "risk-critic"})
    with pytest.raises(ValidationError):
        AgentMessage(**{**message.model_dump(), "data_time": NOW + timedelta(seconds=1)})


def test_evidence_requires_sha256_and_available_order() -> None:
    digest = sha256(b"deterministic evidence").hexdigest()
    evidence = AgentEvidence(
        schema_version="ma-0-v1",
        evidence_id="ev-1",
        run_id="run-1",
        producer_agent_id="momentum-expert",
        evidence_type="metric",
        source_ref="dataset://bars/BTC",
        claim_refs=("claim-1",),
        observed_at=NOW - timedelta(minutes=2),
        available_at=NOW - timedelta(minutes=1),
        content_hash=digest,
        metadata={"metric": "momentum", "value": 0.5},
        trace=TRACE,
    )
    assert evidence.is_valid_at(NOW)
    assert not evidence.is_valid_at(NOW - timedelta(seconds=90))
    with pytest.raises((ValidationError, AttributeError, TypeError)):
        evidence.metadata += (("new", True),)  # type: ignore[misc]
    with pytest.raises(ValidationError):
        AgentEvidence(**{**evidence.model_dump(), "content_hash": "bad"})
    with pytest.raises(ValidationError):
        AgentEvidence(**{**evidence.model_dump(), "observed_at": NOW})


def _proposal(direction: TradeDirection = TradeDirection.LONG) -> TradeProposal:
    return TradeProposal(
        schema_version="ma-0-v1",
        proposal_id="proposal-1",
        run_id="run-1",
        trace_id="trace-1",
        asset="BTC/USDT",
        direction=direction,
        strategy="momentum",
        timeframe="5m",
        regime="TREND_UP",
        evidence_refs=("ev-1",),
        invalidation="Close below structural support.",
        confidence=0.8,
        data_time=NOW - timedelta(minutes=1),
        created_at=NOW,
        trace=TRACE,
    )


def test_trade_proposal_supports_long_short_and_explicit_no_trade() -> None:
    for direction in TradeDirection:
        proposal = _proposal(direction)
        assert proposal.direction is direction
    no_trade = _proposal(TradeDirection.NO_TRADE)
    assert no_trade.status is TradeProposalStatus.CREATED
    with pytest.raises(ValidationError):
        TradeProposal(
            **{
                **no_trade.model_dump(),
                "status": TradeProposalStatus.APPROVED_FOR_RISK_REVIEW,
            }
        )


def test_trace_and_verification_require_distinct_identities() -> None:
    metadata = VerificationMetadata(
        artifact_id="proposal-1",
        builder_agent_id="builder",
        verifier_agent_id="verifier",
    )
    assert metadata.builder_agent_id != metadata.verifier_agent_id
    with pytest.raises(ValidationError):
        VerificationMetadata(
            artifact_id="proposal-1",
            builder_agent_id="same",
            verifier_agent_id="same",
        )


def test_contract_round_trip_preserves_equality() -> None:
    original = _proposal(TradeDirection.NO_TRADE)
    rebuilt = TradeProposal.model_validate(original.model_dump())
    assert rebuilt == original
