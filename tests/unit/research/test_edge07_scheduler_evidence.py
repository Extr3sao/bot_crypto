"""WP-EDGE-07 Track A — the cadence's derived re-read must leave a receipt a reader can find.

WP-EDGE-06 wired the scheduled tick to re-read the lane's reconciliation, but the receipt only
travelled inside the tick record the script *prints*: ``ForwardObserver.tick`` persists the run
record before the re-read happens, and the operating system's scheduler throws stdout away. So on
the live lane nothing durable said whether the reconciliation had actually run from the cadence —
the field a report could read was absent for every tick, refused or observed.

The fix is one appended line per scheduled tick in the observer's own state. These tests are
about that line:

* a scheduled tick that consumed its slot writes a receipt saying it re-read, with a status;
* a tick that changed nothing writes one saying it did not, and why;
* a manual tick writes none — the cadence is the trigger, and a person running the command by
  hand is not the cadence;
* a receipt that cannot be written leaves the tick's own verdict and exit code untouched: the
  tick's verdict is about the lane, the receipt is about the reading.

Everything is driven against ``tmp_path`` and a fake observer, so a run of this file writes
nothing into ``data/forward``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def observer_module() -> Any:
    path = REPO_ROOT / "scripts" / "edge04_observer.py"
    spec = importlib.util.spec_from_file_location("edge04_observer_receipts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeObserver:
    """An observer whose tick returns a declared record and whose state is a temp directory."""

    def __init__(self, record: dict[str, Any], state_root: Path) -> None:
        self._record = dict(record)
        self.state_root = state_root
        self.ticked = 0

    def tick(self, **_kwargs: Any) -> dict[str, Any]:
        self.ticked += 1
        return dict(self._record)


def _record(outcome: str, exit_code: int) -> dict[str, Any]:
    return {
        "run_id": "FWD-EDGE04-20261014T090000Z",
        "slot_key": "2026-10-14T09:00Z",
        "mode": "SCHEDULED",
        "outcome": outcome,
        "outcome_reason": "the tick's own reason",
        "duration_seconds": 1.25,
        "new_bars": 3,
        "market_requests": 6,
        "health_status": "OK",
        "alerts": [],
        "exit_code": exit_code,
        "disk_after": {"status": "HEALTHY", "free_gib": 3.7},
        "publication": {"ran": False, "reason": "not due"},
    }


def _drive(
    observer_module: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    *,
    record: dict[str, Any],
    state_root: Path,
    argv: list[str],
) -> tuple[int, dict[str, Any]]:
    fake = _FakeObserver(record, state_root)
    monkeypatch.setattr(observer_module, "ForwardObserver", lambda **_kw: fake)
    code = observer_module.main(argv)
    printed = capsys.readouterr().out
    return code, json.loads(printed)


def _receipts(state_root: Path) -> list[dict[str, Any]]:
    path = state_root / "derived_refresh.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_a_tick_that_observed_persists_a_receipt_that_it_re_read(
    observer_module: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, tmp_path: Path
) -> None:
    calls: list[str] = []

    def fake_refresh(**kwargs: Any) -> dict[str, Any]:
        calls.append(str(kwargs.get("outcome")))
        return {
            "ran": True,
            "reason": None,
            "seconds": 0.2,
            "after_outcome": "OBSERVED",
            "status": "HISTORICAL_ONLY",
            "unattributed_bars": 0,
            "artifacts": {"reconciliation": "x"},
        }

    monkeypatch.setattr(observer_module, "_refresh_derived", fake_refresh)
    code, payload = _drive(
        observer_module,
        monkeypatch,
        capsys,
        record=_record("OBSERVED", 0),
        state_root=tmp_path,
        argv=["--scheduled", "--due", "--json"],
    )

    assert calls == ["OBSERVED"]
    assert code == 0
    assert payload["derived_refresh"]["ran"] is True
    assert payload["derived_refresh"]["persisted"] is True

    lines = _receipts(tmp_path)
    assert len(lines) == 1
    assert lines[0]["ran"] is True
    assert lines[0]["run_id"] == payload["run_id"]
    assert lines[0]["slot_key"] == payload["slot_key"]
    assert lines[0]["status"] == "HISTORICAL_ONLY"
    assert lines[0]["schema_version"] == "EDGE04_DERIVED_REFRESH_V1"
    assert lines[0]["order_sent"] is False


def test_a_refused_tick_persists_why_it_did_not_re_read(
    observer_module: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, tmp_path: Path
) -> None:
    called: list[int] = []
    monkeypatch.setattr(
        observer_module,
        "_refresh_derived",
        lambda **_kw: called.append(1) or {"ran": True, "seconds": 0.0},
    )
    code, payload = _drive(
        observer_module,
        monkeypatch,
        capsys,
        record=_record("DISK_BUDGET_EXCEEDED", 5),
        state_root=tmp_path,
        argv=["--scheduled", "--due", "--json"],
    )

    assert called == []  # a tick that changed nothing does not re-read
    assert code == 5
    assert payload["derived_refresh"]["ran"] is False
    lines = _receipts(tmp_path)
    assert len(lines) == 1
    assert lines[0]["ran"] is False
    assert "DISK_BUDGET_EXCEEDED" in lines[0]["reason"]
    assert lines[0]["outcome"] == "DISK_BUDGET_EXCEEDED"


def test_a_manual_tick_writes_no_receipt(
    observer_module: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        observer_module, "_refresh_derived", lambda **_kw: {"ran": True, "seconds": 0.0}
    )
    code, payload = _drive(
        observer_module,
        monkeypatch,
        capsys,
        record=_record("OBSERVED", 0),
        state_root=tmp_path,
        argv=["--json"],
    )
    assert code == 0
    assert "derived_refresh" not in payload
    assert _receipts(tmp_path) == []


def test_a_receipt_that_cannot_be_written_leaves_the_verdict_untouched(
    observer_module: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, tmp_path: Path
) -> None:
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("a file where the state root should be", encoding="utf-8")
    monkeypatch.setattr(
        observer_module,
        "_refresh_derived",
        lambda **_kw: {"ran": True, "seconds": 0.1, "after_outcome": "OBSERVED"},
    )
    code, payload = _drive(
        observer_module,
        monkeypatch,
        capsys,
        record=_record("OBSERVED", 0),
        state_root=blocked,
        argv=["--scheduled", "--due", "--json"],
    )

    assert code == 0, "the tick observed; a failed receipt must not change that"
    receipt = payload["derived_refresh"]
    assert receipt["ran"] is True
    assert receipt["persisted"] is False
    assert receipt["persist_error"]
    assert not (blocked / "derived_refresh.jsonl").exists()
