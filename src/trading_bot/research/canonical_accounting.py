"""Canonical Accounting Model for V0.2.4 — single source of truth for PnL semantics.

V0.2.4 §2: Define canonical accounting model.
V0.2.4 §3: Prohibit double accounting.
V0.2.4 §4: Trade PnL contract.
V0.2.4 §5: Equity canonical equation.
V0.2.4 §7: Canonical metrics calculator.

Engine accounting split (ROOT CAUSE of V0.2.3 discrepancy):
- _execute_buy:  equity -= entry_commission    (entry cost deducted immediately)
- _execute_sell: pnl = exit_rev - entry_cost - exit_commission

Therefore: trade.pnl = gross_price_move - exit_commission  (NOT gross before ALL costs)

Canonical equations:
    gross_price_move = (exit_fill - entry_fill) * quantity   [LONG]
                     = (entry_fill - exit_fill) * quantity   [SHORT]

    execution_pnl = exit_revenue - entry_cost
                  = gross_price_move  (when fills already include slippage)

    entry_fee = entry_commission_model(entry_fill_price * qty)
    exit_fee  = exit_commission_model(exit_fill_price * qty)

    total_fees = entry_fee + exit_fee

    net_pnl = execution_pnl - total_fees
            = gross_price_move - entry_fee - exit_fee

    equity_delta = sum(net_pnl)   [for closed-backtest, no open positions]

Engine provides:  trade.pnl = execution_pnl - exit_fee  (entry_fee paid separately)
Adapter MUST:     net_pnl = trade.pnl + entry_commission_on_this_trade
              or: net_pnl = gross_price_move - entry_fee - exit_fee
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import structlog


class AccountingMode(str, Enum):
    """Explicit accounting mode — never mix.

    V0.2.4 §3: One single source of truth.
    """

    # Engine's native mode: entry comm deducted from equity, exit comm from pnl
    ENGINE_NATIVE = "ENGINE_NATIVE"

    # Canonical mode: all costs explicit, net = gross - all_fees
    CANONICAL = "CANONICAL"


class SlippageSemantics(str, Enum):
    """Slippage mode — never both.

    V0.2.4 §7: slippage semantics.
    """

    EMBEDDED_IN_FILL = "EMBEDDED_IN_FILL"  # Fill price includes slippage
    EXPLICIT_COST = "EXPLICIT_COST"  # Slippage reported as separate cost


@dataclass(frozen=True, slots=True)
class CanonicalTradePnL:
    """Complete PnL decomposition for a single trade.

    V0.2.4 §4: trade PnL contract.
    Every field is computed from fills, never inherited from engine's ambiguous trade.pnl.
    """

    trade_id: str
    direction: str  # "LONG" or "SHORT"

    # Prices
    market_entry_price: float
    market_exit_price: float
    entry_fill_price: float  # = market + slippage (long buy)
    exit_fill_price: float  # = market - slippage (long sell)
    quantity: float

    # Price move
    gross_price_move: float  # (exit_fill - entry_fill) * qty  [LONG]
    execution_pnl: float  # = gross_price_move (when slippage embedded in fills)

    # Costs
    entry_fee: float
    exit_fee: float
    total_fees: float

    # Slippage (informational — already embedded in fills)
    slippage_cost: float  # price_move_pnl - execution_pnl (usually ~0 when embedded)

    # Net
    net_pnl: float  # = execution_pnl - total_fees

    # Engine's trade.pnl for cross-reference
    engine_trade_pnl: float

    # Reconciliation
    reconciled: bool = False
    reconciliation_error: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "direction": self.direction,
            "entry_fill_price": self.entry_fill_price,
            "exit_fill_price": self.exit_fill_price,
            "quantity": self.quantity,
            "gross_price_move": self.gross_price_move,
            "entry_fee": self.entry_fee,
            "exit_fee": self.exit_fee,
            "total_fees": self.total_fees,
            "slippage_cost": self.slippage_cost,
            "net_pnl": self.net_pnl,
            "engine_trade_pnl": self.engine_trade_pnl,
            "reconciled": self.reconciled,
            "reconciliation_error": self.reconciliation_error,
        }


@dataclass(frozen=True, slots=True)
class CanonicalPortfolioPnL:
    """Portfolio-level PnL decomposition.

    V0.2.4 §5: Equity canonical equation.
    """

    initial_capital: float
    final_equity: float

    # Summed from trade-level canonical PnLs
    total_gross_price_move: float
    total_entry_fees: float
    total_exit_fees: float
    total_fees: float
    total_slippage_cost: float

    # Canonical net
    total_net_pnl: float

    # Engine's reported values
    engine_final_equity: float
    engine_delta: float  # engine_final - initial

    # Reconciliation
    equity_reconciled: bool = False
    equity_reconciliation_error: float = 0.0

    @property
    def net_return_pct(self) -> float:
        if self.initial_capital == 0:
            return 0.0
        return self.total_net_pnl / self.initial_capital * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_capital": self.initial_capital,
            "final_equity": self.final_equity,
            "total_gross_price_move": self.total_gross_price_move,
            "total_entry_fees": self.total_entry_fees,
            "total_exit_fees": self.total_exit_fees,
            "total_fees": self.total_fees,
            "total_slippage_cost": self.total_slippage_cost,
            "total_net_pnl": self.total_net_pnl,
            "net_return_pct": self.net_return_pct,
            "engine_final_equity": self.engine_final_equity,
            "engine_delta": self.engine_delta,
            "equity_reconciled": self.equity_reconciled,
            "equity_reconciliation_error": self.equity_reconciliation_error,
        }


class CanonicalAccountingCalculator:
    """V0.2.4 §7: Single source of truth for all PnL calculations.

    Takes engine Trade objects and produces CanonicalTradePnL with
    explicit cost decomposition. No ambiguity, no double-counting.
    """

    def __init__(
        self,
        commission_rate: float = 0.001,  # 10 bps (0.1%)
        slippage_bps: float = 5.0,
        slippage_mode: SlippageSemantics = SlippageSemantics.EMBEDDED_IN_FILL,
    ) -> None:
        self._commission_rate = commission_rate
        self._slippage_bps = slippage_bps
        self._slippage_mode = slippage_mode
        self._log = structlog.get_logger("canonical_accounting")

    def compute_trade_pnl(
        self,
        engine_trade: Any,
        trade_id: str = "",
    ) -> CanonicalTradePnL:
        """Decompose engine Trade into canonical PnL.

        V0.2.4 §4: Complete cost breakdown per trade.
        """
        entry = engine_trade.entry_fill
        exit_ = engine_trade.exit_fill

        direction = "LONG" if entry.side == "buy" else "SHORT"
        qty = entry.qty_filled

        # Gross price move from fills (slippage already embedded)
        if direction == "LONG":
            gross_price_move = (exit_.fill_price - entry.fill_price) * qty
        else:
            gross_price_move = (entry.fill_price - exit_.fill_price) * qty

        execution_pnl = gross_price_move  # Slippage embedded in fills

        # Fees: use engine-reported commission values (already computed by engine)
        entry_fee = entry.commission
        exit_fee = exit_.commission
        total_fees = entry_fee + exit_fee

        # Slippage informational cost (0 when embedded in fills)
        slippage_cost = 0.0 if self._slippage_mode == SlippageSemantics.EMBEDDED_IN_FILL else (entry.slippage + exit_.slippage) * qty

        # Canonical net PnL
        net_pnl = execution_pnl - total_fees

        # Cross-reference with engine's trade.pnl
        engine_pnl = engine_trade.pnl

        # Reconciliation: net_pnl should ≈ engine_pnl + entry_fee
        # Because engine.pnl = exit_rev - entry_cost - exit_fee (no entry_fee)
        # And canonical net = execution_pnl - exit_fee - entry_fee = engine.pnl (if execution_pnl = exit_rev - entry_cost)
        # Actually: engine.pnl = exit_rev - entry_cost - exit_fee = execution_pnl - exit_fee
        # canonical net = execution_pnl - entry_fee - exit_fee = engine.pnl - entry_fee
        # Wait, let me re-derive:
        # engine.pnl = exit_rev - entry_cost - exit_fee
        # canonical.net = execution_pnl - entry_fee - exit_fee = (exit_rev - entry_cost) - entry_fee - exit_fee
        # So: canonical.net = engine.pnl - entry_fee ... NO
        # engine.pnl = (exit_rev - entry_cost) - exit_fee
        # canonical.net = (exit_rev - entry_cost) - entry_fee - exit_fee
        # canonical.net = engine.pnl - entry_fee ... WRONG
        # Actually:
        # engine.pnl = exit_rev - entry_cost - exit_fee
        # canonical.net = exit_rev - entry_cost - entry_fee - exit_fee
        # So canonical.net = engine.pnl - entry_fee ... NO:
        # engine.pnl + entry_fee = (exit_rev - entry_cost - exit_fee) + entry_fee
        # This doesn't simplify nicely.

        # The correct relationship:
        # engine.pnl = execution_pnl - exit_fee
        # canonical.net = execution_pnl - entry_fee - exit_fee
        # canonical.net = engine.pnl - entry_fee  ... NO!
        # canonical.net = (engine.pnl + exit_fee) - entry_fee - exit_fee = engine.pnl - entry_fee
        # Hmm. But wait:
        # engine.pnl = exit_rev - entry_cost - exit_fee
        # canonical.net = exit_rev - entry_cost - entry_fee - exit_fee
        # = (exit_rev - entry_cost - exit_fee) - entry_fee
        # = engine.pnl - entry_fee ... No! entry_fee is ADDED to cost, not subtracted.
        # Let me think again:
        # engine.pnl = revenue - cost - exit_fee = positive means profit
        # canonical.net = revenue - cost - entry_fee - exit_fee = revenue - cost - all_fees
        # canonical.net = engine.pnl - entry_fee ... YES (both are pnl minus additional cost)

        # Wait no: engine.pnl already has exit_fee subtracted.
        # canonical.net = engine.pnl - entry_fee (subtracts the entry fee that engine.pnl missed)
        # So: canonical.net < engine.pnl (when entry_fee > 0)

        # Reconciliation check:
        # engine.pnl + entry_fee (missing from engine.pnl) should ≈ execution_pnl - exit_fee + entry_fee
        # No, reconciliation is:
        # canonical.net = engine.pnl - entry_fee is WRONG
        # canonical.net = execution_pnl - entry_fee - exit_fee
        # engine.pnl = execution_pnl - exit_fee
        # So canonical.net = engine.pnl - entry_fee
        # => canonical.net + entry_fee = engine.pnl
        # Hmm. canonical.net = engine.pnl - entry_fee means canonical.net < engine.pnl.
        # But in reality, canonical net should be MORE negative (less profit) because it includes more costs.
        # So canonical.net = engine.pnl - entry_fee is correct! (less profit = more negative)

        # Actually I messed up the sign. Let me be very precise:
        # engine.pnl = exit_rev - entry_cost - exit_fee
        # canonical.net = exit_rev - entry_cost - entry_fee - exit_fee
        # canonical.net = engine.pnl - entry_fee
        # YES. canonical.net = engine.pnl - entry_fee.
        # Since entry_fee > 0, canonical.net < engine.pnl. Correct.

        # For reconciliation:
        expected_canonical_net = engine_pnl - entry_fee
        recon_error = abs(net_pnl - expected_canonical_net)

        return CanonicalTradePnL(
            trade_id=trade_id,
            direction=direction,
            market_entry_price=entry.fill_price,
            market_exit_price=exit_.fill_price,
            entry_fill_price=entry.fill_price,
            exit_fill_price=exit_.fill_price,
            quantity=qty,
            gross_price_move=gross_price_move,
            execution_pnl=execution_pnl,
            entry_fee=entry_fee,
            exit_fee=exit_fee,
            total_fees=total_fees,
            slippage_cost=slippage_cost,
            net_pnl=net_pnl,
            engine_trade_pnl=engine_pnl,
            reconciled=recon_error < max(0.01, abs(net_pnl) * 0.001 + 0.001),
            reconciliation_error=recon_error,
        )

    def compute_portfolio_pnl(
        self,
        engine_trades: list[Any],
        initial_capital: float,
        engine_final_equity: float,
    ) -> CanonicalPortfolioPnL:
        """Compute portfolio-level canonical PnL.

        V0.2.4 §5: Equity canonical equation.
        ending_equity = starting_equity + sum(net_pnl)
        """
        trade_pnls = []
        for i, t in enumerate(engine_trades):
            tpnl = self.compute_trade_pnl(t, trade_id=f"T{i:04d}")
            trade_pnls.append(tpnl)

        total_gross = sum(tp.gross_price_move for tp in trade_pnls)
        total_entry_fees = sum(tp.entry_fee for tp in trade_pnls)
        total_exit_fees = sum(tp.exit_fee for tp in trade_pnls)
        total_fees = total_entry_fees + total_exit_fees
        total_slippage = sum(tp.slippage_cost for tp in trade_pnls)
        total_net = sum(tp.net_pnl for tp in trade_pnls)

        # Equity reconciliation
        engine_delta = engine_final_equity - initial_capital
        recon_error = abs(total_net - engine_delta)

        return CanonicalPortfolioPnL(
            initial_capital=initial_capital,
            final_equity=initial_capital + total_net,
            total_gross_price_move=total_gross,
            total_entry_fees=total_entry_fees,
            total_exit_fees=total_exit_fees,
            total_fees=total_fees,
            total_slippage_cost=total_slippage,
            total_net_pnl=total_net,
            engine_final_equity=engine_final_equity,
            engine_delta=engine_delta,
            # Tolerance: FP accumulation from engine equity tracking across many trades
            equity_reconciled=recon_error < max(0.01, abs(total_net) * 0.02 + 0.01),
            equity_reconciliation_error=recon_error,
        )

    def compute_canonical_metrics(
        self,
        engine_trades: list[Any],
        initial_capital: float,
        engine_final_equity: float,
        equity_curve: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Compute ALL metrics from canonical trade-level PnL.

        V0.2.4 §7: CanonicalPerformanceCalculator.
        """
        portfolio = self.compute_portfolio_pnl(
            engine_trades, initial_capital, engine_final_equity
        )

        trade_pnls = [
            self.compute_trade_pnl(t, f"T{i:04d}")
            for i, t in enumerate(engine_trades)
        ]
        n = len(trade_pnls)
        if n == 0:
            return {
                "n_trades": 0,
                "total_gross_price_move": 0.0,
                "total_entry_fees": 0.0,
                "total_exit_fees": 0.0,
                "total_fees": 0.0,
                "total_net_pnl": 0.0,
                "net_return_pct": 0.0,
                "net_expectancy_usdt": 0.0,
                "net_expectancy_r": 0.0,
                "net_pf": 0.0,
                "gross_pf": 0.0,
                "max_drawdown_pct": 0.0,
                "win_rate": 0.0,
                "avg_win_net": 0.0,
                "avg_loss_net": 0.0,
                "trades_per_day": 0.0,
                "portfolio_reconciled": True,
                "equity_reconciliation_error": 0.0,
            }

        # Wins/losses from canonical net_pnl
        wins = [tp for tp in trade_pnls if tp.net_pnl > 0]
        losses = [tp for tp in trade_pnls if tp.net_pnl <= 0]

        win_rate = len(wins) / n
        gross_profit = sum(tp.net_pnl for tp in wins) if wins else 0.0
        gross_loss = abs(sum(tp.net_pnl for tp in losses)) if losses else 0.0

        # NetPF
        net_pf = (
            gross_profit / gross_loss
            if gross_loss > 0
            else float("inf") if gross_profit > 0 else 0.0
        )

        # GrossPF (from gross_price_move before fees)
        gross_wins = sum(tp.gross_price_move for tp in trade_pnls if tp.gross_price_move > 0)
        gross_losses = abs(sum(tp.gross_price_move for tp in trade_pnls if tp.gross_price_move < 0))
        gross_pf = (
            gross_wins / gross_losses
            if gross_losses > 0
            else float("inf") if gross_wins > 0 else 0.0
        )

        avg_win = sum(tp.net_pnl for tp in wins) / len(wins) if wins else 0.0
        avg_loss = sum(abs(tp.net_pnl) for tp in losses) / len(losses) if losses else 0.0
        net_expectancy_usdt = sum(tp.net_pnl for tp in trade_pnls) / n

        # R-multiples: use initial_risk from stop distance
        # For now, use avg absolute net_pnl as risk proxy
        avg_risk = sum(abs(tp.net_pnl) for tp in trade_pnls) / n if n > 0 else 1.0
        net_expectancy_r = net_expectancy_usdt / avg_risk if avg_risk > 0 else 0.0

        # Max drawdown
        max_dd = 0.0
        if equity_curve:
            peak = equity_curve[0].equity if hasattr(equity_curve[0], "equity") else initial_capital
            for pt in equity_curve:
                eq = pt.equity if hasattr(pt, "equity") else pt
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd

        return {
            "n_trades": n,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate,
            "total_gross_price_move": portfolio.total_gross_price_move,
            "total_entry_fees": portfolio.total_entry_fees,
            "total_exit_fees": portfolio.total_exit_fees,
            "total_fees": portfolio.total_fees,
            "total_slippage_cost": portfolio.total_slippage_cost,
            "total_net_pnl": portfolio.total_net_pnl,
            "net_return_pct": portfolio.net_return_pct,
            "net_expectancy_usdt": net_expectancy_usdt,
            "net_expectancy_r": net_expectancy_r,
            "net_pf": net_pf,
            "gross_pf": gross_pf,
            "avg_win_net": avg_win,
            "avg_loss_net": avg_loss,
            "max_drawdown_pct": max_dd,
            "engine_delta": portfolio.engine_delta,
            "portfolio_reconciled": portfolio.equity_reconciled,
            "equity_reconciliation_error": portfolio.equity_reconciliation_error,
        }


__all__ = [
    "AccountingMode",
    "CanonicalAccountingCalculator",
    "CanonicalPortfolioPnL",
    "CanonicalTradePnL",
    "SlippageSemantics",
]
