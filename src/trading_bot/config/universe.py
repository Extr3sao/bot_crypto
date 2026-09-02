"""Asset universe configuration. Mirrors config/assets.yaml."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from trading_bot.market_data.types import ExchangeMarketType


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


class ExchangeTarget(BaseModel):
    """Un exchange objetivo del hub multi-exchange (TSK-022).

    Identidad: ``(id, type)``. Un mismo ``id`` puede declarar ``spot`` y
    ``futures``, pero solo UNO puede estar habilitado a la vez; la ambigüedad
    se rechaza en ``Universe``. No contiene credenciales: los secretos siguen
    viviendo en ``Exchange``/env existentes.
    """

    id: str = Field(..., min_length=2, max_length=20)
    enabled: bool = True
    sandbox: bool = True
    type: ExchangeMarketType = "spot"


class Universe(BaseModel):
    """Whitelist of tradable assets. Mirrors the top-level key in assets.yaml."""

    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    base_currency: str = Field(..., min_length=2, max_length=10)
    enabled: bool = True
    pairs: list[PairSpec] = Field(..., min_length=1)
    timeframes: list[str] = Field(..., min_length=1)
    filters: UniverseFilters
    exchanges: list[ExchangeTarget] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_exchange_targets(self) -> Universe:
        """Rechaza targets duplicados y tipos habilitados ambiguos por id."""
        seen: set[tuple[str, ExchangeMarketType]] = set()
        for target in self.exchanges:
            key = (target.id, target.type)
            if key in seen:
                raise ValueError(
                    f"target de exchange duplicado: id={target.id!r} type={target.type!r}"
                )
            seen.add(key)

        enabled_types_by_id: dict[str, list[str]] = {}
        for target in self.exchanges:
            if target.enabled:
                enabled_types_by_id.setdefault(target.id, []).append(target.type)
        for exchange_id, types in enabled_types_by_id.items():
            if len(types) > 1:
                raise ValueError(
                    f"ambigüedad de exchange: id={exchange_id!r} tiene múltiples "
                    f"tipos habilitados {sorted(types)}; solo un tipo puede estar "
                    "habilitado por id (TSK-022 no elige spot/futures)."
                )
        return self
