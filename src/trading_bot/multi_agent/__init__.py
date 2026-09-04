"""Deterministic multi-agent foundation, communication, and MA-2 intelligence plane."""

from .blackboard import BLACKBOARD_TOPICS, Blackboard, BlackboardArtifact
from .bus import TOPIC_BY_MESSAGE_TYPE, AgentBus, MessageHandler
from .communication_errors import (
    CommunicationError,
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
from .contracts import (
    AgentCapability,  # noqa: F401
    AgentEvidence,  # noqa: F401
    AgentLifecycleState,  # noqa: F401
    AgentManifest,  # noqa: F401
    AgentMessage,  # noqa: F401
    AgentMessageType,  # noqa: F401
    AgentRole,  # noqa: F401
    DeclaredCapabilities,
    ForbiddenAction,
    TraceContext,
    TradeDirection,
    TradeProposal,
    TradeProposalStatus,
    VerificationMetadata,
)
from .opportunity import (
    ConflictCase,
    MetaRanker,
    Opportunity,
    OpportunityBoard,
    OpportunityError,
    OpportunitySnapshot,
    RankedOpportunity,
)
from .registry import (
    AgentRegistry,  # noqa: F401
    CapabilityDeniedError,
    CapabilityPolicy,
    CapabilityRegistry,
    DuplicateAgentVersionError,
    InvalidLifecycleTransitionError,
    MultiAgentGovernanceError,
    UnknownAgentError,
)
from .session import (
    CommunicationReplay,
    CommunicationReplayResult,
    CommunicationSession,
    CommunicationSessionState,
    SessionStatus,
)
from .specialists import (
    ASSET_EXPERT_FACTORIES,
    STRATEGY_EXPERT_FACTORIES,
    AssetAssessment,
    AssetExpert,
    BreakoutExpert,
    BTCAssetExpert,
    ETHAssetExpert,
    MeanReversionExpert,
    MomentumExpert,
    SOLAssetExpert,
    StrategyEvaluation,
    StrategyExpert,
    TrendExpert,
    VolatilityExpert,
)
from .swarm import SpecialistSwarm, SwarmRun, register_swarm_agents

__all__ = [
    "ASSET_EXPERT_FACTORIES",
    "BLACKBOARD_TOPICS",
    "STRATEGY_EXPERT_FACTORIES",
    "TOPIC_BY_MESSAGE_TYPE",
    "AgentBus",
    "AssetAssessment",
    "AssetExpert",
    "BTCAssetExpert",
    "Blackboard",
    "BlackboardArtifact",
    "BreakoutExpert",
    "CapabilityDeniedError",
    "CapabilityPolicy",
    "CapabilityRegistry",
    "CommunicationError",
    "CommunicationReplay",
    "CommunicationReplayResult",
    "CommunicationSession",
    "CommunicationSessionState",
    "ConflictCase",
    "DeclaredCapabilities",
    "DuplicateAgentVersionError",
    "DuplicateMessageConflictError",
    "ETHAssetExpert",
    "EvidenceMissingError",
    "ExpiredMessageError",
    "ForbiddenAction",
    "InvalidLifecycleTransitionError",
    "InvalidMessageError",
    "MeanReversionExpert",
    "MessageHandler",
    "MetaRanker",
    "MomentumExpert",
    "MultiAgentGovernanceError",
    "Opportunity",
    "OpportunityBoard",
    "OpportunityError",
    "OpportunitySnapshot",
    "RankedOpportunity",
    "ReplyCorrelationError",
    "SOLAssetExpert",
    "SessionMaxRoundsError",
    "SessionStatus",
    "SessionTerminatedError",
    "SessionTimeoutError",
    "SpecialistSwarm",
    "StrategyEvaluation",
    "StrategyExpert",
    "SwarmRun",
    "TraceContext",
    "TraceMismatchError",
    "TradeDirection",
    "TradeProposal",
    "TradeProposalStatus",
    "TrendExpert",
    "UnauthorizedTopicError",
    "UnknownAgentError",
    "UnknownReceiverError",
    "UnknownSenderError",
    "VerificationMetadata",
    "VolatilityExpert",
    "register_swarm_agents",
]
