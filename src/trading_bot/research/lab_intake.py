"""Strategy Lab intake — RESEARCH ONLY (Track E).

SHADOW-AND-LEGACY-VALIDATION-01. Contract for admitting strategy IDEAS into
the Strategy Lab pipeline:

    ExternalStrategyIdea -> StrategyCandidate -> specification
      -> (future) admission pipeline

Hard rules:

- No new candidate may enter PAPER (or any runtime) through this module:
  intake produces research artifacts and evidence references only.
- Orthogonality is REQUIRED: an idea must declare which existing family it
  is orthogonal to (or complement) — duplicates of SOL-LONG momentum-style
  copies are rejected at intake.
- Regime-first hypotheses are supported: an idea may target underserved
  regimes (RANGE, CORRECTION, HIGH_VOL, TRANSITION, BEAR, FUSED_CORRELATION)
  because the portfolio seeks complementary edges, not more of the same.
- Ex-ante specification BEFORE execution: candidates carry a frozen spec
  fingerprint; results can never rewrite it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "EXISTING_FAMILIES",
    "TARGET_REGIMES",
    "ExternalStrategyIdea",
    "IntakeDecision",
    "StrategyCandidate",
]


TARGET_REGIMES: tuple[str, ...] = (
    "RANGE",
    "CORRECTION",
    "HIGH_VOL",
    "TRANSITION",
    "BEAR",
    "FUSED_CORRELATION",
    "ANY",  # explicitly declared all-regime idea (must justify)
)

#: Current runtime strategy families the idea must be orthogonal against.
EXISTING_FAMILIES: tuple[str, ...] = (
    "momentum",
    "trend",
    "breakout",
    "mean_reversion",
    "volatility",
)

#: Research categories the checkpoint declares (orthogonal behavior sources).
RESEARCH_CATEGORIES: tuple[str, ...] = (
    "carry_funding",
    "relative_strength",
    "cross_sectional",
    "liquidity_flow",
    "volatility_structure",
    "session_time",
    "multi_timeframe_context",
)


class IntakeDecision(StrEnum):
    ACCEPTED_TO_LAB = "ACCEPTED_TO_LAB"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_NO_REGIME_HYPOTHESIS = "REJECTED_NO_REGIME_HYPOTHESIS"
    REJECTED_INCOMPLETE_SPEC = "REJECTED_INCOMPLETE_SPEC"


@dataclass(frozen=True, slots=True)
class ExternalStrategyIdea:
    """Raw idea from any allowed source (papers, repos, internal hypotheses)."""

    idea_id: str
    source: str  # e.g. "paper:doi", "repo:owner/name", "internal:hypothesis"
    title: str
    hypothesis: str  # regime-first statement of WHERE the edge may live
    research_category: str
    target_regimes: tuple[str, ...]
    proposed_assets: tuple[str, ...]
    proposed_timeframes: tuple[str, ...]
    orthogonal_to: tuple[str, ...]  # existing families it does NOT duplicate
    complement_of: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.research_category not in RESEARCH_CATEGORIES:
            raise ValueError(
                f"research_category must be one of {RESEARCH_CATEGORIES}, "
                f"got {self.research_category!r}"
            )
        bad = [r for r in self.target_regimes if r not in TARGET_REGIMES]
        if bad:
            raise ValueError(f"unknown target regimes: {bad}")
        if not self.hypothesis.strip():
            raise ValueError("hypothesis must be a non-empty regime-first statement")


@dataclass(frozen=True, slots=True)
class StrategyCandidate:
    """Spec-frozen research candidate (never a runtime artifact)."""

    candidate_id: str
    idea: ExternalStrategyIdea
    specification: dict[str, Any]
    spec_fingerprint: str
    status: str  # IntakeDecision of acceptance
    admitted_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "idea": {
                "idea_id": self.idea.idea_id,
                "source": self.idea.source,
                "title": self.idea.title,
                "research_category": self.idea.research_category,
                "target_regimes": list(self.idea.target_regimes),
                "orthogonal_to": list(self.idea.orthogonal_to),
            },
            "spec_fingerprint": self.spec_fingerprint,
            "status": self.status,
            "admitted_at_utc": self.admitted_at_utc,
        }


class StrategyLabIntake:
    """Intake gate: ideas in, spec-frozen candidates out (RESEARCH ONLY)."""

    def __init__(self) -> None:
        self._candidates: dict[str, StrategyCandidate] = {}

    @property
    def candidates(self) -> tuple[StrategyCandidate, ...]:
        return tuple(self._candidates.values())

    def submit(
        self,
        idea: ExternalStrategyIdea,
        specification: dict[str, Any],
        *,
        admitted_at_utc: str,
    ) -> tuple[IntakeDecision, StrategyCandidate | None]:
        """Evaluate an idea against the preregistered intake rules."""
        # RS-02: orthogonality is mandatory. An idea must declare at least
        # one existing family it is orthogonal to (or complements); a copy
        # of an existing family has nothing truthful to declare here.
        if not idea.orthogonal_to and not idea.complement_of:
            return IntakeDecision.REJECTED_DUPLICATE, None
        # RS-03: regime-first hypothesis support (at least one target).
        if not idea.target_regimes:
            return IntakeDecision.REJECTED_NO_REGIME_HYPOTHESIS, None
        # Ex-ante spec completeness.
        required = {"entry_rule", "exit_rule", "stop_rule", "sizing_rule"}
        if not required.issubset(specification):
            return IntakeDecision.REJECTED_INCOMPLETE_SPEC, None

        canonical = json.dumps(
            {"idea": idea.idea_id, "spec": specification, "regimes": list(idea.target_regimes)},
            sort_keys=True,
            separators=(",", ":"),
        )
        candidate = StrategyCandidate(
            candidate_id=f"lab:{hashlib.sha256(canonical.encode()).hexdigest()[:20]}",
            idea=idea,
            specification=dict(specification),
            spec_fingerprint=hashlib.sha256(canonical.encode()).hexdigest(),
            status=IntakeDecision.ACCEPTED_TO_LAB.value,
            admitted_at_utc=admitted_at_utc,
        )
        self._candidates[candidate.candidate_id] = candidate
        return IntakeDecision.ACCEPTED_TO_LAB, candidate
