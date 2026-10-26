#!/usr/bin/env python
"""WP-051-02F — the forward capture runner: one entry point for a phase-2 capture attempt.

The declaration names a window and a frozen extractor, so the only thing missing between
"the freeze binds" and "a dataset exists" is somebody running the right command at the
right moment. That is what this file is, and nothing more: an orchestrator around contracts
that already exist. Every instant the runner compares against is read from the declaration
at runtime; no window boundary is written down in this file.

It delegates rather than reimplements, because a second copy of an acceptance rule is a
second rule:

* ``scripts/edge04_observer.py`` — the authorised observation. It is the documented
  entry point of the WP-EDGE-04 forward observer, the one the phase-2 declaration itself
  names as the provider ("Binance public REST /api/v3/klines via the WP-EDGE-03 forward
  observer"). This runner does not fetch, download or synthesise a bar.
* ``scripts/exp004a_wp051_02e_preflight.py`` — the ten provenance controls. They are run
  with ``--out-dir`` pointed at this work package's own directory, so the sealed 02E
  artefacts are read and never written.
* ``scripts/exp004a_capture.py`` — the frozen extractor, invoked with the declaration's
  own ``generator_command`` and nothing added: no new flag, no reordered argument, no
  different window.
* ``scripts/exp004a_wp051_02f_verify.py`` — the independent verifier, run as a separate
  process so its verdict is not the runner's verdict.

What this runner adds is the part the frozen pieces do not have: a state machine that
names *why* nothing happened, a lock so two processes cannot publish into the same
directory, a bounded retry, and a temporal guard that quarantines what the frozen
extractor would otherwise have published without complaint.

That last one is the reason this file exists at all. The frozen extractor asks
``eligibility_defects`` whether a bar was fetched at or after the declaration's
``effective_from_utc`` and whether it opens inside the window. It never asks whether the
bar claims to have been ingested *after the moment the capture was decided* — the defect
this package calls ``DEF-02E-01``/``L-01``. Correcting the extractor is forbidden while
phase 2 is frozen, so the correction available to a runner is not a fix but a refusal:
detect the incompatible row, publish nothing further, and say so. The guard below is
therefore independent of the extractor, it runs *after* the extractor has written, and it
never edits or deletes what was written. A quarantined dataset stays on disk as the
record of a quarantined attempt; what it does not get is the word "admissible".

Research only: public market data, local files, no credentials, no orders, no capital,
no promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.prospective.store import INTERVAL_MS, index_series  # noqa: E402

RUNNER_ID = "runner/EXP-004A/WP-051-02F"
SCHEMA_VERSION = "1.0"

DECLARATION = "config/preregistrations/EXP-004A.datasets.phase2.json"
GENERATOR = "scripts/exp004a_capture.py"
PREFLIGHT = "scripts/exp004a_wp051_02e_preflight.py"
VERIFIER_02E = "scripts/exp004a_wp051_02e_verify.py"
VERIFIER_02F = "scripts/exp004a_wp051_02f_verify.py"
OBSERVER = "scripts/edge04_observer.py"
DATASET_DIR = "data/exp004a"
OUT_DIR = "docs/agentic/exp004a/wp051_02f"
LOCK_NAME = "runner.lock"
#: The names the RFC's own evidence layout asks for. A run writes into
#: ``<package>/evidence/<run_id>/`` and the seal promotes one run to the top level,
#: so a prior seal is never overwritten by the next attempt.
RUN_REPORT = "RUN_REPORT.json"
RUN_REPORT_MD = "RUN_REPORT.md"
CLAIM_REPORT = "CLAIM.json"
VERIFICATION_REPORT = "INDEPENDENT_VERIFICATION.json"
EVIDENCE_MANIFEST = "EVIDENCE_MANIFEST.json"
LATEST_RUN = "LATEST_RUN.json"
EVIDENCE_DIR = "evidence"

#: The states the runner can be in. The names are the report: a reader must be able to
#: tell "the window has not opened" from "the observer is stale" from "the bytes that
#: were published are not temporally admissible".
STATE_NOT_DUE = "NOT_DUE"
STATE_PREFLIGHT = "PREFLIGHT"
STATE_PENDING_DATA = "PENDING_DATA"
STATE_PENDING_FRESHNESS = "PENDING_FRESHNESS"
STATE_BLOCKED_INTEGRITY = "BLOCKED_INTEGRITY"
STATE_CAPTURE_ATTEMPTED = "CAPTURE_ATTEMPTED"
STATE_FAILED_OR_PENDING = "FAILED_OR_PENDING"
STATE_TEMPORAL_QUARANTINE_CHECK = "TEMPORAL_QUARANTINE_CHECK"
STATE_QUARANTINED = "QUARANTINED"
STATE_INDEPENDENT_VERIFY = "INDEPENDENT_VERIFY"
#: The RFC's two terminal states. ``BLOCKED`` is "the independent verifier refused";
#: ``CAPTURED_VERIFIED`` is a *data* result of this package, never a certification.
STATE_BLOCKED = "BLOCKED"
STATE_CAPTURED_VERIFIED = "CAPTURED_VERIFIED"

#: The states that mean "this attempt published nothing and says so". They are not
#: failures of the runner; they are the honest description of a window that is closed
#: or a store that is behind the clock.
PENDING_STATES = (
    STATE_NOT_DUE,
    STATE_PENDING_DATA,
    STATE_PENDING_FRESHNESS,
)

#: The runner's own exit codes. They are not the extractor's and not the verifier's, so
#: that a caller can tell which layer refused.
EXIT_OK = 0
EXIT_BLOCKED = 2
EXIT_PENDING = 3
EXIT_FAILED = 4
EXIT_QUARANTINED = 5
EXIT_ALREADY_RUNNING = 6

#: How long a lock older than this is considered abandoned rather than held. The check is
#: on age and not on the pid, because on Windows ``os.kill(pid, 0)`` terminates the
#: process instead of probing it, and a liveness check that kills the holder is not a
#: liveness check.
LOCK_STALE_SECONDS = 900

#: A monotonic per-process counter mixed into :func:`new_run_id`. Two attempts in the same
#: process can happen in the same clock tick; they may not share a directory.
_RUN_SEQUENCE = itertools.count(1)

#: The statuses ``exp004a_wp051_02e_preflight.py`` emits when all ten controls passed.
#: The 02E program names the passing state after the window it found, not with a bare
#: ``PASS``: ``WINDOW_OPEN`` is the passing verdict once the declared window has opened and
#: ``READY_FOR_WINDOW`` is the passing verdict before it does. This runner accepts exactly
#: those two and refuses everything else, including a ``PASS`` nobody emits: a status this
#: file does not recognise is not a status it is allowed to translate.
PREFLIGHT_ACCEPTED = ("WINDOW_OPEN", "READY_FOR_WINDOW")

#: The extractor's exit codes, named here so the report reads in words and not in numbers.
CAPTURE_EXIT = {
    0: "OK",
    2: "CONTRACT_REFUSED",
    3: "NO_ELIGIBLE_BARS",
    4: "SOURCE_UNREADABLE",
    5: "NOT_ELIGIBLE",
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def now_ms() -> int:
    return int(time.time() * 1000)


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str) -> str | None:
    completed = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def git_blob_sha(repo: Path, path: str) -> str | None:
    """The Git blob id of a path at HEAD, or ``None`` when Git does not have it.

    A blob id and a SHA-256 of the checkout's bytes are different magnitudes. The
    checkout of a text file carries the line endings the working tree uses, and a
    CRLF checkout of an LF blob hashes to something else entirely. Both are reported
    and neither is presented as the other.
    """
    return git(repo, "rev-parse", f"HEAD:{path}")


def parse_ms(value: object, field_name: str) -> int:
    """An ISO-8601 instant with a zone. A naive timestamp is not an instant."""
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{field_name} is not an ISO-8601 instant: {value!r}") from error
    if moment.tzinfo is None:
        raise ValueError(f"{field_name} is naive; a window without a zone is not a window")
    return int(moment.astimezone(UTC).timestamp() * 1000)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def tail(text: str, limit: int = 4000) -> str:
    text = (text or "").strip()
    return text[-limit:]


def new_run_id(at_ms: int) -> str:
    """A sortable, unique name for one attempt.

    The timestamp makes the run directories sort in the order the attempts happened;
    the suffix keeps two attempts inside the same second apart. A run directory is
    never reused, so a seal is never overwritten by a later attempt.

    Uniqueness may not rest on the clock alone. ``time.time_ns`` on Windows has a
    coarse resolution and two calls in the same tick return the same value, so an
    in-process counter and an OS-supplied nonce are mixed into the seed: the counter
    separates attempts inside one process, the nonce separates processes that started
    in the same tick.
    """
    stamp = datetime.fromtimestamp(at_ms / 1000, UTC).strftime("%Y%m%dT%H%M%SZ")
    seed = (
        f"{at_ms}:{os.getpid()}:{time.time_ns()}:{next(_RUN_SEQUENCE)}:{os.urandom(8).hex()}"
    ).encode()
    return f"{stamp}-{hashlib.sha256(seed).hexdigest()[:8]}"


# --------------------------------------------------------------------------- #
# the declaration is the authority
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Slice:
    """One declared dataset, resolved against the declaration's own text."""

    spec: str
    dataset_id: str
    asset: str
    interval: str
    timeframe: str
    lag_bound_ms: int
    coverage_required: float
    generator_command: str
    normalized_file: str
    raw_file: str | None
    source_path: Path
    #: The row count the declaration promises for the whole declared period. A capture taken
    #: before that period elapses cannot produce it, and the frozen extractor writes once, so
    #: the shortfall is permanent for that dataset. Recorded so the report can name it.
    declared_row_count: int = 0


