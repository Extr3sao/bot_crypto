"""Errores del hub multi-exchange (TSK-022).

Jerarquía canónica definida en `docs/specs/TSK-022-multi-exchange-adapter/03-specify.md`
§4. Los consumers no capturan estos errores para convertirlos en datos u
órdenes válidas; el composition root decide si una sesión aborta, queda en
paper o emite una alerta estructurada.
"""

from __future__ import annotations


class MultiExchangeError(RuntimeError):
    """Base de errores del hub multi-exchange.

    ``RuntimeError`` y no ``AssertionError``: este último se desactiva con
    ``python -O``, lo que silenciaría el fail en producción (misma regla que
    ``UnmappedOrderStatusError`` en TSK-101).
    """


class MultiExchangeConfigurationError(MultiExchangeError):
    """Configuración inválida del universo de exchanges (targets/aliases)."""


class MultiExchangeResolutionError(MultiExchangeError):
    """No se pudo resolver un exchange habilitado; sin fallback silencioso."""


class ConnectorProtocolError(MultiExchangeError):
    """Un adapter emitió un payload que viola el contrato canónico."""


class UnsupportedConnectorOperationError(MultiExchangeError):
    """Operación no soportada por el tipo de mercado del adapter."""


__all__ = [
    "ConnectorProtocolError",
    "MultiExchangeConfigurationError",
    "MultiExchangeError",
    "MultiExchangeResolutionError",
    "UnsupportedConnectorOperationError",
]
