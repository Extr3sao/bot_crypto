"""RFC-030 §25/§26/§28/§29/§34 — the two-leg execution simulator.

The simulator is deterministic, replayable, timestamped and cost-aware. Its core
guarantee is that the two legs fill **independently**: a leg may fill fully,
partially, or not at all, and a pair is only ``BOTH_FILLED`` when both legs
satisfy the execution contract. One filled leg is never silently carried as a
directional position (§29) — it is either aborted or closed according to the
configured failure policy, and the outcome is recorded as ``PAIR_FAILED``.

Fills are modelled at the *next available* open (PIT) with explicit per-leg
slippage. Costs are charged by :class:`PairCostModelV1`, which charges each leg
independently (§17).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .costs import PairCostBreakdown, PairCostModelV1, ShortLegCost
from .instruments import Side
from .ledger import PairLedgerEntry
from .proposal import (
    LegImbalance,
    PairExecutionPlan,
    PairExecutionStatus,
)

__all__ = [
    "FillConfig",
    "LegFill",
    "PairExecutionResult",
    "PairSimulator",
    "SimulatedLegFill",
]

_TOL = 1e-9


@dataclass(frozen=True, slots=True)
class FillConfig:
    """Deterministic fill model knobs (per leg, in bps)."""

    long_slippage_bps: float = 1.0
    short_slippage_bps: float = 1.0
    long_fill_ratio: float = 1.0
    short_fill_ratio: float = 1.0
    long_available: bool = True
    short_available: bool = True
    long_delay_ms: int = 0
    short_delay_ms: int = 0

    def __post_init__(self) -> None:
        for name, ratio in (
            ("long_fill_ratio", self.long_fill_ratio),
            ("short_fill_ratio", self.short_fill_ratio),
        ):
            if not 0.0 <= ratio <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {ratio}")
        for name, bps in (
            ("long_slippage_bps", self.long_slippage_bps),
            ("short_slippage_bps", self.short_slippage_bps),
        ):
            if bps < 0.0:
                raise ValueError(f"{name} must be >= 0")


@dataclass(frozen=True, slots=True)
class LegFill:
    """The realised outcome of a single leg's execution attempt."""

    side: Side
    filled: bool
    fill_ratio: float
    entry_price: float
    exit_price: float
    qty: float
    notional: float
    fill_time_ms: int
    delay_ms: int
    blocked_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "side": self.side.value,
            "filled": self.filled,
            "fill_ratio": self.fill_ratio,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "qty": self.qty,
            "notional": self.notional,
            "fill_time_ms": self.fill_time_ms,
            "delay_ms": self.delay_ms,
            "blocked_reason": self.blocked_reason,
        }


#: Backwards-compatible alias used by the package export.
SimulatedLegFill = LegFill


@dataclass(frozen=True, slots=True)
class PairExecutionResult:
    """The full outcome of executing one pair plan."""

    execution_id: str
    status: PairExecutionStatus
    long_fill: LegFill
    short_fill: LegFill
    imbalance: LegImbalance
    cost: PairCostBreakdown
    leg_delay_ms: int
    temporary_net_exposure: float
    temporary_beta_exposure: float
    ledger_entry: PairLedgerEntry | None
    fail_closed: bool
    reason: str = ""
    temporary_gross_exposure: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "status": self.status.value,
            "long_fill": self.long_fill.as_dict(),
            "short_fill": self.short_fill.as_dict(),
            "imbalance": self.imbalance.as_dict(),
            "cost": self.cost.as_dict(),
            "leg_delay_ms": self.leg_delay_ms,
            "temporary_net_exposure": self.temporary_net_exposure,
            "temporary_gross_exposure": self.temporary_gross_exposure,
            "temporary_beta_exposure": self.temporary_beta_exposure,
            "fail_closed": self.fail_closed,
            "reason": self.reason,
            "ledger_entry": self.ledger_entry.as_dict() if self.ledger_entry else None,
        }


