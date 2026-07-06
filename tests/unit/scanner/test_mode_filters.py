
"""Tests for ``build_filter_set_per_mode`` (mode_filters.py)."""

from __future__ import annotations

from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import Settings
from trading_bot.scanner.filters import (
    VALID_MODES,
    AtrFilter,
    SpreadFilter,
    VolumeFilter,
)
from trading_bot.scanner.mode_filters import build_filter_set_per_mode
from trading_bot.scanner.registry import FilterRegistry


def _build_minimal_settings(
    *,
    min_volume_usdt: int = 5_000_000,
    max_spread_bps: int = 30,
    max_atr_percent: float = 8.0,
    min_atr_percent: float = 0.05,
) -> Settings:
    """Settings minimal via model_construct (sin disco, sin validadores cross-field)."""
    from trading_bot.config.exchange import (
        Exchange,
        ExchangeEndpoints,
        ExchangeRetries,
        ExchangeTimeouts,
    )
    from trading_bot.config.indicators import IndicatorsConfig, IndicatorsGlobal
    from trading_bot.config.risk import DefensiveBlocks, Risk
    from trading_bot.config.runtime import (
        FeatureFlags,
        LoggingBlock,
        Metrics,
        Paths,
        Reports,
        Runtime,
        Scheduler,
        SchedulerActiveHours,
        Storage,
    )
    from trading_bot.config.strategies import StrategiesConfig, StrategiesGlobal
    from trading_bot.config.universe import PairSpec, Universe, UniverseFilters

    universe = Universe.model_construct(
        name="t",
        description="t",
        base_currency="USDT",
        enabled=True,
        pairs=[PairSpec.model_construct(symbol="BTC/USDT", enabled=True)],
        timeframes=["5m"],
        filters=UniverseFilters.model_construct(
            min_24h_volume_usdt=min_volume_usdt,
            max_spread_bps=max_spread_bps,
            max_atr_percent=max_atr_percent,
            min_atr_percent=min_atr_percent,
        ),
    )
    exchange = Exchange.model_construct(
        id="binance",
        sandbox=True,
        endpoints=ExchangeEndpoints.model_construct(),
        timeouts=ExchangeTimeouts.model_construct(),
        retries=ExchangeRetries.model_construct(),
    )
    risk = Risk.model_construct(
        max_risk_per_trade_pct=1.0,
        max_daily_loss_pct=3.0,
        max_weekly_loss_pct=7.0,
        max_daily_drawdown_pct=5.0,
        max_total_drawdown_pct=15.0,
        max_open_positions=5,
        max_trades_per_day=100,
        max_consecutive_losses=3,
        consecutive_loss_cooldown_minutes=60,
        max_asset_exposure_pct=20.0,
        max_total_exposure_pct=80.0,
        min_order_notional_usdt=10.0,
        max_order_notional_usdt=1000.0,
        default_stop_loss_pct=0.5,
        default_take_profit_pct=1.0,
        blocks=DefensiveBlocks.model_construct(),
        kill_switch_enabled=True,
        live_trading_enabled=False,
    )
    return Settings.model_construct(
        universe=universe,
        exchange=exchange,
        risk=risk,
        strategies=StrategiesConfig.model_construct(
            strategies={},
            global_=StrategiesGlobal.model_construct(
                required_progression=["research", "paper"],
                require_walk_forward_validation=False,
                require_min_trades_for_promotion=1,
            ),
        ),
        indicators=IndicatorsConfig.model_construct(
            indicators={},
            global_=IndicatorsGlobal.model_construct(
                require_min_candles=1,
                cache_results=False,
                invalidate_on_new_candle=False,
            ),
        ),
        runtime=Runtime.model_construct(
            mode=TradingMode.PAPER,
            live_trading_enabled=False,
            require_manual_confirmation_for_live=True,
            i_understand_the_risks=False,
            scheduler=Scheduler.model_construct(
                timezone="UTC",
                active_hours=SchedulerActiveHours.model_construct(),
            ),
            storage=Storage.model_construct(),
            logging=LoggingBlock.model_construct(),
            reports=Reports.model_construct(),
            metrics=Metrics.model_construct(),
            paths=Paths.model_construct(),
            features=FeatureFlags.model_construct(),
        ),
    )


