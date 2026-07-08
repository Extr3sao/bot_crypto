"""Public types for the indicator engine (TSK-200)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

IndicatorResult = float | list[float] | dict[str, float]


@dataclass(frozen=True, slots=True)
class IndicatorCacheKey:
    indicator_name: str
    last_candle_ts: int | None
    params_fingerprint: str


@dataclass(frozen=True, slots=True)
class ConfiguredIndicator:
    name: str
    indicator_type: str
    params: dict[str, Any]
    description: str | None
    enabled: bool


__all__ = ["ConfiguredIndicator", "IndicatorCacheKey", "IndicatorResult"]
