"""Pluggable indicator engine primitives (Fase 2)."""

from .builtin import (
    AtrIndicator,
    BollingerBandsIndicator,
    EmaIndicator,
    MacdIndicator,
    MomentumIndicator,
    OrderBookImbalanceIndicator,
    RsiIndicator,
    SpreadIndicator,
    VolatilityIndicator,
    VolumeRelativeIndicator,
    VwapIndicator,
)
from .cache import IndicatorCache
from .exceptions import IndicatorError, UnknownIndicatorTypeError
from .protocols import Indicator
from .registry import IndicatorRegistry, build_default_indicator_registry
from .types import ConfiguredIndicator, IndicatorCacheKey, IndicatorResult

__all__ = [
    "AtrIndicator",
    "BollingerBandsIndicator",
    "ConfiguredIndicator",
    "EmaIndicator",
    "Indicator",
    "IndicatorCache",
    "IndicatorCacheKey",
    "IndicatorError",
    "IndicatorRegistry",
    "IndicatorResult",
    "MacdIndicator",
    "MomentumIndicator",
    "OrderBookImbalanceIndicator",
    "RsiIndicator",
    "SpreadIndicator",
    "UnknownIndicatorTypeError",
    "VolatilityIndicator",
    "VolumeRelativeIndicator",
    "VwapIndicator",
    "build_default_indicator_registry",
]
