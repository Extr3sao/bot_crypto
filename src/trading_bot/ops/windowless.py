"""Start child processes without a console window, and keep their evidence.

Why this module exists
----------------------

On Windows a *console-subsystem* executable started by a process that has no
console — the Electron shell of the IDE, a ``pythonw.exe`` scheduled task, a GUI
launcher — is given a brand-new console, and a new console is a visible window.
The automation this repository runs is exactly that shape: a task scheduler
starts an interpreter once every fifteen minutes, that interpreter starts a
collector, and each of those children can flash a black window on the operator's
desktop. The window is not cosmetic: it steals focus, and on a machine that is
being left alone it is the difference between "this runs quietly" and "this
cannot be left running".

The fix is one flag and one structure, applied in one place:

* ``CREATE_NO_WINDOW`` tells ``CreateProcess`` to give the child a console that
  has no window at all;
* ``STARTUPINFO`` with ``STARTF_USESHOWWINDOW`` and ``wShowWindow = SW_HIDE``
  covers the child that looks at its own startup information before it draws
  anything.

Both are applied by :func:`spawn` and :func:`run`; nothing in this repository
should call ``subprocess.Popen`` for an automated child.

What is preserved, deliberately
-------------------------------

A window is only worth suppressing if nothing else is lost, so every launch
keeps: the command line, the working directory, the environment, stdout and
stderr (captured or redirected to a file), the PID, the exit code, the wall
time, and a JSONL record of all of it. A timeout and a cancellation end the
child **and its descendants** — and only those: the process handle is the proof
of ownership, so a recycled PID or a process we did not start is never a target.

Nothing here touches risk, orders or the paper broker: this module starts
processes and writes execution records, and that is the whole of its authority.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Sequence
from typing import IO, Any, Final

__all__ = [
    "CREATE_NEW_CONSOLE",
    "CREATE_NEW_PROCESS_GROUP",
    "CREATE_NO_WINDOW",
    "EXIT_CANCELLED",
    "EXIT_SPAWN_ERROR",
    "EXIT_TIMEOUT",
    "OPT_OUT_ENV",
    "SCHEMA_VERSION",
    "ExecutionLog",
    "creation_flags",
    "enabled",
    "job_object_kill_on_close",
    "open_log",
    "pid_alive",
    "popen_kwargs",
    "process_alive",
    "pythonw_executable",
    "record_exit",
    "run",
    "spawn",
    "startupinfo",
    "terminate_tree",
    "wait",
]

SCHEMA_VERSION: Final[str] = "execution-record-v1"

#: ``subprocess`` only defines these on Windows; the names are declared here so
#: the rest of the repository can import them on any platform.
CREATE_NO_WINDOW: Final[int] = 0x08000000
CREATE_NEW_CONSOLE: Final[int] = 0x00000010
CREATE_NEW_PROCESS_GROUP: Final[int] = 0x00000200

#: Set to ``0`` to keep the flags off (debugging a child that needs a console).
OPT_OUT_ENV: Final[str] = "TAP_WINDOWLESS"

EXIT_TIMEOUT: Final[int] = 124
EXIT_SPAWN_ERROR: Final[int] = 127
EXIT_CANCELLED: Final[int] = 130

IS_WINDOWS: Final[bool] = os.name == "nt"


def enabled() -> bool:
    """Whether window suppression is on. On by default; opt-out is explicit."""
    return os.environ.get(OPT_OUT_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


def startupinfo() -> subprocess.STARTUPINFO | None:
    """``STARTUPINFO`` that asks the child to show its first window hidden."""
    if not IS_WINDOWS or not enabled():
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return info


def creation_flags(*, new_group: bool = False) -> int:
    """Creation flags for a child that must not own a visible console."""
    flags = 0
    if IS_WINDOWS and enabled():
        flags |= CREATE_NO_WINDOW
    if IS_WINDOWS and new_group:
        flags |= CREATE_NEW_PROCESS_GROUP
    return flags


def popen_kwargs(*, new_group: bool = False) -> dict[str, Any]:
    """The platform arguments every spawn in this repository must carry."""
    if IS_WINDOWS:
        return {"creationflags": creation_flags(new_group=new_group), "startupinfo": startupinfo()}
    # POSIX has no console to hide; a new session is what lets a timeout end the
    # whole tree with ``killpg`` instead of just the direct child.
    return {"start_new_session": True}


def pythonw_executable() -> str:
    """The GUI-subsystem sibling of the running interpreter.

    A scheduled task that runs ``python.exe`` under an interactive principal owns
    a console for its whole lifetime. ``pythonw.exe`` does not, and its children
    are started with :func:`spawn`, so neither the task nor its children can draw
    a window. When there is no sibling (a non-Windows host, or an embedded
    interpreter), the running executable is returned unchanged.
    """
    if not IS_WINDOWS:
        return sys.executable
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return str(candidate) if candidate.exists() else sys.executable


def open_log(path: Path | str) -> IO[bytes]:
    """Open an append-only child log, creating its directory."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target.open("ab")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(slots=True)
