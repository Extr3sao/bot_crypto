"""Risk policy configuration. Mirrors config/risk.yaml.

Constantes de política. Cambiar este YAML requiere un ADR en tasks/decisions.md.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class DefensiveBlocks(BaseModel):
    """Hard blocks against hostile market conditions."""

    excessive_spread_bps: int = Field(50, ge=0)
    extreme_atr_pct: float = Field(8.0, gt=0, le=100)
    high_latency_ms: int = Field(2_000, ge=50)
    weekend_trading: bool = False


class Risk(BaseModel):
    """Risk policy. Cross-field invariants enforced by the validator."""

    max_risk_per_trade_pct: float = Field(..., gt=0, le=5)
    max_daily_loss_pct: float = Field(..., gt=0, le=10)
    max_weekly_loss_pct: float = Field(..., gt=0, le=20)
    max_daily_drawdown_pct: float = Field(..., gt=0, le=20)
    max_total_drawdown_pct: float = Field(..., gt=0, le=50)
    max_open_positions: int = Field(..., ge=1, le=20)
    max_trades_per_day: int = Field(..., ge=1, le=1000)
    max_consecutive_losses: int = Field(..., ge=1, le=20)
    consecutive_loss_cooldown_minutes: int = Field(60, ge=0)
    max_asset_exposure_pct: float = Field(..., gt=0, le=100)
    max_total_exposure_pct: float = Field(..., gt=0, le=100)
    min_order_notional_usdt: float = Field(..., gt=0)
    max_order_notional_usdt: float = Field(..., gt=0)
    default_stop_loss_pct: float = Field(..., gt=0, le=20)
    default_take_profit_pct: float = Field(..., gt=0, le=20)
    blocks: DefensiveBlocks = Field(default_factory=DefensiveBlocks)
    kill_switch_enabled: bool = True
    # Defensive double of runtime.live_trading_enabled. The single source of
    # truth is runtime.yaml; setting this to True triggers a fail-fast error
    # and forces the operator to follow the proper release-gate flow.
    live_trading_enabled: bool = False

    @model_validator(mode="after")
    def _check_invariants(self) -> Risk:
        if self.max_total_exposure_pct < self.max_risk_per_trade_pct:
            raise ValueError(
                "max_total_exposure_pct debe ser >= max_risk_per_trade_pct "
                f"({self.max_total_exposure_pct} < {self.max_risk_per_trade_pct})."
            )
        if self.max_asset_exposure_pct > self.max_total_exposure_pct:
            raise ValueError(
                "max_asset_exposure_pct debe ser <= max_total_exposure_pct "
                f"({self.max_asset_exposure_pct} > {self.max_total_exposure_pct})."
            )
        if self.max_order_notional_usdt < self.min_order_notional_usdt:
            raise ValueError(
                "max_order_notional_usdt debe ser >= min_order_notional_usdt "
                f"({self.max_order_notional_usdt} < {self.min_order_notional_usdt})."
            )
        if self.default_take_profit_pct <= self.default_stop_loss_pct:
            raise ValueError(
                "default_take_profit_pct debe ser > default_stop_loss_pct "
                f"({self.default_take_profit_pct} <= {self.default_stop_loss_pct}) "
                "para una expectativa de payoff positivo."
            )
        if self.live_trading_enabled:
            raise ValueError(
                "risk.live_trading_enabled=True detectado. La fuente unica sobre "
                "live trading es runtime.yaml; editar este campo rompe el control "
                "de release gates. Cambia runtime.live_trading_enabled solo tras "
                "abrir un ADR y superar las gates manuales."
            )
        return self
