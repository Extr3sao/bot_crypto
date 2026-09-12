"""EXT-CONF-002 — ledger-backed conf_lock and reducer tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.research.h6.confirmation_state import confirmation_state


def _valid_event(confirm_id: str, et: str, aid: str, ts: str, status: str = "ok") -> dict:
    return {
        "confirmation_id": confirm_id,
        "event_type": et,
        "attempt_id": aid,
        "timestamp": ts,
        "commit": "abc123",
        "dataset": "16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99",
        "spec": "221cfa1d6eb3dae30948e9605f258075c0cd69e8f38187da4959c3e696b8b000",
        "status": status,
    }


def test_confirm_lock_status_from_ledger(tmp_path: Path) -> None:
    from trading_bot.research.h6.conf_lock import CONFIRMATION_ID
    from trading_bot.research.h6.confirmation_state import confirmation_state

    # Simulate ledger with LOCK_CHECK
    ledger = tmp_path / "ledger.jsonl"
    ev = _valid_event(CONFIRMATION_ID, "LOCK_CHECK", "LOCK_CHECK-2026-09-12T00:00:00Z", "2026-09-12T00:00:00Z", "LOCKED_UNTIL_2026-09-22T00:00:00Z_CONSUMED_FALSE_EXECUTIONS_0")
    ledger.write_text(json.dumps(ev) + "\n")
    s = confirmation_state(CONFIRMATION_ID, ledger)
    assert s.state_valid
    assert s.consumed is False
    assert s.execution_count == 0
    assert s.locked_until is not None


def test_ledger_backed_conf_lock_before_maturity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import trading_bot.research.h6.conf_lock as cl

    # Point ledger to tmp file
    ledger = tmp_path / "CONFIRMATION_LEDGER_V2.jsonl"
    ev = _valid_event(cl.CONFIRMATION_ID, "LOCK_CHECK", "LOCK_CHECK-2026-09-12T00:00:00Z", "2026-09-12T00:00:00Z", "LOCKED_UNTIL_2026-09-22T00:00:00Z_CONSUMED_FALSE_EXECUTIONS_0")
    ledger.write_text(json.dumps(ev) + "\n")
    monkeypatch.setattr(cl, "CONFIRMATION_LEDGER_PATH", ledger)
    # also ensure legacy path doesn't interfere
    status = cl.confirm_lock_status()
    assert status["source"] == "confirmation_ledger_v2"
    # Should not raise because now < 2026-09-22
    cl.assert_confirmation_locked()


def test_exactly_once_duplicate_started_fails(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ev1 = _valid_event("CONF-EDGE-002-001", "STARTED", "attempt-1", "2026-09-12T00:00:00Z")
    ev2 = _valid_event("CONF-EDGE-002-001", "STARTED", "attempt-1", "2026-09-12T01:00:00Z")
    ledger.write_text(json.dumps(ev1) + "\n" + json.dumps(ev2) + "\n")
    s = confirmation_state("CONF-EDGE-002-001", ledger)
    assert s.state_valid is False
    assert "duplicate attempt_id" in s.error  # type: ignore[operator]


def test_started_after_consumed_fails(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ev1 = _valid_event("CONF-EDGE-002-001", "CONSUMED", "c1", "2026-09-12T00:00:00Z")
    ev2 = _valid_event("CONF-EDGE-002-001", "STARTED", "s1", "2026-09-12T01:00:00Z")
    ledger.write_text(json.dumps(ev1) + "\n" + json.dumps(ev2) + "\n")
    s = confirmation_state("CONF-EDGE-002-001", ledger)
    assert s.state_valid is False
    assert "STARTED after CONSUMED" in s.error  # type: ignore[operator]


def test_pre_ledger_history_not_proven() -> None:
    # The report asserts historical proof is limitation; no ledger existed before 2026-09-12
    # The ledger's earliest event is LOCK_CHECK 2026-09-12, proving no earlier events prove history
    from pathlib import Path as P
    ledger = P("docs/external-audit-01/oi-full-history-02/CONFIRMATION_LEDGER_V2.jsonl")
    events = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    assert events[0]["event_type"] == "LOCK_CHECK"
    # pre-ledger history is by definition not in ledger; status file must say NOT_INDEPENDENTLY_PROVEN
    import json as _json
    report = _json.loads(P("docs/external-audit-01/oi-full-history-02/CONFIRMATION_AUTHORITY_REPORT_V2.json").read_text())
    assert report["pre_ledger_history"]["status"] == "NOT_INDEPENDENTLY_PROVEN"