def test_build_yields_4_frozen_registries() -> None:
    """Cada mode de VALID_MODES tiene un registry, frozen al final."""
    settings = _build_minimal_settings()
    out = build_filter_set_per_mode(settings)
    assert set(out.keys()) == VALID_MODES
    for mode_str, reg in out.items():
        assert isinstance(reg, FilterRegistry)
        assert reg.is_frozen, f"Registry {mode_str!r} no fue freezeado"


def test_build_registers_3_filters_in_order_volume_spread_atr() -> None:
    """Q4 verdict: volume -> spread -> atr (cheap antes de caro)."""
    settings = _build_minimal_settings()
    out = build_filter_set_per_mode(settings)
    for mode_str, reg in out.items():
        names = reg.names()
        assert names == ["volume", "spread", "atr"], (
            f"Mode {mode_str!r} tiene orden {names}; esperaba ['volume','spread','atr']"
        )


def test_build_paper_uses_yaml_bounds_no_live_hardening() -> None:
    """paper/research/backtest: thresholds iguales al YAML (sin endurecer)."""
    settings = _build_minimal_settings(
        min_volume_usdt=7_000_000, max_spread_bps=25, max_atr_percent=7.0
    )
    out = build_filter_set_per_mode(settings)
    for mode_str in ("research", "backtest", "paper"):
        reg = out[mode_str]
        vol = reg.get("volume")
        spread = reg.get("spread")
        atr = reg.get("atr")
        assert isinstance(vol, VolumeFilter)
        assert vol.min_usdt == 7_000_000
        assert vol.live_min_usdt is None  # NO endurece en paper.
        assert vol.mode == mode_str
        assert isinstance(spread, SpreadFilter)
        assert spread.max_bps == 25
        assert isinstance(atr, AtrFilter)
        assert atr.max_pct == 7.0
        assert atr.min_pct == 0.05


def test_build_live_applies_spec_hardening() -> None:
    """live: volume threshold = 10M (LIVE_MIN_VOLUME_USDT), spread <= 20, ATR <= 5."""
    settings = _build_minimal_settings(
        min_volume_usdt=5_000_000, max_spread_bps=30, max_atr_percent=8.0
    )
    out = build_filter_set_per_mode(settings)
    reg = out["live"]
    vol = cast(VolumeFilter, reg.get("volume"))
    spread = cast(SpreadFilter, reg.get("spread"))
    atr = cast(AtrFilter, reg.get("atr"))
    assert isinstance(vol, VolumeFilter)
    assert vol.live_min_usdt == 10_000_000.0  # LIVE_MIN_VOLUME_USDT
    assert vol.mode == "live"
    assert isinstance(spread, SpreadFilter)
    assert spread.max_bps == 20.0  # <= que YAML (30) y que LIVE_MAX_SPREAD_BPS (20).
    assert isinstance(atr, AtrFilter)
    assert atr.max_pct == 5.0  # <= que YAML (8.0) y que LIVE_MAX_ATR_PERCENT (5).


def test_build_live_respects_yaml_when_more_strict_than_spec() -> None:
    """Si el YAML es MAS restrictivo que el spec (e.g. spread=10), gana el YAML."""
    settings = _build_minimal_settings(max_spread_bps=10, max_atr_percent=2.0)
    out = build_filter_set_per_mode(settings)
    reg = out["live"]
    spread = cast(SpreadFilter, reg.get("spread"))
    atr = cast(AtrFilter, reg.get("atr"))
    assert spread.max_bps == 10.0  # YAML es mas estricto.
    assert atr.max_pct == 2.0


def test_build_returns_4_distinct_registry_instances() -> None:
    """Los registries son objetos distintos (freeze() per-instance, no shared)."""
    settings = _build_minimal_settings()
    out = build_filter_set_per_mode(settings)
    instances = list(out.values())
    assert len(set(id(r) for r in instances)) == 4
