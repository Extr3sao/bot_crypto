from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.indicators import IndicatorRegistry, UnknownIndicatorTypeError
from trading_bot.market_data.types import OHLCV


class DummyIndicator:
    def __init__(self, indicator_type: str) -> None:
        self._indicator_type = indicator_type

    @property
    def indicator_type(self) -> str:
        return self._indicator_type

    def compute(self, candles: Sequence[OHLCV], params: dict[str, Any]) -> float:
        del candles, params
        return 1.0


def test_registry_preserves_registration_order() -> None:
    registry = IndicatorRegistry()
    registry.register(DummyIndicator("ema"))
    registry.register(DummyIndicator("rsi"))
    assert registry.types() == ["ema", "rsi"]


def test_registry_rejects_duplicates() -> None:
    registry = IndicatorRegistry()
    registry.register(DummyIndicator("ema"))
    with pytest.raises(ValueError, match="ya registrado"):
        registry.register(DummyIndicator("ema"))


def test_registry_rejects_registration_after_freeze() -> None:
    registry = IndicatorRegistry()
    registry.freeze()
    with pytest.raises(RuntimeError, match="congelado"):
        registry.register(DummyIndicator("ema"))


def test_registry_resolves_enabled_configured_indicators() -> None:
    settings = load_settings()
    registry = IndicatorRegistry()
    for indicator_type in {
        config.type for config in settings.indicators.indicators.values() if config.enabled
    }:
        registry.register(DummyIndicator(indicator_type))

    configured = registry.resolve_enabled(settings)
    assert configured
    assert all(item.enabled for item in configured)
    assert configured[0].name == "ema_fast"


def test_registry_raises_for_unknown_indicator_type() -> None:
    settings = load_settings()
    registry = IndicatorRegistry()
    registry.register(DummyIndicator("ema"))
    with pytest.raises(UnknownIndicatorTypeError, match="no registrado"):
        registry.resolve_enabled(settings)
