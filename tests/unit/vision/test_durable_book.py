"""WP-PAPER-RESUME-001 — el libro durable: atómico, bloqueado, con digest y fail-closed.

Estos tests no usan `VisionLane`: fijan el contrato de almacenamiento y de reconciliación
por separado, porque un fallo ahí no es un fallo de trading, es un fallo de *creencia* sobre
el estado del libro. Lo que se exige:

1. lo escrito se lee idéntico, y una segunda escritura deja la anterior recuperable;
2. un fichero truncado, editado o con otro esquema **no se lee**: se conserva y se rechaza;
3. un solo escritor por libro, y el relevo de un dueño que ya no existe;
4. la reconciliación sólo tiene tres respuestas —`FRESH`, `RECOVERED`, `BLOCKED`— y
   cualquiera de sus invariantes rota bloquea la sesión entera;
5. el digest identifica el *estado*, no el proceso que lo escribió.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from trading_bot.paper.broker import PaperPosition
from trading_bot.vision.durable import (
    BOOK_SCHEMA,
    BOOK_SCHEMA_VERSION,
    CorruptBook,
    LaneBookStore,
    RecoveryStatus,
    SessionBusy,
    closed_digest,
    contract_from,
    reconcile_book,
    state_digest,
)

BAR_MS = 300_000
T0 = 1_792_000_000_000
SYMBOL = "BTC/USDT"


# -- fixtures helpers -----------------------------------------------------------


def _position(**over: object) -> dict:
    base = PaperPosition(
        symbol=SYMBOL,
        side="buy",
        entry_price=100.0,
        quantity=2.0,
        notional_usdt=200.0,
        stop_loss_pct=0.5,
        take_profit_pct=1.0,
        opened_at=T0 / 1000.0,
        entry_commission=0.05,
        reference_entry_price=100.0,
        commission_bps=2.5,
        price_bps_per_side=1.0,
        position_id="pos-book-00000001",
        entry_order_id="order-book-00000001",
    )
    row = base.to_row()
    row.update(over)
    return row


def _closed_row(**over: object) -> dict:
    row = {
        "symbol": SYMBOL,
        "side": "buy",
        "entry_price": 100.0,
        "exit_price": 101.0,
        "quantity": 2.0,
        "pnl": 1.9,
        "exit_reason": "take_profit",
        "opened_at": T0 / 1000.0,
        "closed_at": (T0 + BAR_MS) / 1000.0,
        "strategy_name": "script",
        "trade_id": "trade-book-00000003",
        "position_id": "pos-book-00000001",
        "entry_order_id": "order-book-00000001",
        "exit_order_id": "order-book-00000002",
        "gross_pnl": 2.0,
        "entry_commission": 0.05,
        "exit_commission": 0.05,
        "reference_entry_price": 100.0,
        "reference_exit_price": 101.0,
        "reference_gross_pnl": 2.0,
        "execution_cost_usdt": 0.0,
        "total_cost_usdt": 0.1,
    }
    row.update(over)
    return row


def _dataset(sha: str = "sha-a") -> dict:
    return {
        SYMBOL: {
            "bars": 3,
            "first_open_ms": T0,
            "last_open_ms": T0 + BAR_MS,
            "sha256": sha,
        }
    }


def _contract(**over: object) -> dict:
    dataset = over.pop("dataset", _dataset())
    contract = contract_from(
        book_id="book-test",
        timeframe="5m",
        interval_ms=BAR_MS,
        equity=10_000.0,
        cost_multiplier=1.0,
        window_bars=60,
        decision_every_bars=1,
        risk_policy=A_RISK_POLICY,
        provider="script",
        dataset=dataset,  # type: ignore[arg-type]
    )
    contract.update(over)
    return contract


A_RISK_POLICY = {
    "max_risk_per_trade_pct": 1.0,
    "max_daily_loss_pct": 3.0,
    "max_weekly_loss_pct": 6.0,
    "max_total_drawdown_pct": 10.0,
    "max_open_positions": 3,
    "default_stop_loss_pct": 0.5,
    "default_take_profit_pct": 1.0,
}


def _body(
    *,
    positions: list[dict] | None = None,
    closed: list[dict] | None = None,
    equity: float = 10_000.0,
    marked: float = 10_000.0,
    risk_equity: float | None = None,
    **over: object,
) -> dict:
    closed_rows = list(closed if closed is not None else [])
    body = {
        "book_id": "book-test",
        "session_id": "s1",
        "session_index": 1,
        "session_ids": ["s1"],
        "contract": _contract(),
        "barrier": {"bar_open_ms": T0 + BAR_MS, "bar_close_ms": T0 + 2 * BAR_MS, "bars_committed": 2},
        "broker": {
            "equity": equity,
            "initial_equity": 10_000.0,
            "fills_opened": 1,
            "fills_closed": len(closed_rows),
        },
        "open_positions": list(positions if positions is not None else []),
        "closed_trades": closed_rows,
        "closed_digest": closed_digest(closed_rows),
        "risk": {
            "equity": marked if risk_equity is None else risk_equity,
            "peak_equity": 10_000.0,
        },
        "marked_equity": marked,
        "risk_equity": marked if risk_equity is None else risk_equity,
        "pending": {},
        "entry_provenance": {},
        "marks": {SYMBOL: 100.0},
        "counters": {},
        "calls": 1,
        "spend_usd": 0.0,
        "stop_reason": None,
        "deferrals": {},
    }
    body.update(over)
    return body


def _timeline(bars: int = 4) -> list[int]:
    return [T0 + index * BAR_MS for index in range(bars)]


# -- 1. el almacén --------------------------------------------------------------


def test_a_saved_book_reads_back_with_the_same_digest(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path)
    body = _body(positions=[_position()])

    saved = store.save(body)
    loaded = store.load()

    assert loaded is not None
    assert loaded.digest == saved.digest
    assert loaded.body == body
    assert loaded.barrier_ms == T0 + BAR_MS
    assert store.events() == []


def test_the_previous_generation_survives_a_second_write(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path)
    first = store.save(_body())
    store.save(_body(positions=[_position()]))

    assert store.prev_path.exists()
    previous = json.loads(store.prev_path.read_text(encoding="utf-8"))
    assert previous["digest"] == first.digest


def test_a_truncated_book_is_refused_and_preserved(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path)
    store.save(_body())
    raw = store.path.read_bytes()
    store.path.write_bytes(raw[: len(raw) // 2])

    with pytest.raises(CorruptBook):
        store.load()
    quarantined = list(tmp_path.glob("BOOK.corrupt.*.json"))
    assert quarantined, "los bytes ilegibles deben conservarse para el post-mortem"
    assert len(quarantined[0].read_bytes()) == len(raw) // 2


def test_an_edited_body_is_refused_even_though_it_parses(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path)
    store.save(_body())
    doc = json.loads(store.path.read_text(encoding="utf-8"))
    doc["body"]["broker"]["equity"] = 11_000.0
    store.path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(CorruptBook, match="digest"):
        store.load()


def test_a_book_from_another_schema_is_not_guessed(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path)
    store.save(_body())
    doc = json.loads(store.path.read_text(encoding="utf-8"))
    doc["schema"] = "vision-lane-book/0"
    doc["schema_version"] = 0
    store.path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(CorruptBook, match="refuses to guess"):
        store.load()


def test_the_digest_names_the_state_not_the_session(tmp_path: Path) -> None:
    first = _body()
    second = _body(session_id="s9", session_index=4, session_ids=["s1", "s9"])

    assert state_digest(first) == state_digest(second)
    assert state_digest(_body(marked=10_000.5)) != state_digest(first)
    #: La integridad sí distingue el linaje: son dos preguntas distintas.
    from trading_bot.vision.durable import book_digest

    assert book_digest(first) != book_digest(second)


# -- 2. el cerrojo --------------------------------------------------------------


def test_a_second_writer_is_refused_while_the_first_holds_the_book(tmp_path: Path) -> None:
    first = LaneBookStore(tmp_path).lock(session_id="s1")
    try:
        with pytest.raises(SessionBusy):
            LaneBookStore(tmp_path).lock(session_id="s2")
    finally:
        first.release()
    LaneBookStore(tmp_path).lock(session_id="s3").release()


def test_a_descriptor_is_not_probed_with_a_signal_that_could_kill_the_holder(tmp_path: Path) -> None:
    """Windows mata el proceso ante cualquier señal distinta de CTRL_C/CTRL_BREAK.

    Sondeando con ``os.kill(pid, 0)`` el cerrojo podría matar justo al proceso que
    protege; el cerrojo tiene que saberlo y negarse a hacerlo.
    """

    from trading_bot.vision import durable

    source = Path(durable.__file__).read_text(encoding="utf-8")
    assert "PROCESS_QUERY_LIMITED_INFORMATION" in source
    assert durable.pid_alive(os.getpid()) is True
    assert durable.pid_alive(999_999_999) is False


def test_a_lock_whose_owner_is_gone_is_taken_over(tmp_path: Path) -> None:
    path = tmp_path / "BOOK.lock"
    path.write_text(
        json.dumps({"pid": 999_999_999, "token": "dead", "session_id": "ghost"}),
        encoding="utf-8",
    )
    lock = LaneBookStore(tmp_path).lock(session_id="s2")
    try:
        assert lock.acquired
        holder = json.loads(path.read_text(encoding="utf-8"))
        assert holder["session_id"] == "s2"
    finally:
        lock.release()
    assert not path.exists()


# -- 3. la reconciliación -------------------------------------------------------


def test_no_book_is_a_fresh_book_not_a_recovery(tmp_path: Path) -> None:
    report = reconcile_book(
        None, contract=_contract(), prefix=_dataset(), timeline=_timeline(), interval_ms=BAR_MS
    )
    assert report.status == RecoveryStatus.FRESH
    assert report.ok and not report.recovered


def test_an_intact_book_resumes_at_the_bar_after_its_barrier() -> None:
    body = _body(positions=[_position()])
    recovered = _recover(body)

    assert recovered.status == RecoveryStatus.RECOVERED, recovered.detail
    assert recovered.resume_from_ms == T0 + 2 * BAR_MS
    assert [check["check"] for check in recovered.checks] == [
        "contract_matches",
        "barrier_present",
        "dataset_prefix_matches",
        "equity_identity",
        "closed_history_intact",
        "position_structure",
        "risk_agrees_with_mark",
        "resume_bar_available",
        "barrier_is_continuous",
    ]


def _failed_detail(report: object) -> str:
    """El detalle del check que bloqueó: es donde vive el número, no en el resumen."""
    failed = report.failed()  # type: ignore[attr-defined]
    return failed[0]["detail"] if failed else ""


def _recover(body: dict, **over: object):  # type: ignore[no-untyped-def]
    from trading_bot.vision.durable import LaneBook

    kwargs = {
        "contract": _contract(),
        "prefix": _dataset(),
        "timeline": _timeline(),
        "interval_ms": BAR_MS,
    }
    kwargs.update(over)
    return reconcile_book(
        LaneBook(body=body, digest=state_digest(body), updated_at_ms=0), **kwargs
    )


def test_a_book_from_another_experiment_is_blocked() -> None:
    report = _recover(_body(), contract=_contract(equity=5_000.0))
    assert report.status == RecoveryStatus.BLOCKED
    assert report.code == "CONTRACT_MISMATCH"
    assert "equity" in report.detail


def test_a_dataset_that_changed_under_the_book_is_blocked() -> None:
    report = _recover(_body(), prefix=_dataset(sha="sha-b"))
    assert report.code == "DATASET_MISMATCH"
    assert "sha-a" in _failed_detail(report) and "sha-b" in _failed_detail(report)


def test_an_equity_that_does_not_finance_itself_is_blocked() -> None:
    #: Un cierre de +1.9 sobre 10 000 no puede dejar el libro en 12 000: entre los dos
    #: números falta una operación, y restaurar el saldo publicaría una ganancia inventada.
    body = _body(closed=[_closed_row()], equity=12_000.0, marked=12_000.0)
    report = _recover(body)
    assert report.code == "EQUITY_IDENTITY"
    assert "sum(closed pnl) 1.9" in _failed_detail(report)
    assert "12000.0" in _failed_detail(report)


def test_an_edited_history_is_blocked() -> None:
    body = _body(closed=[_closed_row()], equity=10_001.9, marked=10_001.9)
    body["closed_trades"][0]["pnl"] = 2.9
    body["broker"]["equity"] = 10_002.9
    body["marked_equity"] = 10_002.9
    body["risk"]["equity"] = 10_002.9
    report = _recover(body)
    assert report.code == "CLOSED_HISTORY"


def test_a_position_that_is_both_open_and_closed_is_blocked() -> None:
    body = _body(positions=[_position()], closed=[_closed_row()], equity=10_001.9, marked=10_001.9)
    report = _recover(body)
    assert report.code == "POSITION_INVALID"
    assert "pos-book-00000001" in report.detail


def test_a_position_outside_the_universe_is_blocked() -> None:
    body = _body(positions=[_position(symbol="DOGE/USDT")])
    report = _recover(body)
    assert report.code == "POSITION_INVALID"
    assert "DOGE/USDT" in report.detail


def test_a_risk_engine_that_disagrees_with_the_mark_is_blocked() -> None:
    #: El motor de riesgo y el libro tienen que arrancar con la misma equity: si no, el
    #: siguiente sizing se decide contra un saldo que no existe.
    body = _body(marked=9_999.0, risk_equity=10_000.0)
    report = _recover(body)
    assert report.code == "RISK_MISMATCH"


def test_a_hole_between_the_barrier_and_the_next_bar_is_blocked() -> None:
    timeline = [T0, T0 + BAR_MS, T0 + 3 * BAR_MS, T0 + 4 * BAR_MS]
    report = _recover(_body(), timeline=timeline)
    assert report.code == "UNVERIFIED_GAP"
    assert "could have been crossed" in report.detail


def test_a_restart_between_two_bars_waits_at_the_next_one() -> None:
    """Reiniciar entre dos velas no es un libro roto: es un libro que aún no debe nada."""

    report = _recover(_body(), timeline=[T0, T0 + BAR_MS])
    assert report.status == RecoveryStatus.RECOVERED
    assert report.resume_from_ms == T0 + 2 * BAR_MS
    assert "awaiting" in report.detail


# -- 4. el hueco, con y sin evidencia de 1 minuto ---------------------------------


def _minute_feed(*, low: float = 99.6, high: float = 100.4, minutes: int = 5):
    from trading_bot.vision.quotes import MinuteBarQuoteFeed, MinuteSeries

    start = T0 + 2 * BAR_MS
    rows = [
        [start + index * 60_000, 100.0, high, low, 100.0, 1.0] for index in range(minutes)
    ]
    return MinuteBarQuoteFeed({SYMBOL: MinuteSeries.from_rows(SYMBOL, rows)})


def _gap(*, positions: list[dict] | None = None, feed=None, resume: int | None = None):  # type: ignore[no-untyped-def]
    from trading_bot.vision.gap_recovery import GapWindow, assess_gap

    window = GapWindow(
        barrier_ms=T0 + BAR_MS,
        resume_ms=int(resume if resume is not None else T0 + 3 * BAR_MS),
        interval_ms=BAR_MS,
    )
    return assess_gap(
        window=window,
        positions=[_position()] if positions is None else positions,
        feed=_minute_feed() if feed is None else feed,
    )


_HOLE = [T0, T0 + BAR_MS, T0 + 3 * BAR_MS, T0 + 4 * BAR_MS]


def test_a_hole_the_minutes_cleared_resumes_with_the_book_untouched() -> None:
    report = _recover(_body(positions=[_position()]), timeline=_HOLE, gap=_gap())

    assert report.status == RecoveryStatus.RECOVERED, report.detail
    assert report.resume_from_ms == T0 + 3 * BAR_MS
    assert report.reconstruction is None
    assert report.gap is not None and report.gap["verdict"] == "CLEAR"
    clearing = [check for check in report.checks if check["check"] == "gap_covered_by_quotes"]
    assert clearing and clearing[0]["ok"] is True
    assert SYMBOL in clearing[0]["detail"] and "5 minutes" in clearing[0]["detail"]


def test_a_stop_the_minutes_proved_is_published_as_a_plan_not_as_a_claim() -> None:
    feed = _minute_feed(low=99.0)
    report = _recover(_body(positions=[_position()]), timeline=_HOLE, gap=_gap(feed=feed))

    assert report.status == RecoveryStatus.RECOVERED, report.detail
    plan = report.reconstruction
    assert plan is not None and plan["kind"] == "PROTECTIVE_EXITS"
    assert len(plan["exits"]) == 1
    exit_row = plan["exits"][0]
    assert exit_row["position_id"] == "pos-book-00000001"
    assert exit_row["price"] == pytest.approx(99.5)
    assert exit_row["reason"] == "stop_loss"
    assert exit_row["minute_ms"] == T0 + 2 * BAR_MS
    assert plan["minutes"], "el plan tiene que llevar los OHLC con los que se decide"
    assert all(minute["symbol"] == SYMBOL for minute in plan["minutes"])


def test_an_ambiguous_minute_blocks_the_resume_with_its_own_code() -> None:
    feed = _minute_feed(low=99.0, high=101.5)
    report = _recover(_body(positions=[_position()]), timeline=_HOLE, gap=_gap(feed=feed))

    assert report.status == RecoveryStatus.BLOCKED
    assert report.code == "GAP_EXIT_AMBIGUOUS"
    assert report.resume_from_ms is None
    assert report.gap is not None and report.gap["verdict"] == "BLOCKED"
    assert any(check["check"].startswith("gap.") for check in report.checks)


def test_evidence_about_another_barrier_is_not_applied_to_this_book() -> None:
    stale = _gap(resume=T0 + 4 * BAR_MS)
    report = _recover(_body(positions=[_position()]), timeline=_HOLE, gap=stale)

    assert report.code == "GAP_EVIDENCE_STALE"
    assert "GAP_EVIDENCE_STALE" in (report.code or "")


def test_evidence_about_other_positions_is_not_applied_to_this_book() -> None:
    other = _gap(positions=[_position(position_id="pos-other")])
    report = _recover(_body(positions=[_position()]), timeline=_HOLE, gap=other)

    assert report.code == "GAP_EVIDENCE_STALE"
    assert "pos-other" in report.detail or "pos-other" in str(report.gap)


def test_a_hole_without_evidence_keeps_the_old_refusal() -> None:
    report = _recover(_body(positions=[_position()]), timeline=_HOLE)

    assert report.code == "UNVERIFIED_GAP"
    assert report.gap is None and report.reconstruction is None


# -- 5. las ventanas de la escritura y del relevo --------------------------------


def test_a_crash_before_the_rename_leaves_the_previous_book_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rotar y luego reemplazar deja un instante sin ``BOOK.json``.

    Un proceso que muere justo ahí dejaba sólo ``BOOK.json.prev``; el siguiente leía "no
    hay libro" y arrancaba plano **con la exposición abierta**. La escritura tiene que
    conservar un libro completo en todo momento, y lo hace copiando antes de reemplazar.
    """

    store = LaneBookStore(tmp_path)
    first = store.save(_body())

    real_replace = os.replace

    def explode(source: object, destination: object) -> None:
        if Path(destination) == store.path and Path(source).suffix == ".tmp":
            raise OSError("simulated crash before the rename")
        real_replace(source, destination)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError, match="simulated crash"):
        store.save(_body(positions=[_position()]))
    monkeypatch.undo()

    assert store.path.exists(), "el libro anterior no puede desaparecer durante la escritura"
    loaded = store.load()
    assert loaded is not None
    assert loaded.digest == first.digest


