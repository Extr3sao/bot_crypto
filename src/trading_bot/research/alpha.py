"""Alpha Family Protocol and Registry (FASE 3, P5).

Every independent source of alpha must implement AlphaFamily.
The registry manages multiple families and resolves them by name.

Design:
- AlphaFamily is a Protocol (consistent with project conventions).
- Each family is INDEPENDENT — no coupling between families.
- LONG and SHORT are NOT necessarily symmetric per family.
- Features are diagnostic (P7), not rules.
- Structural risk is explicit (P6).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from trading_bot.indicators.types import IndicatorResult
from trading_bot.market_data.types import OHLCV

from .types import AlphaSignal, FeaturesBag


@runtime_checkable
class AlphaFamily(Protocol):
    """Contract every alpha family must satisfy.

    P5 contract:
    - Each family produces AlphaSignals (or empty list).
    - Families are independent — no coupling.
    - LONG and SHORT may be asymmetric.
    - Features are diagnostic, not operational rules.
    """

    @property
    def family_name(self) -> str:
        """Unique name for this alpha family."""
        ...

    def generate(
        self,
        candles: Sequence[OHLCV],
        indicators: dict[str, IndicatorResult],
        features: FeaturesBag | None = None,
        **kwargs: Any,
    ) -> list[AlphaSignal]:
        """Generate alpha signals from candles + indicators.

        Returns empty list if no signal. Never returns None.
        The family decides its own thresholds — not configurable externally.
        """
        ...


class AlphaRegistry:
    """Registry of alpha families.

    Manages multiple independent alpha sources.
    Resolves by family_name, iterates all for portfolio construction.
    """

    def __init__(self) -> None:
        self._families: dict[str, AlphaFamily] = {}

    def register(self, family: AlphaFamily) -> None:
        """Register an alpha family. Raises if name already registered."""
        name = family.family_name
        if name in self._families:
            raise ValueError(f"Alpha family '{name}' already registered")
        self._families[name] = family

    def get(self, name: str) -> AlphaFamily | None:
        """Get a family by name."""
        return self._families.get(name)

    def all_families(self) -> list[AlphaFamily]:
        """Return all registered families."""
        return list(self._families.values())

    def family_names(self) -> list[str]:
        """Return all registered family names."""
        return list(self._families.keys())

    def generate_all(
        self,
        candles: Sequence[OHLCV],
        indicators: dict[str, IndicatorResult],
        features: FeaturesBag | None = None,
        **kwargs: Any,
    ) -> list[AlphaSignal]:
        """Generate signals from ALL registered families.

        Returns flat list of all signals from all families.
        """
        signals: list[AlphaSignal] = []
        for family in self._families.values():
            family_signals = family.generate(candles, indicators, features, **kwargs)
            signals.extend(family_signals)
        return signals

    def __len__(self) -> int:
        return len(self._families)

    def __contains__(self, name: str) -> bool:
        return name in self._families


__all__ = ["AlphaFamily", "AlphaRegistry"]
