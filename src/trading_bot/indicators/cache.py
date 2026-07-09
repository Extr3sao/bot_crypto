"""Simple cache for indicator computations (TSK-200)."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from trading_bot.market_data.types import OHLCV

from .types import IndicatorCacheKey, IndicatorResult


class IndicatorCache:
    """Caches indicator outputs by name, params, and latest candle timestamp."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        invalidate_on_new_candle: bool = True,
    ) -> None:
        self._enabled = enabled
        self._invalidate_on_new_candle = invalidate_on_new_candle
        self._store: dict[IndicatorCacheKey, IndicatorResult] = {}

    def make_key(
        self,
        indicator_name: str,
        params: dict[str, Any],
        candles: Sequence[OHLCV],
    ) -> IndicatorCacheKey:
        last_candle_ts = (
            candles[-1].timestamp if candles and self._invalidate_on_new_candle else None
        )
        return IndicatorCacheKey(
            indicator_name=indicator_name,
            last_candle_ts=last_candle_ts,
            params_fingerprint=json.dumps(params, sort_keys=True, separators=(",", ":")),
        )

    def get(self, key: IndicatorCacheKey) -> IndicatorResult | None:
        if not self._enabled:
            return None
        return self._store.get(key)

    def set(self, key: IndicatorCacheKey, result: IndicatorResult) -> None:
        if not self._enabled:
            return
        self._store[key] = result

    def get_or_compute(
        self,
        indicator_name: str,
        params: dict[str, Any],
        candles: Sequence[OHLCV],
        compute_fn: Callable[[], IndicatorResult],
    ) -> IndicatorResult:
        key = self.make_key(indicator_name, params, candles)
        cached = self.get(key)
        if cached is not None:
            return cached
        result = compute_fn()
        self.set(key, result)
        return result

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


__all__ = ["IndicatorCache"]