def test_a_book_that_lost_its_current_generation_is_not_read_as_a_fresh_one(
    tmp_path: Path,
) -> None:
    store = LaneBookStore(tmp_path)
    store.save(_body())
    store.save(_body(positions=[_position()]))
    store.path.unlink()

    with pytest.raises(CorruptBook, match="interrupted between generations"):
        store.load()


def test_a_second_taker_is_refused_while_one_takeover_is_in_flight(tmp_path: Path) -> None:
    """Dos relevos simultáneos sobre el mismo dueño muerto no pueden ganar los dos."""

    lock_path = tmp_path / "BOOK.lock"
    lock_path.write_text(
        json.dumps({"pid": 999_999_999, "token": "dead", "session_id": "ghost"}),
        encoding="utf-8",
    )
    (tmp_path / "BOOK.lock.takeover").write_text("taken\n", encoding="utf-8")

    with pytest.raises(SessionBusy, match="taking over"):
        LaneBookStore(tmp_path).lock(session_id="s2")


def test_an_abandoned_takeover_guard_does_not_brick_the_book(tmp_path: Path) -> None:
    import time

    lock_path = tmp_path / "BOOK.lock"
    lock_path.write_text(
        json.dumps({"pid": 999_999_999, "token": "dead", "session_id": "ghost"}),
        encoding="utf-8",
    )
    guard = tmp_path / "BOOK.lock.takeover"
    guard.write_text("taken\n", encoding="utf-8")
    old = time.time() - 120
    os.utime(guard, (old, old))

    lock = LaneBookStore(tmp_path).lock(session_id="s2")
    try:
        assert lock.acquired
        assert json.loads(lock_path.read_text(encoding="utf-8"))["session_id"] == "s2"
        assert not guard.exists()
    finally:
        lock.release()


