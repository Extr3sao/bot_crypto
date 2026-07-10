"""Strategy catalog configuration. Mirrors config/strategies.yaml."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StrategyState(StrEnum):
    """Lifecycle states. required_progression enforces order."""

    DISABLED = "disabled"
    RESEARCH = "research"
    PAPER = "paper"
    LIVE_CANDIDATE = "live_candidate"
    LIVE = "live"


class StrategyEntry(BaseModel):
    """Strategy-specific entry conditions.

    The exact key/value set varies per strategy, so we keep entry permissive
    with `extra='allow'` to preserve flexibility for new strategies. Strategy
    code is responsible for interpreting these fields.
    """

    model_config = ConfigDict(extra="allow")


class StrategyFilters(BaseModel):
    """Strategy-specific liquidity and spread filters."""

    min_volume_24h_usdt: int | None = Field(None, ge=1)
    max_spread_bps: int | None = Field(None, ge=0, le=10_000)

    model_config = ConfigDict(extra="allow")


class StrategyExit(BaseModel):
    """ATR-based exit parameters."""

    stop_loss_atr_multiplier: float | None = Field(None, gt=0)
    take_profit_atr_multiplier: float | None = Field(None, gt=0)
    trailing_stop: bool | None = None
    trailing_stop_atr_multiplier: float | None = Field(None, gt=0)


class StrategyConfig(BaseModel):
    """Definition of a single strategy."""

    enabled: bool = False
    state: StrategyState = StrategyState.DISABLED
    description: str = ""
    timeframes: list[str] = Field(..., min_length=1)
    indicators: list[str] = Field(..., min_length=1)
    entry: StrategyEntry = Field(default_factory=lambda: StrategyEntry())
    exit: StrategyExit = Field(default_factory=lambda: StrategyExit())
    filters: StrategyFilters = Field(default_factory=lambda: StrategyFilters())
    notes: str | None = None


class StrategiesGlobal(BaseModel):
    """Global strategy promotion policy."""

    required_progression: list[str] = Field(..., min_length=2)
    require_walk_forward_validation: bool = True
    require_min_trades_for_promotion: int = Field(..., ge=1)


class StrategiesConfig(BaseModel):
    """Root for config/strategies.yaml.

    The YAML structure is::

        strategies:
          <name>: { ... }
          global: { ... }

    The `global` top-level key is renamed via `Field(alias='global')` so the
    domain models don't have to depend on each other.
    """

    model_config = ConfigDict(populate_by_name=True)

    strategies: dict[str, StrategyConfig] = Field(..., min_length=1)
    global_: StrategiesGlobal = Field(alias="global")
