"""CODEX — the session status must describe a session without changing it.

Three properties are tested, one per group:

* the state is decided from the artefacts (ABSENT / READY / RUNNING / RECOVERING /
  RECOVERED / FAILED), including the case that matters operationally: a lock left behind by
  a proved-dead owner is ``RECOVERING``, not ``RUNNING`` and not a silent ``READY``;
* asking twice is idempotent and asking at all is **read-only** — every file's bytes, size and
  mtime are identical before and after, and no lock is created, reaped or rewritten. A
  diagnostic that reaps while another writer runs would be worse than no diagnostic;
* a refusal or abort that predates the newest stream write is history, and does not paint a
  recovered session as failed forever.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from trading_bot.ops.session_status import session_status
from trading_bot.ops.single_writer import SingleWriter, reclaim_abandoned
from trading_bot.vision.ledger import GENESIS, line_hash


def _write_chain(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prev = GENESIS
    lines = []
    for index, entry in enumerate(entries, start=1):
        digest = line_hash(index, prev, entry)
        lines.append(
            json.dumps(
                {"seq": index, "prev_sha256": prev, "entry": entry, "sha256": digest},
                sort_keys=True,
            )
        )
        prev = digest
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _start(*, resumed: bool, session_id: str = "sess-1") -> dict:
    return {
        "kind": "SESSION_START",
        "recorded_at_utc": "2026-10-23T00:00:00Z",
        "started_at_utc": "2026-10-23T00:00:00Z",
        "live_orders": 0,
        "runtime_sha256": {"src/a.py": "a"},
        "provenance": {
            "run_id": "run-1",
            "session_id": session_id,
            "pinned_identity": "pin-1",
            "runtime_digest": "digest-1",
            "resumed": resumed,
        },
    }


def _dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def _abandoned_record(pid: int, *, token: str = "dead-owner") -> dict:
    return {
        "schema_version": "TAP_SINGLE_WRITER_LOCK_V1",
        "purpose": "test",
        "host": socket.gethostname(),
        "pid": pid,
        "process_start_ms": None,
        "token": token,
        "fence": 1,
    }


def _session(tmp_path: Path, *, resumed_last: bool, result_exit: int = 0) -> Path:
    root = tmp_path / "session"
    root.mkdir()
    _write_chain(
        root / "STREAM.jsonl",
        [
            _start(resumed=False),
            {"kind": "CYCLE", "recorded_at_utc": "2026-10-23T00:01:00Z", "cycle": 1, "live_orders": 0},
            _start(resumed=resumed_last, session_id="sess-2"),
            {"kind": "CYCLE", "recorded_at_utc": "2026-10-23T00:02:00Z", "cycle": 2, "live_orders": 0},
            {"kind": "SESSION_END", "recorded_at_utc": "2026-10-23T00:03:00Z", "live_orders": 0},
        ],
    )
    (root / "RUN_RESULT.json").write_text(json.dumps({"exit_code": result_exit}), encoding="utf-8")
    return root


def test_absent_when_nothing_has_run(tmp_path: Path) -> None:
    root = tmp_path / "session"
    root.mkdir()
    status = session_status(root)
    assert status["state"] == "ABSENT"
    assert status["ledger"]["rows"] == 0
    assert status["locks"]["all"] == []
    assert status["read_only"] is True


def test_ready_after_a_fresh_clean_session(tmp_path: Path) -> None:
    status = session_status(_session(tmp_path, resumed_last=False))
    assert status["state"] == "READY"
    assert status["ledger"]["chain_ok"] is True
    assert status["ledger"]["last_cycle"] == 2
    assert status["recoveries"]["count"] == 0


def test_recovered_when_the_newest_start_resumed(tmp_path: Path) -> None:
    status = session_status(_session(tmp_path, resumed_last=True))
    assert status["state"] == "RECOVERED"
    assert status["session"]["resumed_starts"] == 1


def test_running_when_a_live_owner_holds_the_stream(tmp_path: Path) -> None:
    root = _session(tmp_path, resumed_last=False)
    lock = SingleWriter(root / "STREAM.jsonl.lock", purpose="test-holder")
    lock.acquire()
    try:
        status = session_status(root)
    finally:
        lock.release()
    assert status["state"] == "RUNNING"
    assert status["owner"]["live"] is True
    assert status["owner"]["pid"] == os.getpid()


def test_recovering_when_the_owner_is_proved_gone(tmp_path: Path) -> None:
    root = _session(tmp_path, resumed_last=False)
    pid = _dead_pid()
    (root / "STREAM.jsonl.lock").write_text(json.dumps(_abandoned_record(pid)), encoding="utf-8")
    status = session_status(root)
    assert status["state"] == "RECOVERING"
    assert status["locks"]["abandoned_paths"] == ["STREAM.jsonl.lock"]
    assert status["locks"]["awaiting_recovery"][0]["reason"] == "OWNER_PROCESS_DEAD"
    # Reading the state must never be what performs the recovery.
    assert (root / "STREAM.jsonl.lock").is_file()
    reclaimed = reclaim_abandoned(root / "STREAM.jsonl.lock")
    assert reclaimed is not None and reclaimed["reason"] == "OWNER_PROCESS_DEAD"
    assert session_status(root)["state"] == "READY"


def test_unattributed_lock_is_recovering_but_not_permission_to_recover(tmp_path: Path) -> None:
    root = _session(tmp_path, resumed_last=False)
    (root / "STREAM.jsonl.lock").write_text("", encoding="utf-8")
    status = session_status(root)
    assert status["state"] == "RECOVERING"
    assert status["locks"]["awaiting_recovery"][0]["state"] == "UNATTRIBUTED"
    assert status["locks"]["awaiting_recovery"][0]["reason"] == "EMPTY"


def test_failed_when_the_chain_no_longer_verifies(tmp_path: Path) -> None:
    root = _session(tmp_path, resumed_last=False)
    rows = (root / "STREAM.jsonl").read_text(encoding="utf-8").splitlines()
    payload = json.loads(rows[1])
    payload["entry"]["cycle"] = 99
    rows[1] = json.dumps(payload, sort_keys=True)
    (root / "STREAM.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    status = session_status(root)
    assert status["state"] == "FAILED"
    assert status["ledger"]["chain_ok"] is False
    assert any(item.startswith("CHAIN_") for item in status["why"])


def test_a_historical_refusal_does_not_mark_a_later_run_failed(tmp_path: Path) -> None:
    root = _session(tmp_path, resumed_last=True)
    refused = root / "REFUSED.json"
    refused.write_text(json.dumps({"reason": "RUNTIME_NOT_PROVABLE"}), encoding="utf-8")
    old = time.time() - 600
    os.utime(refused, (old, old))
    assert session_status(root)["state"] == "RECOVERED"

    #: An attempt recorded *after* the newest stream write is the current state; the same
    #: file with an older stamp is history.
    stale = time.time() - 300
    os.utime(root / "STREAM.jsonl", (stale, stale))
    refused.write_text(json.dumps({"reason": "RUNTIME_NOT_PROVABLE"}), encoding="utf-8")
    status = session_status(root)
    assert status["state"] == "FAILED"
    assert status["last_attempt"]["refused"] is True


def test_a_truncated_stream_is_a_failed_state_not_an_exception(tmp_path: Path) -> None:
    """A kill between ``write`` and ``fsync`` leaves a half line. The answer is FAILED."""

    root = _session(tmp_path, resumed_last=False)
    with (root / "STREAM.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"seq": 6, "prev_sha256": "deadbeef", "ent')

    status = session_status(root)

    assert status["state"] == "FAILED"
    assert status["ledger"]["chain_ok"] is False
    assert any(item.startswith("CHAIN_") for item in status["why"])
    assert status["read_only"] is True


def test_the_diagnostic_is_read_only(tmp_path: Path) -> None:
    root = _session(tmp_path, resumed_last=False)
    pid = _dead_pid()
    (root / "STREAM.jsonl.lock").write_text(json.dumps(_abandoned_record(pid)), encoding="utf-8")
    (root / "STREAM.jsonl.lock.fence").write_text("3\n", encoding="utf-8")

    def snapshot() -> dict[str, tuple[int, int, str]]:
        return {
            item.relative_to(root).as_posix(): (
                item.stat().st_size,
                item.stat().st_mtime_ns,
                hashlib.sha256(item.read_bytes()).hexdigest(),
            )
            for item in sorted(root.rglob("*"))
            if item.is_file()
        }

    before = snapshot()
    first = session_status(root)
    second = session_status(root)
    after = snapshot()

    assert before == after
    assert first["state"] == second["state"] == "RECOVERING"
    assert first["checked_at_utc"] is not None
    assert os.path.exists(root / "STREAM.jsonl.lock")
