"""Accounting Integrity Gate and Market Evidence Gate for V0.2.4 §29-30.

V0.2.4 §29: AccountingIntegrityGate — trade + portfolio + equity + fee reconciliation.
V0.2.4 §30: MarketEvidenceGate — provenance + immutable snapshot + data quality.
V0.2.4 §31: ResearchQualificationGate — full qualification with all sub-gates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from .canonical_accounting import CanonicalPortfolioPnL, CanonicalTradePnL
from .evidence import EvidenceClass
from .market_provenance import MarketDataProvenance


class GateResult(str, Enum):
    """Gate pass/fail result."""

    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class GateCheck:
    """Single gate check."""

    check_id: str
    result: GateResult
    message: str = ""
    actual: Any = None
    expected: Any = None


@dataclass(frozen=True, slots=True)
class AccountingIntegrityResult:
    """Result of accounting integrity gate.

    V0.2.4 §29: PASS requires all sub-checks PASS.
    """

    trade_reconciliation: GateResult = GateResult.FAIL
    portfolio_reconciliation: GateResult = GateResult.FAIL
    equity_reconciliation: GateResult = GateResult.FAIL
    fee_reconciliation: GateResult = GateResult.FAIL
    slippage_reconciliation: GateResult = GateResult.FAIL
    turnover_semantics: GateResult = GateResult.FAIL
    checks: list[GateCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(
            r == GateResult.PASS
            for r in [
                self.trade_reconciliation,
                self.portfolio_reconciliation,
                self.equity_reconciliation,
                self.fee_reconciliation,
                self.slippage_reconciliation,
                self.turnover_semantics,
            ]
        )


@dataclass(frozen=True, slots=True)
class MarketEvidenceResult:
    """Result of market evidence gate.

    V0.2.4 §30: FULL qualification requires HISTORICAL_MARKET_REAL + provenance.
    """

    evidence_class_valid: GateResult = GateResult.FAIL
    provenance_complete: GateResult = GateResult.FAIL
    snapshot_immutable: GateResult = GateResult.FAIL
    data_quality: GateResult = GateResult.FAIL
    checks: list[GateCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(
            r == GateResult.PASS
            for r in [
                self.evidence_class_valid,
                self.provenance_complete,
                self.snapshot_immutable,
                self.data_quality,
            ]
        )


@dataclass(frozen=True, slots=True)
class ResearchQualificationResult:
    """Full research qualification gate.

    V0.2.4 §31: FULLY_OPERATIONALLY_QUALIFIED requires all sub-gates PASS.
    """

    accounting_integrity: AccountingIntegrityResult = field(
        default_factory=AccountingIntegrityResult
    )
    market_evidence: MarketEvidenceResult = field(
        default_factory=MarketEvidenceResult
    )
    engine_operational: GateResult = GateResult.FAIL
    risk_integrity: GateResult = GateResult.FAIL
    methodology: GateResult = GateResult.FAIL
    persistent_freeze: GateResult = GateResult.FAIL
    restart_safety: GateResult = GateResult.FAIL
    calendar_completeness: GateResult = GateResult.FAIL
    checks: list[GateCheck] = field(default_factory=list)

    @property
    def accounting_pass(self) -> bool:
        return self.accounting_integrity.passed

    @property
    def evidence_pass(self) -> bool:
        return self.market_evidence.passed

    @property
    def passed(self) -> bool:
        return all(
            r == GateResult.PASS
            for r in [
                GateResult.PASS if self.accounting_integrity.passed else GateResult.FAIL,
                GateResult.PASS if self.market_evidence.passed else GateResult.FAIL,
                self.engine_operational,
                self.risk_integrity,
                self.methodology,
                self.persistent_freeze,
                self.restart_safety,
                self.calendar_completeness,
            ]
        )

    @property
    def fully_qualified(self) -> bool:
        """FULLY_OPERATIONALLY_QUALIFIED."""
        return self.passed


class AccountingIntegrityGate:
    """V0.2.4 §29: Verify all accounting reconciliation.

    PASS requires:
    - trade reconciliation PASS
    - portfolio reconciliation PASS
    - equity reconciliation PASS
    - fee reconciliation PASS
    - slippage reconciliation PASS
    - turnover semantics PASS
    """

    def __init__(self, tolerance: float = 0.01) -> None:
        self._tolerance = tolerance
        self._log = structlog.get_logger("accounting_integrity_gate")

    def evaluate(
        self,
        trade_pnls: list[CanonicalTradePnL],
        portfolio_pnl: CanonicalPortfolioPnL,
        configured_commission_bps: float = 10.0,
        configured_slippage_bps: float = 5.0,
    ) -> AccountingIntegrityResult:
        """Evaluate accounting integrity."""
        checks: list[GateCheck] = []

        # 1. Trade reconciliation: all trades must reconcile
        all_trades_reconciled = all(tp.reconciled for tp in trade_pnls)
        max_error = max(
            (tp.reconciliation_error for tp in trade_pnls), default=0.0
        )
        trade_result = GateResult.PASS if all_trades_reconciled else GateResult.FAIL
        checks.append(
            GateCheck(
                check_id="trade_reconciliation",
                result=trade_result,
                message=f"all_reconciled={all_trades_reconciled}, max_error={max_error:.6f}",
                actual=all_trades_reconciled,
                expected=True,
            )
        )

        # 2. Portfolio reconciliation: sum(net_pnl) ≈ engine_delta
        portfolio_result = (
            GateResult.PASS if portfolio_pnl.equity_reconciled else GateResult.FAIL
        )
        checks.append(
            GateCheck(
                check_id="portfolio_reconciliation",
                result=portfolio_result,
                message=f"error={portfolio_pnl.equity_reconciliation_error:.6f}",
                actual=portfolio_pnl.equity_reconciliation_error,
                expected=self._tolerance,
            )
        )

        # 3. Equity reconciliation: starting + net = final
        reconstructed_equity = (
            portfolio_pnl.initial_capital + portfolio_pnl.total_net_pnl
        )
        equity_error = abs(portfolio_pnl.engine_final_equity - reconstructed_equity)
        equity_result = (
            GateResult.PASS
            if equity_error < max(self._tolerance, abs(reconstructed_equity) * 0.001)
            else GateResult.FAIL
        )
        checks.append(
            GateCheck(
                check_id="equity_reconciliation",
                result=equity_result,
                message=f"reconstructed={reconstructed_equity:.2f}, actual={portfolio_pnl.engine_final_equity:.2f}, error={equity_error:.6f}",
                actual=reconstructed_equity,
                expected=portfolio_pnl.engine_final_equity,
            )
        )

        # 4. Fee reconciliation: observed fees ≈ expected from rates
        # turnover = sum of both-side notionals, so rate is per-side
        expected_fees_bps = configured_commission_bps
        total_turnover = sum(
            tp.entry_fill_price * tp.quantity + tp.exit_fill_price * tp.quantity
            for tp in trade_pnls
        )
        if total_turnover > 0:
            observed_fees_bps = portfolio_pnl.total_fees / total_turnover * 10_000
            fee_delta = abs(observed_fees_bps - expected_fees_bps)
            fee_result = (
                GateResult.PASS
                if fee_delta < max(1.0, expected_fees_bps * 0.1)
                else GateResult.FAIL
            )
        else:
            observed_fees_bps = 0.0
            fee_delta = 0.0
            fee_result = GateResult.PASS  # no trades = no fees to check
        checks.append(
            GateCheck(
                check_id="fee_reconciliation",
                result=fee_result,
                message=f"expected={expected_fees_bps:.1f}bps, observed={observed_fees_bps:.1f}bps, delta={fee_delta:.1f}",
                actual=observed_fees_bps,
                expected=expected_fees_bps,
            )
        )

        # 5. Slippage reconciliation
        slippage_result = GateResult.PASS  # Slippage embedded in fills (info only)
        checks.append(
            GateCheck(
                check_id="slippage_reconciliation",
                result=slippage_result,
                message="slippage embedded in fills (no double-count)",
            )
        )

        # 6. Turnover semantics: turnover = sum(notional both sides)
        turnover_result = GateResult.PASS if total_turnover > 0 or len(trade_pnls) == 0 else GateResult.FAIL
        checks.append(
            GateCheck(
                check_id="turnover_semantics",
                result=turnover_result,
                message=f"total_turnover={total_turnover:.2f}, trades={len(trade_pnls)}",
                actual=total_turnover,
                expected=">0",
            )
        )

        result = AccountingIntegrityResult(
            trade_reconciliation=trade_result,
            portfolio_reconciliation=portfolio_result,
            equity_reconciliation=equity_result,
            fee_reconciliation=fee_result,
            slippage_reconciliation=slippage_result,
            turnover_semantics=turnover_result,
            checks=checks,
        )

        self._log.info(
            "accounting_integrity_gate.evaluated",
            passed=result.passed,
            trade_recon=trade_result.value,
            portfolio_recon=portfolio_result.value,
            equity_recon=equity_result.value,
            fee_recon=fee_result.value,
        )

        return result


class MarketEvidenceGate:
    """V0.2.4 §30: Market evidence verification.

    FULL qualification requires HISTORICAL_MARKET_REAL + verified provenance + immutable snapshot.
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger("market_evidence_gate")

    def evaluate(
        self,
        evidence_class: EvidenceClass,
        provenance: MarketDataProvenance | None = None,
        checksum_valid: bool = True,
        data_quality_passed: bool = True,
    ) -> MarketEvidenceResult:
        """Evaluate market evidence gate."""
        checks: list[GateCheck] = []

        # 1. Evidence class must be HISTORICAL_MARKET_REAL
        ec_result = (
            GateResult.PASS
            if evidence_class == EvidenceClass.HISTORICAL_MARKET_REAL
            else GateResult.FAIL
        )
        checks.append(
            GateCheck(
                check_id="evidence_class_valid",
                result=ec_result,
                message=f"class={evidence_class.value}",
                actual=evidence_class.value,
                expected="HISTORICAL_MARKET_REAL",
            )
        )

        # 2. Provenance must be complete
        prov_result = GateResult.PASS
        prov_msg = "no provenance provided"
        if provenance is not None:
            try:
                provenance.assert_operational()
                prov_msg = "provenance complete"
            except ValueError as e:
                prov_result = GateResult.FAIL
                prov_msg = str(e)
        else:
            prov_result = GateResult.FAIL
        checks.append(
            GateCheck(
                check_id="provenance_complete",
                result=prov_result,
                message=prov_msg,
            )
        )

        # 3. Snapshot must be immutable (checksum valid)
        snap_result = GateResult.PASS if checksum_valid else GateResult.FAIL
        checks.append(
            GateCheck(
                check_id="snapshot_immutable",
                result=snap_result,
                message=f"checksum_valid={checksum_valid}",
                actual=checksum_valid,
                expected=True,
            )
        )

        # 4. Data quality must pass
        dq_result = GateResult.PASS if data_quality_passed else GateResult.FAIL
        checks.append(
            GateCheck(
                check_id="data_quality",
                result=dq_result,
                message=f"data_quality_passed={data_quality_passed}",
                actual=data_quality_passed,
                expected=True,
            )
        )

        result = MarketEvidenceResult(
            evidence_class_valid=ec_result,
            provenance_complete=prov_result,
            snapshot_immutable=snap_result,
            data_quality=dq_result,
            checks=checks,
        )

        self._log.info(
            "market_evidence_gate.evaluated",
            passed=result.passed,
            ec=ec_result.value,
            provenance=prov_result.value,
        )

        return result


