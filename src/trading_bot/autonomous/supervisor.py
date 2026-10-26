"""Portable process supervisor for the PAPER lab (§27-§31, §47).

No Kubernetes, no Temporal, no orchestrator daemon: one process that starts
children, watches them, restarts them with backoff, and stops restarting when a
component is clearly broken rather than unlucky.

The rules that matter:

* **Isolation is the point of being a separate process.** A collector crash can
  never take PAPER down, and a PAPER crash can never take the collector down,
  because neither of them is in the other's address space and this supervisor
  restarts them independently (§26).
* **A crash loop is a diagnosis, not something to retry forever.** Restarts are
  counted inside a window; when a component exceeds its budget it is marked
  ``FAILED`` and left stopped, so the operator sees a broken component instead
  of a machine that has been quietly failing all night (§29).
* **Non-critical components degrade, they do not fail the system.** The
  retention pass and the strategy lab are maintenance: if they break, PAPER and
  the collector must keep running, and the system says ``DEGRADED``.
* **The heartbeat is combined and honest** (§30): process states, restart
  counts, disk and memory, plus whatever the children published.
* **A stop is asked for before it is imposed** (§51). On Windows a supervisor's
  ``terminate()`` is ``TerminateProcess``: the child never runs its cleanup, so
  a capture died with unsealed segments and no manifest while the PAPER loop's
  stop file was never consulted. Every child that benefits from finalising
  publishes a stop file, the supervisor writes it first and only escalates to
  ``terminate()``/``kill()`` once the grace period has passed.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

__all__ = [
    "DEFAULT_BACKOFF_SECONDS",
    "DEFAULT_CRASH_LOOP_WINDOW_SECONDS",
    "DEFAULT_DISK_THRESHOLDS",
    "DEFAULT_MAX_RESTARTS",
    "DiskLevel",
    "DiskTelemetry",
    "DiskThresholds",
    "ManagedProcess",
    "ProcessRuntime",
    "ProcessState",
    "Supervisor",
    "SystemState",
    "disk_free_bytes",
    "process_memory_mb",
]

DEFAULT_MAX_RESTARTS: Final[int] = 3
DEFAULT_CRASH_LOOP_WINDOW_SECONDS: Final[float] = 900.0
DEFAULT_BACKOFF_SECONDS: Final[tuple[float, ...]] = (5.0, 15.0, 60.0)


class ProcessState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RESTARTING = "RESTARTING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    EXITED = "EXITED"


class SystemState(StrEnum):
    """§31 — the combined verdict, derived from the children, never asserted.

    ``STOPPED`` exists because a stop that was asked for and completed cleanly is
    not a fault (D-08): after ``stop_all`` every critical child is *correctly* not
    running, and calling that ``DEGRADED`` reported a fault that never happened on
    every clean shutdown.
    """

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


def disk_free_bytes(path: Path | str = ".") -> int:
    return shutil.disk_usage(path).free


class DiskLevel(StrEnum):
    """§20 — how close the host is to not being able to write anything.

    Named levels, not a percentage: an operator needs to know *what to do*, and
    a percentage of a 238 GB volume says nothing about whether the next hour of
    capture fits.
    """

    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    STOP = "STOP"


@dataclass(frozen=True, slots=True)
class DiskThresholds:
    """Configurable free-space thresholds, declared in one place and recorded."""

    warning_bytes: int = 1_500_000_000
    critical_bytes: int = 800_000_000
    stop_bytes: int = 300_000_000

    def level_for(self, free_bytes: int) -> DiskLevel:
        if free_bytes <= self.stop_bytes:
            return DiskLevel.STOP
        if free_bytes <= self.critical_bytes:
            return DiskLevel.CRITICAL
        if free_bytes <= self.warning_bytes:
            return DiskLevel.WARNING
        return DiskLevel.NORMAL

    def as_dict(self) -> dict[str, Any]:
        return {
            "warning_bytes": self.warning_bytes,
            "critical_bytes": self.critical_bytes,
            "stop_bytes": self.stop_bytes,
            "warning_gb": round(self.warning_bytes / 1e9, 3),
            "critical_gb": round(self.critical_bytes / 1e9, 3),
            "stop_gb": round(self.stop_bytes / 1e9, 3),
        }


DEFAULT_DISK_THRESHOLDS: Final[DiskThresholds] = DiskThresholds()


@dataclass(slots=True)
class DiskTelemetry:
    """§19 — free space, its trend, and how long the trend allows (§20).

    "3 % free" is not a survivable statement: the answer depends entirely on how
    fast the volume is filling. This keeps the last few free-space samples, fits
    the observed rate over them, and publishes the *hours* the operator actually
    has — which is what decides whether to start the run, and whether to leave.
    """

    thresholds: DiskThresholds = DEFAULT_DISK_THRESHOLDS
    samples: deque[tuple[float, int]] = field(default_factory=lambda: deque(maxlen=240))
    reclaimed_bytes: int = 0

    def observe(self, free_bytes: int, *, now: float | None = None) -> DiskLevel:
        stamp = time.time() if now is None else now
        previous = self.samples[-1][1] if self.samples else None
        if previous is not None and free_bytes > previous:
            self.reclaimed_bytes += free_bytes - previous
        self.samples.append((stamp, free_bytes))
        return self.level

    @property
    def free_bytes(self) -> int | None:
        return self.samples[-1][1] if self.samples else None

    @property
    def level(self) -> DiskLevel:
        free = self.free_bytes
        if free is None:
            return DiskLevel.NORMAL
        return self.thresholds.level_for(free)

    def consumption_bytes_per_hour(self) -> float | None:
        """Net bytes consumed per hour across the sample window (>= 0).

        Measured from free space rather than from the collector's own byte
        counter, because everything sharing the volume counts: a retention pass
        that stops keeping up shows up here as growth, which is the finding.
        """
        if len(self.samples) < 2:
            return None
        first_ts, first_free = self.samples[0]
        last_ts, last_free = self.samples[-1]
        hours = (last_ts - first_ts) / 3600.0
        if hours <= 0:
            return None
        return max(0.0, (first_free - last_free) / hours)

    def estimated_hours_remaining(self) -> float | None:
        rate = self.consumption_bytes_per_hour()
        free = self.free_bytes
        if rate is None or free is None or rate <= 0:
            return None
        return max(0.0, (free - self.thresholds.stop_bytes) / rate)

    def as_dict(self) -> dict[str, Any]:
        rate = self.consumption_bytes_per_hour()
        hours = self.estimated_hours_remaining()
        free = self.free_bytes
        return {
            "level": self.level.value,
            "thresholds": self.thresholds.as_dict(),
            "free_bytes": free,
            "free_gb": None if free is None else round(free / 1e9, 3),
            "consumption_bytes_per_hour": None if rate is None else round(rate, 1),
            "consumption_gb_per_day": None if rate is None else round(rate * 24 / 1e9, 3),
            "estimated_hours_remaining": None if hours is None else round(hours, 2),
            "reclaimed_bytes": self.reclaimed_bytes,
            "samples": len(self.samples),
            "measured_from": "free space on the run volume, net of retention",
        }


#: Memory reporting already has exactly one implementation, in the forward
#: resources module, and its contract is "best effort, ``None`` means the
#: platform withheld it". Re-exported rather than reimplemented: two answers to
#: "how much memory is this using" would eventually disagree.
from trading_bot.research.forward.resources import (  # noqa: E402
    process_memory_mb,
)


@dataclass(frozen=True, slots=True)
class ManagedProcess:
    """One supervised child. ``critical`` decides what its death means."""

    name: str
    command: list[str]
    cwd: Path
    critical: bool = True
    max_restarts: int = DEFAULT_MAX_RESTARTS
    crash_loop_window_seconds: float = DEFAULT_CRASH_LOOP_WINDOW_SECONDS
    backoff_seconds: tuple[float, ...] = DEFAULT_BACKOFF_SECONDS
    env: dict[str, str] = field(default_factory=dict)
    #: A process the supervisor starts once and does not restart (maintenance).
    restart_on_exit: bool = True
    #: The file this child watches to stop *itself*: seal its segments, write its
    #: manifest, flush its state, exit 0. ``None`` means the child has no cleanup
    #: to run and will be terminated directly.
    stop_file: Path | None = None
    #: §2 — the exit code this child uses to say "I failed" rather than "I was
    #: stopped". Any non-zero code is a failure; this names the one the documented
    #: contract uses, so reports can quote it instead of guessing.
    failure_exit_code: int = 1
    #: §22 — whether this child is stopped when the host runs out of disk. The
    #: capture is (its data is what fills the volume); PAPER is not (its market
    #: data is authoritative and it owes nothing to the research volume).
    stop_on_storage_guard: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": list(self.command),
            "cwd": str(self.cwd),
            "critical": self.critical,
            "max_restarts": self.max_restarts,
            "restart_on_exit": self.restart_on_exit,
            "stop_file": str(self.stop_file) if self.stop_file is not None else None,
            "stop_on_storage_guard": self.stop_on_storage_guard,
            "failure_exit_code": self.failure_exit_code,
        }


@dataclass(slots=True)
class ProcessRuntime:
    spec: ManagedProcess
    state: ProcessState = ProcessState.PENDING
    pid: int | None = None
    started_at_ms: int | None = None
    ended_at_ms: int | None = None
    exit_code: int | None = None
    #: §2/§3 — set when the supervisor had to overrule this child at stop time.
    forced_stop: bool = False
    restart_times: list[float] = field(default_factory=list)
    next_restart_at: float | None = None
    failure_reason: str | None = None
    _process: subprocess.Popen[bytes] | None = None

    # -- lifecycle ---------------------------------------------------------

    @property
    def restarts(self) -> int:
        return len(self.restart_times)

    @property
    def uptime_seconds(self) -> float:
        if self.started_at_ms is None or self.state is not ProcessState.RUNNING:
            return 0.0
        return max(0.0, (int(time.time() * 1000) - self.started_at_ms) / 1000.0)

    def start(self, log_path: Path, *, restart: bool = False) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # A stop file left behind by a previous run of the same run id would stop
        # this child the moment it started, so it is cleared before it is spawned.
        self.clear_stop_file()
        env = {**os.environ, **self.spec.env}
        handle = log_path.open("ab")
        self._process = subprocess.Popen(
            self.spec.command,
            cwd=str(self.spec.cwd),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        self.pid = self._process.pid
        self.started_at_ms = int(time.time() * 1000)
        self.ended_at_ms = None
        self.exit_code = None
        self.state = ProcessState.RUNNING
        self.failure_reason = None
        self.next_restart_at = None
        if restart:
            self.restart_times.append(time.time())

    def poll(self) -> bool:
        """Return True when the process has just been observed to exit."""
        if self._process is None or self.state is not ProcessState.RUNNING:
            return False
        code = self._process.poll()
        if code is None:
            return False
        self.exit_code = code
        self.ended_at_ms = int(time.time() * 1000)
        self.state = ProcessState.EXITED
        return True

    def pre_check(self) -> bool:
        """True when this process must wait for its backoff before a restart."""
        return self.next_restart_at is not None and time.time() < self.next_restart_at

    def crash_looped(self, now: float | None = None) -> bool:
        """More restarts than the budget inside the window is a crash loop."""
        now = time.time() if now is None else now
        recent = [
            stamp
            for stamp in self.restart_times
            if now - stamp <= self.spec.crash_loop_window_seconds
        ]
        return len(recent) > self.spec.max_restarts

    def schedule_restart(self, now: float | None = None) -> float:
        """Backoff for the next attempt, saturating at the declared maximum."""
        now = time.time() if now is None else now
        index = min(self.restarts, len(self.spec.backoff_seconds) - 1)
        delay = self.spec.backoff_seconds[max(0, index)]
        self.next_restart_at = now + delay
        self.state = ProcessState.RESTARTING
        return delay

    def request_graceful_stop(self) -> Path | None:
        """Ask the child to finalise itself by writing the file it polls.

        Returns the file that was written, or ``None`` when the child has no
        cooperative stop. This is phase one of ``Supervisor.stop_all``: the same
        operator gesture (a STOP file) works for every child, on every platform.
        """
        stop_file = self.spec.stop_file
        if stop_file is None:
            return None
        stop_file.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        stop_file.write_text(f"stop requested at {stamp}\n", encoding="utf-8")
        return stop_file

    def clear_stop_file(self) -> None:
        """Remove our own stop file so a restart is not stopped by its past."""
        if self.spec.stop_file is not None:
            self.spec.stop_file.unlink(missing_ok=True)

    def wait_for_exit(self, timeout: float) -> bool:
        """True when the child exited on its own inside ``timeout`` seconds."""
        process = self._process
        if process is None:
            return True
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        except (OSError, ValueError):  # pragma: no cover - handle already gone
            return False
        return True

    @property
    def is_alive(self) -> bool:
        """Whether the child process is still running, without changing state."""
        process = self._process
        return process is not None and process.poll() is None

    def stop(
        self, *, timeout: float = 10.0, hard: bool = False, escalated: bool = False
    ) -> None:
        """End this child, and say whether we had to overrule it.

        ``escalated`` means the child was asked to stop and did not finalise in
        time. That is a finding, not a detail: the artifacts it was supposed to
        seal may be incomplete, so the child is reported FAILED rather than
        quietly recorded as stopped.
        """
        process = self._process
        if process is not None and process.poll() is None:
            if not hard:
                with contextlib.suppress(OSError, ValueError):
                    process.terminate()
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:  # pragma: no cover - slow child
                    hard = True
            if hard:
                with contextlib.suppress(OSError, ValueError):
                    process.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=timeout)
        self.exit_code = process.poll() if process is not None else None
        self.ended_at_ms = int(time.time() * 1000)
        self.pid = None
        if escalated:
            self.forced_stop = True
            self.state = ProcessState.FAILED
            self.failure_reason = (
                "did not finalise after being asked to stop; the supervisor had to "
                "terminate it, so its artifacts may be incomplete"
            )
            return
        if self.state is not ProcessState.FAILED:
            self.state = ProcessState.STOPPED

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.spec.name,
            "critical": self.spec.critical,
            "state": self.state.value,
            "pid": self.pid,
            "uptime_seconds": round(self.uptime_seconds, 3),
            "restarts": self.restarts,
            "restart_times": [round(stamp, 3) for stamp in self.restart_times],
            "exit_code": self.exit_code,
            "failure_reason": self.failure_reason,
            "forced_stop": self.forced_stop,
            "failure_exit_code": self.spec.failure_exit_code,
            "command": list(self.spec.command),
        }


@dataclass(slots=True)
class Supervisor:
    """Runs the declared children and derives one combined status from them."""

    run_dir: Path
    processes: list[ProcessRuntime]
    heartbeat_seconds: float = 30.0
    #: Files whose content is folded into the heartbeat, verbatim.
    child_heartbeats: dict[str, Path] = field(default_factory=dict)
    started_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    #: §19/§20 — free space, its trend, and the levels that decide what to do.
    disk: DiskTelemetry = field(default_factory=DiskTelemetry)
    #: §3 — what the last stop actually did, once a stop has happened.
    last_stop_report: dict[str, Any] | None = None
    #: §22 — children already asked to stop because the volume is nearly full.
    storage_stopped: set[str] = field(default_factory=set)
    #: Heartbeats that could not be written. Reported rather than raised: the
    #: supervisor's own evidence must never be the thing that kills it.
    heartbeat_write_failures: int = 0

    # -- construction ------------------------------------------------------

    @classmethod
    def build(
        cls,
        run_dir: Path | str,
        specs: list[ManagedProcess],
        *,
        heartbeat_seconds: float = 30.0,
        child_heartbeats: dict[str, Path] | None = None,
        disk_thresholds: DiskThresholds | None = None,
    ) -> Supervisor:
        names = [spec.name for spec in specs]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate process names in supervisor: {names}")
        if not specs:
            raise ValueError("a supervisor with no processes supervises nothing")
        return cls(
            run_dir=Path(run_dir),
            processes=[ProcessRuntime(spec=spec) for spec in specs],
            heartbeat_seconds=heartbeat_seconds,
            child_heartbeats=dict(child_heartbeats or {}),
            disk=DiskTelemetry(thresholds=disk_thresholds or DEFAULT_DISK_THRESHOLDS),
        )

    # -- paths -------------------------------------------------------------

    @property
    def log_dir(self) -> Path:
        return self.run_dir / "logs"

    @property
    def heartbeat_path(self) -> Path:
        return self.run_dir / "SYSTEM_HEARTBEAT.json"

    def log_path(self, name: str) -> Path:
        return self.log_dir / f"{name}.log"

    def get(self, name: str) -> ProcessRuntime:
        for runtime in self.processes:
            if runtime.spec.name == name:
                return runtime
        raise KeyError(f"no supervised process named {name!r}")

    # -- lifecycle ---------------------------------------------------------

    def start_all(self) -> dict[str, Any]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        for runtime in self.processes:
            runtime.start(self.log_path(runtime.spec.name))
        return self.status()

    def stop_all(self, *, timeout: float = 10.0, grace_seconds: float = 0.0) -> dict[str, Any]:
        """Stop every child by asking first and insisting only if it must.

        Phase 1 writes the stop file of every child that has one. Phase 2 waits
        out the grace period for those children to seal their segments, write
        their manifest and flush their state. Phase 3 escalates to
        ``terminate()`` and, if the child still refuses, ``kill()``.

        Skipping phase 1 is what left a stopped discovery capture with partial
        tails and no manifest: on Windows ``terminate()`` is a hard kill, so the
        collector never reached ``finalise()``.
        """
        requested = {
            runtime.spec.name: runtime.request_graceful_stop() for runtime in self.processes
        }
        asked = [runtime for runtime in self.processes if requested[runtime.spec.name] is not None]
        asked_names = {runtime.spec.name for runtime in asked}
        if asked and grace_seconds > 0:
            deadline = time.monotonic() + grace_seconds
            while time.monotonic() < deadline:
                if all(not runtime.is_alive for runtime in asked):
                    break
                time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
        escalated: list[str] = []
        for runtime in self.processes:
            name = runtime.spec.name
            overruled = name in asked_names and runtime.is_alive
            if overruled:
                escalated.append(name)
            runtime.stop(timeout=timeout, escalated=overruled)
        failed = [
            runtime.spec.name
            for runtime in self.processes
            if runtime.spec.name not in escalated and (runtime.exit_code or 0) != 0
        ]
        self.last_stop_report = {
            "schema_version": "lab-stop-report-v1",
            "at_ms": int(time.time() * 1000),
            "asked_to_finalise": sorted(asked_names),
            "escalated": sorted(escalated),
            "failed_children": sorted(failed),
            "exit_codes": {
                runtime.spec.name: runtime.exit_code for runtime in self.processes
            },
            "verdict": "CLEAN" if not escalated and not failed else "FAILED",
            "note": (
                "a child that exits non-zero, or that has to be killed because it "
                "did not finalise, is a failure even though it was stopped on "
                "purpose (§2, §57)"
            ),
        }
        return self.status()

    def poll_once(self, *, now: float | None = None) -> list[dict[str, Any]]:
        """One supervision pass: detect exits, restart or fail. Never raises."""
        now = time.time() if now is None else now
        events: list[dict[str, Any]] = []
        for runtime in self.processes:
            if runtime.state is ProcessState.FAILED:
                continue
            if runtime.poll():
                events.append(
                    {
                        "event": "EXIT",
                        "process": runtime.spec.name,
                        "exit_code": runtime.exit_code,
                        "critical": runtime.spec.critical,
                        # §3 — an exit code is the child's own verdict, and it is
                        # reported verbatim: 0 completed, anything else failed.
                        "outcome": "COMPLETED" if runtime.exit_code == 0 else "FAILED",
                    }
                )
                if runtime.spec.name in self.storage_stopped:
                    # §22 — we asked for this stop because the volume was full;
                    # restarting into a full disk is not supervision, it is a loop.
                    if runtime.exit_code == 0:
                        runtime.state = ProcessState.STOPPED
                        events.append(
                            {
                                "event": "STORAGE_GUARD_COMPLETED",
                                "process": runtime.spec.name,
                                "exit_code": 0,
                            }
                        )
                    else:
                        runtime.state = ProcessState.FAILED
                        runtime.failure_reason = (
                            "storage-guard stop did not complete cleanly "
                            f"(exit {runtime.exit_code}); not restarted while the "
                            "volume is below the STOP threshold"
                        )
                        events.append(
                            {
                                "event": "STORAGE_GUARD_FAILED",
                                "process": runtime.spec.name,
                                "exit_code": runtime.exit_code,
                            }
                        )
                    continue
                if not runtime.spec.restart_on_exit:
                    runtime.state = ProcessState.STOPPED
                    continue
                if runtime.exit_code == 0:
                    # A clean exit is a completion, not a crash: restart it only
                    # when the process is meant to be long-lived, and say so.
                    runtime.state = ProcessState.STOPPED
                    events.append(
                        {"event": "COMPLETED", "process": runtime.spec.name, "exit_code": 0}
                    )
                    continue
                if runtime.crash_looped(now):
                    runtime.state = ProcessState.FAILED
                    runtime.failure_reason = (
                        f"crash loop: {runtime.restarts} restarts inside "
                        f"{runtime.spec.crash_loop_window_seconds:.0f}s "
                        f"(budget {runtime.spec.max_restarts})"
                    )
                    events.append(
                        {
                            "event": "CRASH_LOOP",
                            "process": runtime.spec.name,
                            "reason": runtime.failure_reason,
                        }
                    )
                    continue
                delay = runtime.schedule_restart(now)
                events.append(
                    {
                        "event": "RESTART_SCHEDULED",
                        "process": runtime.spec.name,
                        "delay_seconds": delay,
                        "restart_number": runtime.restarts + 1,
                    }
                )
            elif runtime.state is ProcessState.RESTARTING and not runtime.pre_check():
                runtime.start(self.log_path(runtime.spec.name), restart=True)
                events.append({"event": "RESTARTED", "process": runtime.spec.name})
        return events

    # -- status ------------------------------------------------------------

    def system_state(self) -> SystemState:
        critical_failed = [
            runtime for runtime in self.processes if runtime.spec.critical
            and runtime.state is ProcessState.FAILED
        ]
        if critical_failed:
            return SystemState.FAILED
        # D-08 — a completed stop is a state, not degradation. The verdict has to
        # come from the stop report, so a stop that had to escalate stays FAILED
        # and nothing is papered over; only a CLEAN stop retires the DEGRADED
        # reading that the stopped children would otherwise produce.
        if self.last_stop_report is not None:
            if self.last_stop_report.get("verdict") == "FAILED":
                return SystemState.FAILED
            if not any(runtime.is_alive for runtime in self.processes):
                return SystemState.STOPPED
        critical_not_running = [
            runtime
            for runtime in self.processes
            if runtime.spec.critical and runtime.state is not ProcessState.RUNNING
        ]
        if critical_not_running:
            return SystemState.DEGRADED
        degraded_signals = [
            runtime.spec.name
            for runtime in self.processes
            if runtime.restarts > 0
            or (not runtime.spec.critical and runtime.state is not ProcessState.RUNNING)
        ]
        return SystemState.DEGRADED if degraded_signals else SystemState.HEALTHY

    def read_child_heartbeat(self, path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def status(self) -> dict[str, Any]:
        state = self.system_state()
        children = {name: self.read_child_heartbeat(path) for name, path in self.child_heartbeats.items()}
        free = disk_free_bytes(self.run_dir if self.run_dir.exists() else ".")
        self.disk.observe(free)
        payload: dict[str, Any] = {
            "schema_version": "system-heartbeat-v1",
            "timestamp_ms": int(time.time() * 1000),
            # Who wrote this heartbeat: a restart has to be able to wait for the
            # previous supervisor to finish writing its report instead of racing
            # it (D-09).
            "supervisor_pid": os.getpid(),
            "uptime_seconds": round((time.time() - self.started_at_ms / 1000), 3),
            "state": state.value,
            "processes": {runtime.spec.name: runtime.to_dict() for runtime in self.processes},
            "degraded": state is SystemState.DEGRADED,
            "disk_free_bytes": free,
            # §19 — free space alone is not a survivable statement: the rate and
            # the hours it buys are what an operator can act on.
            "disk": self.disk.as_dict(),
            "memory_mb": process_memory_mb(),
            "children": children,
            "heartbeat_write_failures": self.heartbeat_write_failures,
            "storage_guard_stopped": sorted(self.storage_stopped),
        }
        if self.last_stop_report is not None:
            payload["stop_report"] = self.last_stop_report
        return payload

    def write_heartbeat(self) -> Path | None:
        """Publish the heartbeat, and survive not being able to.

        A full volume used to take the supervisor down with an ``OSError`` from
        this very write, taking away the last process that could have noticed
        anything. The heartbeat failing is a finding; the supervisor dying because
        of it is a second, worse one.
        """
        payload = self.status()
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.heartbeat_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            os.replace(tmp, self.heartbeat_path)
        except OSError as exc:
            self.heartbeat_write_failures += 1
            with contextlib.suppress(OSError):
                self.heartbeat_path.with_suffix(".json.tmp").unlink(missing_ok=True)
            print(
                f"[supervisor] heartbeat write failed ({self.heartbeat_write_failures}): "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return None
        return self.heartbeat_path

    def request_storage_guard(self) -> list[str]:
        """§22 — stop what fills the volume, keep what does not.

        The collector is asked to stop *gracefully* (so it seals and writes its
        manifest), PAPER is left alone, and the maintenance worker is left running
        because reclaiming space is exactly what is needed now. Returns the names
        that were asked this pass, so the caller can report it once.
        """
        asked: list[str] = []
        for runtime in self.processes:
            name = runtime.spec.name
            if not runtime.spec.stop_on_storage_guard or name in self.storage_stopped:
                continue
            if runtime.state is not ProcessState.RUNNING:
                continue
            if runtime.spec.stop_file is None:
                continue
            runtime.request_graceful_stop()
            self.storage_stopped.add(name)
            asked.append(name)
        return asked

    def supervise_forever(
        self,
        *,
        stop_requested: Any,
        on_event: Any = None,
        max_seconds: float | None = None,
        stop_grace_seconds: float = 0.0,
        storage_guard: bool = True,
    ) -> dict[str, Any]:
        """Poll the children until ``stop_requested()`` says otherwise.

        ``max_seconds`` exists for the bounded integrated run: the supervisor
        stops itself the same way it stops for an operator, so the shutdown path
        under test is the shutdown path in production.

        Nothing in this loop is allowed to raise: a supervisor that dies of its
        own heartbeat (or of a callback that prints an event badly) removes the
        only process that could have restarted anything.
        """
        deadline = None if max_seconds is None else time.monotonic() + max_seconds
        next_heartbeat = 0.0
        while True:
            if stop_requested():
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
            events: list[dict[str, Any]] = []
            try:
                events = self.poll_once()
            except Exception as exc:  # pragma: no cover - defensive
                print(f"[supervisor] poll failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            if storage_guard:
                # The level is read from a live measurement, not from the last
                # heartbeat: the guard must not wait a heartbeat to notice.
                self.disk.observe(disk_free_bytes(self.run_dir if self.run_dir.exists() else "."))
            if storage_guard and self.disk.level is DiskLevel.STOP:
                guarded = self.request_storage_guard()
                if guarded:
                    events.append(
                        {
                            "event": "STORAGE_GUARD_STOP",
                            "processes": guarded,
                            "free_bytes": self.disk.free_bytes,
                            "note": (
                                "the volume is below the STOP threshold; the capture was "
                                "asked to stop gracefully and PAPER was not touched"
                            ),
                        }
                    )
            for event in events:
                if on_event is not None:
                    with contextlib.suppress(Exception):
                        on_event(event)
            now = time.monotonic()
            if now >= next_heartbeat:
                self.write_heartbeat()
                next_heartbeat = now + self.heartbeat_seconds
            time.sleep(min(1.0, self.heartbeat_seconds))
        self.stop_all(grace_seconds=stop_grace_seconds)
        self.write_heartbeat()
        return self.status()
