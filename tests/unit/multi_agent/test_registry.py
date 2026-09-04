"""MA-0B registry and governance tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_bot.multi_agent.contracts import (
    AgentCapability,
    AgentLifecycleState,
    AgentManifest,
    AgentRole,
)
from trading_bot.multi_agent.registry import (
    AgentRegistry,
    CapabilityDeniedError,
    CapabilityPolicy,
    CapabilityRegistry,
    DuplicateAgentVersionError,
    InvalidLifecycleTransitionError,
    UnknownAgentError,
)


def manifest(agent_id: str = "agent-a", version: str = "1.0.0") -> AgentManifest:
    return AgentManifest(
        schema_version="ma-0-v1",
        agent_id=agent_id,
        agent_version=version,
        role=AgentRole.STRATEGY_EXPERT,
        description="test agent",
        capabilities=frozenset({AgentCapability.READ, AgentCapability.WRITE}),
        output_contracts=("TradeProposal",),
        created_at=datetime(2026, 9, 4, tzinfo=UTC),
    )


def test_agent_registry_retains_versions_and_rejects_duplicates() -> None:
    registry = AgentRegistry()
    first = manifest()
    second = manifest(version="2.0.0")
    registry.register(first)
    registry.register(second)
    assert registry.get_version("agent-a", "1.0.0") == first
    assert registry.list_versions("agent-a") == ["1.0.0", "2.0.0"]
    with pytest.raises(DuplicateAgentVersionError):
        registry.register(first)
    with pytest.raises(UnknownAgentError):
        registry.get_version("agent-a", "9.0.0")


def test_agent_registry_enforces_explicit_lifecycle() -> None:
    registry = AgentRegistry()
    registry.register(manifest())
    with pytest.raises(InvalidLifecycleTransitionError):
        registry.enable("agent-a", "1.0.0")
    registry.place_in_probation("agent-a", "1.0.0")
    registry.enable("agent-a", "1.0.0")
    registry.disable("agent-a", "1.0.0")
    registry.place_in_probation("agent-a", "1.0.0")
    registry.retire("agent-a", "1.0.0")
    with pytest.raises(InvalidLifecycleTransitionError):
        registry.enable("agent-a", "1.0.0")
    assert registry.get_version("agent-a", "1.0.0").lifecycle_state is AgentLifecycleState.RETIRED


def test_capability_registry_is_default_deny_and_deny_wins() -> None:
    registry = CapabilityRegistry()
    agent = manifest()
    registry.register_agent(agent)
    assert not registry.is_allowed(agent.agent_id, agent.agent_version, AgentCapability.READ)
    registry.register_policy(
        CapabilityPolicy(
            agent_id=agent.agent_id,
            agent_version=agent.agent_version,
            grants=frozenset({AgentCapability.READ}),
        )
    )
    assert registry.is_allowed(agent.agent_id, agent.agent_version, AgentCapability.READ)
    registry.deny(agent.agent_id, agent.agent_version, AgentCapability.READ)
    assert not registry.is_allowed(agent.agent_id, agent.agent_version, AgentCapability.READ)
    assert registry.permissions_for(agent.agent_id, agent.agent_version) == frozenset()


def test_capability_registry_denies_unknown_and_permanent_capabilities() -> None:
    registry = CapabilityRegistry()
    assert not registry.is_allowed("missing", "1.0.0", AgentCapability.READ)
    assert registry.permissions_for("missing", "1.0.0") == frozenset()
    with pytest.raises(UnknownAgentError):
        registry.grant("missing", "1.0.0", AgentCapability.READ)

    agent = manifest()
    registry.register_agent(agent)
    for capability in (
        AgentCapability.PRODUCTION_ACTION,
        AgentCapability.RISK_OVERRIDE,
        AgentCapability.DIRECT_BROKER_ACCESS,
    ):
        with pytest.raises(CapabilityDeniedError):
            registry.grant(agent.agent_id, agent.agent_version, capability)
        assert not registry.is_allowed(agent.agent_id, agent.agent_version, capability)


def test_capability_policy_rejects_permanent_grants() -> None:
    with pytest.raises(ValueError):
        CapabilityPolicy(
            agent_id="agent-a",
            agent_version="1.0.0",
            grants=frozenset({AgentCapability.PRODUCTION_ACTION}),
        )


def test_capability_policy_rejects_unknown_agent() -> None:
    with pytest.raises(UnknownAgentError):
        CapabilityRegistry().register_policy(
            CapabilityPolicy(
                agent_id="missing",
                agent_version="1.0.0",
                grants=frozenset({AgentCapability.READ}),
            )
        )
