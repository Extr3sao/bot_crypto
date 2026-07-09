"""Registry and config resolution for indicators (TSK-200)."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator

from trading_bot.config.settings import Settings

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
from .exceptions import UnknownIndicatorTypeError
from .protocols import Indicator
from .types import ConfiguredIndicator


class IndicatorRegistry:
    """Ordered registry of pluggable indicators, mirroring FilterRegistry."""

    def __init__(self) -> None:
        self._indicators: OrderedDict[str, Indicator] = OrderedDict()
        self._frozen = False

    def register(self, indicator: Indicator) -> None:
        indicator_type = indicator.indicator_type
        if self._frozen:
            raise RuntimeError(
                "IndicatorRegistry esta congelado; construye uno nuevo para mutarlo."
            )
        if indicator_type in self._indicators:
            raise ValueError(f"Indicator type {indicator_type!r} ya registrado.")
        self._indicators[indicator_type] = indicator

    def freeze(self) -> None:
        self._frozen = True

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    def get(self, indicator_type: str) -> Indicator | None:
        return self._indicators.get(indicator_type)

    def all(self) -> list[Indicator]:
        return list(self._indicators.values())

    def types(self) -> list[str]:
        return list(self._indicators.keys())

    def resolve_enabled(self, settings: Settings) -> list[ConfiguredIndicator]:
        configured: list[ConfiguredIndicator] = []
        for name, config in settings.indicators.indicators.items():
            if not config.enabled:
                continue
            if self.get(config.type) is None:
                raise UnknownIndicatorTypeError(
                    f"Indicator type {config.type!r} no registrado para {name!r}."
                )
            configured.append(
                ConfiguredIndicator(
                    name=name,
                    indicator_type=config.type,
                    params=dict(config.params.model_dump()),
                    description=config.description,
                    enabled=config.enabled,
                )
            )
        return configured

    def __contains__(self, indicator_type: object) -> bool:
        return indicator_type in self._indicators

    def __len__(self) -> int:
        return len(self._indicators)

    def __iter__(self) -> Iterator[Indicator]:
        return iter(self._indicators.values())


def build_default_indicator_registry() -> IndicatorRegistry:
    registry = IndicatorRegistry()
    registry.register(EmaIndicator())
    registry.register(RsiIndicator())
    registry.register(MacdIndicator())
    registry.register(AtrIndicator())
    registry.register(BollingerBandsIndicator())
    registry.register(VwapIndicator())
    registry.register(VolumeRelativeIndicator())
    registry.register(SpreadIndicator())
    registry.register(VolatilityIndicator())
    registry.register(MomentumIndicator())
    registry.register(OrderBookImbalanceIndicator())
    registry.freeze()
    return registry


__all__ = ["IndicatorRegistry", "build_default_indicator_registry"]
