"""DEF-RUN-015 — un cierre es una petición, una reversión no existe.

El defecto: ``PaperBroker.execute_signal`` cerraba una posición cuando llegaba una señal
del lado contrario y devolvía ``ClosedTrade``. Los llamadores del runtime contaban ese
valor como una orden creada, la pierna inversa nunca se abría, y ninguna fila decía que
lo ocurrido había sido una salida. Además, en ``PaperCycleEngine`` la señal contraria
pasaba por las puertas de **entrada** (``max_open_positions``, límite diario, cooldown)
antes de llegar al broker, así que una salida podía quedar bloqueada por un límite de
entrada.

Contrato que fijan estos tests:

1. ``close_position`` cierra explícitamente y devuelve ``ClosedTrade``; sobre libro plano
   es un no-op observable, no un error y no una apertura.
2. ``execute_signal`` con ``metadata.intent == "CLOSE"`` cierra y nunca abre.
3. una señal contraria **sin** ``intent == "CLOSE"`` no cierra y no abre: lanza
   ``BrokerOrderError`` y deja el libro intacto (fail closed, con nombre).
4. el ciclo canónico resuelve la ocupación **antes** de las puertas de entrada: una señal
   contraria es una petición de salida contada en ``exits_closed``, no una orden creada;
5. la salida ocurre aunque ``max_open_positions`` ya esté alcanzado.
"""

from __future__ import annotations

from typing import Any

import pytest

from trading_bot.execution.idempotency import IdempotencyGuard
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.broker import BrokerOrderError, ClosedTrade, PaperBroker
from trading_bot.paper.paper_cycle import PaperCycleEngine
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
from trading_bot.research.strategy_router import StrategyRouter
from trading_bot.research.types import AlphaSignal
from trading_bot.risk.manager import RiskManager
from trading_bot.strategies.types import Signal

TS0 = 1_700_000_000_000
SYMBOL = "BTC/USDT"


def _policy() -> Any:
    from trading_bot.config.risk import DefensiveBlocks, Risk

    return Risk.model_construct(
        max_risk_per_trade_pct=1.0,
        max_daily_loss_pct=3.0,
        max_weekly_loss_pct=7.0,
        max_daily_drawdown_pct=5.0,
        max_total_drawdown_pct=15.0,
        max_open_positions=1,
        max_trades_per_day=100,
        max_consecutive_losses=3,
        consecutive_loss_cooldown_minutes=60,
        max_asset_exposure_pct=20.0,
        max_total_exposure_pct=80.0,
        min_order_notional_usdt=10.0,
        max_order_notional_usdt=1_000.0,
        default_stop_loss_pct=0.5,
        default_take_profit_pct=1.0,
        blocks=DefensiveBlocks.model_construct(),
        kill_switch_enabled=True,
        live_trading_enabled=False,
    )


def _signal(side: str, price: float, *, intent: str | None = None, symbol: str = SYMBOL) -> Signal:
    metadata: dict[str, Any] = {"notional_usdt": 500.0}
    if intent is not None:
        metadata["intent"] = intent
    return Signal(
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        strategy_name="ema_crossover",
        timeframe="5m",
        confidence=0.6,
        price=price,
        stop_loss_pct=0.5,
        take_profit_pct=1.0,
        metadata=metadata,
    )


def _bars(symbol: str, n: int = 60) -> list[OHLCV]:
    out: list[OHLCV] = []
    for i in range(n):
        price = 100.0 + i
        out.append(
            OHLCV(
                symbol=symbol,
                timestamp=TS0 + i * 60_000,
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.5,
                volume=1_000.0,
            )
        )
    return out


class _ShortFamily:
    """Emite un SHORT en la última barra: la señal contraria de un largo abierto."""

    family_name = "ema_crossover"

    def generate(self, candles: Any, indicators: Any, features: Any = None, **kw: Any) -> list[AlphaSignal]:
        last = candles[-1]
        return [
            AlphaSignal(
                family=self.family_name,
                symbol=last.symbol,
                timestamp=last.timestamp,
                direction="SHORT",
                entry_reference=last.close,
                structural_stop=last.close * 1.01,
                timeframe="5m",
            )
        ]


