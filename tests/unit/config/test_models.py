"""Smoke tests for each Pydantic model in trading_bot.config."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from trading_bot.config.exchange import Exchange
from trading_bot.config.indicators import IndicatorsConfig
from trading_bot.config.risk import Risk
from trading_bot.config.runtime import Runtime, TradingMode
from trading_bot.config.strategies import StrategiesConfig
from trading_bot.config.universe import Universe

# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------


def test_universe_minimal_loads() -> None:
    u = Universe.model_validate(
        {
            "name": "test_universe",
            "description": "Smoke test universe",
            "base_currency": "USDT",
            "pairs": [{"symbol": "BTC/USDT"}, {"symbol": "ETH/USDT", "enabled": False}],
            "timeframes": ["1m", "5m"],
            "filters": {
                "min_24h_volume_usdt": 1_000_000,
                "max_spread_bps": 30,
                "max_atr_percent": 8.0,
                "min_atr_percent": 0.05,
            },
        }
    )
    assert u.base_currency == "USDT"
    assert len(u.pairs) == 2
    assert u.pairs[0].enabled is True
    assert u.pairs[1].enabled is False


def test_universe_rejects_empty_pairs() -> None:
    with pytest.raises(ValidationError):
        Universe.model_validate(_valid_universe_dict(pairs=[]))


def test_universe_min_volume_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Universe.model_validate(
            _valid_universe_dict(
                filters={
                    "min_24h_volume_usdt": 0,
                    "max_spread_bps": 30,
                    "max_atr_percent": 8.0,
                    "min_atr_percent": 0.05,
                }
            )
        )


# ---------------------------------------------------------------------------
# Exchange
# ---------------------------------------------------------------------------


def test_exchange_minimal_loads() -> None:
    e = Exchange.model_validate({"id": "binance"})
    assert e.id == "binance"
    assert e.api_key == ""
    assert e.api_secret == ""
    assert e.password == ""
    assert e.sandbox is True  # safe default
    assert e.time_in_force_default == "GTC"
    assert e.post_only_default is True


def test_exchange_rejects_unknown_account_type() -> None:
    with pytest.raises(ValidationError):
        Exchange.model_validate({"id": "binance", "account_type": "weenie"})


def test_exchange_retries_bounded() -> None:
    with pytest.raises(ValidationError):
        Exchange.model_validate({"id": "binance", "retries": {"max_attempts": 0}})


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------


def _valid_risk_dict() -> dict[str, float | int]:
    return {
        "max_risk_per_trade_pct": 0.25,
        "max_daily_loss_pct": 1.0,
        "max_weekly_loss_pct": 3.0,
        "max_daily_drawdown_pct": 2.0,
        "max_total_drawdown_pct": 5.0,
        "max_open_positions": 3,
        "max_trades_per_day": 20,
        "max_consecutive_losses": 3,
        "max_asset_exposure_pct": 10,
        "max_total_exposure_pct": 25,
        "min_order_notional_usdt": 20,
        "max_order_notional_usdt": 500,
        "default_stop_loss_pct": 0.5,
        "default_take_profit_pct": 0.75,
    }


def test_risk_minimal_loads() -> None:
    r = Risk.model_validate(_valid_risk_dict())
    assert r.kill_switch_enabled is True
    assert r.live_trading_enabled is False


def test_risk_rejects_live_trading_enabled_flag() -> None:
    """Risk.yaml is a defensive double of runtime.live_trading_enabled."""
    with pytest.raises(ValidationError) as exc:
        Risk.model_validate({**_valid_risk_dict(), "live_trading_enabled": True})
    assert "live_trading_enabled" in str(exc.value)


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


def _valid_runtime_dict() -> dict[str, str | bool]:
    return {
        "mode": "paper",
        "live_trading_enabled": False,
        "require_manual_confirmation_for_live": True,
        "i_understand_the_risks": False,
    }


def test_runtime_default_mode_is_paper() -> None:
    r = Runtime.model_validate({})
    assert r.mode == TradingMode.PAPER
    assert r.live_trading_enabled is False


def test_runtime_rejects_live_without_acknowledgement() -> None:
    """DoD fail-fast: live=true with i_understand_the_risks=False raises."""
    payload = _valid_runtime_dict()
    payload["live_trading_enabled"] = True
    # NOTE: i_understand_the_risks stays False (omitted).
    with pytest.raises(ValidationError) as exc:
        Runtime.model_validate(payload)
    assert "I_UNDERSTAND_THE_RISKS" in str(exc.value)


def test_runtime_live_with_acknowledgement_ok() -> None:
    payload = _valid_runtime_dict()
    payload["live_trading_enabled"] = True
    payload["i_understand_the_risks"] = True
    r = Runtime.model_validate(payload)
    assert r.live_trading_enabled is True
    assert r.i_understand_the_risks is True


def test_runtime_rejects_mode_live_without_flag() -> None:
    payload = _valid_runtime_dict()
    payload["mode"] = "live"  # but live_trading_enabled stays False
    with pytest.raises(ValidationError) as exc:
        Runtime.model_validate(payload)
    assert "mode='live'" in str(exc.value)


def test_runtime_rejects_shadow_live_combined_with_flag() -> None:
    payload = _valid_runtime_dict()
    payload["mode"] = "shadow_live"
    payload["live_trading_enabled"] = True
    with pytest.raises(ValidationError):
        Runtime.model_validate(payload)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _valid_strategies_dict() -> dict[str, object]:
    return {
        "strategies": {
            "trend_pullback_scalping": {
                "enabled": False,
                "state": "research",
                "timeframes": ["5m", "15m"],
                "indicators": ["ema_fast", "ema_slow", "vwap"],
            }
        },
        "global": {
            "required_progression": ["research", "paper", "live_candidate", "live"],
            "require_walk_forward_validation": True,
            "require_min_trades_for_promotion": 200,
        },
    }


def test_strategies_minimal_loads_with_global_alias() -> None:
    s = StrategiesConfig.model_validate(_valid_strategies_dict())
    assert "trend_pullback_scalping" in s.strategies
    assert s.global_.require_min_trades_for_promotion == 200


def test_strategies_rejects_min_trades_zero() -> None:
    bad = {
        "strategies": {
            "trend_pullback_scalping": {
                "enabled": False,
                "state": "research",
                "timeframes": ["5m"],
                "indicators": ["ema_fast"],
            }
        },
        "global": {
            "required_progression": ["research", "paper", "live"],
            "require_walk_forward_validation": True,
            "require_min_trades_for_promotion": 0,
        },
    }
    with pytest.raises(ValidationError):
        StrategiesConfig.model_validate(bad)


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------


def _valid_indicators_dict() -> dict[str, object]:
    return {
        "indicators": {
            "ema_fast": {"type": "ema", "enabled": True, "params": {"period": 9}},
            "rsi": {"type": "rsi", "enabled": True, "params": {"period": 14}},
        },
        "global": {
            "require_min_candles": 100,
            "cache_results": True,
            "invalidate_on_new_candle": True,
        },
    }


def test_indicators_minimal_loads_with_global_alias() -> None:
    i = IndicatorsConfig.model_validate(_valid_indicators_dict())
    assert "ema_fast" in i.indicators
    assert i.global_.require_min_candles == 100


def test_indicators_params_accept_extra_keys() -> None:
    i = IndicatorsConfig.model_validate(_valid_indicators_dict())
    # Strategy-specific params must be tolerated.
    assert i.indicators["ema_fast"].params.model_extra == {"period": 9}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_universe_dict(
    *,
    pairs: list[dict[str, object]] | None = None,
    filters: dict[str, float | int] | None = None,
) -> dict[str, object]:
    if pairs is None:
        pairs = [{"symbol": "BTC/USDT"}]
    if filters is None:
        filters = {
            "min_24h_volume_usdt": 1_000_000,
            "max_spread_bps": 30,
            "max_atr_percent": 8.0,
            "min_atr_percent": 0.05,
        }
    return {
        "name": "test",
        "description": "test",
        "base_currency": "USDT",
        "pairs": pairs,
        "timeframes": ["1m"],
        "filters": filters,
    }
