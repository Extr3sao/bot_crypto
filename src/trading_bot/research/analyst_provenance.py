"""CAP-003 — analyst provenance: what exactly produced each sealed decision.

CAP-002 shipped ``model_id = freebuff-agent-in-context`` and nothing else.  That
is enough to *demo* a pilot, but it is not enough to build a scientific dataset:
after 300 predictions we would not know what actually produced them.  This module
freezes the missing reproducibility surface as a single immutable record.

The record is descriptive metadata, never a signal: it does not change the
frozen analyst prompt (:mod:`trading_bot.research.market_analyst_v1`), the
output schema, the decision, or any measured outcome.  CAP-003 refuses to append
a decision to the real ledger unless this record is complete; CAP-002 artefacts
are left untouched and are simply *not* counted as campaign observations.

``temperature`` is a string on purpose.  A client that does not expose sampling
parameters must say so honestly (``"NOT_EXPOSED"``) instead of inventing a
number that would make the dataset look more reproducible than it is.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

__all__ = [
    "FEATURE_VERSION",
    "NOT_EXPOSED",
    "PROVENANCE_FIELDS",
    "PROVENANCE_VERSION",
    "SCHEMA_VERSION",
    "AnalystProvenance",
    "provenance_digest",
    "provenance_missing",
]

PROVENANCE_VERSION = "ANALYST_PROVENANCE_V1"

#: Version of the *frozen* analyst output schema captured in provenance.
SCHEMA_VERSION = "MARKET_ANALYST_OUTPUT_V1"

#: Version of the deterministic feature builder (real snapshot contract).
FEATURE_VERSION = "REAL_MARKET_CONTEXT_V1"

#: Honest placeholder for a sampling parameter the client does not expose.
NOT_EXPOSED = "NOT_EXPOSED"

#: Every field must be present and non-blank for a decision to be campaign-legal.
PROVENANCE_FIELDS: tuple[str, ...] = (
    "analyst_id",
    "prompt_version",
    "prompt_digest",
    "model",
    "provider",
    "temperature",
    "schema_version",
    "feature_version",
    "dataset",
)


@dataclass(frozen=True, slots=True)
class AnalystProvenance:
    """The immutable identity of one analyst run configuration."""

    analyst_id: str
    prompt_version: str
    prompt_digest: str
    model: str
    provider: str
    temperature: str
    schema_version: str
    feature_version: str
    dataset: str

    def to_dict(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}

    def digest(self) -> str:
        return provenance_digest(self.to_dict())

    def missing(self) -> list[str]:
        return provenance_missing(self.to_dict())


def provenance_missing(payload: Mapping[str, Any]) -> list[str]:
    """Provenance fields that are absent or blank (``[]`` == complete)."""
    missing: list[str] = []
    for field in PROVENANCE_FIELDS:
        value = payload.get(field)
        if value is None or not str(value).strip():
            missing.append(field)
    return missing


def provenance_digest(payload: Mapping[str, Any]) -> str:
    """Deterministic digest of a provenance record (no hidden fields)."""
    text = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
