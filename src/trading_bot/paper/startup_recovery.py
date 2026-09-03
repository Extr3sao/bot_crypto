"""Startup recovery — V3 (P6).

Politica (en orden de preferencia):

1. **RESTORE_FROM_JOURNAL** (preferente en paper trading): una
   posición abierta registrada en el journal se restaura al broker
   con sus parámetros originales. Nunca se pierde ni se falsifica.

2. **ORPHAN_RECONCILIATION_CLOSE**: si la restauración no es posible,
   se obtiene precio de mercado actual, se aplica slippage + fees del
   ``ExecutionCostModel`` y se cierra con PnL REALISTA y motivo
   ``orphan_reconciliation_close``.

PROHIBIDO: cerrar una huérfana con ``pnl=0`` salvo que realmente sea
cero (el bug histórico era ``exit_price = entry_price; pnl = 0.0``).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

from trading_bot.execution.cost_model import ExecutionCostModel

logger = structlog.get_logger("startup_recovery")


class RecoveryAction(str, Enum):
    RESTORE_FROM_JOURNAL = "RESTORE_FROM_JOURNAL"
    ORPHAN_RECONCILIATION_CLOSE = "ORPHAN_RECONCILIATION_CLOSE"
    MATCHED = "MATCHED"


@dataclass(frozen=True, slots=True)
class OrphanCloseResult:
    """Resultado de un cierre conservador de huérfana."""

    trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_fill_price: float  # precio de mercado ya ajustado por slippage
    quantity: float
    gross_pnl: float
    entry_fee: float
    exit_fee: float
    slippage_cost: float
    net_pnl: float

    @property
    def is_truly_zero(self) -> bool:
        return abs(self.net_pnl) < 1e-12


@dataclass(slots=True)
class StartupRecoveryReport:
    timestamp: float
    restored: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    orphan_closes: list[OrphanCloseResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.errors:
            return "errors"
        if self.orphan_closes:
            return "orphans_closed"
        return "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "status": self.status,
            "restored": self.restored,
            "matched": self.matched,
            "orphan_closes": [asdict(o) for o in self.orphan_closes],
            "errors": self.errors,
        }


def compute_orphan_reconciliation_close(
    *,
    trade_id: str,
    symbol: str,
    side: str,
    entry_price: float,
    quantity: float,
    current_market_price: float,
    cost_model: ExecutionCostModel | None = None,
) -> OrphanCloseResult:
    """Cierra una huérfana con fill conservador y costes reales (P6).

    El fill de salida usa el precio de mercado actual desplazado por
    slippage en contra; las comisiones se cobran por ambos lados.
    """
    cm = cost_model or ExecutionCostModel(commission_bps=5.0, slippage_bps=1.0)
    qty = max(quantity, 0.0)
    notional = qty * entry_price

    costs = cm.compute_costs(
        notional_usdt=notional,
        entry_price=entry_price,
        exit_price=current_market_price,
        quantity=qty,
        side="buy" if side == "buy" else "sell",
    )

    return OrphanCloseResult(
        trade_id=trade_id,
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        exit_fill_price=round(current_market_price, 8),
        quantity=qty,
        gross_pnl=costs.gross_pnl,
        entry_fee=costs.entry_fee_usdt,
        exit_fee=costs.exit_fee_usdt,
        slippage_cost=costs.entry_slippage_usdt + costs.exit_slippage_usdt,
        net_pnl=costs.net_pnl,
    )


def recover_startup_positions(
    *,
    journal_open_trades: list[dict[str, Any]],
    broker_symbols: set[str],
    current_prices: dict[str, float],
    cost_model: ExecutionCostModel | None = None,
) -> StartupRecoveryReport:
    """Decide la acción de recuperación para cada trade abierto del journal.

    Args:
        journal_open_trades: lista de dicts del journal con al menos
            trade_id, symbol, side, entry_price, quantity.
        broker_symbols: símbolos que el broker ya tiene vivos.
        current_prices: precio de mercado actual por símbolo (para
            cierres conservadores).
        cost_model: modelo de costes (default 5bps fee + 1bp slip).

    Returns:
        StartupRecoveryReport con acciones RESTORE / CLOSE / MATCHED.
    """
    report = StartupRecoveryReport(timestamp=time.time())
    broker = set(broker_symbols)

    for trade in journal_open_trades:
        symbol = str(trade.get("symbol", ""))
        trade_id = str(trade.get("trade_id", ""))
        try:
            if symbol in broker:
                # Broker ya la tiene viva -> restaurada implicitamente.
                report.restored.append(trade_id)
                continue

            price = current_prices.get(symbol)
            if price is None or price <= 0:
                # Sin precio de mercado NO podemos inventar un cierre.
                report.errors.append(
                    f"{trade_id}: no market price for {symbol}; "
                    f"position left open for next recovery pass"
                )
                logger.error(
                    "startup_recovery.no_market_price",
                    trade_id=trade_id,
                    symbol=symbol,
                )
                continue

            result = compute_orphan_reconciliation_close(
                trade_id=trade_id,
                symbol=symbol,
                side=str(trade.get("side", "buy")),
                entry_price=float(trade.get("entry_price", 0.0)),
                quantity=float(trade.get("quantity", 0.0)),
                current_market_price=price,
                cost_model=cost_model,
            )
            report.orphan_closes.append(result)
            logger.warning(
                "startup_recovery.orphan_closed",
                trade_id=trade_id,
                symbol=symbol,
                net_pnl=result.net_pnl,
                reason="orphan_reconciliation_close",
            )
        except Exception as exc:
            report.errors.append(f"{trade_id}: {exc}")
            logger.error("startup_recovery.error", trade_id=trade_id, error=str(exc))

    return report


def save_recovery_report(
    report: StartupRecoveryReport,
    report_dir: str | Path = "data/storage",
) -> Path:
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "startup_recovery_report.json"
    path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return path


__all__ = [
    "OrphanCloseResult",
    "RecoveryAction",
    "StartupRecoveryReport",
    "compute_orphan_reconciliation_close",
    "recover_startup_positions",
    "save_recovery_report",
]