class _LongFamily(_ShortFamily):
    def generate(self, candles: Any, indicators: Any, features: Any = None, **kw: Any) -> list[AlphaSignal]:
        last = candles[-1]
        return [
            AlphaSignal(
                family=self.family_name,
                symbol=last.symbol,
                timestamp=last.timestamp,
                direction="LONG",
                entry_reference=last.close,
                structural_stop=last.close * 0.99,
                timeframe="5m",
            )
        ]


def _strategy_map(direction: str) -> dict[str, dict[str, Any]]:
    return {
        "ema_crossover": {
            "family": "ema_crossover",
            "regimes": [],
            "direction": direction,
            "enabled": True,
            "status": "PAPER_ACTIVE",
            "priority": 0.0,
        }
    }


def _engine(family: Any, direction: str, *, risk: RiskManager, broker: PaperBroker) -> PaperCycleEngine:
    return PaperCycleEngine(
        asset_registry=CryptoAssetAgentRegistry(),
        router=StrategyRouter(),
        strategy_map=_strategy_map(direction),
        families={"ema_crossover": family},
        risk_manager=risk,
        broker=broker,
        indicator_fn=lambda candles: {},
        idempotency=IdempotencyGuard(),
    )


# --------------------------------------------------------------------------- #
# broker: tres caminos, tres nombres
# --------------------------------------------------------------------------- #


def test_close_position_is_explicit_and_returns_the_closed_trade() -> None:
    broker = PaperBroker(equity=10_000.0)
    broker.execute_signal(_signal("buy", 100.0))
    assert SYMBOL in broker.positions

    trade = broker.close_position(SYMBOL, 101.0, "EXPLICIT_TEST_CLOSE")

    assert isinstance(trade, ClosedTrade)
    assert SYMBOL not in broker.positions
    assert broker.closed_trades[-1] is trade


def test_close_position_on_a_flat_book_is_a_noop() -> None:
    broker = PaperBroker(equity=10_000.0)

    trade = broker.close_position(SYMBOL, 101.0, "EXPLICIT_TEST_CLOSE")

    assert trade is None
    assert not broker.positions
    assert not broker.closed_trades


def test_a_close_intent_closes_and_never_opens() -> None:
    broker = PaperBroker(equity=10_000.0)
    broker.execute_signal(_signal("buy", 100.0))

    result = broker.execute_signal(_signal("sell", 101.0, intent="CLOSE"))

    assert isinstance(result, ClosedTrade)
    assert not broker.positions
    #: Un cierre no deja ninguna posición abierta, ni siquiera la del lado contrario.
    assert len(broker.closed_trades) == 1
    assert broker.extract_state()["fills_opened"] == 1
    assert broker.extract_state()["fills_closed"] == 1


def test_an_opposite_signal_without_close_intent_is_refused_and_changes_nothing() -> None:
    broker = PaperBroker(equity=10_000.0)
    opened = broker.execute_signal(_signal("buy", 100.0))
    assert opened is not None

    with pytest.raises(BrokerOrderError) as excinfo:
        broker.execute_signal(_signal("sell", 101.0))

    assert "IMPLICIT_REVERSAL_FORBIDDEN" in str(excinfo.value)
    #: Fail closed: ni cierre silencioso ni apertura inversa.
    assert broker.positions[SYMBOL].side == "buy"
    assert not broker.closed_trades


def test_a_signal_without_a_stop_is_refused_by_the_broker() -> None:
    """El broker ya no inventa un 1 %: el stop viene aprobado por riesgo o no se opera."""
    broker = PaperBroker(equity=10_000.0)
    no_stop = Signal(
        symbol=SYMBOL,
        side="buy",
        strategy_name="ema_crossover",
        timeframe="5m",
        confidence=0.6,
        price=100.0,
        metadata={"notional_usdt": 500.0},
    )

    with pytest.raises(BrokerOrderError) as excinfo:
        broker.execute_signal(no_stop)

    assert "STOP_LOSS_REQUIRED" in str(excinfo.value)
    assert not broker.positions


