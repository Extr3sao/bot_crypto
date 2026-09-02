"""Puente hub multi-exchange -> scanner (TSK-022).

``MultiExchangeConnector`` es síncrono; el ``UniverseScanner`` consume
``MarketDataSourceProtocol`` async. ``HubMarketDataSource`` adapta el
connector resuelto por el composition root al contrato del scanner sin
tocar los adapters: las llamadas síncronas se ejecutan en un thread
(``asyncio.to_thread``) para no bloquear el event loop.

Volumen 24h y spread vienen del adapter (ticker/order book reales), nunca
se fabrican; un adapter que no los soporte (p. ej. Bitunix futures) falla
loud en vez de inventar valores (regla fail-closed del hub).
"""

from __future__ import annotations

import asyncio

from trading_bot.market_data.types import OHLCV, MultiExchangeConnector


class HubMarketDataSource:
    """Implementa ``MarketDataSourceProtocol`` sobre un ``MultiExchangeConnector``.

    ``timeframe`` se fija en la construcción (el Protocol del scanner no
    lleva timeframe): normalmente ``settings.universe.timeframes[0]`` vía
    ``wiring.resolve_scanner_source``.
    """

    def __init__(self, connector: MultiExchangeConnector, *, timeframe: str) -> None:
        self._connector = connector
        self._timeframe = timeframe

    @property
    def connector(self) -> MultiExchangeConnector:
        """El connector del hub resuelto (compartido con la ejecución).

        Permite que el composition root reutilice la MISMA instancia para el
        scanner y para el path de ejecución (create_order/fetch_balance),
        evitando resolver dos conectores para una misma sesión.
        """
        return self._connector

    @property
    def exchange_id(self) -> str:
        return self._connector.exchange_id

    @property
    def timeframe(self) -> str:
        return self._timeframe

    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        return await asyncio.to_thread(self._connector.fetch_ohlcv, symbol, self._timeframe, limit)

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        return await asyncio.to_thread(self._connector.fetch_24h_volume_usdt, symbol)

    async def fetch_spread_bps(self, symbol: str) -> float:
        return await asyncio.to_thread(self._connector.fetch_spread_bps, symbol)


__all__ = ["HubMarketDataSource"]
