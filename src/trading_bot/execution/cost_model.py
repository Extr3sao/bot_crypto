"""ExecutionCostModel — centralizes fees and slippage.

Fase 7: All execution costs are computed through this model.
Prevents bps/percent/decimal confusion.

Terminology:
- bps (basis points): 5 bps = 0.05% = 0.0005
- percent: 0.05%
- decimal: 0.0005

Every trade registers: entry_fee, entry_slippage, exit_fee, exit_slippage,
total_cost_usdt, total_cost_bps, gross_pnl, net_pnl.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionCosts:
    """Complete cost breakdown for a single trade."""

    entry_fee_usdt: float
    exit_fee_usdt: float
    entry_slippage_usdt: float
    exit_slippage_usdt: float
    total_cost_usdt: float
    total_cost_bps: float
    gross_pnl: float
    net_pnl: float


class ExecutionCostModel:
    """Centralized cost model for paper trading.

    Ensures consistent fee/slippage calculations and prevents
    bps/percent/decimal confusion.
    """

    def __init__(
        self,
        commission_bps: float = 5.0,
        slippage_bps: float = 1.0,
    ) -> None:
        # Store as bps (basis points)
        self._commission_bps = commission_bps
        self._slippage_bps = slippage_bps

        # Validate
        self._validate_bps(commission_bps, "commission_bps")
        self._validate_bps(slippage_bps, "slippage_bps")

    @staticmethod
    def _validate_bps(value: float, name: str) -> None:
        """Validate that a bps value is reasonable."""
        if value < 0:
            raise ValueError(f"{name} must be >= 0, got {value}")
        if value > 1000:  # > 10% is unreasonable
            raise ValueError(f"{name} must be <= 1000 bps (10%), got {value}")

    @staticmethod
    def bps_to_decimal(bps: float) -> float:
        """Convert basis points to decimal: 5 bps -> 0.0005."""
        return bps / 10_000.0

    @staticmethod
    def bps_to_percent(bps: float) -> float:
        """Convert basis points to percent: 5 bps -> 0.05%."""
        return bps / 100.0

    @staticmethod
    def percent_to_bps(pct: float) -> float:
        """Convert percent to basis points: 0.05% -> 5 bps."""
        return pct * 100.0

    def entry_commission_usdt(self, notional_usdt: float) -> float:
        """Compute entry commission in USDT."""
        return notional_usdt * self.bps_to_decimal(self._commission_bps)

    def exit_commission_usdt(self, notional_usdt: float) -> float:
        """Compute exit commission in USDT."""
        return notional_usdt * self.bps_to_decimal(self._commission_bps)

    def entry_slippage_price(self, reference_price: float, side: str) -> float:
        """Compute entry fill price with slippage.

        For buy: slippage makes the price HIGHER (worse fill).
        For sell: slippage makes the price LOWER (worse fill).
        """
        mult = self.bps_to_decimal(self._slippage_bps)
        if side == "buy":
            return reference_price * (1.0 + mult)
        return reference_price * (1.0 - mult)

    def exit_slippage_price(self, reference_price: float, side: str) -> float:
        """Compute exit fill price with slippage.

        For buy exit (sell): slippage makes the price LOWER (worse fill).
        For sell exit (buy): slippage makes the price HIGHER (worse fill).
        """
        mult = self.bps_to_decimal(self._slippage_bps)
        if side == "buy":
            return reference_price * (1.0 - mult)
        return reference_price * (1.0 + mult)

    def compute_costs(
        self,
        *,
        notional_usdt: float,
        entry_price: float,
        exit_price: float,
        quantity: float,
        side: str,
    ) -> ExecutionCosts:
        """Compute complete cost breakdown for a trade.

        Args:
            notional_usdt: Position notional at entry.
            entry_price: Reference entry price (before slippage).
            exit_price: Reference exit price (before slippage).
            quantity: Position quantity.
            side: "buy" or "sell".

        Returns:
            ExecutionCosts with full breakdown.
        """
        # Actual fill prices (with slippage)
        actual_entry = self.entry_slippage_price(entry_price, side)
        actual_exit = self.exit_slippage_price(exit_price, side)

        # Gross PnL (before any costs)
        if side == "buy":
            gross_pnl = (actual_exit - actual_entry) * quantity
        else:
            gross_pnl = (actual_entry - actual_exit) * quantity

        # Fees
        entry_fee = self.entry_commission_usdt(notional_usdt)
        exit_fee = self.exit_commission_usdt(notional_usdt)

        # Slippage cost (vs reference price)
        if side == "buy":
            entry_slip_cost = (actual_entry - entry_price) * quantity
            exit_slip_cost = (exit_price - actual_exit) * quantity
        else:
            entry_slip_cost = (entry_price - actual_entry) * quantity
            exit_slip_cost = (actual_exit - exit_price) * quantity

        entry_slippage = max(entry_slip_cost, 0.0)
        exit_slippage = max(exit_slip_cost, 0.0)

        # Total cost
        total_cost_usdt = entry_fee + exit_fee + entry_slippage + exit_slippage
        total_cost_bps = (total_cost_usdt / notional_usdt * 10_000.0) if notional_usdt > 0 else 0.0

        # Net PnL
        net_pnl = gross_pnl - total_cost_usdt

        return ExecutionCosts(
            entry_fee_usdt=round(entry_fee, 8),
            exit_fee_usdt=round(exit_fee, 8),
            entry_slippage_usdt=round(entry_slippage, 8),
            exit_slippage_usdt=round(exit_slippage, 8),
            total_cost_usdt=round(total_cost_usdt, 8),
            total_cost_bps=round(total_cost_bps, 4),
            gross_pnl=round(gross_pnl, 8),
            net_pnl=round(net_pnl, 8),
        )

    def planned_net_rr(
        self,
        *,
        entry_price: float,
        stop_distance_pct: float,
        target_distance_pct: float,
        side: str,
    ) -> dict[str, float]:
        """Compute planned net risk/reward after costs.

        Used for cost-aware admission (Phase 11).
        """
        # Approximate notional for cost calculation
        notional = 1000.0  # normalized

        stop_distance_usdt = notional * (stop_distance_pct / 100.0)
        target_distance_usdt = notional * (target_distance_pct / 100.0)

        # Approximate roundtrip cost
        entry_fee = self.entry_commission_usdt(notional)
        exit_fee = self.exit_commission_usdt(notional)
        entry_slip = notional * self.bps_to_decimal(self._slippage_bps)
        exit_slip = notional * self.bps_to_decimal(self._slippage_bps)
        total_cost = entry_fee + exit_fee + entry_slip + exit_slip

        net_reward = target_distance_usdt - total_cost
        net_loss = stop_distance_usdt + total_cost

        net_rr = net_reward / net_loss if net_loss > 0 else 0.0

        return {
            "gross_rr": round(target_distance_usdt / stop_distance_usdt, 4)
            if stop_distance_usdt > 0
            else 0.0,
            "net_rr": round(net_rr, 4),
            "cost_fraction_of_target": round(total_cost / target_distance_usdt, 4)
            if target_distance_usdt > 0
            else 1.0,
            "total_cost_bps": round(total_cost / notional * 10_000.0, 2),
        }
