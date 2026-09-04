"""Registry errors for deterministic multi-agent governance."""

from __future__ import annotations


class MultiAgentGovernanceError(ValueError):
    """Base error for invalid multi-agent governance operations."""


class DuplicateAgentVersionError(MultiAgentGovernanceError):
    """Raised when an exact agent/version key is registered twice."""


class UnknownAgentError(MultiAgentGovernanceError):
    """Raised when an operation references an unknown agent version."""


class InvalidLifecycleTransitionError(MultiAgentGovernanceError):
    """Raised when a lifecycle transition is not explicitly permitted."""


class CapabilityDeniedError(MultiAgentGovernanceError):
    """Raised when a capability policy denies an action."""


__all__ = [
    "CapabilityDeniedError",
    "DuplicateAgentVersionError",
    "InvalidLifecycleTransitionError",
    "MultiAgentGovernanceError",
    "UnknownAgentError",
]
