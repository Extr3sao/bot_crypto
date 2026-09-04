"""Versioned agent registry for MA-0B governance."""

from __future__ import annotations

from trading_bot.multi_agent.contracts import AgentLifecycleState, AgentManifest

from .errors import DuplicateAgentVersionError, InvalidLifecycleTransitionError, UnknownAgentError

_ALLOWED_TRANSITIONS: dict[AgentLifecycleState, frozenset[AgentLifecycleState]] = {
    AgentLifecycleState.DRAFT: frozenset({AgentLifecycleState.PROBATION}),
    AgentLifecycleState.PROBATION: frozenset({AgentLifecycleState.ENABLED, AgentLifecycleState.DISABLED, AgentLifecycleState.RETIRED}),
    AgentLifecycleState.ENABLED: frozenset({AgentLifecycleState.DISABLED}),
    AgentLifecycleState.DISABLED: frozenset({AgentLifecycleState.PROBATION, AgentLifecycleState.RETIRED}),
    AgentLifecycleState.RETIRED: frozenset(),
}


class AgentRegistry:
    """In-memory registry retaining every immutable agent version."""

    def __init__(self) -> None:
        self._agents: dict[tuple[str, str], AgentManifest] = {}

    def register(self, manifest: AgentManifest) -> None:
        key = (manifest.agent_id, manifest.agent_version)
        if key in self._agents:
            raise DuplicateAgentVersionError(
                f"agent version already registered: {manifest.agent_id}@{manifest.agent_version}"
            )
        self._agents[key] = manifest

    def get(self, agent_id: str, agent_version: str | None = None) -> AgentManifest:
        """Resolve an exact version, or the sole/latest non-retired version."""
        if agent_version is not None:
            manifest = self._agents.get((agent_id, agent_version))
            if manifest is None:
                raise UnknownAgentError(f"unknown agent version: {agent_id}@{agent_version}")
            return manifest
        matches = [
            manifest
            for (aid, _), manifest in self._agents.items()
            if aid == agent_id and manifest.lifecycle_state is not AgentLifecycleState.RETIRED
        ]
        if not matches:
            raise UnknownAgentError(f"no active version for agent: {agent_id}")
        return matches[-1]

    def get_version(self, agent_id: str, agent_version: str) -> AgentManifest:
        return self.get(agent_id, agent_version)

    def list_agents(self) -> list[AgentManifest]:
        return list(self._agents.values())

    def list_versions(self, agent_id: str) -> list[str]:
        return [version for aid, version in self._agents if aid == agent_id]

    def transition(
        self, agent_id: str, agent_version: str, target: AgentLifecycleState
    ) -> AgentManifest:
        current = self.get(agent_id, agent_version)
        if target not in _ALLOWED_TRANSITIONS[current.lifecycle_state]:
            raise InvalidLifecycleTransitionError(
                f"invalid lifecycle transition for {agent_id}@{agent_version}: "
                f"{current.lifecycle_state} -> {target}"
            )
        updated = current.model_copy(update={"lifecycle_state": target})
        self._agents[(agent_id, agent_version)] = updated
        return updated

    def enable(self, agent_id: str, agent_version: str) -> AgentManifest:
        return self.transition(agent_id, agent_version, AgentLifecycleState.ENABLED)

    def disable(self, agent_id: str, agent_version: str) -> AgentManifest:
        return self.transition(agent_id, agent_version, AgentLifecycleState.DISABLED)

    def place_in_probation(self, agent_id: str, agent_version: str) -> AgentManifest:
        return self.transition(agent_id, agent_version, AgentLifecycleState.PROBATION)

    def retire(self, agent_id: str, agent_version: str) -> AgentManifest:
        return self.transition(agent_id, agent_version, AgentLifecycleState.RETIRED)

    def __len__(self) -> int:
        return len(self._agents)


__all__ = ["AgentRegistry"]