def test_the_schema_constants_are_the_ones_the_runtime_writes() -> None:
    assert BOOK_SCHEMA == "vision-lane-book/1"
    assert BOOK_SCHEMA_VERSION == 1


def test_a_passing_check_never_carries_the_text_of_a_failure() -> None:
    """Un `detail` con `ok: true` se lee como un defecto que no existe.

    El libro real publicaba `equity_identity: ok=true, detail="initial 10000.0 + sum(closed
    pnl) 8.285 != equity 10008.285"`: la frase describía la identidad cumpliéndose como si
    se hubiera roto. Quien lee `RECOVERY.checks` en un incidente no tiene forma de saber a
    cuál de las dos señales creer, así que el detalle tiene que acompañar al veredicto.
    """
    recovered = _recover(_body(positions=[_position()]))
    assert recovered.status == RecoveryStatus.RECOVERED
    passing = [check for check in recovered.checks if check["ok"]]
    assert passing
    for check in passing:
        assert "!=" not in check["detail"], f"{check['check']}: {check['detail']}"

    # ...y el detalle del fallo sigue ahí cuando el check falla de verdad.
    broken = _recover(_body(positions=[_position()], equity=12_345.0))
    failed = [check for check in broken.checks if not check["ok"]]
    assert failed and "!=" in failed[0]["detail"]
