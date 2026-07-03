"""Indicator catalog configuration. Mirrors config/indicators.yaml."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class IndicatorParams(BaseModel):
    """Each indicator type has its own params (type-specific free-form).

    Specific bounds (period length, etc.) are enforced by the indicator
    implementation that consumes them; at this layer we accept any scalar.
    """

    model_config = ConfigDict(extra="allow")


class IndicatorConfig(BaseModel):
    """Single indicator registration."""

    type: str = Field(..., min_length=1)
    enabled: bool = True
    params: IndicatorParams = Field(default_factory=IndicatorParams)
    description: str | None = None


class IndicatorsGlobal(BaseModel):
    """Global settings for the indicator engine."""

    require_min_candles: int = Field(..., ge=1)
    cache_results: bool = True
    invalidate_on_new_candle: bool = True


class IndicatorsConfig(BaseModel):
    """Root for config/indicators.yaml.

    The YAML structure is::

        indicators:
          <name>: { ... }
          global: { ... }

    The `global` key is renamed via `Field(alias='global')`.
    """

    model_config = ConfigDict(populate_by_name=True)

    indicators: dict[str, IndicatorConfig] = Field(..., min_length=1)
    global_: IndicatorsGlobal = Field(alias="global")
