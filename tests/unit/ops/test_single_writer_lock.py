"""CODEX — the single-writer lock must survive a crash without ever dispossessing a writer.

The bug these tests exist for is the one that made a sustained PAPER loop impossible: a
hard kill left ``*.lock`` files behind, and the next run could not start. The naive fix
("delete a lock older than N minutes") is a guess, and it is wrong in two directions that
this file exercises with **real processes**, not mocks:

* a live owner must never be dispossessed, however old its stamp looks;
* a *recycled pid* must not be mistaken for a live owner — the recorded process start time
  is what separates "the owner is still there" from "a stranger inherited its pid". Without
  that column a crash plus a busy host wedges the artefact forever.

Scenarios covered, one test each: normal acquire/release, crash → reclaim, resume without
duplicating rows, two processes racing to reclaim, a live owner, a reused pid, a crash
*during* recovery (stale arbiter), a corrupt/torn lock, a foreign-host owner, and a writer
that lost its lock being refused its next append.

The concurrency tests spawn independent interpreters. In-process threads would share the
GIL and the same ``os.getpid()``, which is exactly the state whose absence matters here.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from trading_bot.ops import single_writer
from trading_bot.ops.single_writer import (
    LockLost,
    LockRefused,
    SingleWriter,
    diagnose_lock,
    process_start_ms,
    reclaim_abandoned,
)
from trading_bot.vision.ledger import DecisionLedger, LedgerLockedError, verify_chain

REPO = Path(__file__).resolve().parents[3]

HOLD_SCRIPT = """
import json, os, sys, time
from pathlib import Path
from trading_bot.ops.single_writer import SingleWriter

path, ready = Path(sys.argv[1]), Path(sys.argv[2])
lock = SingleWriter(path, purpose="test-hold")
result = lock.acquire()
ready.write_text(
    json.dumps({
        "status": result["status"],
        "token": lock.record["token"],
        #: The real interpreter, not the launcher ``Popen`` started. A uv virtualenv's
        #: ``python.exe`` is a trampoline: ``Popen.pid`` is the trampoline, and killing it
        #: leaves the process that holds the lock alive. Measured, and the reason the crash
        #: test kills this pid instead.
        "pid": os.getpid(),
    })
)
time.sleep(120)
lock.release()
"""

CONTEND_SCRIPT = """
import json, sys, time
from pathlib import Path
from trading_bot.ops.single_writer import SingleWriter, LockRefused

path, go, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
while not go.exists():
    time.sleep(0.005)
lock = SingleWriter(path, purpose="test-contend")
try:
    result = lock.acquire()
    status = result["status"]
except LockRefused as exc:
    status = exc.code
