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

Frontera de tipos (TSK-022.1): este módulo reexporta los tipos/guards
públicos canónicos (``CCXTOHLCVProtocol``, ``CCXTPayloadProtocol``,
``narrow_ccxt_ohlcv``, ``narrow_ccxt_payload``), el Protocol de consumo
``MultiExchangeConnector`` y la jerarquía de errores del hub. Es una
frontera de *tipos*, no una exposición de adapters concretos
(``BinanceConnector``, ``BitunixSpotConnector``, ``BitunixFuturesConnector``
no forman parte de este ``__all__``; la frontera cross-layer RF-MX-4 /
ADR-0013 la pinea ``tests/unit/market_data/test_cross_layer.py``).
"""

from trading_bot.market_data.exceptions import (
    ConnectorProtocolError,
    MultiExchangeConfigurationError,
    MultiExchangeError,
    MultiExchangeResolutionError,
    UnsupportedConnectorOperationError,
)
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
    CCXTOHLCVProtocol,
    CCXTPayloadProtocol,
    ExchangeMarketType,
    MarketRules,
    MultiExchangeConnector,
    OrderResult,
    OrderStatus,
    OrderType,
    Side,
    narrow_ccxt_ohlcv,
    narrow_ccxt_payload,
)

__all__ = [
    "MULTI_EXCHANGE_SCOPE",
    "OHLCV",
    "RETRYABLE_EXCEPTIONS",
    "SUPPORTED_EXCHANGES_FOR_TSK_101",
    "_KNOWN_STATUS_MAP",
    "Balance",
    "CCXTExchangeConnector",
    "CCXTOHLCVProtocol",
    "CCXTPayloadProtocol",
    "ConnectorProtocolError",
    "ExchangeConnector",
    "ExchangeMarketType",
    "FakeMarketDataSource",
    "MarketRules",
    "MultiExchangeConfigurationError",
    "MultiExchangeConnector",
    "MultiExchangeError",
    "MultiExchangeResolutionError",
    "OHLCVFetcher",
    "OrderResult",
    "OrderStatus",
    "OrderType",
    "Side",
    "UnmappedOrderStatusError",
    "UnsupportedConnectorOperationError",
    "assert_called_once_per_symbol",
    "build_demo_fetcher",
    "build_demo_settings",
    "make_flat_ohlcv",
    "make_high_volatility_ohlcv",
    "narrow_ccxt_ohlcv",
    "narrow_ccxt_payload",
]
