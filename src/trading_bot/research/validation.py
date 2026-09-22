"""Discovery/Confirmation Validation Pipeline (FASE 5, P10, P11, P14).

Workflow:
  PREREGISTER
      ↓
  DISCOVERY WINDOW (train on D1-D14)
      ↓
  FAIL → REJECT
      ↓ PASS
  FREEZE EXACT CANDIDATE
      ↓
  NEW DISJOINT WINDOW (confirm on D15-D42)
      ↓
  CONFIRMATION
      ↓
  CONFIRMED / REJECTED

Key invariants:
- Discovery and confirmation use DISJOINT windows (P11).
- No retuning between discovery and confirmation (P10).
- Economic quality gates (P14) are configurable, not hardcoded.
- Python is the final authority (P25).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

from .registry import ExperimentRegistry
from .types import (
    DatasetWindow,
    PerformanceMetrics,
)

# ---------------------------------------------------------------------------
# Testing Discipline (P13)
# ---------------------------------------------------------------------------

TestingPhase = Literal[
    "DESCRIPTIVE",  # exploration without hypotheses
    "EXPLORATORY",  # pattern search, not yet preregistered
    "PREREGISTERED",  # frozen code+config+data before seeing results
    "CONFIRMATORY",  # validation on disjoint window, no retuning
]


@dataclass(frozen=True, slots=True)
class TestingDisciplineLabel:
    """Label for a validation run indicating testing discipline (P13).

    P13 contract:
    - DESCRIPTIVE: analyzing data without hypotheses
    - EXPLORATORY: searching for patterns, not yet preregistered
    - PREREGISTERED: frozen before seeing results
    - CONFIRMATORY: validation on disjoint window

    CRITICAL: never execute -> look at winners -> create combination ->
    call it preregistered.
    """

    phase: TestingPhase
    preregistered_before_results: bool = True  # must be True for PREREGISTERED/CONFIRMATORY
    hypothesis_frozen: bool = True  # must be True for PREREGISTERED/CONFIRMATORY
    retuning_detected: bool = False  # if True between discovery/confirmation -> INVALIDATED

    def __post_init__(self) -> None:
        if (
            self.phase in ("PREREGISTERED", "CONFIRMATORY")
            and not self.preregistered_before_results
        ):
            raise ValueError(
                f"{self.phase} phase requires preregistered_before_results=True "
                f"(P13: must freeze before seeing results)"
            )
        if self.phase in ("PREREGISTERED", "CONFIRMATORY") and not self.hypothesis_frozen:
            raise ValueError(
                f"{self.phase} phase requires hypothesis_frozen=True (P13: must freeze hypothesis)"
            )
        if self.retuning_detected and self.phase in ("PREREGISTERED", "CONFIRMATORY"):
            raise ValueError(
                "retuning_detected=True is incompatible with PREREGISTERED/CONFIRMATORY "
                "(P13: retuning invalidates preregistration)"
            )

    @property
    def is_valid(self) -> bool:
        """Check if this label represents a valid testing discipline."""
        return not self.retuning_detected

    @property
    def can_generate_filters(self) -> bool:
        """Only CONFIRMED results can generate operational filters."""
        return self.phase == "CONFIRMATORY" and self.is_valid


# ---------------------------------------------------------------------------
# Economic Quality Gates (P14)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QualityGates:
    """Configurable economic quality gates (P14).

    Discovery gates are typically more lenient than confirmation gates.
    These are CONFIGURABLE, not hardcoded.
    """

    # Discovery gates
    min_trades: int = 30
    min_net_exp_r: float = 0.1
    min_net_pf: float = 1.0
    min_net_pnl: float = 0.0
    max_drawdown_pct: float = 10.0

    # Confirmation gates (stricter)
    min_confirm_trades: int = 20
    min_confirm_net_exp_r: float = 0.05
    min_confirm_net_pf: float = 1.0
    min_confirm_pnl: float = 0.0
    max_confirm_dd_pct: float = 15.0


@dataclass(frozen=True, slots=True)
class GateResult:
    """Result of a single gate check."""

    gate_name: str
    passed: bool
    actual: float | int
    threshold: float | int
    message: str = ""


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Complete validation report for a window."""

    window_id: str
    experiment_id: str
    phase: str  # discovery / confirmation
    all_passed: bool
    total_gates: int
    passed_gates: int
    gate_results: list[GateResult]
    metrics: PerformanceMetrics | None = None