@dataclass(frozen=True, slots=True)
class Declaration:
    document: dict[str, Any]
    path: Path
    sha256: str
    blob_sha: str | None
    commit: str | None
    window_start_ms: int
    window_end_ms: int
    effective_from_ms: int
    slices: tuple[Slice, ...]
    deferred: tuple[str, ...]


def load_declaration(repo: Path) -> Declaration:
    """Read the successor declaration. Every value used later comes from here."""
    path = repo / DECLARATION
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist; the slices have no declared contract")
    document = json.loads(path.read_text(encoding="utf-8"))
    window = document.get("capture_window") or {}
    start_ms = parse_ms(window.get("start_utc"), "capture_window.start_utc")
    end_ms = parse_ms(window.get("end_utc"), "capture_window.end_utc")
    effective_ms = parse_ms(document.get("effective_from_utc"), "effective_from_utc")

    slices: list[Slice] = []
    deferred: list[str] = []
    for entry in document.get("entries") or []:
        command = str(entry.get("generator_command") or "")
        spec = command.split("--slice", 1)[1].strip() if "--slice" in command else ""
        timeframe = str(entry.get("timeframe") or "")
        if not spec:
            deferred.append(f"{entry.get('dataset_id')}: no generator_command")
            continue
        if timeframe not in INTERVAL_MS:
            # st6:tape: the declaration defines no round-to-window rule for it, so there is
            # no slice to resolve. It is deferred, not refused: the extractor is the one
            # that refuses it, and its refusal is the evidence.
            deferred.append(f"{entry.get('dataset_id')}: timeframe {timeframe!r} is not a bar series")
            continue
        interval, asset = spec.split(":", 1)
        parameters = entry.get("generator_parameters") or {}
        slices.append(
            Slice(
                spec=spec,
                dataset_id=str(entry.get("dataset_id")),
                asset=asset,
                interval=interval,
                timeframe=timeframe,
                lag_bound_ms=int(parameters.get("lag_bound_ms") or 0),
                coverage_required=float(parameters.get("coverage_required") or 0.0),
                generator_command=command,
                normalized_file=str(entry.get("normalized_file") or ""),
                raw_file=entry.get("raw_file"),
                source_path=repo
                / "data"
                / "forward"
                / "edge03"
                / interval
                / f"{asset}.jsonl",
                declared_row_count=int(entry.get("row_count") or 0),
            )
        )
    return Declaration(
        document=document,
        path=path,
        sha256=sha256_file(path),
        blob_sha=git_blob_sha(repo, DECLARATION),
        commit=git(repo, "log", "-1", "--format=%H", "--", DECLARATION),
        window_start_ms=start_ms,
        window_end_ms=end_ms,
        effective_from_ms=effective_ms,
        slices=tuple(slices),
        deferred=tuple(deferred),
    )


def window_state(declaration: Declaration, at_ms: int) -> str:
    if at_ms < declaration.window_start_ms:
        return "BEFORE_WINDOW"
    if at_ms >= declaration.window_end_ms:
        return "AFTER_WINDOW"
    return "OPEN"


# --------------------------------------------------------------------------- #
# the store, read
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class SeriesState:
    spec: str
    asset: str
    interval: str
    path: str
    readable: bool = False
    rows: int = 0
    last_open_ms: int | None = None
    last_fetched_ms: int | None = None
    bars_in_window: int = 0
    closed_bars_in_window: int = 0
    last_closed_open_ms: int | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec,
            "asset": self.asset,
            "interval": self.interval,
            "path": self.path,
            "readable": self.readable,
            "rows": self.rows,
            "last_open_utc": iso(self.last_open_ms) if self.last_open_ms else None,
            "last_fetched_utc": iso(self.last_fetched_ms) if self.last_fetched_ms else None,
            "bars_in_window": self.bars_in_window,
            "closed_bars_in_window": self.closed_bars_in_window,
            "last_closed_open_utc": (
                iso(self.last_closed_open_ms) if self.last_closed_open_ms else None
            ),
            "error": self.error,
        }


