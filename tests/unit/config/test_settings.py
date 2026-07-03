"""Tests for the Settings aggregate loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from trading_bot.config import load_settings
from trading_bot.config.runtime import TradingMode


def _write_minimal_config(config_dir: Path) -> None:
    """Write the 6 minimal YAMLs into config_dir so Settings can load."""
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "assets.yaml").write_text(
        "universe:\n"
        "  name: t\n"
        "  description: t\n"
        "  base_currency: USDT\n"
        "  pairs:\n    - {symbol: BTC/USDT}\n"
        "    - {symbol: ETH/USDT}\n"
        "  timeframes: ['1m', '5m']\n"
        "  filters:\n"
        "    min_24h_volume_usdt: 1000000\n"
        "    max_spread_bps: 30\n"
        "    max_atr_percent: 8.0\n"
        "    min_atr_percent: 0.05\n",
        encoding="utf-8",
    )
    (config_dir / "exchange.yaml").write_text(
        "exchange:\n"
        "  id: binance\n"
        "  account_type: spot\n"
        "  default_type: spot\n"
        "  sandbox: true\n"
        "  rate_limit_ms: 250\n"
        "  timeouts: {request_ms: 15000, recv_window_ms: 5000}\n"
        "  retries: {max_attempts: 5, initial_backoff_ms: 500, max_backoff_ms: 8000}\n"
        "  time_in_force_default: GTC\n"
        "  post_only_default: true\n"
        "  endpoints: {api_base: '', ws_base: ''}\n"
        "  options: {defaultType: spot, adjustForTimeDifference: true}\n"
        "symbol_mapping:\n  BTCUSDT: BTC/USDT\n"
        "  ETHUSDT: ETH/USDT\n"
        "excluded_markets:\n"
        "  - Leveraged Tokens\n  - Derivatives\n  - Options\n",
        encoding="utf-8",
    )
    risk_lines = [
        "risk:",
        "  max_risk_per_trade_pct: 0.25",
        "  max_daily_loss_pct: 1.0",
        "  max_weekly_loss_pct: 3.0",
        "  max_daily_drawdown_pct: 2.0",
        "  max_total_drawdown_pct: 5.0",
        "  max_open_positions: 3",
        "  max_trades_per_day: 20",
        "  max_consecutive_losses: 3",
        "  max_asset_exposure_pct: 10",
        "  max_total_exposure_pct: 25",
        "  min_order_notional_usdt: 20",
        "  max_order_notional_usdt: 500",
        "  default_stop_loss_pct: 0.5",
        "  default_take_profit_pct: 0.75",
        "  kill_switch_enabled: true",
    ]
    (config_dir / "risk.yaml").write_text("\n".join(risk_lines) + "\n", encoding="utf-8")
    (config_dir / "strategies.yaml").write_text(
        "strategies:\n"
        "  strategies:\n"
        "    trend_pullback_scalping:\n"
        "      enabled: false\n"
        "      state: research\n"
        "      timeframes: ['5m', '15m']\n"
        "      indicators: ['ema_fast', 'ema_slow', 'vwap']\n"
        "  global:\n"
        "    required_progression:\n"
        "      - research\n"
        "      - paper\n"
        "      - live_candidate\n"
        "      - live\n"
        "    require_walk_forward_validation: true\n"
        "    require_min_trades_for_promotion: 200\n",
        encoding="utf-8",
    )
    (config_dir / "indicators.yaml").write_text(
        "indicators:\n"
        "  indicators:\n"
        "    ema_fast:\n      type: ema\n      enabled: true\n"
        "      params: {period: 9}\n"
        "    rsi:\n      type: rsi\n      enabled: true\n"
        "      params: {period: 14}\n"
        "  global:\n"
        "    require_min_candles: 100\n"
        "    cache_results: true\n"
        "    invalidate_on_new_candle: true\n",
        encoding="utf-8",
    )
    (config_dir / "runtime.yaml").write_text(
        "runtime:\n"
        "  mode: paper\n"
        "  live_trading_enabled: false\n"
        "  require_manual_confirmation_for_live: true\n"
        "  i_understand_the_risks: false\n"
        "  scheduler:\n"
        "    timezone: UTC\n"
        "    active_hours: {start: '00:00', end: '23:59'}\n"
        "    scanner_interval_seconds: 30\n",
        encoding="utf-8",
    )


def test_load_settings_happy_path(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    _write_minimal_config(config_dir)
    settings = load_settings(config_dir=config_dir, env_file=None)
    assert settings.universe.base_currency == "USDT"
    assert settings.exchange.id == "binance"
    assert settings.risk.max_risk_per_trade_pct == 0.25
    assert settings.runtime.mode == TradingMode.PAPER
    assert "trend_pullback_scalping" in settings.strategies.strategies


def test_env_var_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Env var I_UNDERSTAND_THE_RISKS=true wins over YAML false."""
    config_dir = tmp_path / "config"
    _write_minimal_config(config_dir)
    # YAML dice i_understand=false; aqui forzamos el flip.
    monkeypatch.setenv("RUNTIME__I_UNDERSTAND_THE_RISKS", "true")
    settings = load_settings(config_dir=config_dir, env_file=None)
    assert settings.runtime.i_understand_the_risks is True


