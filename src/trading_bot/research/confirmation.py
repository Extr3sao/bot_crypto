"""Confirmation Protocol V0.2.1.

V0.2.1 §17: Confirmation workflow (DISCOVERY_PASS → CANDIDATE_FROZEN → ... → CONFIRMED/REJECTED)
V0.2.1 §18: Exact candidate confirmation (hash match)
V0.2.1 §19: Disjoint window enforcement
V0.2.1 §20: Operational confirmation demo
V0.2.1 §21: Prospective confirmation flow
V0.2.1 §22: Campaign exhaustion
V0.2.1 §23: Campaign autonomy
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

from .evidence import EvidenceRecord

try:
    from trading_agent.core.models_v02 import (
        CampaignStatus,
        CandidateManifest,
        DatasetWindow,
        new_id,
        sha256_hex,
    )
except ImportError:
    # Fallback: define minimal local versions
    from dataclasses import dataclass, field
    from typing import Any, Literal

    def sha256_hex(data: str) -> str:
        import hashlib
        return hashlib.sha256(data.encode('utf-8')).hexdigest()

    def new_id(prefix: str = "") -> str:
        import uuid
        uid = uuid.uuid4().hex[:12]
        return f"{prefix}-{uid}" if prefix else uid

    CampaignStatus = str  # type: ignore

    @dataclass(frozen=True, slots=True)
    class CandidateManifest:  # type: ignore
        experiment_id: str = ""
        hypothesis: str = ""
        mechanism: str = ""
        strategy_name: str = ""
        strategy_version: str = ""
        entry_rules: dict = field(default_factory=dict)
        exit_rules: dict = field(default_factory=dict)
        stop_rules: dict = field(default_factory=dict)
        code_hash: str = ""
        config_hash: str = ""
        bundle_hash_val: str = ""
        dataset_policy: dict = field(default_factory=dict)
        status: str = "DRAFT"
        def compute_bundle_hash(self) -> str:
            return sha256_hex(f"{self.code_hash}:{self.config_hash}")
        def verify_integrity(self) -> bool:
            return self.bundle_hash_val == self.compute_bundle_hash()

    @dataclass(frozen=True, slots=True)
    class DatasetWindow:  # type: ignore
        window_id: str = ""
        symbol: str = ""
        timeframe: str = "5m"
        start_ts: int = 0
        end_ts: int = 0
        candle_count: int = 0
        def overlaps(self, other: DatasetWindow) -> bool:
            if self.symbol != other.symbol:
                return False
            return self.start_ts < other.end_ts and other.start_ts < self.end_ts


# ---------------------------------------------------------------------------
# Confirmation States
# ---------------------------------------------------------------------------

ConfirmationState = Literal[
    "DISCOVERY_PASS",
    "CANDIDATE_FROZEN",
    "WAITING_CONFIRMATION_DATA",
    "CONFIRMATION_READY",
    "RUNNING_CONFIRMATION",
    "AUDITING_CONFIRMATION",
    "CONFIRMED",
    "CONFIRMATION_REJECTED",
    "NOT_CONFIRMATION_INVALIDATED",
    "REJECT_WINDOW_OVERLAP",
]


@dataclass(frozen=True, slots=True)
class FrozenCandidate:
    """Exact frozen candidate for confirmation.

    V0.2.1 §18: Must match exactly during confirmation.
    """

    candidate_id: str = ""
    experiment_id: str = ""
    discovery_bundle_hash: str = ""
    source_code: str = ""
    code_hash: str = ""
    config_hash: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    costs: dict[str, float] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    universe: list[str] = field(default_factory=list)
    timeframe: str = "5m"
    execution_assumptions_hash: str = ""
    frozen_at: float = field(default_factory=time.time)

    def compute_bundle_hash(self) -> str:
        """Compute bundle hash from all components."""
        parts = [
            self.code_hash,
            self.config_hash,
            str(sorted(self.params.items())),
            str(sorted(self.costs.items())),
            str(sorted(self.risk.items())),
            str(sorted(self.universe)),
            self.timeframe,
            self.execution_assumptions_hash,
        ]
        return sha256_hex(":".join(parts))

    def verify_exact_match(self, other: FrozenCandidate) -> bool:
        """Verify two candidates are identical (V0.2.1 §18)."""
        return (
            self.code_hash == other.code_hash
            and self.config_hash == other.config_hash
            and self.params == other.params
            and self.costs == other.costs
            and self.risk == other.risk
            and self.universe == other.universe
            and self.timeframe == other.timeframe
            and self.execution_assumptions_hash == other.execution_assumptions_hash
        )


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    """Result of the confirmation workflow."""

    confirmation_id: str = ""
    state: ConfirmationState = "DISCOVERY_PASS"
    candidate: FrozenCandidate | None = None
    discovery_window: DatasetWindow | None = None
    confirmation_window: DatasetWindow | None = None
    confirmed_metrics: dict[str, Any] = field(default_factory=dict)
    hash_match: bool = False
    disjoint_valid: bool = False
    evidence: EvidenceRecord | None = None
    reason: str = ""
    completed_at: float = 0.0

    @property
    def is_confirmed(self) -> bool:
        return self.state == "CONFIRMED"

    @property
    def is_rejected(self) -> bool:
        return self.state in (
            "CONFIRMATION_REJECTED",
            "NOT_CONFIRMATION_INVALIDATED",
            "REJECT_WINDOW_OVERLAP",
        )


@dataclass
class CampaignQueue:
    """Campaign queue with exhaustion tracking.

    V0.2.1 §22-23: Campaign exhaustion and autonomy.
    Mutable: pointer and completed change during execution.
    """

    campaign_id: str = ""
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    pointer: int = 0
    completed: list[str] = field(default_factory=list)
    exhausted: bool = False

    def __post_init__(self) -> None:
        if not self.hypotheses and not self.exhausted:
            self.exhausted = True

    @property
    def current_hypothesis(self) -> dict[str, Any] | None:
        if self.pointer < len(self.hypotheses):
            return self.hypotheses[self.pointer]
        return None

    @property
    def has_more(self) -> bool:
        return self.pointer < len(self.hypotheses)

    def advance(self) -> None:
        """Advance pointer after rejection."""
        self.completed.append(str(self.pointer))
        self.pointer += 1
        if self.pointer >= len(self.hypotheses):
            self.exhausted = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "pointer": self.pointer,
            "total_hypotheses": len(self.hypotheses),
            "completed": self.completed,
            "exhausted": self.exhausted,
        }


class ConfirmationProtocol:
    """Manages the confirmation workflow.

    V0.2.1 §17-23: Complete confirmation pipeline.
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger("confirmation_protocol")

    def freeze_candidate(
        self,
        candidate: FrozenCandidate,
        discovery_window: DatasetWindow,
    ) -> FrozenCandidate:
        """Freeze candidate after discovery pass.

        V0.2.1 §18: Exact candidate snapshot.
        """
        self._log.info(
            "confirmation.candidate_frozen",
            candidate_id=candidate.candidate_id,
            code_hash=candidate.code_hash[:16],
        )
        return candidate

    def validate_disjoint_windows(
        self,
        discovery_window: DatasetWindow,
        confirmation_window: DatasetWindow,
    ) -> tuple[bool, str]:
        """Validate that windows are strictly disjoint.

        V0.2.1 §19: No overlap allowed.
        """
        if discovery_window.overlaps(confirmation_window):
            msg = (
                f"REJECT_WINDOW_OVERLAP: Discovery {discovery_window.window_id} "
                f"({discovery_window.start_ts}-{discovery_window.end_ts}) overlaps "
                f"Confirmation {confirmation_window.window_id} "
                f"({confirmation_window.start_ts}-{confirmation_window.end_ts})"
            )
            self._log.warning("confirmation.window_overlap", msg=msg)
            return False, msg
        return True, "Windows are disjoint"

    def validate_exact_candidate(
        self,
        frozen: FrozenCandidate,
        confirmation_candidate: FrozenCandidate,
    ) -> tuple[bool, str]:
        """Validate that confirmation uses EXACT same candidate.

        V0.2.1 §18: discovery_bundle_hash == confirmation_bundle_hash
        Must match: strategy code, params, costs, risk, universe,
        timeframe, execution assumptions.
        """
        if not frozen.verify_exact_match(confirmation_candidate):
            mismatches: list[str] = []
            if frozen.code_hash != confirmation_candidate.code_hash:
                mismatches.append("code_hash")
            if frozen.config_hash != confirmation_candidate.config_hash:
                mismatches.append("config_hash")
            if frozen.params != confirmation_candidate.params:
                mismatches.append("params")
            if frozen.costs != confirmation_candidate.costs:
                mismatches.append("costs")
            if frozen.universe != confirmation_candidate.universe:
                mismatches.append("universe")
            if frozen.timeframe != confirmation_candidate.timeframe:
                mismatches.append("timeframe")
            if frozen.execution_assumptions_hash != confirmation_candidate.execution_assumptions_hash:
                mismatches.append("execution_assumptions")

            msg = f"NOT_CONFIRMATION_INVALIDATED: Mismatched fields: {', '.join(mismatches)}"
            self._log.warning("confirmation.candidate_mismatch", msg=msg)
            return False, msg

        self._log.info("confirmation.candidate_verified")
        return True, "Candidate matches exactly"

    def run_confirmation(
        self,
        frozen_candidate: FrozenCandidate,
        confirmation_candidate: FrozenCandidate,
        discovery_window: DatasetWindow,
        confirmation_window: DatasetWindow,
        confirmation_metrics: dict[str, Any] | None = None,
    ) -> ConfirmationResult:
        """Execute the full confirmation workflow.

        V0.2.1 §17: Complete state machine.
        """
        confirmation_id = new_id("CONF")

        # Step 1: Validate disjoint windows
        disjoint_ok, disjoint_msg = self.validate_disjoint_windows(
            discovery_window, confirmation_window
        )
        if not disjoint_ok:
            return ConfirmationResult(
                confirmation_id=confirmation_id,
                state="REJECT_WINDOW_OVERLAP",
                candidate=frozen_candidate,
                discovery_window=discovery_window,
                confirmation_window=confirmation_window,
                disjoint_valid=False,
                reason=disjoint_msg,
            )

        # Step 2: Validate exact candidate
        hash_ok, hash_msg = self.validate_exact_candidate(
            frozen_candidate, confirmation_candidate
        )
        if not hash_ok:
            return ConfirmationResult(
                confirmation_id=confirmation_id,
                state="NOT_CONFIRMATION_INVALIDATED",
                candidate=frozen_candidate,
                discovery_window=discovery_window,
                confirmation_window=confirmation_window,
                hash_match=False,
                disjoint_valid=True,
                reason=hash_msg,
            )

        # Step 3: Run confirmation (placeholder — caller provides actual backtest)
        # In V0.2.1, this is called after the real backtest runs
        return ConfirmationResult(
            confirmation_id=confirmation_id,
            state="RUNNING_CONFIRMATION",
            candidate=frozen_candidate,
            discovery_window=discovery_window,
            confirmation_window=confirmation_window,
            hash_match=True,
            disjoint_valid=True,
        )

    def complete_confirmation(
        self,
        result: ConfirmationResult,
        audit_passed: bool,
        metrics: dict[str, Any] | None = None,
    ) -> ConfirmationResult:
        """Complete the confirmation with audit results."""
        if not result.hash_match:
            return ConfirmationResult(
                confirmation_id=result.confirmation_id,
                state="NOT_CONFIRMATION_INVALIDATED",
                candidate=result.candidate,
                discovery_window=result.discovery_window,
                confirmation_window=result.confirmation_window,
                hash_match=False,
                disjoint_valid=result.disjoint_valid,
                reason="Hash mismatch persisted",
            )

        if not result.disjoint_valid:
            return ConfirmationResult(
                confirmation_id=result.confirmation_id,
                state="REJECT_WINDOW_OVERLAP",
                candidate=result.candidate,
                discovery_window=result.discovery_window,
                confirmation_window=result.confirmation_window,
                hash_match=result.hash_match,
                disjoint_valid=False,
                reason="Window overlap persisted",
            )

        if audit_passed:
            return ConfirmationResult(
                confirmation_id=result.confirmation_id,
                state="CONFIRMED",
                candidate=result.candidate,
                discovery_window=result.discovery_window,
                confirmation_window=result.confirmation_window,
                confirmed_metrics=metrics or {},
                hash_match=True,
                disjoint_valid=True,
                completed_at=time.time(),
            )
        else:
            return ConfirmationResult(
                confirmation_id=result.confirmation_id,
                state="CONFIRMATION_REJECTED",
                candidate=result.candidate,
                discovery_window=result.discovery_window,
                confirmation_window=result.confirmation_window,
                hash_match=True,
                disjoint_valid=True,
                reason="Audit failed",
                completed_at=time.time(),
            )


__all__ = [
    "CampaignQueue",
    "ConfirmationProtocol",
    "ConfirmationResult",
    "ConfirmationState",
    "FrozenCandidate",
]
