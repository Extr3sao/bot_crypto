"""EDGE-05 — an independent watchdog that audits the WP-EDGE-04 forward lane.

WP-EDGE-04 made the lane observe by itself: the operating system's scheduler fires one tick
every fifteen minutes and the lane records what each tick did. What nothing did until now is
*watch the watcher*. A lane that stops firing, a task the scheduler disabled, a tick killed
between two writes, a store that stopped growing, a lease left behind by a dead process, a log
that has grown past its cap — every one of those is invisible from inside the lane, because the
thing that would have reported it is the thing that stopped.

This module is the second pair of eyes, and it is deliberately *not* part of the lane:

* it lives in its own state root (``data/forward/edge05``) and **never writes** to the lane's
  state root or to the forward store. It reads them and it appends to its own log;
* it holds **no lease**, runs **no pipeline**, evaluates **no strategy** and makes **zero market
  requests**. It cannot ingest a bar, cannot consume a slot and cannot publish a report;
* it is registered as its own operating-system task, so it is not kept alive by anything the lane
  does, and the lane is not kept alive by anything it does;
* its vocabulary separates a *market* that produced no new bar from an *operation* that failed to
  collect one. ``market_quiet`` and ``operational_failure`` are two booleans in every reading,
  and the verdict follows the second one.

What one check reads
--------------------
1. **the scheduler** — the repository's own supervisor is asked for the task's registration and
   its own reporting (state, last result, last run, next run, missed-run counter). A task that is
   missing, disabled or reporting a failure is a finding, and the scheduler's last-result field is
   translated through the lane's declared exit-code vocabulary;
2. **the cadence** — the newest *consuming* tick on the lane's own run log, against the declared
   fifteen-minute schedule. Silence is measured from the log, never from a counter this process
   keeps in memory: a watchdog that restarts must not restart the clock it is measuring;
3. **the data** — per series, the newest stored bar from the store's own tail, against the newest
   bar that had closed by the last tick's market instant and by now. This is what separates
   "nothing had closed" (the market is quiet) from "bars closed and are not stored" (the
   operation failed);
4. **the process** — the run log's own pid and, where the platform allows it, the process table:
   a tick the scheduler launched is told from one a person launched, and a tick that died between
   two writes is told from one that finished;
5. **the evidence** — torn lines, duplicate slot seals, a seal that names a run the log no longer
   holds, ledger rows nothing attributes to a run, and the second-pass restart proof;
6. **the resources** — free space against the campaign's own floors, and the lane's measured
   growth against two declared thresholds, so an operator is told *before* a volume fills rather
   than after;
7. **the watchdog itself** — its own previous check. A watchdog that stopped running is exactly
   the failure it exists to detect, so its own silence is a finding rather than an assumption.

Nothing here promotes anything: ``hypothetical``, ``order_sent: false`` and ``promotion: NONE``
are on every row, and the module has no path to an execution venue.

Research only: public market data, no credentials, no orders, no capital, no promotion.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.research.campaign_lock import CampaignLock
from trading_bot.research.campaign_reporting import write_json_atomic
from trading_bot.research.disk_space import CRITICAL, HEALTHY, WARNING, disk_report
from trading_bot.research.edge01.data import BAR_MS

from ..edge03.autonomous import (  # the lane's own vocabulary, reused rather than restated
    ALREADY_OBSERVED,
    ALREADY_RUNNING,
    BLOCKED_AFTER_CONSECUTIVE_FAILURES,
    DISK_BUDGET_EXCEEDED,
    EXIT_CODES,
    GAP_CRITICAL_SECONDS,
    GAP_WARNING_SECONDS,
    HEALTHY_FREE_BYTES,
    CRITICAL_FREE_BYTES,
    MISSING_BARS,
    NO_NEW_DATA,
    OBSERVED,
    PROVIDER_UNAVAILABLE,
    RUNTIME_EXCEPTION,
    SCHEDULE_INTERVAL_SECONDS,
    SLOT_CONSUMING_OUTCOMES,
    STALE_DATA,
    VERIFICATION_FAILED,
    day_key,
    read_jsonl,
    slot_key,
    slot_of,
    stamp,
)

__all__ = [
    "ALERT_KINDS",
    "CHECK_NAMES",
    "ForwardWatchdog",
    "TASK_NAME",
    "WATCHDOG_SCHEMA_VERSION",
    "WATCHDOG_TASK_NAME",
    "WATCH_BLOCKED",
    "WATCH_DEGRADED",
    "WATCH_OK",
    "WATCH_ALARM",
]

#: The lane this watchdog watches, and the task this watchdog is registered as. Two names, two
#: registrations: a watchdog that shares a task with the lane it watches is not independent.
TASK_NAME = "TradingAgentic-EDGE04-Forward"
WATCHDOG_TASK_NAME = "TradingAgentic-EDGE05-Watchdog"

WATCHDOG_SCHEMA_VERSION = "EDGE05_WATCHDOG_V1"
DAILY_SCHEMA_VERSION = "EDGE05_WATCHDOG_DAILY_V1"
SNAPSHOT_SCHEMA_VERSION = "EDGE05_SNAPSHOT_V1"

#: The verdict vocabulary. ``WATCH_OK`` is the only one that means "nothing is wrong that I can
#: see"; the other three name how wrong, and no failure is ever written as success.
WATCH_OK = "WATCH_OK"
WATCH_DEGRADED = "WATCH_DEGRADED"
WATCH_ALARM = "WATCH_ALARM"
WATCH_BLOCKED = "WATCH_BLOCKED"
VERDICT_RANK = {WATCH_OK: 0, WATCH_DEGRADED: 1, WATCH_ALARM: 2, WATCH_BLOCKED: 3}

#: What kind of trouble a reading describes. The first is not trouble; the third is the one the
#: whole work package exists for.
CATEGORY_HEALTHY = "HEALTHY"
CATEGORY_MARKET_QUIET = "MARKET_QUIET"
CATEGORY_LANE_OVERDUE = "LANE_OVERDUE"
CATEGORY_SCHEDULER_FAILURE = "SCHEDULER_FAILURE"
CATEGORY_INGEST_FAILURE = "INGEST_FAILURE"
CATEGORY_EVIDENCE_BROKEN = "EVIDENCE_BROKEN"
CATEGORY_RESOURCE_PRESSURE = "RESOURCE_PRESSURE"
CATEGORY_WATCHDOG_GAP = "WATCHDOG_SELF_GAP"

#: One name per reading, so a check can be pointed at by name and a reader can tell which part of
#: the lane is being described without knowing the implementation.
CHECK_NAMES = (
    "scheduler_task",
    "scheduler_last_result",
    "scheduler_cadence",
    "lane_cadence",
    "lane_process",
    "lane_lease",
    "market_expectation",
    "store_freshness",
    "evidence_integrity",
    "restart_proof",
    "resource_disk",
    "resource_growth",
    "watchdog_cadence",
)

STATUS_OK = "OK"
STATUS_WARN = "WARN"
STATUS_ALARM = "ALARM"
STATUS_BLOCKED = "BLOCKED"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_RANK = {
    STATUS_OK: 0,
    STATUS_UNKNOWN: 1,
    STATUS_WARN: 1,
    STATUS_ALARM: 2,
    STATUS_BLOCKED: 3,
}

#: Silence worth an alert, as a monotone ladder in units of the declared schedule. The first
#: rung is the lane's own warning bound, so the watchdog and the lane agree on what "late" means;
#: the last is the lane's own interruption bound (twelve slots), where "late" stops being the
#: right word. A ladder with a gap in it — warning at two slots, alarm at twelve — would let a
#: four-hour silence read as a warning.
CADENCE_WARN_SECONDS = GAP_WARNING_SECONDS
CADENCE_ALARM_SECONDS = 6 * SCHEDULE_INTERVAL_SECONDS
CADENCE_BLOCKED_SECONDS = GAP_CRITICAL_SECONDS

#: A tick that runs longer than its own declared limit is wedged; the OS task's limit is one hour.
TICK_WEDGED_SECONDS = 3_600.0

#: How long after its due instant the scheduler may still be "about to run". The venue needs a
#: minute to publish a closed bar; the task's repetition is a quarter of an hour.
SCHEDULER_GRACE_SECONDS = 180.0

#: Growth thresholds. The lane declares a 256 MiB budget for everything it writes outside the
#: store. Spread over the sixty days this lane exists to observe, that is 4.37 MiB/day, and the
#: measured rate is ~2 MB/day. The warning is set at 16 MiB/day (roughly four times the declared
#: budget rate) and the stop at 64 MiB/day, which consumes the whole declared budget in four days.
#: Neither number deletes anything: they are the points at which a person is told.
LANE_GROWTH_WARNING_BYTES_PER_DAY = 16 * 1024 * 1024
LANE_GROWTH_STOP_BYTES_PER_DAY = 64 * 1024 * 1024

#: The watchdog's own bounded log. One row per check, sixty days at a fifteen-minute cadence.
WATCH_KEPT = 5_760
WATCH_ALERTS_KEPT = 500
WATCH_DAILY_KEPT = 400

#: The scheduler reporting fields this module reads, named once so a reader can see the whole
#: dependency on the operating system in one place.
SCHEDULER_FIELDS = (
    "installed",
    "enabled",
    "state",
    "last_run_time",
    "last_task_result",
    "next_run_time",
    "missed_runs",
    "multiple_instances",
    "start_when_available",
)

#: Alert kinds. The lane's own list is not reused because these are the watchdog's transitions;
#: they are appended to the watchdog's own log, in the same shape the host's health watch reads.
ALERT_KINDS = (
    "WATCHDOG_DEGRADED",
    "WATCHDOG_ALARM",
    "WATCHDOG_BLOCKED",
    "WATCHDOG_RECOVERED",
    "WATCHDOG_SELF_GAP",
    "SCHEDULER_MISSING",
    "SCHEDULER_DISABLED",
    "SCHEDULER_TASK_FAILED",
    "TICK_OVERDUE",
    "TICK_WEDGED",
    "TICK_DIED_MID_WRITE",
    "INGEST_STALLED",
    "MARKET_QUIET",
    "STORE_STALE",
    "EVIDENCE_CORRUPT",
    "RESTART_PROOF_BROKEN",
    "DISK_WARNING",
    "DISK_CRITICAL",
    "DISK_RECOVERED",
    "GROWTH_BUDGET_EXCEEDED",
    "RECONCILIATION_REQUIRED",
)

#: The exit codes the scheduler's last-result field can carry, read from the lane's own table plus
#: the values Task Scheduler reports for its own failures. A code outside this map is not guessed.
#:
#: The lane's table is many-to-one — three outcomes share exit 0 — so the *primary* outcome for a
#: code is named here explicitly rather than picked by whichever key the comprehension visited
#: last: a reader of this artefact must be able to tell which name the watchdog will print.
PRIMARY_OUTCOME_FOR_CODE: dict[int, str] = {
    0: OBSERVED,
    EXIT_CODES[ALREADY_RUNNING]: ALREADY_RUNNING,
    EXIT_CODES[MISSING_BARS]: MISSING_BARS,
    EXIT_CODES[STALE_DATA]: STALE_DATA,
    EXIT_CODES[DISK_BUDGET_EXCEEDED]: DISK_BUDGET_EXCEEDED,
    EXIT_CODES[VERIFICATION_FAILED]: VERIFICATION_FAILED,
    EXIT_CODES[PROVIDER_UNAVAILABLE]: PROVIDER_UNAVAILABLE,
    EXIT_CODES[RUNTIME_EXCEPTION]: RUNTIME_EXCEPTION,
}

SCHEDULER_RESULT_VOCABULARY: dict[int, str] = {
    **PRIMARY_OUTCOME_FOR_CODE,
} | {
    # Task Scheduler's own failure codes, in the order an operator would meet them. They mean the
    # action never produced a lane exit code at all, which is a different finding from a refusal.
    0x41301: "TASK_IS_RUNNING",
    0x41303: "TASK_HAS_NOT_RUN",
    0x41306: "TASK_TERMINATED_BY_USER",
    0x80070002: "TASK_EXECUTABLE_NOT_FOUND",
    0x80070420: "TASK_SERVICE_ACCOUNT_MISMATCH",
    267009: "TASK_IS_RUNNING",
    267011: "TASK_HAS_NOT_RUN",
    267014: "TASK_TERMINATED_BY_USER",
}


# --------------------------------------------------------------------------- small helpers
def _parse_ms(value: Any) -> int | None:
    """A UTC stamp as milliseconds, or ``None`` when the value is not one. Never guesses a zone."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    text = str(value).strip()
    if not text or text.startswith("11/30/1999"):
        # Task Scheduler's "never ran" instant, in its own locale format. Reading it as a date
        # would turn "has not run" into a measurement taken in 1999.
        return None
    if text.isdigit():
        return int(text)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def _seconds_between(now_ms: int, then_ms: int | None) -> float | None:
    if then_ms is None:
        return None
    return round((now_ms - then_ms) / 1000.0, 3)


