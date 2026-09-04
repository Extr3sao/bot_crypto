"""Canonical trading proposal contract for the intelligence plane."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import TradeDirection, TradeProposalStatus
from .trace import TraceContext


class TradeProposal(BaseModel):
    """A non-executing proposal passed toward later deterministic gates."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    direction: TradeDirection
    strategy: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    regime: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    counter_evidence_refs: tuple[str, ...] = ()
    invalidation: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    data_time: datetime
    created_at: datetime
    expires_at: datetime | None = None
    status: TradeProposalStatus = TradeProposalStatus.CREATED
    trace: TraceContext | None = None

    @field_validator("data_time", "created_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("proposal timestamps must be timezone-aware")
        return value

    @field_validator("evidence_refs", "counter_evidence_refs", mode="before")
    @classmethod
    def _reject_empty_references(cls, value: object) -> object:
        if isinstance(value, (tuple, list)) and any(not item for item in value):
            raise ValueError("evidence references must contain non-empty identifiers")
        return value

    @model_validator(mode="after")
    def _validate_proposal(self) -> TradeProposal:
        if self.data_time > self.created_at:
            raise ValueError("data_time cannot be later than created_at")
        if self.expires_at is not None and self.expires_at < self.created_at:
            raise ValueError("expires_at cannot be earlier than created_at")
        if (
            self.trace is not None
            and (self.trace.run_id != self.run_id or self.trace.trace_id != self.trace_id)
        ):
            raise ValueError("proposal trace identifiers must match proposal identifiers")
        if self.direction is TradeDirection.NO_TRADE and self.status is TradeProposalStatus.APPROVED_FOR_RISK_REVIEW:
            raise ValueError("NO_TRADE cannot be approved for risk review")
        return self


__all__ = ["TradeProposal"]
