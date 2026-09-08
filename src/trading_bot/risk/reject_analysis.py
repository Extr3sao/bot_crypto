"""Risk-reject analysis ledger — HEALTH x RISK analysis contract (Track F).

PORTFOLIO-AND-RUNTIME-INTEGRATION-01. Purely observational: callers who
already observe a ``RiskCheck(approved=False)`` append a record here. The
ledger never relaxes, configures, or wraps ``RiskManager`` — it is evidence
for a future analysis distinguishing

- ``GOOD_CANDIDATE_BLOCKED_BY_RISK``: shadow outcome later shows the rejected
  candidate would have performed, from
- ``LOW_QUALITY_CANDIDATE_CORRECTLY_BLOCKED``: shadow outcome confirms the
  block.

Shadow results may be attached later, once a shadow campaign produces them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "RejectClassification",
    "RiskRejectLedger",
    "RiskRejectRecord",
    "ShadowOutcome",
]


class RejectClassification(StrEnum):
    GOOD_CANDIDATE_BLOCKED_BY_RISK = "GOOD_CANDIDATE_BLOCKED_BY_RISK"
    LOW_QUALITY_CANDIDATE_CORRECTLY_BLOCKED = "LOW_QUALITY_CANDIDATE_CORRECTLY_BLOCKED"
    UNCLASSIFIED = "UNCLASSIFIED"


@dataclass(frozen=True, slots=True)
class ShadowOutcome:
    """Observational shadow result for a rejected candidate."""

    expectancy: float
    profit_factor: float
    sample_size: int

    def __post_init__(self) -> None:
        if self.sample_size <= 0:
            raise ValueError("shadow outcome sample_size must be > 0")


@dataclass(frozen=True, slots=True)
class RiskRejectRecord:
    """One observed risk REJECT with full context for later classification."""

    strategy_id: str
    asset: str
    timeframe: str
    regime: str
    health_state: str
    correlation_state: str
    risk_reason: str
    blocked_by: str
    signal_summary: dict[str, Any] = field(default_factory=dict)
    recorded_at: str = ""  # wall clock = metadata only
    shadow: ShadowOutcome | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "regime": self.regime,
            "health_state": self.health_state,
            "correlation_state": self.correlation_state,
            "risk": {"reason": self.risk_reason, "blocked_by": self.blocked_by},
            "signal_summary": dict(self.signal_summary),
            "recorded_at": self.recorded_at,
            "shadow": (
                None
                if self.shadow is None
                else {
                    "expectancy": self.shadow.expectancy,
                    "profit_factor": self.shadow.profit_factor,
                    "sample_size": self.shadow.sample_size,
                }
            ),
            "classification": classify_reject(self).value,
            "read_only": True,
        }


# Pre-declared deterministic thresholds for classification. A shadow outcome
# with positive expectancy and PF > 1 means the block may have cost
# opportunity; anything else confirms the block.
CLASSIFY_MIN_SHADOW_N: int = 20


def classify_reject(record: RiskRejectRecord) -> RejectClassification:
    """Classify one record; insufficient shadow evidence stays UNCLASSIFIED."""
    shadow = record.shadow
    if shadow is None or shadow.sample_size < CLASSIFY_MIN_SHADOW_N:
        return RejectClassification.UNCLASSIFIED
    if shadow.expectancy > 0.0 and shadow.profit_factor > 1.0:
        return RejectClassification.GOOD_CANDIDATE_BLOCKED_BY_RISK
    return RejectClassification.LOW_QUALITY_CANDIDATE_CORRECTLY_BLOCKED


@dataclass
class RiskRejectLedger:
    """Append-only observational ledger of risk rejects (read-only export)."""

    _records: list[RiskRejectRecord] = field(default_factory=list)

    def record_reject(
        self,
        *,
        strategy_id: str,
        asset: str,
        timeframe: str,
        regime: str,
        health_state: str,
        correlation_state: str,
        risk_reason: str,
        blocked_by: str,
        signal_summary: dict[str, Any] | None = None,
        recorded_at: str = "",
    ) -> RiskRejectRecord:
        """Append one observed reject (callers must not mutate RiskManager)."""
        record = RiskRejectRecord(
            strategy_id=strategy_id,
            asset=asset,
            timeframe=timeframe,
            regime=regime,
            health_state=health_state,
            correlation_state=correlation_state,
            risk_reason=risk_reason,
            blocked_by=blocked_by,
            signal_summary=dict(signal_summary or {}),
            recorded_at=recorded_at,
        )
        self._records.append(record)
        return record

    def attach_shadow(self, index: int, shadow: ShadowOutcome) -> RiskRejectRecord:
        """Attach a later shadow outcome to a recorded reject (returns the
        updated immutable record)."""
        original = self._records[index]
        updated = RiskRejectRecord(
            strategy_id=original.strategy_id,
            asset=original.asset,
            timeframe=original.timeframe,
            regime=original.regime,
            health_state=original.health_state,
            correlation_state=original.correlation_state,
            risk_reason=original.risk_reason,
            blocked_by=original.blocked_by,
            signal_summary=original.signal_summary,
            recorded_at=original.recorded_at,
            shadow=shadow,
        )
        self._records[index] = updated
        return updated

    def records(self) -> tuple[RiskRejectRecord, ...]:
        return tuple(self._records)

    def classify_index(self, index: int) -> RejectClassification:
        """Deterministic classification of one recorded reject."""
        return classify_reject(self._records[index])

    def classification_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {c.value: 0 for c in RejectClassification}
        for record in self._records:
            counts[classify_reject(record).value] += 1
        return counts

    def to_dicts(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._records]
