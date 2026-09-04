"""Canonical enums for the neutral multi-agent foundation."""

from __future__ import annotations

from enum import StrEnum


class AgentRole(StrEnum):
    """Declared role of an intelligence-plane agent."""

    ASSET_EXPERT = "ASSET_EXPERT"
    STRATEGY_EXPERT = "STRATEGY_EXPERT"
    CONTEXT_EXPERT = "CONTEXT_EXPERT"
    CRITIC = "CRITIC"
    ORCHESTRATOR = "ORCHESTRATOR"
    RESEARCHER = "RESEARCHER"


class AgentCapability(StrEnum):
    """Coarse capabilities that may be declared and policy-evaluated."""

    READ = "READ"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"
    EXTERNAL_ACTION = "EXTERNAL_ACTION"
    PRODUCTION_ACTION = "PRODUCTION_ACTION"
    RISK_OVERRIDE = "RISK_OVERRIDE"
    DIRECT_BROKER_ACCESS = "DIRECT_BROKER_ACCESS"


class ForbiddenAction(StrEnum):
    """Actions that trading agents must be able to declare as forbidden."""

    PLACE_LIVE_ORDER = "PLACE_LIVE_ORDER"
    MOVE_CAPITAL = "MOVE_CAPITAL"
    CHANGE_RISK_LIMIT = "CHANGE_RISK_LIMIT"
    CHANGE_LEVERAGE_LIMIT = "CHANGE_LEVERAGE_LIMIT"
    OVERRIDE_RISK_REJECTION = "OVERRIDE_RISK_REJECTION"
    MODIFY_PORTFOLIO_ACCOUNTING = "MODIFY_PORTFOLIO_ACCOUNTING"
    WRITE_SECRET = "WRITE_SECRET"
    EXPOSE_SECRET = "EXPOSE_SECRET"
    SELF_PROMOTE = "SELF_PROMOTE"
    SELF_VERIFY = "SELF_VERIFY"


class AgentLifecycleState(StrEnum):
    """Governed lifecycle states for registered agent versions."""

    DRAFT = "DRAFT"
    PROBATION = "PROBATION"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    RETIRED = "RETIRED"


class AgentMessageType(StrEnum):
    """Structured message kinds reserved for later communication phases."""

    OBSERVATION = "OBSERVATION"
    PROPOSAL = "PROPOSAL"
    CRITIQUE = "CRITIQUE"
    COUNTERPROPOSAL = "COUNTERPROPOSAL"
    RISK_WARNING = "RISK_WARNING"
    VETO = "VETO"
    AGREEMENT = "AGREEMENT"
    DECISION = "DECISION"
    HANDOFF = "HANDOFF"
    STATUS = "STATUS"
    EVIDENCE_REQUEST = "EVIDENCE_REQUEST"
    EVIDENCE_RESPONSE = "EVIDENCE_RESPONSE"


class TradeDirection(StrEnum):
    """Direction of a proposal, including explicit no-trade."""

    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


class TradeProposalStatus(StrEnum):
    """Non-execution lifecycle of a trade proposal."""

    CREATED = "CREATED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REJECTED = "REJECTED"
    APPROVED_FOR_RISK_REVIEW = "APPROVED_FOR_RISK_REVIEW"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


__all__ = [
    "AgentCapability",
    "AgentLifecycleState",
    "AgentMessageType",
    "AgentRole",
    "ForbiddenAction",
    "TradeDirection",
    "TradeProposalStatus",
]