class PairSimulator:
    """Deterministic, replayable two-leg execution simulator (§34)."""

    def __init__(
        self,
        cost_model: PairCostModelV1,
        *,
        long_leg_beta: float = 1.0,
        short_leg_beta: float = 1.0,
    ) -> None:
        self._cost_model = cost_model
        self._long_leg_beta = long_leg_beta
        self._short_leg_beta = short_leg_beta

    def _attempt_leg(
        self,
        *,
        side: Side,
        target_notional: float,
        entry_ref: float,
        exit_ref: float,
        fill_ratio: float,
        available: bool,
        slippage_bps: float,
        delay_ms: int,
        decision_time: int,
    ) -> LegFill:
        """One leg's independent fill attempt (never coupled to the other leg)."""
        if not available:
            return LegFill(
                side=side,
                filled=False,
                fill_ratio=0.0,
                entry_price=0.0,
                exit_price=0.0,
                qty=0.0,
                notional=0.0,
                fill_time_ms=0,
                delay_ms=delay_ms,
                blocked_reason="LEG_UNAVAILABLE",
            )
        slip = slippage_bps / 10_000.0
        # buy (long entry / short exit) fills worse-high; sell fills worse-low.
        if side is Side.LONG:
            entry_price = entry_ref * (1.0 + slip)
            exit_price = exit_ref * (1.0 - slip)
        else:
            entry_price = entry_ref * (1.0 - slip)  # short entry: sell lower
            exit_price = exit_ref * (1.0 + slip)  # short exit: buy higher
        notional = target_notional * fill_ratio
        qty = notional / entry_price if entry_price > 0 else 0.0
        return LegFill(
            side=side,
            filled=fill_ratio > 0.0,
            fill_ratio=fill_ratio,
            entry_price=entry_price,
            exit_price=exit_price,
            qty=qty,
            notional=notional,
            fill_time_ms=decision_time + delay_ms,
            delay_ms=delay_ms,
        )

    def execute(
        self,
        plan: PairExecutionPlan,
        *,
        long_entry_ref: float,
        long_exit_ref: float,
        short_entry_ref: float,
        short_exit_ref: float,
        fill_config: FillConfig | None = None,
        short_leg_cost: ShortLegCost | None = None,
        holding_days: float = 7.0,
        horizon_minutes: float = 10_080.0,
        beta_before: float = 0.0,
        beta_after: float = 0.0,
    ) -> PairExecutionResult:
        """Execute a plan deterministically and return the reconciled outcome."""
        cfg = fill_config or FillConfig()
        proposal = plan.proposal

        long_fill = self._attempt_leg(
            side=Side.LONG,
            target_notional=proposal.long_target_notional,
            entry_ref=long_entry_ref,
            exit_ref=long_exit_ref,
            fill_ratio=cfg.long_fill_ratio,
            available=cfg.long_available,
            slippage_bps=cfg.long_slippage_bps,
            delay_ms=cfg.long_delay_ms,
            decision_time=proposal.decision_time,
        )
        short_fill = self._attempt_leg(
            side=Side.SHORT,
            target_notional=proposal.short_target_notional,
            entry_ref=short_entry_ref,
            exit_ref=short_exit_ref,
            fill_ratio=cfg.short_fill_ratio,
            available=cfg.short_available,
            slippage_bps=cfg.short_slippage_bps,
            delay_ms=cfg.short_delay_ms,
            decision_time=proposal.decision_time,
        )

        leg_delay_ms = abs(cfg.long_delay_ms - cfg.short_delay_ms)
        # §25 — while the two legs are out of sync the book carries an interim
        # one-leg exposure. Model it explicitly instead of assuming simultaneity.
        if leg_delay_ms > 0 and cfg.long_delay_ms <= cfg.short_delay_ms:
            interim_long, interim_short = long_fill.notional, 0.0
        elif leg_delay_ms > 0:
            interim_long, interim_short = 0.0, short_fill.notional
        else:
            interim_long, interim_short = long_fill.notional, short_fill.notional
        temp_net = interim_long - interim_short
        temp_gross = interim_long + interim_short
        temp_beta = interim_long * self._long_leg_beta - interim_short * self._short_leg_beta

        imbalance = LegImbalance(
            target_long_notional=proposal.long_target_notional,
            actual_long_notional=long_fill.notional,
            target_short_notional=proposal.short_target_notional,
            actual_short_notional=short_fill.notional,
            net_imbalance=long_fill.notional - short_fill.notional,
            beta_imbalance=temp_beta,
            max_allowed_imbalance=plan.maximum_allowed_leg_imbalance,
        )

        cost = self._cost_model.price_pair(
            long_instrument=proposal.long_leg,
            short_instrument=proposal.short_leg,
            long_notional=long_fill.notional,
            short_notional=short_fill.notional,
            holding_days=holding_days,
            horizon_minutes=horizon_minutes,
            short_leg_cost=short_leg_cost,
            decision_time=proposal.decision_time,
        )

        status, reason = self._classify(long_fill, short_fill, cfg, plan, imbalance)

        # §13/§29 — a pair whose short leg cannot be economically priced must fail
        # closed. The fills are still *represented* (so partial/one-leg states are
        # observable), but no pair round-trip is recorded.
        if status is PairExecutionStatus.BOTH_FILLED and not cost.economically_executable:
            status = PairExecutionStatus.PAIR_FAILED
            reason = cost.blocked_reason or "SHORT_LEG_UNCOSTED"

        if status is PairExecutionStatus.BOTH_FILLED:
            entry = self._build_ledger_entry(
                plan=plan,
                long_fill=long_fill,
                short_fill=short_fill,
                cost=cost,
                holding_days=holding_days,
                beta_before=beta_before,
                beta_after=beta_after,
            )
            return PairExecutionResult(
                execution_id=plan.execution_id,
                status=status,
                long_fill=long_fill,
                short_fill=short_fill,
                imbalance=imbalance,
                cost=cost,
                leg_delay_ms=leg_delay_ms,
                temporary_net_exposure=temp_net,
                temporary_gross_exposure=temp_gross,
                temporary_beta_exposure=temp_beta,
                ledger_entry=entry,
                fail_closed=False,
            )

        # Not both filled: fail closed. No ledger entry, no directional carry (§29).
        return PairExecutionResult(
            execution_id=plan.execution_id,
            status=status,
            long_fill=long_fill,
            short_fill=short_fill,
            imbalance=imbalance,
            cost=cost,
            leg_delay_ms=leg_delay_ms,
            temporary_net_exposure=temp_net,
            temporary_gross_exposure=temp_gross,
            temporary_beta_exposure=temp_beta,
            ledger_entry=None,
            fail_closed=True,
            reason=reason,
        )

    # -- helpers ------------------------------------------------------------

    def _classify(
        self,
        long_fill: LegFill,
        short_fill: LegFill,
        cfg: FillConfig,
        plan: PairExecutionPlan,
        imbalance: LegImbalance,
    ) -> tuple[PairExecutionStatus, str]:
        long_full = long_fill.fill_ratio >= 1.0 - _TOL
        short_full = short_fill.fill_ratio >= 1.0 - _TOL
        long_any = long_fill.fill_ratio > _TOL
        short_any = short_fill.fill_ratio > _TOL

        if long_full and short_full:
            # §27 — with both legs complete, a residual imbalance beyond the plan's
            # threshold is a failure condition (threshold from config, not judgement).
            if not imbalance.within_tolerance:
                return PairExecutionStatus.PAIR_FAILED, "LEG_IMBALANCE_EXCEEDS_TOLERANCE"
            return PairExecutionStatus.BOTH_FILLED, ""
        if long_full and not short_any:
            return PairExecutionStatus.LONG_FILLED_SHORT_PENDING, "SHORT_LEG_FAILED"
        if short_full and not long_any:
            return PairExecutionStatus.SHORT_FILLED_LONG_PENDING, "LONG_LEG_FAILED"
        if long_any and not short_any:
            return PairExecutionStatus.PARTIAL_LONG, "SHORT_LEG_FAILED"
        if short_any and not long_any:
            return PairExecutionStatus.PARTIAL_SHORT, "LONG_LEG_FAILED"
        if long_any and short_any:
            # both partially filled, or one partial + other full
            if long_full:
                return PairExecutionStatus.PARTIAL_SHORT, "SHORT_LEG_PARTIAL"
            if short_full:
                return PairExecutionStatus.PARTIAL_LONG, "LONG_LEG_PARTIAL"
            return PairExecutionStatus.PAIR_FAILED, "BOTH_LEGS_PARTIAL"
        return PairExecutionStatus.PAIR_FAILED, "NEITHER_LEG_FILLED"

    def _build_ledger_entry(
        self,
        *,
        plan: PairExecutionPlan,
        long_fill: LegFill,
        short_fill: LegFill,
        cost: PairCostBreakdown,
        holding_days: float,
        beta_before: float,
        beta_after: float,
    ) -> PairLedgerEntry:
        proposal = plan.proposal
        long_gross = (long_fill.exit_price - long_fill.entry_price) * long_fill.qty
        short_gross = (short_fill.entry_price - short_fill.exit_price) * short_fill.qty

        long_cost = float(cost.long_cost or 0.0)
        short_cost = float(cost.short_cost or 0.0)
        borrow = float(cost.borrow or 0.0)
        funding = float(cost.funding or 0.0)
        basis = float(cost.basis or 0.0)
        pair_gross = long_gross + short_gross
        pair_net = pair_gross - long_cost - short_cost - borrow - funding + basis

        return PairLedgerEntry(
            pair_id=plan.execution_id,
            timestamp=proposal.decision_time,
            long_asset=proposal.long_leg.asset,
            short_asset=proposal.short_leg.asset,
            long_qty=long_fill.qty,
            short_qty=short_fill.qty,
            long_entry=long_fill.entry_price,
            short_entry=short_fill.entry_price,
            long_exit=long_fill.exit_price,
            short_exit=short_fill.exit_price,
            long_gross_pnl=long_gross,
            short_gross_pnl=short_gross,
            long_cost=long_cost,
            short_cost=short_cost,
            borrow_cost=borrow,
            funding_cost=funding,
            basis_effect=basis,
            pair_gross_pnl=pair_gross,
            pair_net_pnl=pair_net,
            status=PairExecutionStatus.BOTH_FILLED,
            beta_before=beta_before,
            beta_after=beta_after,
            holding_days=holding_days,
            cost_knowledge=(
                "UNKNOWN" if cost.short_knowledge.value == "UNKNOWN" else cost.short_knowledge.value
            ),
        )
