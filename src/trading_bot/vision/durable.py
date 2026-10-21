"""durable — the vision lane's book on disk, so a crash cannot erase exposure.

Before this module the lane's book lived only in the object graph: ``VisionLane`` built a
``PaperBroker`` in memory, published ``open_positions_at_end`` at ``RUN_END``, and threw
the object away. A process that died with two shorts open started again **flat**: the
positions disappeared, their stops were never evaluated again, and the equity they had
already cost (the entry commission) silently came back. That is the defect this module
closes, and it is closed the way the autonomous runtime already closes it
(``paper/paper_state_store.py`` + ``paper/reconciliation_v4.py``): an atomic JSON
document, a single writer, and a reconciler that fails closed instead of guessing.

The contract, stated once:

**The book is the economic truth.** The ledger is an append-only *projection* of one
session; the durable book is what the account is. A ``CLOSE`` row that is not in the
book's ``closed_trades`` never happened, and a position in the book is exposure whether
or not any ledger in any directory still mentions it.

**The commit point is the end of a bar.** Every economic effect of a bar (gap exits,
entries, intrabar exits) is a pure function of the book at the bar's open, the bar data
the lane can see and the answers it already received. ``VisionLane`` therefore persists
the book **after** the close phase of each bar and records the bar as the barrier. A
crash during bar *n* leaves the book at bar *n-1*, and bar *n* is re-executed from that
book: the fill either did not happen (its effect was never committed) or happens once
(the committed book has it and the bar is behind the barrier). There is no third
possibility, which is what "no duplicate economic event" means here.

**A resumed session is not a replay.** Bars at or before the barrier are never processed
again, and no decision is formed on them: the book carries the state they produced.

**State that is not trusted is not used.** Corrections do not exist in this module:
every check either passes or the caller is told ``RECOVERED`` or ``BLOCKED`` with the
first failing check named. Restoring "as much as possible" from a half-readable book is
exactly how a paper account starts lying about its equity.

Format, in one place::

    <dir>/BOOK.json         the current book (atomic replace, digest inside)
    <dir>/BOOK.json.prev    the previous good book (one generation back)
    <dir>/BOOK.lock         single-writer lock, carries pid + host + session id
    <dir>/BOOK_EVENTS.jsonl one row per commit / recovery / block, fsynced

Not in scope: market data, sizing, strategy. This module stores and judges a book; it
never decides what the book should do.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from trading_bot.vision import failpoints
from trading_bot.vision.gap_recovery import GapAssessment

__all__ = [
    "BOOK_SCHEMA",
    "BOOK_SCHEMA_VERSION",
    "BookError",
    "CorruptBook",
    "LaneBook",
    "LaneBookStore",
    "RecoveryBlocked",
    "RecoveryReport",
    "RecoveryStatus",
    "SessionBusy",
    "SessionLock",
    "StoreRecoveryStatus",
    "book_digest",
    "closed_digest",
    "contract_from",
    "pid_alive",
    "reconcile_book",
    "state_digest",
]

#: Bumped when a field's *meaning* changes. The reader refuses a book it does not know
#: rather than defaulting the fields it is missing.
BOOK_SCHEMA = "vision-lane-book/1"
BOOK_SCHEMA_VERSION = 1

#: Equity and PnL identities are compared in USDT at this tolerance. Float addition of
#: commissions is exact to ~1e-12 at these magnitudes; 1e-6 is two orders below a cent
#: and far below the smallest commission this schedule charges.
TOLERANCE_USDT = 1e-6


class BookError(RuntimeError):
    """Base class: the book cannot be used for the reason in the message."""


class CorruptBook(BookError):
    """The bytes exist but do not parse, or do not match their own digest.

    Fail closed. A corrupt book means the exposure is unknown, and starting flat over an
    unknown book is the defect this module exists to prevent.
    """


class SessionBusy(BookError):
    """Another live process owns this book."""


class RecoveryBlocked(BookError):
    """The book exists but cannot be trusted, so the session must not run.

    Carries the whole report: the caller publishes it instead of summarising it, because
    the *reason* a book was refused is the evidence a later audit needs.
    """

    def __init__(self, report: RecoveryReport) -> None:
        super().__init__(f"{report.code}: {report.detail}")
        self.report = report


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


#: Fields that name the *process* that wrote the book, not the money in it. Two runs over
#: the same bars must produce the same economic digest — otherwise the digest cannot be
#: used to prove "this restart changed nothing", and every determinism check would have to
#: normalise the lineage away by hand (and eventually forget to).
OPERATIONAL_FIELDS = frozenset(
    {
        "session_id",
        "session_index",
        "session_ids",
        "counters",
        "calls",
        "spend_usd",
        "entry_provenance",
        "marks",
    }
)


def book_digest(body: dict[str, Any]) -> str:
    """Integrity digest: the *whole* body, so any edit is visible.

    This is the one written into the file and checked on load. It answers "are these the
    bytes that were written", not "is this the same book" — a counter that moved must
    break it, or the store would quietly accept a file that was rewritten under it.
    """
    return hashlib.sha256(_canonical(body)).hexdigest()


def state_digest(body: dict[str, Any]) -> str:
    """Economic digest: the book as money, not as logging.

    Excludes session lineage and operational counters, so a restart that changed nothing
    about the account produces the *same* digest as the run it continues. That is what
    makes "the interrupted run and the continuous run agree" a single comparison instead
    of a hand-written field-by-field one.
    """
    economic = {key: value for key, value in body.items() if key not in OPERATIONAL_FIELDS}
    return hashlib.sha256(_canonical(economic)).hexdigest()


def closed_digest(rows: list[dict[str, Any]]) -> str:
    """Digest of the realised history, so a lost or rewritten close is visible."""
    return hashlib.sha256(_canonical(rows)).hexdigest()


def _now_ms() -> int:
    return int(time.time() * 1000)


# -- the book -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LaneBook:
    """One durable state of the book, with the barrier it is valid at."""

    body: dict[str, Any]
    #: Integrity digest of the whole body (what the store verifies on load).
    digest: str
    updated_at_ms: int
    #: Economic digest of the same body (what two runs are compared on).
    state_digest: str = ""

    # -- convenient, checked reads --------------------------------------------
    @property
    def book_id(self) -> str:
        return str(self.body.get("book_id", ""))

    @property
    def contract(self) -> dict[str, Any]:
        return dict(self.body.get("contract") or {})

    @property
    def barrier_ms(self) -> int | None:
        value = (self.body.get("barrier") or {}).get("bar_open_ms")
        return None if value is None else int(value)

    @property
    def open_positions(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.body.get("open_positions") or []]

    @property
    def closed_trades(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.body.get("closed_trades") or []]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": BOOK_SCHEMA,
            "schema_version": BOOK_SCHEMA_VERSION,
            "updated_at_ms": self.updated_at_ms,
            "digest": self.digest,
            "body": self.body,
        }


# -- the lock -------------------------------------------------------------------


def pid_alive(pid: int) -> bool | None:
    """``True``/``False`` when it can be known, ``None`` when it cannot.

    ``os.kill(pid, 0)`` is not portable: on Windows any signal other than CTRL_C/CTRL_BREAK
    *terminates* the process, so probing a lock holder that way would kill the very process
    the lock is protecting. The Windows path asks the OS to open the process handle
    instead, and only a `None` answer is treated as "unknown" (and therefore as held).
    """
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - exercised by the Windows runtime tests
        #: ``os.kill(pid, 0)`` no sirve aquí y es peligroso; ver el docstring de arriba.

        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            error = ctypes.get_last_error()
            # 5 = access denied: the process exists but belongs to someone else.
            return error == 5
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


@dataclass
class SessionLock:
    """Single writer for one book directory.

    The lock exists because two processes over one book is the one failure mode no amount
    of atomic writing can fix: both would read the same barrier, both would trade the same
    bar, and the second commit would erase the first. The second process is refused with
    :class:`SessionBusy`; it never merges, never waits, never takes over a live holder.
    """

    path: Path
    token: str
    _acquired: bool = False
    _log: Any = field(default=None, repr=False)

    def acquire(self, *, session_id: str, stale_after_s: float = 900.0) -> SessionLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = _canonical(
            {
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "session_id": session_id,
                "token": self.token,
                "acquired_at_ms": _now_ms(),
            }
        )
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            holder = self._read() or {}
            alive = pid_alive(int(holder.get("pid", 0) or 0))
            age_s = time.time() - self.path.stat().st_mtime
            if alive is True or (alive is None and age_s < stale_after_s):
                raise SessionBusy(
                    f"{self.path} is held by pid={holder.get('pid')} "
                    f"session={holder.get('session_id')!r} since "
                    f"{age_s:.0f}s: a second writer over one book would trade the same "
                    "bar twice"
                ) from exc
            # The holder is provably gone (or the file is older than the stale window and
            # the owner cannot be confirmed): take over, and say so in the lock itself.
            #
            # The takeover is serialised by a second lock file. Without it two starters
            # that both see the dead holder can each unlink and recreate the lock, and the
            # first one ends up writing to an orphaned inode while the second owns the
            # path: both processes would then believe they hold the book and trade the
            # same bar. Only one taker may go through, and it must confirm the file it
            # wrote is still the file on disk.
            guard = self.path.with_name(self.path.name + ".takeover")
            try:
                guard_fd = os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as busy:
                try:
                    guard_age = time.time() - guard.stat().st_mtime
                except OSError:
                    guard_age = 0.0
                if guard_age < max(1.0, min(stale_after_s, 30.0)):
                    raise SessionBusy(
                        f"{self.path}: another process is taking over the dead holder "
                        f"right now ({guard.name} is {guard_age:.0f}s old)"
                    ) from busy
                #: A taker that died mid-takeover leaves its guard behind; it is only a
                #: mutex, so an old one can be replaced deliberately.
                guard.unlink(missing_ok=True)
                guard_fd = os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                refreshed = self._read() or {}
                if refreshed.get("token") != holder.get("token"):
                    raise SessionBusy(
                        f"{self.path}: the holder changed while this process was deciding "
                        "to take over; refusing to overwrite a lock it did not inspect"
                    )
                self.path.unlink(missing_ok=True)
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, payload)
                os.fsync(fd)
                os.close(fd)
                written = self._read() or {}
                if written.get("token") != self.token:
                    raise SessionBusy(
                        f"{self.path}: the lock on disk is not the one this process "
                        "wrote; another taker won the race"
                    )
                os.write(guard_fd, b"taken\n")
                os.fsync(guard_fd)
            finally:
                os.close(guard_fd)
                with contextlib.suppress(OSError):
                    guard.unlink()
            if self._log is not None:
                self._log.warning(
                    "lane_book.lock_taken_over",
                    path=str(self.path),
                    previous_pid=holder.get("pid"),
                    age_s=round(age_s, 1),
                )
            self._acquired = True
            failpoints.trigger("lock.after_acquire", path=self.path, takeover=True)
            return self
        os.write(fd, payload)
        os.fsync(fd)
        os.close(fd)
        self._acquired = True
        failpoints.trigger("lock.after_acquire", path=self.path, takeover=False)
        return self

    def _read(self) -> dict[str, Any] | None:
        try:
            return dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None

    @property
    def acquired(self) -> bool:
        return self._acquired

    def release(self) -> None:
        if not self._acquired:
            return
        holder = self._read()
        # Only remove a lock that is still ours: a takeover by another process must not be
        # cancelled by the process it replaced.
        if holder is None or holder.get("token") == self.token:
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()
        self._acquired = False

    def __enter__(self) -> SessionLock:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


# -- the store ------------------------------------------------------------------


class LaneBookStore:
    """Atomic, digest-checked, single-generation store for one :class:`LaneBook`."""

    def __init__(self, directory: Path | str) -> None:
        self._dir = Path(directory)
        self._log = structlog.get_logger("vision_lane_book")
        #: Set when a torn event row was dropped. Reported by :meth:`recover` so a repair
        #: is always visible as one.
        self.events_repair: dict[str, Any] | None = None

    @property
    def directory(self) -> Path:
        return self._dir

    @property
    def path(self) -> Path:
        return self._dir / "BOOK.json"

    @property
    def prev_path(self) -> Path:
        return self._dir / "BOOK.json.prev"

    @property
    def events_path(self) -> Path:
        return self._dir / "BOOK_EVENTS.jsonl"

    @property
    def lock_path(self) -> Path:
        return self._dir / "BOOK.lock"

    def exists(self) -> bool:
        return self.path.exists()

    def lock(self, *, session_id: str) -> SessionLock:
        lock = SessionLock(path=self.lock_path, token=f"{os.getpid()}-{session_id}", _log=self._log)
        return lock.acquire(session_id=session_id)

    def load(self) -> LaneBook | None:
        """The stored book, or ``None`` when there is none.

        A file that does not parse, or whose body does not match its digest, raises
        :class:`CorruptBook` and is preserved byte-for-byte next to the store. Nothing is
        rotated, nothing is reset: the caller decides, and the only decision available is
        to block.
        """
        if not self.path.exists():
            #: ``.prev`` without ``BOOK.json`` is not "no book": a write was interrupted in
            #: the rotation. The exposure is unknown, so this refuses exactly like a
            #: corrupt file instead of starting flat over it.
            if self.prev_path.exists():
                raise CorruptBook(
                    f"{self.path} is missing while {self.prev_path.name} exists: a write "
                    "was interrupted between generations, so the current book cannot be "
                    "named and starting flat would forget the exposure it held"
                )
            return None
        raw = self.path.read_bytes()
        try:
            doc = json.loads(raw.decode("utf-8"))
            body = dict(doc["body"])
            digest = str(doc["digest"])
            economic = str(doc.get("state_digest") or "")
            updated_at_ms = int(doc.get("updated_at_ms", 0))
            schema = str(doc.get("schema", ""))
            version = int(doc.get("schema_version", 0))
        except Exception as exc:  # any parse failure is the same failure
            self._quarantine(raw)
            raise CorruptBook(f"{self.path} does not parse as a lane book: {exc}") from exc
        if schema != BOOK_SCHEMA or version != BOOK_SCHEMA_VERSION:
            raise CorruptBook(
                f"{self.path} declares {schema!r} v{version}; this runtime writes "
                f"{BOOK_SCHEMA!r} v{BOOK_SCHEMA_VERSION} and refuses to guess the rest"
            )
        computed = book_digest(body)
        if computed != digest:
            self._quarantine(raw)
            raise CorruptBook(
                f"{self.path} body digest {computed} does not match the recorded {digest}: "
                "the state was torn or edited after it was written"
            )
        return LaneBook(
            body=body,
            digest=digest,
            updated_at_ms=updated_at_ms,
            state_digest=economic or state_digest(body),
        )

    def _quarantine(self, raw: bytes) -> None:
        backup = self._dir / f"BOOK.corrupt.{_now_ms()}.json"
        with contextlib.suppress(OSError):
            self._dir.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(raw)
            self._log.error("lane_book.corrupt", path=str(backup))

    def save(self, body: dict[str, Any]) -> LaneBook:
        """Persist ``body`` atomically and return the sealed book.

        Order matters: fsync the new file, rotate the old one to ``.prev``, then replace.
        The window in which neither file is a complete book does not exist.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        digest = book_digest(body)
        economic = state_digest(body)
        doc: dict[str, Any] = {
            "schema": BOOK_SCHEMA,
            "schema_version": BOOK_SCHEMA_VERSION,
            "updated_at_ms": _now_ms(),
            "digest": digest,
            "state_digest": economic,
            "body": body,
        }
        payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
        closed_trades = len(body.get("closed_trades") or [])
        #: ``closed_trades`` is the context a crash matrix needs: "the write that first
        #: carries a close" is a different window from "the first write of the run".
        failpoints.trigger(
            "book.before_save", path=self._dir, closed_trades=closed_trades, barrier=body.get("barrier", {}).get("bar_open_ms")
        )
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "wb") as handle:
            handle.write(payload)
            failpoints.trigger(
                "book.after_tmp_write", path=self._dir, closed_trades=closed_trades
            )
            handle.flush()
            os.fsync(handle.fileno())
        failpoints.trigger(
            "book.after_tmp_fsync", path=self._dir, closed_trades=closed_trades
        )
        if self.path.exists():
            #: A copy, not a rename. Rotating the current book out of the way and then
            #: replacing it has a window in which ``BOOK.json`` does not exist: a crash
            #: exactly there left only ``BOOK.json.prev`` and the next process read "no
            #: book" and started flat over open exposure. Copying first keeps a complete
            #: book at ``BOOK.json`` for the whole write, and the copy is fsynced so the
            #: fallback generation is durable too.
            self._copy_previous()
            failpoints.trigger(
                "book.after_prev_copy", path=self._dir, closed_trades=closed_trades
            )
        os.replace(tmp, self.path)
        failpoints.trigger("book.after_replace", path=self._dir, closed_trades=closed_trades)
        self._fsync_dir()
        failpoints.trigger(
            "book.after_dir_fsync", path=self._dir, closed_trades=closed_trades
        )
        return LaneBook(
            body=body,
            digest=digest,
            updated_at_ms=int(doc["updated_at_ms"] or 0),
            state_digest=economic,
        )

    def _copy_previous(self) -> None:
        """Keep the generation that ``BOOK.json`` holds right now as ``.prev``."""
        with contextlib.suppress(OSError):
            raw = self.path.read_bytes()
            with open(self.prev_path, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())

    def _fsync_dir(self) -> None:
        """Make the rename itself durable. Not every platform allows opening a directory."""
        if os.name == "nt":  # pragma: no cover - Windows has no directory fsync
            return
        with contextlib.suppress(OSError):
            fd = os.open(self._dir, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def event(self, kind: str, payload: dict[str, Any]) -> None:
        """Append one durable event row (commit / recovery / block) and fsync it.

        Separate from the book on purpose: the book says *what is true now*, the events
        say *how it became true*. A verifier that only had the book could not tell a
        clean restart from a takeover over a corrupt file.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        row = {"kind": kind, "at_ms": _now_ms(), **payload}
        self._repair_events_tail()
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            failpoints.trigger("event.after_write", path=self._dir, kind=kind)
            handle.flush()
            os.fsync(handle.fileno())
        failpoints.trigger("event.after_fsync", path=self._dir, kind=kind)

    def events(self) -> list[dict[str, Any]]:
        """Every committed event row.

        A trailing row that does not parse is the signature of a process killed inside
        ``event()``. It is not committed and it is not reported as if it were: it is
        skipped, and :meth:`recover` names it. A bad row with a good one after it is an
        edit and raises, because silently skipping it would rewrite history.
        """
        if not self.events_path.exists():
            return []
        out: list[dict[str, Any]] = []
        raw = self.events_path.read_bytes()
        lines = [line for line in raw.split(b"\n") if line.strip()]
        for index, line in enumerate(lines):
            try:
                out.append(json.loads(line.decode("utf-8")))
            except (ValueError, UnicodeDecodeError):
                if index == len(lines) - 1:
                    self.events_repair = {
                        "reason": "TORN_TAIL",
                        "dropped_bytes": len(line),
                        "lines_kept": len(out),
                    }
                    break
                raise CorruptBook(
                    f"{self.events_path} line {index + 1} does not parse and is not the "
                    "last one: the commit log was edited"
                ) from None
        return out

    def _repair_events_tail(self) -> None:
        """Drop a tail that a killed process left half-written, and say that it did.

        The truncation is recorded as a ``REPAIR`` row *in the log itself* after the cut,
        so the absence of a commit cannot be mistaken for a log that never had one.
        """
        if not self.events_path.exists():
            return
        raw = self.events_path.read_bytes()
        if not raw or raw.endswith(b"\n"):
            return
        cut = raw.rfind(b"\n") + 1
        dropped = raw[cut:]
        with self.events_path.open("r+b") as handle:
            handle.truncate(cut)
            handle.flush()
            os.fsync(handle.fileno())
        self.events_repair = {
            "reason": "TORN_TAIL",
            "dropped_bytes": len(dropped),
            "dropped_preview": dropped[:120].decode("utf-8", "replace"),
        }
        row = {"kind": "REPAIR", "at_ms": _now_ms(), **self.events_repair}
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    # -- recovery -------------------------------------------------------------

    def recover(
        self,
        *,
        ledger_path: Path | str | None = None,
        check_lock: bool = True,
    ) -> dict[str, Any]:
        """Classify what a resume finds, in the vocabulary the RFC asks for.

        This is a diagnosis, not a repair of the economics. It answers, separately:

        * is there a book at all (:data:`StoreRecoveryStatus.NO_CHANGE` when the account
          is fresh)?
        * is the generation on disk *nameable* (a ``.prev`` without a ``BOOK.json`` is not
          "an older book", it is an interrupted rotation: ambiguous, refused)?
        * did the process die between the atomic replace and the ``COMMIT`` event? The book
          is authoritative and carries its own digest, so the lag is recoverable and is
          reported as such, not invented as a rollback;
        * does the ledger (the projection) agree with the book? Missing committed rows are
          corruption; extra rows are the *expected* residue of a crash between the ledger
          fsync and the book replace, and are named one by one;
        * what can this platform actually promise about power loss?

        ``check_lock=False`` is for a caller that already holds the lock (the lane holds it
        for the whole session): the lock file it finds is its own, and reporting
        ``BLOCKED_LOCK`` there would turn a normal session into a false alarm.
        ``ledger_path`` is only meaningful when the file is the ledger of *this book's whole
        life*; a per-session ledger cannot prove anything about closes committed by an
        earlier process, so the caller decides.
        """
        checks: list[dict[str, Any]] = []
        report: dict[str, Any] = {
            "status": StoreRecoveryStatus.NO_CHANGE,
            "code": None,
            "detail": "",
            "checks": checks,
            "book_digest": None,
            "state_digest": None,
            "barrier_ms": None,
            "orphan_tmp": False,
            "commit_event_lag": False,
            "events_repair": None,
            "ledger": None,
            "platform": {
                "os": os.name,
                "directory_fsync": "unsupported" if os.name == "nt" else "attempted",
                "power_loss_scope": "POWER_LOSS_DURABILITY_NOT_VERIFIED",
            },
        }

        def add(name: str, ok: bool, detail: str) -> None:
            checks.append({"check": name, "ok": bool(ok), "detail": detail})

        tmp = self.path.with_suffix(".json.tmp")
        report["orphan_tmp"] = tmp.exists()
        add(
            "orphan_tmp_absent",
            True,
            "no temporary book left behind"
            if not tmp.exists()
            else f"{tmp.name} exists and is not adopted: a partial write is never a state",
        )

        if not self.path.exists():
            if self.prev_path.exists() or tmp.exists():
                add(
                    "current_generation_nameable",
                    False,
                    f"{self.path.name} is missing while "
                    + ", ".join(
                        name for name, present in ((self.prev_path.name, self.prev_path.exists()), (tmp.name, tmp.exists())) if present
                    )
                    + " exist(s)",
                )
                report.update(
                    status=StoreRecoveryStatus.REFUSED_AMBIGUOUS_COMMIT,
                    code="CURRENT_GENERATION_MISSING",
                    detail=(
                        "the book that is current cannot be named: a write was interrupted "
                        "between generations and neither the previous file nor the temporary "
                        "one is proof of which one committed"
                    ),
                )
                return report
            add("book_present", True, "no book on disk: this session starts the account")
            report["detail"] = "no durable book: nothing to recover"
            return report

        try:
            book = self.load()
        except CorruptBook as exc:
            add("book_loadable", False, str(exc))
            report.update(
                status=StoreRecoveryStatus.REFUSED_CORRUPTION,
                code="BOOK_NOT_TRUSTWORTHY",
                detail=str(exc),
            )
            return report
        assert book is not None
        add(
            "book_loadable",
            True,
            f"{self.path.name} parses and matches its own digest {book.digest[:12]}",
        )
        report.update(
            book_digest=book.digest, state_digest=book.state_digest, barrier_ms=book.barrier_ms
        )

        events = self.events()
        report["events_repair"] = self.events_repair
        commits = [row for row in events if row.get("kind") == "COMMIT"]
        congruent = bool(commits) and str(commits[-1].get("digest")) == book.digest
        report["commit_event_lag"] = not congruent
        add(
            "commit_event_congruent",
            True,
            f"the last COMMIT event carries this book's digest {book.digest[:12]}"
            if congruent
            else (
                "the book is ahead of its commit log (replace landed, event did not): the "
                "book is authoritative and carries its own digest, so the merge is a log "
                "entry, not a rollback"
            ),
        )

        changed = bool(report["orphan_tmp"]) or report["commit_event_lag"] or bool(
            report["events_repair"]
        )

        if ledger_path is not None:
            ledger = self._ledger_projection(book, Path(ledger_path))
            report["ledger"] = ledger
            add(
                "ledger_projection_consistent",
                not ledger["missing"] and not ledger["duplicates"],
                ledger["detail"],
            )
            if ledger["missing"] or ledger["duplicates"]:
                report.update(
                    status=StoreRecoveryStatus.REFUSED_CORRUPTION,
                    code="PROJECTION_BEHIND_AUTHORITY"
                    if ledger["missing"]
                    else "DUPLICATE_OPERATION",
                    detail=ledger["detail"],
                )
                return report
            if ledger["uncommitted"]:
                changed = True

        held = self._lock_held() if check_lock else False
        add(
            "lock_state",
            True,
            "the caller holds the lock for this session"
            if not check_lock
            else (
                "no live writer holds the book"
                if not held
                else f"{self.lock_path.name} is held by a live process: a resume must wait"
            ),
        )
        if held:
            report.update(
                status=StoreRecoveryStatus.BLOCKED_LOCK,
                code="LOCK_HELD",
                detail=(
                    f"{self.lock_path} names a pid that is still alive; a second writer "
                    "would trade the same bar twice"
                ),
            )
            return report

        if changed:
            report.update(
                status=StoreRecoveryStatus.RECOVERED,
                detail=(
                    "the committed book is intact and was reconciled with its log and "
                    "projection; nothing was replayed and no effect was re-applied"
                ),
            )
        else:
            report["detail"] = "the book, its commit log and its projection already agree"
        return report

    def _lock_held(self) -> bool:
        if not self.lock_path.exists():
            return False
        try:
            holder = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return True
        return pid_alive(int(holder.get("pid", 0) or 0)) is not False

    def _ledger_projection(self, book: LaneBook, ledger_path: Path) -> dict[str, Any]:
        """Compare the committed book with the rows the ledger claims.

        The book is the authority (a close exists iff it is in ``closed_trades``). The
        ledger is at-least-once by construction: a crash after its fsync and before the
        book replace leaves rows the account never committed, and a resume re-executes
        exactly those. So *extra* rows are named and tolerated; *missing* committed rows
        and *duplicate* operation identities are refused.
        """
        rows: list[dict[str, Any]] = []
        if ledger_path.exists():
            for line in ledger_path.read_bytes().split(b"\n"):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line.decode("utf-8")))
                except (ValueError, UnicodeDecodeError):
                    continue
        seen: dict[str, int] = {}
        for row in rows:
            entry = dict(row.get("entry") or {})
            operation_id = str(entry.get("operation_id") or "")
            if operation_id:
                seen[operation_id] = seen.get(operation_id, 0) + 1
        duplicates = sorted(key for key, count in seen.items() if count > 1)
        #: Every economic operation the book says happened: the close of a position and the
        #: fill that opened it, including positions still open (their FILL is committed even
        #: though their CLOSE does not exist yet). Comparing closes alone turned every open
        #: position's fill into a phantom "uncommitted row".
        closed_ids = {str(row.get("position_id", "")) for row in book.closed_trades}
        open_ids = {str(row.get("position_id", "")) for row in book.open_positions}
        committed = {f"{book.book_id}|CLOSE|{position_id}" for position_id in closed_ids}
        committed |= {
            f"{book.book_id}|FILL|{position_id}" for position_id in closed_ids | open_ids
        }
        missing = sorted(committed - set(seen))
        uncommitted = sorted(set(seen) - committed)
        detail = (
            f"{len(seen)} operation row(s) in the ledger, {len(committed)} committed "
            f"operation(s); missing={len(missing)} uncommitted={len(uncommitted)} "
            f"duplicates={len(duplicates)}"
        )
        return {
            "path": str(ledger_path),
            "rows": len(rows),
            "operations": len(seen),
            "committed_operations": len(committed),
            "committed_closes": len(closed_ids),
            "missing": missing,
            "uncommitted": uncommitted,
            "duplicates": duplicates,
            "detail": detail,
        }


# -- recovery -------------------------------------------------------------------


class RecoveryStatus:
    """Names for the only three answers this contract has."""

    FRESH = "FRESH"
    RECOVERED = "RECOVERED"
    BLOCKED = "BLOCKED"


class StoreRecoveryStatus:
    """What a *store-level* resume found. Separate from :class:`RecoveryStatus`.

    ``RecoveryStatus`` answers "may this session continue at this bar?", which needs the
    market data. This one answers "what does the disk say?", which does not — and a
    verifier has to be able to ask the second question without a dataset.
    """

    NO_CHANGE = "NO_CHANGE"
    RECOVERED = "RECOVERED"
    REFUSED_CORRUPTION = "REFUSED_CORRUPTION"
    REFUSED_AMBIGUOUS_COMMIT = "REFUSED_AMBIGUOUS_COMMIT"
    BLOCKED_LOCK = "BLOCKED_LOCK"


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    status: str
    code: str | None
    detail: str
    checks: tuple[dict[str, Any], ...] = ()
    barrier_ms: int | None = None
    resume_from_ms: int | None = None
    #: The 1-minute evidence the verdict rests on, when the resume crossed a hole. It is
    #: published whole rather than summarised: the checks say *that* the minutes covered the
    #: hole, the evidence says *which bytes* did.
    gap: dict[str, Any] | None = None
    #: Economic actions the caller must apply before the first bar: protective exits the hole
    #: proved were crossed. ``None`` when the hole was crossed with the book untouched.
    reconstruction: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status in {RecoveryStatus.FRESH, RecoveryStatus.RECOVERED}

    @property
    def recovered(self) -> bool:
        return self.status == RecoveryStatus.RECOVERED

    def failed(self) -> list[dict[str, Any]]:
        return [check for check in self.checks if not check.get("ok")]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "code": self.code,
            "detail": self.detail,
            "barrier_ms": self.barrier_ms,
            "resume_from_ms": self.resume_from_ms,
            "checks": [dict(check) for check in self.checks],
            "gap": self.gap,
            "reconstruction": self.reconstruction,
        }


def contract_from(
    *,
    book_id: str,
    timeframe: str,
    interval_ms: int,
    equity: float,
    cost_multiplier: float,
    window_bars: int,
    decision_every_bars: int,
    risk_policy: dict[str, Any],
    provider: str,
    dataset: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """What a book must continue to be for a resumed session to be the same experiment.

    ``dataset`` carries, per symbol, the *prefix* digest at the barrier: the bars that
    produced this book, not the whole file. A later bar is new; an earlier bar that changed
    means the history under the book moved, and no economics computed on top of it survive.
    """
    return {
        "book_id": book_id,
        "timeframe": str(timeframe),
        "interval_ms": int(interval_ms),
        "equity": round(float(equity), 8),
        "cost_multiplier": round(float(cost_multiplier), 8),
        "window_bars": int(window_bars),
        "decision_every_bars": int(decision_every_bars),
        "risk_policy": dict(risk_policy),
        "provider": str(provider),
        "dataset": {symbol: dict(meta) for symbol, meta in dataset.items()},
    }


def _check(
    checks: list[dict[str, Any]],
    name: str,
    ok: bool,
    detail: str = "",
    fail_detail: str = "",
) -> bool:
    """Record one check, with a detail that matches its verdict.

    ``detail`` describes a check that **passed** (what was observed, e.g. "the dataset holds
    a bar at 1792506600000"); ``fail_detail`` is only written when the check failed. Passing
    a failure sentence as ``detail`` would leave rows that read as a defect next to
    ``ok: true``, and a reader of ``RECOVERY.checks`` has no way to tell which one to trust.
    """
    recorded = detail if ok else fail_detail or detail
    checks.append({"check": name, "ok": bool(ok), "detail": recorded})
    return ok


def reconcile_book(
    book: LaneBook | None,
    *,
    contract: dict[str, Any],
    prefix: dict[str, dict[str, Any]],
    timeline: list[int],
    interval_ms: int,
    gap: GapAssessment | None = None,
) -> RecoveryReport:
    """Decide whether ``book`` may continue, and from which bar.

    The order of the checks is the order in which a wrong answer would cost the most:
    identity first (is this the same book?), then the money (does it add up?), then the
    book's own structure (are the rows usable?), then time (is the bar it claims to have
    processed provable from the data at hand?).

    A single failing check blocks the whole recovery. There is no partial restore: a book
    whose equity identity is broken and whose positions look fine is a book that has
    already lost a fill, and restoring the positions would hide the loss.
    """
    checks: list[dict[str, Any]] = []
    if book is None:
        _check(checks, "book_present", True, "no book on disk: a fresh book is the only one")
        return RecoveryReport(
            status=RecoveryStatus.FRESH,
            code=None,
            detail="no durable book: this session starts the account",
            checks=tuple(checks),
            barrier_ms=None,
            resume_from_ms=None,
        )

    stored = book.contract
    mismatched = sorted(
        name
        for name in (
            "book_id",
            "timeframe",
            "interval_ms",
            "equity",
            "cost_multiplier",
            "window_bars",
            "decision_every_bars",
            "risk_policy",
            "provider",
        )
        if stored.get(name) != contract.get(name)
    )
    if not _check(
        checks,
        "contract_matches",
        not mismatched,
        "" if not mismatched else f"incompatible configuration: {', '.join(mismatched)}",
    ):
        return RecoveryReport(
            status=RecoveryStatus.BLOCKED,
            code="CONTRACT_MISMATCH",
            detail=(
                "the book belongs to a different experiment: "
                f"{', '.join(mismatched)}; continuing would publish one account as another"
            ),
            checks=tuple(checks),
            barrier_ms=book.barrier_ms,
            resume_from_ms=None,
        )

    barrier = book.barrier_ms
    if not _check(
        checks,
        "barrier_present",
        barrier is not None,
        "" if barrier is not None else "the book has no committed bar",
    ):
        return RecoveryReport(
            status=RecoveryStatus.BLOCKED,
            code="BARRIER_MISSING",
            detail="the book carries no committed bar, so there is nothing to resume from",
            checks=tuple(checks),
            barrier_ms=None,
            resume_from_ms=None,
        )
    assert barrier is not None

    # The history under the book must be the history the book was written on.
    dataset_ok = True
    dataset_detail: list[str] = []
    for symbol, expected in (stored.get("dataset") or {}).items():
        actual = prefix.get(symbol)
        if actual is None:
            dataset_ok = False
            dataset_detail.append(f"{symbol}: not in the dataset at all")
            continue
        if int(actual.get("last_open_ms") or 0) < barrier:
            dataset_ok = False
            dataset_detail.append(
                f"{symbol}: the dataset ends at {actual.get('last_open_ms')}, before the "
                f"barrier {barrier}"
            )
            continue
        if str(actual.get("sha256")) != str(expected.get("sha256")):
            dataset_ok = False
            dataset_detail.append(
                f"{symbol}: the bars up to the barrier hash to {actual.get('sha256')}, "
                f"the book recorded {expected.get('sha256')}"
            )
    if not _check(
        checks,
        "dataset_prefix_matches",
        dataset_ok,
        fail_detail="; ".join(dataset_detail),
    ):
        return RecoveryReport(
            status=RecoveryStatus.BLOCKED,
            code="DATASET_MISMATCH",
            detail=(
                "the bars that produced this book are not the bars on disk; a resumed book "
                "would carry decisions taken on history that no longer exists"
            ),
            checks=tuple(checks),
            barrier_ms=barrier,
            resume_from_ms=None,
        )

    broker = dict(book.body.get("broker") or {})
    closed = book.closed_trades
    equity = float(broker.get("equity", 0.0))
    initial = float(broker.get("initial_equity", 0.0))
    pnl_sum = sum(float(row.get("pnl", 0.0)) for row in closed)
    identity_ok = initial > 0 and abs((initial + pnl_sum) - equity) <= TOLERANCE_USDT
    if not _check(
        checks,
        "equity_identity",
        identity_ok,
        fail_detail=f"initial {initial} + sum(closed pnl) {pnl_sum} != equity {equity}",
    ):
        return RecoveryReport(
            status=RecoveryStatus.BLOCKED,
            code="EQUITY_IDENTITY",
            detail=(
                "the persisted book does not finance itself: a closed trade is missing or "
                "was counted twice, and no equity can be published from it"
            ),
            checks=tuple(checks),
            barrier_ms=barrier,
            resume_from_ms=None,
        )

    if not _check(
        checks,
        "closed_history_intact",
        str(book.body.get("closed_digest", "")) == closed_digest(closed),
        fail_detail="the closed-trade rows do not hash to the digest stored beside them",
    ):
        return RecoveryReport(
            status=RecoveryStatus.BLOCKED,
            code="CLOSED_HISTORY",
            detail="the realised history was edited after it was committed",
            checks=tuple(checks),
            barrier_ms=barrier,
            resume_from_ms=None,
        )

    positions = book.open_positions
    open_ids = [str(row.get("position_id", "")) for row in positions]
    closed_ids = {str(row.get("position_id", "")) for row in closed}
    structure: list[str] = []
    if len(set(open_ids)) != len(open_ids):
        structure.append("two open positions share one position_id")
    if any(not pid for pid in open_ids):
        structure.append("an open position has no position_id")
    overlap = sorted(set(open_ids) & closed_ids)
    if overlap:
        structure.append(f"position(s) both open and closed: {', '.join(overlap)}")
    for row in positions:
        symbol = str(row.get("symbol", ""))
        if symbol not in contract.get("dataset", {}):
            structure.append(f"{symbol or '?'} is open but not in the configured universe")
        if str(row.get("side")) not in {"buy", "sell"}:
            structure.append(f"{symbol}: side {row.get('side')!r} is not buy/sell")
        if float(row.get("quantity", 0.0)) <= 0 or float(row.get("entry_price", 0.0)) <= 0:
            structure.append(f"{symbol}: non-positive quantity or entry price")
        if float(row.get("entry_commission", 0.0)) < 0:
            structure.append(f"{symbol}: negative entry commission")
    if not _check(
        checks, "position_structure", not structure, fail_detail="; ".join(structure)
    ):
        return RecoveryReport(
            status=RecoveryStatus.BLOCKED,
            code="POSITION_INVALID",
            detail="the open book is not usable as it stands: " + "; ".join(structure),
            checks=tuple(checks),
            barrier_ms=barrier,
            resume_from_ms=None,
        )

    risk_equity = book.body.get("risk_equity")
    marked = book.body.get("marked_equity")
    risk_ok = (
        marked is not None
        and risk_equity is not None
        and abs(float(risk_equity) - float(marked)) <= TOLERANCE_USDT
    )
    if not _check(
        checks,
        "risk_agrees_with_mark",
        bool(risk_ok),
        fail_detail=f"risk equity {risk_equity} != marked equity {marked}",
    ):
        return RecoveryReport(
            status=RecoveryStatus.BLOCKED,
            code="RISK_MISMATCH",
            detail=(
                "the risk engine and the book would restart with different equity, so the "
                "next sizing decision would be taken against a book that does not exist"
            ),
            checks=tuple(checks),
            barrier_ms=barrier,
            resume_from_ms=None,
        )

    next_bar = barrier + int(interval_ms)
    present = [ts for ts in timeline if ts > barrier]
    if not present:
        #: A process restarted between two bars owes the book nothing yet. That is not a
        #: blocked recovery and it is not a signal to start flat either: the session waits
        #: at the bar that *should* come next, and the first commit it makes will be that
        #: bar. When the data never arrives, the feed health gate — not this check — is
        #: what refuses to trade.
        _check(
            checks,
            "resume_bar_available",
            True,
            f"no bar after {barrier} yet: the session waits at {next_bar}",
        )
        return RecoveryReport(
            status=RecoveryStatus.RECOVERED,
            code=None,
            detail=(
                f"book {book.book_id} recovered at bar {barrier}: {len(positions)} open, "
                f"{len(closed)} closed, equity {equity:.8f}; awaiting {next_bar}"
            ),
            checks=tuple(checks),
            barrier_ms=barrier,
            resume_from_ms=next_bar,
        )

    first = min(present)
    _check(checks, "resume_bar_available", True, f"the dataset holds a bar at {first}")
    continuous = next_bar == int(first)
    if not _check(
        checks,
        "barrier_is_continuous",
        continuous,
        detail=f"resuming at {first}",
        fail_detail=f"bar {next_bar} is missing; the next bar is {first}",
    ):
        #: A gap is not automatically fatal: a 1-minute feed may have observed every minute
        #: of it, which answers the one question the 5-minute grid cannot — was a protective
        #: level crossed. Without that assessment the refusal stands exactly as before.
        if gap is None:
            return RecoveryReport(
                status=RecoveryStatus.BLOCKED,
                code="UNVERIFIED_GAP",
                detail=(
                    f"bar {next_bar} is missing between the committed book and the next bar "
                    f"({first}). A protective exit could have been crossed inside that window "
                    "and no range is available to prove it was not"
                ),
                checks=tuple(checks),
                barrier_ms=barrier,
                resume_from_ms=None,
            )

        #: The assessment must describe *this* hole and *this* book. A verdict computed on
        #: another barrier, another resume bar or another set of positions is not evidence
        #: about what is on disk, and adopting it would be the partial restore this module
        #: refuses to do.
        assessed_ids = sorted(item.position_id for item in gap.positions)
        book_ids = sorted(str(row.get("position_id", "")) for row in positions)
        aligned = (
            gap.window.barrier_ms == barrier
            and gap.window.resume_ms == int(first)
            and gap.window.interval_ms == int(interval_ms)
            and assessed_ids == book_ids
        )
        if not _check(
            checks,
            "gap_evidence_matches_book",
            aligned,
            detail=(
                f"the assessment covers bars {gap.window.barrier_ms}->{gap.window.resume_ms} "
                f"and {len(assessed_ids)} position(s), matching this book"
            ),
            fail_detail=(
                f"the assessment covers bars {gap.window.barrier_ms}->{gap.window.resume_ms} "
                f"for {assessed_ids}; this book is at {barrier}, resumes at {first} and "
                f"holds {book_ids}"
            ),
        ):
            return RecoveryReport(
                status=RecoveryStatus.BLOCKED,
                code="GAP_EVIDENCE_STALE",
                detail=(
                    "the 1-minute assessment was computed against a different book, "
                    "barrier or resume bar; using it would apply someone else's evidence "
                    "to this exposure"
                ),
                checks=tuple(checks),
                barrier_ms=barrier,
                resume_from_ms=None,
                gap=gap.to_dict(),
            )

        gap_checks = tuple(
            {"check": f"gap.{item['check']}", "ok": item["ok"], "detail": item["detail"]}
            for item in gap.checks
        )
        if not gap.ok:
            return RecoveryReport(
                status=RecoveryStatus.BLOCKED,
                code=gap.code or "GAP_NOT_COVERED",
                detail=gap.detail,
                checks=(*checks, *gap_checks),
                barrier_ms=barrier,
                resume_from_ms=None,
                gap=gap.to_dict(),
            )

        coverage = gap.evidence.get("symbols") or {}
        _check(
            checks,
            "gap_covered_by_quotes",
            True,
            (
                f"{gap.feed} observed every minute of {next_bar}..{first - 1} for "
                + ", ".join(
                    f"{symbol} ({item.get('minutes_observed')} minutes, "
                    f"{str(item.get('window_sha256'))[:12]})"
                    for symbol, item in sorted(coverage.items())
                )
                if coverage
                else f"{gap.feed} observed every minute of the hole; no position is open"
            ),
        )
        reconstruction = None
        if gap.verdict == "RECONSTRUCT":
            exits = gap.exits
            _check(
                checks,
                "gap_exits_placeable",
                True,
                (
                    f"{len(exits)} protective exit(s) crossed inside the hole and are "
                    "placed at their observed minute: "
                    + ", ".join(
                        f"{item.position_id} {item.symbol} {item.exit_reason} at "
                        f"{item.exit_price} (minute {item.exit_minute_ms})"
                        for item in exits
                    )
                ),
            )
            reconstruction = {
                "kind": "PROTECTIVE_EXITS",
                "feed": gap.feed,
                "window": gap.to_dict()["window"],
                "exits": [
                    {
                        "position_id": item.position_id,
                        "symbol": item.symbol,
                        "side": item.side,
                        "reason": item.exit_reason,
                        "price": item.exit_price,
                        "minute_ms": item.exit_minute_ms,
                        "stop_price": item.stop_price,
                        "take_profit_price": item.take_profit_price,
                        "worst_price": item.worst_price,
                        "worst_unrealised_usdt": item.worst_unrealised_usdt,
                        "stop_touch": None
                        if item.stop_touch is None
                        else item.stop_touch.to_dict(),
                        "take_profit_touch": None
                        if item.take_profit_touch is None
                        else item.take_profit_touch.to_dict(),
                    }
                    for item in exits
                ],
                "minutes": [
                    minute for minute in gap.minutes if minute["symbol"] in {i.symbol for i in exits}
                ],
                "evidence": gap.evidence,
            }
        return RecoveryReport(
            status=RecoveryStatus.RECOVERED,
            code=None,
            detail=(
                f"book {book.book_id} recovered at bar {barrier} across a {len(gap.window.missing_bars)}-bar "
                f"hole: {len(positions)} open, {len(closed)} closed, "
                f"{len(gap.exits)} exit(s) reconstructed, equity {equity:.8f}"
            ),
            checks=tuple(checks),
            barrier_ms=barrier,
            resume_from_ms=int(first),
            gap=gap.to_dict(),
            reconstruction=reconstruction,
        )

    return RecoveryReport(
        status=RecoveryStatus.RECOVERED,
        code=None,
        detail=(
            f"book {book.book_id} recovered at bar {barrier}: "
            f"{len(positions)} open, {len(closed)} closed, equity {equity:.8f}"
        ),
        checks=tuple(checks),
        barrier_ms=barrier,
        resume_from_ms=int(first),
    )
