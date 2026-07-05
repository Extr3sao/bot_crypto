"""Commission models for the backtest engine (TSK-104 F2).

Pine contract (TSK-104 F2 + docs/backtesting-methodology.md principle 3):

- ``CommissionModel`` is a ``@runtime_checkable`` Protocol. Any class
  with a ``calculate(notional, qty, price) -> float`` method passes
  ``isinstance(x, CommissionModel)``.
- F1 hard-coded ``commission = notional * self.commission`` (flat-pct);
  F2 makes this pluggable.
- All implementations are deterministic (no random, no I/O) and
  return non-negative floats (commissions are debits, never credits).
- The engine accepts either a ``float`` (backward-compat, auto-wrapped
  in ``FlatPctCommission``) or an explicit ``CommissionModel``.

Anti-patterns (no deben regressar):

- NO devolver valores negativos (los commissions son siempre debitos).
- NO acoplar a ``BacktestEngine``: el protocol permite testear los
  modelos aisladamente.
- NO meter pandas/numpy: el proyecto es pure-Python.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CommissionModel(Protocol):
    """Contrato para cualquier modelo de comision.

    ``calculate(notional, qty, price)`` retorna el commission (en
    unidades de la quote currency, e.g. USDT) para una orden de
    ``qty`` unidades a ``price`` (notional = qty * price). El engine
    descuenta este valor del cash del portfolio.
    """

    def calculate(self, notional: float, qty: float, price: float) -> float:
        """Calcula el commission para una orden.

        ``notional`` y ``qty`` son tipicamente redundantes
        (``notional = qty * price``), pero se pasan ambos para
        permitir modelos que dependen del tamano del trade (e.g.
        maker/taker distinto por tier) ademas del valor.
        """
        ...


class FlatPctCommission:
    """Commission flat-pct (e.g. 0.001 = 10 bps = 0.1%).

    Preserva la semantica exacta de F1: ``commission = notional * rate``.
    Por defecto 0.001 (Binance spot taker tipico).
    """

    def __init__(self, rate: float = 0.001) -> None:
        if rate < 0.0:
            raise ValueError(f"rate must be >= 0, got {rate}")
        self.rate = rate

    def calculate(self, notional: float, qty: float, price: float) -> float:
        """Retorna ``notional * rate``. No clamps; deja el math transparente."""
        return notional * self.rate

    def __repr__(self) -> str:
        return f"FlatPctCommission(rate={self.rate})"


class TieredCommission:
    """Commission por tiers con fixed fee opcional (Binance-like).

    ``tiers`` es una lista de tuplas ``(max_notional, rate)`` ordenada
    ascendente por ``max_notional``. Ejemplo Binance VIP0:
    ``tiers=[(50_000, 0.001), (100_000, 0.0009), (float('inf'), 0.0008)]``
    + ``fixed_fee=0.0`` para spot sin fixed component.

    Pine contract:
    - El tier seleccionado es el primero cuyo ``max_notional >= notional``.
    - Si ``notional`` excede todos los ``max_notional``, se usa el
      ultimo tier (fallback). Esto es el comportamiento esperado en
      exchanges reales (no se rechaza la orden, se cobra el tier mas
      alto).
    - ``fixed_fee`` se suma siempre (e.g. 0.0 para spot, ~0.0 para
      futures perp en muchos exchanges). Usar ``fixed_fee > 0`` para
      pares con componente fijo (e.g. algunos pares de Coinbase Pro).
    """

    def __init__(
        self,
        tiers: list[tuple[float, float]],
        fixed_fee: float = 0.0,
    ) -> None:
        if not tiers:
            raise ValueError("tiers must be non-empty")
        for max_notional, rate in tiers:
            if max_notional < 0:
                raise ValueError(f"tier max_notional must be >= 0, got {max_notional}")
            if rate < 0.0:
                raise ValueError(f"tier rate must be >= 0, got {rate}")
        if fixed_fee < 0.0:
            raise ValueError(f"fixed_fee must be >= 0, got {fixed_fee}")
        # Pine contract: tiers must be sorted ascending by max_notional.
        for i in range(1, len(tiers)):
            if tiers[i][0] < tiers[i - 1][0]:
                raise ValueError(
                    f"tiers must be sorted ascending by max_notional; "
                    f"got tier {i - 1}={tiers[i - 1]} then tier {i}={tiers[i]}"
                )
        self.tiers = tiers
        self.fixed_fee = fixed_fee

    def calculate(self, notional: float, qty: float, price: float) -> float:
        """Encuentra el tier aplicable y retorna ``notional * rate + fixed_fee``."""
        selected_rate = self.tiers[-1][1]  # fallback: last tier
        for max_notional, rate in self.tiers:
            if notional <= max_notional:
                selected_rate = rate
                break
        return notional * selected_rate + self.fixed_fee

    def __repr__(self) -> str:
        return f"TieredCommission(tiers={self.tiers}, fixed_fee={self.fixed_fee})"


__all__ = [
    "CommissionModel",
    "FlatPctCommission",
    "TieredCommission",
]
