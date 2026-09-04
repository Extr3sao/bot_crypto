"""Deterministic multi-agent foundation.

MA-0 provides neutral contracts and governance registries only. It has no
runtime trading authority and deliberately does not import paper, risk,
execution, exchange, or orchestration modules.
"""

from .contracts import (
    AgentCapability,
    AgentEvidence,
    AgentLifecycleState,
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
from .registry import (
    AgentRegistry,
    CapabilityDeniedError,
    CapabilityPolicy,
    CapabilityRegistry,
    DuplicateAgentVersionError,
    InvalidLifecycleTransitionError,
    MultiAgentGovernanceError,
    UnknownAgentError,
)

__all__ = [
    "AgentCapability",
    "AgentEvidence",
    "AgentLifecycleState",
    "AgentManifest",
    "AgentMessage",
    "AgentMessageType",
    "AgentRegistry",
    "AgentRole",
    "CapabilityDeniedError",
    "CapabilityPolicy",
    "CapabilityRegistry",
    "DeclaredCapabilities",
    "DuplicateAgentVersionError",
    "ForbiddenAction",
    "InvalidLifecycleTransitionError",
    "MultiAgentGovernanceError",
    "TraceContext",
    "TradeDirection",
    "TradeProposal",
    "TradeProposalStatus",
    "UnknownAgentError",
    "VerificationMetadata",
]
