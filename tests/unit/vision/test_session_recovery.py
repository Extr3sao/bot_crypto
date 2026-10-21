"""WP-PAPER-RESUME-001 — una sesión PAPER que muere con exposición no la pierde.

El defecto que estos tests cierran está medido en `roundtrip-5m`: el proceso terminó con dos
cortos abiertos, `RUN_END` los publicó, y nada los restauró. Un reinicio empezaba plano, así
que esas dos posiciones sólo podía cerrarlas el proceso que ya no existía.

Lo que se exige aquí, sobre el `PaperBroker` y el `RiskManager` de producción:

1. una posición abierta en el momento de la caída vuelve con su identidad, su precio, su
   comisión de entrada y su stop;
2. el proceso que reanuda **no vuelve a procesar** las velas que el libro ya cubre: no
   reabre lo que ya está abierto ni recobra una opinión ya pagada;
3. el stop que estaba armado antes de la caída sigue armado después, y cierra en el mismo
   precio que habría cerrado sin interrupción;
4. un cierre ya contabilizado no se contabiliza dos veces;
5. la corrida partida en dos produce el **mismo estado económico** que la corrida continua,
   comparado por digest y no campo a campo;
6. un libro de otro experimento, o con velas que cambiaron debajo, se rechaza en vez de
   continuarse.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision import failpoints
from trading_bot.vision.durable import (
    CorruptBook,
    LaneBookStore,
    RecoveryBlocked,
    SessionBusy,
)
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import read_entries
from trading_bot.vision.provider import ReplayProvider, VisionResponse
from trading_bot.vision.quotes import MINUTE_MS, MinuteBarQuoteFeed, MinuteSeries
from trading_bot.vision.settings import load_vision_config

HOUR_MS = 3_600_000
START_MS = int(datetime(2026, 10, 20, tzinfo=UTC).timestamp() * 1000)
REPO = Path(__file__).resolve().parents[3]
SYMBOL = "BTC/USDT"
BOOK = "resume-test-book"
STOP_PCT = 0.5
TAKE_PCT = 0.75


def _answer(symbol: str, action: str) -> str:
    stop = STOP_PCT if action not in {"NO_TRADE", "CLOSE"} else None
    take = TAKE_PCT if action not in {"NO_TRADE", "CLOSE"} else None
    return (
        f'{{"schema_version":"ai-vision-decision/1","symbol":"{symbol}","action":"{action}",'
        f'"confidence":0.6,"horizon_bars":6,"stop_loss_pct":{stop},"take_profit_pct":{take},'
        '"invalidation":null,"rationale":"Recuperación de sesión PAPER."}'
    )


class ScriptedProvider(ReplayProvider):
    """Una respuesta por llamada, repitiendo la última cuando la lista se agota.

    Repetir la última es deliberado: un `ProviderError` por guion agotado convertiría un
    fallo de recuperación en un fallo del test, y el test dejaría de decir qué se rompió.
    """

    def __init__(self, actions: list[str], *, latency_ms: int = 0) -> None:
        self._actions = list(actions) or ["NO_TRADE"]
        self._latency_ms = int(latency_ms)
        self.seen = 0
        super().__init__(self._script)

    def _script(self, request) -> str:  # type: ignore[no-untyped-def]
        index = min(self.seen, len(self._actions) - 1)
        return _answer(request.chart.symbol, self._actions[index])

    def analyze(self, request) -> VisionResponse:  # type: ignore[override]
        response = super().analyze(request)
        self.seen += 1
        return replace(response, latency_ms=self._latency_ms)


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
#: La posición se abre en la vela 20 y sigue abierta al final de la vela 21.
OPEN_AT_END = [*FLAT, (100.0, 100.3)]
#: La vela 22 perfora el stop por abajo (99,5) y lo cierra dentro del rango.
EXTEND_STOP = [*OPEN_AT_END, (100.3, 99.0), (99.0, 99.0)]
#: La vela 22 toca el take profit (100,75).
EXTEND_TP = [*OPEN_AT_END, (100.3, 101.0)]
#: Sin relleno: sirve para reanudar y comprobar que no se abre nada nuevo.
EXTEND_FLAT = [*OPEN_AT_END, (100.3, 100.3)]


def _config(*, equity: float = 10_000.0):
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


def _policy():
    return load_settings(config_dir=REPO / "config", env_file=None).risk


def _lane(
    series: list[Bar],
    provider: ScriptedProvider,
    ledger: Path,
    *,
    store: LaneBookStore | None = None,
    book=None,  # type: ignore[no-untyped-def]
    session_id: str = "s1",
    equity: float = 10_000.0,
    quote_feed=None,  # type: ignore[no-untyped-def]
) -> VisionLane:
    return VisionLane(
        series={SYMBOL: list(series)},
        provider=provider,
        config=_config(equity=equity),
        risk_policy=_policy(),
        ledger_path=ledger,
        equity=10_000.0,
        book_id=BOOK,
        decision_every_bars=1,
        book_store=store,
        book=book,
        session_id=session_id,
        quote_feed=quote_feed,
    )


def _first_run(tmp_path: Path, series: list[Bar], *, name: str = "run-1"):
    """Una sesión que muere con lo que tenga abierto al final del dataset."""
    store = LaneBookStore(tmp_path / "state")
    lock = store.lock(session_id=name)
    try:
        lane = _lane(
            series,
            ScriptedProvider(["LONG", "NO_TRADE"]),
            tmp_path / f"{name}.jsonl",
            store=store,
            session_id=name,
        )
        summary = lane.run()
    finally:
        lock.release()
    book = store.load()
    assert book is not None
    return store, summary, book, [row["entry"] for row in read_entries(tmp_path / f"{name}.jsonl")]


def _resume(
    tmp_path: Path,
    series: list[Bar],
    store: LaneBookStore,
    *,
    name: str = "run-2",
    quote_feed=None,  # type: ignore[no-untyped-def]
):
    book = store.load()
    assert book is not None
    lock = store.lock(session_id=name)
    try:
        lane = _lane(
            series,
            ScriptedProvider(["NO_TRADE"]),
            tmp_path / f"{name}.jsonl",
            store=store,
            book=book,
            session_id=name,
            quote_feed=quote_feed,
        )
        summary = lane.run()
    finally:
        lock.release()
    return lane, summary, [row["entry"] for row in read_entries(tmp_path / f"{name}.jsonl")]


def _closes(entries: list[dict]) -> list[dict]:  # type: ignore[type-arg]
    return [entry for entry in entries if entry.get("kind") == "CLOSE"]


# -- 1. la posición vuelve con su identidad --------------------------------------


def test_a_position_open_at_the_crash_resumes_with_its_identity(tmp_path: Path) -> None:
    store, first, book, _ = _first_run(tmp_path, _bars(OPEN_AT_END))

    assert first["fills"] == 1
    assert list(first["open_positions_at_end"]) == [SYMBOL]
    assert len(book.open_positions) == 1
    position = book.open_positions[0]

    lane, summary, entries = _resume(tmp_path, _bars(EXTEND_FLAT), store)

    restored = lane.broker.positions[SYMBOL]
    assert restored.position_id == position["position_id"]
    assert restored.entry_price == pytest.approx(position["entry_price"], abs=1e-9)
    assert restored.quantity == pytest.approx(position["quantity"], abs=1e-12)
    assert restored.entry_commission == pytest.approx(position["entry_commission"], abs=1e-12)
    assert restored.stop_loss_price == pytest.approx(
        position["entry_price"] * (1 - STOP_PCT / 100.0), abs=1e-9
    )
    assert lane.recovery is not None and lane.recovery.recovered
    assert summary["session"]["resumed"] is True
    assert summary["session"]["session_index"] == 2
    #: Un segundo proceso sobre el mismo libro sí cierra la vela nueva, pero no reabre nada.
    assert summary["session"]["fills"] == 0
    assert _closes(entries) == []


def test_the_resumed_session_reports_the_account_not_only_its_own_trades(tmp_path: Path) -> None:
    store, first, _, _ = _first_run(tmp_path, _bars(OPEN_AT_END))
    lane, summary, _ = _resume(tmp_path, _bars(EXTEND_STOP), store)

    assert summary["closed_trades"] == 1  # el libro entero
    assert summary["session"]["closed_trades"] == 1  # lo que hizo este proceso
    assert len(lane.broker.closed_trades) == 1
    assert summary["final_equity_usdt"] == pytest.approx(
        10_000.0 + lane.broker.closed_trades[0].pnl, abs=1e-6
    )
    assert first["final_equity_usdt"] == pytest.approx(10_000.0, abs=1e-6)


def test_a_restart_with_no_new_bars_changes_nothing(tmp_path: Path) -> None:
    store, _first, book, _ = _first_run(tmp_path, _bars(OPEN_AT_END))
    lane, summary, entries = _resume(tmp_path, _bars(OPEN_AT_END), store)

    assert summary["session"]["fills"] == 0
    assert summary["session"]["closed_trades"] == 0
    assert summary["session"]["book_digest"] == book.state_digest
    assert lane.broker.positions[SYMBOL].position_id == book.open_positions[0]["position_id"]
    assert [entry for entry in entries if entry.get("kind") in {"FILL", "CLOSE"}] == []


# -- 2. el stop armado sigue armado ---------------------------------------------


def test_the_stop_armed_before_the_crash_closes_the_trade_after_it(tmp_path: Path) -> None:
    store, _, book, _ = _first_run(tmp_path, _bars(OPEN_AT_END))
    position_id = book.open_positions[0]["position_id"]

    lane, summary, entries = _resume(tmp_path, _bars(EXTEND_STOP), store)
    closes = _closes(entries)

    assert len(closes) == 1
    close = closes[0]
    assert close["position_id"] == position_id
    assert close["exit_reason"] == "stop_loss"
    assert close["exit_price"] == pytest.approx(99.5, abs=1e-9)
    assert close["exit_ts_resolution"] == "BAR_WINDOW"
    assert close["phase"] == "INTRABAR"
    assert close["pnl_net_usdt"] < 0
    assert lane.broker.positions == {}
    assert summary["open_positions_at_end"] == {}


def test_a_close_that_already_happened_is_not_booked_twice(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path / "state")
    lock = store.lock(session_id="run-1")
    try:
        lane = _lane(
            _bars(EXTEND_TP),
            ScriptedProvider(["LONG", "NO_TRADE"]),
            tmp_path / "run-1.jsonl",
            store=store,
            session_id="run-1",
        )
        first = lane.run()
    finally:
        lock.release()
    assert first["closed_trades"] == 1
    closed_before = store.load().closed_trades  # type: ignore[union-attr]

    _, summary, entries = _resume(tmp_path, _bars([*EXTEND_TP, (101.0, 101.0)]), store)

    assert summary["closed_trades"] == 1
    assert summary["session"]["closed_trades"] == 0
    assert _closes(entries) == []
    assert store.load().closed_trades == closed_before  # type: ignore[union-attr]


# -- 3. la corrida partida y la continua coinciden -------------------------------


def _continuous(tmp_path: Path, series: list[Bar]):
    store = LaneBookStore(tmp_path / "state")
    lock = store.lock(session_id="continuous")
    try:
        lane = _lane(
            series,
            ScriptedProvider(["LONG", "NO_TRADE"]),
            tmp_path / "continuous.jsonl",
            store=store,
            session_id="continuous",
        )
        summary = lane.run()
    finally:
        lock.release()
    return summary, store.load(), [row["entry"] for row in read_entries(tmp_path / "continuous.jsonl")]


def test_an_interrupted_run_and_a_continuous_run_reach_the_same_economy(tmp_path: Path) -> None:
    continuous_dir = tmp_path / "a"
    continuous_dir.mkdir()
    summary_a, book_a, entries_a = _continuous(continuous_dir, _bars(EXTEND_STOP))

    store, _, book_b1, _ = _first_run(tmp_path, _bars(OPEN_AT_END))
    _, summary_b, entries_b = _resume(tmp_path, _bars(EXTEND_STOP), store)
    book_b2 = store.load()

    assert book_a is not None and book_b2 is not None
    assert book_a.state_digest == book_b2.state_digest, (
        "la corrida partida en dos tiene que dejar el mismo libro que la corrida continua"
    )
    assert book_b1.state_digest != book_a.state_digest  # la interrupción ocurrió de verdad
    assert summary_a["closed_trades"] == summary_b["closed_trades"] == 1

    close_a = _closes(entries_a)[0]
    close_b = _closes(entries_b)[0]
    for field in (
        "symbol",
        "side",
        "entry_price",
        "exit_price",
        "quantity",
        "pnl_net_usdt",
        "gross_pnl_usdt",
        "entry_commission_usdt",
        "exit_commission_usdt",
        "execution_cost_usdt",
        "position_id",
        "trade_id",
        "exit_reason",
    ):
        assert close_a[field] == close_b[field], f"{field} diverge entre A y B"


# -- 4. lo que estaba en vuelo sobrevive ----------------------------------------


def test_an_opinion_waiting_for_its_quote_survives_the_restart(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path / "state")
    lock = store.lock(session_id="run-1")
    try:
        lane = _lane(
            _bars(OPEN_AT_END),
            ScriptedProvider(["NO_TRADE", "NO_TRADE", "LONG"]),
            tmp_path / "run-1.jsonl",
            store=store,
            session_id="run-1",
        )
        first = lane.run()
    finally:
        lock.release()

    book = store.load()
    assert book is not None
    assert list(book.body["pending"]) == [SYMBOL], "la opinión en vuelo pertenece al libro"
    assert first["fills"] == 0

    _, summary, entries = _resume(tmp_path, _bars(EXTEND_FLAT), store)

    fills = [entry for entry in entries if entry.get("kind") == "FILL"]
    assert len(fills) == 1, "la opinión pagada se cobra en el primer hueco que la puede pagar"
    assert summary["session"]["fills"] == 1
    assert store.load().body["pending"] == {}  # type: ignore[union-attr]


# -- 5. un libro que no se puede creer no se continúa ---------------------------


def test_a_book_from_another_experiment_is_refused_at_the_lane(tmp_path: Path) -> None:
    store, _, book, _ = _first_run(tmp_path, _bars(OPEN_AT_END))

    with pytest.raises(RecoveryBlocked) as blocked:
        VisionLane(
            series={SYMBOL: _bars(EXTEND_FLAT)},
            provider=ScriptedProvider(["NO_TRADE"]),
            config=_config(),
            risk_policy=_policy(),
            ledger_path=tmp_path / "other.jsonl",
            equity=5_000.0,
            book_id=BOOK,
            decision_every_bars=1,
            book_store=store,
            book=book,
            session_id="run-2",
        )

    assert blocked.value.report.code == "CONTRACT_MISMATCH"
    assert "equity" in blocked.value.report.detail


def test_bars_that_changed_under_the_book_are_refused(tmp_path: Path) -> None:
    store, _, book, _ = _first_run(tmp_path, _bars(OPEN_AT_END))
    changed = _bars(OPEN_AT_END)
    changed[3] = replace(changed[3], close=changed[3].close + 0.5)

    with pytest.raises(RecoveryBlocked) as blocked:
        VisionLane(
            series={SYMBOL: changed},
            provider=ScriptedProvider(["NO_TRADE"]),
            config=_config(),
            risk_policy=_policy(),
            ledger_path=tmp_path / "changed.jsonl",
            equity=10_000.0,
            book_id=BOOK,
            decision_every_bars=1,
            book_store=store,
            book=book,
            session_id="run-2",
        )

    assert blocked.value.report.code == "DATASET_MISMATCH"


def test_a_corrupt_book_is_never_read_as_an_empty_one(tmp_path: Path) -> None:
    store, _, _, _ = _first_run(tmp_path, _bars(OPEN_AT_END))
    raw = store.path.read_bytes()
    store.path.write_bytes(raw[: len(raw) // 3])

    with pytest.raises(CorruptBook):
        store.load()
    assert store.prev_path.exists(), "la generación anterior queda disponible para el forense"


def test_a_book_held_by_a_live_session_cannot_be_taken_over(tmp_path: Path) -> None:
    """El cerrojo es del *libro*, no de la instancia: quien no lo tiene no arranca."""

    store, _, book, _ = _first_run(tmp_path, _bars(OPEN_AT_END))
    holder = store.lock(session_id="run-2")
    try:
        with pytest.raises(SessionBusy):
            store.lock(session_id="run-3")
        #: El libro sigue intacto: nadie escribió sobre él mientras estaba tomado.
        assert store.load().state_digest == book.state_digest
    finally:
        holder.release()
    store.lock(session_id="run-3").release()


# -- 6. el libro se escribe en cada vela ----------------------------------------


def test_every_processed_bar_is_committed_and_named(tmp_path: Path) -> None:
    store, summary, book, _ = _first_run(tmp_path, _bars(OPEN_AT_END))
    commits = [row for row in store.events() if row["kind"] == "COMMIT"]

    bar_commits = [row for row in commits if not row["session_end"]]
    assert len(bar_commits) == len(OPEN_AT_END) == 22
    assert len(commits) == 23  # 22 velas + el cierre de sesión
    assert commits[-1]["barrier_open_ms"] == START_MS + 21 * HOUR_MS
    assert commits[-1]["session_end"] is True
    assert commits[-1]["digest"] == book.digest
    assert summary["session"]["book_digest"] == book.state_digest
    assert book.body["barrier"]["bars_committed"] == 22


# -- 7. el cerrojo del ledger también sobrevive a una muerte --------------------


def test_a_ledger_lock_left_by_a_killed_process_is_taken_over(tmp_path: Path) -> None:
    """Una muerte a la fuerza no ejecuta `finally`: el cerrojo queda en disco.

    Sin relevo, el libro durable protegería una cadena que ya nadie puede abrir, y el
    reinicio fallaría no por el libro sino por un fichero de cero bytes.
    """

    from trading_bot.vision.ledger import DecisionLedger

    path = tmp_path / "ledger.jsonl"
    lock = tmp_path / "ledger.jsonl.lock"
    lock.write_text("999999999", encoding="utf-8")

    ledger = DecisionLedger(path).open()
    try:
        ledger.append("RUN", {"book_id": "x"})
    finally:
        ledger.close()
    assert not lock.exists()
    assert len(read_entries(path)) == 1


def test_a_ledger_lock_held_by_a_live_process_is_still_refused(tmp_path: Path) -> None:
    import os

    from trading_bot.vision.ledger import DecisionLedger, LedgerLockedError

    path = tmp_path / "ledger.jsonl"
    (tmp_path / "ledger.jsonl.lock").write_text(str(os.getpid()), encoding="utf-8")

    with pytest.raises(LedgerLockedError):
        DecisionLedger(path).open()


# -- 8. un hueco de 5 minutos cruzado con evidencia de 1 minuto ------------------
#
# El defecto que estos tests cierran es el `UNVERIFIED_GAP`: el libro sabe que le falta
# una vela y no tiene forma de saber si dentro del hueco el stop se llevó la posición. La
# salida correcta no es adivinar ni empezar plano, sino mirar los minutos.


def _hole_series(*, low: float | None = None, high: float | None = None):
    """La vela 22 no existe; sus 60 minutos sí."""

    start = START_MS + 22 * HOUR_MS
    rows = []
    for index in range(60):
        stamp = start + index * MINUTE_MS
        minute_low = 99.6 if low is None or index != 15 else low
        minute_high = 100.4 if high is None or index != 15 else high
        rows.append([stamp, 100.0, minute_high, minute_low, 100.0, 1.0])
    return MinuteBarQuoteFeed({SYMBOL: MinuteSeries.from_rows(SYMBOL, rows)})


def _holed_bars(path: list[tuple[float, float]]) -> list[Bar]:
    return [bar for index, bar in enumerate(_bars(path)) if index != 22]


def test_a_covered_hole_resumes_without_touching_the_book(tmp_path: Path) -> None:
    store, _, book, _ = _first_run(tmp_path, _bars(OPEN_AT_END))

    #: La vela de reanudación no perfora el stop: si lo hiciera, el cierre sería suyo y el
    #: test dejaría de hablar del hueco.
    lane, summary, entries = _resume(
        tmp_path,
        _holed_bars([*EXTEND_FLAT, (100.3, 100.3)]),
        store,
        quote_feed=_hole_series(),
    )

    assert lane.recovery is not None and lane.recovery.recovered
    assert lane.recovery.resume_from_ms == START_MS + 23 * HOUR_MS
    assert lane.recovery.reconstruction is None
    assert [check["check"] for check in lane.recovery.checks][-3:] == [
        "barrier_is_continuous",
        "gap_evidence_matches_book",
        "gap_covered_by_quotes",
    ]
    gap = lane.recovery.gap
    assert gap is not None and gap["verdict"] == "CLEAR"
    assert gap["evidence"]["symbols"][SYMBOL]["minutes_observed"] == 60

    #: Nada se cerró ni se abrió: el hueco no contenía ninguna barrera.
    assert _closes(entries) == []
    assert summary["session"]["fills"] == 0
    assert lane.broker.positions[SYMBOL].position_id == book.open_positions[0]["position_id"]


def test_a_stop_crossed_inside_the_hole_is_booked_at_its_minute(tmp_path: Path) -> None:
    store, _, _, _ = _first_run(tmp_path, _bars(OPEN_AT_END))

    lane, summary, entries = _resume(
        tmp_path, _holed_bars(EXTEND_STOP), store, quote_feed=_hole_series(low=99.0)
    )
    closes = _closes(entries)

    assert len(closes) == 1
    close = closes[0]
    assert close["phase"] == "GAP_RECONSTRUCTION"
    assert close["exit_ts_resolution"] == "MINUTE_WINDOW"
    assert close["exit_reason"] == "stop_loss"
    assert close["exit_price"] == pytest.approx(99.5, abs=1e-9)
    assert close["exit_ts_lower_bound_ms"] == START_MS + 22 * HOUR_MS + 15 * MINUTE_MS
    assert close["exit_ts_upper_bound_ms"] == close["exit_ts_lower_bound_ms"] + MINUTE_MS
    assert lane.broker.positions == {}
    assert summary["open_positions_at_end"] == {}

    #: El precio es el que la corrida continua habría pagado por la misma vela: la
    #: reconstrucción aporta el minuto, no un modelo de ejecución distinto.
    continuous_dir = tmp_path / "continuous"
    continuous_dir.mkdir()
    _, book_continuous, entries_continuous = _continuous(
        continuous_dir, _bars(EXTEND_STOP)
    )
    continuous_close = _closes(entries_continuous)[0]
    assert continuous_close["exit_price"] == close["exit_price"]
    assert continuous_close["pnl_net_usdt"] == close["pnl_net_usdt"]
    assert continuous_close["exit_ts_resolution"] == "BAR_WINDOW"
    #: El instante del continuo cae dentro de la ventana que la reconstrucción nombra.
    assert close["exit_ts_lower_bound_ms"] <= START_MS + 23 * HOUR_MS
    assert book_continuous is not None
    #: El libro guarda 8 decimales; el redondeo es de la fila, no del número económico.
    assert book_continuous.body["closed_trades"][0]["pnl"] == pytest.approx(
        close["pnl_net_usdt"], abs=1e-7
    )


def test_a_hole_without_a_feed_is_still_unverified(tmp_path: Path) -> None:
    store, _, _, _ = _first_run(tmp_path, _bars(OPEN_AT_END))

    with pytest.raises(RecoveryBlocked) as blocked:
        _resume(tmp_path, _holed_bars(EXTEND_STOP), store)

    assert blocked.value.report.code == "UNVERIFIED_GAP"
    assert blocked.value.report.resume_from_ms is None


def test_an_ambiguous_minute_blocks_and_leaves_the_position_open(tmp_path: Path) -> None:
    store, _, book, _ = _first_run(tmp_path, _bars(OPEN_AT_END))

    with pytest.raises(RecoveryBlocked) as blocked:
        _resume(
            tmp_path,
            _holed_bars(EXTEND_STOP),
            store,
            quote_feed=_hole_series(low=99.0, high=101.5),
        )

    assert blocked.value.report.code == "GAP_EXIT_AMBIGUOUS"
    assert blocked.value.report.resume_from_ms is None
    gap = blocked.value.report.gap
    assert gap is not None and gap["verdict"] == "BLOCKED"
    assert gap["positions"][0]["status"] == "AMBIGUOUS"
    #: El libro en disco no se tocó: sigue teniendo la posición.
    assert store.load().state_digest == book.state_digest
    assert len(store.load().open_positions) == 1


def test_a_partial_minute_grid_blocks_instead_of_resuming_on_a_guess(tmp_path: Path) -> None:
    store, _, _, _ = _first_run(tmp_path, _bars(OPEN_AT_END))
    rows = [
        [START_MS + 22 * HOUR_MS + index * MINUTE_MS, 100.0, 100.4, 99.6, 100.0, 1.0]
        for index in range(60)
        if index != 33
    ]
    feed = MinuteBarQuoteFeed({SYMBOL: MinuteSeries.from_rows(SYMBOL, rows)})

    with pytest.raises(RecoveryBlocked) as blocked:
        _resume(tmp_path, _holed_bars(EXTEND_STOP), store, quote_feed=feed)

    assert blocked.value.report.code == "GAP_NOT_COVERED"
    assert "59/60" in blocked.value.report.detail
# -- 8. la rama posterior al COMMIT ----------------------------------------------


def test_a_resume_after_the_gap_close_was_committed_books_nothing_twice(tmp_path: Path) -> None:
    """El lado posterior al ``COMMIT``: el cierre ya está en disco y reanudar no lo repite.

    Los 14 kills originales caían todos antes del commit, así que la otra mitad de la
    frontera no tenía regresión. Dos reanudaciones seguidas sobre el libro que ya cerró
    tienen que dejar el mismo digest, un solo cierre y ninguna posición abierta: si la
    segunda encontrara el libro a medias, volvería a cerrar o bloquearía para siempre.
    """
    store, _, book_first, _ = _first_run(tmp_path, _bars(OPEN_AT_END))
    assert len(book_first.open_positions) == 1

    _, _, entries_second = _resume(
        tmp_path, _holed_bars(EXTEND_STOP), store, quote_feed=_hole_series(low=99.0)
    )
    assert len(_closes(entries_second)) == 1
    book_second = store.load()
    assert book_second is not None
    assert len(book_second.closed_trades) == 1
    assert book_second.open_positions == []
    committed_digest = book_second.state_digest

    for attempt in ("run-3", "run-4"):
        _, summary, entries = _resume(
            tmp_path,
            _holed_bars(EXTEND_STOP),
            store,
            name=attempt,
            quote_feed=_hole_series(low=99.0),
        )
        assert _closes(entries) == [], attempt
        current = store.load()
        assert current is not None
        assert current.state_digest == committed_digest, attempt
        assert len(current.closed_trades) == 1, attempt
        assert current.open_positions == [], attempt
        #: La reanudación corrió de verdad; no es un libro que se negó a abrirse.
        assert isinstance(summary, dict), attempt


# -- 9. el commit intermedio de la reconstrucción -------------------------------
#
# El plan de hueco cierra la posición y llama a ``_commit()`` *antes* de procesar la
# primera vela posterior. Ese commit es durable y el proceso puede morir justo después, así
# que el libro que deja tiene que poder reanudarse. Medido en RFC004: publicaba
# ``risk_equity=9997.26097534`` frente a ``marked_equity=9996.3809662`` —la parte no
# realizada del cierre contada dos veces— y ``reconcile_book`` lo rechazaba con
# ``RISK_MISMATCH`` para siempre: fail-closed, pero cuenta bloqueada.


class _StopAtCommit(RuntimeError):
    """Detiene el proceso de test en un failpoint sin matarlo (el laboratorio usa os._exit)."""


def test_the_commit_that_books_a_reconstruction_can_be_resumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(failpoints.ENV_SPEC, "bar.after_commit")
    monkeypatch.setenv(failpoints.ENV_SANDBOX, str(tmp_path))
    #: El hook se instala *antes* de la primera sesión: sin él, un failpoint armado hace
    #: ``os._exit`` y se llevaría por delante a pytest. La bandera decide cuándo el disparo
    #: detiene la prueba, para que el commit de la sesión inicial no la corte.
    state: dict[str, object] = {"armed": False, "hits": []}

    def hook(spec) -> None:  # type: ignore[no-untyped-def]
        hits = state["hits"]
        assert isinstance(hits, list)
        hits.append(spec.name)
        if state["armed"]:
            raise _StopAtCommit(spec.name)

    failpoints.set_trigger_hook(hook)
    try:
        store, _, book_first, _ = _first_run(tmp_path, _bars(OPEN_AT_END))
        state["armed"] = True
        lane = _lane(
            _holed_bars(EXTEND_STOP),
            ScriptedProvider(["NO_TRADE"]),
            tmp_path / "run-2.jsonl",
            store=store,
            book=book_first,
            session_id="run-2",
            quote_feed=_hole_series(low=99.0),
        )
        with pytest.raises(_StopAtCommit):
            lane.run()
    finally:
        #: Desarmar las dos mitades: sin el hook, un failpoint armado hace ``os._exit``; sin
        #: desarmar el entorno, la reanudación que viene detrás mataría a pytest.
        failpoints.set_trigger_hook(None)
        monkeypatch.delenv(failpoints.ENV_SPEC, raising=False)
        monkeypatch.delenv(failpoints.ENV_SANDBOX, raising=False)
        failpoints.reset()

    #: El commit que corta es el primero de la reanudación: el del plan de hueco, con la
    #: posición ya cerrada y la barrera todavía en la vela 21.
    assert state["hits"][-1] == "bar.after_commit"
    committed = store.load()
    assert committed is not None
    assert len(committed.closed_trades) == 1
    assert committed.open_positions == []
    assert committed.body["risk_equity"] == pytest.approx(
        committed.body["marked_equity"], abs=1e-6
    ), (
        "the reconstruction commit must publish risk and mark as one number; "
        f"risk={committed.body['risk_equity']} marked={committed.body['marked_equity']}"
    )
    recovered = store.recover()
    assert recovered["status"] in {"NO_CHANGE", "RECOVERED"}, recovered["detail"]

    _, _, entries = _resume(
        tmp_path,
        _holed_bars(EXTEND_STOP),
        store,
        name="run-3",
        quote_feed=_hole_series(low=99.0),
    )
    after = store.load()
    assert after is not None
    assert _closes(entries) == [], "the committed close must not be booked a second time"
    assert len(after.closed_trades) == 1
    assert after.body["broker"]["equity"] == pytest.approx(
        committed.body["broker"]["equity"], abs=1e-9
    )
