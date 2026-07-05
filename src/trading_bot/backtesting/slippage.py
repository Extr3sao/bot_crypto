"""Slippage models for the backtest engine (TSK-104 F2).

Pine contract (TSK-104 F2 + docs/backtesting-methodology.md principle 3):

- ``SlippageModel`` is a ``@runtime_checkable`` Protocol. Any class
  with a ``calculate(price, qty, side, volume) -> float`` method
  passes ``isinstance(x, SlippageModel)``.
- F1 hard-coded ``slippage = price * (bps / 10_000)`` (flat,
  always a-favor-del-market: engine adds to buy, subtracts to sell).
  F2 makes this pluggable.
- All implementations are deterministic and return non-negative floats
  (slippage es la distancia absoluta que el precio se mueve contra el
  trader; el engine decide si suma o resta segun ``side``).
- The engine accepts either a ``float`` (backward-compat, auto-wrapped
  in ``FlatBpsSlippage``) or an explicit ``SlippageModel``.

Anti-patterns (no deben regressar):

- NO devolver valores negativos (slippage es siempre distancia >= 0).
- NO acoplar a ``BacktestEngine``: el protocol permite testear los
  modelos aisladamente.
- NO meter pandas/numpy: el proyecto es pure-Python.
"""

from __future__ import annotations

import math
from typing import Literal, Protocol, runtime_checkable


@runtime_checkable
class SlippageModel(Protocol):
    """Contrato para cualquier modelo de slippage.

    ``calculate(price, qty, side, volume)`` retorna la distancia
    absoluta (en unidades del quote) que el fill price se desviaria
    del precio del candle. El engine luego:

    - Para ``side == "buy"``: ``fill_price = candle.close + slippage``
    - Para ``side == "sell"``: ``fill_price = candle.close - slippage``
    """

    def calculate(
        self,
        price: float,
        qty: float,
        side: Literal["buy", "sell"],
        volume: float,
    ) -> float:
        """Calcula el slippage absoluto (no signed) para una orden.

        ``volume`` es el volumen de la vela (del ``OHLCV.volume``);
        se usa para modelos volume-weighted. Si el modelo no lo
        necesita, lo ignora.
        """
        ...


class FlatBpsSlippage:
    """Slippage flat en basis points (e.g. 5.0 bps = 0.05%).

    Preserva la semantica exacta de F1: ``slippage = price * (bps / 10_000)``.
    No distingue entre buy/sell; el engine aplica el signo segun side.
    """

    def __init__(self, bps: float = 5.0) -> None:
        if bps < 0.0:
            raise ValueError(f"bps must be >= 0, got {bps}")
        self.bps = bps

    def calculate(
        self,
        price: float,
        qty: float,
        side: Literal["buy", "sell"],
        volume: float,
    ) -> float:
        """Retorna ``price * (bps / 10_000)``. ``side`` y ``volume`` ignorados."""
        return price * (self.bps / 10_000.0)

    def __repr__(self) -> str:
        return f"FlatBpsSlippage(bps={self.bps})"


class VolumeImpactSlippage:
    """Slippage volume-weighted (square-root price impact model).

    Modelo realista para mercados de cripto: el slippage depende de
    cuanto del volumen de la vela consume la orden. Formula:

        slippage = price * (base_bps / 10_000)
                 + impact_coef * sqrt(qty / max(volume, 1e-8))

    Pine contract:
    - ``base_bps`` es el slippage piso (independiente de qty).
    - ``impact_coef`` escala el componente variable; tipicamente
      pequeno (e.g. 0.01 a 0.1). Calibrar con datos de fill reales
      del exchange target.
    - ``volume = 0`` no crashea: se usa ``max(volume, 1e-8)`` para
      evitar division por zero.
    - El termino ``sqrt(qty / volume)`` modela el "depth" del order
      book: ordenes que consumen mas volumen cruzan mas niveles y
      pagan mas slippage.
    """

    def __init__(self, base_bps: float = 2.0, impact_coef: float = 0.01) -> None:
        if base_bps < 0.0:
            raise ValueError(f"base_bps must be >= 0, got {base_bps}")
        if impact_coef < 0.0:
            raise ValueError(f"impact_coef must be >= 0, got {impact_coef}")
        self.base_bps = base_bps
        self.impact_coef = impact_coef

    def calculate(
        self,
        price: float,
        qty: float,
        side: Literal["buy", "sell"],
        volume: float,
    ) -> float:
        """Retorna ``price * (base_bps / 10_000) + impact_coef * sqrt(qty / max(volume, 1e-8))``.

        ``side`` no se usa (el modelo es side-symmetric; el engine
        aplica el signo segun side). ``volume`` se clampa a 1e-8
        para evitar ``ZeroDivisionError`` en velas sin volumen.
        """
        base = price * (self.base_bps / 10_000.0)
        # Clamp volume para evitar ZeroDivisionError en velas sin volumen.
        impact = self.impact_coef * math.sqrt(qty / max(volume, 1e-8))
        return base + impact

    def __repr__(self) -> str:
        return f"VolumeImpactSlippage(base_bps={self.base_bps}, impact_coef={self.impact_coef})"


__all__ = [
    "FlatBpsSlippage",
    "SlippageModel",
    "VolumeImpactSlippage",
]