def expected_last_closed_open(at_ms: int, interval_ms: int) -> int:
    """The open instant of the most recent bar that has already closed.

    A bar with open ``t`` closes at ``t + interval``; the latest one that can be stored
    as *closed* at ``at_ms`` therefore opens at ``floor(at_ms / interval) * interval -
    interval``.
    """
    return (at_ms // interval_ms) * interval_ms - interval_ms


def read_series_state(slice_: Slice, declaration: Declaration) -> SeriesState:
    state = SeriesState(
        spec=slice_.spec,
        asset=slice_.asset,
        interval=slice_.interval,
        path=slice_.source_path.relative_to(REPO).as_posix()
        if slice_.source_path.is_relative_to(REPO)
        else slice_.source_path.as_posix(),
    )
    try:
        index = index_series(slice_.source_path, slice_.asset, slice_.interval)
    except Exception as error:  # the reason is reported, not raised
        state.error = f"{type(error).__name__}: {error}"
        return state
    state.readable = True
    state.rows = len(index.bars)
    state.last_open_ms = index.bars[-1].open_ms
    state.last_fetched_ms = max(bar.fetched_at_ms for bar in index.bars)
    in_window = [
        bar
        for bar in index.bars
        if declaration.window_start_ms <= bar.open_ms < declaration.window_end_ms
    ]
    state.bars_in_window = len(in_window)
    state.closed_bars_in_window = sum(1 for bar in in_window if bar.closed)
    closed = [bar for bar in in_window if bar.closed]
    state.last_closed_open_ms = closed[-1].open_ms if closed else None
    return state


def freshness(state: SeriesState, at_ms: int) -> dict[str, Any]:
    """Is the store as current as the clock says it should be?

    This is the check ``L-04`` asks for: an observer inside its lag bound does not prove
    that the last expected bar is *in the store*. The store is compared against the
    clock, not against the observer's own log.
    """
    if not state.readable:
        return {"ok": False, "reason": f"the series is not readable: {state.error}"}
    expected = expected_last_closed_open(at_ms, INTERVAL_MS[state.interval])
    if state.last_open_ms is None:
        return {"ok": False, "reason": "the series holds no bar"}
    behind_ms = expected - state.last_open_ms
    if behind_ms > 0:
        return {
            "ok": False,
            "reason": (
                f"the store's last bar opens {iso(state.last_open_ms)} but the clock says the "
                f"last closed bar should open {iso(expected)}; the store is "
                f"{behind_ms // 1000} s behind"
            ),
            "expected_last_closed_open_utc": iso(expected),
            "behind_ms": behind_ms,
        }
    return {
        "ok": True,
        "reason": (
            f"the store's last bar opens {iso(state.last_open_ms)}; the clock expects "
            f"{iso(expected)}"
        ),
        "expected_last_closed_open_utc": iso(expected),
        "behind_ms": behind_ms,
    }


# --------------------------------------------------------------------------- #
# the lock
# --------------------------------------------------------------------------- #


class LockHeld(RuntimeError):
    """Another runner holds the directory. Two publishers would be one dataset too many."""


class Lock:
    """An exclusive, age-based lease over the dataset directory.

    ``O_CREAT | O_EXCL`` is the atomic part: only one process can create the file. The
    age check is the recovery part: a lock left behind by a process that died is taken
    over, and the takeover is recorded rather than hidden.
    """

    def __init__(self, path: Path, *, stale_seconds: int = LOCK_STALE_SECONDS) -> None:
        self.path = path
        self.stale_seconds = stale_seconds
        self.taken_over: dict[str, Any] | None = None

    def __enter__(self) -> Lock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "runner": RUNNER_ID,
                "acquired_at_utc": iso(now_ms()),
            }
        ).encode("utf-8")
        try:
            handle = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing = read_json(self.path) or {}
            age = now_ms() / 1000 - self.path.stat().st_mtime
            if age <= self.stale_seconds:
                raise LockHeld(
                    f"{self.path} is held by pid {existing.get('pid')} since "
                    f"{existing.get('acquired_at_utc')} ({int(age)} s old)"
                ) from None
            self.taken_over = {"previous": existing, "age_seconds": int(age)}
            self.path.unlink(missing_ok=True)
            handle = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        return self

    def __exit__(self, *exc: object) -> None:
        self.path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# the delegated commands
# --------------------------------------------------------------------------- #


def run_command(
    repo: Path,
    argv: list[str],
    *,
    timeout: int,
    cwd: Path | None = None,
    log_dir: Path | None = None,
    log_name: str | None = None,
) -> dict[str, Any]:
    """Run one command and record everything a reader needs to repeat it.

    The full stdout and stderr are written to the run's own log directory when one is
    given: the tail in the report is a convenience, the log on disk is the evidence.
    """
    started = time.perf_counter()
    completed = subprocess.run(
        argv,
        cwd=str(cwd or repo),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    result = {
        "command": " ".join(argv),
        "exit_code": completed.returncode,
        "duration_s": round(time.perf_counter() - started, 3),
        "stdout": tail(completed.stdout),
        "stderr": tail(completed.stderr),
    }
    if log_dir is not None and log_name:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{log_name}.log"
        log_path.write_text(
            f"$ {result['command']}\n"
            f"exit_code: {result['exit_code']}\n"
            f"duration_s: {result['duration_s']}\n"
            f"--- stdout ---\n{completed.stdout}\n"
            f"--- stderr ---\n{completed.stderr}\n",
            encoding="utf-8",
        )
        result["log"] = log_path.name
    return result


def observe(repo: Path, *, timeout: int, log_dir: Path | None = None) -> dict[str, Any]:
    """One tick of the authorised forward observer.

    The runner never fetches a bar itself. The observer is the documented entry point
    of the lane the declaration names, it holds its own lease, and it appends to the same
    store the extractor reads.
    """
    return run_command(
        repo, [sys.executable, OBSERVER], timeout=timeout,
        log_dir=log_dir, log_name="observation",
    )


def preflight(
    repo: Path, out_dir: Path, *, timeout: int, log_dir: Path | None = None
) -> dict[str, Any]:
    """The ten provenance controls, run into this package's own directory.

    ``--out-dir`` keeps the sealed 02E artefacts read-only: the same program, a
    different output directory.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result = run_command(
        repo,
        [sys.executable, PREFLIGHT, "--out-dir", str(out_dir)],
        timeout=timeout,
        log_dir=log_dir, log_name="preflight",
    )
    report = read_json(out_dir / "WP_051_02E_PREFLIGHT.json") or {}
    result["preflight_status"] = report.get("status")
    result["controls"] = len(report.get("checks") or [])
    result["failed_controls"] = report.get("failed_controls") or []
    result["out_dir"] = out_dir.relative_to(repo).as_posix()
    return result


def verify_02f(
    repo: Path,
    out_dir: Path,
    *,
    timeout: int,
    report_name: str = CLAIM_REPORT,
    log_dir: Path | None = None,
) -> dict[str, Any]:
    """The independent verifier, run as a separate process.

    A separate process is the whole point: the verifier must not be able to read the
    runner's verdict, and the runner must not be able to grade its own work. Its output
    goes to this run's own directory; the sealed 02E artefacts are read, never written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / VERIFICATION_REPORT
    result = run_command(
        repo,
        [
            sys.executable,
            VERIFIER_02F,
            "--run-dir",
            str(out_dir),
            "--report",
            report_name,
            "--out",
            str(out_path),
        ],
        timeout=timeout,
        log_dir=log_dir, log_name="verify_02f",
    )
    payload = read_json(out_path) or {}
    result["verifier_status"] = payload.get("status")
    result["verifier_report"] = report_name
    result["out"] = out_path.relative_to(repo).as_posix() if out_path.is_relative_to(repo) else out_path.as_posix()
    return result


def capture(
    repo: Path, slice_: Slice, *, timeout: int, log_dir: Path | None = None
) -> dict[str, Any]:
    """The declared command, verbatim.

    The declaration's ``generator_command`` is used as it stands: no new flag, no
    reordered argument, no different window. The runner has no business widening the
    contract of a frozen extractor.
    """
    argv = [sys.executable, GENERATOR, "--slice", slice_.spec]
    result = run_command(
        repo, argv, timeout=timeout,
        log_dir=log_dir, log_name=f"capture_{slice_.spec.replace(':', '_')}",
    )
    result["slice"] = slice_.spec
    result["dataset_id"] = slice_.dataset_id
    result["declared_command"] = slice_.generator_command
    result["exit_meaning"] = CAPTURE_EXIT.get(result["exit_code"], "UNKNOWN")
    target = repo / slice_.normalized_file
    result["dataset_path"] = slice_.normalized_file
    result["dataset_exists"] = target.is_file()
    result["dataset_sha256"] = sha256_file(target) if target.is_file() else None
    result["dataset_bytes"] = target.stat().st_size if target.is_file() else 0
    manifest = target.parent / f"{slice_.dataset_id}.MANIFEST.json"
    result["manifest_path"] = manifest.relative_to(repo).as_posix()
    result["manifest_exists"] = manifest.is_file()
    return result


# --------------------------------------------------------------------------- #
# the temporal guard
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class GuardVerdict:
    verdict: str
    rows: int = 0
    violations: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "rows": self.rows,
            "violations": self.violations,
            "metrics": self.metrics,
        }