def _tail_rows(path: Path, *, keep: int, chunk_bytes: int = 262_144) -> list[dict[str, Any]]:
    """The last ``keep`` complete lines of a JSONL file, without reading the whole file.

    A torn last line is dropped, not repaired: this is a reading, and the count of torn lines is
    the evidence check's job.
    """
    if not path.is_file():
        return []
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        start = max(0, size - chunk_bytes)
        handle.seek(start)
        blob = handle.read().decode("utf-8", errors="replace")
    lines = [line for line in blob.splitlines() if line.strip()]
    if start > 0 and lines:
        lines = lines[1:]  # the first line of a tail chunk is probably a fragment
    rows: list[dict[str, Any]] = []
    for line in lines[-keep:]:
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            rows.append(loaded)
    return rows


def _count_lines(path: Path) -> tuple[int, int]:
    """``(complete rows, torn lines)`` for a JSONL file, read whole. Never raises."""
    rows, corrupt = read_jsonl(path)
    return len(rows), corrupt


def default_scheduler_probe(*, repo_root: Path, task_name: str = TASK_NAME) -> dict[str, Any]:
    """Ask the repository's own supervisor about the task. Reused, never re-implemented.

    The supervisor is a ``scripts/`` module rather than a package, so it is imported by path the
    same way the lane's entry point imports it. When the platform has no task scheduler — a POSIX
    host, a rehearsal in a temporary directory — the reading says so instead of pretending the
    task is fine.
    """
    scripts = Path(repo_root) / "scripts"
    if not (scripts / "cap004_supervisor.py").is_file():  # pragma: no cover - rehearsal only
        return {"available": False, "reason": "cap004_supervisor.py is not in this tree"}
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import cap004_supervisor as sup  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - import failure is environmental
        return {"available": False, "reason": f"importing the supervisor failed: {exc!r}"}
    try:
        status = sup.scheduler_status(task_name=task_name)
    except Exception as exc:  # pragma: no cover - the platform answered nothing
        return {"available": False, "reason": f"the scheduler query raised: {exc!r}"}
    reading = dict(status or {})
    reading["available"] = True
    if str(reading.get("scheduler_type")) == "none":
        return {"available": False, "reason": "this platform has no task scheduler"}
    if not reading.get("installed") and not reading.get("scheduler_type"):
        reading["available"] = False
        reading["reason"] = "the scheduler did not describe the task"
    return reading


def default_scheduler_instant_probe(*, task_name: str = TASK_NAME) -> dict[str, Any]:
    """The scheduler's own instants, told in a form that does not depend on the host's locale.

    The repository's supervisor asks the platform for its reporting and gets it back the way the
    platform spells it — ``10/13/2026 13:25:53``, an *unlabelled local* instant. Reading that as
    UTC, or reading the host's offset into it, is how a watchdog ends up two hours wrong and
    reports a healthy schedule as a stalled one. This probe asks the same platform for the same
    instants as round-trip ISO-8601 **in UTC**, and records the raw answer it was given.
    """
    if os.name != "nt":  # pragma: no cover - exercised only on a Windows host
        return {"available": False, "reason": "no Task Scheduler on this platform"}
    import shutil
    import subprocess

    exe = shutil.which("powershell") or "powershell"
    script = (
        f"$t = Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue; "
        "if ($null -eq $t) { '{}' } else { "
        f"$i = Get-ScheduledTaskInfo -TaskName '{task_name}'; "
        "[pscustomobject]@{ State=[string]$t.State; "
        "NextRunTime=$i.NextRunTime.ToUniversalTime().ToString('o'); "
        "LastRunTime=$i.LastRunTime.ToUniversalTime().ToString('o'); "
        "LastTaskResult=$i.LastTaskResult; NumberOfMissedRuns=$i.NumberOfMissedRuns; "
        "Now=([datetime]::UtcNow.ToString('o')); LocalOffsetMinutes=[int]([System.TimeZoneInfo]::Local.BaseUtcOffset.TotalMinutes) } "
        "| ConvertTo-Json -Compress }"
    )
    try:
        proc = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - environmental
        return {"available": False, "reason": repr(exc)}
    if proc.returncode != 0:
        return {"available": False, "reason": proc.stderr.strip()[:200]}
    text = proc.stdout.strip() or "{}"
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {"available": False, "reason": "the scheduler instant query did not answer with JSON"}
    if not isinstance(loaded, dict) or not loaded:
        return {"available": False, "reason": "the scheduler did not describe the task"}
    return {
        "available": True,
        "task_name": task_name,
        "state": loaded.get("State"),
        "next_run_utc": loaded.get("NextRunTime"),
        "last_run_utc": loaded.get("LastRunTime"),
        "last_task_result": loaded.get("LastTaskResult"),
        "missed_runs": loaded.get("NumberOfMissedRuns"),
        "queried_at_utc": loaded.get("Now"),
        "local_offset_minutes": loaded.get("LocalOffsetMinutes"),
    }


def default_process_probe(*, match: str = "edge04_observer.py") -> dict[str, Any]:
    """Read the operating system's process table for the lane's tick, best effort.

    Only used to tell a *launch* from a *person* and a live tick from a dead one. On a platform
    that cannot answer, the reading says ``available: False``; nothing is inferred from silence.
    """
    if os.name != "nt":  # pragma: no cover - only exercised on Windows hosts
        return {"available": False, "reason": "no process probe on this platform"}
    import shutil
    import subprocess

    exe = shutil.which("powershell") or "powershell"
    script = (
        "$rows = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*"
        + match
        + "*' } | Select-Object ProcessId,ParentProcessId,Name,CreationDate,CommandLine; "
        "if ($null -eq $rows) { '[]' } else { $rows | ConvertTo-Json -Compress -Depth 3 }"
    )
    try:
        proc = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - environmental
        return {"available": False, "reason": repr(exc)}
    if proc.returncode != 0:
        return {"available": False, "reason": proc.stderr.strip()[:200]}
    text = proc.stdout.strip() or "[]"
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {"available": False, "reason": "the process query did not answer with JSON"}
    rows = loaded if isinstance(loaded, list) else [loaded]
    processes: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        processes.append(
            {
                "pid": row.get("ProcessId"),
                "parent_pid": row.get("ParentProcessId"),
                "name": row.get("Name"),
                "started_at": row.get("CreationDate"),
                "command_line": row.get("CommandLine"),
            }
        )
    return {"available": True, "match": match, "processes": processes}


def _rank(verdict: str) -> int:
    return VERDICT_RANK.get(verdict, len(VERDICT_RANK))


