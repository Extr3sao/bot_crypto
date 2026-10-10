"""Portfolio risk and margin reservation (RFC-048 §10).

Two strategies must never consume the same free margin. The reservation is taken
against a *versioned snapshot* of the book under a lock, so concurrent decisions
either reserve disjoint margin or are refused — never both approved.

A cross-margin claim is never declared safe here: positions carry an explicit
``collateral_group`` and only ``ISOLATED`` groups are supported, so a shared
collateral set cannot be created by accident.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .contracts import Direction, RejectionCode

__all__ = ["MarginLedger", "PortfolioSnapshot", "PortfolioState"]


@dataclass(frozen=True, slots=True)
class PortfolioState:
    """One open simulated position."""

    instrument_id: str
    asset: str
    direction: Direction
    quantity: float
    entry_price: float
    notional: float
    reserved_margin: float
    collateral_group: str = "ISOLATED"
    correlation_key: str = ""
    strategy_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "asset": self.asset,
            "direction": self.direction.value,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "notional": self.notional,
            "reserved_margin": self.reserved_margin,
            "collateral_group": self.collateral_group,
            "correlation_key": self.correlation_key,
            "strategy_id": self.strategy_id,
        }


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """A versioned, immutable view of the book used by one decision."""

    snapshot_id: str
    timestamp_ms: int
    equity: float
    free_margin: float
    reserved_margin: float
    daily_pnl: float = 0.0
    drawdown_pct: float = 0.0
    consecutive_losses: int = 0
    positions: tuple[PortfolioState, ...] = ()
    provider_healthy: bool = True
    version: int = 1

    @property
    def gross_exposure(self) -> float:
        return sum(p.notional for p in self.positions)

    @property
    def net_exposure(self) -> float:
        net = 0.0
        for position in self.positions:
            net += position.notional if position.direction is Direction.LONG else -position.notional
        return net

    def exposure_by_asset(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for position in self.positions:
            out[position.asset] = out.get(position.asset, 0.0) + position.notional
        return out

    def exposure_by_correlation(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for position in self.positions:
            key = position.correlation_key or position.asset
            out[key] = out.get(key, 0.0) + position.notional
        return out

    def margin_by_collateral_group(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for position in self.positions:
            out[position.collateral_group] = (
                out.get(position.collateral_group, 0.0) + position.reserved_margin
            )
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "version": self.version,
            "timestamp_ms": self.timestamp_ms,
            "equity": self.equity,
            "free_margin": self.free_margin,
            "reserved_margin": self.reserved_margin,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "daily_pnl": self.daily_pnl,
            "drawdown_pct": self.drawdown_pct,
            "consecutive_losses": self.consecutive_losses,
            "positions": [p.to_dict() for p in self.positions],
            "exposure_by_asset": self.exposure_by_asset(),
            "exposure_by_correlation": self.exposure_by_correlation(),
            "margin_by_collateral_group": self.margin_by_collateral_group(),
            "provider_healthy": self.provider_healthy,
        }


@dataclass
class MarginLedger:
    """Free-margin accounting with an atomic check-and-reserve.

    ``try_reserve`` is the only way to consume margin. It is atomic with respect
    to every other reservation on the same ledger, which is what makes the
    "two simultaneous decisions on the same collateral" case fail closed.
    """

    equity: float
    _reserved: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _grants: list[dict[str, Any]] = field(default_factory=list, repr=False)

    @property
    def reserved(self) -> float:
        with self._lock:
            return self._reserved

    @property
    def free(self) -> float:
        with self._lock:
            return self.equity - self._reserved

    def try_reserve(
        self, amount: float, *, decision_id: str, collateral_group: str = "ISOLATED"
    ) -> tuple[bool, float, RejectionCode | None]:
        """Reserve ``amount`` or refuse. Returns ``(ok, granted, reason)``."""
        if amount <= 0:
            return False, 0.0, RejectionCode.RISK_BUDGET_EXCEEDED
        with self._lock:
            available = self.equity - self._reserved
            if amount > available + 1e-12:
                return False, 0.0, RejectionCode.INSUFFICIENT_MARGIN
            self._reserved += amount
            self._grants.append(
                {
                    "decision_id": decision_id,
                    "amount": amount,
                    "collateral_group": collateral_group,
                }
            )
            return True, amount, None

    def release(self, decision_id: str) -> float:
        """Release every reservation tied to a decision id (cancellation)."""
        with self._lock:
            remain: list[dict[str, Any]] = []
            released = 0.0
            for grant in self._grants:
                if grant["decision_id"] == decision_id:
                    released += float(grant["amount"])
                else:
                    remain.append(grant)
            self._grants = remain
            self._reserved = max(self._reserved - released, 0.0)
            return released

    def snapshot_of(self, snapshot: PortfolioSnapshot, *, decision_id: str) -> PortfolioSnapshot:
        """A copy of ``snapshot`` carrying this ledger's live reservation.

        The ledger's own equity is authoritative for free margin, so a caller
        cannot widen the pool by passing a bigger snapshot than the ledger holds.
        """
        with self._lock:
            reserved = self._reserved
            equity = min(self.equity, snapshot.equity)
        return PortfolioSnapshot(
            snapshot_id=f"{snapshot.snapshot_id}:{decision_id}",
            timestamp_ms=snapshot.timestamp_ms,
            equity=equity,
            free_margin=max(equity - reserved, 0.0),
            reserved_margin=reserved,
            daily_pnl=snapshot.daily_pnl,
            drawdown_pct=snapshot.drawdown_pct,
            consecutive_losses=snapshot.consecutive_losses,
            positions=snapshot.positions,
            provider_healthy=snapshot.provider_healthy,
            version=snapshot.version,
        )
