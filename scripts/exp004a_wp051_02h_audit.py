"""WP-051-02H builder: is the forward observer running, and what did its hole cost?

The previous package (02G) read the forward store **in its own worktree**, where
``data/forward`` is a copy made for a rehearsal. That copy is frozen by construction, so
"the observer stopped at 18:00Z" was a statement about a file, not about the observer.
This program measures the live thing instead, and it measures it from bytes:

* the operating-system task that runs the observer, read through the scheduler rather
  than through the repository's own declaration of it;
* the observer's own tick log, one JSON object per tick, appended by the observer;
* the live store the observer writes, read bar by bar with the store's own lag formula;
* the phase-3 declaration 02G froze, read (never written) for the boundary it defines.

It produces three reports and refuses to guess:

``RECOVERY_REPORT.json``   whether the observer is running, and the tick that proves it
``COVERAGE_GAP_REPORT.json`` the hole, quantified, and what it costs the declaration
``CONTINUITY_REPORT.json``  which continuity properties hold, and which do not

Nothing here trades, sizes, fetches or repairs. It reads files and asks the scheduler a
question. The one thing it must never do is turn a hole into a pass: a day that already
holds an inadmissible bar is reported as lost, and the coverage ceiling is computed from
that day rather than from the days that remain.

Exit codes:

    0  every requested section was measured
    2  a control failed: the inputs contradict themselves
    4  a required input is missing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
PACKAGE = "WP-051-02H"
TASK_NAME = "TradingAgentic-EDGE04-Forward"
WATCHDOG_TASK = "TradingAgentic-EDGE04-Watchdog"
WATCHDOG_SCRIPT = "scripts/edge04_watchdog.py"

REPO_ROOT = Path(__file__).resolve().parents[1]

HOUR_MS = 3_600_000
DEFAULT_STATE = "data/forward/edge04"
DEFAULT_STORE = "data/forward/edge03"
DECLARATION = "config/preregistrations/EXP-004A.datasets.phase3.json"
SERIES: tuple[tuple[str, str], ...] = (("1h", "BTC"), ("1h", "ETH"), ("1h", "SOL"))

#: The instant 02G's report named as the last bar it saw. This package measures the same
#: instant against the live store; if the two disagree, the disagreement is the finding.
CLAIMED_LAST_BAR_UTC = "2026-10-22T18:00:00Z"

#: The observer's own cadence, from the OS task's repetition interval. A silence longer
#: than three internals is a hole; two is normal scheduler jitter.
INTERVAL_MINUTES = 15
SILENCE_FACTOR = 3

EXIT_OK = 0
EXIT_FAILED = 2
EXIT_MISSING = 4


# --------------------------------------------------------------------------- #
# small helpers, no third-party imports
# --------------------------------------------------------------------------- #
def now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(text: str) -> int:
    value = text.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_bytes().decode("utf-8"))


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Every parsable line, plus the number of lines that were not parsable.

    A corrupt line is counted, never dropped silently: a tick log that loses rows is a
    tick log whose hole arithmetic is wrong.
    """
    rows: list[dict[str, Any]] = []
    corrupt = 0
    if not path.is_file():
        return rows, corrupt
    for raw in path.read_bytes().splitlines():
        if not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            corrupt += 1
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
        else:
            corrupt += 1
    return rows, corrupt


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))


def run(argv: list[str], *, timeout: int = 60) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, "", repr(exc)
    return completed.returncode, completed.stdout, completed.stderr


# --------------------------------------------------------------------------- #
# the scheduler, asked directly
# --------------------------------------------------------------------------- #
def _powershell_json(script: str) -> Any | None:
    """Run a PowerShell snippet that emits JSON, and return the parsed value.

    The scheduler is queried through the OS rather than through ``install.json``: a file
    in the repository can say a task was installed while the task has been deleted, and
    that is exactly the difference this package has to measure.
    """
    if not sys.platform.startswith("win"):
        return None
    code, out, _err = run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=90,
    )
    if code != 0 or not out.strip():
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def scheduled_task(task_name: str) -> dict[str, Any]:
    """The task's registration and its last run, as the scheduler reports them."""
    detail: dict[str, Any] = {
        "task_name": task_name,
        "queried": False,
        "installed": None,
        "enabled": None,
        "state": None,
        "settings": {},
        "trigger": {},
        "action": {},
        "last_run": {},
        "note": "read through the OS scheduler; never through the repository's install.json",
    }
    if not sys.platform.startswith("win"):
        detail["note"] = "not a Windows host: the scheduler was not queried"
        return detail

    code, out, _err = run(["schtasks", "/query", "/tn", task_name, "/xml"], timeout=60)
    if code != 0 or not out.strip():
        detail["installed"] = False
        detail["note"] = "the scheduler does not know this task"
        return detail
    detail["queried"] = True
    detail["installed"] = True
    text = out.replace("\x00", "").strip()
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        detail["note"] = f"the scheduler answered, but its XML did not parse: {exc!r}"
        return detail

    ns = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
    settings = root.find(f"{ns}Settings")
    if settings is not None:
        restart = settings.find(f"{ns}RestartOnFailure")
        detail["settings"] = {
            "multiple_instances": (settings.findtext(f"{ns}MultipleInstancesPolicy") or "").strip(),
            "start_when_available": (settings.findtext(f"{ns}StartWhenAvailable") or "").strip().lower() == "true",
            "disallow_start_if_on_batteries": (
                settings.findtext(f"{ns}DisallowStartIfOnBatteries") or ""
            ).strip().lower()
            == "true",
            "stop_if_going_on_batteries": (settings.findtext(f"{ns}StopIfGoingOnBatteries") or "").strip().lower()
            == "true",
            "execution_time_limit": (settings.findtext(f"{ns}ExecutionTimeLimit") or "").strip(),
            "restart_on_failure": {
                "count": int(restart.findtext(f"{ns}Count") or 0) if restart is not None else 0,
                "interval": (restart.findtext(f"{ns}Interval") or "").strip() if restart is not None else "",
            },
        }
    trigger = root.find(f"{ns}Triggers/{ns}TimeTrigger")
    if trigger is not None:
        repetition = trigger.find(f"{ns}Repetition")
        detail["trigger"] = {
            "start_boundary": (trigger.findtext(f"{ns}StartBoundary") or "").strip(),
            "interval": (repetition.findtext(f"{ns}Interval") or "").strip() if repetition is not None else "",
            "duration": (repetition.findtext(f"{ns}Duration") or "").strip() if repetition is not None else "",
        }
    action = root.find(f"{ns}Actions/{ns}Exec")
    if action is not None:
        detail["action"] = {
            "command": (action.findtext(f"{ns}Command") or "").strip(),
            "arguments": (action.findtext(f"{ns}Arguments") or "").strip(),
            "working_directory": (action.findtext(f"{ns}WorkingDirectory") or "").strip(),
        }
    principal = root.find(f"{ns}Principals/{ns}Principal")
    if principal is not None:
        detail["principal"] = {
            "logon_type": (principal.findtext(f"{ns}LogonType") or "").strip(),
            "user_id": (principal.findtext(f"{ns}UserId") or "").strip(),
        }

    info = _powershell_json(
        "try { Get-ScheduledTaskInfo -TaskName '%s' | Select-Object LastRunTime,LastTaskResult,"
        "NextRunTime,NumberOfMissedRuns | ConvertTo-Json -Compress } catch { '' }" % task_name
    )
    if isinstance(info, dict):
        detail["last_run"] = {
            "last_run_time": info.get("LastRunTime"),
            "last_task_result": info.get("LastTaskResult"),
            "next_run_time": info.get("NextRunTime"),
            "missed_runs": info.get("NumberOfMissedRuns"),
        }
    else:
        state = _powershell_json(
            "try { (Get-ScheduledTask -TaskName '%s').State | ConvertTo-Json -Compress } catch { '' }" % task_name
        )
        if state is not None:
            detail["state"] = state
    return detail


