"""Trace and independent-verification contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TraceContext(BaseModel):
    """Correlation root shared by future intelligence artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    causation_id: str = Field(min_length=1)
    decision_id: str | None = None


class VerificationMetadata(BaseModel):
    """Auditable builder/verifier identity separation."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    artifact_id: str = Field(min_length=1)
    builder_agent_id: str = Field(min_length=1)
    verifier_agent_id: str = Field(min_length=1)
    independent_verification_required: bool = True

    @model_validator(mode="after")
    def _enforce_separation(self) -> VerificationMetadata:
        if (
            self.independent_verification_required
            and self.builder_agent_id == self.verifier_agent_id
        ):
            raise ValueError("builder_agent_id and verifier_agent_id must differ")
        return self


__all__ = ["TraceContext", "VerificationMetadata"]
