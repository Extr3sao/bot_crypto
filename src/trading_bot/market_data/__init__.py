"""Conectores de mercado + descarga + cache local.

Fase objetivo: 1.

Responsabilidades:
- ``ExchangeConnector``: abstraccion sobre el exchange (CCXT v4+).
  Implementacion actual: ``CCXTExchangeConnector`` (TSK-101,
  Binance-only sandbox-tested via ``SUPPORTED_EXCHANGES_FOR_TSK_101``).
- ``OHLCVFetcher``: pull desde el connector + validate + cache en
  ``OHLCVStore`` (TSK-102). Idempotente: re-fetch no duplica filas
  y preserva last-write-wins para correcciones tardias.

Restricciones:
- No conoce estrategias ni indicadores (regla 11 de ``docs/architecture.md``).
- Todas las llamadas al connector pasan por ``Retry`` (tenacity).
- En sandbox por defecto (TSK-101: whitelist TSK-101 = ``{"binance"}``).
- Persistencia cubierta por TSK-102 SQLite (NO Parquet/CSV; el
  docstring previo incorrecto queda corregido en esta revision).
"""

from trading_bot.market_data.exchange_connector import (
    _KNOWN_STATUS_MAP,
    MULTI_EXCHANGE_SCOPE,
    RETRYABLE_EXCEPTIONS,
    SUPPORTED_EXCHANGES_FOR_TSK_101,
    CCXTExchangeConnector,
    ExchangeConnector,
    UnmappedOrderStatusError,
)
from trading_bot.market_data.fake import (
    FakeMarketDataSource,
    assert_called_once_per_symbol,
    build_demo_fetcher,
    build_demo_settings,
    make_flat_ohlcv,
    make_high_volatility_ohlcv,
)
from trading_bot.market_data.ohlcv_fetcher import OHLCVFetcher
from trading_bot.market_data.types import (
    OHLCV,
    Balance,
    OrderResult,
    OrderStatus,
    OrderType,
    Side,
)

__all__ = [
    "MULTI_EXCHANGE_SCOPE",
    "OHLCV",
    "RETRYABLE_EXCEPTIONS",
    "SUPPORTED_EXCHANGES_FOR_TSK_101",
    "_KNOWN_STATUS_MAP",
    "Balance",
    "CCXTExchangeConnector",
    "ExchangeConnector",
    "FakeMarketDataSource",
    "OHLCVFetcher",
    "OrderResult",
    "OrderStatus",
    "OrderType",
    "Side",
    "UnmappedOrderStatusError",
    "assert_called_once_per_symbol",
    "build_demo_fetcher",
    "build_demo_settings",
    "make_flat_ohlcv",
    "make_high_volatility_ohlcv",
]