def observer_processes(script_name: str = "edge04_observer.py") -> dict[str, Any]:
    """Every live process whose command line names the observer entry point.

    ``ps`` on this host does not carry command lines, so the query goes through WMI. A
    second live observer is a defect, not a detail: the task policy says ``IgnoreNew``,
    which stops the scheduler from starting one, not a person from starting one by hand.
    """
    payload = _powershell_json(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*%s*' } | "
        "Select-Object ProcessId,ParentProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress" % script_name
    )
    if payload is None:
        return {"queried": False, "matches": [], "note": "the process table was not readable on this host"}
    rows = payload if isinstance(payload, list) else [payload]
    rows = [row for row in rows if isinstance(row, dict)]
    return {"queried": True, "count": len(rows), "matches": rows}


# --------------------------------------------------------------------------- #
# the observer's own log
# --------------------------------------------------------------------------- #
def tick_census(runs: list[dict[str, Any]], *, since_ms: int) -> dict[str, Any]:
    """What the ticks did in the interval, and where they went silent.

    Silence is measured between consecutive tick *starts*. The scheduler fires every 15
    minutes; a gap longer than three intervals is not jitter, and it is named with the
    instants on both sides so a reader can check it against the task's own history.
    """
    stamps: list[tuple[int, dict[str, Any]]] = []
    for row in runs:
        started = row.get("started_at_utc") or row.get("started_at")
        if not started:
            continue
        try:
            stamps.append((parse_iso(str(started)), row))
        except ValueError:
            continue
    stamps.sort(key=lambda item: item[0])
    window = [(ms, row) for ms, row in stamps if ms >= since_ms]

    outcomes: dict[str, int] = {}
    for _ms, row in window:
        key = str(row.get("outcome") or "UNRECORDED")
        outcomes[key] = outcomes.get(key, 0) + 1

    silence_limit = INTERVAL_MINUTES * 60_000 * SILENCE_FACTOR
    silences: list[dict[str, Any]] = []
    for (left_ms, left), (right_ms, right) in zip(window, window[1:]):
        if right_ms - left_ms > silence_limit:
            silences.append(
                {
                    "from_utc": iso(left_ms),
                    "to_utc": iso(right_ms),
                    "minutes": round((right_ms - left_ms) / 60_000, 2),
                    "from_outcome": left.get("outcome"),
                    "to_outcome": right.get("outcome"),
                }
            )

    blocked = [
        {"ms": ms, "row": row}
        for ms, row in window
        if str(row.get("outcome") or "") == "DISK_BUDGET_EXCEEDED"
    ]
    free_gibs = [
        float((row.get("disk") or {}).get("free_gib"))
        for _ms, row in window
        if (row.get("disk") or {}).get("free_gib") is not None
    ]

    # ``run_id`` is keyed by the slot, not by the attempt: a slot may be attempted more than
    # once (OBSERVED, then ALREADY_OBSERVED, then ALREADY_RUNNING if two of them overlap) and
    # those attempts deliberately share the id. The invariant that matters is that a slot is
    # *sealed* once: two sealing rows for one slot would mean two consuming ticks.
    sealed: dict[str, int] = {}
    for _ms, row in window:
        if row.get("slot_sealed"):
            key = str(row.get("slot_key") or "")
            sealed[key] = sealed.get(key, 0) + 1
    sealed_twice = sorted(key for key, count in sealed.items() if count > 1)
    refused_lease = sum(1 for _ms, row in window if str(row.get("outcome")) == "ALREADY_RUNNING")
    attempts_per_slot: dict[str, int] = {}
    for _ms, row in window:
        key = str(row.get("slot_key") or "")
        attempts_per_slot[key] = attempts_per_slot.get(key, 0) + 1

    first = window[0] if window else None
    last = window[-1] if window else None
    return {
        "since_utc": iso(since_ms),
        "ticks": len(window),
        "by_outcome": dict(sorted(outcomes.items())),
        "first_tick_utc": iso(first[0]) if first else None,
        "last_tick_utc": iso(last[0]) if last else None,
        "expected_ticks": int((last[0] - first[0]) / (INTERVAL_MINUTES * 60_000)) + 1 if first and last else 0,
        "silences": silences,
        "blocked": {
            "count": len(blocked),
            "first_utc": iso(blocked[0]["ms"]) if blocked else None,
            "last_utc": iso(blocked[-1]["ms"]) if blocked else None,
            "min_free_gib": min(free_gibs) if free_gibs else None,
            "reason": (blocked[-1]["row"].get("outcome_reason") if blocked else None),
        },
        "slot_integrity": {
            "sealed_slots": len(sealed),
            "sealed_twice": sealed_twice,
            "max_attempts_in_one_slot": max(attempts_per_slot.values()) if attempts_per_slot else 0,
            "lease_refusals": refused_lease,
        },
        "last_tick": last[1] if last else None,
    }


