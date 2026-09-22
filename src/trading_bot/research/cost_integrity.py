"""Cost Integrity System for V0.2.3 §6-9.

V0.2.3 §6: Fee invariants (bps conversion, no double count).
V0.2.3 §7: Slippage invariants (embedded vs explicit, never both).
V0.2.3 §8: Turnover reconciliation.
V0.2.3 §9: CostSanityGate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

SlippageMode = Literal["EMBEDDED", "EXPLICIT"]


@dataclass(frozen=True, slots=True)
class FeeRecord:
    """Per-trade fee record for reconciliation."""

    trade_id: str
    entry_notional: float
    exit_notional: float
    entry_fee_rate: float  # decimal (0.0005 = 5 bps)
    exit_fee_rate: float
    expected_entry_fee: float
    expected_exit_fee: float
    stored_entry_fee: float
    stored_exit_fee: float
    fee_difference: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fee_difference",
            abs(self.expected_entry_fee - self.stored_entry_fee)
            + abs(self.expected_exit_fee - self.stored_exit_fee),
        )


@dataclass(frozen=True, slots=True)
class SlippageRecord:
    """Per-trade slippage record."""

    trade_id: str
    entry_price: float
    exit_price: float
    entry_fill_price: float
    exit_fill_price: float
    quantity: float
    expected_slippage_bps: float
    stored_slippage_bps: float
    slippage_mode: SlippageMode = "EMBEDDED"
    expected_slippage_usdt: float = 0.0
    stored_slippage_usdt: float = 0.0


@dataclass(frozen=True, slots=True)
class TurnoverReport:
    """Turnover reconciliation report."""

    entry_turnover: float
    exit_turnover: float
    total_turnover: float
    total_fees: float
    total_slippage: float
    fees_as_bps_of_turnover: float = 0.0
    expected_fees_bps: float = 0.0
    fees_reconciled: bool = False

    def __post_init__(self) -> None:
        if self.total_turnover > 0:
            object.__setattr__(
                self, "fees_as_bps_of_turnover", self.total_fees / self.total_turnover * 10_000
            )


@dataclass(frozen=True, slots=True)
class CostSanityResult:
    """Result of cost sanity gate."""

    passed: bool
    checks: list[CostCheck] = field(default_factory=list)

    @property
    def failed_checks(self) -> list[CostCheck]:
        return [c for c in self.checks if not c.passed]


@dataclass(frozen=True, slots=True)
class CostCheck:
    """Single cost sanity check."""

    check_id: str
    passed: bool
    actual: Any = None
    expected: Any = None
    message: str = ""
    severity: str = "CRITICAL"

    @property
    def is_blocking(self) -> bool:
        return not self.passed and self.severity == "CRITICAL"


class FeeInvariantCalculator:
    """V0.2.3 §6: Fee invariants.

    Entry fee = entry_notional * entry_fee_rate
    Exit fee = exit_notional * exit_fee_rate
    Total fee = entry_fee + exit_fee

    Prohibited:
    - 5 bps = 0.05 (wrong: should be 0.0005)
    - 5 bps = 5% (wrong: should be 0.05%)
    """

    @staticmethod
    def bps_to_decimal(bps: float) -> float:
        """Convert basis points to decimal: 5 bps → 0.0005."""
        return bps / 10_000.0

    @staticmethod
    def decimal_to_bps(decimal: float) -> float:
        """Convert decimal to basis points: 0.0005 → 5 bps."""
        return decimal * 10_000.0

    @staticmethod
    def bps_to_percent(bps: float) -> float:
        """Convert basis points to percent: 5 bps → 0.05%."""
        return bps / 100.0

    def compute_expected_fees(
        self,
        entry_notional: float,
        exit_notional: float,
        fee_rate_bps: float,
    ) -> tuple[float, float]:
        """Compute expected fees from notional and rate."""
        rate_decimal = self.bps_to_decimal(fee_rate_bps)
        entry_fee = entry_notional * rate_decimal
        exit_fee = exit_notional * rate_decimal
        return entry_fee, exit_fee

    def validate_fee_record(self, record: FeeRecord, tolerance: float = 1e-6) -> CostCheck:
        """Validate a single fee record."""
        diff = abs(record.expected_entry_fee - record.stored_entry_fee) + abs(
            record.expected_exit_fee - record.stored_exit_fee
        )
        passed = diff <= tolerance
        return CostCheck(
            check_id="fee_invariant",
            passed=passed,
            actual=f"entry={record.stored_entry_fee:.6f}, exit={record.stored_exit_fee:.6f}",
            expected=f"entry={record.expected_entry_fee:.6f}, exit={record.expected_exit_fee:.6f}",
        )


class SlippageValidator:
    """V0.2.3 §7: Slippage invariants.

    MODE A: slippage embedded in fill prices
    MODE B: slippage explicit cost

    Never both.
    """

    def __init__(self, mode: SlippageMode = "EMBEDDED") -> None:
        self._mode = mode

    def validate(
        self,
        entry_price: float,
        exit_price: float,
        entry_fill_price: float,
        exit_fill_price: float,
        quantity: float,
        slippage_bps: float,
    ) -> SlippageRecord:
        """Validate slippage for a trade."""
        if self._mode == "EMBEDDED":
            # Slippage is in the fill price difference
            expected_entry_slip = entry_price * FeeInvariantCalculator.bps_to_decimal(slippage_bps)
            expected_exit_slip = exit_price * FeeInvariantCalculator.bps_to_decimal(slippage_bps)

            actual_entry_slip = abs(entry_fill_price - entry_price)
            actual_exit_slip = abs(exit_fill_price - exit_price)

            actual_entry_bps = FeeInvariantCalculator.decimal_to_bps(
                actual_entry_slip / entry_price if entry_price > 0 else 0
            )
            actual_exit_bps = FeeInvariantCalculator.decimal_to_bps(
                actual_exit_slip / exit_price if exit_price > 0 else 0
            )

            return SlippageRecord(
                trade_id="",
                entry_price=entry_price,
                exit_price=exit_price,
                entry_fill_price=entry_fill_price,
                exit_fill_price=exit_fill_price,
                quantity=quantity,
                expected_slippage_bps=slippage_bps,
                stored_slippage_bps=(actual_entry_bps + actual_exit_bps) / 2,
                slippage_mode="EMBEDDED",
                expected_slippage_usdt=expected_entry_slip * quantity
                + expected_exit_slip * quantity,
                stored_slippage_usdt=actual_entry_slip * quantity + actual_exit_slip * quantity,
            )
        else:
            # Explicit slippage cost
            return SlippageRecord(
                trade_id="",
                entry_price=entry_price,
                exit_price=exit_price,
                entry_fill_price=entry_fill_price,
                exit_fill_price=exit_fill_price,
                quantity=quantity,
                expected_slippage_bps=slippage_bps,
                stored_slippage_bps=0.0,
                slippage_mode="EXPLICIT",
            )


class TurnoverCalculator:
    """V0.2.3 §8: Turnover reconciliation."""

    def compute(
        self,
        entry_turnover: float,
        exit_turnover: float,
        total_fees: float,
        total_slippage: float,
        expected_fee_bps: float,
    ) -> TurnoverReport:
        """Compute and reconcile turnover."""
        total_turnover = entry_turnover + exit_turnover

        # Expected fees based on turnover and rate
        rate_decimal = FeeInvariantCalculator.bps_to_decimal(expected_fee_bps)
        expected_fees = total_turnover * rate_decimal

        fees_reconciled = abs(total_fees - expected_fees) < max(1.0, expected_fees * 0.01)

        return TurnoverReport(
            entry_turnover=entry_turnover,
            exit_turnover=exit_turnover,
            total_turnover=total_turnover,
            total_fees=total_fees,
            total_slippage=total_slippage,
            expected_fees_bps=expected_fee_bps,
            fees_reconciled=fees_reconciled,
        )


class CostSanityGate:
    """V0.2.3 §9: Cost sanity gate.

    Detects:
    - fees incompatible with turnover
    - slippage incompatible with configured bps
    - negative fees
    - double counting
    - bps/percent errors
    - fees > plausible upper bound
    """

    def __init__(
        self,
        max_fee_bps: float = 50.0,  # 50 bps = 0.5% max per side
        max_slippage_bps: float = 50.0,
    ) -> None:
        self._max_fee_bps = max_fee_bps
        self._max_slippage_bps = max_slippage_bps
        self._log = structlog.get_logger("cost_sanity_gate")

    def validate(
        self,
        trades: list[Any],
        fee_rate_bps: float,
        slippage_bps: float,
    ) -> CostSanityResult:
        """Run all cost sanity checks."""
        checks: list[CostCheck] = []

        if not trades:
            return CostSanityResult(passed=True, checks=[])

        total_fees = 0.0
        total_slippage = 0.0
        total_turnover = 0.0
        negative_fees = False
        excessive_fees = False

        for trade in trades:
            # Support both engine Trade objects and TradeRecord objects
            if hasattr(trade, "entry_fill"):
                entry = trade.entry_fill
                exit_ = trade.exit_fill
                notional = entry.fill_price * entry.qty_filled
                entry_fee = entry.commission
                exit_fee = exit_.commission
                entry_slip = entry.slippage
                exit_slip = exit_.slippage
            elif hasattr(trade, "entry_price"):
                # TradeRecord
                notional = trade.notional
                entry_fee = trade.fees / 2  # Approximate split
                exit_fee = trade.fees / 2
                entry_slip = trade.slippage / 2
                exit_slip = trade.slippage / 2
            else:
                continue

            total_turnover += notional * 2
            total_fees += entry_fee + exit_fee
            total_slippage += entry_slip + exit_slip

            if entry_fee < 0 or exit_fee < 0:
                negative_fees = True

            if entry_fee > notional * FeeInvariantCalculator.bps_to_decimal(self._max_fee_bps):
                excessive_fees = True

        # 1. No negative fees
        checks.append(
            CostCheck(
                check_id="no_negative_fees",
                passed=not negative_fees,
                severity="CRITICAL",
            )
        )

        # 2. Fees compatible with turnover
        # turnover = entry_notional + exit_notional (both sides)
        # fees = entry_fee + exit_fee (both sides)
        # So actual_bps = (entry_fee + exit_fee) / (entry_notional + exit_notional) * 10000
        #                = rate (per side, not doubled)
        if total_turnover > 0:
            actual_fee_bps = FeeInvariantCalculator.decimal_to_bps(total_fees / total_turnover)
            fee_compatible = abs(actual_fee_bps - fee_rate_bps) < fee_rate_bps  # Allow 1x tolerance
            checks.append(
                CostCheck(
                    check_id="fees_compatible_turnover",
                    passed=fee_compatible,
                    actual=f"{actual_fee_bps:.1f} bps",
                    expected=f"~{fee_rate_bps:.1f} bps",
                )
            )
        else:
            checks.append(
                CostCheck(
                    check_id="fees_compatible_turnover",
                    passed=True,
                    message="No turnover",
                )
            )

        # 3. Fees not excessive
        checks.append(
            CostCheck(
                check_id="fees_not_excessive",
                passed=not excessive_fees,
                actual=f"max fee rate = {self._max_fee_bps} bps",
            )
        )

        # 4. Slippage non-negative
        checks.append(
            CostCheck(
                check_id="slippage_non_negative",
                passed=total_slippage >= 0,
            )
        )

        # 5. Slippage compatible with configured bps
        if total_turnover > 0:
            actual_slip_bps = FeeInvariantCalculator.decimal_to_bps(total_slippage / total_turnover)
            slip_compatible = actual_slip_bps <= self._max_slippage_bps
            checks.append(
                CostCheck(
                    check_id="slippage_compatible",
                    passed=slip_compatible,
                    actual=f"{actual_slip_bps:.1f} bps",
                    expected=f"<= {self._max_slippage_bps} bps",
                )
            )

        passed = all(c.passed for c in checks)

        self._log.info(
            "cost_sanity.completed",
            passed=passed,
            total_fees=total_fees,
            total_slippage=total_slippage,
            total_turnover=total_turnover,
        )

        return CostSanityResult(passed=passed, checks=checks)


__all__ = [
    "CostCheck",
    "CostSanityGate",
    "CostSanityResult",
    "FeeInvariantCalculator",
    "FeeRecord",
    "SlippageMode",
    "SlippageRecord",
    "SlippageValidator",
    "TurnoverCalculator",
    "TurnoverReport",
]