def test_yaml_mode_overridden_by_env_trading_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Env var TRADING_MODE sobreescribe runtime.mode del YAML."""
    config_dir = tmp_path / "config"
    _write_minimal_config(config_dir)
    monkeypatch.setenv("RUNTIME__MODE", "backtest")
    settings = load_settings(config_dir=config_dir, env_file=None)
    assert settings.runtime.mode == TradingMode.BACKTEST


def test_settings_risk_invariants_applied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Los validadores de risk se disparan al cargar Settings."""
    config_dir = tmp_path / "config"
    _write_minimal_config(config_dir)
    # Romper la consistencia a traves de env var sobre risk.live_trading_enabled.
    monkeypatch.setenv("RISK__LIVE_TRADING_ENABLED", "true")
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        load_settings(config_dir=config_dir, env_file=None)


# ---------------------------------------------------------------------------
# Flat-env aliases (TRADING_MODE, EXCHANGE_ID, ...).
#
# The docs that operators follow (.env.example, docker-compose.yml,
# docs/live-trading-checklist.md, bdd/features/*.feature) use FLAT env
# names, while the Settings model_config uses env_nested_delimiter="__".
# FlatEnvAliasSource bridges the gap; these tests pin the contract.
# ---------------------------------------------------------------------------

_FLAT_ALIAS_ENV_VARS: tuple[str, ...] = (
    "TRADING_MODE",
    "LIVE_TRADING_ENABLED",
    "I_UNDERSTAND_THE_RISKS",
    "EXCHANGE_ID",
    "EXCHANGE_SANDBOX",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "LOG_TO_FILE",
    "LOG_FILE_PATH",
    "DATABASE_URL",
    "SCHEDULER_TIMEZONE",
    "ACTIVE_HOURS_START",
    "ACTIVE_HOURS_END",
    # Nested-form variants (legacy + existing tests).
    "RUNTIME__MODE",
    "RUNTIME__I_UNDERSTAND_THE_RISKS",
    "RUNTIME__LIVE_TRADING_ENABLED",
    "EXCHANGE__ID",
    "RUNTIME__SCHEDULER__ACTIVE_HOURS__START",
)


