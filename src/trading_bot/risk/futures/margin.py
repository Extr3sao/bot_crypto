"""Margin and liquidation model for ISOLATED LINEAR perpetuals.

The model is derived, not guessed (RFC-048 §7). For an isolated position the
venue's margin condition is

    wallet_balance + unrealised_pnl - accrued_funding - fees == maintenance_margin

with ``maintenance_margin = notional * rate - cum_maintenance_amount`` taken from
the venue's own bracket ladder. Solving that condition for the mark price gives
the closed forms used here:

    LONG :  LP = (qty*entry - WB + A - cum) / (qty * (1 - rate))
    SHORT:  LP = (qty*entry + WB - A + cum) / (qty * (1 + rate))

where ``A`` is the adverse term (funding owed + liquidation fee) charged BEFORE
solving, and ``WB`` is the isolated wallet balance. For a long, ``A`` raises the
liquidation price; for a short, it lowers it. Either way the buffer shrinks, which
is the conservative direction.

If the ladder, the mark price or the liquidation fee is unknown, the assessment
is returned as ``LIQUIDATION_RISK_UNKNOWN`` and no approval may rest on it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .contracts import Direction, RejectionCode
from .instruments import InstrumentSpec

__all__ = [
    "LiquidationAssessment",
    "LiquidationStatus",
    "MarginModel",
    "StressScenario",
]


class LiquidationStatus(StrEnum):
    LIQUIDATION_RISK_KNOWN = "LIQUIDATION_RISK_KNOWN"
    LIQUIDATION_RISK_UNKNOWN = "LIQUIDATION_RISK_UNKNOWN"


@dataclass(frozen=True, slots=True)
class StressScenario:
    """One adverse path the position must survive (§7)."""

    name: str
    adverse_move_pct: float  # positive number = move against the position
    spread_widening_bps: float = 0.0
    funding_settlements: int = 0
    funding_rate: float = 0.0
    bracket_shift: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "adverse_move_pct": self.adverse_move_pct,
            "spread_widening_bps": self.spread_widening_bps,
            "funding_settlements": self.funding_settlements,
            "funding_rate": self.funding_rate,
            "bracket_shift": self.bracket_shift,
        }


@dataclass(frozen=True, slots=True)
class LiquidationAssessment:
    """Result of the liquidation model for one simulated position."""

    status: LiquidationStatus
    direction: Direction
    quantity: float
    entry_price: float
    wallet_balance: float
    initial_margin: float
    maintenance_margin_entry: float
    maintenance_margin_unknown: bool
    bracket_seq: int | None
    liquidation_price: float | None
    liquidation_buffer_bps: float | None
    liquidation_fee_usdt: float | None
    adverse_terms_usdt: float
    stress_liquidation_price: float | None
    stress_buffer_bps: float | None
    bracket_shifted: bool
    reasons: tuple[RejectionCode, ...] = ()
    notes: tuple[str, ...] = ()
    stress_path: tuple[dict[str, Any], ...] = ()

    @property
    def known(self) -> bool:
        return self.status is LiquidationStatus.LIQUIDATION_RISK_KNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "direction": self.direction.value,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "wallet_balance": self.wallet_balance,
            "initial_margin": self.initial_margin,
            "maintenance_margin_entry": self.maintenance_margin_entry,
            "maintenance_margin_unknown": self.maintenance_margin_unknown,
            "bracket_seq": self.bracket_seq,
            "liquidation_price": self.liquidation_price,
            "liquidation_buffer_bps": self.liquidation_buffer_bps,
            "liquidation_fee_usdt": self.liquidation_fee_usdt,
            "adverse_terms_usdt": self.adverse_terms_usdt,
            "stress_liquidation_price": self.stress_liquidation_price,
            "stress_buffer_bps": self.stress_buffer_bps,
            "bracket_shifted": self.bracket_shifted,
            "reasons": [r.value for r in self.reasons],
            "notes": list(self.notes),
            "stress_path": list(self.stress_path),
        }


class MarginModel:
    """Deterministic margin maths for one instrument. No state, no I/O."""

    def __init__(self, spec: InstrumentSpec) -> None:
        self._spec = spec

    @property
    def spec(self) -> InstrumentSpec:
        return self._spec

    # -- margin --------------------------------------------------------------

    def initial_margin(self, notional: float, leverage: float) -> float:
        if leverage <= 0:
            raise ValueError("leverage must be > 0")
        return notional / leverage

    def maintenance_margin(self, notional: float) -> tuple[float, int]:
        """``(maintenance_margin, bracket_seq)``; raises if the ladder is absent."""
        bracket = self._spec.bracket_for(notional)
        return bracket.maintenance_margin(notional), bracket.bracket_seq

    def effective_leverage(self, notional: float, margin: float) -> float:
        return notional / margin if margin > 0 else math.inf

    # -- liquidation ---------------------------------------------------------

    def liquidation_price(
        self,
        *,
        direction: Direction,
        quantity: float,
        entry_price: float,
        wallet_balance: float,
        bracket_rate: float,
        cum_maintenance_amount: float,
        adverse_terms_usdt: float = 0.0,
    ) -> float | None:
        """Closed-form liquidation price under the venue's margin condition.

        ``adverse_terms_usdt`` is funding owed plus liquidation fees already
        deducted from the wallet balance (always >= 0 here).
        """
        if quantity <= 0 or entry_price <= 0:
            return None
        if direction is Direction.LONG:
            # Solved from  WB + qty*(P - E) - S = qty*P*rate - cum  for P:
            #   qty*P*(1 - rate) = qty*E - WB + S - cum
            # S (funding owed + liquidation fee) RAISES the long's liquidation
            # price, so it can only reduce the buffer. RFC-048 DEF-048-01.
            numerator = quantity * entry_price - wallet_balance + adverse_terms_usdt
            numerator -= cum_maintenance_amount
            denominator = quantity * (1.0 - bracket_rate)
        else:
            numerator = quantity * entry_price + wallet_balance + cum_maintenance_amount
            numerator -= adverse_terms_usdt
            denominator = quantity * (1.0 + bracket_rate)
        if denominator <= 0:
            return None
        price = numerator / denominator
        return price if price > 0 else 0.0

    def assess(
        self,
        *,
        direction: Direction,
        quantity: float,
        entry_price: float,
        wallet_balance: float,
        market_price: float | None,
        funding_owed_usdt: float = 0.0,
        stress_scenarios: tuple[StressScenario, ...] = (),
    ) -> LiquidationAssessment:
        """Full liquidation assessment, including bracket-shift stress."""
        reasons: list[RejectionCode] = []
        notes: list[str] = []

        if not self._spec.margin_ladder_complete:
            return self._unknown_assessment(
                direction=direction,
                quantity=quantity,
                entry_price=entry_price,
                wallet_balance=wallet_balance,
                reason=RejectionCode.INCOMPLETE_MARGIN_MODEL,
                notes=["maintenance margin ladder missing or discontinuous"],
            )
        if quantity <= 0 or entry_price <= 0:
            return self._unknown_assessment(
                direction=direction,
                quantity=quantity,
                entry_price=entry_price,
                wallet_balance=wallet_balance,
                reason=RejectionCode.INCOMPLETE_MARGIN_MODEL,
                notes=["quantity/entry not usable for a liquidation computation"],
            )

        entry_notional = quantity * entry_price
        bracket = self._spec.bracket_for(entry_notional)
        maintenance, bracket_seq = self.maintenance_margin(entry_notional)

        if self._spec.liquidation_fee_rate is None:
            liquidation_fee: float | None = None
            reasons.append(RejectionCode.LIQUIDATION_RISK_UNKNOWN)
            notes.append("venue liquidation fee unknown: liquidation cost not modelled")
        else:
            liquidation_fee = entry_notional * self._spec.liquidation_fee_rate

        if market_price is None or market_price <= 0:
            reasons.append(RejectionCode.MISSING_MARK_PRICE)
            notes.append("mark price missing: cannot separate mark from index/last")

        if reasons:
            return self._unknown_assessment(
                direction=direction,
                quantity=quantity,
                entry_price=entry_price,
                wallet_balance=wallet_balance,
                reasons=reasons,
                notes=notes,
                maintenance_margin=maintenance,
                bracket_seq=bracket_seq,
            )

        safety = max(funding_owed_usdt, 0.0) + float(liquidation_fee or 0.0)
        liquidation_price = self.liquidation_price(
            direction=direction,
            quantity=quantity,
            entry_price=entry_price,
            wallet_balance=wallet_balance,
            bracket_rate=bracket.maintenance_margin_rate,
            cum_maintenance_amount=bracket.cum_maintenance_amount,
            adverse_terms_usdt=safety,
        )
        buffer_bps = _buffer_bps(direction, entry_price, liquidation_price)

        stress_lp, stress_buffer, bracket_shifted, stress_path = self._stress(
            direction=direction,
            quantity=quantity,
            entry_price=entry_price,
            wallet_balance=wallet_balance,
            liquidation_fee=float(liquidation_fee or 0.0),
            funding_owed_usdt=funding_owed_usdt,
            scenarios=stress_scenarios,
        )

        return LiquidationAssessment(
            status=(
                LiquidationStatus.LIQUIDATION_RISK_UNKNOWN
                if reasons
                else LiquidationStatus.LIQUIDATION_RISK_KNOWN
            ),
            direction=direction,
            quantity=quantity,
            entry_price=entry_price,
            wallet_balance=wallet_balance,
            initial_margin=wallet_balance,
            maintenance_margin_entry=maintenance,
            maintenance_margin_unknown=False,
            bracket_seq=bracket_seq,
            liquidation_price=liquidation_price,
            liquidation_buffer_bps=buffer_bps,
            liquidation_fee_usdt=liquidation_fee,
            adverse_terms_usdt=safety,
            stress_liquidation_price=stress_lp,
            stress_buffer_bps=stress_buffer,
            bracket_shifted=bracket_shifted,
            reasons=tuple(reasons),
            notes=tuple(notes),
            stress_path=stress_path,
        )

    def _stress(
        self,
        *,
        direction: Direction,
        quantity: float,
        entry_price: float,
        wallet_balance: float,
        liquidation_fee: float,
        funding_owed_usdt: float,
        scenarios: tuple[StressScenario, ...],
    ) -> tuple[float | None, float | None, bool, tuple[dict[str, Any], ...]]:
        """Worst liquidation price across the declared stress paths."""
        worst_lp: float | None = None
        worst_buffer: float | None = None
        bracket_shifted = False
        path: list[dict[str, Any]] = []
        for scenario in scenarios:
            if direction is Direction.LONG:
                mark = entry_price * (1.0 - scenario.adverse_move_pct)
            else:
                mark = entry_price * (1.0 + scenario.adverse_move_pct)
            stress_notional = quantity * mark
            entry_notional = quantity * entry_price
            if scenario.bracket_shift:
                bracket = self._spec.worst_bracket_for(entry_notional, stress_notional)
                shifted = bracket.bracket_seq != self._spec.bracket_for(entry_notional).bracket_seq
                bracket_shifted = bracket_shifted or shifted
            else:
                bracket = self._spec.bracket_for(entry_notional)
                shifted = False
            extra_funding = (
                abs(scenario.funding_rate) * stress_notional * scenario.funding_settlements
                if scenario.funding_rate
                else 0.0
            )
            spread_cost = stress_notional * scenario.spread_widening_bps / 10_000.0
            safety = (
                max(funding_owed_usdt, 0.0)
                + extra_funding
                + liquidation_fee
                + spread_cost
            )
            lp = self.liquidation_price(
                direction=direction,
                quantity=quantity,
                entry_price=entry_price,
                wallet_balance=wallet_balance,
                bracket_rate=bracket.maintenance_margin_rate,
                cum_maintenance_amount=bracket.cum_maintenance_amount,
                adverse_terms_usdt=safety,
            )
            buffer = _buffer_bps(direction, entry_price, lp)
            path.append(
                {
                    "scenario": scenario.name,
                    "mark_price": round(mark, 6),
                    "stress_notional": round(stress_notional, 6),
                    "bracket_seq": bracket.bracket_seq,
                    "bracket_shifted": shifted,
                    "extra_funding_usdt": round(extra_funding, 6),
                    "spread_cost_usdt": round(spread_cost, 6),
                    "liquidation_price": None if lp is None else round(lp, 6),
                    "buffer_bps": None if buffer is None else round(buffer, 6),
                }
            )
            if lp is None or buffer is None:
                continue
            if worst_buffer is None or buffer < worst_buffer:
                worst_buffer = buffer
                worst_lp = lp
        return worst_lp, worst_buffer, bracket_shifted, tuple(path)

    def _unknown_assessment(
        self,
        *,
        direction: Direction,
        quantity: float,
        entry_price: float,
        wallet_balance: float,
        reason: RejectionCode | None = None,
        reasons: list[RejectionCode] | None = None,
        notes: list[str] | None = None,
        maintenance_margin: float = 0.0,
        bracket_seq: int | None = None,
    ) -> LiquidationAssessment:
        merged = list(reasons or [])
        if reason is not None:
            merged.append(reason)
        if RejectionCode.LIQUIDATION_RISK_UNKNOWN not in merged:
            merged.append(RejectionCode.LIQUIDATION_RISK_UNKNOWN)
        return LiquidationAssessment(
            status=LiquidationStatus.LIQUIDATION_RISK_UNKNOWN,
            direction=direction,
            quantity=quantity,
            entry_price=entry_price,
            wallet_balance=wallet_balance,
            initial_margin=wallet_balance,
            maintenance_margin_entry=maintenance_margin,
            maintenance_margin_unknown=True,
            bracket_seq=bracket_seq,
            liquidation_price=None,
            liquidation_buffer_bps=None,
            liquidation_fee_usdt=None,
            adverse_terms_usdt=0.0,
            stress_liquidation_price=None,
            stress_buffer_bps=None,
            bracket_shifted=False,
            reasons=tuple(dict.fromkeys(merged)),
            notes=tuple(notes or []),
        )


def _buffer_bps(direction: Direction, entry: float, lp: float | None) -> float | None:
    """Distance from entry to liquidation, in bps of entry (positive = room)."""
    if lp is None or entry <= 0:
        return None
    if direction is Direction.LONG:
        return (entry - lp) / entry * 10_000.0
    return (lp - entry) / entry * 10_000.0