def temporal_guard(
    repo: Path,
    slice_: Slice,
    declaration: Declaration,
    *,
    decision_ms: int,
    now_at_guard_ms: int,
) -> GuardVerdict:
    """Read the published bytes and decide whether they may be called admissible.

    This is the read-only answer to ``DEF-02E-01``/``L-01``. The frozen extractor marks
    a bar eligible when it was fetched at or after ``effective_from_utc`` and opens
    inside the window; it never asks whether the bar claims to have been ingested after
    the capture was decided. A row that claims to come from the future cannot be
    observed, so a dataset that contains one is quarantined: it stays on disk, it is
    named, and it is not admitted.

    Nothing is edited and nothing is deleted. The guard has no write access to the
    dataset directory at all.
    """
    verdict = GuardVerdict(verdict="PASS")
    target = repo / slice_.normalized_file
    if not target.is_file():
        verdict.verdict = "NOT_PUBLISHED"
        verdict.violations.append(
            {
                "code": "DATASET_ABSENT",
                "detail": f"{slice_.normalized_file} does not exist; nothing to check",
            }
        )
        return verdict

    rows: list[dict[str, Any]] = []
    for number, line in enumerate(target.read_bytes().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            verdict.verdict = "QUARANTINE"
            verdict.violations.append(
                {"code": "ROW_NOT_JSON", "detail": f"line {number}: {error}"}
            )
            continue
        rows.append(row)

    verdict.rows = len(rows)
    span = INTERVAL_MS[slice_.interval]
    opens: list[int] = []
    for number, row in enumerate(rows, start=1):
        try:
            open_ms = int(row["ts"])
            fetched_ms = int(row["fetched_at_ms"])
        except (KeyError, TypeError, ValueError):
            verdict.verdict = "QUARANTINE"
            verdict.violations.append(
                {"code": "ROW_INCOMPLETE", "detail": f"line {number} lacks ts/fetched_at_ms"}
            )
            continue
        opens.append(open_ms)
        close_ms = open_ms + span
        checks = (
            ("OUTSIDE_DECLARED_WINDOW", not declaration.window_start_ms <= open_ms < declaration.window_end_ms,
             f"bar opens {iso(open_ms)}"),
            ("INGEST_BEFORE_EFFECTIVE", fetched_ms < declaration.effective_from_ms,
             f"bar claims to have been ingested {iso(fetched_ms)}"),
            ("INGEST_AFTER_DECISION", fetched_ms > decision_ms,
             f"bar claims to have been ingested {iso(fetched_ms)}, after the capture decision "
             f"{iso(decision_ms)}"),
            ("INGEST_AFTER_NOW", fetched_ms > now_at_guard_ms,
             f"bar claims to have been ingested {iso(fetched_ms)}, after the guard's own clock "
             f"{iso(now_at_guard_ms)}"),
            ("CLOSE_AFTER_DECISION", close_ms > decision_ms,
             f"bar closes {iso(close_ms)}, after the capture decision {iso(decision_ms)}"),
            ("NEGATIVE_LAG", fetched_ms < close_ms,
             f"bar is ingested {close_ms - fetched_ms} ms before it closes"),
        )
        for code, failed, detail in checks:
            if failed:
                verdict.verdict = "QUARANTINE"
                verdict.violations.append(
                    {"code": code, "detail": detail, "line": number, "ts": open_ms}
                )

    if len(set(opens)) != len(opens):
        verdict.verdict = "QUARANTINE"
        verdict.violations.append(
            {"code": "DUPLICATE_BAR_OPEN", "detail": f"{len(opens) - len(set(opens))} repeated open instant(s)"}
        )
    if opens != sorted(opens):
        verdict.verdict = "QUARANTINE"
        verdict.violations.append(
            {"code": "OUT_OF_ORDER", "detail": "the rows are not ordered by bar open"}
        )

    if rows:
        lags = [int(row["fetched_at_ms"]) - (int(row["ts"]) + span) for row in rows]
        verdict.metrics = {
            "min_lag_ms": min(lags),
            "max_lag_ms": max(lags),
            "lag_bound_ms": slice_.lag_bound_ms,
            "bars_outside_lag_bound": sum(
                1 for lag in lags if slice_.lag_bound_ms and not 0 <= lag <= slice_.lag_bound_ms
            ),
            "coverage_required": slice_.coverage_required,
            "rows_in_source": None,
        }
    return verdict


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #


def capture_ok(item: dict[str, Any]) -> bool:
    """A slice counts as captured only if it exited 0 *and* wrote its dataset.

    An exit code of 0 without a dataset on disk is the false success the failure
    matrix names, and it is not a success here. A dataset that was already published
    counts too: the extractor writes one once and refuses to regenerate it, so a
    second attempt over it is a no-op rather than a new capture.
    """
    if item.get("exit_code") not in (0, None):
        return False
    return bool(item.get("dataset_exists"))


def count_rows(path: Path) -> int:
    """Non-empty lines, which is the number of bars the file actually holds."""
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_bytes().splitlines() if line.strip())


def coverage_status(published: int, declared: int, required: float) -> str:
    """Name the shortfall instead of averaging it away.

    ``coverage_required`` is the declaration's own threshold for the dataset it promises over
    the *whole* declared period. The frozen extractor does not enforce it and writes a dataset
    once, so a capture taken before that period has elapsed freezes a short file permanently.
    The dataset is still the store's bytes and still temporally admissible; what it is not is
    the dataset the declaration describes, and this function is where that is said out loud.
    """
    if published <= 0:
        return "NOT_PUBLISHED"
    if declared <= 0:
        return "DECLARED_COUNT_UNKNOWN"
    return "AT_LEAST_DECLARED" if published / declared >= required > 0 else "BELOW_DECLARED"


