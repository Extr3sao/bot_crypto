"""Equity Reconstruction and Exposure Sanity for V0.2.3 §10-13.

V0.2.3 §10: Exposure sanity per timestamp.
V0.2.3 §11: Trade risk sanity.
V0.2.3 §12: Notional sanity.
V0.2.3 §13: Capital flow reconstruction.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog


@dataclass(frozen=True, slots=True)
class ExposureSnapshot:
    """Exposure at a point in time."""

    timestamp: int
    aggregate_open_notional: float
    equity: float
    exposure_pct: float
    max_exposure_pct: float
    within_limit: bool = True


@dataclass(frozen=True, slots=True)
class TradeRiskEvidence:
    """Per-trade risk evidence."""

    trade_id: str
    equity_before: float
    risk_per_trade_pct: float
    risk_budget_usdt: float
    entry_price: float
    stop_price: float
    stop_distance_pct: float
    quantity: float
    notional: float
    stop_risk_usdt: float
    risk_budget_utilization_pct: float = 0.0
    within_budget: bool = True


@dataclass(frozen=True, slots=True)
class EquityReconstruction:
    """Independent equity curve reconstruction."""

    starting_equity: float = 0.0
    ending_equity: float = 0.0
    total_realized_pnl: float = 0.0
    total_fees: float = 0.0
    total_slippage: float = 0.0
    reconstructed_ending: float = 0.0
    difference: float = 0.0
    reconciled: bool = False

    def __post_init__(self) -> None:
        reconstructed = self.starting_equity + self.total_realized_pnl - self.total_fees - self.total_slippage
        object.__setattr__(self, "reconstructed_ending", reconstructed)
        diff = abs(self.ending_equity - reconstructed)
        object.__setattr__(self, "difference", diff)
        object.__setattr__(self, "reconciled",
            diff < max(0.01, abs(reconstructed) * 0.001)
        )


class ExposureSanityChecker:
    """V0.2.3 §10: Exposure sanity per timestamp."""

    def __init__(self, max_exposure_pct: float = 1.0) -> None:
        self._max_exposure_pct = max_exposure_pct
        self._log = structlog.get_logger("exposure_sanity")

    def check_trade(
        self,
        notional: float,
        equity: float,
    ) -> ExposureSnapshot:
        """Check exposure for a single trade."""
        exposure_pct = notional / equity if equity > 0 else float("inf")
        within = exposure_pct <= self._max_exposure_pct + 1e-6
        return ExposureSnapshot(
            timestamp=0,
            aggregate_open_notional=notional,
            equity=equity,
            exposure_pct=exposure_pct,
            max_exposure_pct=self._max_exposure_pct,
            within_limit=within,
        )


class TradeRiskChecker:
    """V0.2.3 §11: Trade risk sanity."""

    def __init__(self, tolerance: float = 0.01) -> None:
        self._tolerance = tolerance

    def check(
        self,
        trade_id: str,
        equity: float,
        risk_per_trade_pct: float,
        entry_price: float,
        stop_price: float,
        quantity: float,
    ) -> TradeRiskEvidence:
        """Check risk budget for a single trade."""
        risk_budget_usdt = equity * risk_per_trade_pct
        stop_distance_pct = abs(entry_price - stop_price) / entry_price if entry_price > 0 else 0
        stop_risk_usdt = abs(entry_price - stop_price) * quantity
        utilization = stop_risk_usdt / risk_budget_usdt if risk_budget_usdt > 0 else float("inf")
        within = stop_risk_usdt <= risk_budget_usdt * (1 + self._tolerance)

        return TradeRiskEvidence(
            trade_id=trade_id,
            equity_before=equity,
            risk_per_trade_pct=risk_per_trade_pct,
            risk_budget_usdt=risk_budget_usdt,
            entry_price=entry_price,
            stop_price=stop_price,
            stop_distance_pct=stop_distance_pct,
            quantity=quantity,
            notional=entry_price * quantity,
            stop_risk_usdt=stop_risk_usdt,
            risk_budget_utilization_pct=utilization * 100,
            within_budget=within,
        )


class EquityReconstructor:
    """V0.2.3 §13: Capital flow reconstruction."""

    def __init__(self) -> None:
        self._log = structlog.get_logger("equity_reconstructor")

    def reconstruct(
        self,
        initial_capital: float,
        trades: list[Any],
        final_equity: float,
    ) -> EquityReconstruction:
        """Reconstruct equity from trades independently."""
        total_pnl = 0.0
        total_fees = 0.0
        total_slippage = 0.0

        for trade in trades:
            total_pnl += trade.pnl
            if hasattr(trade, "entry_fill"):
                total_fees += trade.entry_fill.commission + trade.exit_fill.commission
                total_slippage += trade.entry_fill.slippage + trade.exit_fill.slippage

        return EquityReconstruction(
            starting_equity=initial_capital,
            ending_equity=final_equity,
            total_realized_pnl=total_pnl,
            total_fees=total_fees,
            total_slippage=total_slippage,
        )

    def write_csv(
        self,
        reconstruction: EquityReconstruction,
        output_path: Path,
    ) -> Path:
        """Write equity reconstruction to CSV."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["metric", "value"])
            writer.writerow(["starting_equity", reconstruction.starting_equity])
            writer.writerow(["ending_equity", reconstruction.ending_equity])
            writer.writerow(["total_realized_pnl", reconstruction.total_realized_pnl])
            writer.writerow(["total_fees", reconstruction.total_fees])
            writer.writerow(["total_slippage", reconstruction.total_slippage])
            writer.writerow(["reconstructed_ending", reconstruction.reconstructed_ending])
            writer.writerow(["difference", reconstruction.difference])
            writer.writerow(["reconciled", reconstruction.reconciled])
        return output_path


__all__ = [
    "EquityReconstruction",
    "EquityReconstructor",
    "ExposureSanityChecker",
    "ExposureSnapshot",
    "TradeRiskChecker",
    "TradeRiskEvidence",
]
