"""Protocols for pluggable indicators (TSK-200)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from trading_bot.market_data.types import OHLCV

from .types import IndicatorResult


@runtime_checkable
class Indicator(Protocol):
    """Contract every indicator implementation must satisfy."""

    indicator_type: str

    def compute(
        self,
        candles: Sequence[OHLCV],
        params: dict[str, Any],
    ) -> IndicatorResult: ...


__all__ = ["Indicator"]
