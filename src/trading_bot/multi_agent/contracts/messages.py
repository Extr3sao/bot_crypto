"""Structured inter-agent message contract."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import AgentMessageType
from .trace import TraceContext


class AgentMessage(BaseModel):
    """A bounded, structured message; never a free-form conversation log."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    sender: str = Field(min_length=1)
    receiver: str = Field(min_length=1)
    message_type: AgentMessageType
    claim: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    counter_evidence_refs: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime
    data_time: datetime
    requires_response: bool = False
    asset: str | None = None
    timeframe: str | None = None
    regime: str | None = None
    causation_id: str | None = None
    correlation_id: str | None = None
    expires_at: datetime | None = None
    # Optional structured payload (MA-3 debate artifacts travel inside the
    # certified MA-1 message envelope; no parallel message system).
    payload: tuple[tuple[str, str], ...] = ()
    trace: TraceContext | None = None

    @field_validator("created_at", "data_time", "expires_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("message timestamps must be timezone-aware")
        return value

    @field_validator("evidence_refs", "counter_evidence_refs", mode="before")
    @classmethod
    def _reject_empty_references(cls, value: object) -> object:
        if isinstance(value, (tuple, list)) and any(not item for item in value):
            raise ValueError("evidence references must contain non-empty identifiers")
        return value

    @field_validator("payload", mode="before")
    @classmethod
    def _freeze_payload(cls, value: object) -> object:
        if isinstance(value, dict):
            return tuple(sorted((str(k), str(v)) for k, v in value.items()))
        if isinstance(value, (tuple, list)) and any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not item[0]
            or not isinstance(item[1], str)
            for item in value
        ):
            raise ValueError("payload must be non-empty string key/value pairs")
        return value

    @model_validator(mode="after")
    def _validate_message(self) -> AgentMessage:
        if self.sender == self.receiver:
            raise ValueError("sender and receiver must differ")
        if self.data_time > self.created_at:
            raise ValueError("data_time cannot be later than created_at")
        if self.expires_at is not None and self.expires_at < self.created_at:
            raise ValueError("expires_at cannot be earlier than created_at")
        if self.trace is not None and (
            self.trace.run_id != self.run_id or self.trace.trace_id != self.trace_id
        ):
            raise ValueError("message trace identifiers must match message identifiers")
        return self


__all__ = ["AgentMessage"]
