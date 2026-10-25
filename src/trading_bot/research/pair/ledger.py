"""RFC-030 §18/§19/§20/§21/§30/§31 — pair ledger and portfolio accounting.

The ledger is the single raw source of truth. The independent verifier (§40)
recomputes every summary from these entries, never from an aggregate JSON.

Reconciliation is an *invariant*, enforced on construction of every entry:

    pair_net_pnl == long_gross_pnl + short_gross_pnl
                    - long_cost - short_cost
                    - borrow_cost - funding_cost
                    + basis_effect

and, across the portfolio (§19):

    final_equity == initial_capital + realized_pnl + unrealized_pnl - costs

Note on §20/§21: gross exposure is ``long + |short|`` and net exposure is the
*signed* ``long + short``. A 2x gross book is never reported as "2x leverage".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .proposal import PairExecutionStatus

__all__ = [
    "PairAccountingError",
    "PairLedger",
    "PairLedgerEntry",
    "PortfolioState",
]

_TOL = 1e-6


class PairAccountingError(AssertionError):
    """Raised when an accounting invariant is violated (§31)."""


@dataclass(frozen=True, slots=True)
class PairLedgerEntry:
    """§18 — one reconciled pair round-trip."""

    pair_id: str
    timestamp: int
    long_asset: str
    short_asset: str
    long_qty: float
    short_qty: float  #: positive magnitude of the short leg
    long_entry: float
    short_entry: float
    long_exit: float
    short_exit: float
    long_gross_pnl: float
    short_gross_pnl: float
    long_cost: float
    short_cost: float
    borrow_cost: float
    funding_cost: float
    basis_effect: float
    pair_gross_pnl: float
    pair_net_pnl: float
    status: PairExecutionStatus
    beta_before: float = 0.0
    beta_after: float = 0.0
    holding_days: float = 0.0
    cost_knowledge: str = "UNKNOWN"

    def __post_init__(self) -> None:
        """§31 — the pair-PnL identity is enforced on construction, not assumed.

        ``pair_gross_pnl`` and ``pair_net_pnl`` are stored (not derived) precisely
        so that a mutated or fabricated entry cannot silently disagree with its
        leg arithmetic.
        """
        expected_gross = self.long_gross_pnl + self.short_gross_pnl
        expected_net = (
            expected_gross
            - self.long_cost
            - self.short_cost
            - self.borrow_cost
            - self.funding_cost
            + self.basis_effect
        )
        if abs(expected_gross - self.pair_gross_pnl) > max(_TOL, abs(expected_gross) * 1e-9):
            raise PairAccountingError(
                f"pair {self.pair_id}: gross pnl {self.pair_gross_pnl} != "
                f"leg arithmetic {expected_gross}"
            )
        if abs(expected_net - self.pair_net_pnl) > max(_TOL, abs(expected_net) * 1e-9):
            raise PairAccountingError(
                f"pair {self.pair_id}: net pnl {self.pair_net_pnl} != leg arithmetic {expected_net}"
            )

    # -- derived quantities -------------------------------------------------

    @property
    def total_cost(self) -> float:
        return (
            self.long_cost
            + self.short_cost
            + self.borrow_cost
            + self.funding_cost
            - self.basis_effect
        )

    @property
    def gross_exposure(self) -> float:
        """§20 — long notional + |short| notional."""
        return abs(self.long_qty * self.long_entry) + abs(self.short_qty * self.short_entry)

    @property
    def net_exposure(self) -> float:
        """§21 — signed net = long notional - short notional.

        ``short_qty`` is a positive magnitude, so the short leg enters with a
        negative sign: a dollar-neutral pair reports net ~= 0.
        """
        return self.long_qty * self.long_entry - self.short_qty * self.short_entry

    def as_dict(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "timestamp": self.timestamp,
            "long_asset": self.long_asset,
            "short_asset": self.short_asset,
            "long_qty": self.long_qty,
            "short_qty": self.short_qty,
            "long_entry": self.long_entry,
            "short_entry": self.short_entry,
            "long_exit": self.long_exit,
            "short_exit": self.short_exit,
            "long_gross_pnl": self.long_gross_pnl,
            "short_gross_pnl": self.short_gross_pnl,
            "long_cost": self.long_cost,
            "short_cost": self.short_cost,
            "borrow_cost": self.borrow_cost,
            "funding_cost": self.funding_cost,
            "basis_effect": self.basis_effect,
            "pair_gross_pnl": self.pair_gross_pnl,
            "pair_net_pnl": self.pair_net_pnl,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "beta_before": self.beta_before,
            "beta_after": self.beta_after,
            "holding_days": self.holding_days,
            "cost_knowledge": self.cost_knowledge,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class PortfolioState:
    """§19 — one explicit capital model. No ambiguous per-leg reference notional.

    ``realized_pnl`` is **gross**; ``costs`` is separate; ``equity`` applies the
    §30 identity ``initial + realized + unrealized - costs``.
    """

    initial_capital: float
    cash: float
    long_notional: float
    short_notional: float
    realized_pnl: float
    unrealized_pnl: float
    costs: float

    @property
    def gross_exposure(self) -> float:
        return self.long_notional + abs(self.short_notional)

    @property
    def net_exposure(self) -> float:
        return self.long_notional + self.short_notional

    @property
    def net_pnl(self) -> float:
        return self.realized_pnl - self.costs

    @property
    def equity(self) -> float:
        """§30 — initial + realized(gross) + unrealized - costs."""
        return self.initial_capital + self.realized_pnl + self.unrealized_pnl - self.costs

    def as_dict(self) -> dict[str, float]:
        return {
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "long_notional": self.long_notional,
            "short_notional": self.short_notional,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "costs": self.costs,
            "net_pnl": self.net_pnl,
            "equity": self.equity,
        }


@dataclass(slots=True)
class PairLedger:
    """Append-only ledger of reconciled pair round-trips (§18)."""

    initial_capital: float = 0.0
    entries: list[PairLedgerEntry] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.entries is None:
            self.entries = []

    def append(self, entry: PairLedgerEntry) -> None:
        """Append a reconciled entry; refuses a pair that was never both-filled."""
        if not entry.status.is_filled:
            raise PairAccountingError(
                f"pair {entry.pair_id} cannot enter the ledger in state {entry.status.value}: "
                "a one-leg or partial execution is not a pair round-trip (§26/§29)"
            )
        self.entries.append(entry)

    # -- aggregates (recomputed, never cached) ------------------------------

    @property
    def n_pairs(self) -> int:
        return len(self.entries)

    @property
    def total_long_gross_pnl(self) -> float:
        return math.fsum(e.long_gross_pnl for e in self.entries)

    @property
    def total_short_gross_pnl(self) -> float:
        return math.fsum(e.short_gross_pnl for e in self.entries)

    @property
    def total_pair_gross_pnl(self) -> float:
        return math.fsum(e.pair_gross_pnl for e in self.entries)

    @property
    def total_pair_net_pnl(self) -> float:
        return math.fsum(e.pair_net_pnl for e in self.entries)

    @property
    def total_long_cost(self) -> float:
        return math.fsum(e.long_cost for e in self.entries)

    @property
    def total_short_cost(self) -> float:
        return math.fsum(e.short_cost for e in self.entries)

    @property
    def total_borrow(self) -> float:
        return math.fsum(e.borrow_cost for e in self.entries)

    @property
    def total_funding(self) -> float:
        return math.fsum(e.funding_cost for e in self.entries)

    @property
    def total_basis(self) -> float:
        return math.fsum(e.basis_effect for e in self.entries)

    @property
    def total_costs(self) -> float:
        return self.total_long_cost + self.total_short_cost + self.total_borrow + self.total_funding

    @property
    def total_gross_exposure(self) -> float:
        return math.fsum(e.gross_exposure for e in self.entries)

    @property
    def total_net_exposure(self) -> float:
        return math.fsum(e.net_exposure for e in self.entries)

    def reconcile_pnl(self) -> float:
        """§30 — the residual of the pair-PnL identity (0 when reconciled)."""
        return abs(
            self.total_pair_net_pnl
            - (
                self.total_long_gross_pnl
                + self.total_short_gross_pnl
                - self.total_long_cost
                - self.total_short_cost
                - self.total_borrow
                - self.total_funding
                + self.total_basis
            )
        )

    def reconcile_equity(self, *, unrealized_pnl: float = 0.0) -> float:
        """§30 — residual of the equity identity (0 when reconciled).

        Checks that the reported equity equals the independent reconstruction
        ``initial + realized_net + unrealized`` — i.e. that costs were subtracted
        exactly once.
        """
        state = self.portfolio_state(unrealized_pnl=unrealized_pnl)
        reconstructed = self.initial_capital + self.total_pair_net_pnl + unrealized_pnl
        return abs(state.equity - reconstructed)

    def portfolio_state(self, *, unrealized_pnl: float = 0.0) -> PortfolioState:
        long_notional = math.fsum(e.long_qty * e.long_entry for e in self.entries)
        short_notional = math.fsum(-e.short_qty * e.short_entry for e in self.entries)
        return PortfolioState(
            initial_capital=self.initial_capital,
            cash=self.initial_capital - self.total_gross_exposure + self.total_pair_net_pnl,
            long_notional=long_notional,
            short_notional=short_notional,
            realized_pnl=self.total_pair_gross_pnl,
            unrealized_pnl=unrealized_pnl,
            costs=self.total_costs - self.total_basis,
        )

    def equity_curve(self) -> list[float]:
        """§32 — true equity curve from cumulative realized net PnL."""
        curve: list[float] = []
        running = self.initial_capital
        for e in self.entries:
            running += e.pair_net_pnl
            curve.append(running)
        return curve

    def as_dict(self) -> dict[str, Any]:
        return {
            "initial_capital": self.initial_capital,
            "n_pairs": self.n_pairs,
            "total_long_gross_pnl": self.total_long_gross_pnl,
            "total_short_gross_pnl": self.total_short_gross_pnl,
            "total_pair_gross_pnl": self.total_pair_gross_pnl,
            "total_pair_net_pnl": self.total_pair_net_pnl,
            "total_long_cost": self.total_long_cost,
            "total_short_cost": self.total_short_cost,
            "total_borrow": self.total_borrow,
            "total_funding": self.total_funding,
            "total_basis": self.total_basis,
            "total_costs": self.total_costs,
            "total_gross_exposure": self.total_gross_exposure,
            "total_net_exposure": self.total_net_exposure,
            "pnl_reconciliation_residual": self.reconcile_pnl(),
            "equity_reconciliation_residual": self.reconcile_equity(),
            "entries": [e.as_dict() for e in self.entries],
        }
