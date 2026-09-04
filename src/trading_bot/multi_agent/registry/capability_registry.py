"""Capability policy registry for MA-0B."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trading_bot.multi_agent.contracts import AgentCapability, AgentManifest

from .errors import CapabilityDeniedError, UnknownAgentError

_ALWAYS_DENIED = frozenset(
    {
        AgentCapability.PRODUCTION_ACTION,
        AgentCapability.RISK_OVERRIDE,
        AgentCapability.DIRECT_BROKER_ACCESS,
    }
)


class CapabilityPolicy(BaseModel):
    """Immutable grants and denials for one exact agent version."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    agent_id: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    grants: frozenset[AgentCapability] = Field(default_factory=frozenset)
    denials: frozenset[AgentCapability] = Field(default_factory=frozenset)

    @field_validator("grants")
    @classmethod
    def _reject_permanent_grants(
        cls, value: frozenset[AgentCapability]
    ) -> frozenset[AgentCapability]:
        invalid = value.intersection(_ALWAYS_DENIED)
        if invalid:
            names = ", ".join(sorted(item.value for item in invalid))
            raise ValueError(f"MA-0 permanently denies capability grants: {names}")
        return value


class CapabilityRegistry:
    """Evaluate effective permissions using default-deny semantics."""

    def __init__(self) -> None:
        self._manifests: dict[tuple[str, str], AgentManifest] = {}
        self._policies: dict[tuple[str, str], CapabilityPolicy] = {}

    def register_agent(self, manifest: AgentManifest) -> None:
        """Register an agent identity for subsequent policy evaluation."""
        self._manifests[(manifest.agent_id, manifest.agent_version)] = manifest

    def register_policy(self, policy: CapabilityPolicy) -> None:
        self._require_agent(policy.agent_id, policy.agent_version)
        self._policies[(policy.agent_id, policy.agent_version)] = policy

    def grant(self, agent_id: str, agent_version: str, capability: AgentCapability) -> None:
        self._require_agent(agent_id, agent_version)
        if capability in _ALWAYS_DENIED:
            raise CapabilityDeniedError(f"MA-0 permanently denies capability: {capability}")
        current = self._policies.get((agent_id, agent_version))
        grants = set(current.grants if current else ())
        denials = set(current.denials if current else ())
        grants.add(capability)
        self._policies[(agent_id, agent_version)] = CapabilityPolicy(
            agent_id=agent_id,
            agent_version=agent_version,
            grants=frozenset(grants),
            denials=frozenset(denials),
        )

    def deny(self, agent_id: str, agent_version: str, capability: AgentCapability) -> None:
        self._require_agent(agent_id, agent_version)
        current = self._policies.get((agent_id, agent_version))
        grants = set(current.grants if current else ())
        denials = set(current.denials if current else ())
        denials.add(capability)
        self._policies[(agent_id, agent_version)] = CapabilityPolicy(
            agent_id=agent_id,
            agent_version=agent_version,
            grants=frozenset(grants),
            denials=frozenset(denials),
        )

    def is_allowed(self, agent_id: str, agent_version: str, capability: AgentCapability) -> bool:
        """Return effective permission; unknown identities/capabilities deny."""
        if not isinstance(capability, AgentCapability):
            return False
        if (agent_id, agent_version) not in self._manifests:
            return False
        if capability in _ALWAYS_DENIED:
            return False
        policy = self._policies.get((agent_id, agent_version))
        if policy is None or capability in policy.denials:
            return False
        return capability in policy.grants

    def assert_allowed(
        self, agent_id: str, agent_version: str, capability: AgentCapability
    ) -> None:
        if not self.is_allowed(agent_id, agent_version, capability):
            raise CapabilityDeniedError(
                f"capability denied for {agent_id}@{agent_version}: {capability}"
            )

    def permissions_for(self, agent_id: str, agent_version: str) -> frozenset[AgentCapability]:
        """Return effective permissions, or deny all for an unknown agent."""
        if (agent_id, agent_version) not in self._manifests:
            return frozenset()
        return frozenset(
            capability
            for capability in AgentCapability
            if self.is_allowed(agent_id, agent_version, capability)
        )

    def _require_agent(self, agent_id: str, agent_version: str) -> AgentManifest:
        manifest = self._manifests.get((agent_id, agent_version))
        if manifest is None:
            raise UnknownAgentError(f"unknown agent version: {agent_id}@{agent_version}")
        return manifest


__all__ = ["CapabilityPolicy", "CapabilityRegistry"]
