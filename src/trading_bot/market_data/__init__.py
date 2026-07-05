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
    CCXTExchangeConnector,
    ExchangeConnector,
    MULTI_EXCHANGE_SCOPE,
    SUPPORTED_EXCHANGES_FOR_TSK_101,
    RETRYABLE_EXCEPTIONS,
    UnmappedOrderStatusError,
    _KNOWN_STATUS_MAP,
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
    Balance,
    OHLCV,
    OrderResult,
    OrderStatus,
    OrderType,
    Side,
)

__all__ = [
    "CCXTExchangeConnector",
    "ExchangeConnector",
    "FakeMarketDataSource",
    "MULTI_EXCHANGE_SCOPE",
    "OHLCVFetcher",
    "RETRYABLE_EXCEPTIONS",
    "SUPPORTED_EXCHANGES_FOR_TSK_101",
    "Side",
    "Balance",
    "OHLCV",
    "OrderResult",
    "OrderStatus",
    "OrderType",
    "UnmappedOrderStatusError",
    "_KNOWN_STATUS_MAP",
    "assert_called_once_per_symbol",
    "build_demo_fetcher",
    "build_demo_settings",
    "make_flat_ohlcv",
    "make_high_volatility_ohlcv",
]
