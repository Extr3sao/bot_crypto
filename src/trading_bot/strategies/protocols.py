"""Strategy protocol — the contract every strategy must satisfy.

Fase 4: pluggable strategy interface. Strategies receive OHLCV candles
+ indicator values and emit Signal or None. No I/O, no execution.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from trading_bot.indicators.types import IndicatorResult
from trading_bot.market_data.types import OHLCV

from .types import Signal, StrategyConfig


@runtime_checkable
class Strategy(Protocol):
    """Contract every strategy implementation must satisfy.

    A strategy is a pure function: candles + config -> Signal | None.
    It does NOT access exchange, does NOT place orders, does NOT
    manage risk. Those are upstream/downstream responsibilities.
    """

    strategy_name: str

    def evaluate(
        self,
        candles: Sequence[OHLCV],
        indicators: dict[str, IndicatorResult],
        config: StrategyConfig,
    ) -> Signal | None:
        """Evaluate candles + indicators and return a Signal or None.

        Args:
            candles: Recent OHLCV candles (most recent last).
            indicators: Pre-computed indicator values keyed by name.
            config: Runtime strategy configuration.

        Returns:
            Signal if the strategy triggers, None otherwise.
        """
        ...


__all__ = ["Strategy"]
