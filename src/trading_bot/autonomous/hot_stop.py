"""Hot activation of the kill switch for a process that is already running.

G-2.  Rule 0 (MT-0003) blocks an order while the switch is engaged, but until
this module the only way to engage it was an environment variable read at
import: an operator who needs the stop *now* had to kill the process, which
also drops the book and the evidence of the run.

Two layers, both fail-closed, neither arguable by a proposal, a risk verdict,
an agent or an LLM:

1. ``engage`` activates the process-wide ``KillSwitch``, so every later
   ``DecisionEngine.intend``/``decide`` returns NO_TRADE through rule 0;
2. ``order_boundary`` re-checks at the last point before the broker call, so a
   future regression that bypasses the decision engine still cannot send.

**Persistence (G-1).** The marker is the authority across process boundaries.
``__post_init__`` adopts it, so a restart over the same run directory is
engaged before the constructor returns and therefore before any broker call can
begin. ``engage`` writes the marker itself (temp file, ``fsync``,
``os.replace``), which makes an in-process activation durable and makes a crash
between the write and the ACK harmless: the next boot restores it.

**Scope, stated rather than implied.** The marker lives in ``run_dir``. A
restart that reuses the run id is blocked. A new run id — or a different run
root — is a new directory and boots operational; see ``docs/audit/G-1.md`` §4.6.
No global latch is written: it could not be cleared without a disarm path,
which this design deliberately does not have.

**Linearization.** ``order_boundary`` holds the same lock as ``engage`` for the
whole broker call. ``engage`` therefore cannot return its ACK while a dispatch
is in flight, and no dispatch can begin after that ACK. This is deliberately
stronger than "an order that began earlier may finish later": the ACK means
the process is quiet.

**Monotonic.** There is no disarm and no rearm inside the process. Deleting the
control file does nothing once engaged; the only way back to trading is a new
process with the existing explicit off token **and** no marker in its run
directory. The JSONL audit is evidence, never authority: nothing here reads it
to decide state.

**Channel.** The project already has a file-based operator channel (``STOP`` in
the run directory, see ``paper_loop.StopController``). This module adds
``KILL_SWITCH`` next to it rather than inventing an unauthenticated socket or
an HTTP control endpoint.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from trading_bot.domain.enums.kill_switch import KillSwitchAction, KillSwitchState

#: Control file, relative to the run directory. Presence is the request.
HOT_STOP_FILE_NAME: Final[str] = "KILL_SWITCH"

#: Audit trail of every transition, next to the control file.
AUDIT_FILE_NAME: Final[str] = "kill_switch_events.jsonl"

#: The path this gate protects. Recorded in each event so a reader can tell
#: which boundary the claim covers — and, by omission, which ones it does not.
BOUNDARY: Final[str] = "autonomous.runtime._execute_paper -> broker.execute_signal"


@dataclass(frozen=True, slots=True)
class EngageAck:
    """What the *process* answers once the stop is in force.

    Not to be confused with the CLI's ``{"status": "REQUESTED"}``: this object
    is produced inside the running loop, after the lock proved no dispatch is in
    flight. ``persisted`` says the marker is on disk (or was already there); a
    ``False`` is a stop that a restart would not inherit, reported rather than
    hidden. ``restored`` says this engagement came from a previous process.
    """

    run_id: str
    previous_state: str
    new_state: str
    activated_at_ms: int
    actor: str
    reason: str
    commit: str
    version: str
    boundary: str
    repeated: bool
    audited: bool
    lock_timeout: bool
    activation_error: str | None
    orders_blocked: int
    persisted: bool = False
    restored: bool = False

    @property
    def event(self) -> str:
        if self.repeated:
            return "already_engaged"
        return "restored" if self.restored else "engaged"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "run_id": self.run_id,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "activated_at_ms": self.activated_at_ms,
            "actor": self.actor,
            "reason": self.reason,
            "commit": self.commit,
            "version": self.version,
            "boundary": self.boundary,
            "repeated": self.repeated,
            "audited": self.audited,
            "lock_timeout": self.lock_timeout,
            "activation_error": self.activation_error,
            "orders_blocked": self.orders_blocked,
            "persisted": self.persisted,
            "restored": self.restored,
        }


@dataclass
class HotStopGate:
    """Engage-only safety gate shared by the loop and the broker boundary.

    ``kill_switch`` is duck-typed (``state``, ``is_active``, ``activate``) so a
    test can inject the authority it drives; production passes
    ``process_kill_switch()``.
    """

    kill_switch: Any
    run_dir: Path | str
    run_id: str = ""
    commit: str = ""
    version: str = ""
    boundary_timeout_seconds: float = 30.0
    control_path: Path | None = None
    audit_path: Path | None = None
    now_ms: Any = None
    _engaged: bool = field(default=False, init=False, repr=False)
    _reason: str = field(default="", init=False, repr=False)
    _actor: str = field(default="", init=False, repr=False)
    _engaged_at_ms: int | None = field(default=None, init=False, repr=False)
    _orders_blocked: int = field(default=0, init=False, repr=False)
    _broker_calls: int = field(default=0, init=False, repr=False)
    _lock_timeouts: int = field(default=0, init=False, repr=False)
    _restored: bool = field(default=False, init=False, repr=False)
    _lock: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir)
        if self.control_path is None:
            self.control_path = self.run_dir / HOT_STOP_FILE_NAME
        if self.audit_path is None:
            self.audit_path = self.run_dir / AUDIT_FILE_NAME
        if self.now_ms is None:
            self.now_ms = _now_ms
        if not self.version:
            # The deployment may not know its commit; it always knows its build.
            from trading_bot import __version__

            self.version = __version__
        # A real lock, not a dummy: the linearization argument in the module
        # docstring is the whole point of this class.
        self._lock = threading.Lock()
        # G-1 — adopt a stop written by an earlier process. This runs in the
        # constructor on purpose: every construction path (the runtime, a
        # script, a future entrypoint) then starts closed without a second
        # wiring site to forget. Nothing can dispatch before the constructor
        # returns.
        self.restore()

    # -- state ------------------------------------------------------------

    @property
    def engaged(self) -> bool:
        return self._engaged

    @property
    def engaged_reason(self) -> str:
        return self._reason

    def stats(self) -> dict[str, Any]:
        return {
            "engaged": self._engaged,
            "reason": self._reason,
            "actor": self._actor,
            "engaged_at_ms": self._engaged_at_ms,
            "orders_blocked": self._orders_blocked,
            "broker_calls_allowed": self._broker_calls,
            "lock_timeouts": self._lock_timeouts,
            "restored": self._restored,
            "control_path": str(self.control_path),
            "boundary": BOUNDARY,
        }

    # -- persistence ------------------------------------------------------

    def restore(self, *, run_id: str = "") -> bool:
        """Adopt a stop persisted by an earlier process. Returns engaged.

        Called from ``__post_init__``, so a restart cannot reach a broker call
        before the marker is honoured. Fail closed: only a *proven absence*
        leaves the gate open; a path that exists but cannot be inspected, or an
        ``lstat`` that raises anything else, engages.
        """
        if self._engaged:
            return True
        try:
            present = self._marker_presence()
        except OSError as exc:
            self._restored = True
            self.engage(
                f"control_file_unreadable:{type(exc).__name__}",
                actor=f"boot_restore:{self.control_path}",
                run_id=run_id,
            )
            return True
        if not present:
            return False
        detail, read_error = self._read_marker()
        self._restored = True
        self.engage(
            read_error or detail or f"persisted stop:{HOT_STOP_FILE_NAME}",
            actor=f"boot_restore:{self.control_path}",
            run_id=run_id,
        )
        return True

    def _marker_presence(self) -> bool:
        """True if the marker entry exists, False only on a proven absence.

        ``Path.exists()`` is not used here: it swallows several ``OSError``s
        and reports a dangling symlink as absent, which would turn a corrupt
        control path into permission to trade.
        """
        path = self.control_path
        assert path is not None  # set in __post_init__ before restore()
        try:
            os.lstat(path)
        except FileNotFoundError:
            return False
        return True

    def _read_marker(self) -> tuple[str, str | None]:
        """Return ``(reason, error)``. An unreadable marker is still a stop.

        The error is returned rather than swallowed so the audit names *why* the
        reason is empty: "the file said nothing" and "the file could not be
        read" are different facts, and the second one is a fault.
        """
        path = self.control_path
        assert path is not None
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip(), None
        except OSError as exc:
            return "", f"control_file_unreadable:{type(exc).__name__}"

    def _ensure_marker(self) -> bool:
        """Make the current stop durable. ``False`` means "not on disk".

        An existing entry is already the authority (even an unreadable one), so
        it is never rewritten; that keeps a restore from touching the file it
        just read.
        """
        try:
            if self._marker_presence():
                return True
        except OSError:
            return False
        path = self.control_path
        assert path is not None  # set in __post_init__
        try:
            write_control_file(path, self._reason)
        except OSError:
            return False
        return True

    # -- activation -------------------------------------------------------

    def engage(self, reason: str = "", *, actor: str = "operator", run_id: str = "") -> EngageAck:
        """Engage, idempotently, and answer only when the process is quiet.

        Order of operations is deliberate: ``_engaged`` is set **before** the
        underlying switch is touched, so an exception from ``activate`` cannot
        leave a window where the gate believes it is open.
        """
        acquired = self._lock.acquire(timeout=max(0.0, float(self.boundary_timeout_seconds)))
        if not acquired:  # pragma: no cover - requires a wedged broker
            # A dispatch is stuck holding the lock. Engage anyway: the stop is
            # never allowed to wait on the thing it is stopping.
            self._lock_timeouts += 1
            self._engaged = True
            self._reason = reason or "lock_timeout"
            self._actor = actor
            self._engaged_at_ms = int(self.now_ms())
            previous, activation_error = self._activate_switch(reason)
            return self._ack(
                run_id=run_id,
                previous=previous,
                repeated=False,
                lock_timeout=True,
                activation_error=activation_error,
                persisted=self._ensure_marker(),
            )
        try:
            if self._engaged:
                # Not a new transition: re-assert the switch in case something
                # reset it behind our back, and record that nothing changed.
                previous, activation_error = self._activate_switch(self._reason)
                return self._ack(
                    run_id=run_id,
                    previous=previous,
                    repeated=True,
                    lock_timeout=False,
                    activation_error=activation_error,
                    persisted=self._ensure_marker(),
                )
            self._engaged = True
            self._reason = reason or "hot engage"
            self._actor = actor
            self._engaged_at_ms = int(self.now_ms())
            previous, activation_error = self._activate_switch(self._reason)
            return self._ack(
                run_id=run_id,
                previous=previous,
                repeated=False,
                lock_timeout=False,
                activation_error=activation_error,
                persisted=self._ensure_marker(),
            )
        finally:
            self._lock.release()

    def poll(self, *, run_id: str = "") -> bool:
        """Honour the control file. Returns the engaged flag.

        Fail closed: an unreadable control path engages. Absence of the file is
        the only answer that leaves the gate open, and it can never *open* an
        already engaged gate.
        """
        if self._engaged:
            return True
        path = self.control_path
        assert path is not None  # set in __post_init__
        try:
            if not self._marker_presence():
                return False
        except OSError as exc:
            self.engage(
                f"control_file_unreadable:{type(exc).__name__}",
                actor=f"control_file:{path}",
                run_id=run_id,
            )
            return True
        detail, read_error = self._read_marker()
        self.engage(
            read_error or detail or f"control file present:{path.name}",
            actor=f"control_file:{path}",
            run_id=run_id,
        )
        return True

    # -- the boundary -----------------------------------------------------

    @contextmanager
    def order_boundary(self, *, run_id: str = "") -> Iterator[bool]:
        """Yield ``True`` if the caller may dispatch, holding the lock meanwhile.

        The caller must perform the broker call inside the ``with`` block: the
        lock is what makes ``engage``'s ACK mean "nothing is in flight".
        """
        if not self._engaged:
            try:
                self.poll(run_id=run_id)
            except Exception as exc:  # a broken poll must never authorise
                self.engage(f"poll_error:{type(exc).__name__}", actor="gate", run_id=run_id)
        if self._engaged:
            self._orders_blocked += 1
            yield False
            return
        acquired = self._lock.acquire(timeout=max(0.0, float(self.boundary_timeout_seconds)))
        if not acquired:
            self._lock_timeouts += 1
            self._orders_blocked += 1
            yield False
            return
        try:
            if self._engaged:  # re-check under the lock: engage could have won
                self._orders_blocked += 1
                yield False
                return
            self._broker_calls += 1
            yield True
        finally:
            self._lock.release()

    # -- internals --------------------------------------------------------

    def _ack(
        self,
        *,
        run_id: str,
        previous: str,
        repeated: bool,
        lock_timeout: bool,
        activation_error: str | None,
        persisted: bool,
    ) -> EngageAck:
        audited = self._write_audit(
            self._event_payload(
                run_id=run_id,
                previous=previous,
                repeated=repeated,
                lock_timeout=lock_timeout,
                activation_error=activation_error,
                persisted=persisted,
            )
        )
        return EngageAck(
            run_id=run_id or self.run_id,
            previous_state=previous,
            new_state=self._state_name(),
            activated_at_ms=int(self._engaged_at_ms or self.now_ms()),
            actor=self._actor,
            reason=self._reason,
            commit=self.commit,
            version=self.version,
            boundary=BOUNDARY,
            repeated=repeated,
            audited=audited,
            lock_timeout=lock_timeout,
            activation_error=activation_error,
            orders_blocked=self._orders_blocked,
            persisted=persisted,
            restored=self._restored,
        )

    def _activate_switch(self, reason: str) -> tuple[str, str | None]:
        previous = self._state_name()
        try:
            self.kill_switch.activate(
                KillSwitchAction.USER,
                target=KillSwitchState.HALTED,
                reason=reason or "hot engage",
            )
        except Exception as exc:  # the gate is already closed; report the fault
            return previous, f"{type(exc).__name__}: {exc}"
        return previous, None

    def _state_name(self) -> str:
        try:
            state = self.kill_switch.state
        except Exception:
            return "UNREADABLE"
        return str(getattr(state, "value", state))

    def _event_payload(
        self,
        *,
        run_id: str,
        previous: str,
        repeated: bool,
        lock_timeout: bool,
        activation_error: str | None,
        persisted: bool,
    ) -> dict[str, Any]:
        return {
            "event": (
                "already_engaged" if repeated else ("restored" if self._restored else "engaged")
            ),
            "run_id": run_id or self.run_id,
            "previous_state": previous,
            "new_state": self._state_name(),
            "activated_at_ms": self._engaged_at_ms,
            "actor": self._actor,
            "reason": self._reason,
            "commit": self.commit,
            "version": self.version,
            "boundary": BOUNDARY,
            "repeated": repeated,
            "lock_timeout": lock_timeout,
            "activation_error": activation_error,
            "orders_blocked": self._orders_blocked,
            "broker_calls_allowed": self._broker_calls,
            "persisted": persisted,
            "restored": self._restored,
        }

    def _write_audit(self, payload: dict[str, Any]) -> bool:
        """Append one line and fsync it. ``False`` means "no evidence"."""
        path = self.audit_path
        assert path is not None
        line = json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n"
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            return False
        return True


def write_control_file(path: Path | str, reason: str) -> None:
    """Write the stop marker atomically and durably. Raises ``OSError``.

    Order is what makes a crash safe: the bytes reach the file **before** the
    rename exposes it, so a reader either sees the previous state or the whole
    new marker, never a half-written one. The directory ``fsync`` publishes the
    rename where the platform allows it; on Windows the directory handle cannot
    be opened without a privileged flag, so it is skipped — the rename is still
    atomic, but this contract does not claim power-loss durability there.
    """
    target = Path(path)
    directory = target.parent
    payload = (reason.strip() or "operator requested hot engage") + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=target.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        with suppress(OSError):
            tmp.unlink()
        raise
    _fsync_directory(directory)


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":  # no portable directory handle; the rename is atomic
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _now_ms() -> int:
    return int(time.time() * 1000)


__all__ = [
    "AUDIT_FILE_NAME",
    "BOUNDARY",
    "HOT_STOP_FILE_NAME",
    "EngageAck",
    "HotStopGate",
    "write_control_file",
]