def test_flat_env_alias_from_process_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Flat doc-names load from process env and override YAML defaults."""
    config_dir = tmp_path / "config"
    _write_minimal_config(config_dir)

    # Hermeticidad: limpiamos cualquier bleed-over de CI o tests anteriores.
    for k in _FLAT_ALIAS_ENV_VARS:
        monkeypatch.delenv(k, raising=False)

    monkeypatch.setenv("TRADING_MODE", "backtest")
    monkeypatch.setenv("EXCHANGE_ID", "kraken")
    monkeypatch.setenv("ACTIVE_HOURS_START", "08:00")
    monkeypatch.setenv("ACTIVE_HOURS_END", "16:00")

    settings = load_settings(config_dir=config_dir, env_file=None)

    assert settings.runtime.mode == TradingMode.BACKTEST
    assert settings.exchange.id == "kraken"
    assert settings.runtime.scheduler.active_hours.start == "08:00"
    assert settings.runtime.scheduler.active_hours.end == "16:00"


def test_flat_env_alias_from_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Flat doc-names loaded from the .env file when no process env override."""
    config_dir = tmp_path / "config"
    _write_minimal_config(config_dir)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "TRADING_MODE=paper\n"
        "EXCHANGE_ID=coinbase\n"
        "ACTIVE_HOURS_START=09:00\n"
        "ACTIVE_HOURS_END=17:30\n",
        encoding="utf-8",
    )

    # Asegurar process-env neutro: solo el archivo .env aporta overrides.
    for k in _FLAT_ALIAS_ENV_VARS:
        monkeypatch.delenv(k, raising=False)

    settings = load_settings(config_dir=config_dir, env_file=env_file)

    assert settings.runtime.mode == TradingMode.PAPER
    assert settings.exchange.id == "coinbase"
    assert settings.runtime.scheduler.active_hours.start == "09:00"
    assert settings.runtime.scheduler.active_hours.end == "17:30"


def test_nested_env_form_beats_flat_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Forma anidada (RUNTIME__MODE) gana sobre TRADING_MODE cuando ambas estan."""
    config_dir = tmp_path / "config"
    _write_minimal_config(config_dir)

    for k in _FLAT_ALIAS_ENV_VARS:
        monkeypatch.delenv(k, raising=False)

    monkeypatch.setenv("RUNTIME__MODE", "backtest")
    monkeypatch.setenv("TRADING_MODE", "paper")

    settings = load_settings(config_dir=config_dir, env_file=None)
    assert settings.runtime.mode == TradingMode.BACKTEST


def test_flat_alias_is_case_insensitive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Una env var en minusculas ('trading_mode') debe mapear igual que 'TRADING_MODE'."""
    config_dir = tmp_path / "config"
    _write_minimal_config(config_dir)

    for k in _FLAT_ALIAS_ENV_VARS:
        monkeypatch.delenv(k, raising=False)

    monkeypatch.setenv("trading_mode", "backtest")

    settings = load_settings(config_dir=config_dir, env_file=None)
    assert settings.runtime.mode == TradingMode.BACKTEST


def test_flat_alias_skips_empty_env_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Una env var vacia no debe pisar el default del YAML; se considera unset."""
    config_dir = tmp_path / "config"
    _write_minimal_config(config_dir)

    for k in _FLAT_ALIAS_ENV_VARS:
        monkeypatch.delenv(k, raising=False)

    monkeypatch.setenv("TRADING_MODE", "")

    settings = load_settings(config_dir=config_dir, env_file=None)
    # YAML default gana porque empty string fue omitido por FlatEnvAliasSource.
    assert settings.runtime.mode == TradingMode.PAPER


def test_flat_alias_invalid_value_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un valor plano invalido (TRADING_MODE=garbage) propaga ValidationError."""
    config_dir = tmp_path / "config"
    _write_minimal_config(config_dir)

    for k in _FLAT_ALIAS_ENV_VARS:
        monkeypatch.delenv(k, raising=False)

    monkeypatch.setenv("TRADING_MODE", "garbage")

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        load_settings(config_dir=config_dir, env_file=None)


