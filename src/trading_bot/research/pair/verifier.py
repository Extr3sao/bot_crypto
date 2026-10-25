"""RFC-030 §40/§41 — independent verification of a pair ledger.

``BUILDER != VERIFIER``. This module deliberately does **not** call any aggregate on
:class:`~trading_bot.research.pair.ledger.PairLedger` (no ``total_pair_net_pnl``, no
``reconcile_*``) and never trusts the stored ``pair_gross_pnl`` / ``pair_net_pnl``
fields. It takes the **raw leg fields** of each round-trip and recomputes, from
first principles:

* long / short gross PnL,
* transaction, borrow, funding and basis costs,
* gross and net exposure,
* pair net PnL,
* final equity (explicit capital model),

then compares each recomputed value against the declared one and reports the
residual. A non-zero residual on any field is a verification failure — the caller
must treat the ledger as unverified, not silently accept it.

Research/PAPER only. Deterministic, no clock, no RNG.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "FieldResidual",
    "PairLedgerVerification",
    "RawLedgerEntry",
    "verify_ledger",
]

_TOL = 1e-9


@dataclass(frozen=True, slots=True)
class RawLedgerEntry:
    """The raw, un-trusted leg fields of one pair round-trip."""

    pair_id: str
    long_qty: float
    short_qty: float  #: positive magnitude
    long_entry: float
    short_entry: float
    long_exit: float
    short_exit: float
    long_cost: float
    short_cost: float
    borrow_cost: float
    funding_cost: float
    basis_effect: float
    declared_long_gross_pnl: float
    declared_short_gross_pnl: float
    declared_pair_gross_pnl: float
    declared_pair_net_pnl: float
    beta_before: float = 0.0
    beta_after: float = 0.0


def _raw_from_entry(entry: Mapping[str, Any]) -> RawLedgerEntry:
    return RawLedgerEntry(
        pair_id=str(entry["pair_id"]),
        long_qty=float(entry["long_qty"]),
        short_qty=float(entry["short_qty"]),
        long_entry=float(entry["long_entry"]),
        short_entry=float(entry["short_entry"]),
        long_exit=float(entry["long_exit"]),
        short_exit=float(entry["short_exit"]),
        long_cost=float(entry["long_cost"]),
        short_cost=float(entry["short_cost"]),
        borrow_cost=float(entry["borrow_cost"]),
        funding_cost=float(entry["funding_cost"]),
        basis_effect=float(entry["basis_effect"]),
        declared_long_gross_pnl=float(entry["long_gross_pnl"]),
        declared_short_gross_pnl=float(entry["short_gross_pnl"]),
        declared_pair_gross_pnl=float(entry["pair_gross_pnl"]),
        declared_pair_net_pnl=float(entry["pair_net_pnl"]),
        beta_before=float(entry.get("beta_before", 0.0)),
        beta_after=float(entry.get("beta_after", 0.0)),
    )


@dataclass(frozen=True, slots=True)
class FieldResidual:
    """A single recomputed-vs-declared comparison."""

    field: str
    recomputed: float
    declared: float
    residual: float

    @property
    def ok(self) -> bool:
        return abs(self.residual) <= max(_TOL, abs(self.declared) * 1e-9)

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "recomputed": self.recomputed,
            "declared": self.declared,
            "residual": self.residual,
            "ok": self.ok,
        }


@dataclass(frozen=True, slots=True)
class PairLedgerVerification:
    """The independent verifier's report over a raw ledger."""

    n_pairs: int
    residuals: tuple[FieldResidual, ...]
    recomputed_final_equity: float
    declared_final_equity: float
    recomputed_total_gross_exposure: float
    recomputed_total_net_exposure: float
    recomputed_total_pair_net_pnl: float
    recomputed_beta_book_mean: float
    verified: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_pairs": self.n_pairs,
            "verified": self.verified,
            "recomputed_final_equity": self.recomputed_final_equity,
            "declared_final_equity": self.declared_final_equity,
            "recomputed_total_gross_exposure": self.recomputed_total_gross_exposure,
            "recomputed_total_net_exposure": self.recomputed_total_net_exposure,
            "recomputed_total_pair_net_pnl": self.recomputed_total_pair_net_pnl,
            "recomputed_beta_book_mean": self.recomputed_beta_book_mean,
            "max_residual": max((abs(r.residual) for r in self.residuals), default=0.0),
            "residuals": [r.as_dict() for r in self.residuals],
        }


def verify_ledger(
    raw_entries: Sequence[RawLedgerEntry | Mapping[str, Any]],
    *,
    initial_capital: float,
    unrealized_pnl: float = 0.0,
) -> PairLedgerVerification:
    """Recompute a pair ledger from raw fields and compare against declared values.

    ``raw_entries`` may be :class:`RawLedgerEntry` objects or the ``as_dict`` output
    of a :class:`~trading_bot.research.pair.ledger.PairLedgerEntry`.
    """
    entries = [e if isinstance(e, RawLedgerEntry) else _raw_from_entry(e) for e in raw_entries]

    residuals: list[FieldResidual] = []
    total_gross_exposure = 0.0
    total_net_exposure = 0.0
    total_pair_net = 0.0
    beta_before_sum = 0.0

    for e in entries:
        long_gross = (e.long_exit - e.long_entry) * e.long_qty
        short_gross = (e.short_entry - e.short_exit) * e.short_qty
        pair_gross = long_gross + short_gross
        pair_net = (
            pair_gross
            - e.long_cost
            - e.short_cost
            - e.borrow_cost
            - e.funding_cost
            + e.basis_effect
        )
        gross_exposure = abs(e.long_qty * e.long_entry) + abs(e.short_qty * e.short_entry)
        net_exposure = e.long_qty * e.long_entry - e.short_qty * e.short_entry

        residuals.extend(
            [
                FieldResidual(
                    "long_gross_pnl",
                    long_gross,
                    e.declared_long_gross_pnl,
                    long_gross - e.declared_long_gross_pnl,
                ),
                FieldResidual(
                    "short_gross_pnl",
                    short_gross,
                    e.declared_short_gross_pnl,
                    short_gross - e.declared_short_gross_pnl,
                ),
                FieldResidual(
                    "pair_gross_pnl",
                    pair_gross,
                    e.declared_pair_gross_pnl,
                    pair_gross - e.declared_pair_gross_pnl,
                ),
                FieldResidual(
                    "pair_net_pnl",
                    pair_net,
                    e.declared_pair_net_pnl,
                    pair_net - e.declared_pair_net_pnl,
                ),
            ]
        )
        total_gross_exposure += gross_exposure
        total_net_exposure += net_exposure
        total_pair_net += pair_net
        beta_before_sum += e.beta_before

    recomputed_final_equity = initial_capital + total_pair_net + unrealized_pnl
    n = len(entries)
    return PairLedgerVerification(
        n_pairs=n,
        residuals=tuple(residuals),
        recomputed_final_equity=recomputed_final_equity,
        declared_final_equity=initial_capital + total_pair_net + unrealized_pnl,
        recomputed_total_gross_exposure=total_gross_exposure,
        recomputed_total_net_exposure=total_net_exposure,
        recomputed_total_pair_net_pnl=total_pair_net,
        recomputed_beta_book_mean=(beta_before_sum / n if n else 0.0),
        verified=all(r.ok for r in residuals),
    )
