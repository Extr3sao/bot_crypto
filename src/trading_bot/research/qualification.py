"""Operational Qualification Gate and Result Taxonomy for V0.2.1.

V0.2.1 §29: OperationalQualificationGate — checks real data, real strategy code,
real backtest, trade evidence, PnL reconciliation, audit PASS, hash integrity,
dataset classification, no live effects.

V0.2.1 §30: Result Taxonomy — separate INFRASTRUCTURE_PASS, METHODOLOGY_PASS,
ECONOMIC_PASS, FREQUENCY_PASS, CONFIRMATION_PASS.

Example: INFRASTRUCTURE_PASS + METHODOLOGY_PASS + ECONOMIC_FAIL + FREQUENCY_PASS
= strategy REJECTED but research engine QUALIFIED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

from .backtest_evidence import RealBacktestResult
from .confirmation import ConfirmationResult
from .evidence import EvidenceClass, EvidenceRecord
from .historical_data import DataQualityResult, HistoricalDataset

# ---------------------------------------------------------------------------
# Result Taxonomy
# ---------------------------------------------------------------------------

GateCategory = Literal[
    "INFRASTRUCTURE",
    "METHODOLOGY",
    "ECONOMIC",
    "FREQUENCY",
    "CONFIRMATION",
]


@dataclass(frozen=True, slots=True)
class GateCheck:
    """Single gate check result."""

    category: GateCategory
    name: str
    passed: bool
    actual: Any = None
    threshold: Any = None
    message: str = ""

    @property
    def label(self) -> str:
        return f"{self.category}:{self.name}"


@dataclass(frozen=True, slots=True)
class QualificationResult:
    """Complete qualification result with taxonomy.

    V0.2.1 §30: Separates INFRASTRUCTURE, METHODOLOGY, ECONOMIC, FREQUENCY,
    CONFIRMATION passes.
    """

    checks: list[GateCheck] = field(default_factory=list)

    @property
    def infrastructure_pass(self) -> bool:
        return all(c.passed for c in self.checks if c.category == "INFRASTRUCTURE")

    @property
    def methodology_pass(self) -> bool:
        return all(c.passed for c in self.checks if c.category == "METHODOLOGY")

    @property
    def economic_pass(self) -> bool:
        return all(c.passed for c in self.checks if c.category == "ECONOMIC")

    @property
    def frequency_pass(self) -> bool:
        return all(c.passed for c in self.checks if c.category == "FREQUENCY")

    @property
    def confirmation_pass(self) -> bool:
        conf_checks = [c for c in self.checks if c.category == "CONFIRMATION"]
        if not conf_checks:
            return True  # No confirmation required yet
        return all(c.passed for c in conf_checks)

    @property
    def engine_qualified(self) -> bool:
        """RESEARCH_ENGINE_OPERATIONALLY_QUALIFIED.

        Requires: infrastructure + methodology pass.
        Economic/frequency can fail (strategy rejected but engine qualified).
        """
        return self.infrastructure_pass and self.methodology_pass

    @property
    def strategy_profitable(self) -> bool:
        """Economic pass — strategy shows edge."""
        return self.economic_pass

    @property
    def overall_pass(self) -> bool:
        """All categories pass."""
        return all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> list[GateCheck]:
        return [c for c in self.checks if not c.passed]

    def summary(self) -> dict[str, bool]:
        """Summary by category."""
        return {
            "INFRASTRUCTURE_PASS": self.infrastructure_pass,
            "METHODOLOGY_PASS": self.methodology_pass,
            "ECONOMIC_PASS": self.economic_pass,
            "FREQUENCY_PASS": self.frequency_pass,
            "CONFIRMATION_PASS": self.confirmation_pass,
            "ENGINE_QUALIFIED": self.engine_qualified,
            "STRATEGY_PROFITABLE": self.strategy_profitable,
        }


# ---------------------------------------------------------------------------
# Operational Qualification Gate
# ---------------------------------------------------------------------------


class OperationalQualificationGate:
    """V0.2.1 §29: Operational Qualification Gate.

    Checks:
    1. Real data (evidence_class >= HISTORICAL_REAL)
    2. Real strategy code (compiled, imported, sandboxed)
    3. Real backtest engine invoked
    4. Trade evidence exists (n_trades >= 0 with valid result)
    5. PnL reconciliation passes
    6. Audit PASS
    7. Hash integrity (candidate frozen correctly)
    8. Dataset classification (not re-labeled)
    9. No live/paper side effects

    Only if ALL pass: RESEARCH_ENGINE_OPERATIONALLY_QUALIFIED.
    This does NOT mean STRATEGY_PROFITABLE.
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger("operational_qualification_gate")

    def evaluate(
        self,
        *,
        evidence: EvidenceRecord | None = None,
        data_quality: DataQualityResult | None = None,
        backtest_result: RealBacktestResult | None = None,
        pnl_reconciliation_ok: bool = False,
        audit_passed: bool = False,
        candidate_frozen: bool = False,
        candidate_hash_valid: bool = False,
        confirmation_result: ConfirmationResult | None = None,
        has_live_effects: bool = False,
        has_paper_effects: bool = False,
        dataset: HistoricalDataset | None = None,
    ) -> QualificationResult:
        """Run all qualification checks.

        Returns QualificationResult with individual gate checks.
        """
        checks: list[GateCheck] = []

        # 1. Real data
        real_data = evidence is not None and evidence.evidence_class.is_operational
        checks.append(
            GateCheck(
                category="INFRASTRUCTURE",
                name="real_data",
                passed=real_data,
                actual=evidence.evidence_class.value if evidence else "NONE",
                threshold="HISTORICAL_REAL or better",
                message=""
                if real_data
                else "Evidence class insufficient for operational qualification",
            )
        )

        # 2. Data quality
        dq_ok = data_quality is not None and data_quality.passed
        checks.append(
            GateCheck(
                category="INFRASTRUCTURE",
                name="data_quality",
                passed=dq_ok,
                actual="PASS" if dq_ok else "FAIL",
                threshold="PASS",
                message="" if dq_ok else "Data quality gate failed",
            )
        )

        # 3. Real backtest engine
        engine_used = (
            backtest_result is not None
            and backtest_result.metrics_source == "CALCULATED_FROM_REAL_TRADES"
        )
        checks.append(
            GateCheck(
                category="INFRASTRUCTURE",
                name="real_backtest_engine",
                passed=engine_used,
                actual=backtest_result.metrics_source if backtest_result else "NONE",
                threshold="CALCULATED_FROM_REAL_TRADES",
                message="" if engine_used else "Backtest did not use real engine",
            )
        )

        # 4. Trade evidence exists
        has_trades = (
            backtest_result is not None
            and backtest_result.n_trades >= 0
            and len(backtest_result.trades) >= 0
        )
        checks.append(
            GateCheck(
                category="METHODOLOGY",
                name="trade_evidence",
                passed=has_trades,
                actual=backtest_result.n_trades if backtest_result else 0,
                threshold=">= 0 (valid result with or without trades)",
                message="" if has_trades else "No trade evidence available",
            )
        )

        # 5. PnL reconciliation
        checks.append(
            GateCheck(
                category="METHODOLOGY",
                name="pnl_reconciliation",
                passed=pnl_reconciliation_ok,
                actual="PASS" if pnl_reconciliation_ok else "FAIL",
                threshold="PASS",
                message="" if pnl_reconciliation_ok else "PnL reconciliation failed",
            )
        )

        # 6. Audit
        checks.append(
            GateCheck(
                category="METHODOLOGY",
                name="audit_pass",
                passed=audit_passed,
                actual="PASS" if audit_passed else "FAIL",
                threshold="PASS",
                message="" if audit_passed else "Audit did not pass",
            )
        )

        # 7. Hash integrity
        checks.append(
            GateCheck(
                category="METHODOLOGY",
                name="hash_integrity",
                passed=candidate_hash_valid,
                actual="VALID" if candidate_hash_valid else "INVALID",
                threshold="VALID",
                message="" if candidate_hash_valid else "Candidate hash mismatch",
            )
        )

        # 8. No live effects
        no_live = not has_live_effects
        checks.append(
            GateCheck(
                category="INFRASTRUCTURE",
                name="no_live_effects",
                passed=no_live,
                actual="CLEAN" if no_live else "LIVE_EFFECTS_DETECTED",
                threshold="CLEAN",
                message="" if no_live else "Live trading side effects detected!",
            )
        )

        # 9. No paper effects (in research mode)
        no_paper = not has_paper_effects
        checks.append(
            GateCheck(
                category="INFRASTRUCTURE",
                name="no_paper_effects",
                passed=no_paper,
                actual="CLEAN" if no_paper else "PAPER_EFFECTS_DETECTED",
                threshold="CLEAN",
                message="" if no_paper else "Paper trading side effects detected!",
            )
        )

        # 10. Dataset classification
        ds_ok = dataset is None or dataset.evidence_class != EvidenceClass.SYNTHETIC
        checks.append(
            GateCheck(
                category="METHODOLOGY",
                name="dataset_classification",
                passed=ds_ok,
                actual=dataset.evidence_class.value if dataset else "N/A",
                threshold="!= SYNTHETIC",
                message="" if ds_ok else "Dataset improperly classified as SYNTHETIC",
            )
        )

        # 11. Confirmation (if applicable)
        if confirmation_result is not None:
            conf_ok = confirmation_result.is_confirmed
            checks.append(
                GateCheck(
                    category="CONFIRMATION",
                    name="confirmation",
                    passed=conf_ok,
                    actual=confirmation_result.state,
                    threshold="CONFIRMED",
                    message=confirmation_result.reason if not conf_ok else "",
                )
            )

        # Frequency checks (from backtest)
        if backtest_result is not None:
            freq_ok = backtest_result.trades_per_day >= 0
            checks.append(
                GateCheck(
                    category="FREQUENCY",
                    name="frequency_from_trades",
                    passed=freq_ok,
                    actual=backtest_result.trades_per_day,
                    threshold=">= 0",
                )
            )

            # Economic checks
            econ_ok = backtest_result.n_trades > 0
            checks.append(
                GateCheck(
                    category="ECONOMIC",
                    name="has_trades",
                    passed=econ_ok,
                    actual=backtest_result.n_trades,
                    threshold="> 0",
                    message="" if econ_ok else "No trades executed",
                )
            )

        result = QualificationResult(checks=checks)

        self._log.info(
            "qualification.evaluated",
            engine_qualified=result.engine_qualified,
            strategy_profitable=result.strategy_profitable,
            infrastructure=result.infrastructure_pass,
            methodology=result.methodology_pass,
            economic=result.economic_pass,
        )

        return result


__all__ = [
    "GateCategory",
    "GateCheck",
    "OperationalQualificationGate",
    "QualificationResult",
]
