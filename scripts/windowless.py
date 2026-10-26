"""Run a command without a console window, keeping what it printed and returned.

    pythonw.exe scripts/windowless.py --log logs/job.log -- python.exe script.py

This is the process the Windows Task Scheduler should start, and the one a
``.cmd`` wrapper should call when it is invoked by automation rather than by a
human. ``pythonw.exe`` is a GUI-subsystem binary: it never owns a console, so the
task itself cannot draw a window. The real command is started by
:mod:`trading_bot.ops.windowless` with ``CREATE_NO_WINDOW`` and a
``STARTUPINFO`` that hides the first window, so the child cannot draw one either.

Everything the command did is kept:

* stdout and stderr go to ``--log`` (append-only, both streams, unbuffered);
* the command, PID, working directory, start time, exit code, duration and
  whether it timed out go to ``--event-log`` as JSONL;
* the child's exit code becomes this launcher's exit code, unchanged — a
  wrapper that hides a failure is worse than a window.

A timeout, ``Ctrl-C`` or the launcher being stopped ends the child **and its
descendants** (a job object on Windows, a process group on POSIX) and nothing
else: the process handle is the only thing targeted.

Exit codes: the child's own, ``124`` on timeout, ``127`` when the command could
not be started, ``130`` when the launcher was asked to stop.
"""

from __future__ import annotations

import argparse
import contextlib
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import FrameType

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.ops import windowless  # noqa: E402


def _write(path: Path, text: str) -> None:
    """Best-effort message for a launcher that may have no stdout at all."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(text.rstrip("\n") + "\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path, help="stdout+stderr, append-only")
    parser.add_argument("--event-log", type=Path, default=None, help="JSONL launch/exit records")
    parser.add_argument(
        "--timeout", type=float, default=None, help="seconds before the tree is ended"
    )
    parser.add_argument("--cwd", type=Path, default=REPO)
    parser.add_argument("--label", default=None)
    parser.add_argument(
        "--keep-together", action="store_true", help="kill the child if this launcher dies"
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")

    events = windowless.ExecutionLog(args.event_log) if args.event_log else None
    label = args.label or Path(command[0]).name
    log = args.log

    def stop(signum: int, _frame: FrameType | None) -> None:
        raise KeyboardInterrupt(f"signal {signum}")

    for name in ("SIGINT", "SIGTERM"):
        with_ = getattr(signal, name, None)
        if with_ is not None:
            with contextlib.suppress(OSError, ValueError):  # pragma: no cover - not main thread
                signal.signal(with_, stop)

    started = time.monotonic()
    try:
        handle = windowless.open_log(log)
    except OSError as exc:
        _write(log, f"[windowless] cannot open the log: {type(exc).__name__}: {exc}")
        if events:
            events.record("spawn_error", label=label, command=command, error=str(exc))
        return windowless.EXIT_SPAWN_ERROR

    job: int | None = None
    try:
        process = windowless.spawn(
            command,
            cwd=args.cwd,
            stdout=handle,
            stderr=subprocess.STDOUT,
            event_log=events,
            label=label,
        )
    except OSError as exc:
        handle.close()
        _write(log, f"[windowless] cannot start {command[0]}: {type(exc).__name__}: {exc}")
        if events:
            events.record(
                "spawn_error", label=label, command=command, error=f"{type(exc).__name__}: {exc}"
            )
        return windowless.EXIT_SPAWN_ERROR

    if args.keep_together:
        job = windowless.job_object_kill_on_close(process)

    cancelled = False
    timed_out = False
    try:
        process.wait(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        windowless.terminate_tree(process)
    except KeyboardInterrupt:
        cancelled = True
        windowless.terminate_tree(process)
    finally:
        handle.close()

    windowless.record_exit(
        process,
        event_log=events,
        label=label,
        duration_seconds=time.monotonic() - started,
        timed_out=timed_out,
        cancelled=cancelled,
        extra={"log": str(log), "job_object": bool(job)},
    )
    if job is not None:
        # Releasing the last job handle is what ends anything the child left
        # behind; it is scoped to this launch by construction.
        try:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(job)
        except (OSError, AttributeError):  # pragma: no cover - platform dependent
            pass

    if timed_out:
        _write(log, f"[windowless] TIMEOUT after {args.timeout}s: {label}")
        return windowless.EXIT_TIMEOUT
    if cancelled:
        _write(log, f"[windowless] CANCELLED: {label}")
        return windowless.EXIT_CANCELLED
    return int(process.returncode if process.returncode is not None else 1)


if __name__ == "__main__":
    raise SystemExit(main())