class ExecutionLog:
    """Append-only JSONL of what was started, from where, and how it ended.

    A failure to write the log must never fail the work it describes: automation
    that dies because its evidence file is on a full disk is worse than one whose
    evidence says ``write_failures > 0``. The count is kept so the omission is
    visible instead of silent.
    """

    path: Path
    write_failures: int = 0
    last_error: str | None = None
    _warned: bool = field(default=False, repr=False)

    def record(self, event: str, **fields: Any) -> dict[str, Any]:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "event": event,
            "at_utc": _utc_now(),
            **fields,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            self.write_failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            if not self._warned:
                self._warned = True
                print(
                    f"[windowless] execution log unavailable ({self.path}): {self.last_error}",
                    file=sys.stderr,
                )
        return payload


def _command_list(command: str | os.PathLike[str] | Sequence[str]) -> list[str]:
    if isinstance(command, (str, os.PathLike)):
        return [os.fspath(command)]
    return [os.fspath(part) for part in command]


def spawn(
    command: str | os.PathLike[str] | Sequence[str],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    stdout: IO[Any] | int | None = None,
    stderr: IO[Any] | int | None = subprocess.STDOUT,
    stdin: IO[Any] | int | None = subprocess.DEVNULL,
    text: bool = False,
    event_log: ExecutionLog | None = None,
    label: str | None = None,
    new_group: bool = False,
) -> subprocess.Popen[Any]:
    """Start a child windowless. This is the only spawn automation should use."""
    argv = _command_list(command)
    started = time.monotonic()
    process = subprocess.Popen(
        argv,
        cwd=None if cwd is None else str(cwd),
        env=env,
        stdout=stdout,
        stderr=stderr,
        stdin=stdin,
        text=text,
        **popen_kwargs(new_group=new_group),
    )
    if event_log is not None:
        event_log.record(
            "spawn",
            label=label,
            pid=process.pid,
            command=argv,
            cwd=None if cwd is None else str(cwd),
            started_at_monotonic=round(started, 6),
            windowless=enabled() and IS_WINDOWS,
        )
    return process