def dataset_inventory(repo: Path, declaration: Declaration) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for slice_ in declaration.slices:
        target = repo / slice_.normalized_file
        manifest = target.parent / f"{slice_.dataset_id}.MANIFEST.json"
        published = count_rows(target)
        inventory.append(
            {
                "dataset_id": slice_.dataset_id,
                "slice": slice_.spec,
                "dataset_path": slice_.normalized_file,
                "exists": target.is_file(),
                "bytes": target.stat().st_size if target.is_file() else 0,
                "sha256": sha256_file(target) if target.is_file() else None,
                "published_rows": published,
                "declared_row_count": slice_.declared_row_count,
                "declared_coverage_required": slice_.coverage_required,
                "fraction_of_declared": (
                    round(published / slice_.declared_row_count, 6)
                    if slice_.declared_row_count > 0
                    else None
                ),
                "coverage_status": coverage_status(
                    published, slice_.declared_row_count, slice_.coverage_required
                ),
                "manifest_exists": manifest.is_file(),
                "manifest_sha256": sha256_file(manifest) if manifest.is_file() else None,
            }
        )
    return inventory


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    """Write a JSON artefact and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def relative_to_repo(repo: Path, path: Path) -> str:
    """A path as the repository writes it, so a report names the file, not the machine."""
    if path.is_relative_to(repo):
        return path.relative_to(repo).as_posix()
    return path.as_posix()


def build_report(
    repo: Path,
    declaration: Declaration,
    *,
    mode: str,
    state: str,
    started_at_ms: int,
    steps: list[dict[str, Any]],
    store: list[SeriesState],
    captures: list[dict[str, Any]],
    guards: list[dict[str, Any]],
    decision_ms: int | None,
    notes: list[str],
    run_id: str | None = None,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    generator = repo / GENERATOR
    frozen_generator = declaration.document.get("generator") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "runner": RUNNER_ID,
        "rfc": "RFC-EXP004A-051-02F",
        "mode": mode,
        "run_id": run_id,
        "run_dir": relative_to_repo(repo, run_dir) if run_dir else None,
        "state": state,
        "started_at_utc": iso(started_at_ms),
        "finished_at_utc": iso(now_ms()),
        "head": git(repo, "rev-parse", "HEAD"),
        "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "platform": platform.platform(),
        "declaration": {
            "path": DECLARATION,
            "declaration_id": declaration.document.get("declaration_id"),
            "worktree_sha256": declaration.sha256,
            "git_blob_sha": declaration.blob_sha,
            "commit": declaration.commit,
            "effective_from_utc": iso(declaration.effective_from_ms),
            "hash_note": (
                "worktree_sha256 hashes the bytes in this checkout; git_blob_sha is the "
                "Git object id at HEAD. They are different magnitudes and a CRLF "
                "checkout of an LF blob makes them differ without any drift in the "
                "committed content."
            ),
        },
        "generator": {
            "path": GENERATOR,
            "worktree_sha256": sha256_file(generator) if generator.is_file() else None,
            "git_blob_sha": git_blob_sha(repo, GENERATOR),
            "frozen_commit": frozen_generator.get("commit"),
            "frozen_blob_sha256": frozen_generator.get("blob_sha256"),
        },
        "capture_window": {
            "start_utc": iso(declaration.window_start_ms),
            "end_utc": iso(declaration.window_end_ms),
            "state_at_run": window_state(declaration, now_ms()),
        },
        "capture_decision_at_utc": iso(decision_ms) if decision_ms else None,
        "steps": steps,
        "store": [item.as_dict() for item in store],
        "captures": captures,
        "temporal_guards": guards,
        "datasets": dataset_inventory(repo, declaration),
        "deferred_slices": list(declaration.deferred),
        "notes": notes,
        "gates": {
            "C_004": "PASS",
            "C_013": "TIME_PROOF_WEAK",
            "C_015": "PASS (provenance of the declaration chain); unchanged by this runner",
            "C_016": "UNREACHABLE_UNDER_DECLARED_COST_MODEL",
            "PAPER_VALIDATION": "NOT_PASS",
            "CERTIFICATION": "BLOCKED",
            "PROMOTION": "NO_PROMOTION",
        },
        "economic_executions": 0,
        "not_a_certification": (
            "this runner moves bytes and names reasons. It does not admit a day, does not "
            "recompute cost, does not validate a strategy and does not promote anything."
        ),
    }


def finish(
    repo: Path,
    declaration: Declaration,
    run_dir: Path,
    *,
    mode: str,
    state: str,
    exit_code: int,
    started_at_ms: int,
    steps: list[dict[str, Any]],
    store: list[SeriesState],
    captures: list[dict[str, Any]],
    guards: list[dict[str, Any]],
    decision_ms: int | None,
    notes: list[str],
    timeout: int,
    run_id: str,
) -> tuple[int, dict[str, Any]]:
    """Write the claim, have it checked independently, and return the attempt's verdict.

    The claim goes to disk *before* the verifier runs, because the verifier reads that
    exact file: a verifier handed a file the runner has not written yet verifies
    nothing, and one handed a different file than the reader sees verifies something
    else. The report that comes back names the claim's digest, so a reader can prove
    which bytes were checked.

    Every attempt gets a verdict, including the ones that published nothing. A pending
    attempt with an independent witness is a different thing from a pending attempt
    nobody checked, and only the first one is evidence.
    """
    claim = build_report(
        repo, declaration, mode=mode, state=state, started_at_ms=started_at_ms,
        steps=steps, store=store, captures=captures, guards=guards,
        decision_ms=decision_ms, notes=notes, run_id=run_id, run_dir=run_dir,
    )
    below = [
        item
        for item in claim.get("datasets") or []
        if item.get("coverage_status") == "BELOW_DECLARED"
    ]
    if below:
        claim.setdefault("notes", []).append(
            "these datasets hold fewer bars than the declaration promises over its whole "
            f"period: {[(item['dataset_id'], item['published_rows'], item['declared_row_count']) for item in below]}. "
            "The frozen extractor writes a dataset once and does not enforce the declared "
            "coverage, so the file cannot be extended by running it again. The published rows "
            "are the store's own rows and are admissible; the *dataset the declaration "
            "describes* is not complete, and this attempt does not claim it is."
        )
    claim_path = write_json(run_dir / CLAIM_REPORT, claim)
    claim_sha256 = sha256_file(claim_path)

    verifier = verify_02f(
        repo, run_dir, timeout=timeout, report_name=CLAIM_REPORT, log_dir=run_dir / "logs"
    )
    verifier["step"] = "independent_verification"
    verifier["claim"] = {
        "path": relative_to_repo(repo, claim_path),
        "sha256": claim_sha256,
    }
    steps.append(verifier)
    verdict = str(verifier.get("verifier_status") or "UNKNOWN")

    final_state = state
    final_exit = exit_code
    if verdict == "FAIL":
        if state != STATE_QUARANTINED:
            final_state = STATE_BLOCKED
            final_exit = EXIT_BLOCKED
        notes.append(
            "the independent verifier refused the claim (exit "
            f"{verifier.get('exit_code')}); its checks are in {VERIFICATION_REPORT}"
        )
    elif verdict == "BLOCKED":
        if state == STATE_INDEPENDENT_VERIFY:
            # The attempt claims a capture and the verifier could not complete its
            # controls. A claim that nobody could check is not a claim that stands.
            final_state = STATE_BLOCKED
            final_exit = EXIT_BLOCKED
        notes.append(
            "the independent verifier could not complete every control; the attempt's own "
            "state stands and the incomplete control is named in the verification report"
        )
    elif state == STATE_INDEPENDENT_VERIFY:
        final_state = STATE_CAPTURED_VERIFIED
        final_exit = EXIT_OK
        notes.append(
            "the independent verifier passed the claim: the published bytes are the "
            "store's own bytes and every row is temporally admissible"
        )
    else:
        notes.append(
            "the independent verifier passed the claim: the attempt published what it "
            "said it published, and nothing it did not say"
        )

    report = build_report(
        repo, declaration, mode=mode, state=final_state, started_at_ms=started_at_ms,
        steps=steps, store=store, captures=captures, guards=guards,
        decision_ms=decision_ms, notes=notes, run_id=run_id, run_dir=run_dir,
    )
    report["independent_verification"] = verdict
    report["verified_claim"] = {
        "path": relative_to_repo(repo, claim_path),
        "sha256": claim_sha256,
        "claimed_state": state,
        "verifier_status": verdict,
        "verifier_exit_code": verifier.get("exit_code"),
        "verifier_report": relative_to_repo(repo, run_dir / VERIFICATION_REPORT),
    }
    return final_exit, report


def run_once(
    repo: Path,
    out_dir: Path,
    *,
    timeout: int,
    retries: int,
    skip_observation: bool,
) -> tuple[int, dict[str, Any]]:
    """One authorised attempt, end to end, with its own sealed artefacts.

    The attempt writes into its own directory under ``<package>/evidence/<run_id>/``.
    Two attempts never share a directory, so a seal is never overwritten by a later
    attempt, and the reader can see every attempt that was ever made.
    """
    code, report = attempt(
        repo,
        out_dir,
        timeout=timeout,
        retries=retries,
        skip_observation=skip_observation,
    )
    run_dir = out_dir / EVIDENCE_DIR / str(report.get("run_id"))
    write_run_artifacts(repo, out_dir, run_dir, report, code)
    return code, report


def write_run_artifacts(
    repo: Path, out_dir: Path, run_dir: Path, report: dict[str, Any], exit_code: int
) -> None:
    """Write the attempt's own report and move the package's pointer forward.

    The pointer is a pointer, not a seal: it names the most recent attempt and it is
    overwritten on purpose. The seal is ``--seal``, and it refuses to overwrite a
    seal that belongs to another attempt.
    """
    write_json(run_dir / RUN_REPORT, report)
    (run_dir / RUN_REPORT_MD).write_text(render_run_report_md(report), encoding="utf-8")
    write_json(
        out_dir / LATEST_RUN,
        {
            "run_id": report.get("run_id"),
            "run_dir": relative_to_repo(repo, run_dir),
            "state": report.get("state"),
            "independent_verification": report.get("independent_verification"),
            "started_at_utc": report.get("started_at_utc"),
            "finished_at_utc": report.get("finished_at_utc"),
            "head": report.get("head"),
            "exit_code": exit_code,
        },
    )


def attempt(
    repo: Path,
    out_dir: Path,
    *,
    timeout: int,
    retries: int,
    skip_observation: bool,
) -> tuple[int, dict[str, Any]]:
    """One authorised attempt, end to end.

    The attempt writes into its own directory under ``<package>/evidence/<run_id>/``.
    Two attempts never share a directory, so a seal is never overwritten by a later
    attempt, and the reader can see every attempt that was ever made.
    """
    started_at_ms = now_ms()
    run_id = new_run_id(started_at_ms)
    run_dir = out_dir / EVIDENCE_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    steps: list[dict[str, Any]] = []
    notes: list[str] = []
    captures: list[dict[str, Any]] = []
    guards: list[dict[str, Any]] = []
    decision_ms: int | None = None
    state = STATE_NOT_DUE

    declaration = load_declaration(repo)
    store = [read_series_state(slice_, declaration) for slice_ in declaration.slices]

    # -- 1. the observation ------------------------------------------------- #
    if skip_observation:
        steps.append(
            {
                "step": "observation",
                "skipped": True,
                "reason": "--skip-observation was given; the store was not refreshed",
            }
        )
    else:
        observation = observe(repo, timeout=timeout, log_dir=run_dir / "logs")
        observation["step"] = "observation"
        steps.append(observation)
        store = [read_series_state(slice_, declaration) for slice_ in declaration.slices]
        if observation["exit_code"] != 0:
            notes.append(
                f"the authorised observer returned exit {observation['exit_code']}; the store was "
                "read afterwards regardless, and the freshness check below decides what that means"
            )

    # -- 2. the window ------------------------------------------------------ #
    at_ms = now_ms()
    wstate = window_state(declaration, at_ms)
    steps.append(
        {
            "step": "window",
            "state": wstate,
            "instant_utc": iso(at_ms),
            "seconds_until_open": max(0, (declaration.window_start_ms - at_ms) // 1000),
        }
    )
    if wstate == "BEFORE_WINDOW":
        state = STATE_NOT_DUE
        notes.append(
            "the declared window has not opened; no bar can open inside it, so the extractor "
            "would refuse with an empty selection and there is nothing to capture"
        )
        return finish(
            repo, declaration, run_dir, mode="once", state=state, exit_code=EXIT_PENDING,
            started_at_ms=started_at_ms, steps=steps, store=store, captures=captures,
            guards=guards, decision_ms=None, notes=notes, timeout=timeout, run_id=run_id,
        )
    if wstate == "AFTER_WINDOW":
        state = STATE_PENDING_DATA
        notes.append("the declared window has closed")
        return finish(
            repo, declaration, run_dir, mode="once", state=state, exit_code=EXIT_PENDING,
            started_at_ms=started_at_ms, steps=steps, store=store, captures=captures,
            guards=guards, decision_ms=None, notes=notes, timeout=timeout, run_id=run_id,
        )

    # -- 3. freshness (L-04) ------------------------------------------------ #
    fresh = [freshness(item, now_ms()) for item in store]
    steps.append({"step": "freshness", "per_series": fresh})
    if not all(item["ok"] for item in fresh):
        state = STATE_PENDING_FRESHNESS
        notes.append(
            "the store is behind the clock: an observer inside its lag bound does not prove "
            "that the last expected bar is in the store"
        )
        return finish(
            repo, declaration, run_dir, mode="once", state=state, exit_code=EXIT_PENDING,
            started_at_ms=started_at_ms, steps=steps, store=store, captures=captures,
            guards=guards, decision_ms=None, notes=notes, timeout=timeout, run_id=run_id,
        )

    # -- 4. eligibility ----------------------------------------------------- #
    eligible = [item for item in store if item.closed_bars_in_window > 0]
    steps.append(
        {
            "step": "eligibility",
            "series_with_closed_in_window_bars": [item.spec for item in eligible],
            "per_series_closed_bars": {item.spec: item.closed_bars_in_window for item in store},
        }
    )
    if not eligible:
        state = STATE_PENDING_DATA
        notes.append(
            "no closed bar opens inside the declared window yet; the extractor would refuse "
            "with an empty selection, and no dataset is written"
        )
        return finish(
            repo, declaration, run_dir, mode="once", state=state, exit_code=EXIT_PENDING,
            started_at_ms=started_at_ms, steps=steps, store=store, captures=captures,
            guards=guards, decision_ms=None, notes=notes, timeout=timeout, run_id=run_id,
        )

    # -- 5. the provenance controls ----------------------------------------- #
    pre = preflight(repo, run_dir / "reused_preflight", timeout=timeout, log_dir=run_dir / "logs")
    steps.append(pre)
    pre_status = str(pre.get("preflight_status") or "UNKNOWN")
    failed_controls = list(pre.get("failed_controls") or [])
    if pre_status not in PREFLIGHT_ACCEPTED or failed_controls:
        state = STATE_BLOCKED_INTEGRITY
        notes.append(
            f"the provenance controls did not pass: status {pre_status!r}, failed controls "
            f"{failed_controls or 'none named'}; the freeze or the contract does not bind, and "
            "nothing is captured"
        )
        return finish(
            repo, declaration, run_dir, mode="once", state=state, exit_code=EXIT_BLOCKED,
            started_at_ms=started_at_ms, steps=steps, store=store, captures=captures,
            guards=guards, decision_ms=None, notes=notes, timeout=timeout, run_id=run_id,
        )

    # -- 6. the capture ------------------------------------------------------ #
    state = STATE_CAPTURE_ATTEMPTED
    attempts = 0
    for slice_ in declaration.slices:
        target = repo / slice_.normalized_file
        if target.is_file():
            # The extractor writes a dataset once and refuses to regenerate it. A second
            # run over an existing dataset is not a failure and not a new capture.
            captures.append(
                {
                    "slice": slice_.spec,
                    "dataset_id": slice_.dataset_id,
                    "declared_command": slice_.generator_command,
                    "exit_code": None,
                    "exit_meaning": "ALREADY_PUBLISHED",
                    "dataset_path": slice_.normalized_file,
                    "dataset_exists": True,
                    "dataset_sha256": sha256_file(target),
                    "dataset_bytes": target.stat().st_size,
                    "manifest_exists": (target.parent / f"{slice_.dataset_id}.MANIFEST.json").is_file(),
                }
            )
            continue
        attempt = 0
        while True:
            attempt += 1
            attempts += 1
            result = capture(repo, slice_, timeout=timeout, log_dir=run_dir / "logs")
            result["attempt"] = attempt
            # Only a source that could not be read is worth another try. A contract
            # refusal, an empty selection and a not-eligible verdict are decisions.
            if result["exit_code"] == 4 and attempt <= retries:
                result["retry"] = True
                time.sleep(2)
                continue
            break
        if result["exit_code"] == 0 and not result.get("dataset_exists"):
            # Exit 0 without a dataset is the false success the failure matrix names.
            # It is recorded as a failure here rather than as a capture.
            result["exit_meaning"] = "EXIT_WITHOUT_OUTPUT"
        captures.append(result)
    steps.append({"step": "capture", "attempts": attempts, "slices": len(captures)})

    # -- 7. the temporal guard ---------------------------------------------- #
    state = STATE_TEMPORAL_QUARANTINE_CHECK
    decision_ms = now_ms()
    guards = []
    quarantined = []
    for slice_ in declaration.slices:
        verdict = temporal_guard(
            repo,
            slice_,
            declaration,
            decision_ms=decision_ms,
            now_at_guard_ms=now_ms(),
        )
        guards.append({"slice": slice_.spec, **verdict.as_dict()})
        if verdict.verdict == "QUARANTINE":
            quarantined.append(slice_.spec)
    steps.append({"step": "temporal_guard", "quarantined": quarantined})

    if quarantined:
        state = STATE_QUARANTINED
        notes.append(
            "the published bytes claim an ingest that the capture decision or the guard's own "
            "clock cannot support. The dataset is left on disk as the record of a quarantined "
            "attempt; it is not deleted, and it is not admitted."
        )
        return finish(
            repo, declaration, run_dir, mode="once", state=state, exit_code=EXIT_QUARANTINED,
            started_at_ms=started_at_ms, steps=steps, store=store, captures=captures,
            guards=guards, decision_ms=decision_ms, notes=notes, timeout=timeout, run_id=run_id,
        )

    # -- 8. the independent verification ------------------------------------ #
    failed = [item for item in captures if not capture_ok(item)]
    if failed:
        state = STATE_FAILED_OR_PENDING
        notes.append(
            "the extractor did not produce a verifiable dataset for every slice: "
            + ", ".join(f"{item['slice']} exit {item['exit_code']}" for item in failed)
        )
        return finish(
            repo, declaration, run_dir, mode="once", state=state, exit_code=EXIT_FAILED,
            started_at_ms=started_at_ms, steps=steps, store=store, captures=captures,
            guards=guards, decision_ms=decision_ms, notes=notes, timeout=timeout, run_id=run_id,
        )

    state = STATE_INDEPENDENT_VERIFY
    return finish(
        repo, declaration, run_dir, mode="once", state=state, exit_code=EXIT_OK,
        started_at_ms=started_at_ms, steps=steps, store=store, captures=captures,
        guards=guards, decision_ms=decision_ms, notes=notes, timeout=timeout, run_id=run_id,
    )


def run_check(repo: Path) -> dict[str, Any]:
    """Read the world and say what is true of it. Writes nothing at all."""
    started_at_ms = now_ms()
    declaration = load_declaration(repo)
    store = [read_series_state(slice_, declaration) for slice_ in declaration.slices]
    at_ms = now_ms()
    fresh = [freshness(item, at_ms) for item in store]
    return {
        "schema_version": SCHEMA_VERSION,
        "runner": RUNNER_ID,
        "mode": "check",
        "checked_at_utc": iso(at_ms),
        "head": git(repo, "rev-parse", "HEAD"),
        "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "window": {
            "start_utc": iso(declaration.window_start_ms),
            "end_utc": iso(declaration.window_end_ms),
            "effective_from_utc": iso(declaration.effective_from_ms),
            "state": window_state(declaration, at_ms),
            "seconds_until_open": max(0, (declaration.window_start_ms - at_ms) // 1000),
        },
        "store": [item.as_dict() for item in store],
        "freshness": fresh,
        "datasets": dataset_inventory(repo, declaration),
        "deferred_slices": list(declaration.deferred),
        "eligible_series": [
            item.spec for item in store if item.closed_bars_in_window > 0
        ],
        "started_at_utc": iso(started_at_ms),
        "economic_executions": 0,
    }


def run_resume(repo: Path, out_dir: Path) -> dict[str, Any]:
    """Reconcile what a previous run left behind, without publishing anything."""
    declaration = load_declaration(repo)
    pointer = read_json(out_dir / LATEST_RUN) or {}
    runs: list[dict[str, Any]] = []
    evidence = out_dir / EVIDENCE_DIR
    if evidence.is_dir():
        for run_dir in sorted(item for item in evidence.iterdir() if item.is_dir()):
            report = read_json(run_dir / RUN_REPORT) or {}
            runs.append(
                {
                    "run_id": run_dir.name,
                    "state": report.get("state"),
                    "independent_verification": report.get("independent_verification"),
                    "started_at_utc": report.get("started_at_utc"),
                    "finished_at_utc": report.get("finished_at_utc"),
                    "run_dir": relative_to_repo(repo, run_dir),
                }
            )
    inventory = dataset_inventory(repo, declaration)
    published = [item for item in inventory if item["exists"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "runner": RUNNER_ID,
        "mode": "resume",
        "resumed_at_utc": iso(now_ms()),
        "head": git(repo, "rev-parse", "HEAD"),
        "latest_run": pointer.get("run_id"),
        "previous_state": pointer.get("state"),
        "previous_started_at_utc": pointer.get("started_at_utc"),
        "previous_finished_at_utc": pointer.get("finished_at_utc"),
        "attempts": runs,
        "attempt_count": len(runs),
        "datasets": inventory,
        "published": [item["dataset_path"] for item in published],
        "published_count": len(published),
        "eligible_series": [
            item.spec
            for item in (read_series_state(slice_, declaration) for slice_ in declaration.slices)
            if item.closed_bars_in_window > 0
        ],
        "note": (
            "a dataset that is already on disk is not captured again: the extractor writes a "
            "dataset once and refuses to regenerate it, so a second attempt over a published "
            "dataset is a no-op, not a new capture"
        ),
        "economic_executions": 0,
    }


def render_run_report_md(report: dict[str, Any]) -> str:
    """The human-readable twin of the run report.

    It is rendered from the same dictionary that was written to disk, so the two
    cannot disagree: the markdown is a view of the JSON, not a second account of it.
    """
    lines: list[str] = []
    add = lines.append
    add(f"# WP-051-02F — run report `{report.get('run_id')}`")
    add("")
    add(f"- **state**: `{report.get('state')}`")
    add(f"- **run directory**: `{report.get('run_dir')}`")
    add(f"- **independent verification**: `{report.get('independent_verification')}`")
    add(f"- **head**: `{report.get('head')}` on `{report.get('branch')}`")
    add(f"- **started**: {report.get('started_at_utc')} — **finished**: {report.get('finished_at_utc')}")
    add(f"- **capture decision**: {report.get('capture_decision_at_utc') or 'none'}")
    declaration = report.get("declaration") or {}
    generator = report.get("generator") or {}
    add("")
    add("## The frozen inputs")
    add("")
    add("| artefact | worktree sha256 | git blob sha |")
    add("| --- | --- | --- |")
    add(
        f"| `{declaration.get('path')}` | `{declaration.get('worktree_sha256')}` | "
        f"`{declaration.get('git_blob_sha')}` |"
    )
    add(
        f"| `{generator.get('path')}` | `{generator.get('worktree_sha256')}` | "
        f"`{generator.get('git_blob_sha')}` |"
    )
    add("")
    add(
        "The two columns are different magnitudes: the first hashes the bytes in this "
        "checkout, the second is the Git object id at HEAD. A CRLF checkout of an LF "
        "blob makes them differ without any drift in the committed content."
    )
    window = report.get("capture_window") or {}
    add("")
    add("## The window")
    add("")
    add(f"- declared: `{window.get('start_utc')}` → `{window.get('end_utc')}`")
    add(f"- state at the end of the run: `{window.get('state_at_run')}`")
    add("")
    add("## The store")
    add("")
    add("| series | rows | last bar opens | last ingest | bars in window | closed in window |")
    add("| --- | --- | --- | --- | --- | --- |")
    for item in report.get("store") or []:
        add(
            f"| `{item.get('spec')}` | {item.get('rows')} | {item.get('last_open_utc')} | "
            f"{item.get('last_fetched_utc')} | {item.get('bars_in_window')} | "
            f"{item.get('closed_bars_in_window')} |"
        )
    add("")
    add("## The capture")
    add("")
    add("| slice | exit | meaning | dataset | bytes |")
    add("| --- | --- | --- | --- | --- |")
    for item in report.get("captures") or []:
        add(
            f"| `{item.get('slice')}` | {item.get('exit_code')} | {item.get('exit_meaning')} | "
            f"{item.get('dataset_path')} | {item.get('dataset_bytes')} |"
        )
    add("")
    add("## The temporal guard")
    add("")
    add("| slice | verdict | rows | violations |")
    add("| --- | --- | --- | --- |")
    for item in report.get("temporal_guards") or []:
        violations = item.get("violations") or []
        add(
            f"| `{item.get('slice')}` | {item.get('verdict')} | {item.get('rows')} | "
            f"{len(violations)} |"
        )
    for item in report.get("temporal_guards") or []:
        for violation in item.get("violations") or []:
            add(f"- `{item.get('slice')}` **{violation.get('code')}**: {violation.get('detail')}")
    add("")
    add("## The gates this package did not move")
    add("")
    for name, value in (report.get("gates") or {}).items():
        add(f"- `{name}`: {value}")
    add("")
    add("## The notes")
    add("")
    for note in report.get("notes") or []:
        add(f"- {note}")
    add("")
    add(
        "This report is not a certification, a paper validation or a promotion. "
        "`economic_executions` in the JSON twin is 0 and stays 0."
    )
    return "\n".join(lines) + "\n"


def evidence_manifest(repo: Path, out_dir: Path, run_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    """The manifest of the package: what is sealed, and what each file hashes to.

    The manifest lists every file of the package except itself, with both the SHA-256
    of the bytes on disk and — for the files Git already knows — the Git blob id. The
    two are kept apart on purpose.
    """
    entries: list[dict[str, Any]] = []
    for path in sorted(p for p in out_dir.rglob("*") if p.is_file()):
        relative = relative_to_repo(repo, path)
        if relative.endswith(EVIDENCE_MANIFEST):
            continue
        entry: dict[str, Any] = {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        blob = git_blob_sha(repo, relative)
        if blob:
            entry["git_blob_sha"] = blob
        entries.append(entry)

    # The published datasets are the artefacts the attempt exists to produce, so a manifest
    # that named only the paper about them would seal the description and not the thing.
    # Each entry carries the claim's digest beside the measured one: a seal that quietly
    # recorded one where they disagree would be attesting a file nobody checked.
    for dataset in report.get("datasets") or []:
        relative = str(dataset.get("dataset_path") or "")
        if not relative:
            continue
        path = repo / relative
        if not path.is_file():
            entries.append(
                {
                    "path": relative,
                    "role": "dataset",
                    "present": False,
                    "claimed_sha256": dataset.get("sha256"),
                }
            )
            continue
        digest = sha256_file(path)
        entries.append(
            {
                "path": relative,
                "role": "dataset",
                "present": True,
                "bytes": path.stat().st_size,
                "sha256": digest,
                "claimed_sha256": dataset.get("sha256"),
                "matches_claim": digest == dataset.get("sha256"),
            }
        )
        extractor_manifest = path.parent / f"{dataset.get('dataset_id')}.MANIFEST.json"
        if extractor_manifest.is_file():
            entries.append(
                {
                    "path": relative_to_repo(repo, extractor_manifest),
                    "role": "dataset_manifest",
                    "present": True,
                    "bytes": extractor_manifest.stat().st_size,
                    "sha256": sha256_file(extractor_manifest),
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "runner": RUNNER_ID,
        "rfc": "RFC-EXP004A-051-02F",
        "sealed_at_utc": iso(now_ms()),
        "head": git(repo, "rev-parse", "HEAD"),
        "run_id": report.get("run_id"),
        "run_dir": relative_to_repo(repo, run_dir),
        "state": report.get("state"),
        "independent_verification": report.get("independent_verification"),
        "hash_semantics": (
            "sha256 hashes the bytes in this checkout; git_blob_sha is the Git object id "
            "at HEAD. They are different magnitudes and are never presented as the same one."
        ),
        "entries": entries,
        "entry_count": len(entries),
        "not_a_certification": (
            "a manifest says what is in the package. It does not say the package is right, "
            "and it does not promote anything."
        ),
    }


def latest_run_dir(out_dir: Path) -> Path | None:
    """The most recent run directory, or ``None`` when no attempt has been made."""
    evidence = out_dir / EVIDENCE_DIR
    if not evidence.is_dir():
        return None
    candidates = sorted(item for item in evidence.iterdir() if item.is_dir())
    return candidates[-1] if candidates else None


def seal(repo: Path, out_dir: Path, run_id: str | None) -> tuple[int, dict[str, Any]]:
    """Promote one run to the package's sealed artefacts.

    The seal refuses to overwrite a seal that belongs to another run: a package whose
    evidence changes underneath the reader is worse than a package with no seal.
    """
    run_dir = out_dir / EVIDENCE_DIR / run_id if run_id else latest_run_dir(out_dir)
    if run_dir is None or not run_dir.is_dir():
        return EXIT_FAILED, {"ok": False, "error": "there is no run to seal"}
    report = read_json(run_dir / RUN_REPORT)
    if report is None:
        return EXIT_FAILED, {"ok": False, "error": f"{run_dir.name} has no run report"}
    manifest_path = out_dir / EVIDENCE_MANIFEST
    existing = read_json(manifest_path) or {}
    if existing and existing.get("run_id") != report.get("run_id"):
        return EXIT_BLOCKED, {
            "ok": False,
            "error": (
                f"a seal for run {existing.get('run_id')} already exists; sealing "
                f"{report.get('run_id')} would overwrite it. Remove the seal deliberately "
                "if that is what you mean."
            ),
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / RUN_REPORT, report)
    verification = read_json(run_dir / VERIFICATION_REPORT)
    if verification is not None:
        write_json(out_dir / VERIFICATION_REPORT, verification)
    (out_dir / RUN_REPORT_MD).write_text(render_run_report_md(report), encoding="utf-8")
    manifest = evidence_manifest(repo, out_dir, run_dir, report)
    write_json(manifest_path, manifest)
    return EXIT_OK, {
        "ok": True,
        "run_id": report.get("run_id"),
        "state": report.get("state"),
        "independent_verification": report.get("independent_verification"),
        "sealed": [
            relative_to_repo(repo, out_dir / RUN_REPORT),
            relative_to_repo(repo, out_dir / RUN_REPORT_MD),
            relative_to_repo(repo, out_dir / VERIFICATION_REPORT),
            relative_to_repo(repo, manifest_path),
        ],
        "entry_count": manifest["entry_count"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="read the world; write nothing")
    mode.add_argument("--once", action="store_true", help="one authorised attempt")
    mode.add_argument("--resume", action="store_true", help="reconcile a previous attempt")
    mode.add_argument(
        "--seal",
        action="store_true",
        help="promote one attempt to the package's sealed artefacts (RUN_REPORT, "
        "INDEPENDENT_VERIFICATION, EVIDENCE_MANIFEST)",
    )
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--run-id", default=None, help="the attempt to seal (default: the latest)")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument(
        "--skip-observation",
        action="store_true",
        help="do not tick the authorised observer (for a rehearsal against a store that is "
        "already current)",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else repo / OUT_DIR

    if args.check:
        print(json.dumps(run_check(repo), indent=2, sort_keys=False))
        return EXIT_OK
    if args.resume:
        print(json.dumps(run_resume(repo, out_dir), indent=2, sort_keys=False))
        return EXIT_OK
    if args.seal:
        code, payload = seal(repo, out_dir, args.run_id)
        print(json.dumps(payload, indent=2, sort_keys=False))
        return code

    out_dir.mkdir(parents=True, exist_ok=True)
    lock = Lock(out_dir / LOCK_NAME)
    try:
        with lock:
            code, report = run_once(
                repo,
                out_dir,
                timeout=args.timeout,
                retries=max(0, args.retries),
                skip_observation=args.skip_observation,
            )
    except LockHeld as error:
        print(json.dumps({"ok": False, "state": "ALREADY_RUNNING", "error": str(error)}))
        return EXIT_ALREADY_RUNNING

    if lock.taken_over:
        report["lock_takeover"] = lock.taken_over
    print(
        json.dumps(
            {
                "state": report["state"],
                "exit_code": code,
                "run_id": report.get("run_id"),
                "independent_verification": report.get("independent_verification"),
            },
            sort_keys=True,
        )
    )
    for note in report.get("notes", []):
        print(f"[runner] {note}")
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
