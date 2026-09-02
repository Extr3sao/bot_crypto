"""Registry/factory lazy del hub multi-exchange (TSK-022.2).

Resuelve un target habilitado exactamente una vez, cacheando la instancia por
``exchange_id`` dentro del registry. No realiza I/O ni llama a
``load_markets()`` durante el import o el constructor: la construcción del
conector ocurre únicamente en el primer ``resolve(...)``. No existe fallback
implícito a Binance.

Contrato (``03-specify.md`` §2.2):

- ``targets`` debe tener IDs únicos y solo los targets habilitados pueden
  resolverse.
- ``factory_by_id`` debe cubrir cada target habilitado; la instancia se
  construye solo en el primer ``resolve(id)``.
- ``resolve`` cachea por ``exchange_id``; un ID vacío, desconocido o
  deshabilitado produce ``MultiExchangeResolutionError`` con los IDs
  habilitados ordenados. Un target duplicado o habilitado sin factory produce
  ``MultiExchangeConfigurationError`` en la construcción (fail-fast antes de
  iniciar sesión).
- El registry no registra secretos ni expone credenciales.

Frontera: el registry se construye en el composition root (Settings/wiring),
nunca en ``scanner``, ``strategies`` ni ``execution``. Esos paquetes reciben
únicamente ``MultiExchangeConnector`` por inyección de dependencias.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from trading_bot.market_data.exceptions import (
    MultiExchangeConfigurationError,
    MultiExchangeResolutionError,
)
from trading_bot.market_data.types import MultiExchangeConnector


class ExchangeTargetSpec(Protocol):
    """Vista estructural mínima de un target que consume el registry.

    TSK-022.3 introducirá el modelo concreto ``ExchangeTarget`` (pydantic) en la
    capa de configuración; el registry depende únicamente de esta vista
    estructural para no acoplarse a ``config``. Cualquier modelo con
    ``id: str`` y ``enabled: bool`` la satisface (subtipado estructural).

    No se marca ``@runtime_checkable``: al contener solo miembros de datos,
    ``isinstance`` no podría verificarlos y devolvería ``True`` de forma
    engañosa. Es un contrato de tipos estáticos, no un guard de runtime.
    """

    id: str
    enabled: bool


class MultiExchangeConnectorRegistry:
    """Resuelve y cachea conectores por ``exchange_id``, sin I/O eager."""

    def __init__(
        self,
        *,
        targets: Mapping[str, ExchangeTargetSpec],
        factory_by_id: Mapping[str, Callable[[], MultiExchangeConnector]],
    ) -> None:
        self._targets = dict(targets)
        self._factory_by_id = dict(factory_by_id)
        self._cache: dict[str, MultiExchangeConnector] = {}

        # Fail-fast de configuración, antes de iniciar sesión.
        for key, target in self._targets.items():
            if target.id != key:
                raise MultiExchangeConfigurationError(
                    f"Target bajo la clave {key!r} declara id {target.id!r}: "
                    "los IDs deben ser únicos y coincidir con su clave "
                    "(posible id duplicado)."
                )

        missing_factories = sorted(
            key
            for key, target in self._targets.items()
            if target.enabled and key not in self._factory_by_id
        )
        if missing_factories:
            raise MultiExchangeConfigurationError(
                "Targets habilitados sin factory: "
                f"{missing_factories}. El registry exige una factory por "
                "target habilitado antes de iniciar sesión."
            )

    def _enabled_ids(self) -> list[str]:
        """IDs habilitados, ordenados (para mensajes de error deterministas)."""
        return sorted(key for key, target in self._targets.items() if target.enabled)

    def resolve(self, exchange_id: str) -> MultiExchangeConnector:
        """Resuelve (construyendo y cacheando) el conector de un target habilitado.

        Sin fallback implícito a Binance: un ID vacío, desconocido o
        deshabilitado falla loud con ``MultiExchangeResolutionError`` y los IDs
        habilitados ordenados.
        """
        if not exchange_id or not exchange_id.strip():
            raise MultiExchangeResolutionError(
                "exchange_id vacío; el registry no aplica fallback implícito. "
                f"IDs habilitados: {self._enabled_ids()}."
            )

        target = self._targets.get(exchange_id)
        if target is None:
            raise MultiExchangeResolutionError(
                f"exchange_id {exchange_id!r} desconocido. IDs habilitados: {self._enabled_ids()}."
            )
        if not target.enabled:
            raise MultiExchangeResolutionError(
                f"exchange_id {exchange_id!r} deshabilitado. "
                f"IDs habilitados: {self._enabled_ids()}."
            )

        if exchange_id in self._cache:
            return self._cache[exchange_id]

        connector = self._factory_by_id[exchange_id]()
        self._cache[exchange_id] = connector
        return connector


__all__ = [
    "ExchangeTargetSpec",
    "MultiExchangeConnectorRegistry",
]
