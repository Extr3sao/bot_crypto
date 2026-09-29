"""Supervisor tests: restart, backoff, crash-loop protection, isolation (§26-§31).

The children here are real processes (`python -c ...`), not mocks: the claim
under test is precisely that separate operating-system processes have separate
failure domains, and a mock cannot fail that way.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from trading_bot.autonomous.supervisor import (
    ManagedProcess,
    ProcessState,
    Supervisor,
    SystemState,
    disk_free_bytes,
)

RUNNING_CHILD = "import time, sys; time.sleep(60); sys.exit(0)"
FAILING_CHILD = "raise SystemExit(3)"
ONESHOT_CHILD = "import sys; sys.exit(0)"
#: A child that can only be stopped by the file it polls: it seals "output" and
#: exits 0 — exactly what the collector does with its manifest (§51).
GRACEFUL_CHILD = (
    "import pathlib, sys, time;"
    " stop = pathlib.Path(sys.argv[1]); out = pathlib.Path(sys.argv[2]);"
    "\nwhile not stop.exists():\n    time.sleep(0.05)\n"
    "out.write_text('sealed=1\\n', encoding='utf-8'); sys.exit(0)"
)
#: A child that ignores the stop file, to prove the escalation still exists.
DEAF_CHILD = "import time; time.sleep(60)"


def _spec(
    name: str,
    code: str,
    *,
    critical: bool = True,
    max_restarts: int = 3,
    window: float = 900.0,
    backoff: tuple[float, ...] = (0.05, 0.1, 0.2),
    restart_on_exit: bool = True,
    args: tuple[str, ...] = (),
    stop_file: Path | None = None,
) -> ManagedProcess:
    return ManagedProcess(
        name=name,
        command=[sys.executable, "-c", code, *args],
        cwd=Path.cwd(),
        critical=critical,
        max_restarts=max_restarts,
        crash_loop_window_seconds=window,
        backoff_seconds=backoff,
        env={},
        restart_on_exit=restart_on_exit,
        stop_file=stop_file,
    )


def _supervisor(tmp_path: Path, specs: list[ManagedProcess]) -> Supervisor:
    return Supervisor.build(tmp_path, specs, heartbeat_seconds=0.05)


# ------------------------------------------------------------------- lifecycle


def test_a_running_child_is_reported_healthy(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path, [_spec("paper", RUNNING_CHILD)])
    try:
        status = supervisor.start_all()
        assert status["state"] == SystemState.HEALTHY.value
        assert status["processes"]["paper"]["state"] == ProcessState.RUNNING.value
        assert status["processes"]["paper"]["pid"]
        assert status["processes"]["paper"]["restarts"] == 0
    finally:
        supervisor.stop_all()
    assert supervisor.status()["processes"]["paper"]["state"] == ProcessState.STOPPED.value


def test_a_crash_is_restarted_with_backoff(tmp_path: Path) -> None:
    supervisor = _supervisor(
        tmp_path, [_spec("collector", FAILING_CHILD, max_restarts=2, backoff=(0.05, 0.05, 0.05))]
    )
    try:
        supervisor.start_all()
        deadline = time.monotonic() + 15.0
        while supervisor.get("collector").restarts < 1 and time.monotonic() < deadline:
            supervisor.poll_once()
            time.sleep(0.05)
        runtime = supervisor.get("collector")
        assert runtime.restarts >= 1
        assert runtime.state in (ProcessState.RESTARTING, ProcessState.RUNNING)
    finally:
        supervisor.stop_all()


def test_a_crash_loop_is_given_up_on_rather_than_retried_forever(tmp_path: Path) -> None:
    supervisor = _supervisor(
        tmp_path,
        [_spec("paper", FAILING_CHILD, max_restarts=1, window=900.0, backoff=(0.01, 0.01))],
    )
    try:
        supervisor.start_all()
        runtime = supervisor.get("paper")
        deadline = time.monotonic() + 20.0
        while runtime.state is not ProcessState.FAILED and time.monotonic() < deadline:
            supervisor.poll_once()
            time.sleep(0.05)
        assert runtime.state is ProcessState.FAILED
        assert runtime.failure_reason and "crash loop" in runtime.failure_reason

        # A failed component is not restarted behind the operator's back.
        restarts_at_failure = runtime.restarts
        for _ in range(20):
            supervisor.poll_once()
            time.sleep(0.01)
        assert runtime.restarts == restarts_at_failure
        assert supervisor.system_state() is SystemState.FAILED
    finally:
        supervisor.stop_all()


def test_a_non_critical_failure_degrades_instead_of_failing(tmp_path: Path) -> None:
    """The strategy lab breaking must not stop PAPER (§16, §26)."""
    supervisor = _supervisor(
        tmp_path,
        [
            _spec("paper", RUNNING_CHILD, critical=True),
            _spec("strategy_lab", FAILING_CHILD, critical=False, max_restarts=0, backoff=(0.01,)),
        ],
    )
    try:
        supervisor.start_all()
        runtime = supervisor.get("strategy_lab")
        deadline = time.monotonic() + 20.0
        while runtime.state is not ProcessState.FAILED and time.monotonic() < deadline:
            supervisor.poll_once()
            time.sleep(0.05)
        assert runtime.state is ProcessState.FAILED
        assert supervisor.system_state() is SystemState.DEGRADED
        # PAPER is untouched by the other component's failure.
        assert supervisor.get("paper").state is ProcessState.RUNNING
    finally:
        supervisor.stop_all()


def test_two_critical_children_have_separate_failure_domains(tmp_path: Path) -> None:
    """§26 — collector death cannot take PAPER down, and vice versa."""
    supervisor = _supervisor(
        tmp_path,
        [
            _spec("paper", RUNNING_CHILD),
            _spec("collector", FAILING_CHILD, max_restarts=10, backoff=(0.01,)),
        ],
    )
    try:
        supervisor.start_all()
        deadline = time.monotonic() + 15.0
        collector = supervisor.get("collector")
        while collector.restarts < 3 and time.monotonic() < deadline:
            supervisor.poll_once()
            time.sleep(0.05)
        assert collector.restarts >= 3
        paper = supervisor.get("paper")
        assert paper.state is ProcessState.RUNNING
        assert paper.restarts == 0
        assert paper.pid is not None
    finally:
        supervisor.stop_all()


def test_a_clean_one_shot_completion_is_not_a_crash(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path, [_spec("retention", ONESHOT_CHILD, critical=False)])
    try:
        supervisor.start_all()
        runtime = supervisor.get("retention")
        deadline = time.monotonic() + 15.0
        events: list[dict[str, object]] = []
        while runtime.state is ProcessState.RUNNING and time.monotonic() < deadline:
            events.extend(supervisor.poll_once())
            time.sleep(0.05)
        assert runtime.state is ProcessState.STOPPED
        assert runtime.restarts == 0
        assert any(event["event"] == "COMPLETED" for event in events)
    finally:
        supervisor.stop_all()


def test_restart_on_exit_false_means_started_once(tmp_path: Path) -> None:
    supervisor = _supervisor(
        tmp_path,
        [_spec("one_shot", ONESHOT_CHILD, restart_on_exit=False, critical=False)],
    )
    try:
        supervisor.start_all()
        runtime = supervisor.get("one_shot")
        deadline = time.monotonic() + 15.0
        while runtime.state is ProcessState.RUNNING and time.monotonic() < deadline:
            supervisor.poll_once()
            time.sleep(0.05)
        assert runtime.state is ProcessState.STOPPED
        assert runtime.restarts == 0
    finally:
        supervisor.stop_all()


# -------------------------------------------------------------------- heartbeat


def test_the_system_heartbeat_combines_children_disk_and_memory(tmp_path: Path) -> None:
    child_heartbeat = tmp_path / "heartbeat.json"
    child_heartbeat.write_text(json.dumps({"cycles_completed": 7}), encoding="utf-8")
    supervisor = Supervisor.build(
        tmp_path,
        [_spec("paper", RUNNING_CHILD)],
        heartbeat_seconds=0.05,
        child_heartbeats={"paper": child_heartbeat},
    )
    try:
        supervisor.start_all()
        path = supervisor.write_heartbeat()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["state"] == SystemState.HEALTHY.value
        assert payload["disk_free_bytes"] > 0
        assert "memory_mb" in payload
        assert payload["children"]["paper"]["cycles_completed"] == 7
        assert payload["processes"]["paper"]["state"] == ProcessState.RUNNING.value
    finally:
        supervisor.stop_all()
        payload = json.loads(supervisor.write_heartbeat().read_text(encoding="utf-8"))
        assert payload["state"] == SystemState.DEGRADED.value  # stopped, so not healthy


def test_an_unreadable_child_heartbeat_does_not_break_the_supervisor(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    supervisor = Supervisor.build(
        tmp_path, [_spec("paper", RUNNING_CHILD)], child_heartbeats={"paper": missing}
    )
    try:
        supervisor.start_all()
        payload = json.loads(supervisor.write_heartbeat().read_text(encoding="utf-8"))
        assert payload["children"]["paper"] is None
    finally:
        supervisor.stop_all()


def test_supervise_forever_stops_when_asked_and_flushes(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path, [_spec("paper", RUNNING_CHILD)])
    supervisor.start_all()
    ticks = {"n": 0}

    def stop_requested() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 2

    final = supervisor.supervise_forever(stop_requested=stop_requested)
    assert final["processes"]["paper"]["state"] == ProcessState.STOPPED.value
    assert supervisor.heartbeat_path.exists()


def test_supervise_forever_honours_a_time_budget(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path, [_spec("paper", RUNNING_CHILD)])
    supervisor.start_all()
    started = time.monotonic()
    supervisor.supervise_forever(stop_requested=lambda: False, max_seconds=0.2)
    assert time.monotonic() - started < 10.0
    assert supervisor.get("paper").state is ProcessState.STOPPED


def test_duplicate_process_names_are_refused(tmp_path: Path) -> None:
    try:
        Supervisor.build(tmp_path, [_spec("paper", RUNNING_CHILD), _spec("paper", RUNNING_CHILD)])
    except ValueError as error:
        assert "duplicate process names" in str(error)
    else:  # pragma: no cover - the guard must fire
        raise AssertionError("duplicate names were accepted")


def test_a_supervisor_with_nothing_to_run_is_refused(tmp_path: Path) -> None:
    try:
        Supervisor.build(tmp_path, [])
    except ValueError as error:
        assert "supervises nothing" in str(error)
    else:  # pragma: no cover
        raise AssertionError("an empty supervisor was accepted")


def test_disk_free_bytes_is_a_real_measurement() -> None:
    assert disk_free_bytes(Path.cwd()) > 0


# ------------------------------------------------------------ graceful stop (§51)


def test_stop_all_asks_before_it_kills(tmp_path: Path) -> None:
    """The child must be given the chance to seal and finalise, not killed."""
    stop_file = tmp_path / "STOP"
    sealed = tmp_path / "sealed.txt"
    spec = _spec("collector", GRACEFUL_CHILD, args=(str(stop_file), str(sealed)), stop_file=stop_file)
    supervisor = _supervisor(tmp_path, [spec])
    supervisor.start_all()
    assert not sealed.exists()

    supervisor.stop_all(grace_seconds=15.0)

    runtime = supervisor.get("collector")
    assert sealed.exists(), "the child was killed before it could finalise"
    assert runtime.exit_code == 0
    assert runtime.state is ProcessState.STOPPED
    assert stop_file.exists()


def test_a_child_that_ignores_the_stop_file_is_terminated(tmp_path: Path) -> None:
    """Asking first must not mean waiting forever."""
    stop_file = tmp_path / "STOP"
    spec = _spec("paper", DEAF_CHILD, args=(), stop_file=stop_file)
    supervisor = _supervisor(tmp_path, [spec])
    supervisor.start_all()
    started = time.monotonic()

    supervisor.stop_all(grace_seconds=0.5, timeout=5.0)

    runtime = supervisor.get("paper")
    assert time.monotonic() - started < 20.0
    assert not runtime.is_alive
    assert runtime.state is ProcessState.STOPPED
    assert runtime.exit_code != 0


def test_a_stale_stop_file_cannot_stop_a_fresh_start(tmp_path: Path) -> None:
    """Restarting with the same run id must not inherit the last stop."""
    stop_file = tmp_path / "STOP"
    stop_file.write_text("stop requested earlier\n", encoding="utf-8")
    spec = _spec(
        "collector", GRACEFUL_CHILD, args=(str(stop_file), str(tmp_path / "sealed.txt")), stop_file=stop_file
    )
    supervisor = _supervisor(tmp_path, [spec])
    supervisor.start_all()
    try:
        assert not stop_file.exists()
        runtime = supervisor.get("collector")
        assert runtime.state is ProcessState.RUNNING
        assert runtime.is_alive
    finally:
        supervisor.stop_all(grace_seconds=1.0)


def test_supervise_forever_applies_the_stop_grace(tmp_path: Path) -> None:
    """The bounded run stops through the same polite path as an operator stop."""
    stop_file = tmp_path / "STOP"
    sealed = tmp_path / "sealed.txt"
    spec = _spec("collector", GRACEFUL_CHILD, args=(str(stop_file), str(sealed)), stop_file=stop_file)
    supervisor = _supervisor(tmp_path, [spec])
    supervisor.start_all()

    final = supervisor.supervise_forever(
        stop_requested=lambda: False, max_seconds=0.2, stop_grace_seconds=15.0
    )

    assert sealed.exists()
    assert final["processes"]["collector"]["exit_code"] == 0
