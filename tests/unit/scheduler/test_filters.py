"""Tests unitarios para ``src/trading_bot/scheduler/filters.py``.

Pinea el contrato de los dos guards pre-batch/per-par + los helpers
de parsing HH:MM.

Cobertura esperada per DoD F2 (TSK-104.2.2): 10+ tests verde
(cubren kill-switch enabled/disabled + active-hours normal/wrap/
boundary/empty + parse_hhmm_to_minute valid + invalid).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_bot.config.exchange import Exchange
from trading_bot.config.indicators import (
    IndicatorConfig,
    IndicatorsConfig,
    IndicatorsGlobal,
)
from trading_bot.config.risk import DefensiveBlocks, Risk
from trading_bot.config.runtime import (
    Runtime,
    Scheduler,
    SchedulerActiveHours,
    TradingMode,
)
from trading_bot.config.settings import Settings
from trading_bot.config.strategies import (
    StrategiesConfig,
    StrategiesGlobal,
    StrategyConfig,
    StrategyState,
)
from trading_bot.config.universe import PairSpec, Universe, UniverseFilters
from trading_bot.scheduler.filters import (
    PreBatchDecision,
    active_hours_window_from_settings,
    check_active_hours,
    check_kill_switch,
    parse_hhmm_to_minute,
)

# ---------------------------------------------------------------------------
# Helpers de construccion de Settings (Pydantic v2 Aggregator).
# ---------------------------------------------------------------------------



def _make_risk(
    *,
    kill_switch_enabled: bool = False,
) -> Risk:
    """Construye un ``Risk`` minimo valido para los tests del scheduler.

    Pine contract: el resto de campos usan los defaults del YAML
    (`risk.yaml`) o del modelo. Solo override lo que el test usa.
    """
    return Risk(
        max_risk_per_trade_pct=1.0,
        max_daily_loss_pct=2.0,
        max_weekly_loss_pct=5.0,
        max_daily_drawdown_pct=3.0,
        max_total_drawdown_pct=10.0,
        max_open_positions=5,
        max_trades_per_day=20,
        max_consecutive_losses=3,
        consecutive_loss_cooldown_minutes=15,
        max_asset_exposure_pct=20.0,
        max_total_exposure_pct=80.0,
        min_order_notional_usdt=10.0,
        max_order_notional_usdt=1_000.0,
        default_stop_loss_pct=1.5,
        default_take_profit_pct=2.5,
        blocks=DefensiveBlocks(),
        kill_switch_enabled=kill_switch_enabled,
        live_trading_enabled=False,
    )


def _make_exchange() -> Exchange:
    """Exchange minimo valido para tests."""
    return Exchange(id="binance", sandbox=True)


def _make_runtime(
    *,
    active_hours_start: str = "00:00",
    active_hours_end: str = "23:59",
) -> Runtime:
    """Runtime minimo valido para tests, overrideando active_hours."""
    return Runtime(
        mode=TradingMode.PAPER,
        live_trading_enabled=False,
        require_manual_confirmation_for_live=True,
        i_understand_the_risks=False,
        scheduler=Scheduler(
            timezone="UTC",
            active_hours=SchedulerActiveHours(
                start=active_hours_start,
                end=active_hours_end,
            ),
        ),
    )


def _make_universe() -> Universe:
    """Universe minimo valido (los tests no usan el contenido)."""
    return Universe(
        name="sprint002-test-universe",
        description="Minimal Universe fixture for scheduler tests (TSK-104.2.2).",
        base_currency="USDT",
        pairs=[PairSpec(symbol="BTC/USDT", enabled=True)],
        timeframes=["5m"],
        filters=UniverseFilters(
            min_24h_volume_usdt=5_000_000,
            max_spread_bps=50,
            max_atr_percent=8.0,
            min_atr_percent=0.5,
        ),
    )


def _make_strategies_config() -> StrategiesConfig:
    """StrategiesConfig minimo valido (los tests no usan el contenido)."""
    return StrategiesConfig(
        strategies={
            "trend_pullback_scalping": StrategyConfig(
                enabled=False,
                state=StrategyState.RESEARCH,
                timeframes=["5m"],
                indicators=["ema", "rsi"],
            ),
        },
        global_=StrategiesGlobal(
            required_progression=["research", "paper", "live_candidate"],
            require_min_trades_for_promotion=30,
        ),
    )


def _make_indicators_config() -> IndicatorsConfig:
    """IndicatorsConfig minimo valido (los tests no usan el contenido)."""
    return IndicatorsConfig(
        indicators={
            "ema": IndicatorConfig(type="ema"),
        },
        global_=IndicatorsGlobal(require_min_candles=100),
    )


def _make_settings(
    *,
    kill_switch_enabled: bool = False,
    active_hours_start: str = "00:00",
    active_hours_end: str = "23:59",
) -> Settings:
    """Build minimal valid ``Settings`` overriding kill_switch + active_hours.

    Pine contract: ``Settings`` es el aggregator top-level con 6
    sub-configs requeridos (universe + exchange + risk + strategies +
    indicators + runtime). Los tests solo necesitan los campos que
    ``check_kill_switch`` y ``check_active_hours`` leen, pero el
    aggregator exige los 6 sub-modelos completos. Usamos defaults
    del YAML/Model para los que no importan al scheduler.

    Cross-layer note: este helper acopla el test al shape interno de
    ``Settings``; en F4 (wiring con production paths) considerar
    mover a una factory compartida en ``tests/unit/config/conftest.py``
    para evitar duplicacion. (Reviewer Q4.d nice-to-have.)
    """
    return Settings(
        exchange=_make_exchange(),
        risk=_make_risk(kill_switch_enabled=kill_switch_enabled),
        runtime=_make_runtime(
            active_hours_start=active_hours_start,
            active_hours_end=active_hours_end,
        ),
        universe=_make_universe(),
        strategies=_make_strategies_config(),
        indicators=_make_indicators_config(),
    )


# ---------------------------------------------------------------------------
# parse_hhmm_to_minute: happy path + invalid inputs.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hhmm,expected_minute",
    [
        ("00:00", 0),
        ("00:01", 1),
        ("00:59", 59),
        ("01:00", 60),
        ("08:00", 8 * 60),
        ("08:30", 8 * 60 + 30),
        ("12:00", 12 * 60),
        ("18:00", 18 * 60),
        ("23:59", 23 * 60 + 59),
        # edge: direct swap spec uses end_hour=0..23 inclusive
        ("23:00", 23 * 60),
    ],
)
def test_parse_hhmm_to_minute_valid_inputs(hhmm: str, expected_minute: int) -> None:
    """Pinea unmarshalling HH:MM -> [0..1439] sobre 10 boundary cases."""
    assert parse_hhmm_to_minute(hhmm) == expected_minute


@pytest.mark.parametrize(
    "bad_input,why",
    [
        ("", "empty string"),
        ("8", "no colon"),
        ("8:00", "single-digit hour"),
        ("25:00", "hour out of range"),
        ("-1:00", "negative hour"),
        ("08:60", "minute out of range"),
        ("08:-1", "negative minute"),
        ("08:00:00", "too many parts"),
        ("aa:bb", "non-numeric"),
        ("08;00", "wrong separator"),
    ],
)
def test_parse_hhmm_to_minute_invalid_inputs_raise_value_error(bad_input: str, why: str) -> None:
    """Pinea fail-fast: cualquier input malformed lanza ValueError claro."""
    with pytest.raises(ValueError, match=r"HH|MM|parts|non-numeric"):
        parse_hhmm_to_minute(bad_input)


def test_parse_hhmm_to_minute_non_string_input_raises() -> None:
    """Defensivo: cualquier tipo no-string -> ValueError explicito."""
    with pytest.raises(ValueError, match=r"must be a string"):
        parse_hhmm_to_minute(None)


# ---------------------------------------------------------------------------
# active_hours_window_from_settings: round-trip + transformation.
# ---------------------------------------------------------------------------


def test_active_hours_window_from_settings_default_window() -> None:
    """Default 00:00..23:59 -> window(0, 1439) (24h casi entero)."""
    settings = _make_settings(
        active_hours_start="00:00",
        active_hours_end="23:59",
    )
    window = active_hours_window_from_settings(settings)
    assert window.start_minute == 0
    assert window.end_minute == 23 * 60 + 59


def test_active_hours_window_from_settings_normal_window() -> None:
    """08:00..18:00 -> window(480, 1080)."""
    settings = _make_settings(
        active_hours_start="08:00",
        active_hours_end="18:00",
    )
    window = active_hours_window_from_settings(settings)
    assert window.start_minute == 480
    assert window.end_minute == 1080


def test_active_hours_window_from_settings_wrap_around_window() -> None:
    """22:00..06:00 -> window(1320, 360); wrap-around."""
    settings = _make_settings(
        active_hours_start="22:00",
        active_hours_end="06:00",
    )
    window = active_hours_window_from_settings(settings)
    assert window.start_minute == 22 * 60
    assert window.end_minute == 6 * 60


# ---------------------------------------------------------------------------
# check_kill_switch: enabled vs disabled.
# ---------------------------------------------------------------------------


def test_check_kill_switch_enabled_returns_skip() -> None:
    """Risk.kill_switch_enabled=True -> 'skip_kill_switch'."""
    settings = _make_settings(kill_switch_enabled=True)
    assert check_kill_switch(settings) == "skip_kill_switch"


def test_check_kill_switch_disabled_returns_continue() -> None:
    """Risk.kill_switch_enabled=False -> 'continue'."""
    settings = _make_settings(kill_switch_enabled=False)
    assert check_kill_switch(settings) == "continue"


# ---------------------------------------------------------------------------
# check_active_hours: normal window.
# ---------------------------------------------------------------------------


def test_check_active_hours_normal_window_hour_inside() -> None:
    """08:00..18:00, now=10:00 -> 'continue'."""
    settings = _make_settings(active_hours_start="08:00", active_hours_end="18:00")
    now = datetime(2026, 7, 4, 10, 0, tzinfo=UTC)
    assert check_active_hours(settings, now) == "continue"


def test_check_active_hours_normal_window_hour_outside() -> None:
    """08:00..18:00, now=20:00 -> 'skip_active_hours'."""
    settings = _make_settings(active_hours_start="08:00", active_hours_end="18:00")
    now = datetime(2026, 7, 4, 20, 0, tzinfo=UTC)
    assert check_active_hours(settings, now) == "skip_active_hours"


def test_check_active_hours_normal_window_boundary_inclusive_start() -> None:
    """08:00..18:00, now=08:00 (start inclusive) -> 'continue'."""
    settings = _make_settings(active_hours_start="08:00", active_hours_end="18:00")
    now = datetime(2026, 7, 4, 8, 0, tzinfo=UTC)
    assert check_active_hours(settings, now) == "continue"


def test_check_active_hours_normal_window_boundary_exclusive_end() -> None:
    """08:00..18:00, now=18:00 (end exclusive) -> 'skip_active_hours'."""
    settings = _make_settings(active_hours_start="08:00", active_hours_end="18:00")
    now = datetime(2026, 7, 4, 18, 0, tzinfo=UTC)
    assert check_active_hours(settings, now) == "skip_active_hours"


def test_check_active_hours_normal_window_minute_boundary() -> None:
    """08:00..18:00, now=08:01 (un minuto adentro) -> 'continue'."""
    settings = _make_settings(active_hours_start="08:00", active_hours_end="18:00")
    now = datetime(2026, 7, 4, 8, 1, tzinfo=UTC)
    assert check_active_hours(settings, now) == "continue"


def test_check_active_hours_normal_window_just_before_end() -> None:
    """08:00..18:00, now=17:59 -> 'continue' (ultimo minuto valido)."""
    settings = _make_settings(active_hours_start="08:00", active_hours_end="18:00")
    now = datetime(2026, 7, 4, 17, 59, tzinfo=UTC)
    assert check_active_hours(settings, now) == "continue"


# ---------------------------------------------------------------------------
# check_active_hours: wrap-around window.
# ---------------------------------------------------------------------------


def test_check_active_hours_wrap_around_hour_in_late_evening() -> None:
    """22:00..06:00, now=23:00 -> 'continue' (parte nocturna de la ventana)."""
    settings = _make_settings(active_hours_start="22:00", active_hours_end="06:00")
    now = datetime(2026, 7, 4, 23, 0, tzinfo=UTC)
    assert check_active_hours(settings, now) == "continue"


def test_check_active_hours_wrap_around_hour_in_early_morning() -> None:
    """22:00..06:00, now=03:00 -> 'continue' (parte matutina de la ventana)."""
    settings = _make_settings(active_hours_start="22:00", active_hours_end="06:00")
    now = datetime(2026, 7, 4, 3, 0, tzinfo=UTC)
    assert check_active_hours(settings, now) == "continue"


def test_check_active_hours_wrap_around_hour_outside_window() -> None:
    """22:00..06:00, now=12:00 -> 'skip_active_hours' (mediodia no esta)."""
    settings = _make_settings(active_hours_start="22:00", active_hours_end="06:00")
    now = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
    assert check_active_hours(settings, now) == "skip_active_hours"


def test_check_active_hours_wrap_around_minute_boundary_start() -> None:
    """22:00..06:00, now=21:59 -> 'skip_active_hours' (justo antes de start)."""
    settings = _make_settings(active_hours_start="22:00", active_hours_end="06:00")
    now = datetime(2026, 7, 4, 21, 59, tzinfo=UTC)
    assert check_active_hours(settings, now) == "skip_active_hours"


def test_check_active_hours_wrap_around_minute_boundary_end() -> None:
    """22:00..06:00, now=06:00 (end exclusive en wrap) -> 'skip_active_hours'."""
    settings = _make_settings(active_hours_start="22:00", active_hours_end="06:00")
    now = datetime(2026, 7, 4, 6, 0, tzinfo=UTC)
    assert check_active_hours(settings, now) == "skip_active_hours"


# ---------------------------------------------------------------------------
# check_active_hours: empty window + default 24h.
# ---------------------------------------------------------------------------


def test_check_active_hours_empty_window_always_skips() -> None:
    """Window start == end -> ventana vacia, siempre skip."""
    settings = _make_settings(active_hours_start="10:00", active_hours_end="10:00")
    for hour in [0, 6, 10, 12, 18, 23]:
        now = datetime(2026, 7, 4, hour, 0, tzinfo=UTC)
        assert check_active_hours(settings, now) == "skip_active_hours"


def test_check_active_hours_default_window_minute_precision() -> None:
    """00:00..23:59 -> 'continue' para todo minuto del dia EXCEPTO el ultimo
    minuto exacto (23:59:00), pineado por strict-< boundary contract
    (03-specify §4 verbatim): el minute_of_day == end_minute queda fuera.
    Cobertura separada del caso boundary en
    test_check_active_hours_default_window_end_minute_excluded.
    """
    settings = _make_settings(active_hours_start="00:00", active_hours_end="23:59")
    for hour in [0, 6, 12, 18, 23]:
        for minute in [0, 30]:
            now = datetime(2026, 7, 4, hour, minute, tzinfo=UTC)
            assert check_active_hours(settings, now) == "continue"


def test_check_active_hours_default_window_end_minute_excluded() -> None:
    """00:00..23:59 con now=23:59 (minute_of_day == end_minute exact) ->
    'skip_active_hours' por pine contract strict-< (03-specify §4).

    Sentinel anti-regresion: si alguien refactoriza a ``<=`` end
    sin actualizar el spec, este test cae.
    """
    settings = _make_settings(active_hours_start="00:00", active_hours_end="23:59")
    now = datetime(2026, 7, 4, 23, 59, tzinfo=UTC)
    assert check_active_hours(settings, now) == "skip_active_hours"


# ---------------------------------------------------------------------------
# Pinpo contract: PreBatchDecision cubre los 4 valores (Literal exhaustivo).
# ---------------------------------------------------------------------------


def test_pre_batch_decision_literal_exhaustivo() -> None:
    """ADR lock: el Literal ``PreBatchDecision`` contiene los 4 valores pineados."""
    from typing import get_args

    expected = {
        "continue",
        "skip_kill_switch",
        "skip_empty_universe",
        "skip_active_hours",
    }
    assert set(get_args(PreBatchDecision)) == expected