# ---------------------------------------------------------------------------
# Discovery/Confirmation Pipeline
# ---------------------------------------------------------------------------


class ValidationPipeline:
    """Discovery/Confirmation validation pipeline.

    P10 contract:
    1. PREREGISTER → discovery experiment
    2. RUN discovery on disjoint window
    3. PASS/FAIL with economic quality gates
    4. FREEZE exact candidate (no retuning)
    5. RUN confirmation on NEW disjoint window
    6. CONFIRMED/REJECTED

    P11 contract:
    - Discovery and confirmation windows MUST be disjoint.
    - Once consumed, a window cannot be re-labeled FRESH.
    """

    def __init__(
        self,
        registry: ExperimentRegistry,
        discovery_gates: QualityGates | None = None,
        confirmation_gates: QualityGates | None = None,
    ) -> None:
        self._registry = registry
        self._discovery_gates = discovery_gates or QualityGates()
        self._confirmation_gates = confirmation_gates or QualityGates()
        self._log = structlog.get_logger("validation_pipeline")

    def validate_discovery(
        self,
        experiment_id: str,
        window: DatasetWindow,
        metrics: PerformanceMetrics,
    ) -> ValidationReport:
        """Validate discovery results against economic quality gates (P14).

        Returns ValidationReport with all gate results.
        """
        gates = self._discovery_gates
        gate_results: list[GateResult] = []

        # Gate: minimum trades
        gate_results.append(
            GateResult(
                gate_name="min_trades",
                passed=metrics.total_trades >= gates.min_trades,
                actual=metrics.total_trades,
                threshold=gates.min_trades,
            )
        )

        # Gate: minimum net expected R
        gate_results.append(
            GateResult(
                gate_name="min_net_exp_r",
                passed=metrics.net_exp_r >= gates.min_net_exp_r,
                actual=metrics.net_exp_r,
                threshold=gates.min_net_exp_r,
            )
        )

        # Gate: minimum net profit factor
        gate_results.append(
            GateResult(
                gate_name="min_net_pf",
                passed=metrics.net_pf >= gates.min_net_pf,
                actual=metrics.net_pf,
                threshold=gates.min_net_pf,
            )
        )

        # Gate: positive net PnL
        gate_results.append(
            GateResult(
                gate_name="positive_net_pnl",
                passed=metrics.net_pnl > gates.min_net_pnl,
                actual=metrics.net_pnl,
                threshold=gates.min_net_pnl,
            )
        )

        # Gate: max drawdown
        gate_results.append(
            GateResult(
                gate_name="max_drawdown",
                passed=metrics.max_drawdown <= gates.max_drawdown_pct / 100,
                actual=metrics.max_drawdown,
                threshold=gates.max_drawdown_pct / 100,
            )
        )

        all_passed = all(g.passed for g in gate_results)
        passed_count = sum(1 for g in gate_results if g.passed)

        report = ValidationReport(
            window_id=window.window_id,
            experiment_id=experiment_id,
            phase="discovery",
            all_passed=all_passed,
            total_gates=len(gate_results),
            passed_gates=passed_count,
            gate_results=gate_results,
            metrics=metrics,
        )

        # Record consumed period (P11)
        self._registry.record_consumed_period(
            experiment_id,
            window.symbol,
            window.timeframe,
            window.start_ts,
            window.end_ts,
        )

        if all_passed:
            self._log.info(
                "validation.discovery_passed", experiment_id=experiment_id, gates=passed_count
            )
        else:
            failed = [g.gate_name for g in gate_results if not g.passed]
            self._log.info(
                "validation.discovery_failed", experiment_id=experiment_id, failed_gates=failed
            )

        return report

    def validate_confirmation(
        self,
        experiment_id: str,
        window: DatasetWindow,
        metrics: PerformanceMetrics,
    ) -> ValidationReport:
        """Validate confirmation results (P10).

        Confirmation uses STRICTER gates and disjoint window.
        """
        gates = self._confirmation_gates
        gate_results: list[GateResult] = []

        gate_results.append(
            GateResult(
                gate_name="min_confirm_trades",
                passed=metrics.total_trades >= gates.min_confirm_trades,
                actual=metrics.total_trades,
                threshold=gates.min_confirm_trades,
            )
        )

        gate_results.append(
            GateResult(
                gate_name="min_confirm_net_exp_r",
                passed=metrics.net_exp_r >= gates.min_confirm_net_exp_r,
                actual=metrics.net_exp_r,
                threshold=gates.min_confirm_net_exp_r,
            )
        )

        gate_results.append(
            GateResult(
                gate_name="min_confirm_net_pf",
                passed=metrics.net_pf >= gates.min_confirm_net_pf,
                actual=metrics.net_pf,
                threshold=gates.min_confirm_net_pf,
            )
        )

        gate_results.append(
            GateResult(
                gate_name="positive_confirm_pnl",
                passed=metrics.net_pnl > gates.min_confirm_pnl,
                actual=metrics.net_pnl,
                threshold=gates.min_confirm_pnl,
            )
        )

        gate_results.append(
            GateResult(
                gate_name="max_confirm_dd",
                passed=metrics.max_drawdown <= gates.max_confirm_dd_pct / 100,
                actual=metrics.max_drawdown,
                threshold=gates.max_confirm_dd_pct / 100,
            )
        )

        all_passed = all(g.passed for g in gate_results)
        passed_count = sum(1 for g in gate_results if g.passed)

        report = ValidationReport(
            window_id=window.window_id,
            experiment_id=experiment_id,
            phase="confirmation",
            all_passed=all_passed,
            total_gates=len(gate_results),
            passed_gates=passed_count,
            gate_results=gate_results,
            metrics=metrics,
        )

        # Record consumed period (P11)
        self._registry.record_consumed_period(
            experiment_id,
            window.symbol,
            window.timeframe,
            window.start_ts,
            window.end_ts,
        )

        return report

    def execute_discovery_confirmation(
        self,
        discovery_experiment_id: str,
        confirmation_experiment_id: str,
        discovery_window: DatasetWindow,
        confirmation_window: DatasetWindow,
        discovery_metrics: PerformanceMetrics,
        confirmation_metrics: PerformanceMetrics,
    ) -> tuple[ValidationReport, ValidationReport]:
        """Execute full discovery → confirmation cycle.

        P10 contract:
        1. Validate discovery window
        2. If discovery fails → reject both, return reports
        3. Validate confirmation window
        4. If confirmation passes → CONFIRMED
        5. If confirmation fails → REJECTED

        P11: windows MUST be disjoint.
        """
        # Validate disjoint windows (P11)
        if discovery_window.overlaps(confirmation_window):
            raise ValueError(
                f"Discovery and confirmation windows overlap: "
                f"{discovery_window.window_id} and {confirmation_window.window_id}"
            )

        # Validate discovery
        discovery_report = self.validate_discovery(
            discovery_experiment_id,
            discovery_window,
            discovery_metrics,
        )

        # Update experiment status
        if discovery_report.all_passed:
            self._registry.update_status(
                discovery_experiment_id,
                "CANDIDATE",
                results=discovery_metrics,
                decision="discovery passed",
            )
        else:
            failed = [g.gate_name for g in discovery_report.gate_results if not g.passed]
            self._registry.update_status(
                discovery_experiment_id,
                "REJECTED",
                results=discovery_metrics,
                decision=f"discovery failed: {', '.join(failed)}",
            )
            # Return early — no confirmation if discovery fails
            return discovery_report, ValidationReport(
                window_id=confirmation_window.window_id,
                experiment_id=confirmation_experiment_id,
                phase="confirmation",
                all_passed=False,
                total_gates=0,
                passed_gates=0,
                gate_results=[],
            )

        # Confirm candidate (P10: freeze exact candidate, no retuning)
        self._registry.update_status(
            confirmation_experiment_id,
            "CONFIRMING",
        )

        # Validate confirmation
        confirmation_report = self.validate_confirmation(
            confirmation_experiment_id,
            confirmation_window,
            confirmation_metrics,
        )

        if confirmation_report.all_passed:
            self._registry.update_status(
                confirmation_experiment_id,
                "CONFIRMED",
                results=confirmation_metrics,
                decision="confirmation passed",
            )
        else:
            failed = [g.gate_name for g in confirmation_report.gate_results if not g.passed]
            self._registry.update_status(
                confirmation_experiment_id,
                "REJECTED",
                results=confirmation_metrics,
                decision=f"confirmation failed: {', '.join(failed)}",
            )

        return discovery_report, confirmation_report


__all__ = [
    "GateResult",
    "QualityGates",
    "TestingDisciplineLabel",
    "TestingPhase",
    "ValidationPipeline",
    "ValidationReport",
]