def record_exit(
    process: subprocess.Popen[Any],
    *,
    event_log: ExecutionLog | None,
    label: str | None = None,
    duration_seconds: float | None = None,
    timed_out: bool = False,
    cancelled: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write the matching ``exit`` record. The PID is the one we were given."""
    if event_log is None:
        return
    argv = process.args if isinstance(process.args, (list, tuple)) else [str(process.args)]
    event_log.record(
        "exit",
        label=label,
        pid=process.pid,
        command=[os.fspath(part) for part in argv],
        exit_code=process.returncode,
        duration_seconds=None if duration_seconds is None else round(duration_seconds, 3),
        timed_out=timed_out,
        cancelled=cancelled,
        **(extra or {}),
    )


def wait(process: subprocess.Popen[Any], *, timeout: float | None = None) -> int | None:
    """Wait for a child, ending its tree if the wait expires.

    ``subprocess.wait(timeout=...)`` leaves grandchildren behind; a capture that
    spawns a writer would keep writing after its parent was declared timed out.
    """
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_tree(process)
        raise


def pid_alive(pid: int) -> bool:
    """Whether a PID is running, without assuming permission to signal it."""
    if pid <= 0:
        return False
    if IS_WINDOWS:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        try:
            # WAIT_TIMEOUT means the process is still running.
            return bool(kernel32.WaitForSingleObject(handle, 0) == 0x00000102)
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - exists but is not ours
        return True
    return True


#: Alias kept because both spellings read naturally at the call site.
process_alive = pid_alive


def terminate_tree(
    process: subprocess.Popen[Any],
    *,
    timeout: float = 10.0,
    hard: bool = True,
) -> int | None:
    """End one child and its descendants; never anything else.

    The ``Popen`` handle is the ownership proof: while ``poll()`` is ``None`` the
    PID still belongs to the process we started, so ``taskkill /PID <pid> /T``
    cannot reach a recycled PID, and ``/T`` cannot leave a writer behind. On
    POSIX the child was started in its own session, so ``killpg`` has the same
    scope.
    """
    if process.poll() is not None:
        return process.returncode
    if IS_WINDOWS:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
                creationflags=creation_flags(),
                startupinfo=startupinfo(),
            )
    else:
        # Typeshed is platform-specific: ``killpg`` only exists on POSIX, so the
        # names are resolved at runtime rather than promised to the type checker.
        killpg = getattr(os, "killpg", None)
        getpgid = getattr(os, "getpgid", None)
        if killpg is not None and getpgid is not None:
            with contextlib.suppress(OSError, ProcessLookupError):
                killpg(getpgid(process.pid), int(getattr(signal, "SIGKILL" if hard else "SIGTERM")))
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError, ValueError):
            process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            return process.wait(timeout=timeout)
        return None


def run(
    command: str | os.PathLike[str] | Sequence[str],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    input: str | bytes | None = None,
    text: bool = False,
    check: bool = False,
    event_log: ExecutionLog | None = None,
    label: str | None = None,
) -> subprocess.CompletedProcess[Any]:
    """Run a child to completion, windowless, keeping both streams and its PID.

    On timeout the child *and its descendants* are ended before
    ``TimeoutExpired`` is raised, and the record says ``timed_out: true`` with the
    PID that was actually used.
    """
    argv = _command_list(command)
    started = time.monotonic()
    process = spawn(
        argv,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        text=text,
        event_log=event_log,
        label=label,
    )
    try:
        stdout, stderr = process.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_tree(process)
        stdout, stderr = process.communicate()
        record_exit(
            process,
            event_log=event_log,
            label=label,
            duration_seconds=time.monotonic() - started,
            timed_out=True,
        )
        raise subprocess.TimeoutExpired(
            argv, 0.0 if timeout is None else timeout, output=stdout, stderr=stderr
        ) from None
    record_exit(
        process,
        event_log=event_log,
        label=label,
        duration_seconds=time.monotonic() - started,
    )
    completed: subprocess.CompletedProcess[Any] = subprocess.CompletedProcess(
        args=argv,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
    )
    if check and completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode, argv, output=stdout, stderr=stderr
        )
    return completed


def job_object_kill_on_close(process: subprocess.Popen[Any]) -> int | None:
    """Tie a child's lifetime to this process, on Windows, without a window.

    A scheduled task that is stopped — or a launcher that crashes — otherwise
    leaves its child running with nobody watching it. A job object with
    ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` ends exactly the processes assigned to
    it when the last handle closes, which is a scope Windows enforces and a
    ``taskkill`` by name cannot.

    The returned handle must stay open for as long as the child should live; a
    caller that drops it has, by design, killed the child at close. ``None`` on a
    platform without job objects, or when the assignment was refused.
    """
    if not IS_WINDOWS:
        return None
    import ctypes
    from ctypes import wintypes

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.windll.kernel32
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
    configured = kernel32.SetInformationJobObject(
        job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
    )  # AssignProcessToJobObject requires PROCESS_SET_QUOTA and PROCESS_TERMINATE.
    process_handle = kernel32.OpenProcess(0x0100 | 0x0001, False, process.pid)
    assigned = bool(process_handle) and bool(kernel32.AssignProcessToJobObject(job, process_handle))
    if process_handle:
        kernel32.CloseHandle(process_handle)
    if not configured or not assigned:
        kernel32.CloseHandle(job)
        return None
    return int(job)


def new_run_id() -> str:
    """A short identifier for a launch whose own name cannot collide."""
    return f"{int(time.time() * 1000):x}-{uuid.uuid4().hex[:8]}"