def test_flat_alias_boolean_coercion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """LIVE_TRADING_ENABLED acepta '0','1','yes','false' segun coercion Pydantic v2."""
    config_dir = tmp_path / "config"
    _write_minimal_config(config_dir)

    for k in _FLAT_ALIAS_ENV_VARS:
        monkeypatch.delenv(k, raising=False)

    for truthy in ("true", "True", "1", "yes"):
        monkeypatch.setenv("LIVE_TRADING_ENABLED", truthy)
        monkeypatch.setenv("I_UNDERSTAND_THE_RISKS", "true")
        settings = load_settings(config_dir=config_dir, env_file=None)
        assert settings.runtime.live_trading_enabled is True, truthy

    for falsy in ("false", "False", "0", "no"):
        monkeypatch.setenv("LIVE_TRADING_ENABLED", falsy)
        monkeypatch.delenv("I_UNDERSTAND_THE_RISKS", raising=False)
        settings = load_settings(config_dir=config_dir, env_file=None)
        assert settings.runtime.live_trading_enabled is False, falsy


def test_flat_alias_extra_ignore_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Vars no mapeadas en .env no rompen load_settings (extra='ignore')."""
    config_dir = tmp_path / "config"
    _write_minimal_config(config_dir)

    for k in _FLAT_ALIAS_ENV_VARS:
        monkeypatch.delenv(k, raising=False)

    monkeypatch.setenv("MY_RANDOM_VAR", "42")
    monkeypatch.setenv("ANOTHER_UNKNOWN_KEY", "whatever")

    settings = load_settings(config_dir=config_dir, env_file=None)
    assert settings.runtime.mode == TradingMode.PAPER  # defaults intactos


def test_nested_override_of_unrelated_deep_path_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Paths profundos no listados en FLAT_ENV_ALIASES se siguen pisando via env_nested_delimiter."""
    config_dir = tmp_path / "config"
    _write_minimal_config(config_dir)

    for k in _FLAT_ALIAS_ENV_VARS:
        monkeypatch.delenv(k, raising=False)

    monkeypatch.setenv("RUNTIME__SCHEDULER__SCANNER_INTERVAL_SECONDS", "90")

    settings = load_settings(config_dir=config_dir, env_file=None)
    assert settings.runtime.scheduler.scanner_interval_seconds == 90
    # El YAML default para TRADING_MODE sigue siendo 'paper' (no fue pisado por env).
    assert settings.runtime.mode == TradingMode.PAPER


def test_dotenv_file_empty_value_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Una linea vacia en .env (TRADING_MODE= sin valor) no pisa el default YAML."""
    config_dir = tmp_path / "config"
    _write_minimal_config(config_dir)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "TRADING_MODE=\nEXCHANGE_ID=coinbase\n",
        encoding="utf-8",
    )

    for k in _FLAT_ALIAS_ENV_VARS:
        monkeypatch.delenv(k, raising=False)

    # Pin contract: python-dotenv expone claves con valor vacio como value="";
    # FlatEnvAliasSource depende de este comportamiento en su rama
    # `if v is not None and v != ""`. Si python-dotenv cambia y empieza a
    # omitir keys vacios, parsed.get("TRADING_MODE") devuelve None y el
    # assert revienta — señal ruidosa para revisar el skip-branch.
    from dotenv import dotenv_values

    parsed = dotenv_values(env_file)
    # Pineado laxo: contrato relevante (TRADING_MODE vacio, EXCHANGE_ID
    # presente) sin acoplar a claves extra o normalizacion de quote/whitespace
    # que una futura version benigna de python-dotenv pueda introducir.
    assert parsed.get("TRADING_MODE") == ""
    assert parsed["EXCHANGE_ID"] == "coinbase"

    settings = load_settings(config_dir=config_dir, env_file=env_file)
    # TRADING_MODE empty -> FlatEnvAliasSource salta el branch .env -> YAML default gana.
    assert settings.runtime.mode == TradingMode.PAPER
    # EXCHANGE_ID sigue mapeando desde el archivo .env (path diferente).
    assert settings.exchange.id == "coinbase"
