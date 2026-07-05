"""Protocolos abstractos del scanner.

Define el contrato que cualquier ``MarketDataSource`` implementador
(de ``OHLCVFetcher`` + ``OHLCVStore`` en produccion, o
``FakeMarketDataSource`` en tests) debe cumplir, asi como el contrato
de un ``Filter`` individual. No son ``ABC`` concretos: usar
``typing.Protocol`` con ``runtime_checkable`` cuando conviene
permite type-check de pato estructural sin forzar herencia, lo que
simplifica las tests con mocks.

Regla desacople (``docs/architecture.md`` §11 + §14, pineada por el
test ``test_cross_layer.py`` en TSK-103.4.9):

- ``MarketDataSourceProtocol`` se implementa en ``market_data/`` con
  la composicion ``OHLCVFetcher`` + ``OHLCVStore`` (TSK-102). El
  ``UniverseScanner`` (TSK-103.4) NO importa ``fetcher.fetch_recent``
  ni ``store.get_ohlcv`` directamente; solo conoce este Protocol.
- ``Filter`` se implementa en ``scanner/filters.py`` (TSK-103.2).
  Cada filtro encapsula una sola decision (SRP) y no conoce al
  orquestador ni a otros filtros.

Async: la implementacion CCXT en ``market_data/exchange_connector.py``
es async via Tenacity decorator; ``OHLCVFetcher`` envuelve ese async.
El ``UniverseScanner`` invocara estos metodos con ``await``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from trading_bot.market_data.types import OHLCV
from trading_bot.scanner.types import FilterOutcome


@runtime_checkable
class MarketDataSourceProtocol(Protocol):
    """Abstraccion sobre OHLCVFetcher + OHLCVStore (Decision D2 del spec).

    ``runtime_checkable=True`` permite ``isinstance(fake, MarketDataSourceProtocol)``
    en tests unitarios sin importar ABC. mypy strict + Protocol detecta
    implementaciones parciales en compile-time; aqui solo cubrimos
    validacion runtime (P3 del reviewer de TSK-101 round-3).
    """

    async def fetch_recent(
        self, symbol: str, limit: int = 100
    ) -> list[OHLCV]:
        """Devuelve las ``limit`` velas mas recientes de ``symbol``.

        El conector CCXT (TSK-101) ya inyecta ``symbol`` en cada vela
        (round-2 P1 fix), por lo que downstream el discriminador
        ``row.symbol == expected`` ya no es necesario defensivamente.
        """
        ...

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        """Volumen rolling 24h en USDT (entrada para ``VolumeFilter``)."""
        ...

    async def fetch_spread_bps(self, symbol: str) -> float:
        """Spread top-of-book actual en basis points (entrada para ``SpreadFilter``)."""
        ...


class Filter(Protocol):
    """Filtro abstracto sobre un par (TSK-103.2).

    Una implementacion decide activo/inactivo y devuelve un
    ``FilterOutcome``. NO conoce al ``UniverseScanner`` ni a otros
    filtros: encapsula una sola decision (SRP). El orden lo gestiona
    ``FilterRegistry`` (TSK-103.2.1).

    NO es ``runtime_checkable``: el atributo ``name`` es field de
    clase (no metodo) y los ``Protocol`` estructurales con atributos
    no-metodo presentan problemas con ``isinstance`` checks. El test
    ``test_protocols.py::test_filter_protocol_attr_name`` pinea el
    contrato via ``hasattr`` en lugar de ``isinstance``. Mypy strict
    cubre la validacion en compile-time.
    """

    name: str

    async def apply(
        self, symbol: str, source: MarketDataSourceProtocol
    ) -> FilterOutcome:
        """Devuelve ``FilterOutcome(passed=True)`` o ``(passed=False, reason=...)``."""
        ...


__all__ = ["Filter", "MarketDataSourceProtocol"]