out.write_text(
    json.dumps({
        "status": status,
        "token": (lock.record or {}).get("token"),
        "fence": (lock.record or {}).get("fence"),
    })
)
#: The winner keeps holding while the others finish deciding. A winner that exited at once
#: would leave an *abandoned* lock, and a later contender would reclaim it legitimately —
#: correct behaviour that would make this test's "exactly one winner" claim wrong.
time.sleep(1.5)
"""


def _dead_pid() -> int:
    """A pid that existed and no longer does: spawned, reaped, then asked again."""

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return int(proc.pid)


def _dead_pid_or_skip() -> int:
    pid = _dead_pid()
    if single_writer.pid_alive(pid):  # pragma: no cover - pid reuse on a busy host
        pytest.skip("the reaped pid was reused before it could be probed")
    return pid


def _record(path: Path, **overrides: object) -> dict[str, object]:
    """Write a lock record by hand, the way a crashed owner would have left it."""

    payload: dict[str, object] = {
        "schema_version": single_writer.SCHEMA_VERSION,
        "purpose": "test",
        "path": path.name,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "process_start_ms": process_start_ms(os.getpid()),
        "token": "deadbeef" * 4,
        "fence": 1,
    }
    payload.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _spawn(script: str, *args: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", script, *(str(arg) for arg in args)],
        cwd=str(REPO),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _hard_kill(pid: int) -> None:
    """Terminate a process without giving it a chance to release anything."""

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/PID", str(int(pid))],
            capture_output=True,
            text=True,
            check=False,
        )
    else:  # pragma: no cover - the host is Windows
        import signal

        os.kill(int(pid), signal.SIGKILL)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not single_writer.pid_alive(int(pid)):
            return
        time.sleep(0.02)
    raise AssertionError(f"pid {pid} survived a hard kill")


def _wait_for(path: Path, *, timeout_s: float = 60.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size:
            return json.loads(path.read_text(encoding="utf-8"))
        time.sleep(0.01)
    raise AssertionError(f"{path} was not written within {timeout_s}s")


# --------------------------------------------------------------- normal lifecycle


def test_a_lock_is_acquired_fenced_and_released(tmp_path: Path) -> None:
    path = tmp_path / "STREAM.jsonl.lock"
    lock = SingleWriter(path, purpose="normal")

    acquired = lock.acquire()
    assert acquired["status"] == "ACQUIRED"
    assert acquired["fence"] == 1
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["token"] == lock.record["token"]
    assert on_disk["pid"] == os.getpid()
    #: The record is complete the instant it exists: no empty window a reader could mistake
    #: for an unattributable lock. ``os.link`` gives creation *and* content in one step.
    assert on_disk["process_start_ms"] == process_start_ms(os.getpid())
    assert lock.assert_held()["token"] == on_disk["token"]

    assert lock.release() is True
    assert not path.exists()
    #: The fence outlives the lock, so no later acquisition can reuse a lower number.
    assert int((tmp_path / "STREAM.jsonl.lock.fence").read_text().strip()) == 1


def test_a_second_writer_is_refused_while_the_owner_is_alive(tmp_path: Path) -> None:
    path = tmp_path / "STREAM.jsonl.lock"
    ready = tmp_path / "ready.json"
    holder = _spawn(HOLD_SCRIPT, path, ready)
    try:
        first = _wait_for(ready)
        assert first["status"] == "ACQUIRED"
        before = path.read_text(encoding="utf-8")

        with pytest.raises(LockRefused) as excinfo:
            SingleWriter(path, purpose="intruder").acquire()
        assert excinfo.value.code == "LOCK_HELD"
        assert diagnose_lock(json.loads(before))["state"] == "HELD"
        assert path.read_text(encoding="utf-8") == before, "a live owner's lock is untouched"

        with pytest.raises(LockRefused) as excinfo:
            reclaim_abandoned(path)
        assert excinfo.value.code == "LOCK_HELD"
    finally:
        _hard_kill(int(first["pid"]))
        holder.kill()
        holder.wait(timeout=30)


def test_a_killed_owner_is_reclaimed_and_the_crash_is_evidence(tmp_path: Path) -> None:
    path = tmp_path / "STREAM.jsonl.lock"
    ready = tmp_path / "ready.json"
    holder = _spawn(HOLD_SCRIPT, path, ready)
    first = _wait_for(ready)
    #: A hard crash: no finally, no release, the file stays behind.
    _hard_kill(int(first["pid"]))
    holder.wait(timeout=30)

    evidence = reclaim_abandoned(path, purpose="test-recovery")
    assert evidence is not None
    assert evidence["reason"] == "OWNER_PROCESS_DEAD"
    assert evidence["pid"] == first["pid"]
    assert evidence["fence"] == 2, "the takeover advanced the fence past the crashed owner"
    assert not path.exists(), "reclaim hands the artefact back free, it does not keep it"

    #: The crashed owner's token can no longer be presented: any survivor of that process
    #: would be refused on its next protected write.
    assert evidence["fence"] != first.get("fence")


def test_a_reused_pid_is_recognised_as_a_different_owner(tmp_path: Path) -> None:
    path = tmp_path / "ETHUSDT.jsonl.lock"
    real_start = process_start_ms(os.getpid())
    assert real_start is not None
    _record(path, pid=os.getpid(), process_start_ms=int(real_start) - 60_000)

    verdict = diagnose_lock(json.loads(path.read_text(encoding="utf-8")))
    assert verdict["state"] == "ABANDONED"
    assert verdict["reason"] == "PID_REUSED"

    result = SingleWriter(path, purpose="after-reuse").acquire()
    assert result["status"] == "RECLAIMED"
    assert result["previous_owner"]["pid"] == os.getpid()


def test_a_live_pid_with_a_matching_start_time_is_never_reclaimed(tmp_path: Path) -> None:
    path = tmp_path / "SOLUSDT.jsonl.lock"
    _record(path)  # exactly this process, exactly its start time
    assert diagnose_lock(json.loads(path.read_text(encoding="utf-8")))["state"] == "HELD"
    with pytest.raises(LockRefused) as excinfo:
        SingleWriter(path, purpose="after-live").acquire()
    assert excinfo.value.code == "LOCK_HELD"


# ------------------------------------------------------------------ unsafe records


@pytest.mark.parametrize("content", ["", "   \n", "not a lock", '{"pid": "seven"}'])
def test_a_lock_whose_owner_cannot_be_named_is_refused_not_deleted(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / "broken.jsonl.lock"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(LockRefused) as excinfo:
        SingleWriter(path, purpose="broken").acquire()
    assert excinfo.value.code == "LOCK_UNATTRIBUTED"
    assert path.read_text(encoding="utf-8") == content, "an unattributable lock is never removed"


def test_a_lock_written_by_another_host_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "remote.jsonl.lock"
    _record(path, host="some-other-machine", pid=_dead_pid_or_skip())

    verdict = diagnose_lock(json.loads(path.read_text(encoding="utf-8")))
    assert verdict["state"] == "UNATTRIBUTED"
    assert verdict["reason"] == "FOREIGN_HOST_OWNER"
    with pytest.raises(LockRefused) as excinfo:
        reclaim_abandoned(path)
    assert excinfo.value.code == "LOCK_UNATTRIBUTED"
    assert path.exists()


# ------------------------------------------------------------------- concurrency


def test_only_one_of_many_processes_reclaims_the_same_lock(tmp_path: Path) -> None:
    path = tmp_path / "STREAM.jsonl.lock"
    go = tmp_path / "go"
    dead = _dead_pid_or_skip()
    _record(path, pid=dead, process_start_ms=None, token="crashed" * 8)

    outputs = [tmp_path / f"result-{index}.json" for index in range(6)]
    procs = [_spawn(CONTEND_SCRIPT, path, go, out) for out in outputs]
    go.touch()
    try:
        results = [_wait_for(out) for out in outputs]
        for proc in procs:
            assert proc.wait(timeout=60) == 0
    finally:
        for proc in procs:
            if proc.poll() is None:  # pragma: no cover - only on a hung child
                proc.kill()
                proc.wait(timeout=30)

    winners = [row for row in results if row["status"] in ("ACQUIRED", "RECLAIMED")]
    losers = [row for row in results if row["status"] not in ("ACQUIRED", "RECLAIMED")]
    assert len(winners) == 1, results
    assert winners[0]["status"] == "RECLAIMED"
    assert {row["status"] for row in losers} <= {"LOCK_HELD", "LOCK_CONTENDED"}
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["token"] == winners[0]["token"], "the file names the one winner"
    assert int(stored["fence"]) == int(winners[0]["fence"])


def test_a_crash_during_recovery_leaves_a_recoverable_arbiter(tmp_path: Path) -> None:
    path = tmp_path / "STREAM.jsonl.lock"
    arbiter = path.with_name(path.name + single_writer.ARBITER_SUFFIX)
    dead = _dead_pid_or_skip()
    _record(path, pid=dead, process_start_ms=None, token="crashed" * 8)
    #: The recovery process died *after* taking the arbiter and before replacing the record.
    _record(arbiter, pid=dead, process_start_ms=None, token="recoverer" * 4)

    result = SingleWriter(path, purpose="after-recovery-crash").acquire()

    assert result["status"] == "RECLAIMED"
    assert not arbiter.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["token"] == result["token"]


def test_a_torn_arbiter_is_broken_only_after_its_grace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "STREAM.jsonl.lock"
    arbiter = path.with_name(path.name + single_writer.ARBITER_SUFFIX)
    dead = _dead_pid_or_skip()
    _record(path, pid=dead, process_start_ms=None, token="crashed" * 8)

    arbiter.write_text("", encoding="utf-8")  # torn: create happened, write did not
    monkeypatch.setattr(single_writer, "ARBITER_WAIT_SECONDS", 0.2)
    with pytest.raises(LockRefused) as excinfo:
        SingleWriter(path, purpose="too-soon").acquire()
    assert excinfo.value.code == "LOCK_CONTENDED"
    assert path.exists() and arbiter.exists(), "nothing was guessed while the arbiter is fresh"

    old = time.time() - single_writer.ARBITER_UNATTRIBUTED_GRACE_SECONDS - 1
    os.utime(arbiter, (old, old))
    result = SingleWriter(path, purpose="after-grace").acquire()
    assert result["status"] == "RECLAIMED"


def test_a_live_arbiter_holder_blocks_recovery_without_being_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "STREAM.jsonl.lock"
    arbiter = path.with_name(path.name + single_writer.ARBITER_SUFFIX)
    dead = _dead_pid_or_skip()
    original = _record(path, pid=dead, process_start_ms=None, token="crashed" * 8)
    _record(arbiter)  # this very process is inside its decision
    monkeypatch.setattr(single_writer, "ARBITER_WAIT_SECONDS", 0.2)

    with pytest.raises(LockRefused) as excinfo:
        SingleWriter(path, purpose="blocked").acquire()
    assert excinfo.value.code == "LOCK_CONTENDED"
    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert arbiter.exists()


# ------------------------------------------------------- consumers use the real code


def test_a_ledger_whose_lock_was_taken_over_refuses_to_append(tmp_path: Path) -> None:
    path = tmp_path / "STREAM.jsonl"
    ledger = DecisionLedger(path).open()
    try:
        ledger.append("RUN", {"note": "before the takeover"})
        #: A takeover the writer did not notice: exactly what a paused process sees when its
        #: lock is reclaimed after a crash it did not have.
        _record(path.with_suffix(".jsonl.lock"), token="new-owner" * 4, fence=9)
        with pytest.raises(LedgerLockedError, match="LOCK_LOST"):
            ledger.append("RUN", {"note": "must never be written"})
    finally:
        ledger.close()

    assert verify_chain(path)["ok"] is True
    rows = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1, "the refused append left no row behind"


def test_a_resumed_ledger_continues_the_chain_without_duplicating_rows(tmp_path: Path) -> None:
    path = tmp_path / "cycles" / "cycle-0001" / "ledger.jsonl"
    path.parent.mkdir(parents=True)
    crashed = DecisionLedger(path).open()
    crashed.append("RUN", {"step": 1})
    crashed.append("DECISION", {"step": 2})
    crashed_record = dict(crashed.lock_record)
    #: Simulate the crash: the process is gone but the lock file stayed, with its pid dead.
    crashed._lock.record = None  # do not let ``close`` remove the file we want to keep
    _record(
        path.with_suffix(".jsonl.lock"),
        pid=_dead_pid_or_skip(),
        process_start_ms=None,
        token=crashed_record["token"],
        fence=crashed_record["fence"],
    )

    evidence = reclaim_abandoned(path.with_suffix(".jsonl.lock"))
    assert evidence is not None and evidence["reason"] == "OWNER_PROCESS_DEAD"

    resumed = DecisionLedger(path).open()
    try:
        resumed.append("DECISION", {"step": 3})
    finally:
        resumed.close()

    report = verify_chain(path)
    assert report["ok"] is True
    assert report["lines"] == 3
    seqs = [json.loads(line)["seq"] for line in path.read_text(encoding="utf-8").splitlines()]
    assert seqs == [1, 2, 3], "a resume appends; it never rewrites or repeats a row"


def test_lost_ownership_is_reported_not_silently_ignored(tmp_path: Path) -> None:
    path = tmp_path / "minutes.jsonl.lock"
    lock = SingleWriter(path, purpose="lost")
    lock.acquire()
    original = dict(lock.record or {})

    #: Another owner installs itself over the record: the old holder still has its token in
    #: memory and must fail closed on the next protected write.
    _record(path, token="another" * 4, fence=int(original["fence"]) + 1)

    with pytest.raises(LockLost) as excinfo:
        lock.assert_held()
    assert excinfo.value.code == "LOCK_LOST"
    assert lock.release() is False, "a lock we no longer own is never deleted by us"
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["token"] == "another" * 4
