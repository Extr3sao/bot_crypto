"""§19-§22 — a full disk degrades the lab; it does not take the lab down.

The failures under test here actually happened, on this host: the research volume
filled while the lab was running, PAPER died with an unhandled ``OSError`` from
writing its own daily report, and the supervisor died from writing its own
heartbeat — which left nobody to restart anything and no evidence of why.

Three claims close that:

* an artifact write that fails is recorded and survived, never raised
  (``durable_write``), so PAPER keeps deciding;
* the supervisor survives its own heartbeat failing;
* when the volume reaches the configured ``STOP`` level, the capture is asked to
  stop gracefully and PAPER is deliberately left running (§22).
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from trading_bot.autonomous.paper_loop import (
    ArtifactWriteFailures,
    HeartbeatWriter,
    PaperHeartbeat,
    durable_write,
)
from trading_bot.autonomous.supervisor import (
    DiskLevel,
    DiskThresholds,
    ManagedProcess,
    ProcessState,
    Supervisor,
    disk_free_bytes,
)

RUNNING_CHILD = "import time; time.sleep(60)"
GRACEFUL_CHILD = (
    "import pathlib, sys, time;"
    " stop = pathlib.Path(sys.argv[1]); out = pathlib.Path(sys.argv[2]);"
    "\nwhile not stop.exists():\n    time.sleep(0.05)\n"
    "out.write_text('sealed=1\\n', encoding='utf-8'); sys.exit(0)"
)


def _heartbeat(cycle: int = 1) -> PaperHeartbeat:
    return PaperHeartbeat(
        run_id="run-ops",
        cycle=cycle,
        timestamp_ms=1_800_000_000_000,
        assets=("BTC",),
        timeframe="5m",
        strategies_evaluated=3,
        decisions=1,
        no_trade=1,
        no_trade_kinds={"NO_TRADE_STRATEGIC": 1},
        shadow_trades=0,
        paper_trades=0,
        risk_vetoes=0,
        runtime_failures=0,
        errors=(),
        cycles_completed=cycle,
        uptime_seconds=60.0,
        state_age_seconds=None,
    )


# ------------------------------------------------------------ durable writes (§22)


def test_a_storage_failure_is_recorded_and_never_raised() -> None:
    failures = ArtifactWriteFailures()

    def _write() -> str:
        raise OSError(28, "No space left on device")

    assert durable_write(_write, what="daily report", failures=failures) is None
    assert failures.count == 1
    assert "No space left on device" in failures.failures[0]
    assert failures.recent()[0].startswith("daily report:")


def test_a_programming_error_is_still_raised() -> None:
    """Only the operational condition is absorbed; a bug must surface."""
    failures = ArtifactWriteFailures()

    def _write() -> None:
        raise ValueError("serialiser is wrong")

    with pytest.raises(ValueError):
        durable_write(_write, what="daily report", failures=failures)
    assert failures.count == 0


def test_a_heartbeat_that_cannot_be_written_does_not_stop_the_loop(tmp_path: Path) -> None:
    """The exact failure that killed PAPER: a heartbeat the volume refuses."""
    # ``run_dir`` is a *file*, so no heartbeat can ever be created under it.
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupied\n", encoding="utf-8")
    writer = HeartbeatWriter(run_dir=blocked)
    failures = ArtifactWriteFailures()

    result = durable_write(
        lambda: writer.write(_heartbeat()), what="heartbeat", failures=failures
    )

    assert result is None
    assert failures.count == 1
    assert writer.written == 0
    # And the loop is still able to record the next cycle's decision.
    assert failures.recent()[0].startswith("heartbeat:")


def test_the_heartbeat_carries_the_storage_failures_it_survived(tmp_path: Path) -> None:
    writer = HeartbeatWriter(run_dir=tmp_path)
    beat = replace(
        _heartbeat(),
        storage_failures=2,
        storage_errors=("daily report: OSError: ENOSPC", "heartbeat: OSError: ENOSPC"),
    )
    writer.write(beat)

    payload = json.loads(writer.current_path.read_text(encoding="utf-8"))
    assert payload["storage_failures"] == 2
    assert len(payload["storage_errors"]) == 2


# ------------------------------------------------- the supervisor survives its own evidence


def test_a_heartbeat_that_cannot_be_written_does_not_kill_the_supervisor(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.write_text("not a directory\n", encoding="utf-8")
    supervisor = Supervisor.build(
        run_dir,
        [
            ManagedProcess(
                name="paper",
                command=[sys.executable, "-c", RUNNING_CHILD],
                cwd=Path.cwd(),
            )
        ],
        heartbeat_seconds=0.05,
    )
    # Start is best-effort under a broken run dir; the loop must not raise.
    final = supervisor.supervise_forever(stop_requested=lambda: False, max_seconds=0.2)
    assert supervisor.heartbeat_write_failures >= 1
    assert final["heartbeat_write_failures"] >= 1


def test_supervision_survives_an_event_callback_that_raises(tmp_path: Path) -> None:
    supervisor = Supervisor.build(
        tmp_path,
        [
            ManagedProcess(
                name="paper",
                command=[sys.executable, "-c", "raise SystemExit(3)"],
                cwd=Path.cwd(),
                max_restarts=1,
                backoff_seconds=(0.01,),
            )
        ],
        heartbeat_seconds=0.05,
    )
    supervisor.start_all()

    def _bad_callback(_event: dict[str, object]) -> None:
        raise RuntimeError("the report renderer is broken")

    final = supervisor.supervise_forever(
        stop_requested=lambda: False, on_event=_bad_callback, max_seconds=3.0
    )
    assert final["processes"]["paper"]["state"] == ProcessState.FAILED.value


# ----------------------------------------------------------- the storage guard (§22)


def _guard_supervisor(tmp_path: Path) -> tuple[Supervisor, Path, Path]:
    collector_stop = tmp_path / "collector.stop"
    sealed = tmp_path / "sealed.txt"
    stop_bytes = disk_free_bytes(tmp_path) + 10**9  # nothing is ever that free
    supervisor = Supervisor.build(
        tmp_path / "run",
        [
            ManagedProcess(
                name="paper",
                command=[sys.executable, "-c", RUNNING_CHILD],
                cwd=Path.cwd(),
                stop_file=tmp_path / "paper.stop",
            ),
            ManagedProcess(
                name="collector",
                command=[
                    sys.executable,
                    "-c",
                    GRACEFUL_CHILD,
                    str(collector_stop),
                    str(sealed),
                ],
                cwd=Path.cwd(),
                stop_file=collector_stop,
                stop_on_storage_guard=True,
            ),
        ],
        heartbeat_seconds=0.05,
        disk_thresholds=DiskThresholds(warning_bytes=stop_bytes, critical_bytes=stop_bytes, stop_bytes=stop_bytes),
    )
    return supervisor, collector_stop, sealed


def test_the_storage_guard_stops_the_capture_and_leaves_paper_running(tmp_path: Path) -> None:
    supervisor, collector_stop, sealed = _guard_supervisor(tmp_path)
    supervisor.start_all()
    paper_state_when_guarded: list[str] = []
    events: list[dict[str, object]] = []

    def _on_event(event: dict[str, object]) -> None:
        events.append(event)
        if event.get("event") == "STORAGE_GUARD_STOP":
            paper_state_when_guarded.append(supervisor.get("paper").state.value)

    final = supervisor.supervise_forever(
        stop_requested=lambda: False, on_event=_on_event, max_seconds=4.0, storage_guard=True
    )

    guarded = [event for event in events if event.get("event") == "STORAGE_GUARD_STOP"]
    assert guarded, events
    assert guarded[0]["processes"] == ["collector"]
    # PAPER was untouched at the moment the guard fired.
    assert paper_state_when_guarded == [ProcessState.RUNNING.value]
    # The capture was asked politely, sealed its work, and exited cleanly.
    assert collector_stop.exists()
    assert sealed.exists()
    assert final["processes"]["collector"]["exit_code"] == 0
    assert final["processes"]["collector"]["state"] == ProcessState.STOPPED.value
    # And it was never restarted into the full volume.
    assert not [
        event
        for event in events
        if event.get("event") == "RESTART_SCHEDULED" and event.get("process") == "collector"
    ]
    assert final["disk"]["level"] == DiskLevel.STOP.value


def test_the_guard_is_not_armed_when_the_volume_is_fine(tmp_path: Path) -> None:
    supervisor = Supervisor.build(
        tmp_path / "run",
        [
            ManagedProcess(
                name="collector",
                command=[
                    sys.executable,
                    "-c",
                    GRACEFUL_CHILD,
                    str(tmp_path / "collector.stop"),
                    str(tmp_path / "sealed.txt"),
                ],
                cwd=Path.cwd(),
                stop_file=tmp_path / "collector.stop",
                stop_on_storage_guard=True,
            )
        ],
        heartbeat_seconds=0.05,
        disk_thresholds=DiskThresholds(
            warning_bytes=1, critical_bytes=1, stop_bytes=1
        ),
    )
    supervisor.start_all()
    events: list[dict[str, object]] = []
    final = supervisor.supervise_forever(
        stop_requested=lambda: False,
        on_event=events.append,
        max_seconds=0.5,
        storage_guard=True,
        stop_grace_seconds=10.0,
    )
    assert not [event for event in events if event.get("event") == "STORAGE_GUARD_STOP"]
    assert final["disk"]["level"] == DiskLevel.NORMAL.value
    assert final["processes"]["collector"]["state"] == ProcessState.STOPPED.value
    assert final["processes"]["collector"]["exit_code"] == 0


def test_disk_telemetry_reports_rate_and_survival_time() -> None:
    from trading_bot.autonomous.supervisor import DiskTelemetry

    telemetry = DiskTelemetry(thresholds=DiskThresholds(stop_bytes=0))
    telemetry.observe(3_000_000_000, now=0.0)
    telemetry.observe(1_000_000_000, now=3600.0)
    payload = telemetry.as_dict()
    assert payload["consumption_bytes_per_hour"] == pytest.approx(2_000_000_000)
    assert payload["estimated_hours_remaining"] == pytest.approx(0.5)
    assert payload["level"] == DiskLevel.WARNING.value


def test_the_guard_needs_a_stop_file_to_be_able_to_be_polite(tmp_path: Path) -> None:
    """A child with no cooperative stop is never selected by the guard."""
    supervisor = Supervisor.build(
        tmp_path / "run",
        [
            ManagedProcess(
                name="collector",
                command=[sys.executable, "-c", RUNNING_CHILD],
                cwd=Path.cwd(),
                stop_on_storage_guard=True,
            )
        ],
    )
    supervisor.start_all()
    try:
        assert supervisor.request_storage_guard() == []
        assert supervisor.storage_stopped == set()
    finally:
        supervisor.stop_all()


def test_a_sleeping_child_is_still_alive_to_the_supervisor(tmp_path: Path) -> None:
    supervisor = Supervisor.build(
        tmp_path / "run",
        [ManagedProcess(name="paper", command=[sys.executable, "-c", RUNNING_CHILD], cwd=Path.cwd())],
    )
    supervisor.start_all()
    try:
        time.sleep(0.2)
        assert supervisor.get("paper").state is ProcessState.RUNNING
        assert supervisor.get("paper").is_alive
    finally:
        supervisor.stop_all()


# ------------------------------------------------- the rest of the §6 inject list


def test_the_disk_level_ladder_is_complete_and_monotone() -> None:
    """§6/§20 — every level a bounded volume passes through is reachable.

    The guard behaviour is keyed off these levels, so a level that can never be
    returned (or a boundary that overlaps) is a guard that never fires.
    """
    thresholds = DiskThresholds(
        warning_bytes=1_500_000_000,
        critical_bytes=800_000_000,
        stop_bytes=300_000_000,
    )

    assert thresholds.level_for(10_000_000_000) is DiskLevel.NORMAL
    assert thresholds.level_for(1_500_000_000) is DiskLevel.WARNING
    assert thresholds.level_for(1_499_999_999) is DiskLevel.WARNING
    assert thresholds.level_for(800_000_000) is DiskLevel.CRITICAL
    assert thresholds.level_for(799_999_999) is DiskLevel.CRITICAL
    assert thresholds.level_for(300_000_000) is DiskLevel.STOP
    assert thresholds.level_for(0) is DiskLevel.STOP

    # The ladder only ever gets more urgent as space runs out.
    order = [DiskLevel.NORMAL, DiskLevel.WARNING, DiskLevel.CRITICAL, DiskLevel.STOP]
    seen = [thresholds.level_for(free) for free in (2_000_000_000, 1_000_000_000, 400_000_000, 1)]
    assert seen == order


def test_a_reused_pid_is_not_reported_as_the_run_still_being_alive() -> None:
    """§6/§26 — a PID is not a heartbeat.

    The operator console must not call a lab healthy because some number is
    still in the process table, and it must not invent a death when it simply
    cannot look.
    """
    from trading_bot.autonomous.observability import process_alive

    # A PID far above anything this host allocates: nothing can be there.
    assert process_alive(999_999_999) is False
    # No PID at all is "unknown", which is different from "dead".
    assert process_alive(None) is None
    # Our own live process is the positive control.
    assert process_alive(os.getpid()) is True


def test_a_dead_collector_is_not_reported_as_ready() -> None:
    """§57 — readiness must not contradict the verdicts next to it.

    A capture that dies on its *first* write never saves a state file, so a
    readiness check keyed off ``fatal_failure`` alone said "COLLECTOR_READY:
    yes" while the supervisor had already given up on the collector with a
    crash loop. That is a false success: the operator console is the one place
    it must not happen.
    """
    from trading_bot.autonomous.observability import _readiness_flags

    def payload(**collector: Any) -> dict[str, Any]:
        return {
            "children": {"collector": {"state": ProcessState.RUNNING.value}},
            "disk": {"level": DiskLevel.NORMAL.value},
            "paper": {"available": True},
            "collector": {"available": True, "fatal_failure": None, "manifest": None, **collector},
            "strategy_lab": {"available": True, "all_checks_ok": True},
            "readiness": {"M-03": {"verdict": "COLLECTING"}, "M-07": {"verdict": "COLLECTING"}},
            "errors": [],
        }

    # The honest baseline: a healthy, running collector with no verdict against it.
    assert _readiness_flags(payload())["COLLECTOR_READY"] is True

    # A manifest that says FAILED is a verdict, even when the state file is missing.
    failed_manifest = payload(manifest={"status": "FAILED", "failure_kind": "STORAGE_WRITE_FAILURE"})
    assert _readiness_flags(failed_manifest)["COLLECTOR_READY"] is False

    # And so is a supervisor that has declared the child FAILED.
    crashed = payload()
    crashed["children"]["collector"]["state"] = ProcessState.FAILED.value
    assert _readiness_flags(crashed)["COLLECTOR_READY"] is False


def test_the_status_screen_never_prints_a_missing_measurement_as_none() -> None:
    """§19 — "unknown" is a fact; "~None h" is a rendering bug."""
    from trading_bot.autonomous.observability import status_summary

    status = {
        "run_id": "run-x",
        "mode": "PAPER",
        "generated_at_iso": "2026-09-29T00:00:00Z",
        "run_dir": "/tmp/run-x",
        "system": {"state": "DEGRADED", "running": False, "heartbeat_age_seconds": 12.0},
        "disk": {
            "free_gb": 12.3,
            "level": DiskLevel.NORMAL.value,
            "consumption_gb_per_day": None,
            "estimated_hours_remaining": None,
            "guidance": "no action",
        },
    }

    rendered = status_summary(status)

    assert "survival unknown" in rendered
    assert "=None" not in rendered
    assert "Nones" not in rendered

    # When a rate was measured it is shown, in the units it was measured in.
    status["disk"].update({"consumption_gb_per_day": 3.2, "estimated_hours_remaining": 3.84})
    measured = status_summary(status)
    assert "3.84 h at 3.2 GB/day" in measured
    assert "=None" not in measured

    # A plane with nothing to say is spelled "?", not "None", and a missing
    # measurement never grows a unit suffix ("state_age=Nones").
    assert "cycles=?" in measured
    assert "state_age=?" in measured
    assert "?s" not in measured


def test_a_child_log_written_in_the_console_code_page_is_not_mangled(tmp_path: Path) -> None:
    """§26/§57 — reading a log must not invent characters a console cannot print.

    A child's stdout is a redirected handle, so on Windows its log is written in
    the console code page while the same child's JSON artifacts are UTF-8. Reading
    that log as UTF-8 with ``errors="replace"`` injected U+FFFD into the status
    payload, and a cp1252 console then raised ``UnicodeEncodeError`` — the
    operator's own status command died with a traceback.
    """
    from trading_bot.autonomous.observability import _last_log_error

    run_dir = tmp_path / "run"
    logs = run_dir / "logs"
    logs.mkdir(parents=True)
    # 0x97 is the cp1252 em dash and is not valid UTF-8, exactly like the real log.
    (logs / "collector.log").write_bytes(
        b"forward collector: FAILED \x97 refusing to exit 0\n"
    )

    found = _last_log_error(run_dir, "collector")

    assert found is not None
    assert "\ufffd" not in found["line"]
    assert "\x97" not in found["line"]
    assert "refusing to exit 0" in found["line"]
    # And the payload it lands in is safe for a console that cannot print it.
    assert json.dumps(found, ensure_ascii=True).isascii()


def test_a_missing_or_corrupt_manifest_is_absent_not_an_empty_capture(tmp_path: Path) -> None:
    """§6/§57 — unreadable evidence is not evidence.

    A capture whose manifest never got written must read as "no manifest on
    disk", never as a manifest full of zeros that looks like a clean short run.
    """
    from trading_bot.autonomous import observability

    forward = tmp_path / "forward"
    (forward / "state").mkdir(parents=True)
    (forward / "state" / "run-x.json").write_text(
        json.dumps({"events": 12, "gaps": 0, "reconnects": 0, "resnapshots": 0}),
        encoding="utf-8",
    )

    missing = observability._collector_status(forward, "run-x", now_ms=1_800_000_000_000)
    assert missing["manifest"] is None
    # The state file is still read: absence of a manifest is not absence of a run.
    assert missing["events"] == 12

    (forward / "manifest").mkdir()
    (forward / "manifest" / "run-x.json").write_text("{not json", encoding="utf-8")
    corrupt = observability._collector_status(forward, "run-x", now_ms=1_800_000_000_000)
    assert corrupt["manifest"] is None
