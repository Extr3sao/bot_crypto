"""003I — el ciclo de cierre de una operación PAPER, observado y reconciliado.

H8 de 003H quedó bloqueado porque ninguna sesión había *observado* la transición
devengado→realizado: la rama de cierre estaba cubierta por tests, nunca por una corrida
cuyo ledger pudiera re-derivarse. Estos tests atacan ``VisionLane.run`` con el
``PaperBroker`` y el ``RiskManager`` de producción —``TEST_TARGET == RUNTIME_TARGET``— y
fijan las propiedades que el verificador independiente vuelve a comprobar desde los bytes:

1. un cierre con beneficio y un cierre con pérdida mueven el efectivo exactamente por su
   PnL neto, y el resultado realizado deja de ser cero;
2. ambas comisiones se cobran en el cierre, una sola vez, y la de entrada deja de estar
   devengada cuando la posición se cierra;
3. un cierre retira la exposición completa: la posición sale del libro y la cantidad
   cerrada es la cantidad ejecutada (el modelo no expresa cierres parciales);
4. el libro restaurado desde el estado persistido reconcilia con el libro vivo;
5. dos corridas con las mismas entradas escriben el mismo ledger, fila a fila.

Un cierre controlado demuestra que la contabilidad funciona. **No** demuestra que la
estrategia sea rentable, y ningún informe debe presentarlo como tal.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.paper.broker import PaperBroker
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import read_entries
from trading_bot.vision.provider import ReplayProvider, VisionResponse
from trading_bot.vision.settings import load_vision_config

HOUR_MS = 3_600_000
START_MS = int(datetime(2026, 10, 19, tzinfo=UTC).timestamp() * 1000)
REPO = Path(__file__).resolve().parents[3]
SYMBOL = "BTC/USDT"
STOP_PCT = 0.5
TAKE_PCT = 0.75


def _answer(symbol: str, action: str) -> str:
    stop = STOP_PCT if action != "NO_TRADE" else None
    take = TAKE_PCT if action != "NO_TRADE" else None
    return (
        f'{{"schema_version":"ai-vision-decision/1","symbol":"{symbol}","action":"{action}",'
        f'"confidence":0.6,"horizon_bars":6,"stop_loss_pct":{stop},"take_profit_pct":{take},'
        '"invalidation":null,"rationale":"Controlled 003I close cycle."}'
    )


class FirstActionThenFlat(ReplayProvider):
    """``first_action`` en la primera llamada y ``NO_TRADE`` después: un solo relleno."""

    first_action = "LONG"

    def __init__(self) -> None:
        self.seen = 0
        super().__init__(self._script)

    def _script(self, request) -> str:  # type: ignore[no-untyped-def]
        self.seen += 1
        return _answer(request.chart.symbol, self.first_action if self.seen == 1 else "NO_TRADE")

    def analyze(self, request) -> VisionResponse:  # type: ignore[override]
        response = super().analyze(request)
        return replace(response, latency_ms=0)


class FirstShortThenFlat(FirstActionThenFlat):
    first_action = "SHORT"


def _bars(path: list[tuple[float, float]]) -> list[Bar]:
    out: list[Bar] = []
    for index, (opened, closed) in enumerate(path):
        pad = 0.0005
        out.append(
            Bar(
                ts_ms=START_MS + index * HOUR_MS,
                open=opened,
                high=max(opened, closed) * (1.0 + pad),
                low=min(opened, closed) * (1.0 - pad),
                close=closed,
                volume=100.0 + index,
            )
        )
    return out


FLAT = [(100.0, 100.0)] * 21
UP = [*FLAT, (100.0, 101.0), (101.0, 101.2)]
DOWN = [*FLAT, (100.0, 99.0), (99.0, 99.0)]
STILL_OPEN = [*FLAT, (100.0, 100.3), (100.3, 100.4), (100.4, 100.4)]


def _config():
    base = load_vision_config(env={})
    return base.__class__(
        provider=base.provider,
        lane=base.lane.__class__(
            timeframe="1h",
            window_bars=20,
            decision_every_bars=1,
            max_calls_per_run=50,
            max_estimated_spend_usd=1.0,
            data_delay_ms=0,
        ),
    )


def _bar(index: int, *, open_: float, high: float, low: float, close: float) -> Bar:
    """Una vela cuyo rango se declara a mano: ``_bars`` lo deriva y no puede tocar dos niveles."""

    return Bar(
        ts_ms=START_MS + index * HOUR_MS,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100.0 + index,
    )


def _run(
    tmp_path: Path, path: list[tuple[float, float]], *, short: bool = False, name: str = "book"
):
    return _run_on_bars(tmp_path, _bars(path), short=short, name=name)


def _run_on_bars(tmp_path: Path, bars: list[Bar], *, short: bool = False, name: str = "book"):
    ledger = tmp_path / f"{name}.jsonl"
    lane = VisionLane(
        series={SYMBOL: bars},
        provider=FirstShortThenFlat() if short else FirstActionThenFlat(),
        config=_config(),
        risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
        ledger_path=ledger,
        equity=10_000.0,
        book_id="003i-test-book",
        decision_every_bars=1,
    )
    summary = lane.run()
    entries = [row["entry"] for row in read_entries(ledger)]
    return lane, summary, entries


def _closes(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry.get("kind") == "CLOSE"]


def test_profit_close_moves_cash_by_its_net_pnl(tmp_path):
    _, summary, entries = _run(tmp_path, UP)
    closes = _closes(entries)

    assert len(closes) == 1
    close = closes[0]
    assert close["exit_reason"] == "take_profit"
    assert close["pnl_net_usdt"] > 0
    assert summary["closed_trades"] == 1
    assert summary["pnl_realised_usdt"] == pytest.approx(close["pnl_net_usdt"], abs=1e-8)
    #: El resumen publica el efectivo con 6 decimales y el PnL del cierre con 8.
    assert summary["final_equity_usdt"] == pytest.approx(10_000.0 + close["pnl_net_usdt"], abs=1e-6)
    assert summary["open_positions_at_end"] == {}
    assert summary["reconciliation"]["identities"]["cash_rebuilds_from_realised_pnl"]


def test_loss_close_moves_cash_the_other_way(tmp_path):
    _, summary, entries = _run(tmp_path, DOWN)
    closes = _closes(entries)

    assert len(closes) == 1
    close = closes[0]
    assert close["exit_reason"] == "stop_loss"
    assert close["pnl_net_usdt"] < 0
    #: El resumen publica el efectivo con 6 decimales y el PnL del cierre con 8.
    assert summary["final_equity_usdt"] == pytest.approx(10_000.0 + close["pnl_net_usdt"], abs=1e-6)
    assert summary["final_equity_usdt"] < 10_000.0
    assert summary["drawdown_status"] == "MEASURED"


def test_a_short_close_uses_the_sell_side_schedule(tmp_path):
    _, summary, entries = _run(tmp_path, DOWN, short=True)
    fills = [entry for entry in entries if entry.get("kind") == "FILL"]
    closes = _closes(entries)

    assert len(fills) == 1 and len(closes) == 1
    assert fills[0]["side"] == "sell"
    #: El relleno de venta cruza el spread hacia abajo: el precio pagado es menor que la
    #: referencia, que es lo que hace que el PnL neto sea distinto del bruto.
    assert fills[0]["entry_price"] < fills[0]["reference_price"]
    assert closes[0]["pnl_net_usdt"] > 0
    assert summary["final_equity_usdt"] > 10_000.0


def test_commissions_are_charged_on_both_legs_exactly_once(tmp_path):
    _, summary, entries = _run(tmp_path, UP)
    close = _closes(entries)[0]
    fill = next(entry for entry in entries if entry.get("kind") == "FILL")

    assert close["entry_commission_usdt"] == pytest.approx(fill["entry_commission_usdt"], abs=1e-9)
    assert close["exit_commission_usdt"] > 0
    assert close["execution_cost_usdt"] > 0
    assert close["pnl_net_usdt"] == pytest.approx(
        close["reference_gross_pnl_usdt"]
        - close["execution_cost_usdt"]
        - close["entry_commission_usdt"]
        - close["exit_commission_usdt"],
        abs=1e-9,
    )
    #: Cerrada la posición, su comisión de entrada ya no está devengada: pasa a realizada
    #: una vez, y las dos mitades del libro siguen sumando el total.
    assert summary["entry_commissions_accrued_open_usdt"] == 0.0
    assert summary["costs_total_usdt"] == pytest.approx(summary["costs_realised_usdt"], abs=1e-9)
    assert summary["costs_realised_usdt"] == pytest.approx(
        close["entry_commission_usdt"]
        + close["exit_commission_usdt"]
        + close["execution_cost_usdt"],
        abs=1e-9,
    )
    assert summary["reconciliation"]["identities"]["total_costs_equal_realised_plus_accrued"]


def test_a_close_removes_the_whole_position(tmp_path):
    """El modelo PAPER no expresa cierres parciales: un cierre es la posición entera.

    La consecuencia se declara en vez de esconderse: ``_close_position`` hace ``pop`` de la
    posición y el ``ClosedTrade`` lleva su ``quantity`` completa. No existe una ruta que
    reduzca media posición y deje la otra media en el libro, así que una lectura del ledger
    nunca puede confundir un cierre parcial con uno total.
    """

    lane, _, _ = _run(tmp_path, STILL_OPEN)
    open_position = next(iter(lane.broker.positions.values()))
    quantity_before = open_position.quantity

    trade = lane.broker.check_positions({SYMBOL: 99.0})[0]

    assert trade.quantity == quantity_before
    assert trade.position_id == open_position.position_id
    assert SYMBOL not in lane.broker.positions, "la exposición cerrada debe desaparecer del libro"
    assert lane.broker.closed_trades[-1].quantity == quantity_before


def test_the_restored_book_reconciles_with_the_live_one(tmp_path):
    lane, summary, _ = _run(tmp_path, STILL_OPEN)
    marks = {SYMBOL: 100.4}
    snapshot = lane.broker.accounting_snapshot(marks)
    state = lane.broker.extract_state()

    restored = PaperBroker(equity=state["initial_equity"], book_id="003i-test-book")
    restored.restore(
        equity=state["equity"],
        initial_equity=state["initial_equity"],
        fills_opened=state["fills_opened"],
        fills_closed=state["fills_closed"],
        open_positions=list(lane.broker.positions.values()),
        closed_trades=lane.broker.closed_trades_rows(),
    )
    after = restored.accounting_snapshot(marks)

    assert after["cash"] == pytest.approx(snapshot["cash"], abs=1e-9)
    assert after["realised_pnl"] == pytest.approx(snapshot["realised_pnl"], abs=1e-9)
    assert after["unrealised_pnl"] == pytest.approx(snapshot["unrealised_pnl"], abs=1e-9)
    assert after["accrued_entry_commissions"] == pytest.approx(
        snapshot["accrued_entry_commissions"], abs=1e-9
    )
    assert after["equity_mark_to_market"] == pytest.approx(
        snapshot["equity_mark_to_market"], abs=1e-9
    )
    assert after["identities"] == snapshot["identities"]
    assert all(after["identities"].values())
    #: El libro vivo terminó con una posición abierta y su comisión devengada; el restaurado
    #: tiene que decir lo mismo, no una versión más favorable.
    assert (
        summary["open_positions_at_end"][SYMBOL]["position_id"]
        == restored.positions[SYMBOL].position_id
    )
    assert after["accrued_entry_commissions"] > 0


def test_both_levels_in_the_same_bar_book_the_stop_not_the_target(tmp_path):
    """Una vela que toca stop y objetivo a la vez se liquida por el stop.

    ``both_hit_policy="stop_first"`` es la opción conservadora y es la que la lane usa sin
    pasarla: el orden intrabar no es observable, así que un rango que cruza los dos niveles no
    puede contarse como acierto. El TP tocado no se marca como ejecutado en ninguna fila.
    """

    bars = [
        *_bars(STILL_OPEN[:22]),
        _bar(22, open_=100.4, high=104.0, low=95.0, close=100.4),
    ]
    _, summary, entries = _run_on_bars(tmp_path, bars)
    closes = _closes(entries)

    assert len(closes) == 1
    close = closes[0]
    assert close["exit_reason"] == "stop_loss"
    #: El ledger publica el precio de referencia y el stop con 8 decimales, no con todos.
    assert close["exit_reference_price"] == pytest.approx(close["stop_loss_price"], abs=1e-8)
    assert close["pnl_net_usdt"] < 0
    assert close["exit_ts_resolution"] == "BAR_WINDOW"
    assert summary["closed_trades"] == 1
    assert summary["open_positions_at_end"] == {}
    assert all(entry.get("exit_reason") != "take_profit" for entry in entries)


def test_a_restart_from_the_persisted_book_closes_at_the_same_level(tmp_path):
    """Reanudar no cambia el desenlace: el libro restaurado cierra donde cerraría el vivo.

    La sesión se corta con la posición abierta, se restaura el estado que el broker puede
    extraer y se le entrega la misma vela con la que la corrida continua cerró. Precio, motivo y
    PnL neto tienen que coincidir al decimal; si el reinicio perdiera la comisión de entrada o el
    precio pagado, la diferencia aparecería aquí.
    """

    tail = (100.4, 99.2)
    _, _, continuous = _run(tmp_path, [*STILL_OPEN[:22], tail], name="continuous")
    continuous_close = _closes(continuous)[0]

    lane, _, _ = _run(tmp_path, STILL_OPEN[:22], name="interrupted")
    assert SYMBOL in lane.broker.positions, "el caso de prueba necesita la posición abierta"
    state = lane.broker.extract_state()
    restored = PaperBroker(equity=state["initial_equity"], book_id="003i-test-book")
    restored.restore(
        equity=state["equity"],
        initial_equity=state["initial_equity"],
        fills_opened=state["fills_opened"],
        fills_closed=state["fills_closed"],
        open_positions=list(lane.broker.positions.values()),
        closed_trades=lane.broker.closed_trades_rows(),
    )

    bar = _bars([*STILL_OPEN[:22], tail])[22]
    closed = restored.check_positions_ohlc(
        {SYMBOL: (bar.open, bar.high, bar.low, bar.close)}, gap_policy="open_on_gap"
    )

    assert len(closed) == 1
    assert closed[0].exit_reason == continuous_close["exit_reason"]
    assert float(closed[0].pnl) == pytest.approx(continuous_close["pnl_net_usdt"], abs=1e-8)
    assert float(closed[0].entry_commission) == pytest.approx(
        continuous_close["entry_commission_usdt"], abs=1e-9
    )
    assert SYMBOL not in restored.positions


def test_a_closed_position_cannot_be_closed_again(tmp_path):
    """Cerrar dos veces la misma posición no duplica ni el PnL ni la comisión.

    La guarda es estructural: ``_close_position`` hace ``pop`` de la posición, y ambos
    evaluadores (close y OHLC) iteran el libro de posiciones. No hay bandera de idempotencia que
    pueda quedar en el estado equivocado; lo que no existe no se puede volver a cerrar.
    """

    lane, _, entries = _run(tmp_path, DOWN)
    close = _closes(entries)[0]
    cash_before = lane.broker.accounting_snapshot({SYMBOL: 90.0})["cash"]
    closed_before = len(lane.broker.closed_trades)

    assert lane.broker.check_positions({SYMBOL: 90.0}) == []
    assert lane.broker.check_positions_ohlc({SYMBOL: (90.0, 90.0, 90.0, 90.0)}) == []

    after = lane.broker.accounting_snapshot({SYMBOL: 90.0})
    assert len(lane.broker.closed_trades) == closed_before == 1
    assert after["cash"] == pytest.approx(cash_before, abs=1e-12)
    assert after["realised_pnl"] == pytest.approx(close["pnl_net_usdt"], abs=1e-8)
    assert SYMBOL not in lane.broker.positions


def test_two_identical_runs_write_the_same_ledger(tmp_path):
    _, _, first = _run(tmp_path, UP, name="run-1")
    _, _, second = _run(tmp_path, UP, name="run-2")

    assert len(first) == len(second)
    for index, (left, right) in enumerate(zip(first, second, strict=True), start=1):
        assert {k: v for k, v in left.items() if k != "recorded_at_utc"} == {
            k: v for k, v in right.items() if k != "recorded_at_utc"
        }, f"fila {index} ({left.get('kind')}) diverge entre dos corridas idénticas"
