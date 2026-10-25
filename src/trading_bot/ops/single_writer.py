"""ops.single_writer — one writer per file, and a lock that outlives its owner safely.

The append-only artefacts in this repository (``STREAM.jsonl``, ``cycles/*/ledger.jsonl``,
``market-1m/<SYMBOL>.jsonl``) are single-writer: two processes appending the same hash chain
would interleave ``prev_sha256`` and the chain would (correctly) stop verifying. The original
guard was ``O_CREAT | O_EXCL`` plus ``unlink`` on exit, and it has one failure mode that a
sustained PAPER loop cannot live with: **a killed process leaves the lock file behind and
nothing can ever take it again.** Measured on this host: ``Stop-Process -Force`` mid-session
left ``STREAM.jsonl.lock`` and one lock per symbol, and the next run could not start.

That is the obvious half. The subtle half is that "delete the lock" is not recovery: it is a
guess about who owns it, and the guess is wrong in two cases that this module refuses to make:

* **A live owner.** A stale-looking stamp is not evidence of death. Liveness is asked first
  and a running owner is never dispossessed, however old its mtime.
* **A recycled PID.** "pid 4242 no longer exists" is safe; "pid 4242 exists" is not the same
  claim as "pid 4242 is the process that wrote this lock". So the record carries the owner's
  **process start time**, and a live pid whose start time differs is a *different* process:
  the original owner is gone and the lock is abandoned. Without that column, a crash plus a
  busy host wedges the file forever behind an unrelated process that happens to hold the pid.

Recovery is therefore *proved*, never assumed:

``ABSENT``       nobody holds it;
``HELD``         a live owner with the same (pid, start time) — refuse, always;
``ABANDONED``    the owner is proved gone (dead pid, or pid reused by a later process);
``UNATTRIBUTED`` the record cannot name an owner on this host (empty, torn, foreign host) —
                 refuse and say so; deleting a lock we cannot attribute could corrupt a
                 writer that is still running, and that is worse than a manual step.

Taking over an abandoned lock is atomic: the decision is serialised by an arbiter file, the
owner record is re-verified *inside* the arbiter, and the new record is installed with
``os.replace``. A crash at any point leaves either the old record or the new one, never a
missing lock that a third process could read as free. A crashed arbiter is itself reclaimed
by the same proof: its recorded owner must be dead, or (for a torn arbiter) it must be older
than a short grace.

Finally, ownership is **fenced**. Every acquisition increments a monotonic counter kept in
``<lock>.fence``, and the record carries a per-acquisition token. ``assert_held()`` re-reads
the record before every protected write, so a writer that lost its lock (paused, partitioned,
or dispossessed after a crash) cannot keep appending: it raises ``LockLost`` instead. The old
process's in-memory token cannot match a record written after its own, so it fails closed.

Scope note: this guard is for locks on one host. A lock whose owner is on another host is
``UNATTRIBUTED`` — a distributed lease needs a fencing token the storage layer enforces, and
pretending a local pid probe answers for a remote machine is exactly the guess this module
refuses. See ``research/campaign_lock.py`` for the campaign lease, which adds renewal.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

__all__ = [
    "ARBITER_STALE_SECONDS",
    "ARBITER_UNATTRIBUTED_GRACE_SECONDS",
    "ARBITER_WAIT_SECONDS",
    "FENCE_SUFFIX",
    "SCHEMA_VERSION",
    "LockLost",
    "LockRefused",
    "SingleWriter",
    "diagnose_lock",
    "pid_alive",
    "process_start_ms",
    "reclaim_abandoned",
]

SCHEMA_VERSION = "TAP_SINGLE_WRITER_LOCK_V1"
ARBITER_SUFFIX = ".claim"
FENCE_SUFFIX = ".fence"
#: How long a contended process waits for the decision arbiter before refusing, and how old
#: a torn arbiter must be before it is broken. Both are bounded: refusing is always allowed.
ARBITER_WAIT_SECONDS = 5.0
ARBITER_STALE_SECONDS = 30.0
ARBITER_UNATTRIBUTED_GRACE_SECONDS = 5.0
ARBITER_POLL_SECONDS = 0.02

ABSENT = "ABSENT"
HELD = "HELD"
ABANDONED = "ABANDONED"
UNATTRIBUTED = "UNATTRIBUTED"


# --------------------------------------------------------------------- identity


def process_start_ms(pid: int) -> int | None:
    """When the process that owns ``pid`` started, in Unix milliseconds.

    This is the column that separates "the owner is still there" from "a later process
    reused its pid". ``None`` means the platform could not say, which callers must treat as
    *unknown* rather than as *same*: an unknown start time never justifies a takeover.
    """

    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if os.name == "nt":
        return _windows_start_ms(pid)
    return _posix_start_ms(pid)


def _windows_start_ms(pid: int) -> int | None:  # pragma: no cover - exercised on Windows
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    #: 1601-01-01 → 1970-01-01 in milliseconds; ``FILETIME`` counts 100 ns ticks from 1601.
    EPOCH_OFFSET_MS = 11_644_473_600_000

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    created = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    try:
        ok = kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
    finally:
        kernel32.CloseHandle(handle)
    if not ok:
        return None
    ticks = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
    if ticks <= 0:
        return None
    return ticks // 10_000 - EPOCH_OFFSET_MS


def _posix_start_ms(pid: int) -> int | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        # ``comm`` may contain spaces and parentheses, so the fields after it are found from
        # the last ')'. ``starttime`` is field 22, i.e. index 19 of what follows.
        fields = raw[raw.rindex(")") + 2 :].split()
        ticks = int(fields[19])
    except (ValueError, IndexError):
        return None
    boot_s = None
    with contextlib.suppress(OSError, ValueError):
        for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
            if line.startswith("btime "):
                boot_s = int(line.split()[1])
                break
    if boot_s is None:
        return None
    #: ``os.sysconf`` does not exist on Windows, and this module is imported there.
    sysconf = getattr(os, "sysconf", None)
    try:
        hz = int(sysconf("SC_CLK_TCK")) if sysconf is not None else 100
    except (ValueError, OSError, TypeError):
        hz = 100
    return boot_s * 1000 + (ticks * 1000) // hz


def pid_alive(pid: int) -> bool:
    """Is *some* process using this pid? Asked without signalling it.

    Windows has no ``kill(pid, 0)``: ``os.kill`` there is a console-control call for ``0``
    and falls through to ``TerminateProcess`` when the caller shares no console with the
    target — a liveness probe that kills. ``OpenProcess`` with query-only rights answers the
    question and changes nothing. A denial (the process exists, we may not see it) answers
    *alive*: the failure mode must be "refuse to reclaim", never "reclaim a live writer".

    Measured on this host and fixed here: ``OpenProcess`` alone says **alive** for a process
    that has already exited while *someone else still holds a handle to it* — which is the
    normal case for a supervisor's ``Popen`` object. A crashed child would then look alive to
    its own parent and its lock could never be reclaimed. ``WaitForSingleObject(handle, 0)``
    distinguishes "running" from "exited, handle still open" and changes nothing either.
    """

    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - exercised on Windows
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        SYNCHRONIZE = 0x00100000
        WAIT_TIMEOUT = 0x102
        WAIT_OBJECT_0 = 0x00000000
        ERROR_ACCESS_DENIED = 5
        ERROR_INVALID_PARAMETER = 87

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not handle:
            error = int(ctypes.get_last_error())
            if error == ERROR_ACCESS_DENIED:
                # It exists; we are simply not allowed to look closer.
                return True
            return error != ERROR_INVALID_PARAMETER
        try:
            waited = int(kernel32.WaitForSingleObject(handle, 0))
        finally:
            kernel32.CloseHandle(handle)
        if waited == WAIT_TIMEOUT:
            return True
        #: Any other answer than "signalled" is treated as alive: fail closed.
        return waited != WAIT_OBJECT_0
    if _posix_is_zombie(pid):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _posix_is_zombie(pid: int) -> bool:
    """A zombie holds a pid but runs no code: it cannot be writing anything."""

    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    try:
        return raw[raw.rindex(")") + 2 :].split()[0] == "Z"
    except (IndexError, ValueError):
        return False


def _host() -> str:
    return socket.gethostname()


# ------------------------------------------------------------------- the record


def _normalise(raw: str) -> dict[str, Any]:
    """Read a lock file's bytes into a record, remembering how much it actually says.

    Two legacy shapes predate this module and must be recognised rather than mistaken for
    corruption: a bare integer pid (the original ``DecisionLedger`` and ``MinuteStore``
    format) and an empty file (a crash between ``O_CREAT`` and the ``write``). Both are
    handled conservatively: the pid form is usable only for a dead-pid verdict, and the
    empty form is unattributable.
    """

    text = raw.strip()
    if not text:
        return {"unattributed": True, "reason": "EMPTY"}
    #: A bare integer is valid JSON, so the legacy pid check has to come after parsing and
    #: before the "is a record" check, or the original lock format reads as corruption.
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return payload
    if text.isdigit():
        return {"legacy_pid_only": True, "pid": int(text)}
    return {"unattributed": True, "reason": "UNPARSABLE"}


def diagnose_lock(record: Mapping[str, Any] | None, *, host: str | None = None) -> dict[str, Any]:
    """State of a lock from its record alone. Pure: it never touches the filesystem.

    The order is the whole argument: attribution, then liveness, then PID reuse. An owner on
    another host is not "probably dead" — it is unanswerable here, so it is refused.
    """

    if record is None:
        return {"state": ABSENT, "reason": "NO_LOCK"}
    if record.get("unattributed"):
        return {"state": UNATTRIBUTED, "reason": str(record.get("reason") or "UNATTRIBUTED")}
    pid = record.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return {"state": UNATTRIBUTED, "reason": "NO_OWNER_PID"}
    if not record.get("legacy_pid_only"):
        declared_host = record.get("host")
        if not declared_host:
            return {"state": UNATTRIBUTED, "reason": "NO_OWNER_HOST"}
        if str(declared_host) != (host or _host()):
            # A pid is only meaningful on the machine that wrote it. Probing a foreign one
            # would answer about an unrelated local process.
            return {
                "state": UNATTRIBUTED,
                "reason": "FOREIGN_HOST_OWNER",
                "host": str(declared_host),
            }
    if not pid_alive(pid):
        return {"state": ABANDONED, "reason": "OWNER_PROCESS_DEAD", "pid": pid}
    recorded_start = record.get("process_start_ms")
    if isinstance(recorded_start, int):
        current_start = process_start_ms(pid)
        if current_start is not None and int(current_start) != int(recorded_start):
            # The pid is alive but it is not the process that wrote this lock.
            return {
                "state": ABANDONED,
                "reason": "PID_REUSED",
                "pid": pid,
                "recorded_start_ms": int(recorded_start),
                "current_start_ms": int(current_start),
            }
    return {"state": HELD, "reason": "LIVE_OWNER", "pid": pid}


class LockRefused(RuntimeError):
    """The lock was not taken, and nothing was deleted. ``code`` names the reason."""

    def __init__(self, code: str, message: str, *, record: Mapping[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = str(code)
        self.record = dict(record) if record is not None else None


class LockLost(LockRefused):
    """This writer no longer owns the lock; its protected write must not happen."""


class SingleWriter:
    """Exclusive ownership of one artefact, with proved recovery and fencing."""

    def __init__(self, path: Path | str, *, purpose: str = "append-only file") -> None:
        self.path = Path(path)
        self.purpose = str(purpose)
        self.token = uuid.uuid4().hex
        self.fence = 0
        self.record: dict[str, Any] | None = None

    # -- paths ------------------------------------------------------------- #

    @property
    def arbiter_path(self) -> Path:
        return self.path.with_name(self.path.name + ARBITER_SUFFIX)

    @property
    def fence_path(self) -> Path:
        return self.path.with_name(self.path.name + FENCE_SUFFIX)

    # -- reading ------------------------------------------------------------ #

    def read(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return {"unattributed": True, "reason": "UNREADABLE"}
        return _normalise(raw)

    def _record(self, *, fence: int | None = None) -> dict[str, Any]:
        pid = os.getpid()
        return {
            "schema_version": SCHEMA_VERSION,
            "purpose": self.purpose,
            "path": self.path.name,
            "host": _host(),
            "pid": pid,
            "process_start_ms": process_start_ms(pid),
            "token": self.token,
            "fence": int(self.fence if fence is None else fence),
            "acquired_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    # -- acquiring ---------------------------------------------------------- #

    def acquire(self) -> dict[str, Any]:
        """Take the lock, or raise ``LockRefused`` with a code. Never deletes a live lock."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(3):
            candidate = self._record(fence=max(self._read_fence(), 0) + 1)
            if self._create_exclusive(candidate):
                self._write_fence(candidate["fence"])
                self.fence = int(candidate["fence"])
                self.record = candidate
                return {"status": "ACQUIRED", "reclaimed": None, **candidate}

            holder = self.read()
            verdict = diagnose_lock(holder)
            if verdict["state"] == HELD:
                raise LockRefused(
                    "LOCK_HELD",
                    f"{self.path} is held by live pid {verdict.get('pid')}; a second writer "
                    "would interleave prev_sha256 and the chain would stop verifying",
                    record=holder,
                )
            if verdict["state"] == UNATTRIBUTED:
                raise LockRefused(
                    "LOCK_UNATTRIBUTED",
                    f"{self.path} does not name an owner this host can verify "
                    f"({verdict['reason']}); not removed, because a lock we cannot attribute "
                    "could belong to a writer that is still running",
                    record=holder,
                )
            if verdict["state"] == ABSENT:
                # The holder vanished between ``exists`` and ``read``. Loop: the next attempt
                # creates the record; if somebody else won the race we see their record.
                continue
            return self._takeover(candidate, expected=holder, reason=str(verdict["reason"]))
        raise LockRefused(
            "LOCK_CONTENDED",
            f"{self.path} kept changing hands while it was being acquired; refusing rather "
            "than guessing who owns it",
        )

    def _create_exclusive(self, record: Mapping[str, Any]) -> bool:
        """Create the lock with its content already complete, or report that it exists.

        ``O_CREAT | O_EXCL`` creates an empty file and then a second call writes it: a crash
        in that window leaves an unattributable lock, which is exactly the state this module
        exists to keep out of. ``os.link`` gives exclusive creation *and* complete content in
        one atomic step. Filesystems that refuse hard links fall back to the old two steps,
        and the fallback is reported in the test suite rather than assumed.
        """

        payload = json.dumps(record, indent=2, sort_keys=True) + "\n"
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(payload, encoding="utf-8", newline="\n")
        try:
            os.link(tmp, self.path)
            return True
        except FileExistsError:
            return False
        except (OSError, NotImplementedError, AttributeError):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                return False
            try:
                os.write(fd, payload.encode())
                os.fsync(fd)
            finally:
                os.close(fd)
            return True
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()

    def _takeover(
        self,
        candidate: dict[str, Any],
        *,
        expected: Mapping[str, Any] | None,
        reason: str,
    ) -> dict[str, Any]:
        """Install a new record over an abandoned one, atomically and only once."""

        self._take_arbiter()
        try:
            current = self.read()
            verdict = diagnose_lock(current)
            if verdict["state"] != ABANDONED:
                code = (
                    "LOCK_HELD"
                    if verdict["state"] == HELD
                    else (
                        "LOCK_UNATTRIBUTED"
                        if verdict["state"] == UNATTRIBUTED
                        else "LOCK_CONTENDED"
                    )
                )
                raise LockRefused(
                    code,
                    f"{self.path} changed while the takeover was being prepared: it is now "
                    f"{verdict['state']} ({verdict['reason']}); nothing was overwritten",
                    record=current,
                )
            if _identity(current) != _identity(expected):
                raise LockRefused(
                    "LOCK_CONTENDED",
                    f"{self.path} is not the lock that was diagnosed as abandoned "
                    "(its owner record differs); nothing was overwritten",
                    record=current,
                )
            fence = self._write_fence(max(self._read_fence(), int(_fence_of(current))) + 1)
            candidate = self._record(fence=fence)
            tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.takeover")
            tmp.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            try:
                os.replace(tmp, self.path)
            finally:
                with contextlib.suppress(OSError):
                    tmp.unlink()
            self.fence = int(fence)
            self.record = candidate
            return {
                "status": "RECLAIMED",
                "reason": reason,
                "previous_owner": dict(current) if current else None,
                **candidate,
            }
        finally:
            self._drop_arbiter()

    # -- the arbiter -------------------------------------------------------- #

    def _take_arbiter(self) -> None:
        """Serialise the *decision* to take over, not the run that follows it.

        Reading a record and then replacing it is two steps; two processes could both read
        the same abandoned record and both install themselves. ``O_CREAT | O_EXCL`` closes
        that window. A crashed arbiter is reclaimed by the same proof used for the lock —
        its recorded owner must be dead — or, when it is too torn to name an owner, by a
        short grace: the arbiter lives for microseconds of work, so five seconds of no
        progress is not a slow owner, it is a dead one.
        """

        deadline = time.monotonic() + ARBITER_WAIT_SECONDS
        while True:
            try:
                fd = os.open(self.arbiter_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if self._arbiter_abandoned():
                    with contextlib.suppress(OSError):
                        self.arbiter_path.unlink()
                    continue
                if time.monotonic() >= deadline:
                    raise LockRefused(
                        "LOCK_CONTENDED",
                        f"{self.arbiter_path} is held by another process; the takeover of "
                        f"{self.path} was not decided rather than guessed",
                    ) from None
                time.sleep(ARBITER_POLL_SECONDS)
                continue
            except OSError as exc:
                raise LockRefused(
                    "LOCK_UNWRITABLE", f"{self.arbiter_path} cannot be created: {exc}"
                ) from exc
            try:
                os.write(fd, json.dumps(self._record(), sort_keys=True).encode())
                os.fsync(fd)
            finally:
                os.close(fd)
            return

    def _arbiter_abandoned(self) -> bool:
        if not self.arbiter_path.exists():
            return True
        try:
            raw = self.arbiter_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        verdict = diagnose_lock(_normalise(raw))
        if verdict["state"] == ABANDONED:
            return True
        if verdict["state"] in (ABSENT,):
            return True
        if verdict["state"] == UNATTRIBUTED:
            try:
                age = time.time() - self.arbiter_path.stat().st_mtime
            except OSError:
                return False
            return age > ARBITER_UNATTRIBUTED_GRACE_SECONDS
        return False

    def _drop_arbiter(self) -> None:
        with contextlib.suppress(OSError):
            self.arbiter_path.unlink()

    # -- the fence ---------------------------------------------------------- #

    def _read_fence(self) -> int:
        with contextlib.suppress(OSError, ValueError):
            return int(self.fence_path.read_text(encoding="utf-8").strip() or 0)
        return 0

    def _write_fence(self, value: int) -> int:
        """Publish the new fence, atomically, and return the value actually stored."""

        fence = max(int(value), self._read_fence())
        tmp = self.fence_path.with_name(
            f"{self.fence_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        tmp.write_text(f"{fence}\n", encoding="utf-8", newline="\n")
        try:
            os.replace(tmp, self.fence_path)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
        return fence

    # -- ownership ---------------------------------------------------------- #

    def assert_held(self) -> dict[str, Any]:
        """Re-read the lock before a protected write; raise ``LockLost`` if it is not ours.

        This is the fence in practice: an owner that was paused across a takeover still has
        its old token and old fence in memory, and neither matches the record on disk, so
        its next write is refused instead of silently interleaving a chain.
        """

        if self.record is None:
            raise LockLost("LOCK_LOST", f"{self.path}: this writer never acquired the lock")
        current = self.read()
        if current is None:
            raise LockLost(
                "LOCK_LOST", f"{self.path} disappeared while this writer held it; refusing to write"
            )
        if str(current.get("token") or "") != str(self.record.get("token")):
            raise LockLost(
                "LOCK_LOST",
                f"{self.path} is owned by another writer (pid {current.get('pid')}, fence "
                f"{current.get('fence')}); this writer's fence {self.record.get('fence')} is "
                "stale, so its protected writes are refused",
                record=current,
            )
        return current

    def owned(self) -> bool:
        try:
            self.assert_held()
        except LockLost:
            return False
        return True

    def release(self) -> bool:
        """Remove the lock only if it is still ours.

        A compare-then-unlink has a residual window in which another process could take a
        proved-abandoned lock between the read and the unlink. The fence closes the
        consequence: if that happened, our own ``assert_held`` fails and no protected write
        happens. Deleting a lock we no longer own would be the worse error, so the token is
        re-checked immediately before the unlink and the result is reported honestly.
        """

        if self.record is None:
            return False
        current = self.read()
        if current is None or str(current.get("token") or "") != str(self.record.get("token")):
            self.record = None
            return False
        with contextlib.suppress(OSError):
            self.path.unlink()
        self.record = None
        return True


def _identity(record: Mapping[str, Any] | None) -> tuple[Any, ...]:
    """What makes a record *that* record, for compare-and-take-over."""

    if record is None:
        return (None,)
    if record.get("legacy_pid_only"):
        return ("legacy", record.get("pid"))
    return (record.get("token"), record.get("pid"), record.get("fence"))


def _fence_of(record: Mapping[str, Any] | None) -> int:
    if not record:
        return 0
    value = record.get("fence")
    return int(value) if isinstance(value, int) else 0


def reclaim_abandoned(path: Path | str, *, purpose: str = "recovery") -> dict[str, Any] | None:
    """Take over and release a lock whose owner is proved gone. Returns the evidence.

    ``None`` means there was nothing to reclaim. ``LockRefused`` means the lock is held or
    cannot be attributed: the caller must abort with that code, not delete the file.
    """

    lock = SingleWriter(path, purpose=purpose)
    holder = lock.read()
    if holder is None:
        return None
    verdict = diagnose_lock(holder)
    if verdict["state"] == HELD:
        raise LockRefused(
            "LOCK_HELD",
            f"{path} is held by live pid {verdict.get('pid')}",
            record=holder,
        )
    if verdict["state"] != ABANDONED:
        raise LockRefused(
            "LOCK_UNATTRIBUTED",
            f"{path} does not name an owner this host can verify ({verdict['reason']})",
            record=holder,
        )
    result = lock.acquire()
    released = lock.release()
    return {
        "lock": Path(path).name,
        "pid": holder.get("pid"),
        "reason": verdict["reason"],
        "state": "ABANDONED",
        "fence": result.get("fence"),
        "process_start_ms": holder.get("process_start_ms"),
        "released": bool(released),
    }
