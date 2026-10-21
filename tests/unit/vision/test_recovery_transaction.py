"""RFC-PAPER-RECOVERY-004 — la transacción a nivel de unidad.

El laboratorio de crashes (``scripts/recovery_lab.py``) demuestra el comportamiento con
procesos reales, y es lento a propósito. Estos tests fijan las piezas que ese laboratorio
usa, en el proceso de pytest: que un failpoint no dispare si no está armado, que no pueda
armarse fuera de su sandbox, que una operación repetida no escriba una segunda fila, que
una cola rota se recorte dejando constancia, y que ``recover()`` distinga "no hay nada que
hacer" de "esto no se puede nombrar".

Ninguno de estos tests mata un proceso: para eso está el laboratorio, y un test que hiciera
``os._exit`` se llevaría por delante a pytest y al resto de la suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.vision import failpoints
from trading_bot.vision.durable import (
    CorruptBook,
    LaneBookStore,
    StoreRecoveryStatus,
    book_digest,
)
from trading_bot.vision.ledger import (
    GENESIS,
    DecisionLedger,
    OperationConflict,
    line_hash,
    verify_chain,
)


@pytest.fixture(autouse=True)
def _clean_failpoints() -> object:
    failpoints.reset()
    failpoints.set_trigger_hook(None)
    yield
    failpoints.set_trigger_hook(None)
    failpoints.reset()


def _body(*, closed: int = 0, book_id: str = "book-1") -> dict:
    return {
        "book_id": book_id,
        "barrier": {"bar_open_ms": 1_000, "bar_close_ms": 2_000, "bars_committed": 1},
        "broker": {"equity": 1000.0, "initial_equity": 1000.0},
        "open_positions": [],
        "closed_trades": [
            {"position_id": f"pos-{index}", "pnl": 1.0} for index in range(closed)
        ],
        "risk": {"daily_pnl": 0.0},
    }


# -- failpoints ------------------------------------------------------------------


def test_a_failpoint_is_inert_when_nothing_is_armed(tmp_path: Path) -> None:
    hits: list[str] = []
    failpoints.set_trigger_hook(lambda spec: hits.append(spec.name))

    failpoints.trigger("book.after_replace", path=tmp_path, closed_trades=0)

    assert hits == []
    assert failpoints.spec() is None
    assert failpoints.describe() == {"armed": False}


def test_a_failpoint_refuses_a_path_outside_its_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "real-book"
    outside.mkdir()
    monkeypatch.setenv(failpoints.ENV_SPEC, "book.after_replace")
    monkeypatch.setenv(failpoints.ENV_SANDBOX, str(sandbox))

    with pytest.raises(failpoints.FailpointRefused):
        failpoints.trigger("book.after_replace", path=outside, closed_trades=0)


def test_an_armed_failpoint_honours_its_skip_and_its_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hits: list[dict] = []
    failpoints.set_trigger_hook(lambda spec: hits.append(spec.to_dict()))
    monkeypatch.setenv(
        failpoints.ENV_SPEC,
        json.dumps(
            {"name": "book.after_replace", "skip": 1, "match": {"closed_trades": 1}}
        ),
    )
    monkeypatch.setenv(failpoints.ENV_SANDBOX, str(tmp_path))

    failpoints.trigger("book.after_replace", path=tmp_path, closed_trades=0)  # wrong match
    failpoints.trigger("book.after_replace", path=tmp_path, closed_trades=1)  # skipped
    assert hits == []
    failpoints.trigger("book.after_replace", path=tmp_path, closed_trades=1)  # fires
    assert hits == [{"name": "book.after_replace", "skip": 1, "match": {"closed_trades": 1}, "exit_code": 86}]


def test_an_unknown_failpoint_name_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(failpoints.ENV_SPEC, "book.after_everything")
    monkeypatch.setenv(failpoints.ENV_SANDBOX, str(tmp_path))

    with pytest.raises(failpoints.FailpointRefused):
        failpoints.spec()


# -- the ledger ------------------------------------------------------------------


def _open(path: Path) -> DecisionLedger:
    return DecisionLedger(path).open()


def test_a_repeated_operation_is_not_written_twice(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = _open(path)
    try:
        payload = {"ts_ms": 1_000, "position_id": "pos-1", "pnl_net_usdt": -3.5}
        first = ledger.append("CLOSE", payload, operation_id="book|CLOSE|pos-1")
        second = ledger.append("CLOSE", payload, operation_id="book|CLOSE|pos-1")
    finally:
        ledger.close()

    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 1
    assert second.sha256 == first.sha256
    assert ledger.duplicates_suppressed == 1
    assert verify_chain(path)["ok"] is True


def test_a_retry_that_changes_the_number_is_a_conflict_not_a_duplicate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = _open(path)
    try:
        ledger.append(
            "CLOSE", {"position_id": "pos-1", "pnl_net_usdt": -3.5}, operation_id="op-1"
        )
        with pytest.raises(OperationConflict) as caught:
            ledger.append(
                "CLOSE",
                {"position_id": "pos-1", "pnl_net_usdt": -2.5},
                operation_id="op-1",
            )
    finally:
        ledger.close()

    assert "pnl_net_usdt" in str(caught.value)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_a_torn_tail_is_dropped_and_the_drop_is_recorded(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = _open(path)
    try:
        ledger.append("RUN", {"book_id": "b"})
    finally:
        ledger.close()
    with path.open("ab") as handle:
        handle.write(b'{"seq":2,"prev_sha256":"aa","entry":{"kind":"CLO')

    reopened = _open(path)
    try:
        survived = reopened.append("RUN_END", {"closed_trades": 0})
    finally:
        reopened.close()

    assert reopened.tail_repair is not None
    assert reopened.tail_repair["reason"] == "TORN_TAIL"
    assert (tmp_path / "ledger.jsonl.torn.json").exists()
    assert survived.seq == 2
    assert verify_chain(path)["ok"] is True


def test_garbage_that_ends_with_a_newline_is_cut_at_its_byte(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = _open(path)
    try:
        ledger.append("RUN", {"book_id": "b"})
    finally:
        ledger.close()
    good = path.read_bytes()
    path.write_bytes(good + b'{"seq":2,"prev\n')

    reopened = _open(path)
    try:
        reopened.append("RUN_END", {"closed_trades": 0})
    finally:
        reopened.close()

    assert reopened.tail_repair is not None
    assert reopened.tail_repair["reason"] == "BAD_TAIL"
    #: El recorte se hace por offset de byte: uno de menos se llevaría parte de una fila
    #: buena y el recorte sería una edición.
    assert reopened.tail_repair["offset"] == len(good)
    assert verify_chain(path)["ok"] is True


def test_a_bad_line_before_the_tail_is_not_repaired(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = _open(path)
    try:
        ledger.append("RUN", {"book_id": "b"})
        ledger.append("RUN_END", {"closed_trades": 0})
    finally:
        ledger.close()
    lines = path.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    rows[0]["entry"]["book_id"] = "edited"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    reopened = _open(path)
    try:
        assert reopened.tail_repair is None
    finally:
        reopened.close()
    assert verify_chain(path)["ok"] is False
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_the_chain_still_verifies_after_a_clean_reopen(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = _open(path)
    try:
        ledger.append("RUN", {"book_id": "b"})
    finally:
        ledger.close()
    ledger = _open(path)
    try:
        ledger.append("RUN_END", {"closed_trades": 0})
    finally:
        ledger.close()

    chain = verify_chain(path)
    assert chain["ok"] is True and chain["lines"] == 2
    assert chain["head_sha256"] != GENESIS


# -- the store's recovery classification -----------------------------------------


def test_no_book_at_all_is_no_change(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path / "state")

    report = store.recover()

    assert report["status"] == StoreRecoveryStatus.NO_CHANGE
    assert report["code"] is None
    assert report["platform"]["power_loss_scope"] == "POWER_LOSS_DURABILITY_NOT_VERIFIED"


def test_a_prev_without_a_current_book_is_ambiguous_not_old(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path / "state")
    store.save(_body(closed=0))
    store.save(_body(closed=1))
    store.path.unlink()

    report = store.recover()

    assert report["status"] == StoreRecoveryStatus.REFUSED_AMBIGUOUS_COMMIT
    assert report["code"] == "CURRENT_GENERATION_MISSING"


def test_an_orphan_temporary_book_is_reported_and_never_adopted(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path / "state")
    store.save(_body(closed=1))
    digest = store.path.read_bytes()
    tmp = store.path.with_suffix(".json.tmp")
    tmp.write_bytes(b'{"body": {"forged": true}, "digest": "x"}')

    report = store.recover()

    assert report["orphan_tmp"] is True
    assert store.path.read_bytes() == digest
    assert store.load().digest == book_digest(_body(closed=1))


def test_a_commit_whose_event_never_landed_is_recoverable_and_named(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path / "state")
    store.save(_body(closed=1))  # replace landed, no COMMIT event written

    report = store.recover()

    assert report["status"] == StoreRecoveryStatus.RECOVERED
    assert report["commit_event_lag"] is True
    assert report["state_digest"]


def test_the_projection_missing_a_committed_close_is_refused(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path / "state")
    store.save(_body(closed=2))
    ledger_path = tmp_path / "ledger.jsonl"
    ledger = _open(ledger_path)
    try:
        ledger.append("CLOSE", {"position_id": "pos-0"}, operation_id="book-1|CLOSE|pos-0")
    finally:
        ledger.close()

    report = store.recover(ledger_path=ledger_path)

    assert report["status"] == StoreRecoveryStatus.REFUSED_CORRUPTION
    assert report["code"] == "PROJECTION_BEHIND_AUTHORITY"
    #: Falta el cierre de pos-1 y, además, el FILL que abrió cada posición: el libro dice
    #: que esas operaciones ocurrieron y la proyección no las tiene.
    assert "book-1|CLOSE|pos-1" in report["ledger"]["missing"]
    assert report["ledger"]["committed_closes"] == 2
    assert len(report["ledger"]["missing"]) == 3


def test_uncommitted_rows_in_the_projection_are_tolerated_and_listed(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path / "state")
    store.save(_body(closed=1))
    ledger_path = tmp_path / "ledger.jsonl"
    ledger = _open(ledger_path)
    try:
        #: La vida completa de pos-0: su FILL y su CLOSE. Sin el FILL, la proyección
        #: estaría incompleta y ese es otro veredicto (probado arriba).
        ledger.append("FILL", {"position_id": "pos-0"}, operation_id="book-1|FILL|pos-0")
        ledger.append("CLOSE", {"position_id": "pos-0"}, operation_id="book-1|CLOSE|pos-0")
        ledger.append("CLOSE", {"position_id": "pos-9"}, operation_id="book-1|CLOSE|pos-9")
    finally:
        ledger.close()

    report = store.recover(ledger_path=ledger_path)

    assert report["status"] == StoreRecoveryStatus.RECOVERED
    assert report["ledger"]["uncommitted"] == ["book-1|CLOSE|pos-9"]
    assert report["ledger"]["duplicates"] == []


def test_an_open_positions_fill_is_a_committed_operation(tmp_path: Path) -> None:
    body = _body(closed=0)
    body["open_positions"] = [{"position_id": "pos-7"}]
    store = LaneBookStore(tmp_path / "state")
    store.save(body)
    ledger_path = tmp_path / "ledger.jsonl"
    ledger = _open(ledger_path)
    try:
        ledger.append("FILL", {"position_id": "pos-7"}, operation_id="book-1|FILL|pos-7")
    finally:
        ledger.close()

    report = store.recover(ledger_path=ledger_path)

    assert report["status"] != StoreRecoveryStatus.REFUSED_CORRUPTION, report["detail"]
    assert report["ledger"]["uncommitted"] == []
    assert report["ledger"]["missing"] == []


def test_a_live_lock_blocks_a_recovery_report(tmp_path: Path) -> None:
    import os

    store = LaneBookStore(tmp_path / "state")
    store.save(_body())
    store.lock_path.write_text(
        json.dumps({"pid": os.getpid(), "host": "test", "session_id": "live", "token": "t"}),
        encoding="utf-8",
    )

    report = store.recover()

    assert report["status"] == StoreRecoveryStatus.BLOCKED_LOCK


def test_a_corrupt_book_is_quarantined_and_refused(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path / "state")
    store.save(_body())
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["body"]["broker"]["equity"] = 999.0
    store.path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(CorruptBook):
        store.load()
    report = store.recover()

    assert report["status"] == StoreRecoveryStatus.REFUSED_CORRUPTION
    assert list((tmp_path / "state").glob("BOOK.corrupt.*.json"))


def test_two_saves_keep_the_previous_generation_complete(tmp_path: Path) -> None:
    store = LaneBookStore(tmp_path / "state")
    store.save(_body(closed=0))
    store.save(_body(closed=1))

    assert store.prev_path.exists()
    previous = json.loads(store.prev_path.read_text(encoding="utf-8"))
    assert previous["digest"] == book_digest(previous["body"])
    assert previous["body"]["closed_trades"] == []


def test_line_hash_is_domain_separated_by_sequence_and_previous(tmp_path: Path) -> None:
    """Si la identidad de una fila no incluyera la posición, dos cierres colisionarían."""
    same = {"kind": "CLOSE", "position_id": "pos-1"}
    assert line_hash(1, GENESIS, same) != line_hash(2, GENESIS, same)
    assert line_hash(1, GENESIS, same) != line_hash(1, "a" * 64, same)
