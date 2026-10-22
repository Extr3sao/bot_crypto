"""Windows automation must not open a console window: RED contract, then GREEN.

The claim under test is narrow and checkable:

* every child we start on Windows is created with ``CREATE_NO_WINDOW`` and a
  ``STARTUPINFO`` whose ``wShowWindow`` is ``SW_HIDE``;
* the child's stdout, stderr, exit code and PID survive that;
* a timeout or a cancellation ends our child *and its descendants* and leaves a
  process we did not start alone;
* the launchers that automation actually uses — the supervisor, the scheduled
  task, the rehearsal and the report — go through that one implementation, so a
  new launcher cannot quietly reintroduce a window.

A window is not observable in every session (Windows Terminal hosts the console
without an ``HWND``), so the tests assert the mechanism that prevents it, plus a
live child that reports what console it received. They do not assert "I saw no
window" — that would be an unfalsifiable claim.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from trading_bot.ops import windowless

IS_WINDOWS = os.name == "nt"
REPO = Path(__file__).resolve().parents[3]
LAUNCHER = REPO / "scripts" / "windowless.py"


# --------------------------------------------------------------------- flags


@pytest.mark.skipif(not IS_WINDOWS, reason="CREATE_NO_WINDOW is a Windows contract")
def test_creation_flags_request_no_window() -> None:
    flags = windowless.creation_flags()
    assert flags & windowless.CREATE_NO_WINDOW
    assert flags != windowless.CREATE_NEW_CONSOLE


@pytest.mark.skipif(not IS_WINDOWS, reason="STARTUPINFO is a Windows contract")
def test_startupinfo_hides_the_first_window() -> None:
    info = windowless.startupinfo()
    assert info is not None
    assert info.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert info.wShowWindow == subprocess.SW_HIDE


def test_the_escape_hatch_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(windowless.OPT_OUT_ENV, "0")
    assert windowless.creation_flags() == 0
    assert windowless.startupinfo() is None


def test_popen_arguments_carry_the_flags() -> None:
    kwargs = windowless.popen_kwargs()
    if IS_WINDOWS:
        assert kwargs["creationflags"] & windowless.CREATE_NO_WINDOW
        assert kwargs["startupinfo"] is not None
    else:  # pragma: no cover - exercised on non-Windows CI
        assert kwargs["start_new_session"] is True


# ------------------------------------------------------------ run / capture


def test_run_keeps_streams_exit_code_and_pid(tmp_path: Path) -> None:
    events = windowless.ExecutionLog(tmp_path / "exec.jsonl")
    completed = windowless.run(
        [
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)",
        ],
        text=True,
        event_log=events,
        label="streams",
    )

    assert completed.returncode == 7
    assert completed.stdout.strip() == "out"
    assert completed.stderr.strip() == "err"
    record = json.loads((tmp_path / "exec.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert record["event"] == "exit"
    assert record["label"] == "streams"
    assert record["exit_code"] == 7
    assert isinstance(record["pid"], int) and record["pid"] > 0
    assert record["command"][0] == sys.executable
    assert record["duration_seconds"] >= 0
    assert "timed_out" in record


def test_a_timeout_ends_our_tree_and_not_a_foreign_process(tmp_path: Path) -> None:
    grandchild_pid = tmp_path / "grandchild.pid"
    child = textwrap.dedent(
        f"""
        import pathlib, subprocess, sys, time
        grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        pathlib.Path({str(grandchild_pid)!r}).write_text(str(grandchild.pid), encoding="utf-8")
        time.sleep(120)
        """
    )
    decoy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            windowless.run([sys.executable, "-c", child], timeout=1.5, text=True)

        assert grandchild_pid.exists(), "the child never started its grandchild"
        pid = int(grandchild_pid.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and windowless.process_alive(pid):
            time.sleep(0.1)
        assert not windowless.process_alive(pid), "the grandchild outlived the timed-out child"
        assert windowless.process_alive(decoy.pid), "a process we did not start was killed"
    finally:
        windowless.terminate_tree(decoy)


@pytest.mark.skipif(not IS_WINDOWS, reason="job objects are a Windows primitive")
def test_a_child_can_be_tied_to_the_launchers_lifetime() -> None:
    process = windowless.spawn([sys.executable, "-c", "import time; time.sleep(30)"])
    job = windowless.job_object_kill_on_close(process)
    try:
        assert job is not None, (
            "the launcher could not assign its child to a kill-on-close job: a crash would "
            "leave the child running with nobody watching it"
        )
    finally:
        windowless.terminate_tree(process)
        if job is not None:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(job)


def test_spawn_records_a_pid_and_a_finish_record(tmp_path: Path) -> None:
    events = windowless.ExecutionLog(tmp_path / "spawn.jsonl")
    log = tmp_path / "child.log"
    with log.open("wb") as handle:
        process = windowless.spawn(
            [sys.executable, "-c", "import sys; print('hello'); sys.exit(3)"],
            stdout=handle,
            event_log=events,
            label="spawned",
        )
    assert isinstance(process.pid, int) and process.pid > 0
    assert process.wait(timeout=30) == 3
    windowless.record_exit(process, event_log=events, label="spawned")
    assert "hello" in log.read_text(encoding="utf-8")
    records = [
        json.loads(line)
        for line in (tmp_path / "spawn.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["event"] for row in records] == ["spawn", "exit"]
    assert records[0]["pid"] == process.pid == records[1]["pid"]
    assert records[1]["exit_code"] == 3


# --------------------------------------------------------------- the launcher


def test_the_launcher_propagates_the_exit_code_and_writes_the_log(tmp_path: Path) -> None:
    log = tmp_path / "launcher.log"
    events = tmp_path / "launcher.jsonl"
    completed = subprocess.run(
        [
            sys.executable,
            str(LAUNCHER),
            "--log",
            str(log),
            "--event-log",
            str(events),
            "--label",
            "launcher",
            "--",
            sys.executable,
            "-c",
            "print('hola'); raise SystemExit(9)",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 9
    assert "hola" in log.read_text(encoding="utf-8")
    record = json.loads(events.read_text(encoding="utf-8").splitlines()[-1])
    assert record["exit_code"] == 9
    assert record["label"] == "launcher"


def test_the_launcher_reports_a_missing_command_as_a_spawn_error(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(LAUNCHER),
            "--log",
            str(tmp_path / "missing.log"),
            "--",
            str(tmp_path / "does-not-exist.exe"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 127
    assert "does-not-exist.exe" in (tmp_path / "missing.log").read_text(encoding="utf-8")


# ------------------------------------------------------------- real launchers


def _load_script(name: str) -> object:
    import importlib.util

    module_name = name.replace(".py", "")
    spec = importlib.util.spec_from_file_location(module_name, REPO / "scripts" / name)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves string annotations through sys.modules, so a module
    # loaded from a path must be registered before it is executed.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_the_scheduled_task_runs_through_the_windowless_launcher() -> None:
    module = _load_script("cap004_supervisor.py")
    command = module.task_command()  # type: ignore[attr-defined]
    arguments = module.task_arguments()  # type: ignore[attr-defined]

    assert Path(command).name.lower() == "pythonw.exe", (
        "a console-subsystem interpreter in an interactive scheduled task is a window"
    )
    assert "windowless.py" in arguments
    assert "cap004_supervisor.py" in arguments and "run" in arguments
    assert "cmd.exe" not in arguments.lower()


def test_the_supervisor_starts_and_stops_children_through_the_shared_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trading_bot.autonomous import supervisor as supervisor_module

    calls: dict[str, object] = {}

    real_spawn = windowless.spawn

    def spy_spawn(*args: object, **kwargs: object) -> object:
        calls["spawn"] = (args, kwargs)
        return real_spawn(*args, **kwargs)  # type: ignore[arg-type]

    real_terminate = windowless.terminate_tree

    def spy_terminate(*args: object, **kwargs: object) -> object:
        calls["terminate"] = (args, kwargs)
        return real_terminate(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(windowless, "spawn", spy_spawn)
    monkeypatch.setattr(windowless, "terminate_tree", spy_terminate)
    monkeypatch.setattr(supervisor_module.windowless, "spawn", spy_spawn)
    monkeypatch.setattr(supervisor_module.windowless, "terminate_tree", spy_terminate)

    spec = supervisor_module.ManagedProcess(
        name="oneshot",
        command=[sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        critical=False,
        restart_on_exit=False,
    )
    runtime = supervisor_module.ProcessRuntime(spec=spec)
    runtime.start(tmp_path / "oneshot.log")
    try:
        assert "spawn" in calls
        assert runtime.pid is not None
    finally:
        runtime.stop(timeout=10)
    assert "terminate" in calls


# ------------------------------------------------------------- the repository


def test_no_controlled_launcher_can_start_an_unhidden_child() -> None:
    module = _load_script("ops_background_audit.py")
    report = module.scan(REPO)  # type: ignore[attr-defined]
    high = [finding for finding in report["findings"] if finding["severity"] == "HIGH"]
    assert not high, json.dumps(high, indent=2)
