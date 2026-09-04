"""Agent manifest contract for the multi-agent foundation."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import AgentCapability, AgentLifecycleState, AgentRole, ForbiddenAction


class AgentManifest(BaseModel):
    """Versioned identity and declared scope of one agent implementation."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    role: AgentRole
    description: str = Field(min_length=1)
    capabilities: frozenset[AgentCapability] = Field(default_factory=frozenset)
    input_contracts: tuple[str, ...] = ()
    output_contracts: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    forbidden_actions: frozenset[ForbiddenAction] = Field(default_factory=frozenset)
    lifecycle_state: AgentLifecycleState = AgentLifecycleState.DRAFT
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @field_validator(
        "input_contracts", "output_contracts", "allowed_tools", mode="before"
    )
    @classmethod
    def _reject_empty_names(cls, value: object) -> object:
        if isinstance(value, (tuple, list)) and any(not item for item in value):
            raise ValueError("contract and tool names must be non-empty")
        return value


__all__ = ["AgentManifest"]
