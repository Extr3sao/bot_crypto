"""DoD fail-fast scenarios for trading_bot.config.

Cubre los tres casos exigidos por tasks/sprint-001.md (TSK-099 DoD):
1. YAML malformado.
2. Live=true sin I_UNDERSTAND_THE_RISKS=true.
3. Risk inconsistente.

Y dos casos adicionales cercanos (mode=live sin flag, shadow-live + flag).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from pydantic_settings import BaseSettings

from trading_bot.config import load_settings
from trading_bot.config.risk import Risk
from trading_bot.config.runtime import Runtime
from trading_bot.config.settings import FLAT_ENV_ALIASES, YamlDirectorySource

# ---------------------------------------------------------------------------
# 1. YAML malformado
# ---------------------------------------------------------------------------


def test_load_settings_rejects_malformed_yaml(tmp_path: Path) -> None:
    """YAML con syntax error (indentacion rota) => ValidationError."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    # assets.yaml con indent corruption.
    (config_dir / "assets.yaml").write_text(
        "universe:\n"
        "  name: t\n"
        "   description: BAD INDENT\n"  # indent invalido rompe la lectura YAML
        "  base_currency: USDT\n",
        encoding="utf-8",
    )
    with pytest.raises(yaml.YAMLError):
        load_settings(config_dir=config_dir, env_file=None)


def test_yaml_directory_source_rejects_non_mapping_root(tmp_path: Path) -> None:
    """YAML cuya raiz no es un dict => ValueError explicito."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "assets.yaml").write_text("- item1\n- item2\n", encoding="utf-8")

    class _Stub(BaseSettings):
        pass

    src = YamlDirectorySource(_Stub, config_dir)
    with pytest.raises(ValueError, match="debe tener un mapping raiz"):
        src()


# ---------------------------------------------------------------------------
# 2. live=true sin I_UNDERSTAND_THE_RISKS (DoD fail-fast)
# ---------------------------------------------------------------------------


def test_runtime_live_enabled_without_agreement_fails() -> None:
    with pytest.raises(ValidationError) as exc:
        Runtime.model_validate(
            {
                "mode": "paper",
                "live_trading_enabled": True,
                # i_understand_the_risks stays False (default).
            }
        )
    msg = str(exc.value)
    assert "I_UNDERSTAND_THE_RISKS" in msg
    # Mensaje humano legible (no solo traceback).
    assert "no arranca en modo live" in msg


# ---------------------------------------------------------------------------
# 3. Risk inconsistente
# ---------------------------------------------------------------------------


def _good_risk() -> dict[str, float | int]:
    return {
        "max_risk_per_trade_pct": 0.25,
        "max_daily_loss_pct": 1.0,
        "max_weekly_loss_pct": 3.0,
        "max_daily_drawdown_pct": 2.0,
        "max_total_drawdown_pct": 5.0,
        "max_open_positions": 3,
        "max_trades_per_day": 20,
        "max_consecutive_losses": 3,
        "consecutive_loss_cooldown_minutes": 60,
        "max_asset_exposure_pct": 10,
        "max_total_exposure_pct": 25,
        "min_order_notional_usdt": 20,
        "max_order_notional_usdt": 500,
        "default_stop_loss_pct": 0.5,
        "default_take_profit_pct": 0.75,
    }


def test_risk_total_exposure_below_per_trade_fails() -> None:
    bad = _good_risk()
    bad["max_total_exposure_pct"] = 0.1  # < max_risk_per_trade_pct (0.25)
    with pytest.raises(ValidationError) as exc:
        Risk.model_validate(bad)
    assert "max_total_exposure_pct" in str(exc.value)


def test_risk_take_profit_below_stop_loss_fails() -> None:
    bad = _good_risk()
    bad["default_take_profit_pct"] = 0.3  # < default_stop_loss_pct (0.5)
    with pytest.raises(ValidationError) as exc:
        Risk.model_validate(bad)
    assert "default_take_profit_pct" in str(exc.value)


def test_risk_min_above_max_order_notional_fails() -> None:
    bad = _good_risk()
    bad["min_order_notional_usdt"] = 600
    bad["max_order_notional_usdt"] = 500
    with pytest.raises(ValidationError):
        Risk.model_validate(bad)


# ---------------------------------------------------------------------------
# Cross-domain: live+risk kill_switch off must fail at Settings level.
# ---------------------------------------------------------------------------


def test_settings_rejects_live_with_kill_switch_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mode='live' requiere risk.kill_switch_enabled=True (cross-domain gate)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    # Solo necesitamos el subset minimo para que Settings valide.
    (config_dir / "assets.yaml").write_text(
        "universe:\n"
        "  name: t\n  description: t\n  base_currency: USDT\n"
        "  pairs: [{symbol: BTC/USDT}]\n  timeframes: ['1m']\n"
        "  filters:\n    min_24h_volume_usdt: 1000\n"
        "    max_spread_bps: 30\n    max_atr_percent: 8.0\n"
        "    min_atr_percent: 0.05\n",
        encoding="utf-8",
    )
    (config_dir / "exchange.yaml").write_text(
        "exchange:\n  id: binance\n  account_type: spot\n  default_type: spot\n  sandbox: true\n",
        encoding="utf-8",
    )
    risk_yaml = (
        "risk:\n"
        + "\n".join(f"  {k}: {v}" for k, v in _good_risk().items())
        + "\n  kill_switch_enabled: false\n"
    )
    (config_dir / "risk.yaml").write_text(risk_yaml, encoding="utf-8")
    (config_dir / "strategies.yaml").write_text(
        "strategies:\n  strategies:\n    s1:\n      enabled: false\n      state: research\n"
        "      timeframes: ['1m']\n      indicators: ['ema_fast']\n  global:\n"
        "    required_progression: ['research', 'paper', 'live']\n"
        "    require_walk_forward_validation: true\n"
        "    require_min_trades_for_promotion: 100\n",
        encoding="utf-8",
    )
    (config_dir / "indicators.yaml").write_text(
        "indicators:\n  indicators:\n    ema_fast:\n      type: ema\n      enabled: true\n"
        "      params: {period: 9}\n  global:\n"
        "    require_min_candles: 100\n    cache_results: true\n"
        "    invalidate_on_new_candle: true\n",
        encoding="utf-8",
    )
    (config_dir / "runtime.yaml").write_text(
        "runtime:\n  mode: live\n  live_trading_enabled: true\n"
        "  i_understand_the_risks: true\n  require_manual_confirmation_for_live: true\n",
        encoding="utf-8",
    )
    # Clear all env vars that FlatEnvAliasSource reads so the YAML's values
    # are authoritative. The host shell may set TRADING_MODE, EXCHANGE_ID,
    # LOG_LEVEL, etc.; without this, those env vars silently override the
    # YAML's runtime.mode='live' and the cross-domain gate does not fire.
    for env_var in FLAT_ENV_ALIASES:
        monkeypatch.delenv(env_var, raising=False)
    # Set agreement env var so Settings picks it up if YAML miss.
    monkeypatch.setenv("I_UNDERSTAND_THE_RISKS", "true")
    with pytest.raises(ValidationError) as exc:
        load_settings(config_dir=config_dir, env_file=None)
    assert "kill_switch_enabled" in str(exc.value)
