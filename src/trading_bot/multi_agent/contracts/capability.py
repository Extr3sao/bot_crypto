"""Capability contracts for the multi-agent intelligence plane."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import AgentCapability


class DeclaredCapabilities(BaseModel):
    """Capabilities an agent declares for policy evaluation.

    Declarations are descriptive only; they never grant permissions. MA-0
    rejects capabilities that would cross the certified execution boundary.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    capabilities: frozenset[AgentCapability] = Field(default_factory=frozenset)


__all__ = ["DeclaredCapabilities"]
