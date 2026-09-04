"""Evidence contract for point-in-time, auditable agent claims."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .trace import TraceContext

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AgentEvidence(BaseModel):
    """Evidence linking a source observation to one or more claims.

    Metadata is represented as an immutable tuple of key/value pairs so the
    frozen Pydantic model is also safe against nested mutation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    producer_agent_id: str = Field(min_length=1)
    evidence_type: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    claim_refs: tuple[str, ...] = ()
    observed_at: datetime
    available_at: datetime
    content_hash: str = Field(min_length=64, max_length=64)
    metadata: tuple[tuple[str, str | int | float | bool], ...] = ()
    trace: TraceContext | None = None

    @field_validator("observed_at", "available_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evidence timestamps must be timezone-aware")
        return value

    @field_validator("content_hash")
    @classmethod
    def _require_sha256(cls, value: str) -> str:
        if _SHA256_RE.fullmatch(value) is None:
            raise ValueError("content_hash must be a lowercase SHA-256 hex digest")
        return value

    @field_validator("metadata", mode="before")
    @classmethod
    def _freeze_metadata(cls, value: object) -> object:
        if isinstance(value, Mapping):
            return tuple(value.items())
        return value

    @field_validator("claim_refs", mode="before")
    @classmethod
    def _reject_empty_claim_refs(cls, value: object) -> object:
        if isinstance(value, (tuple, list)) and any(not item for item in value):
            raise ValueError("claim_refs must contain non-empty identifiers")
        return value

    @model_validator(mode="after")
    def _validate_temporal_order(self) -> AgentEvidence:
        if self.observed_at > self.available_at:
            raise ValueError("observed_at cannot be later than available_at")
        if self.trace is not None and self.trace.run_id != self.run_id:
            raise ValueError("trace.run_id must match evidence.run_id")
        return self

    def is_valid_at(self, decision_time: datetime) -> bool:
        """Return whether this evidence was available by a decision time."""
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        return self.available_at <= decision_time


__all__ = ["AgentEvidence"]