class ForwardWatchdog:
    """One independent check of the forward lane. Reads everything, changes nothing of the lane.

    Every clock, every probe and every threshold is injectable: the tests drive the real decision
    logic over a scripted operating system, and the live check drives it over the real one.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        lane_state_root: Path | None = None,
        store_root: Path | None = None,
        state_root: Path | None = None,
        series: Sequence[tuple[str, str]] | None = None,
        task_name: str = TASK_NAME,
        scheduler_probe: Callable[[], dict[str, Any]] | None = None,
        scheduler_instant_probe: Callable[[], dict[str, Any]] | None = None,
        process_probe: Callable[[], dict[str, Any]] | None = None,
        clock: Callable[[], float] = time.time,
        host: str | None = None,
        disk_probe: Callable[[Path], dict[str, Any]] | None = None,
        warning_bytes: int = HEALTHY_FREE_BYTES,
        critical_bytes: int = CRITICAL_FREE_BYTES,
        growth_warning_bytes: int = LANE_GROWTH_WARNING_BYTES_PER_DAY,
        growth_stop_bytes: int = LANE_GROWTH_STOP_BYTES_PER_DAY,
        cadence_warn_seconds: int = CADENCE_WARN_SECONDS,
        cadence_alarm_seconds: int = CADENCE_ALARM_SECONDS,
        cadence_blocked_seconds: int = CADENCE_BLOCKED_SECONDS,
        watch_kept: int = WATCH_KEPT,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.lane_state_root = Path(
            lane_state_root
            if lane_state_root is not None
            else self.repo_root / "data" / "forward" / "edge04"
        )
        self.store_root = Path(
            store_root
            if store_root is not None
            else self.repo_root / "data" / "forward" / "edge03"
        )
        self.state_root = Path(
            state_root if state_root is not None else self.repo_root / "data" / "forward" / "edge05"
        )
        self.series: tuple[tuple[str, str], ...] = tuple(
            series
            or (("1h", "BTC"), ("1h", "ETH"), ("1h", "SOL"), ("15m", "BTC"), ("15m", "ETH"), ("15m", "SOL"))
        )
        self.task_name = task_name
        self._scheduler_probe = scheduler_probe or (
            lambda: default_scheduler_probe(repo_root=self.repo_root, task_name=task_name)
        )
        self._scheduler_instant_probe = scheduler_instant_probe or (
            lambda: default_scheduler_instant_probe(task_name=task_name)
        )
        self._process_probe = process_probe or default_process_probe
        self._clock = clock
        self.host = host or socket.gethostname()
        self._disk_probe = disk_probe
        self.warning_bytes = int(warning_bytes)
        self.critical_bytes = int(critical_bytes)
        self.growth_warning_bytes = int(growth_warning_bytes)
        self.growth_stop_bytes = int(growth_stop_bytes)
        self.cadence_warn_seconds = int(cadence_warn_seconds)
        self.cadence_alarm_seconds = int(cadence_alarm_seconds)
        self.cadence_blocked_seconds = int(cadence_blocked_seconds)
        self.watch_kept = int(watch_kept)

    # -- layout ------------------------------------------------------------ #
    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    @property
    def watch_path(self) -> Path:
        return self.state_root / "watchdog.jsonl"

    @property
    def latest_path(self) -> Path:
        return self.state_root / "LATEST.json"

    @property
    def alerts_path(self) -> Path:
        return self.state_root / "watch_alerts.jsonl"

    @property
    def install_path(self) -> Path:
        return self.state_root / "install.json"

    @property
    def daily_dir(self) -> Path:
        return self.state_root / "daily"

    @property
    def snapshots_dir(self) -> Path:
        return self.state_root / "snapshots"

    # -- the lane's evidence, read only ------------------------------------ #
    def lane_runs(self) -> list[dict[str, Any]]:
        rows, _corrupt = read_jsonl(self.lane_state_root / "runs.jsonl")
        return rows

    def lane_slots(self) -> list[dict[str, Any]]:
        rows, _corrupt = read_jsonl(self.lane_state_root / "slots.jsonl")
        return rows

    def lane_ledger(self) -> list[dict[str, Any]]:
        rows, _corrupt = read_jsonl(self.lane_state_root / "ledger" / "INGEST_LEDGER.jsonl")
        return rows

    def lane_lease(self) -> dict[str, Any]:
        """The lane's lease, read through the repository's own lock idiom rather than re-parsed."""
        holder = self._lane_lock().holder()
        return dict(holder) if holder else {}

    def _lane_lock(self) -> CampaignLock:
        return CampaignLock(
            self.lane_state_root / "lock",
            campaign_id="EDGE04_FORWARD_OBSERVER",
            stale_after_seconds=300,
        )

    def consuming_runs(self, runs: Iterable[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """The ticks that actually consumed a slot, in the order the log holds them."""
        rows = list(runs if runs is not None else self.lane_runs())
        return [row for row in rows if str(row.get("outcome")) in SLOT_CONSUMING_OUTCOMES]

    def newest_stored_bar(self, timeframe: str, symbol: str) -> dict[str, Any] | None:
        """The store's own tail for one series: the newest bar, and when it was fetched."""
        path = self.store_root / timeframe / f"{symbol.upper()}.jsonl"
        rows = _tail_rows(path, keep=2)
        if not rows:
            return None
        row = rows[-1]
        return {
            "ts": int(row["ts"]),
            "fetched_at_ms": row.get("fetched_at_ms"),
            "closed": bool(row.get("closed")),
        }

    def store_counts(self) -> dict[str, int]:
        return {
            f"{timeframe}:{symbol}": _count_lines(
                self.store_root / timeframe / f"{symbol.upper()}.jsonl"
            )[0]
            for timeframe, symbol in self.series
        }

    def disk(self) -> dict[str, Any]:
        if self._disk_probe is not None:
            return self._disk_probe(self.lane_state_root)
        return disk_report(
            self.lane_state_root,
            warning_bytes=self.warning_bytes,
            critical_bytes=self.critical_bytes,
        )

    def lane_growth(self) -> dict[str, Any]:
        """The lane's own measured growth, read from the lane's own budget artefact."""
        path = self.lane_state_root / "resource_budget.json"
        reading: dict[str, Any] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                reading = loaded if isinstance(loaded, dict) else {}
            except json.JSONDecodeError:
                reading = {"corrupt": True}
        growth = reading.get("growth") or {}
        measured = reading.get("measured") or {}
        return {
            "source": str(path),
            "available": bool(reading),
            "status": growth.get("status"),
            "bytes_per_day": growth.get("bytes_per_day"),
            "mean_bytes_per_day": growth.get("mean_bytes_per_day"),
            "coefficient_of_variation": growth.get("coefficient_of_variation"),
            "samples": growth.get("samples"),
            "lane_bytes": measured.get("lane_bytes"),
            "measured_at_utc": reading.get("generated_at_utc"),
            "warning_bytes_per_day": self.growth_warning_bytes,
            "stop_bytes_per_day": self.growth_stop_bytes,
        }

    # -- checks ------------------------------------------------------------ #
    def check_scheduler_task(self) -> dict[str, Any]:
        reading = self._scheduler_probe()
        instants = self._scheduler_instant_probe()
        if not reading.get("available", True):
            return {
                "status": STATUS_UNKNOWN,
                "available": False,
                "reason": reading.get("reason") or "the scheduler could not be read",
                "task_name": self.task_name,
                "reading": reading,
            }
        installed = bool(reading.get("installed"))
        enabled = bool(reading.get("enabled"))
        state = str(reading.get("state") or instants.get("state") or "")
        if not installed:
            status = STATUS_BLOCKED
        elif not enabled or state.lower() == "disabled":
            status = STATUS_ALARM
        else:
            status = STATUS_OK
        return {
            "status": status,
            "available": True,
            "task_name": self.task_name,
            "installed": installed,
            "enabled": enabled,
            "state": state or None,
            "multiple_instances": reading.get("multiple_instances"),
            "start_when_available": reading.get("start_when_available"),
            "next_run_utc": reading.get("next_run_time"),
            "last_run_utc": reading.get("last_run_time"),
            "missed_runs": reading.get("missed_runs"),
            "reason": (
                "the task is not registered"
                if not installed
                else "the task is disabled"
                if not enabled
                else "the task is registered and enabled"
            ),
        }

    def check_scheduler_last_result(self) -> dict[str, Any]:
        reading = self._scheduler_probe()
        if not reading.get("available", True):
            return {
                "status": STATUS_UNKNOWN,
                "available": False,
                "reason": reading.get("reason") or "the scheduler could not be read",
            }
        instants = self._scheduler_instant_probe()
        raw = reading.get("last_task_result")
        if raw is None and instants.get("available"):
            raw = instants.get("last_task_result")
        code = None
        if raw is not None:
            try:
                code = int(str(raw), 0) if not isinstance(raw, int) else int(raw)
            except (TypeError, ValueError):
                code = None
        outcome = SCHEDULER_RESULT_VOCABULARY.get(code) if code is not None else None
        if code is None:
            status = STATUS_UNKNOWN
            reason = "the scheduler reports no last result for this task"
        elif code == 0:
            status = STATUS_OK
            reason = "the scheduler's last result is a lane tick that did its job"
        elif outcome in (NO_NEW_DATA, OBSERVED, ALREADY_OBSERVED):
            status = STATUS_OK
            reason = f"the scheduler's last result is {outcome}"
        elif outcome == ALREADY_RUNNING:
            status = STATUS_WARN
            reason = "the scheduler's last result is a tick that lost the lease to a live one"
        elif outcome in (MISSING_BARS, STALE_DATA, PROVIDER_UNAVAILABLE):
            status = STATUS_WARN
            reason = f"the scheduler's last result is {outcome}: the tick ran and the store is short"
        elif outcome in (DISK_BUDGET_EXCEEDED, VERIFICATION_FAILED, RUNTIME_EXCEPTION):
            status = STATUS_ALARM
            reason = f"the scheduler's last result is {outcome}"
        elif outcome in ("TASK_IS_RUNNING",):
            status = STATUS_OK
            reason = "the scheduler reports a tick in flight"
        elif outcome in ("TASK_HAS_NOT_RUN", "TASK_TERMINATED_BY_USER"):
            status = STATUS_WARN
            reason = f"the scheduler reports {outcome}"
        else:
            status = STATUS_ALARM
            reason = f"the scheduler's last result {raw!r} is not in the lane's vocabulary"
        return {
            "status": status,
            "available": True,
            "raw_result": raw,
            "exit_code": code,
            "lane_outcome": outcome,
            "reason": reason,
            "vocabulary": {str(key): value for key, value in sorted(SCHEDULER_RESULT_VOCABULARY.items())},
        }

    def check_scheduler_cadence(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """Whether the next trigger is still in the future, from an instant the host labels UTC."""
        now = int(now_ms if now_ms is not None else self._now_ms())
        instants = self._scheduler_instant_probe()
        scheduler = self._scheduler_probe()
        next_ms = _parse_ms(instants.get("next_run_utc")) if instants.get("available") else None
        host_ms = _parse_ms(instants.get("queried_at_utc")) if instants.get("available") else None
        missed = instants.get("missed_runs") if instants.get("available") else scheduler.get("missed_runs")
        try:
            missed_count = int(str(missed))
        except (TypeError, ValueError):
            missed_count = None
        skew = _seconds_between(now, host_ms) if host_ms is not None else None
        overdue = None if next_ms is None else round((now - next_ms) / 1000.0, 3)
        status = STATUS_OK
        reason = "the next trigger is in the future"
        if next_ms is None:
            status = STATUS_UNKNOWN
            reason = (
                "the scheduler's next instant could not be read as UTC: the platform's own "
                "spelling of it is unlabelled local time, and guessing the host's offset is how a "
                "watchdog reports a healthy schedule as a stalled one"
            )
        elif overdue is not None and overdue > SCHEDULER_GRACE_SECONDS:
            status = STATUS_ALARM
            reason = (
                f"the next trigger was due {overdue}s ago and has not fired: the schedule is "
                "stalled, not merely waiting"
            )
        if missed_count:
            status = STATUS_ALARM
            reason = f"the scheduler reports {missed_count} missed run(s)"
        if skew is not None and abs(skew) > SCHEDULER_GRACE_SECONDS:
            status = STATUS_ALARM
            reason = (
                f"this process and the scheduler disagree about the current instant by {skew}s: "
                "every age below is measured against a clock that is wrong"
            )
        return {
            "status": status,
            "available": bool(instants.get("available")),
            "source": "powershell_iso_utc" if instants.get("available") else "unavailable",
            "task_name": self.task_name,
            "next_run_utc": instants.get("next_run_utc"),
            "next_run_ms": next_ms,
            "last_run_utc": instants.get("last_run_utc"),
            "overdue_seconds": overdue,
            "missed_runs": missed_count,
            "host_clock_skew_seconds": skew,
            "local_offset_minutes": instants.get("local_offset_minutes"),
            "scheduler_spelling": scheduler.get("next_run_time"),
            "grace_seconds": SCHEDULER_GRACE_SECONDS,
            "reason": reason,
            "note": (
                "the platform's unlabelled spelling is recorded verbatim and is not read as an "
                "instant: only the round-trip UTC form is"
            ),
        }

    def check_lane_cadence(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """Silence since the newest tick that consumed a slot, from the lane's own log."""
        now = int(now_ms if now_ms is not None else self._now_ms())
        rows = self.lane_runs()
        consuming = self.consuming_runs(rows)
        if not consuming:
            return {
                "status": STATUS_BLOCKED,
                "runs_on_file": len(rows),
                "consuming_runs": 0,
                "reason": "the lane's run log holds no consuming tick at all",
            }
        newest = consuming[-1]
        finished_ms = int(
            newest.get("finished_at_ms") or newest.get("started_at_ms") or 0
        ) or None
        silence = _seconds_between(now, finished_ms)
        started = int(newest.get("started_at_ms") or 0) or None
        elapsed = _seconds_between(now, started)
        in_flight = str(newest.get("outcome")) not in SLOT_CONSUMING_OUTCOMES
        wedged = bool(elapsed is not None and elapsed > TICK_WEDGED_SECONDS)
        if silence is None:
            status = STATUS_UNKNOWN
            reason = "the newest consuming tick records no finish instant"
        elif silence > self.cadence_blocked_seconds:
            status = STATUS_BLOCKED
            reason = (
                f"no tick has consumed a slot for {round(silence / 60.0, 1)} minutes: the lane is "
                "not merely late"
            )
        elif silence > self.cadence_alarm_seconds:
            status = STATUS_ALARM
            reason = f"no tick has consumed a slot for {round(silence / 60.0, 1)} minutes"
        elif silence > self.cadence_warn_seconds:
            status = STATUS_WARN
            reason = f"the newest consuming tick finished {round(silence / 60.0, 1)} minutes ago"
        else:
            status = STATUS_OK
            reason = "a tick consumed a slot within the declared schedule"
        return {
            "status": status,
            "newest_consuming_run_id": newest.get("run_id"),
            "newest_consuming_outcome": newest.get("outcome"),
            "newest_consuming_slot": newest.get("slot_key"),
            "finished_at_utc": newest.get("finished_at_utc"),
            "silence_seconds": silence,
            "tick_elapsed_seconds": elapsed,
            "tick_wedged": wedged,
            "in_flight": in_flight,
            "thresholds_seconds": {
                "warn": self.cadence_warn_seconds,
                "alarm": self.cadence_alarm_seconds,
                "blocked": self.cadence_blocked_seconds,
            },
            "runs_on_file": len(rows),
            "reason": reason,
        }

    def check_lane_process(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """The lane's process, told from the operating system's process table where it can be.

        The reading is deliberately two-sided: the run log says which process claimed to be a tick,
        and the process table says which processes are actually running one. A tick that recorded a
        start and no finish is a process that died inside the tick, whatever the table says.
        """
        now = int(now_ms if now_ms is not None else self._now_ms())
        rows = self.lane_runs()
        unfinished = [
            {
                "run_id": row.get("run_id"),
                "pid": row.get("pid"),
                "started_at_utc": row.get("started_at_utc"),
            }
            for row in rows
            if not row.get("finished_at_utc")
        ]
        process = self._process_probe()
        observed: list[dict[str, Any]] = []
        if process.get("available"):
            for row in process.get("processes") or []:
                observed.append(
                    {
                        "pid": row.get("pid"),
                        "parent_pid": row.get("parent_pid"),
                        "name": row.get("name"),
                        "started_at": row.get("started_at"),
                        # A tick whose parent is the Task Scheduler service was launched by the
                        # schedule; one launched from a shell was launched by a person.
                        "launched_by_task_scheduler": _launched_by_scheduler(row),
                    }
                )
        if unfinished:
            status = STATUS_ALARM
            reason = (
                f"{len(unfinished)} tick(s) started and never finished: the process died inside "
                "the tick"
            )
        else:
            status = STATUS_OK if process.get("available") else STATUS_UNKNOWN
            reason = (
                "every recorded tick finished and the process table answered"
                if process.get("available")
                else "every recorded tick finished; this platform cannot read the process table"
            )
        return {
            "status": status,
            "unfinished_runs": unfinished,
            "process_probe": process.get("reason") if not process.get("available") else None,
            "observer_processes": observed,
            "observer_running": bool(observed),
            "checked_at_utc": stamp(now),
            "reason": reason,
        }

    def check_market_expectation(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """The bar the market owes against the bar the store holds. This is the whole difference.

        Two instants are measured, and they must not be confused:

        * the **last consuming tick's market instant** — bars that had closed by then and are not in
          the store are bars that tick failed to collect, whatever happens next;
        * **now** — bars that have closed since then. Those are *pending*, not missing: the next
          trigger is what collects them, and calling them a failure would report the schedule as a
          fault once a minute.
        """
        now = int(now_ms if now_ms is not None else self._now_ms())
        consuming = self.consuming_runs()
        last = consuming[-1] if consuming else None
        last_market_ms = _parse_ms(last.get("market_instant_utc")) if last else None
        series_rows: list[dict[str, Any]] = []
        missing_at_last_tick = 0
        pending_since = 0
        quiet_series = 0
        for timeframe, symbol in self.series:
            span = BAR_MS[timeframe]
            key = f"{timeframe}:{symbol}"
            newest = self.newest_stored_bar(timeframe, symbol)
            stored_ts = int(newest["ts"]) if newest else None
            newest_closed_now = ((now // span) * span) - span
            newest_closed_then = (
                ((last_market_ms // span) * span) - span if last_market_ms is not None else None
            )
            missing = 0
            pending = 0
            if newest_closed_then is not None and stored_ts is not None:
                missing = max(0, (newest_closed_then - stored_ts) // span)
            if stored_ts is not None:
                pending = max(0, (newest_closed_now - stored_ts) // span)
            quiet_series += 1 if pending == 0 else 0
            missing_at_last_tick += missing
            pending_since += pending
            series_rows.append(
                {
                    "series": key,
                    "stored_last_ts": stored_ts,
                    "stored_last_utc": stamp(stored_ts) if stored_ts else None,
                    "fetched_at_utc": stamp(int(newest["fetched_at_ms"]))
                    if newest and newest.get("fetched_at_ms")
                    else None,
                    "newest_closed_at_last_tick_ts": newest_closed_then,
                    "newest_closed_now_ts": newest_closed_now,
                    "missing_at_last_tick": missing,
                    "pending_since_last_tick": pending,
                    "span_ms": span,
                }
            )
        market_quiet = pending_since == 0
        if missing_at_last_tick:
            status = STATUS_ALARM
            reason = (
                f"{missing_at_last_tick} bar(s) had closed by the last tick's own market instant "
                "and are not in the store: the operation failed to collect what the market "
                "already published"
            )
        elif market_quiet:
            status = STATUS_OK
            reason = (
                "no bar has closed for any series since the store's newest one: the market, not "
                "the lane, is what is quiet"
            )
        else:
            status = STATUS_OK
            reason = (
                f"{pending_since} bar(s) closed since the last tick and are pending the next "
                "trigger: normal latency inside the declared schedule, not a failure"
            )
        return {
            "status": status,
            "market_quiet": market_quiet,
            "missing_at_last_tick": missing_at_last_tick,
            "pending_since_last_tick": pending_since,
            "quiet_series": quiet_series,
            "last_consuming_run_id": last.get("run_id") if last else None,
            "last_market_instant_utc": last.get("market_instant_utc") if last else None,
            "series": series_rows,
            "reason": reason,
        }

    def check_store_freshness(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """Whether each series' newest stored bar is too old for its own timeframe."""
        from ..edge03.autonomous import STALE_AFTER_MS

        now = int(now_ms if now_ms is not None else self._now_ms())
        stale: list[str] = []
        rows: list[dict[str, Any]] = []
        for timeframe, symbol in self.series:
            newest = self.newest_stored_bar(timeframe, symbol)
            if newest is None:
                stale.append(f"{timeframe}:{symbol}")
                rows.append({"series": f"{timeframe}:{symbol}", "stored_last_utc": None})
                continue
            closed_ms = int(newest["ts"]) + BAR_MS[timeframe]
            lag = round((now - closed_ms) / 1000.0, 3)
            key = f"{timeframe}:{symbol}"
            if lag > STALE_AFTER_MS[timeframe] / 1000.0:
                stale.append(key)
            rows.append(
                {
                    "series": key,
                    "stored_last_utc": stamp(int(newest["ts"])),
                    "closed_ago_seconds": lag,
                    "bound_seconds": STALE_AFTER_MS[timeframe] / 1000.0,
                }
            )
        status = STATUS_OK if not stale else STATUS_ALARM
        if stale and len(stale) == len(self.series) and not self.consuming_runs():
            status = STATUS_BLOCKED
        return {
            "status": status,
            "stale_series": sorted(stale),
            "series": rows,
            "reason": (
                "every series holds a bar that closed inside its staleness bound"
                if not stale
                else f"{len(stale)} series' newest bar is older than its bound: {sorted(stale)}"
            ),
        }

    def check_evidence_integrity(self) -> dict[str, Any]:
        """Torn lines, duplicate seals, a seal naming a run the log no longer holds, orphans."""
        runs, corrupt_runs = read_jsonl(self.lane_state_root / "runs.jsonl")
        slots, corrupt_slots = read_jsonl(self.lane_state_root / "slots.jsonl")
        ledger, corrupt_ledger = read_jsonl(self.lane_state_root / "ledger" / "INGEST_LEDGER.jsonl")
        seals: dict[str, int] = {}
        for row in slots:
            key = str(row.get("slot_key"))
            seals[key] = seals.get(key, 0) + 1
        duplicates = {key: count for key, count in seals.items() if count > 1}
        known_runs = {str(row.get("run_id")) for row in runs}
        seals_without_run = [
            {"slot_key": key, "run_id": row.get("run_id"), "outcome": row.get("outcome")}
            for key in sorted(seals)
            for row in [next(r for r in slots if str(r.get("slot_key")) == key)]
            if str(row.get("run_id")) not in known_runs
        ]
        # An ingest attempt is a set of ledger rows sharing one market instant. The pipeline
        # ingests twice at the same instant on purpose — the second pass is its restart proof —
        # so an attempt is attributed when EITHER pass has a run row that names that instant.
        instants = sorted({int(row["run_at_ms"]) for row in ledger if row.get("run_at_ms") is not None})
        run_instants = {
            _parse_ms(row.get("market_instant_utc"))
            for row in runs
            if row.get("market_instant_utc")
        }
        unattributed = [
            {
                "run_at_ms": instant,
                "at_utc": stamp(instant),
                "bars": sum(
                    int(row.get("appended") or 0)
                    for row in ledger
                    if int(row.get("run_at_ms") or -1) == instant
                ),
                "rows": sum(1 for row in ledger if int(row.get("run_at_ms") or -1) == instant),
            }
            for instant in instants
            if instant not in run_instants
        ]
        problems: list[str] = []
        if corrupt_runs or corrupt_slots or corrupt_ledger:
            problems.append(
                f"torn log lines: runs {corrupt_runs}, slots {corrupt_slots}, ledger {corrupt_ledger}"
            )
        if duplicates:
            problems.append(f"{len(duplicates)} slot(s) hold more than one seal")
        if seals_without_run:
            problems.append(f"{len(seals_without_run)} seal(s) name a run the log no longer holds")
        status = STATUS_OK
        reason = "the lane's evidence is readable and internally consistent"
        if corrupt_runs or corrupt_slots:
            status = STATUS_ALARM
            reason = f"torn log lines in the lane's own logs: {problems}"
        elif duplicates or seals_without_run:
            status = STATUS_WARN
            reason = f"the lane's evidence holds repairable inconsistencies: {problems}"
        return {
            "status": status,
            "corrupt_lines": {
                "runs": corrupt_runs,
                "slots": corrupt_slots,
                "ledger": corrupt_ledger,
            },
            "duplicate_seals": duplicates,
            "seals_without_run": seals_without_run,
            "ingest_attempts": len(instants),
            "attempts_without_a_run": unattributed,
            "unattributed_bars": sum(row["bars"] for row in unattributed),
            "counts": {"runs": len(runs), "slots": len(slots), "ledger": len(ledger)},
            "reason": reason,
            "note": (
                "an ingest attempt with no run row is a tick that wrote bars and died before it "
                "recorded itself; its bars are in the store and the reconciliation names them"
            ),
        }

    def check_restart_proof(self) -> dict[str, Any]:
        """Every instant the pipeline ingested twice must have appended nothing the second time.

        The pipeline runs its ingest a second time at the same market instant on purpose: any bar
        the second pass appended would be a duplicate. This is the lane's own idempotence claim,
        re-derived from the ledger by a process that did not write it.
        """
        ledger = self.lane_ledger()
        by_instant: dict[int, list[dict[str, Any]]] = {}
        for row in ledger:
            if row.get("run_at_ms") is None:
                continue
            by_instant.setdefault(int(row["run_at_ms"]), []).append(row)
        broken: list[dict[str, Any]] = []
        proofs = 0
        for instant, rows in sorted(by_instant.items()):
            positions: dict[str, int] = {}
            for row in rows:
                key = f"{row.get('timeframe')}:{row.get('symbol')}"
                positions[key] = positions.get(key, 0) + 1
            passes = max(positions.values(), default=0)
            if passes < 2:
                continue
            proofs += 1
            first_seen: set[str] = set()
            for row in rows:
                key = f"{row.get('timeframe')}:{row.get('symbol')}"
                appended = int(row.get("appended") or 0)
                if key in first_seen and appended:
                    broken.append(
                        {
                            "run_at_ms": instant,
                            "at_utc": stamp(instant),
                            "series": key,
                            "appended_on_second_pass": appended,
                            "high_water_ts": row.get("high_water_ts"),
                        }
                    )
                first_seen.add(key)
        status = STATUS_OK if not broken else STATUS_BLOCKED
        return {
            "status": status,
            "instants_with_two_passes": proofs,
            "broken": broken,
            "reason": (
                "every second ingest pass at an instant appended nothing: no bar was written twice"
                if not broken
                else f"{len(broken)} bar(s) were appended by a second pass at the same market "
                "instant: a duplicate write"
            ),
        }

    def check_lane_lease(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """The lane's lease, read as arithmetic: who holds it, how long ago they renewed it."""
        now_ms = int(now_ms if now_ms is not None else self._now_ms())
        now = now_ms // 1000
        lease = self.lane_lease()
        if not lease:
            return {"status": STATUS_OK, "held": False, "reason": "no lease is on disk"}
        renewed = lease.get("renewed_at")
        stale_after = lease.get("stale_after_seconds")
        age = None if not isinstance(renewed, (int, float)) else max(0, now - int(renewed))
        stale = self._lane_lock().is_stale(lease, now=now)
        consuming = self.consuming_runs()
        finished_ms = int(consuming[-1].get("finished_at_ms") or 0) if consuming else 0
        # A lease that outlived the last tick's own finish was left behind by a process that died.
        # It is a warning, not a verdict: the next trigger is what reclaims it, and this module
        # cannot prove a pid is dead on a platform that refuses the question.
        abandoned = bool(stale and finished_ms and int(renewed or 0) * 1000 < finished_ms)
        return {
            "status": STATUS_WARN if stale else STATUS_OK,
            "held": True,
            "corrupt": bool(lease.get("corrupt")),
            "lease_version": lease.get("lease_version"),
            "holder_pid": lease.get("pid"),
            "holder_host": lease.get("host"),
            "renewed_at_utc": stamp(int(renewed) * 1000)
            if isinstance(renewed, (int, float))
            else None,
            "age_seconds": age,
            "stale_after_seconds": stale_after,
            "stale": stale,
            "abandoned_by_a_finished_tick": abandoned,
            "reason": (
                f"the lease is {age}s old, past its own {stale_after}s staleness bound: a tick "
                "died holding it and the next trigger will reclaim it"
                if abandoned
                else f"the lease is {age}s old, past its staleness bound, and no tick has finished "
                "since: a tick may be in flight"
                if stale
                else f"the lease is fresh ({age}s of a {stale_after}s bound)"
            ),
        }

    def check_resource_disk(self) -> dict[str, Any]:
        disk = self.disk()
        status = {
            HEALTHY: STATUS_OK,
            WARNING: STATUS_WARN,
            CRITICAL: STATUS_BLOCKED,
        }.get(str(disk.get("status")), STATUS_UNKNOWN)
        return {
            "status": status,
            "disk_status": disk.get("status"),
            "free_bytes": disk.get("free_bytes"),
            "free_gib": disk.get("free_gib"),
            "used_percent": disk.get("used_percent"),
            "warning_free_bytes": disk.get("warning_free_bytes", self.warning_bytes),
            "critical_free_bytes": disk.get("critical_free_bytes", self.critical_bytes),
            "reason": (
                "free space is above the warning floor"
                if status == STATUS_OK
                else "free space is below the warning floor: the lane keeps ingesting and the "
                "heavy publication waits"
                if status == STATUS_WARN
                else "free space is below the critical floor: the lane's next tick refuses before "
                "making any market request"
            ),
        }

    def check_resource_growth(self) -> dict[str, Any]:
        growth = self.lane_growth()
        rate = growth.get("bytes_per_day")
        lane_bytes = growth.get("lane_bytes")
        status = STATUS_UNKNOWN
        reason = "the lane publishes no growth reading yet"
        if not growth.get("available") and not self.consuming_runs():
            # A lane that has never ticked has nothing to measure, and saying so is not a fault.
            status = STATUS_OK
            reason = "the lane has not ticked yet: there is no growth to measure"
        elif not growth.get("available"):
            # A lane that HAS ticked and publishes no resource reading is missing one of its own
            # declared artefacts. That is not a fault of the disk; it is a fault of the record.
            status = STATUS_WARN
            reason = (
                "the lane has ticked and publishes no resource budget artefact: its own growth "
                "reading is missing"
            )
        elif isinstance(rate, (int, float)):
            if rate > self.growth_stop_bytes:
                status = STATUS_ALARM
                reason = (
                    f"measured growth {rate:.0f} bytes/day is above the stop threshold "
                    f"{self.growth_stop_bytes}: the declared 256 MiB lane budget would be consumed "
                    "in days, not in the observed window"
                )
            elif rate > self.growth_warning_bytes:
                status = STATUS_WARN
                reason = f"measured growth {rate:.0f} bytes/day is above the warning threshold"
            else:
                status = STATUS_OK
                reason = f"measured growth {rate:.0f} bytes/day is inside the declared budget"
        elif growth.get("available"):
            status = STATUS_OK
            reason = (
                "the lane publishes no forecast because its own measured rate is volatile; a "
                "growth verdict is not invented from an unstable reading"
            )
        return {
            "status": status,
            "growth": growth,
            "lane_bytes": lane_bytes,
            "warning_bytes_per_day": self.growth_warning_bytes,
            "stop_bytes_per_day": self.growth_stop_bytes,
            "deletes_evidence": False,
            "reason": reason,
            "note": (
                "these thresholds alert; nothing in this module deletes a store, a daily evidence "
                "file or a published report"
            ),
        }

    def check_watchdog_cadence(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """The watchdog's own silence. A watch that stopped is the failure it exists to catch."""
        now = int(now_ms if now_ms is not None else self._now_ms())
        rows, _corrupt = read_jsonl(self.watch_path)
        if not rows:
            return {
                "status": STATUS_OK,
                "previous_check_utc": None,
                "reason": "this is the watchdog's first check: there is no silence to measure",
            }
        previous_ms = _parse_ms(rows[-1].get("at_utc"))
        gap = _seconds_between(now, previous_ms)
        if gap is None:
            status = STATUS_UNKNOWN
            reason = "the previous check records no instant"
        elif gap > self.cadence_alarm_seconds:
            status = STATUS_ALARM
            reason = (
                f"the watchdog itself was silent for {round(gap / 60.0, 1)} minutes: the "
                "observation it is supposed to be making did not happen"
            )
        elif gap > self.cadence_warn_seconds:
            status = STATUS_WARN
            reason = f"the watchdog's previous check was {round(gap / 60.0, 1)} minutes ago"
        else:
            status = STATUS_OK
            reason = "the watchdog's previous check is inside its own cadence"
        return {
            "status": status,
            "previous_check_utc": rows[-1].get("at_utc"),
            "gap_seconds": gap,
            "checks_on_file": len(rows),
            "thresholds_seconds": {
                "warn": self.cadence_warn_seconds,
                "alarm": self.cadence_alarm_seconds,
            },
            "reason": reason,
        }

    # -- the verdict ------------------------------------------------------- #
    def check(self, *, now_ms: int | None = None, persist: bool = True) -> dict[str, Any]:
        """One full reading of the lane, its scheduler, its evidence and this process."""
        now = int(now_ms if now_ms is not None else self._now_ms())
        checks: dict[str, dict[str, Any]] = {
            "scheduler_task": self.check_scheduler_task(),
            "scheduler_last_result": self.check_scheduler_last_result(),
            "scheduler_cadence": self.check_scheduler_cadence(now_ms=now),
            "lane_cadence": self.check_lane_cadence(now_ms=now),
            "lane_process": self.check_lane_process(now_ms=now),
            "market_expectation": self.check_market_expectation(now_ms=now),
            "store_freshness": self.check_store_freshness(now_ms=now),
            "evidence_integrity": self.check_evidence_integrity(),
            "restart_proof": self.check_restart_proof(),
            "resource_disk": self.check_resource_disk(),
            "resource_growth": self.check_resource_growth(),
            "watchdog_cadence": self.check_watchdog_cadence(now_ms=now),
        }
        checks["lane_lease"] = self.check_lane_lease(now_ms=now)
        verdict, category, operational_failure, market_quiet = self.verdict(checks)
        row: dict[str, Any] = {
            "schema_version": WATCHDOG_SCHEMA_VERSION,
            "check_id": f"WATCH-{stamp(now).replace('-', '').replace(':', '')}",
            "at_utc": stamp(now),
            "at_ms": now,
            "host": self.host,
            "pid": os.getpid(),
            "python": sys.executable,
            "watching": {
                "task_name": self.task_name,
                "lane_state_root": str(self.lane_state_root),
                "store_root": str(self.store_root),
                "state_root": str(self.state_root),
                "series": [f"{timeframe}:{symbol}" for timeframe, symbol in self.series],
            },
            "verdict": verdict,
            "category": category,
            "operational_failure": operational_failure,
            "market_quiet": market_quiet,
            "checks": {name: checks[name] for name in sorted(checks)},
            "findings": [
                f"{name}: {body.get('reason')}"
                for name, body in sorted(checks.items())
                if str(body.get("status")) in (STATUS_ALARM, STATUS_BLOCKED)
            ],
            "warnings": [
                f"{name}: {body.get('reason')}"
                for name, body in sorted(checks.items())
                if str(body.get("status")) == STATUS_WARN
            ],
            # The invariants this module exists to keep, on every row it writes.
            "market_requests": 0,
            "wrote_to_lane": False,
            "held_no_lease": not self.lane_lease(),
            "hypothetical": True,
            "order_sent": False,
            "promotion": "NONE",
        }
        row["history"] = self._history(now, current=verdict)
        row["alerts"] = self.alerts(row)
        if persist:
            self._persist(row)
        return row

    def verdict(
        self, checks: dict[str, dict[str, Any]]
    ) -> tuple[str, str, bool, bool]:
        """Worst status wins, and the category is the *reason* a reader needs first.

        ``operational_failure`` is deliberately narrower than the verdict: disk pressure and a
        watchdog gap are real trouble, but they are not the lane failing to observe. The WP that
        this module serves asks for that distinction explicitly, so it is a field rather than a
        sentence.
        """
        worst = STATUS_OK
        for body in checks.values():
            status = str(body.get("status"))
            if STATUS_RANK.get(status, 0) > STATUS_RANK.get(worst, 0):
                worst = status
        verdict = {
            STATUS_OK: WATCH_OK,
            STATUS_UNKNOWN: WATCH_DEGRADED,
            STATUS_WARN: WATCH_DEGRADED,
            STATUS_ALARM: WATCH_ALARM,
            STATUS_BLOCKED: WATCH_BLOCKED,
        }.get(worst, WATCH_DEGRADED)
        expectation = checks.get("market_expectation", {})
        market_quiet = bool(expectation.get("market_quiet"))
        lane_failure = any(
            str(checks[name].get("status")) in (STATUS_ALARM, STATUS_BLOCKED)
            for name in ("lane_cadence", "lane_process", "market_expectation", "store_freshness")
            if name in checks
        )
        restart_broken = str(checks.get("restart_proof", {}).get("status")) == STATUS_BLOCKED
        scheduler_failure = any(
            str(checks[name].get("status")) in (STATUS_ALARM, STATUS_BLOCKED)
            for name in ("scheduler_task", "scheduler_cadence", "scheduler_last_result")
            if name in checks
        )
        evidence_broken = str(checks.get("evidence_integrity", {}).get("status")) == STATUS_ALARM
        resource_pressure = any(
            str(checks[name].get("status")) in (STATUS_BLOCKED, STATUS_ALARM)
            for name in ("resource_disk", "resource_growth")
            if name in checks
        )
        watchdog_gap = str(checks.get("watchdog_cadence", {}).get("status")) in (
            STATUS_WARN,
            STATUS_ALARM,
        )
        if verdict == WATCH_OK:
            category = CATEGORY_MARKET_QUIET if market_quiet else CATEGORY_HEALTHY
        elif restart_broken or evidence_broken:
            category = CATEGORY_EVIDENCE_BROKEN
        elif lane_failure:
            category = CATEGORY_LANE_OVERDUE if market_quiet is False else CATEGORY_INGEST_FAILURE
        elif scheduler_failure:
            category = CATEGORY_SCHEDULER_FAILURE
        elif resource_pressure:
            category = CATEGORY_RESOURCE_PRESSURE
        elif watchdog_gap:
            category = CATEGORY_WATCHDOG_GAP
        else:
            category = CATEGORY_HEALTHY
        return verdict, category, bool(lane_failure or scheduler_failure or restart_broken), market_quiet

    # -- its own log ------------------------------------------------------- #
    def _history(self, now_ms: int, *, current: str | None = None) -> dict[str, Any]:
        """What this watchdog has seen so far: episodes of trouble and of recovery.

        The reading being taken counts as the newest one, so ``LATEST.json`` describes the lane as
        of the moment it was written: a recovery that has just happened must not be reported as an
        episode still open until the *next* check is written.
        """
        rows, corrupt = read_jsonl(self.watch_path)
        previous = rows[-1] if rows else {}
        counted = [*rows, {"verdict": current, "at_utc": stamp(now_ms)}] if current else rows
        episodes = 0
        recoveries = 0
        open_episode: dict[str, Any] | None = None
        last_bad: dict[str, Any] | None = None
        for row in counted:
            verdict = str(row.get("verdict"))
            if verdict != WATCH_OK and open_episode is None:
                episodes += 1
                open_episode = row
                last_bad = row
            elif verdict == WATCH_OK and open_episode is not None:
                recoveries += 1
                open_episode = None
        return {
            "checks_on_file": len(rows),
            "corrupt_lines": corrupt,
            "previous_verdict": previous.get("verdict"),
            "previous_at_utc": previous.get("at_utc"),
            "episodes_of_trouble": episodes,
            "recoveries": recoveries,
            "episode_open": open_episode is not None,
            "open_episode_since_utc": (open_episode or {}).get("at_utc"),
            "newest_trouble_at_utc": (last_bad or {}).get("at_utc"),
            "read_at_utc": stamp(now_ms),
        }

    def alerts(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        """Emit one event per *transition*, including the transition back to healthy."""
        existing, _corrupt = read_jsonl(self.alerts_path)
        last: dict[str, dict[str, Any]] = {}
        for stored in existing:
            last[str(stored.get("kind"))] = stored
        emitted: list[dict[str, Any]] = []
        checks = row["checks"]
        now = int(row["at_ms"])

        def raise_alert(kind: str, detail: dict[str, Any]) -> None:
            # One event per *transition*: the same state twice is not news, and a recovery that
            # is announced on every healthy reading is not a recovery.
            previous = last.get(kind)
            if previous and previous.get("state") == detail.get("state"):
                return
            append = {
                "schema_version": WATCHDOG_SCHEMA_VERSION,
                "kind": kind,
                "at_utc": stamp(now),
                "check_id": row.get("check_id"),
                "verdict": row.get("verdict"),
                "category": row.get("category"),
                "hypothetical": True,
                "order_sent": False,
                **detail,
            }
            _append_jsonl(self.alerts_path, append)
            last[kind] = append
            emitted.append({"kind": kind, **detail})

        def state_of(name: str) -> str:
            return f"{name}:{checks.get(name, {}).get('status')}"

        scheduler = checks.get("scheduler_task", {})
        if scheduler.get("available") and not scheduler.get("installed"):
            raise_alert(
                "SCHEDULER_MISSING",
                {"state": "MISSING", "severity": "CRITICAL", "reason": scheduler.get("reason")},
            )
        elif scheduler.get("installed") and not scheduler.get("enabled"):
            raise_alert(
                "SCHEDULER_DISABLED",
                {"state": "DISABLED", "severity": "CRITICAL", "reason": scheduler.get("reason")},
            )
        else:
            raise_alert(
                "SCHEDULER_DISABLED",
                {"state": "ENABLED", "severity": "INFO", "reason": scheduler.get("reason")},
            )
        result = checks.get("scheduler_last_result", {})
        if result.get("status") in (STATUS_ALARM, STATUS_BLOCKED):
            raise_alert(
                "SCHEDULER_TASK_FAILED",
                {
                    "state": f"RESULT:{result.get('lane_outcome') or result.get('raw_result')}",
                    "severity": "CRITICAL",
                    "reason": result.get("reason"),
                },
            )
        else:
            raise_alert(
                "SCHEDULER_TASK_FAILED",
                {"state": "CLEAR", "severity": "INFO", "reason": result.get("reason")},
            )
        cadence = checks.get("lane_cadence", {})
        overdue = str(cadence.get("status")) in (STATUS_ALARM, STATUS_BLOCKED, STATUS_WARN)
        raise_alert(
            "TICK_OVERDUE",
            {
                "state": state_of("lane_cadence") if overdue else "CLEAR",
                "severity": "CRITICAL"
                if str(cadence.get("status")) == STATUS_BLOCKED
                else "WARNING"
                if overdue
                else "INFO",
                "silence_minutes": (
                    round(float(cadence["silence_seconds"]) / 60.0, 1)
                    if isinstance(cadence.get("silence_seconds"), (int, float))
                    else None
                ),
                "reason": cadence.get("reason"),
            },
        )
        process = checks.get("lane_process", {})
        unfinished = process.get("unfinished_runs") or []
        raise_alert(
            "TICK_DIED_MID_WRITE",
            {
                "state": f"{len(unfinished)} UNFINISHED" if unfinished else "CLEAR",
                "severity": "CRITICAL" if unfinished else "INFO",
                "runs": unfinished,
            },
        )
        expectation = checks.get("market_expectation", {})
        raise_alert(
            "INGEST_STALLED",
            {
                "state": state_of("market_expectation"),
                "severity": "CRITICAL"
                if str(expectation.get("status")) == STATUS_ALARM
                else "INFO",
                "missing_at_last_tick": expectation.get("missing_at_last_tick"),
                "reason": expectation.get("reason"),
            },
        )
        raise_alert(
            "MARKET_QUIET",
            {
                "state": "QUIET" if expectation.get("market_quiet") else "NEW_BARS_EXPECTED",
                "severity": "INFO",
                "pending_since_last_tick": expectation.get("pending_since_last_tick"),
                "reason": expectation.get("reason"),
            },
        )
        freshness = checks.get("store_freshness", {})
        raise_alert(
            "STORE_STALE",
            {
                "state": state_of("store_freshness"),
                "severity": "CRITICAL"
                if str(freshness.get("status")) in (STATUS_ALARM, STATUS_BLOCKED)
                else "INFO",
                "stale_series": freshness.get("stale_series"),
            },
        )
        evidence = checks.get("evidence_integrity", {})
        raise_alert(
            "EVIDENCE_CORRUPT",
            {
                "state": state_of("evidence_integrity"),
                "severity": "CRITICAL"
                if str(evidence.get("status")) == STATUS_ALARM
                else "WARNING"
                if str(evidence.get("status")) == STATUS_WARN
                else "INFO",
                "corrupt_lines": evidence.get("corrupt_lines"),
                "duplicate_seals": len(evidence.get("duplicate_seals") or {}),
                "attempts_without_a_run": len(evidence.get("attempts_without_a_run") or []),
                "unattributed_bars": evidence.get("unattributed_bars"),
            },
        )
        if evidence.get("attempts_without_a_run"):
            raise_alert(
                "RECONCILIATION_REQUIRED",
                {
                    "state": f"{evidence['unattributed_bars']} UNATTRIBUTED BARS",
                    "severity": "WARNING",
                    "attempts": evidence.get("attempts_without_a_run"),
                    "reason": (
                        "bars are in the store with no run row claiming the attempt that fetched "
                        "them: the reconciliation names them and leaves them in place"
                    ),
                },
            )
        else:
            raise_alert(
                "RECONCILIATION_REQUIRED",
                {"state": "CLEAR", "severity": "INFO", "reason": "every stored bar is attributed"},
            )
        proof = checks.get("restart_proof", {})
        raise_alert(
            "RESTART_PROOF_BROKEN",
            {
                "state": state_of("restart_proof"),
                "severity": "CRITICAL"
                if str(proof.get("status")) == STATUS_BLOCKED
                else "INFO",
                "broken": proof.get("broken"),
            },
        )
        disk = checks.get("resource_disk", {})
        disk_state = str(disk.get("disk_status"))
        raise_alert(
            "DISK_CRITICAL" if disk_state == CRITICAL else "DISK_WARNING",
            {
                "state": disk_state,
                "severity": "CRITICAL" if disk_state == CRITICAL else "WARNING",
                "free_gib": disk.get("free_gib"),
            },
        )
        if disk_state == HEALTHY:
            raise_alert(
                "DISK_RECOVERED",
                {"state": "HEALTHY", "severity": "INFO", "free_gib": disk.get("free_gib")},
            )
        growth = checks.get("resource_growth", {})
        if str(growth.get("status")) in (STATUS_WARN, STATUS_ALARM):
            raise_alert(
                "GROWTH_BUDGET_EXCEEDED",
                {
                    "state": state_of("resource_growth"),
                    "severity": "WARNING"
                    if str(growth.get("status")) == STATUS_WARN
                    else "CRITICAL",
                    "reason": growth.get("reason"),
                },
            )
        else:
            raise_alert(
                "GROWTH_BUDGET_EXCEEDED",
                {"state": "CLEAR", "severity": "INFO", "reason": growth.get("reason")},
            )
        self_check = checks.get("watchdog_cadence", {})
        if str(self_check.get("status")) in (STATUS_WARN, STATUS_ALARM):
            raise_alert(
                "WATCHDOG_SELF_GAP",
                {
                    "state": state_of("watchdog_cadence"),
                    "severity": "WARNING",
                    "gap_seconds": self_check.get("gap_seconds"),
                    "reason": self_check.get("reason"),
                },
            )
        verdict = str(row.get("verdict"))
        previous_verdict = str(row.get("history", {}).get("previous_verdict") or WATCH_OK)
        if verdict == WATCH_BLOCKED:
            raise_alert(
                "WATCHDOG_BLOCKED",
                {
                    "state": "BLOCKED",
                    "severity": "CRITICAL",
                    "findings": row.get("findings"),
                    "category": row.get("category"),
                },
            )
        elif verdict == WATCH_ALARM:
            raise_alert(
                "WATCHDOG_ALARM",
                {
                    "state": "ALARM",
                    "severity": "CRITICAL",
                    "findings": row.get("findings"),
                    "category": row.get("category"),
                },
            )
        elif verdict == WATCH_DEGRADED:
            raise_alert(
                "WATCHDOG_DEGRADED",
                {
                    "state": "DEGRADED",
                    "severity": "WARNING",
                    "warnings": row.get("warnings"),
                    "category": row.get("category"),
                },
            )
        # The recovery is emitted because the *previous* reading was not healthy — and it names
        # the tick that ended the episode, which is the evidence a reader needs.
        if verdict == WATCH_OK and previous_verdict != WATCH_OK:
            raise_alert(
                "WATCHDOG_RECOVERED",
                {
                    "state": "OK",
                    "severity": "INFO",
                    "recovered_from": previous_verdict,
                    "recovered_by_run_id": (
                        checks.get("lane_cadence", {}).get("newest_consuming_run_id")
                    ),
                    "recovered_by_tick_utc": checks.get("lane_cadence", {}).get("finished_at_utc"),
                },
            )
        if emitted:
            _prune_jsonl(self.alerts_path, WATCH_ALERTS_KEPT)
        return emitted

    def _persist(self, row: dict[str, Any]) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        _prune_jsonl(self.watch_path, max(0, self.watch_kept - 1))
        _append_jsonl(self.watch_path, row)
        write_json_atomic(self.latest_path, self._latest_payload(row))
        self._daily_update(row)

    def _latest_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        """What an operator reads first: the verdict, the findings, and what was seen so far."""
        return {
            "schema_version": WATCHDOG_SCHEMA_VERSION,
            "check_id": row["check_id"],
            "at_utc": row["at_utc"],
            "verdict": row["verdict"],
            "category": row["category"],
            "operational_failure": row["operational_failure"],
            "market_quiet": row["market_quiet"],
            "findings": row["findings"],
            "warnings": row["warnings"],
            "history": row["history"],
            "checks": {
                name: {"status": body.get("status"), "reason": body.get("reason")}
                for name, body in row["checks"].items()
            },
            "scheduler": {
                "task_name": self.task_name,
                "state": row["checks"].get("scheduler_task", {}).get("state"),
                "enabled": row["checks"].get("scheduler_task", {}).get("enabled"),
                "last_task_result": row["checks"].get("scheduler_last_result", {}).get("raw_result"),
                "next_run_utc": row["checks"].get("scheduler_task", {}).get("next_run_utc"),
            },
            "lane": {
                "newest_consuming_run_id": row["checks"]
                .get("lane_cadence", {})
                .get("newest_consuming_run_id"),
                "silence_seconds": row["checks"].get("lane_cadence", {}).get("silence_seconds"),
                "missing_at_last_tick": row["checks"]
                .get("market_expectation", {})
                .get("missing_at_last_tick"),
                "pending_since_last_tick": row["checks"]
                .get("market_expectation", {})
                .get("pending_since_last_tick"),
            },
            "hypothetical": True,
            "order_sent": False,
            "promotion": "NONE",
            "reading": (
                "an independent verdict on the forward lane: it is produced by a process that "
                "holds no lease, runs no pipeline and makes no market request, and every field "
                "above is derived from the lane's own files and the operating system's own "
                "reporting"
            ),
        }

    def _daily_update(self, row: dict[str, Any]) -> None:
        """Fold this check into the day's durable rollup. Rolling up readings, not copying files."""
        day = day_key(int(row["at_ms"]))
        path = self.daily_dir / f"{day}.json"
        existing: dict[str, Any] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                existing = loaded if isinstance(loaded, dict) else {}
            except json.JSONDecodeError:
                existing = {}
        verdicts = dict(existing.get("verdicts") or {})
        verdicts[str(row["verdict"])] = int(verdicts.get(str(row["verdict"]), 0)) + 1
        checks = row["checks"]
        disk = checks.get("resource_disk", {})
        free = disk.get("free_bytes")
        free_min = existing.get("free_bytes_min")
        free_max = existing.get("free_bytes_max")
        record = {
            "schema_version": DAILY_SCHEMA_VERSION,
            "day": day,
            "first_check_utc": existing.get("first_check_utc") or row["at_utc"],
            "last_check_utc": row["at_utc"],
            "checks": int(existing.get("checks", 0)) + 1,
            "verdicts": dict(sorted(verdicts.items())),
            "episodes_of_trouble": int(row.get("history", {}).get("episodes_of_trouble") or 0),
            "recoveries": int(row.get("history", {}).get("recoveries") or 0),
            "operational_failure_checks": int(existing.get("operational_failure_checks", 0))
            + (1 if row["operational_failure"] else 0),
            "market_quiet_checks": int(existing.get("market_quiet_checks", 0))
            + (1 if row["market_quiet"] else 0),
            "free_bytes_min": min(x for x in (free_min, free) if isinstance(x, int))
            if isinstance(free, int) or isinstance(free_min, int)
            else None,
            "free_bytes_max": max(x for x in (free_max, free) if isinstance(x, int))
            if isinstance(free, int) or isinstance(free_max, int)
            else None,
            "findings_seen": sorted(
                set(existing.get("findings_seen") or []) | set(row.get("findings") or [])
            ),
            "hypothetical": True,
            "order_sent": False,
            "promotion": "NONE",
        }
        write_json_atomic(path, record)
        self._prune_daily()

    def _prune_daily(self) -> int:
        if not self.daily_dir.is_dir():
            return 0
        files = sorted(self.daily_dir.glob("*.json"))
        if len(files) <= WATCH_DAILY_KEPT:
            return 0
        dropped = 0
        for path in files[: len(files) - WATCH_DAILY_KEPT]:
            path.unlink()
            dropped += 1
        return dropped

    def install(self) -> dict[str, Any]:
        if not self.install_path.is_file():
            return {}
        try:
            loaded = json.loads(self.install_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"corrupt": True}
        return loaded if isinstance(loaded, dict) else {}

    # -- snapshots, refused when they would be redundant -------------------- #
    def snapshot(self, outdir: Path, *, force: bool = False) -> dict[str, Any]:
        """Write a digest record of this watchdog's own state, or refuse to repeat one.

        Part of the resource discipline this work package owes: a snapshot that would be identical
        to the previous one is *not taken*, and the refusal is recorded. What is copied is this
        watchdog's own bounded state — a handful of kilobytes of readings. The lane's store and its
        daily evidence are never copied, moved or pruned by this module.
        """
        import hashlib

        outdir = Path(outdir)
        files: dict[str, Any] = {}
        # ``snapshot_status.json`` is the record of the *previous decision*, not part of the state
        # being observed: including it would mean that every snapshot changes the digest that
        # decides whether a snapshot is worth taking, and the anti-redundancy rule could never
        # fire. Everything else under the root is the state.
        excluded = {"snapshot_status.json"}
        if self.state_root.is_dir():
            for source in sorted(self.state_root.rglob("*")):
                if not source.is_file():
                    continue
                relative = source.relative_to(self.state_root)
                if any(part.startswith(".") for part in relative.parts):
                    continue
                if relative.parts[0] == "snapshots":
                    continue
                if relative.as_posix() in excluded:
                    continue
                files[relative.as_posix()] = {
                    "bytes": source.stat().st_size,
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
        digest = hashlib.sha256(
            json.dumps(files, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        previous = self._previous_snapshot_digest()
        if previous == digest and not force:
            record = {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "at_utc": stamp(self._now_ms()),
                "status": "SKIPPED_IDENTICAL",
                "digest": digest,
                "files": len(files),
                "reason": (
                    "this snapshot would be byte-identical to the previous one: a duplicate of a "
                    "reading is not new evidence, so it is not written"
                ),
                "wrote_to_lane": False,
                "hypothetical": True,
                "order_sent": False,
            }
            write_json_atomic(self.state_root / "snapshot_status.json", record)
            return record
        outdir.mkdir(parents=True, exist_ok=True)
        for name in files:
            source = self.state_root / name
            target = outdir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        record = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "at_utc": stamp(self._now_ms()),
            "status": "WRITTEN",
            "digest": digest,
            "outdir": str(outdir),
            "files": len(files),
            "file_digests": files,
            "wrote_to_lane": False,
            "hypothetical": True,
            "order_sent": False,
        }
        write_json_atomic(outdir / "SNAPSHOT.json", record)
        write_json_atomic(self.state_root / "snapshot_status.json", record)
        return record

    def _previous_snapshot_digest(self) -> str | None:
        path = self.state_root / "snapshot_status.json"
        if not path.is_file():
            return None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if isinstance(loaded, dict) and loaded.get("status") == "WRITTEN":
            return str(loaded.get("digest") or "") or None
        return None

    def silence_report(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """The reading a reader wants when the question is "how long has nothing happened"."""
        now = int(now_ms if now_ms is not None else self._now_ms())
        return {
            "at_utc": stamp(now),
            "lane": self.check_lane_cadence(now_ms=now),
            "market": self.check_market_expectation(now_ms=now),
            "scheduler": self.check_scheduler_task(),
            "scheduler_cadence": self.check_scheduler_cadence(now_ms=now),
        }


def _launched_by_scheduler(row: dict[str, Any]) -> bool | None:
    """Whether a process row was started by the Task Scheduler service, when the row says so."""
    parent = row.get("parent_name")
    if parent is None:
        return None
    return str(parent).lower() in ("svchost.exe", "taskeng.exe", "taskhostw.exe")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def _prune_jsonl(path: Path, keep: int) -> int:
    """Front-truncate a bounded log. Returns the number of rows dropped."""
    if not path.is_file():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    dropped = max(0, len(lines) - max(0, keep))
    if not dropped:
        return 0
    path.write_text("\n".join(lines[dropped:]) + "\n", encoding="utf-8")
    return dropped


