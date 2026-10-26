"""DEF-RUN-014 — el stop que la estrategia declara es el que se arriesga.

El defecto: ``VisionLane`` entregaba a ``RiskManager.check_signal`` un ``Signal`` sin
``stop_loss_pct``, y el manager aplicaba el default de política (0.5 %) como si la
estrategia no hubiera dicho nada. El stop del modelo se registraba como consejo y se
descartaba, así que el riesgo realizado no era el declarado y la economía del libro se
medía con una distancia que la estrategia no eligió.

Estos tests fijan el contrato que lo impide:

1. si hay stop explícito, se usa (no hay fallback silencioso) y el origen se declara;
2. si no lo hay, el default se usa **y se dice** (``source == POLICY_DEFAULT``);
3. un stop inválido es ``NO_TRADE`` con causa, nunca un tamaño inventado;
4. un stop más corto que el coste de ida y vuelta no es un límite de pérdida: con la
   política declarada ``REJECT`` es ``NO_TRADE`` con ambos números en el motivo; con
   ``REPORT`` se publica el hecho y se opera igual;
5. el sizing sigue siendo el del ``RiskManager`` y el ledger puede publicar el dinero
   realmente en riesgo (``risk_at_stop_usdt``), distinto del presupuesto cuando el clamp
   de notional es el que manda.

Ningún límite de ``config/risk.yaml`` se toca: el guard de coste solo puede reducir el
conjunto de operaciones, nunca aumentar el tamaño.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.risk.manager import RiskManager
from trading_bot.strategies.types import Signal

REPO = Path(__file__).resolve().parents[3]
SYMBOL = "BTC/USDT"
PRICE = 100_000.0

#: Los dos números que deciden si un stop es ejecutable. El coste de ida y vuelta del
#: modelo de costes vigente a 500 USDT de stake es 24.79 bps (``cost_for``); el stop que
#: el modelo declaró en las sesiones live fue 5.56 bps.
ROUND_TRIP_COST_BPS = 24.786423721316186
MODEL_STOP_PCT = 0.0556  # 5.56 bps


def _policy():
    return load_settings(config_dir=REPO / "config", env_file=None).risk


def _manager(**kwargs: object) -> RiskManager:
    return RiskManager(risk=_policy(), equity=10_000.0, **kwargs)  # type: ignore[arg-type]


def _signal(*, stop: float | None = None, take: float | None = None) -> Signal:
    return Signal(
        symbol=SYMBOL,
        side="buy",
        strategy_name="ai_vision",
        timeframe="1h",
        confidence=0.6,
        price=PRICE,
        stop_loss_pct=stop,
        take_profit_pct=take,
    )


def test_an_explicit_stop_survives_the_risk_manager() -> None:
    """0.2 % pedido es 0.2 % arriesgado, no el 0.5 % de la política."""
    check = _manager().check_signal(_signal(stop=0.2, take=0.5))

    assert check.approved is True
    size = check.position_size
    assert size is not None
    assert size.stop_loss_pct == pytest.approx(0.2)
    assert size.take_profit_pct == pytest.approx(0.5)
    resolution = check.stop_resolution
    assert resolution is not None
    assert resolution.source == "SIGNAL"
    assert resolution.requested_stop_pct == pytest.approx(0.2)
    assert resolution.effective_stop_pct == pytest.approx(0.2)


def test_an_absent_stop_uses_the_default_and_declares_it() -> None:
    check = _manager().check_signal(_signal())

    size = check.position_size
    assert size is not None
    assert size.stop_loss_pct == pytest.approx(_policy().default_stop_loss_pct)
    resolution = check.stop_resolution
    assert resolution is not None
    assert resolution.source == "POLICY_DEFAULT"
    assert resolution.requested_stop_pct is None
    #: El motivo no puede ser vacío: "no dijo nada" es una decisión, no una ausencia.
    assert resolution.reason


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, 100.0, 150.0])
def test_an_invalid_stop_is_a_no_trade_with_a_cause(bad: float) -> None:
    check = _manager().check_signal(_signal(stop=bad))

    assert check.approved is False
    assert check.position_size is None
    assert check.blocked_by == "invalid_stop"
    assert check.reason and ("stop" in check.reason.lower())


def test_a_stop_inside_the_round_trip_cost_is_refused_when_the_policy_says_so() -> None:
    manager = _manager(
        cost_bps_for=lambda symbol, notional: ROUND_TRIP_COST_BPS,
        stop_cost_policy="REJECT",
    )
    check = manager.check_signal(_signal(stop=MODEL_STOP_PCT))

    assert check.approved is False
    assert check.blocked_by == "stop_inside_costs"
    assert check.position_size is None
    #: Los dos números que justifican la negativa están en el motivo, no en un informe.
    assert "5.56" in check.reason or "5.5" in check.reason
    assert "24.7" in check.reason or "24.786" in check.reason


def test_the_same_stop_is_only_reported_under_the_report_policy() -> None:
    manager = _manager(
        cost_bps_for=lambda symbol, notional: ROUND_TRIP_COST_BPS,
        stop_cost_policy="REPORT",
    )
    check = manager.check_signal(_signal(stop=MODEL_STOP_PCT))

    assert check.approved is True
    resolution = check.stop_resolution
    assert resolution is not None
    assert resolution.round_trip_cost_bps == pytest.approx(ROUND_TRIP_COST_BPS)
    assert resolution.stop_distance_bps == pytest.approx(MODEL_STOP_PCT * 100.0)
    assert resolution.stop_clears_costs is False


def test_a_stop_that_clears_its_costs_passes() -> None:
    manager = _manager(
        cost_bps_for=lambda symbol, notional: ROUND_TRIP_COST_BPS,
        stop_cost_policy="REJECT",
    )
    check = manager.check_signal(_signal(stop=0.5))

    assert check.approved is True
    resolution = check.stop_resolution
    assert resolution is not None
    assert resolution.stop_clears_costs is True


def test_risk_at_stop_is_the_money_the_sizing_really_risks() -> None:
    """El clamp de notional es el que manda: el presupuesto no es el riesgo real."""
    check = _manager().check_signal(_signal(stop=0.5))
    size = check.position_size
    resolution = check.stop_resolution
    assert size is not None and resolution is not None

    assert size.notional_usdt == pytest.approx(_policy().max_order_notional_usdt)
    assert resolution.sizing_basis == "MAX_ORDER_NOTIONAL_CLAMP"
    assert resolution.risk_at_stop_usdt == pytest.approx(
        size.notional_usdt * size.stop_loss_pct / 100.0, abs=1e-9
    )
    assert resolution.risk_at_stop_usdt < resolution.risk_budget_usdt


def test_no_risk_limit_is_relaxed_to_make_the_stop_fit() -> None:
    policy = _policy()
    manager = _manager()
    for stop in (0.2, 0.5, 2.0, 10.0):
        check = manager.check_signal(_signal(stop=stop))
        size = check.position_size
        assert size is not None
        assert policy.min_order_notional_usdt <= size.notional_usdt <= policy.max_order_notional_usdt
        assert size.notional_usdt <= manager.equity * policy.max_total_exposure_pct / 100.0
        assert size.notional_usdt <= manager.equity * policy.max_asset_exposure_pct / 100.0
        assert size.quantity == pytest.approx(size.notional_usdt / PRICE)
