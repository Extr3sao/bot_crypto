"""Asset universe configuration. Mirrors config/assets.yaml."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PairSpec(BaseModel):
    """Single trading pair definition in the universe whitelist."""

    symbol: str = Field(
        ...,
        min_length=3,
        max_length=20,
        description="CCXT-style symbol, e.g. 'BTC/USDT'.",
    )
    enabled: bool = True
    notes: str | None = None


class UniverseFilters(BaseModel):
    """Global filters applied to every pair in the universe."""

    min_24h_volume_usdt: int = Field(..., ge=1)
    max_spread_bps: int = Field(..., ge=0, le=10_000)
    max_atr_percent: float = Field(..., gt=0, le=100)
    min_atr_percent: float = Field(..., gt=0, le=100)


class Universe(BaseModel):
    """Whitelist of tradable assets. Mirrors the top-level key in assets.yaml."""

    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    base_currency: str = Field(..., min_length=2, max_length=10)
    enabled: bool = True
    pairs: list[PairSpec] = Field(..., min_length=1)
    timeframes: list[str] = Field(..., min_length=1)
    filters: UniverseFilters