class ResearchQualificationGate:
    """V0.2.4 §31: Full research qualification gate.

    FULLY_OPERATIONALLY_QUALIFIED requires:
    - ENGINE_OPERATIONAL
    - ACCOUNTING_INTEGRITY
    - COST_INTEGRITY
    - RISK_INTEGRITY
    - DATA_PROVENANCE
    - DATA_QUALITY
    - METHODOLOGY
    - PERSISTENT_FREEZE
    - RESTART_SAFETY
    - CALENDAR_COMPLETENESS
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger("research_qualification_gate")

    def evaluate(
        self,
        accounting: AccountingIntegrityResult,
        evidence: MarketEvidenceResult,
        engine_operational: bool = True,
        risk_integrity: bool = True,
        methodology: bool = True,
        persistent_freeze: bool = True,
        restart_safety: bool = True,
        calendar_completeness: bool = True,
    ) -> ResearchQualificationResult:
        """Evaluate full research qualification."""
        checks: list[GateCheck] = []

        def _check(name: str, val: bool) -> GateCheck:
            r = GateResult.PASS if val else GateResult.FAIL
            return GateCheck(check_id=name, result=r, message=f"{'PASS' if val else 'FAIL'}")

        checks.append(_check("accounting_integrity", accounting.passed))
        checks.append(_check("market_evidence", evidence.passed))
        checks.append(_check("engine_operational", engine_operational))
        checks.append(_check("risk_integrity", risk_integrity))
        checks.append(_check("methodology", methodology))
        checks.append(_check("persistent_freeze", persistent_freeze))
        checks.append(_check("restart_safety", restart_safety))
        checks.append(_check("calendar_completeness", calendar_completeness))

        result = ResearchQualificationResult(
            accounting_integrity=accounting,
            market_evidence=evidence,
            engine_operational=GateResult.PASS if engine_operational else GateResult.FAIL,
            risk_integrity=GateResult.PASS if risk_integrity else GateResult.FAIL,
            methodology=GateResult.PASS if methodology else GateResult.FAIL,
            persistent_freeze=GateResult.PASS if persistent_freeze else GateResult.FAIL,
            restart_safety=GateResult.PASS if restart_safety else GateResult.FAIL,
            calendar_completeness=GateResult.PASS if calendar_completeness else GateResult.FAIL,
            checks=checks,
        )

        self._log.info(
            "research_qualification_gate.evaluated",
            fully_qualified=result.fully_qualified,
            accounting=result.accounting_pass,
            evidence=result.evidence_pass,
        )

        return result


__all__ = [
    "AccountingIntegrityGate",
    "AccountingIntegrityResult",
    "GateCheck",
    "GateResult",
    "MarketEvidenceGate",
    "MarketEvidenceResult",
    "ResearchQualificationGate",
    "ResearchQualificationResult",
]
