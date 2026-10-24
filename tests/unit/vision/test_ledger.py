"""A ledger that can be quietly edited is not evidence."""

from __future__ import annotations

import json

import pytest

from trading_bot.vision.ledger import (
    DecisionLedger,
    LedgerLockedError,
    read_entries,
    summarize,
    verify_chain,
)


def test_lines_chain_and_verify(tmp_path):
    path = tmp_path / "decisions.jsonl"
    with DecisionLedger(path) as ledger:
        ledger.append("RUN", {"book_id": "demo"})
        ledger.append("DECISION", {"decision": {"action": "LONG"}, "coherence_reason": "MODEL_LONG"})
        ledger.append("CLOSE", {"pnl_net_usdt": -12.5})

    report = verify_chain(path)

    assert report["ok"] is True
    assert report["lines"] == 3
    assert report["kinds"] == {"RUN": 1, "DECISION": 1, "CLOSE": 1}


def test_editing_a_past_line_is_detected(tmp_path):
    path = tmp_path / "decisions.jsonl"
    with DecisionLedger(path) as ledger:
        ledger.append("DECISION", {"decision": {"action": "LONG"}, "coherence_reason": "MODEL_LONG"})
        ledger.append("CLOSE", {"pnl_net_usdt": -100.0})

    lines = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[1])
    row["entry"]["pnl_net_usdt"] = 50.0
    lines[1] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = verify_chain(path)

    assert report["ok"] is False
    assert report["reason"].startswith("TAMPERED_LINE")


def test_removing_a_line_breaks_the_chain(tmp_path):
    path = tmp_path / "decisions.jsonl"
    with DecisionLedger(path) as ledger:
        ledger.append("RUN", {"book_id": "demo"})
        ledger.append("DECISION", {"decision": {"action": "LONG"}})
        ledger.append("CLOSE", {"pnl_net_usdt": -1.0})

    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")

    report = verify_chain(path)

    assert report["ok"] is False
    assert report["reason"].startswith(("SEQ_GAP", "BROKEN_LINK"))


def test_a_second_writer_is_refused_and_the_lock_is_released(tmp_path):
    path = tmp_path / "decisions.jsonl"
    first = DecisionLedger(path).open()
    try:
        with pytest.raises(LedgerLockedError):
            DecisionLedger(path).open()
    finally:
        first.close()

    with DecisionLedger(path) as second:
        second.append("RUN", {"book_id": "demo"})

    assert not (tmp_path / "decisions.jsonl.lock").exists()
    assert verify_chain(path)["ok"] is True


def test_an_unopened_ledger_refuses_to_write(tmp_path):
    with pytest.raises(LedgerLockedError):
        DecisionLedger(tmp_path / "x.jsonl").append("RUN", {})


def test_appending_to_an_existing_chain_continues_from_its_head(tmp_path):
    path = tmp_path / "decisions.jsonl"
    with DecisionLedger(path) as ledger:
        ledger.append("RUN", {"book_id": "demo"})

    with DecisionLedger(path) as ledger:
        ledger.append("DECISION", {"decision": {"action": "SHORT"}})

    report = verify_chain(path)
    assert report["ok"] is True
    assert report["lines"] == 2


def test_summary_counts_actions_rejections_and_net(tmp_path):
    path = tmp_path / "decisions.jsonl"
    with DecisionLedger(path) as ledger:
        ledger.append("DECISION", {"decision": {"action": "LONG"}, "coherence_reason": "MODEL_LONG"})
        ledger.append(
            "DECISION",
            {
                "decision": {"action": "CLOSE"},
                "coherence_reason": "NO_POSITION_TO_CLOSE",
                "risk_blocked_by": None,
            },
        )
        ledger.append(
            "DECISION",
            {
                "decision": None,
                "parse_error": "SCHEMA_VIOLATION",
                "coherence_reason": None,
            },
        )
        ledger.append("PROVIDER_FAILURE", {"code": "AUTH_ERROR"})
        ledger.append("CLOSE", {"pnl_net_usdt": -10.0})
        ledger.append("CLOSE", {"pnl_net_usdt": 4.0})

    summary = summarize(path)

    assert summary["actions"] == {"LONG": 1, "CLOSE": 1, "PARSE_FAILED": 1}
    assert summary["rejections"]["NO_POSITION_TO_CLOSE"] == 1
    assert summary["rejections"]["SCHEMA_VIOLATION"] == 1
    assert summary["provider_failures"] == {"AUTH_ERROR": 1}
    assert summary["closed_trades"] == 2
    assert summary["net_realised_usdt"] == pytest.approx(-6.0)


def test_entries_are_readable_in_order(tmp_path):
    path = tmp_path / "decisions.jsonl"
    with DecisionLedger(path) as ledger:
        for index in range(3):
            ledger.append("DECISION", {"decision": {"action": "NO_TRADE"}, "index": index})

    entries = read_entries(path)

    assert [row["entry"]["index"] for row in entries] == [0, 1, 2]
    assert [row["seq"] for row in entries] == [1, 2, 3]
