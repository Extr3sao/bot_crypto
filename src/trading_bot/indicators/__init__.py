"""Motor enchufable de indicadores tecnicos.

Fase objetivo: 2.

Indicadores v1:
- EMA (rapida/lenta/media).
- RSI.
- MACD.
- ATR.
- Bollinger Bands.
- VWAP.
- Volumen relativo.
- Spread.
- Volatilidad reciente.
- Order book imbalance (feature flag).

Contrato:
- Una implementacion del Protocol ``Indicator`` (``compute(ohlcv,
  params) -> IndicatorOutput``).
- Cache por ``(indicator.name, params_hash, last_candle_ts)`` en
  ``IndicatorCache`` (LRU 256 + ``threading.Lock``).
- Registry frozneable en ``IndicatorRegistry``.
- Property tests con ``hypothesis`` (TSK Fase 5/6).
"""

from __future__ import annotations

# TSK-200.5.1 stub partially delivered in F4.8: explicit public
# re-exports so callers can write ``from trading_bot.indicators import
# IndicatorOutput`` (and the rest) without going through sub-modules.
# The phase order is preserved by the F5 close-out which will audit
# ``__all__`` against the final public surface.
from trading_bot.indicators.cache import (
    IndicatorCache,
    IndicatorCacheStats,
    compute_params_hash,
)
from trading_bot.indicators.ema import EmaIndicator
from trading_bot.indicators.exceptions import (
    IndicatorError,
    InsufficientHistoryError,
    ParamsHashError,
    RegistryFrozenError,
)
from trading_bot.indicators.protocols import Indicator
from trading_bot.indicators.registry import IndicatorRegistry
from trading_bot.indicators.types import (
    IndicatorOutput,
    IndicatorParams,
)

__all__ = [
    "EmaIndicator",
    "Indicator",
    "IndicatorCache",
    "IndicatorCacheStats",
    "IndicatorError",
    "IndicatorOutput",
    "IndicatorParams",
    "IndicatorRegistry",
    "InsufficientHistoryError",
    "ParamsHashError",
    "RegistryFrozenError",
    "compute_params_hash",
]
