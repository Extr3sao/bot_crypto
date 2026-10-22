"""Motor de ejecución (Fase 9).

``live_gate`` se importa de forma perezosa (PEP 562) desde RFC-PAPER-ISOLATION-005.
La razón es concreta: ``live_gate`` importa ``trading_bot.config.settings``, que importa
``trading_bot.config.universe``, que importa ``trading_bot.market_data``, cuyos adapters
necesitan ``isolation`` — el módulo que impide que esos adapters envíen órdenes. Importar
el gate aquí arriba cierra ese círculo y rompe el arranque del runtime paper, que es
justamente el que hay que poder arrancar para demostrar el aislamiento. El nombre público
sigue disponible:

    from trading_bot.execution import LiveTradingGate   # resuelve vía __getattr__
"""

from __future__ import annotations

from typing import Any

from . import isolation

__all__ = [
    "GateReport",
    "GateResult",
    "LiveTradingBlocked",
    "LiveTradingGate",
    "isolation",
]

_LAZY = frozenset({"GateReport", "GateResult", "LiveTradingBlocked", "LiveTradingGate"})


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        from . import live_gate

        return getattr(live_gate, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
