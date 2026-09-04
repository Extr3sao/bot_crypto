"""Public MA-0B governance registries."""

from .agent_registry import AgentRegistry
from .capability_registry import CapabilityPolicy, CapabilityRegistry
from .errors import (
    CapabilityDeniedError,
    DuplicateAgentVersionError,
    InvalidLifecycleTransitionError,
    MultiAgentGovernanceError,
    UnknownAgentError,
)

__all__ = [
    "AgentRegistry",
    "CapabilityDeniedError",
    "CapabilityPolicy",
    "CapabilityRegistry",
    "DuplicateAgentVersionError",
    "InvalidLifecycleTransitionError",
    "MultiAgentGovernanceError",
    "UnknownAgentError",
]