# --------------------------------------------------------------------------- #
# ciclo canónico: la ocupación se resuelve antes de las puertas de entrada
# --------------------------------------------------------------------------- #


def test_an_opposite_signal_closes_and_does_not_reverse() -> None:
    broker = PaperBroker(equity=10_000.0)
    risk = RiskManager(risk=_policy(), equity=10_000.0)
    engine = _engine(_LongFamily(), "LONG", risk=risk, broker=broker)
    timestamps = {SYMBOL: TS0 + 59 * 60_000}

    first = engine.run_cycle_sync({SYMBOL: _bars(SYMBOL)}, timestamps)
    assert first.orders_created == 1
    assert broker.positions[SYMBOL].side == "buy"

    #: La misma barra, un router que ahora pide SHORT: la señal contraria es una
    #: *petición de salida*, nunca una orden de apertura inversa.
    engine._strategy_map = _strategy_map("SHORT")
    engine._families = {"ema_crossover": _ShortFamily()}
    engine.bump_state_version("test_opposite_signal")
    second = engine.run_cycle_sync({SYMBOL: _bars(SYMBOL)}, timestamps)

    assert second.orders_created == 0
    assert second.exits_requested == 1
    assert second.exits_closed == 1
    assert not broker.positions, "the short leg must not be opened"
    assert broker.closed_trades


def test_an_exit_is_not_blocked_by_an_entry_limit() -> None:
    """``max_open_positions`` no puede impedir una salida."""
    broker = PaperBroker(equity=10_000.0)
    risk = RiskManager(risk=_policy(), equity=10_000.0)
    broker.execute_signal(_signal("buy", 100.0))
    #: El libro de riesgo cree que ya no cabe nada más.
    assert len(risk.open_positions) == 0
    risk.open_positions = {"ETH/USDT": {"notional_usdt": 500.0}}
    assert risk.risk.max_open_positions == 1

    engine = _engine(_ShortFamily(), "SHORT", risk=risk, broker=broker)
    counts = engine.run_cycle_sync({SYMBOL: _bars(SYMBOL)}, {SYMBOL: TS0 + 59 * 60_000})

    assert not broker.positions
    assert counts.exits_closed == 1
    assert counts.orders_created == 0
    assert not any(r["stage"] == "risk" for r in counts.rejections)


def test_a_same_side_signal_does_not_open_a_second_position() -> None:
    broker = PaperBroker(equity=10_000.0)
    risk = RiskManager(risk=_policy(), equity=10_000.0)
    engine = _engine(_LongFamily(), "LONG", risk=risk, broker=broker)
    timestamps = {SYMBOL: TS0 + 59 * 60_000}

    engine.run_cycle_sync({SYMBOL: _bars(SYMBOL)}, timestamps)
    position_id = broker.positions[SYMBOL].position_id
    #: Una barra nueva ⇒ un intento nuevo (cloid distinto): lo que se prueba aquí es la
    #: ocupación del libro, no la idempotencia del mismo intento.
    engine.bump_state_version("test_same_side")
    counts = engine.run_cycle_sync(
        {SYMBOL: _bars(SYMBOL, n=61)}, {SYMBOL: TS0 + 60 * 60_000}
    )

    assert counts.orders_created == 0
    assert counts.same_side_skips == 1
    assert broker.positions[SYMBOL].position_id == position_id


def test_the_new_counters_are_published() -> None:
    counts = _engine(
        _ShortFamily(), "SHORT", risk=RiskManager(risk=_policy(), equity=10_000.0),
        broker=PaperBroker(equity=10_000.0),
    ).run_cycle_sync({SYMBOL: _bars(SYMBOL)}, {SYMBOL: TS0 + 59 * 60_000})
    payload = counts.to_dict()
    for key in ("exits_requested", "exits_closed", "reversals_refused", "same_side_skips"):
        assert key in payload