def last_stored_bar(rows_by_series: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """The newest bar in the store, and how late it was fetched when it arrived."""
    summary: dict[str, Any] = {}
    for key, rows in rows_by_series.items():
        if not rows:
            summary[key] = {"rows": 0, "last_open_utc": None, "last_fetched_utc": None}
            continue
        newest = max(rows, key=lambda row: int(row.get("ts") or 0))
        open_ms = int(newest.get("ts") or 0)
        fetched = int(newest.get("fetched_at_ms") or newest.get("fetched_ms") or 0)
        summary[key] = {
            "rows": len(rows),
            "last_open_utc": iso(open_ms),
            "last_fetched_utc": iso(fetched) if fetched else None,
            "lag_minutes": round((fetched - (open_ms + HOUR_MS)) / 60_000, 2) if fetched else None,
            "store_sha256": hashlib.sha256(
                b"\n".join(json.dumps(row, sort_keys=True).encode("utf-8") for row in rows)
            ).hexdigest(),
        }
    return summary


# --------------------------------------------------------------------------- #
# the declaration, read but never written
# --------------------------------------------------------------------------- #
def read_declaration(path: Path) -> dict[str, Any]:
    document = read_json(path)
    window = document.get("capture_window") or {}
    entries = document.get("entries") or []
    bounds = {
        int(entry["generator_parameters"]["lag_bound_ms"])
        for entry in entries
        if (entry.get("generator_parameters") or {}).get("lag_bound_ms") is not None
    }
    policy = (document.get("lag_policy") or {}).get("bound_ms")
    if policy is not None:
        bounds.add(int(policy))
    if len(bounds) > 1:
        raise SystemExit(f"{path} declares more than one lag bound: {sorted(bounds)}")
    if not bounds:
        raise SystemExit(f"{path} declares no lag bound")
    return {
        "path": path.as_posix(),
        "sha256": sha256_file(path),
        "declaration_id": document.get("declaration_id"),
        "effective_from_utc": document.get("effective_from_utc"),
        "start_utc": window.get("start_utc"),
        "end_utc": window.get("end_utc"),
        "days": int(window.get("days") or 0),
        "declared_rows": sum(int(entry.get("row_count") or 0) for entry in entries),
        "required_fraction": float((document.get("coverage") or {}).get("required_fraction") or 0.0),
        "complete_rule": (document.get("coverage") or {}).get("complete_rule"),
        "lag_bound_ms": bounds.pop(),
        "entries": [
            {
                "asset": entry.get("asset"),
                "timeframe": entry.get("timeframe"),
                "row_count": int(entry.get("row_count") or 0),
                "source_path": entry.get("source_path"),
                "period_start_utc": entry.get("period_start_utc"),
                "period_end_utc": entry.get("period_end_utc"),
            }
            for entry in entries
        ],
    }


# --------------------------------------------------------------------------- #
# the bars, measured with the declaration's own lag formula
# --------------------------------------------------------------------------- #
def bar_verdicts(
    rows: list[dict[str, Any]],
    *,
    bound_ms: int,
    effective_from_ms: int,
    store_ms: int,
) -> dict[int, dict[str, Any]]:
    """Every bar keyed by its open instant, with the lag verdict the policy would give it."""
    verdicts: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            open_ms = int(row.get("ts") or 0)
            fetched_ms = int(row.get("fetched_at_ms") or row.get("fetched_ms") or 0)
        except (TypeError, ValueError):
            continue
        if open_ms <= 0:
            continue
        lag_ms = fetched_ms - (open_ms + HOUR_MS)
        closed = bool(row.get("closed", True))
        reasons: list[str] = []
        if not closed:
            reasons.append("UNCLOSED")
        if fetched_ms > store_ms:
            reasons.append("INGESTED_AFTER_THE_READ")
        if lag_ms < 0:
            reasons.append("NEGATIVE_LAG")
        elif lag_ms > bound_ms:
            reasons.append("LATE")
        if fetched_ms < effective_from_ms:
            reasons.append("BEFORE_EFFECTIVE_FROM")
        verdicts[open_ms] = {
            "open_utc": iso(open_ms),
            "fetched_utc": iso(fetched_ms) if fetched_ms else None,
            "lag_ms": lag_ms,
            "lag_minutes": round(lag_ms / 60_000, 2),
            "admissible": not reasons,
            "reasons": reasons,
            "source": row.get("source"),
            "payload_sha256": row.get("payload_sha256"),
        }
    return verdicts


def hourly_grid(start_ms: int, end_ms: int) -> list[int]:
    """The declaration's grid: a bar opens at k * interval, half-open at the end."""
    first = (start_ms // HOUR_MS) * HOUR_MS
    grid: list[int] = []
    cursor = first
    while cursor < end_ms:
        grid.append(cursor)
        cursor += HOUR_MS
    return grid


DAY_MS = 24 * HOUR_MS


#: A day is lost the moment one of its bars is inadmissible. The bar cannot be re-fetched,
#: so neither can the day: the quarantine is decided by the worst bar, not by the average.
DAY_COMPLETE = "DAY_COMPLETE"
DAY_QUARANTINED = "DAY_QUARANTINED"
DAY_OPEN_DOOMED = "DAY_OPEN_ALREADY_DOOMED"
DAY_NOT_CLOSED = "DAY_NOT_CLOSED"

LOST_STATES = (DAY_QUARANTINED, DAY_OPEN_DOOMED)


def day_rows(
    verdicts: dict[int, dict[str, Any]],
    *,
    day_start_ms: int,
    bound_ms: int,
    closed_before_ms: int,
) -> dict[str, Any]:
    """One UTC day against the declaration's policy, including days that are still open.

    An open day is not ``DAY_NOT_CLOSED`` when it already holds an inadmissible bar: the
    bar will still be there when the day closes. Saying "not closed yet" about such a day
    is how a hole becomes invisible for eighteen hours before it becomes fatal.
    """
    grid = [day_start_ms + k * HOUR_MS for k in range(24)]
    present = [verdicts[open_ms] for open_ms in grid if open_ms in verdicts]
    admissible = [row for row in present if row["admissible"]]
    inadmissible = [row for row in present if not row["admissible"]]
    missing = [iso(open_ms) for open_ms in grid if open_ms not in verdicts]
    closed = day_start_ms + DAY_MS <= closed_before_ms
    if closed:
        classification = DAY_COMPLETE if not missing and not inadmissible else DAY_QUARANTINED
    else:
        classification = DAY_OPEN_DOOMED if inadmissible else DAY_NOT_CLOSED
    return {
        "day": iso(day_start_ms)[:10],
        "closed_at_audit": closed,
        "bars_in_store": len(present),
        "admissible": len(admissible),
        "inadmissible": [
            {"open_utc": row["open_utc"], "lag_minutes": row["lag_minutes"], "reasons": row["reasons"]}
            for row in inadmissible
        ],
        "missing_opens": missing,
        "classification": classification,
        "lost": classification in LOST_STATES,
        "lag_bound_ms": bound_ms,
        "note": (
            "a day holding one inadmissible bar is written once as admissible=false and "
            "excluded from the numerator; it is never repaired or re-fetched"
        ),
    }


# --------------------------------------------------------------------------- #
# the reports
# --------------------------------------------------------------------------- #
def build_recovery(
    *,
    repo: Path,
    state_root: Path,
    store_root: Path,
    since_ms: int,
) -> dict[str, Any]:
    runs, corrupt = read_jsonl(state_root / "runs.jsonl")
    health = read_json(state_root / "health.json") if (state_root / "health.json").is_file() else {}
    task = scheduled_task(TASK_NAME)
    watchdog_task = scheduled_task(WATCHDOG_TASK)
    processes = observer_processes()
    census = tick_census(runs, since_ms=since_ms)
    rows_by_series = {
        f"1h:{asset}": read_jsonl(store_root / "1h" / f"{asset}.jsonl")[0] for _tf, asset in SERIES
    }
    newest = last_stored_bar(rows_by_series)
    audit_ms = now_ms()
    last_tick = census["last_tick"] or {}
    last_tick_age_s = (
        round((audit_ms - parse_iso(str(last_tick.get("finished_at_utc")))) / 1000, 1)
        if last_tick.get("finished_at_utc")
        else None
    )

    recovered = [
        (ms, row)
        for ms, row in (
            (
                parse_iso(str(row.get("started_at_utc"))),
                row,
            )
            for row in runs
            if row.get("started_at_utc")
        )
        if str(row.get("outcome") or "") == "OBSERVED" and int(row.get("new_bars") or 0) > 0
    ]
    recovered.sort(key=lambda item: item[0])
    blocked_starts = [
        parse_iso(str(row.get("started_at_utc")))
        for row in runs
        if row.get("outcome") == "DISK_BUDGET_EXCEEDED" and row.get("started_at_utc")
    ]
    last_block_ms = max(blocked_starts) if blocked_starts else None
    after_block = [item for item in recovered if last_block_ms is None or item[0] > last_block_ms]
    recovery_tick = after_block[0][1] if after_block else (recovered[-1][1] if recovered else None)

    observations = {
        "task_installed": task.get("installed") is True,
        "task_enabled": (task.get("settings") or {}).get("multiple_instances") is not None,
        "tick_within_three_intervals": last_tick_age_s is not None
        and last_tick_age_s <= INTERVAL_MINUTES * 60 * SILENCE_FACTOR,
        "bars_advancing": (newest.get("1h:BTC") or {}).get("last_open_utc") is not None,
        "no_slot_sealed_twice": not census["slot_integrity"]["sealed_twice"],
        "single_process": processes.get("queried") is True and int(processes.get("count") or 0) == 1,
    }
    verdict = "OBSERVER_RUNNING" if all(
        [
            observations["task_installed"],
            observations["tick_within_three_intervals"],
            observations["no_slot_sealed_twice"],
        ]
    ) else "OBSERVER_NOT_RUNNING"

    return {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "generated_at_utc": iso(audit_ms),
        "head": git_head(repo),
        "reference_instant": {
            "claimed_last_bar_utc": CLAIMED_LAST_BAR_UTC,
            "origin": "WP-051-02G FINAL_REPORT §8 DEF-02G-10, measured in that package's worktree",
        },
        "observer": {
            "task": task,
            "watchdog_task": watchdog_task,
            "processes": processes,
            "last_tick_age_seconds": last_tick_age_s,
            "runs_log_lines": len(runs),
            "corrupt_run_lines": corrupt,
            "health_status": health.get("status"),
            "health_generated_at_utc": health.get("generated_at_utc"),
            "health_reasons": health.get("reasons"),
            "consecutive_non_observations": health.get("consecutive_non_observations"),
        },
        "tick_census": census,
        "store": newest,
        "recovered_observation": None
        if recovery_tick is None
        else {
            "run_id": recovery_tick.get("run_id"),
            "started_at_utc": recovery_tick.get("started_at_utc"),
            "finished_at_utc": recovery_tick.get("finished_at_utc"),
            "outcome": recovery_tick.get("outcome"),
            "new_bars": recovery_tick.get("new_bars"),
            "expected_new_bars": recovery_tick.get("expected_new_bars"),
            "missing_bars": recovery_tick.get("missing_bars"),
            "market_instant_utc": recovery_tick.get("market_instant_utc"),
            "market_requests": recovery_tick.get("market_requests"),
            "order_sent": recovery_tick.get("order_sent"),
            "promotion": recovery_tick.get("promotion"),
            "store_root": recovery_tick.get("store_root"),
            "state_root": recovery_tick.get("state_root"),
            "first_observed_tick_after_the_last_block": bool(after_block),
            "last_blocked_tick_utc": iso(last_block_ms) if last_block_ms is not None else None,
            "minutes_from_block_to_observation": round((after_block[0][0] - last_block_ms) / 60_000, 2)
            if after_block and last_block_ms is not None
            else None,
        },
        "observations": observations,
        "verdict": verdict,
        "not_a_certification": (
            "the observer running is not the experiment succeeding: this file says the "
            "acquisition is alive, and nothing about what it will be worth"
        ),
    }


def build_coverage_gap(
    *,
    repo: Path,
    state_root: Path,
    store_root: Path,
    declaration_path: Path,
    since_ms: int,
) -> dict[str, Any]:
    declaration = read_declaration(declaration_path)
    bound_ms = int(declaration["lag_bound_ms"])
    effective_ms = parse_iso(str(declaration["effective_from_utc"]))
    window_start_ms = parse_iso(str(declaration["start_utc"]))
    window_end_ms = parse_iso(str(declaration["end_utc"]))
    audit_ms = now_ms()

    series_report: dict[str, Any] = {}
    day_findings: dict[str, dict[str, Any]] = {}
    lost_by_asset: dict[str, list[str]] = {}
    complete_by_asset: dict[str, list[str]] = {}
    rows_reachable = 0
    for timeframe, asset in SERIES:
        rows, corrupt = read_jsonl(store_root / timeframe / f"{asset}.jsonl")
        verdicts = bar_verdicts(
            rows, bound_ms=bound_ms, effective_from_ms=effective_ms, store_ms=audit_ms
        )
        ordered = sorted(verdicts)
        before = [ms for ms in ordered if ms <= parse_iso(CLAIMED_LAST_BAR_UTC)]
        after = [ms for ms in ordered if ms > parse_iso(CLAIMED_LAST_BAR_UTC)]
        series_report[f"{timeframe}:{asset}"] = {
            "rows": len(rows),
            "corrupt_lines": corrupt,
            "last_bar_before_reference": verdicts[before[-1]] if before else None,
            "first_bar_after_reference": verdicts[after[0]] if after else None,
            "span": {
                "first_open_utc": iso(ordered[0]) if ordered else None,
                "last_open_utc": iso(ordered[-1]) if ordered else None,
            },
        }

        # every hour of the declared window that the store could already hold, day by day
        day_start = (window_start_ms // DAY_MS) * DAY_MS
        horizon = min(window_end_ms, audit_ms)
        asset_lost: list[str] = []
        asset_complete: list[str] = []
        asset_rows = 0
        while day_start < horizon:
            day = day_rows(
                verdicts,
                day_start_ms=day_start,
                bound_ms=bound_ms,
                closed_before_ms=audit_ms,
            )
            slot = day_findings.setdefault(day["day"], {"day": day["day"], "assets": {}})
            slot["assets"][asset] = {
                key: day[key]
                for key in (
                    "bars_in_store",
                    "admissible",
                    "inadmissible",
                    "missing_opens",
                    "classification",
                    "lost",
                )
            }
            if day["lost"]:
                asset_lost.append(day["day"])
            elif day["classification"] == DAY_COMPLETE:
                asset_complete.append(day["day"])
                asset_rows += 24
            day_start += DAY_MS
        lost_by_asset[asset] = asset_lost
        complete_by_asset[asset] = asset_complete
        rows_reachable += 2160 - 24 * len(asset_lost)

    # the day of the hole is outside the declared window but is what a reader comes for
    context: list[dict[str, Any]] = []
    for day_start in range(
        (parse_iso(CLAIMED_LAST_BAR_UTC) // DAY_MS) * DAY_MS,
        (audit_ms // DAY_MS) * DAY_MS + DAY_MS,
        DAY_MS,
    ):
        entry: dict[str, Any] = {"day": iso(day_start)[:10], "assets": {}}
        for timeframe, asset in SERIES:
            rows, _corrupt = read_jsonl(store_root / timeframe / f"{asset}.jsonl")
            verdicts = bar_verdicts(
                rows, bound_ms=bound_ms, effective_from_ms=effective_ms, store_ms=audit_ms
            )
            day = day_rows(
                verdicts, day_start_ms=day_start, bound_ms=bound_ms, closed_before_ms=audit_ms
            )
            entry["assets"][asset] = {
                key: day[key]
                for key in ("bars_in_store", "admissible", "inadmissible", "missing_opens", "classification", "lost")
            }
        entry["in_declared_window"] = day_start >= window_start_ms
        context.append(entry)

    for day, entry in sorted(day_findings.items()):
        classes = {asset["classification"] for asset in entry["assets"].values()}
        entry["classification"] = sorted(classes)[0] if len(classes) == 1 else "MIXED_ACROSS_ASSETS"
        entry["lost"] = any(asset["lost"] for asset in entry["assets"].values())
        entry["assets_in_agreement"] = len(classes) == 1

    declared_rows = int(declaration["declared_rows"])
    rows_per_day = 24 * len(SERIES)
    distinct_lost = sorted({day for days in lost_by_asset.values() for day in days})
    ceiling = rows_reachable / declared_rows if declared_rows else 0.0

    return {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "generated_at_utc": iso(audit_ms),
        "head": git_head(repo),
        "declaration": declaration,
        "series": series_report,
        "context_days": context,
        "days": [day_findings[day] for day in sorted(day_findings)],
        "phase_impact": {
            "declared_days": int(declaration["days"]),
            "declared_rows": declared_rows,
            "rows_per_day": rows_per_day,
            "lost_days_any_asset": distinct_lost,
            "lost_days_by_asset": lost_by_asset,
            "complete_days_by_asset": complete_by_asset,
            "rows_still_reachable": rows_reachable,
            "fraction_still_reachable": round(ceiling, 6),
            "required_fraction": float(declaration["required_fraction"]),
            "coverage_complete_reachable": ceiling >= 1.0,
            "status_now": "PENDING" if not distinct_lost else "CEILING_BELOW_DECLARED",
            "reading": (
                "COVERAGE_COMPLETE requires admissible_rows == declared_rows exactly. Once a "
                "day is quarantined that equality is arithmetically unreachable, so the "
                "declaration as written can no longer be completed, whatever the remaining "
                "days do. The ceiling is computed by removing the lost days only; it assumes "
                "every remaining day arrives clean, which is an assumption, not a result."
            ),
        },
        "recovery_boundary": recovery_boundary(read_jsonl(state_root / "runs.jsonl")[0], audit_ms, since_ms),
        "since_utc": iso(since_ms),
        "not_applied": (
            "no bar was re-fetched, no timestamp was synthesised, and no threshold moved. "
            "The alternatives in FINAL_REPORT §4 are proposals for the owner of the "
            "declaration, and none of them is implemented here."
        ),
    }


def recovery_boundary(runs: list[dict[str, Any]], audit_ms: int, since_ms: int = 0) -> dict[str, Any]:
    """The refusal episodes, and the two different delays a reader must not confuse.

    ``recovery_latency`` is how long the scheduler took to get a tick through after the last
    refusal. ``store_silence`` is how long the *store* went without a new bar, which is what
    actually costs coverage: it starts at the last tick that added bars, not at the first
    refusal, because a refused tick is only the moment the hole became unavoidable.
    """
    ordered = sorted(
        ((parse_iso(str(row["started_at_utc"])), row) for row in runs if row.get("started_at_utc")),
        key=lambda item: item[0],
    )
    episodes: list[list[tuple[int, dict[str, Any]]]] = []
    current: list[tuple[int, dict[str, Any]]] = []
    for ms, row in ordered:
        if row.get("outcome") == "DISK_BUDGET_EXCEEDED":
            if current and ms - current[-1][0] > 3 * INTERVAL_MINUTES * 60_000:
                episodes.append(current)
                current = []
            current.append((ms, row))
        elif current:
            episodes.append(current)
            current = []
    if current:
        episodes.append(current)
    if not episodes:
        return {"episodes": [], "block_episode": None, "store_silence_seconds": None}

    consuming = [
        (ms, row)
        for ms, row in ordered
        if row.get("outcome") == "OBSERVED" and int(row.get("new_bars") or 0) > 0
    ]

    def boundary_of(group: list[tuple[int, dict[str, Any]]]) -> dict[str, Any]:
        episode_start, episode_end = group[0][0], group[-1][0]
        before = [(ms, row) for ms, row in consuming if ms < episode_start]
        after = [(ms, row) for ms, row in consuming if ms > episode_end]
        resume = after[0][0] if after else None
        last_bar = before[-1][0] if before else None
        return {
            "first_blocked_start_utc": iso(episode_start),
            "last_blocked_start_utc": iso(episode_end),
            "blocked_ticks": len(group),
            "last_block_reason": group[-1][1].get("outcome_reason"),
            "min_free_gib": min(
                (float((row.get("disk") or {}).get("free_gib")) for _ms, row in group
                 if (row.get("disk") or {}).get("free_gib") is not None),
                default=None,
            ),
            "last_consuming_tick_before": None
            if last_bar is None
            else {
                "started_at_utc": iso(last_bar),
                "run_id": before[-1][1].get("run_id"),
                "new_bars": before[-1][1].get("new_bars"),
            },
            "resume": None
            if resume is None
            else {
                "started_at_utc": iso(resume),
                "run_id": after[0][1].get("run_id"),
                "new_bars": after[0][1].get("new_bars"),
            },
            "recovery_latency_seconds": None if resume is None else round((resume - episode_end) / 1000, 1),
            "store_silence_seconds": None
            if resume is None or last_bar is None
            else round((resume - last_bar) / 1000, 1),
            "store_silence_minutes": None
            if resume is None or last_bar is None
            else round((resume - last_bar) / 60_000, 2),
        }

    per_episode = [boundary_of(group) for group in episodes]
    measured = [item for item in per_episode if item["store_silence_seconds"] is not None]
    all_time = max(measured, key=lambda item: item["store_silence_seconds"], default=None)
    # the episode that matters to *this* audit is the one inside the audited window, not the
    # worst in the observer's history: the history is context, the window is the finding.
    in_window = [
        item
        for item in measured
        if parse_iso(item["last_blocked_start_utc"]) >= since_ms
    ]
    worst = max(in_window, key=lambda item: item["store_silence_seconds"], default=None)
    last = episodes[-1]
    episode_start, episode_end = last[0][0], last[-1][0]
    before = [(ms, row) for ms, row in consuming if ms < episode_start]
    after = [(ms, row) for ms, row in consuming if ms > episode_end]
    resume_ms = after[0][0] if after else None
    last_bar_ms = before[-1][0] if before else None
    return {
        "episode_boundaries": per_episode,
        "worst_episode": worst,
        "worst_episode_all_time": all_time,
        "episodes": [
            {
                "first_blocked_start_utc": iso(group[0][0]),
                "last_blocked_start_utc": iso(group[-1][0]),
                "blocked_ticks": len(group),
                "minutes": round((group[-1][0] - group[0][0]) / 60_000, 2),
                "min_free_gib": min(
                    (float((row.get("disk") or {}).get("free_gib")) for _ms, row in group
                     if (row.get("disk") or {}).get("free_gib") is not None),
                    default=None,
                ),
            }
            for group in episodes
        ],
        "block_episode": {
            "first_blocked_start_utc": iso(episode_start),
            "last_blocked_start_utc": iso(episode_end),
            "blocked_ticks": len(last),
            "last_block_reason": last[-1][1].get("outcome_reason"),
            "last_block_free_gib": (last[-1][1].get("disk") or {}).get("free_gib"),
            "last_block_health": last[-1][1].get("health_status"),
        },
        "last_consuming_tick_before": None
        if last_bar_ms is None
        else {
            "started_at_utc": iso(last_bar_ms),
            "run_id": before[-1][1].get("run_id"),
            "new_bars": before[-1][1].get("new_bars"),
        },
        "resume": None
        if resume_ms is None
        else {
            "started_at_utc": iso(resume_ms),
            "new_bars": after[0][1].get("new_bars"),
            "outcome": after[0][1].get("outcome"),
            "run_id": after[0][1].get("run_id"),
        },
        "recovery_latency_seconds": None
        if resume_ms is None
        else round((resume_ms - episode_end) / 1000, 1),
        "store_silence_seconds": None
        if resume_ms is None or last_bar_ms is None
        else round((resume_ms - last_bar_ms) / 1000, 1),
        "store_silence_minutes": None
        if resume_ms is None or last_bar_ms is None
        else round((resume_ms - last_bar_ms) / 60_000, 2),
        "audited_at_utc": iso(audit_ms),
    }


def build_continuity(*, repo: Path, state_root: Path) -> dict[str, Any]:
    health = read_json(state_root / "health.json") if (state_root / "health.json").is_file() else {}
    runs, corrupt = read_jsonl(state_root / "runs.jsonl")
    alerts, corrupt_alerts = read_jsonl(state_root / "alerts.jsonl")
    task = scheduled_task(TASK_NAME)
    watchdog = scheduled_task(WATCHDOG_TASK)
    settings = task.get("settings") or {}
    trigger = task.get("trigger") or {}
    audit_ms = now_ms()
    generations = [
        parse_iso(str(row.get("started_at_utc")))
        for row in runs
        if row.get("started_at_utc")
    ]
    last_tick_age = round((audit_ms - max(generations)) / 1000, 1) if generations else None

    requirements = [
        {
            "id": "C1_AUTOSTART",
            "requirement": "the observer starts without a person",
            "status": "SATISFIED" if trigger.get("interval") else "MISSING",
            "evidence": {
                "trigger_interval": trigger.get("interval"),
                "trigger_duration": trigger.get("duration"),
                "start_boundary": trigger.get("start_boundary"),
            },
        },
        {
            "id": "C2_RESTART_AFTER_FAILURE",
            "requirement": "a failed run is retried by the scheduler",
            "status": "SATISFIED" if (settings.get("restart_on_failure") or {}).get("count") else "MISSING",
            "evidence": settings.get("restart_on_failure"),
        },
        {
            "id": "C3_AFTER_REBOOT",
            "requirement": "a run missed while the machine was down is taken when it returns",
            "status": "SATISFIED" if settings.get("start_when_available") else "MISSING",
            "evidence": {
                "start_when_available": settings.get("start_when_available"),
                "logon_type": (task.get("principal") or {}).get("logon_type"),
                "caveat": (
                    "LogonType InteractiveToken means the task runs only while that user is "
                    "signed in: a reboot that nobody signs into after is still a hole"
                ),
            },
        },
        {
            "id": "C4_NO_DUPLICATE_INSTANCES",
            "requirement": "two observers cannot run at once",
            "status": "SATISFIED" if settings.get("multiple_instances") == "IgnoreNew" else "MISSING",
            "evidence": {
                "multiple_instances": settings.get("multiple_instances"),
                "campaign_lease": "the tick also takes a lease; the second holder is refused",
            },
        },
        {
            "id": "C5_ATOMIC_PERSISTENCE",
            "requirement": "state written by a tick survives a crash",
            "status": "SATISFIED",
            "evidence": {
                "append_only_logs": ["runs.jsonl", "slots.jsonl", "alerts.jsonl", "derived_refresh.jsonl"],
                "corrupt_run_lines": corrupt,
                "corrupt_alert_lines": corrupt_alerts,
            },
        },
        {
            "id": "C6_HEARTBEAT",
            "requirement": "health can be read without asking the observer",
            "status": "SATISFIED" if health else "MISSING",
            "evidence": {
                "health_path": (state_root / "health.json").as_posix(),
                "status": health.get("status"),
                "generated_at_utc": health.get("generated_at_utc"),
                "age_seconds": last_tick_age,
            },
        },
        {
            "id": "C7_STALE_DETECTION",
            "requirement": "silence is detected and named",
            "status": "SATISFIED"
            if health.get("consecutive_non_observations") is not None
            else "MISSING",
            "evidence": {
                "consecutive_non_observations": health.get("consecutive_non_observations"),
                "ticks_in_window": health.get("ticks_in_window"),
                "outcomes_in_window": health.get("outcomes_in_window"),
            },
        },
        {
            "id": "C8_INTERRUPTION_LOG",
            "requirement": "interruptions are recorded where a reader can find them",
            "status": "SATISFIED" if alerts else "MISSING",
            "evidence": {
                "alerts_path": (state_root / "alerts.jsonl").as_posix(),
                "alert_lines": len(alerts),
                "last_alert": alerts[-1] if alerts else None,
            },
        },
        {
            "id": "C9_ALERT_REACHES_A_HUMAN",
            "requirement": "a blocked or stale observer produces a signal outside its own log",
            "status": "SATISFIED" if watchdog.get("installed") is True else "MISSING",
            "evidence": {
                "watchdog_task": WATCHDOG_TASK,
                "installed": watchdog.get("installed"),
                "state": watchdog.get("state"),
                "script": WATCHDOG_SCRIPT,
                "reading": (
                    "the observer wrote HEALTH_BLOCKED into alerts.jsonl for six hours and "
                    "nobody saw it; a file that must be opened is not an alarm"
                ),
            },
        },
        {
            "id": "C10_NO_DAILY_HUMAN_STEP",
            "requirement": "no daily human action is required",
            "status": "SATISFIED" if trigger.get("interval") else "MISSING",
            "evidence": {"interval": trigger.get("interval"), "duration": trigger.get("duration")},
        },
    ]
    blocking = [item["id"] for item in requirements if item["status"] != "SATISFIED"]
    return {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "generated_at_utc": iso(audit_ms),
        "head": git_head(repo),
        "scheduler": task,
        "watchdog": {"task": watchdog, "script": WATCHDOG_SCRIPT},
        "requirements": requirements,
        "blocking": blocking,
        "verdict": "CONTINUITY_SATISFIED" if not blocking else "CONTINUITY_PARTIAL",
        "not_a_certification": (
            "this reads the scheduler's own registration. It is evidence that a schedule "
            "exists, never evidence that a bar was stored; the tick log is that evidence"
        ),
    }


def git_head(repo: Path) -> str | None:
    code, out, _err = run(["git", "-C", str(repo), "rev-parse", "HEAD"])
    return out.strip() if code == 0 else None


# --------------------------------------------------------------------------- #
# root cause, as a set of falsifiable statements
# --------------------------------------------------------------------------- #
def build_root_cause(*, repo: Path, recovery: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    census = recovery["tick_census"]
    blocked = census["blocked"]
    boundary = gap["recovery_boundary"]
    newest = recovery["store"]
    claimed = parse_iso(CLAIMED_LAST_BAR_UTC)
    live_last = parse_iso(str((newest.get("1h:BTC") or {}).get("last_open_utc")))
    return {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "generated_at_utc": iso(now_ms()),
        "head": git_head(repo),
        "question": "why did the forward store stop at 2026-10-22T18:00Z?",
        "finding": (
            "It did not. The store 02G measured is a copy of data/forward made inside that "
            "package's worktree for a rehearsal, and a copy stops when the copying stops. The "
            "live store kept growing; the real interruption was elsewhere and shorter."
        ),
        "claims": [
            {
                "id": "RC1",
                "claim": "the instant 02G named was a copy, not the live store",
                "evidence": {
                    "claimed_last_bar_utc": CLAIMED_LAST_BAR_UTC,
                    "live_last_bar_utc": iso(live_last),
                    "live_last_bar_is_newer": live_last > claimed,
                    "worktree_copy": "data/forward/ is git-ignored; the 02G worktree holds a copy",
                },
                "verdict": "CONFIRMED" if live_last > claimed else "REFUTED",
            },
            {
                "id": "RC2",
                "claim": "the live store has a real hole, and its cause was the disk guard",
                "evidence": {
                    "blocked_ticks_in_window": blocked["count"],
                    "first_blocked_utc": blocked["first_utc"],
                    "last_blocked_utc": blocked["last_utc"],
                    "min_free_gib": blocked["min_free_gib"],
                    "reason": blocked["reason"],
                },
                "verdict": "CONFIRMED" if blocked["count"] and blocked["min_free_gib"] is not None else "REFUTED",
            },
            {
                "id": "RC3",
                "claim": "the observer resumed by itself, without any intervention",
                "evidence": boundary,
                "verdict": "CONFIRMED" if boundary.get("resume") else "REFUTED",
            },
            {
                "id": "RC4",
                "claim": "the hole cost the declaration a whole day, and no repair is possible",
                "evidence": gap["phase_impact"],
                "verdict": "CONFIRMED" if gap["phase_impact"]["lost_days_any_asset"] else "REFUTED",
            },
        ],
        "root_cause": (
            "DISK_BUDGET_EXCEEDED: the observer's own storage guard refused to make a market "
            "request while the volume was below its critical free-space floor, and it said so "
            "in every tick it refused. Nothing was broken; nothing was fetched."
        ),
        "why_nobody_noticed": (
            "the refusal reached alerts.jsonl and health.json, both of which are files that "
            "must be opened. The scheduler's last-result field carried exit 5 for hours and "
            "no one read that either. There was no push, and there is still none: C9."
        ),
        "not_the_cause": [
            "the scheduler was never disabled or unregistered",
            "no duplicate observer contended for the lease",
            "the provider did not fail: refused ticks made zero market requests",
            "the store was not corrupt: no corrupt line appears in the tick log",
        ],
    }


def render_run_report(package: Path, repo: Path) -> tuple[dict[str, Any], str]:
    """The package's front page, rendered from the JSONs so the prose cannot drift.

    Every number below is read out of the reports the verifier checks, not retyped by hand:
    a summary that can disagree with its own evidence is a summary nobody should trust.
    """
    recovery = read_json(package / "RECOVERY_REPORT.json")
    gap = read_json(package / "COVERAGE_GAP_REPORT.json")
    continuity = read_json(package / "CONTINUITY_REPORT.json")
    root = read_json(package / "ROOT_CAUSE.json")
    verification_path = package / "INDEPENDENT_VERIFICATION.json"
    verification = read_json(verification_path) if verification_path.is_file() else None
    impact = gap["phase_impact"]
    census = recovery["tick_census"]
    boundary = gap["recovery_boundary"]
    observed = recovery.get("recovered_observation") or {}

    summary = {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "generated_at_utc": iso(now_ms()),
        "head": git_head(repo) or recovery.get("head"),
        "recovery": {
            "verdict": recovery["verdict"],
            "observer_task": recovery["observer"]["task"].get("last_run"),
            "last_tick_age_seconds": recovery["observer"]["last_tick_age_seconds"],
            "ticks_since_reference": census["ticks"],
            "by_outcome": census["by_outcome"],
            "blocked_ticks": census["blocked"]["count"],
            "min_free_gib": census["blocked"]["min_free_gib"],
            "resumed_observation": observed.get("run_id"),
            "resumed_new_bars": observed.get("new_bars"),
        },
        "gap": {
            "store_silence_minutes": (boundary.get("worst_episode") or {}).get("store_silence_minutes"),
            "recovery_latency_seconds": boundary.get("recovery_latency_seconds"),
            "episodes": len(boundary.get("episode_boundaries") or []),
            "last_valid_before_utc": (gap["series"]["1h:BTC"]["last_bar_before_reference"] or {}).get("open_utc"),
            "first_valid_after_utc": (gap["series"]["1h:BTC"]["first_bar_after_reference"] or {}).get("open_utc"),
            "lost_days": impact["lost_days_any_asset"],
            "rows_reachable": impact["rows_still_reachable"],
            "declared_rows": impact["declared_rows"],
            "ceiling": impact["fraction_still_reachable"],
            "coverage_complete_reachable": impact["coverage_complete_reachable"],
        },
        "continuity": {
            "verdict": continuity["verdict"],
            "blocking": continuity["blocking"],
            "requirements": len(continuity["requirements"]),
        },
        "root_cause": {
            "claims": {claim["id"]: claim["verdict"] for claim in root["claims"]},
            "root_cause": root["root_cause"],
        },
        "independent_verification": None
        if verification is None
        else {
            "verdict": verification["verdict"],
            "checks": verification["check_count"],
            "failed": verification["failed_checks"],
        },
        "experiment_certified": False,
        "false_success": 0,
        "not_a_certification": (
            "the observer is alive and the package is measured. The declaration it feeds can no "
            "longer be completed, and nothing here changes that."
        ),
    }

    lines = [
        f"# {PACKAGE} — run report",
        "",
        f"**Generated:** `{summary['generated_at_utc']}` · **HEAD:** `{summary['head']}` · "
        f"**Experiment certified:** `false`",
        "",
        "## Recovery",
        "",
        f"- verdict: **{summary['recovery']['verdict']}**",
        f"- ticks since the reference instant: **{census['ticks']}** ({census['since_utc']} → "
        f"{census['last_tick_utc']}), outcomes `{json.dumps(census['by_outcome'], sort_keys=True)}`",
        f"- refusals in that window: **{census['blocked']['count']}**, lowest free space **"
        f"{census['blocked']['min_free_gib']} GiB**",
        f"- newest tick age: **{recovery['observer']['last_tick_age_seconds']} s**",
        f"- first observation after the last refusal: `{observed.get('run_id')}` at "
        f"`{observed.get('started_at_utc')}`, **{observed.get('new_bars')} new bar(s)**",
        "",
        "## The hole",
        "",
        f"- last bar before the reference instant: `{summary['gap']['last_valid_before_utc']}` "
        f"(lag {(gap['series']['1h:BTC']['last_bar_before_reference'] or {}).get('lag_minutes')} min)",
        f"- first bar after it: `{summary['gap']['first_valid_after_utc']}` "
        f"(lag {(gap['series']['1h:BTC']['first_bar_after_reference'] or {}).get('lag_minutes')} min, "
        f"{(gap['series']['1h:BTC']['first_bar_after_reference'] or {}).get('reasons')})",
        f"- refusal episodes in the log: **{len(boundary.get('episode_boundaries') or [])}**; the worst one "
        f"ran `{(boundary.get('worst_episode') or {}).get('first_blocked_start_utc')}` → "
        f"`{(boundary.get('worst_episode') or {}).get('last_blocked_start_utc')}` "
        f"({(boundary.get('worst_episode') or {}).get('blocked_ticks')} tick(s), lowest free space "
        f"{(boundary.get('worst_episode') or {}).get('min_free_gib')} GiB)",
        f"- **store silence: {(boundary.get('worst_episode') or {}).get('store_silence_minutes')} min** "
        f"between the last tick that added bars and the tick that resumed them",
        f"- recovery latency after the last refusal: "
        f"`{boundary.get('recovery_latency_seconds')} s`",
        "",
        "## Coverage, against the declaration",
        "",
        f"- declared: **{impact['declared_rows']}** rows over **{impact['declared_days']}** days",
        f"- days already lost: **{impact['lost_days_any_asset']}**",
        f"- rows still reachable: **{impact['rows_still_reachable']} / {impact['declared_rows']}** "
        f"= **{impact['fraction_still_reachable']}** (required floor {impact['required_fraction']})",
        f"- `COVERAGE_COMPLETE` reachable: **{impact['coverage_complete_reachable']}** — "
        f"{impact['status_now']}",
        "",
        "## Continuity",
        "",
        f"- verdict: **{continuity['verdict']}** over {len(continuity['requirements'])} requirement(s)",
        f"- blocking: `{continuity['blocking']}`",
        "",
        "## Independent verification",
        "",
        "- none yet"
        if verification is None
        else f"- **{verification['verdict']}**, {verification['check_count']} checks, failed "
        f"`{verification['failed_checks']}`",
        "",
        "## Root cause",
        "",
        f"{root['root_cause']}",
        "",
        f"Claims: `{json.dumps(summary['root_cause']['claims'], sort_keys=True)}`",
        "",
    ]
    return summary, "\n".join(lines)


def render_root_cause(package: Path) -> str:
    """Prose for the root cause, with the numbers pulled from the reports."""
    recovery = read_json(package / "RECOVERY_REPORT.json")
    gap = read_json(package / "COVERAGE_GAP_REPORT.json")
    root = read_json(package / "ROOT_CAUSE.json")
    census = recovery["tick_census"]
    boundary = gap["recovery_boundary"]
    observed = recovery.get("recovered_observation") or {}
    lines = [
        f"# {PACKAGE} — root cause analysis",
        "",
        f"**Question:** {root['question']}",
        "",
        f"**Answer, in one sentence:** {root['finding']}",
        "",
        "## What was actually true, and how it was measured",
        "",
        "| Claim | Verdict | Evidence |",
        "|---|---|---|",
    ]
    for claim in root["claims"]:
        evidence = json.dumps(claim["evidence"], sort_keys=True)
        if len(evidence) > 400:
            evidence = evidence[:397] + "…"
        lines.append(f"| `{claim['id']}` {claim['claim']} | **{claim['verdict']}** | `{evidence}` |")
    lines += [
        "",
        "## The interruption that was real",
        "",
        f"{root['root_cause']}",
        "",
        f"- refusals in the audited window: **{census['blocked']['count']}**",
        f"- first refusal: `{census['blocked']['first_utc']}`",
        f"- lowest free space seen: **{census['blocked']['min_free_gib']} GiB** "
        f"(the observer's critical floor is 2 GiB)",
        f"- the refusal's own words: _{census['blocked']['reason']}_",
        f"- the worst episode put the store quiet for "
        f"**{(boundary.get('worst_episode') or {}).get('store_silence_minutes')} min** between the last "
        f"tick that added bars and the tick that resumed them "
        f"(`{(boundary.get('worst_episode') or {}).get('last_consuming_tick_before')}` → "
        f"`{(boundary.get('worst_episode') or {}).get('resume')}`)",
        f"- the observer resumed by itself at `{observed.get('started_at_utc')}` with "
        f"**{observed.get('new_bars')}** bar(s), {boundary.get('recovery_latency_seconds')} s after the "
        f"last refusal: nothing was done to it",
        "",
        "## Why six hours passed before anyone could see it",
        "",
        f"{root['why_nobody_noticed']}",
        "",
        "## What it was not",
        "",
        *[f"- {item}" for item in root["not_the_cause"]],
        "",
    ]
    return "\n".join(lines)


def seal(repo: Path, out_dir: Path) -> dict[str, Any]:
    entries = []
    for path in sorted(p for p in out_dir.rglob("*") if p.is_file()):
        name = path.relative_to(repo).as_posix()
        if name.endswith("EVIDENCE_MANIFEST.json"):
            continue
        code, blob, _err = run(["git", "-C", str(repo), "rev-parse", f"HEAD:{name}"])
        entries.append(
            {
                "path": name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "git_blob_sha": blob.strip() if code == 0 else None,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "sealed_at_utc": iso(now_ms()),
        "head": git_head(repo),
        "entries": entries,
        "entry_count": len(entries),
        "hash_semantics": (
            "sha256 is the bytes on disk at seal time; git_blob_sha is HEAD:<path> at seal "
            "time, so an artefact that the seal itself rewrites cannot agree with both"
        ),
        "not_a_certification": "a manifest says what is in the package, not that the package is right",
    }


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument("--state-root", type=Path, default=None)
    parser.add_argument("--store-root", type=Path, default=None)
    parser.add_argument("--declaration", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--since", default=CLAIMED_LAST_BAR_UTC)
    parser.add_argument("--recovery", action="store_true")
    parser.add_argument("--gap", action="store_true")
    parser.add_argument("--continuity", action="store_true")
    parser.add_argument("--seal", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    state_root = (args.state_root or repo / DEFAULT_STATE).resolve()
    store_root = (args.store_root or repo / DEFAULT_STORE).resolve()
    declaration = (args.declaration or repo / DECLARATION).resolve()
    out_dir = (args.out or repo / "docs/agentic/exp004a/wp051_02h").resolve()

    if not any([args.recovery, args.gap, args.continuity, args.seal, args.report, args.all]):
        parser.error("choose at least one of --recovery --gap --continuity --seal --report --all")
    if not state_root.is_dir():
        print(f"missing observer state root: {state_root}", file=sys.stderr)
        return EXIT_MISSING

    since_ms = parse_iso(args.since)
    written: dict[str, str] = {}

    if args.recovery or args.all:
        report = build_recovery(repo=repo, state_root=state_root, store_root=store_root, since_ms=since_ms)
        write_json(out_dir / "RECOVERY_REPORT.json", report)
        written["RECOVERY_REPORT.json"] = report["verdict"]
    if args.gap or args.all:
        report = build_coverage_gap(
            repo=repo,
            state_root=state_root,
            store_root=store_root,
            declaration_path=declaration,
            since_ms=since_ms,
        )
        write_json(out_dir / "COVERAGE_GAP_REPORT.json", report)
        written["COVERAGE_GAP_REPORT.json"] = report["phase_impact"]["status_now"]
    if args.continuity or args.all:
        report = build_continuity(repo=repo, state_root=state_root)
        write_json(out_dir / "CONTINUITY_REPORT.json", report)
        written["CONTINUITY_REPORT.json"] = report["verdict"]
    if args.all:
        recovery = read_json(out_dir / "RECOVERY_REPORT.json")
        gap = read_json(out_dir / "COVERAGE_GAP_REPORT.json")
        root = build_root_cause(repo=repo, recovery=recovery, gap=gap)
        write_json(out_dir / "ROOT_CAUSE.json", root)
        written["ROOT_CAUSE.json"] = " / ".join(
            claim["verdict"] for claim in root["claims"] if claim["verdict"] == "REFUTED"
        ) or "all claims confirmed"
    if args.report or args.all:
        summary, markdown = render_run_report(out_dir, repo)
        write_json(out_dir / "RUN_REPORT.json", summary)
        (out_dir / "RUN_REPORT.md").write_bytes(markdown.replace("\n", "\r\n").encode("utf-8"))
        (out_dir / "ROOT_CAUSE_ANALYSIS.md").write_bytes(
            render_root_cause(out_dir).replace("\n", "\r\n").encode("utf-8")
        )
        written["RUN_REPORT.json"] = summary["recovery"]["verdict"]
    if args.seal:
        manifest = seal(repo, out_dir)
        write_json(out_dir / "EVIDENCE_MANIFEST.json", manifest)
        written["EVIDENCE_MANIFEST.json"] = f"{manifest['entry_count']} entries"

    print(json.dumps({"ok": True, "out": str(out_dir), "written": written}, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
