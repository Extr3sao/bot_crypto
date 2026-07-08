"""Regression tests for Indicator Protocol contract (fix/tsk-014.1-protocol-attr).

The `Indicator` Protocol historically declared `indicator_type` as `@property`
while every built-in indicator in `trading_bot.indicators.builtin` declares it
as a plain class attribute. Under `@runtime_checkable` that mismatch made
``isinstance(x, Indicator)`` return ``False`` even when ``x`` satisfied every
contract member. The fix relaxes the Protocol to ``indicator_type: str`` so
both styles satisfy the Protocol via structural typing.

These tests lock the contract: they must remain green for any future indicator
added to ``builtin.py``.
"""

from __future__ import annotations

from trading_bot.indicators import (
    AtrIndicator,
    BollingerBandsIndicator,
    EmaIndicator,
    Indicator,
    IndicatorCache,
    IndicatorRegistry,
    MacdIndicator,
    MomentumIndicator,
    OrderBookImbalanceIndicator,
    RsiIndicator,
    SpreadIndicator,
    VolatilityIndicator,
    VolumeRelativeIndicator,
    VwapIndicator,
    build_default_indicator_registry,
)


ALL_INDICATORS = (
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


def test_indicator_protocol_runtime_checkable_for_each_builtin():
    """Every built-in indicator is instanceof-Indicator under @runtime_checkable.

    This is the explicit guard against the historical property/attribute drift.
    """
    for cls in ALL_INDICATORS:
        assert isinstance(cls(), Indicator), (
            f"{cls.__name__} should satisfy Indicator under @runtime_checkable; "
            "if this fails, the Protocol class was likely redeclared with @property."
        )


def test_indicator_type_attribute_on_each_builtin():
    """Each indicator exposes a non-empty ``indicator_type`` string attribute."""
    for cls in ALL_INDICATORS:
        instance = cls()
        assert isinstance(instance.indicator_type, str)
        assert instance.indicator_type, (
            f"{cls.__name__}.indicator_type must be a non-empty string (used in registry keys)"
        )


def test_build_default_indicator_registry_returns_registry():
    """``build_default_indicator_registry()`` returns a registry pre-populated
    with at least every built-in indicator class.

    The registry implements ``__len__`` over its registered indicators (see
    ``src/trading_bot/indicators/registry.py``), so size introspection stays
    on the public surface.
    """
    registry = build_default_indicator_registry()
    assert isinstance(registry, IndicatorRegistry)
    assert len(registry) >= len(ALL_INDICATORS), (
        f"default registry must register at least {len(ALL_INDICATORS)} built-ins; "
        f"got {len(registry)}"
    )


def test_indicator_cache_supports_lookup():
    """``IndicatorCache`` exposes the ``get_or_compute`` API used by the registry."""
    cache = IndicatorCache()
    # Cache API surface used by the registry layer (lock API contract)
    assert hasattr(cache, "get_or_compute")
    assert callable(cache.get_or_compute)
