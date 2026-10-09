"""ST-6 — a read-only external witness of the scheduled task.

The Task Scheduler's Operational channel is **disabled on this host and has never recorded
anything**, so no per-run external record of the ST-6 schedule exists and none can be recovered for
the period that has already run.  This program never changes a system setting: it does not enable a
channel, does not touch the audit policy, does not register a task and does not clear a log.  What
it does instead is build the only external record this host can give as it stands:

* it samples the **scheduler's own reporting** for the task (``Get-ScheduledTaskInfo``: last run
  instant, last result, next run instant, missed-run counter, state) and the task's own
  registration, and it stores the raw answer verbatim with its sha256, so the sample can be checked
  against the operating system rather than trusted;
* it samples the **operating system's process table** for the tick in flight and resolves the
  process that launched it, so a run that the scheduler started can be told from one a person
  started: a tick whose parent is the Task Scheduler service was launched by the scheduler;
* it records the **channel state** it found (enabled/disabled, whether the event file exists at all,
  its size and mtime, and whether the Security log can be read), because "there is no evidence" is
  itself a finding and has to be dated and bounded;
* it keeps a compact, append-only witness log with atomic and idempotent writes and a declared
  bound, and it writes the retention audit that states exactly which external evidence survives,
  which has been lost to the disabled channel, and the one remediation that would recover it —
  which needs an administrator's authorisation and is therefore not applied here.

The witness is evidence about the schedule, never evidence about the market: it takes no sample,
makes no market request, renews no lease and holds nothing.

Run:  python scripts/st6_scheduler_witness.py --export          (channel state + retention audit)
      python scripts/st6_scheduler_witness.py --once            (one sample, then exit)
      python scripts/st6_scheduler_witness.py --watch 3600      (sample every interval for a while)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "st6"
WITNESS_LOG = DATA / "ST6_SCHEDULER_WITNESS.jsonl"
EVIDENCE_JSON = DATA / "ST6_SCHEDULER_EVIDENCE.json"
RETENTION_MD = DATA / "ST6_RETENTION_AUDIT.md"
TASK_NAME = "TradingAgentic-ST6-Forward"
#: The channels that could carry a per-run record of this task, in the order a reader should try
#: them.  The first is disabled on this host; the second is enabled but holds only maintenance
#: events, which name no task.
CHANNELS = (
    "Microsoft-Windows-TaskScheduler/Operational",
    "Microsoft-Windows-TaskScheduler/Maintenance",
)
#: The evidence file of each channel, as the operating system names it (``%SystemRoot%`` expanded
#: here).  A disabled channel that has never been enabled leaves no file behind, and a missing file
#: is stronger than a "no events" reading: it says the channel never recorded, not that the log is
#: empty.
EVTX_DIR = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "winevt" / "Logs"
WITNESS_KEPT = 20160  # fourteen days of minute samples: bounded, and longer than the period
DEFAULT_INTERVAL_S = 60.0
POWERSHELL_TIMEOUT_S = 60
#: What would recover per-run external evidence.  Recorded, never applied: it is a machine-wide
#: audit setting and it needs an administrator.
REMEDIATION = {
    "what": "enable the Task Scheduler operational channel for this host",
    "command": "wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true",
    "privilege": "administrator",
    "authorised": False,
    "why_not_applied": (
        "it changes a machine-wide audit setting, it needs an administrator, and it cannot recover "
        "the runs that have already happened: the channel records from the moment it is enabled"
    ),
    "what_it_would_give": (
        "per-run events (100 started, 102 completed, 107/110 triggered, 200/201 action started and "
        "finished) with their own record ids, so every slot could be corroborated run by run instead "
        "of from a point-in-time sample"
    ),
}


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    """Write through a temporary file in the same directory and replace: no half-written artefact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _append_jsonl_atomic(path: Path, record: dict[str, Any], keep: int) -> int:
    """Append one line, then bound the log.  Returns how many old lines the bound dropped.

    The append opens the file in append mode and writes one line, so a reader never sees a partial
    record; the pruning that follows rewrites the bounded tail through a temporary file, so the log
    is never left truncated mid-line either.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
    rows = _read_jsonl(path)
    if len(rows) <= keep:
        return 0
    dropped = len(rows) - keep
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows[-keep:]),
        encoding="utf-8",
    )
    temporary.replace(path)
    return dropped


# ---------------------------------------------------------------------------------------------
# reading the operating system (read-only)
# ---------------------------------------------------------------------------------------------


def powershell(script: str, timeout: int = POWERSHELL_TIMEOUT_S) -> dict[str, Any]:
    """Run one read-only PowerShell expression and report its raw answer verbatim."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:  # a missing or hanging shell is a recorded finding, not a crash
        return {
            "exit_code": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout or "",
        "stderr": (result.stderr or "").strip()[:1000],
        "error": None if result.returncode == 0 else (result.stderr or "").strip()[:1000],
    }


def _channel_file_state(name: str) -> dict[str, Any]:
    """The channel's own log file, if it exists at all."""
    candidate = EVTX_DIR / f"{name.replace('/', '%4')}.evtx"
    if not candidate.exists():
        return {
            "path": str(candidate),
            "exists": False,
            "bytes": None,
            "last_write_utc": None,
            "reading": (
                "no event file exists, so this channel has never recorded on this host: a channel "
                "that was enabled and later disabled keeps its file"
            ),
        }
    stat = candidate.stat()
    return {
        "path": str(candidate),
        "exists": True,
        "bytes": stat.st_size,
        "last_write_utc": datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reading": "the channel has recorded at least once on this host",
    }


def wevtutil(*arguments: str) -> dict[str, Any]:
    """Ask the operating system's own event-log tool, answering *why* when it cannot be reached.

    A tool that is missing, denied or slow is a finding about the evidence, not an exception that
    stops the audit: the witness must be able to say "this source is not readable" with the same
    confidence with which it says "this source is empty".
    """
    try:
        completed = subprocess.run(
            ["wevtutil", *arguments],
            capture_output=True,
            text=True,
            timeout=POWERSHELL_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "stdout": "",
            "stderr": "",
            "exit_code": None,
            "error": f"{type(exc).__name__}: {exc}"[:200],
            "reachable": False,
        }
    return {
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "exit_code": completed.returncode,
        "error": None,
        "reachable": True,
    }


def channel_depth(channel: str) -> dict[str, Any]:
    """How far back a channel can still answer, and how much of it has already rotated away.

    A circular log evicts its oldest record when it fills, so the numbers the operating system
    reports about the log itself are the measure of what has already been lost: the number of
    records held, the number of the oldest record still present, and the instant of that record.
    A channel that never existed answers nothing, which is a different finding from an empty log,
    and the difference is kept here instead of being flattened into "no events".
    """
    fields = wevtutil("gli", channel)
    depth: dict[str, str] = {}
    for line in (fields["stdout"] or "").splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            depth[key.strip()] = value.strip()
    numbers: dict[str, int | None] = {}
    for key, name in (
        ("numberOfLogRecords", "records_held"),
        ("oldestRecordNumber", "oldest_record_number"),
        ("fileSize", "file_size_bytes"),
    ):
        try:
            numbers[name] = int(depth[key])
        except (KeyError, ValueError):
            numbers[name] = None
    oldest_record_number = numbers["oldest_record_number"]
    oldest = wevtutil("qe", channel, "/c:1", "/rd:false", "/f:text")
    newest = wevtutil("qe", channel, "/c:1", "/rd:true", "/f:text")

    # ``wevtutil qe /f:text`` prints the event's date in the host's **local** time even though it
    # ends the field with a Z, so the raw text is kept and converted with the host's own offset:
    # labelling a local instant as UTC would misdate every record this audit retains
    local_offset = datetime.now().astimezone().utcoffset() or timedelta(0)

    def stamp(answer: dict[str, Any]) -> tuple[str | None, str | None]:
        for line in (answer.get("stdout") or "").splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("date:"):
                continue
            raw = stripped.split(":", 1)[1].strip()
            text = raw.rstrip("Zz").split(".")[0]
            try:
                moment = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
            except ValueError:
                return None, raw
            return (moment - local_offset).strftime("%Y-%m-%dT%H:%M:%SZ"), raw
        return None, None

    oldest_utc, oldest_raw = stamp(oldest)
    newest_utc, newest_raw = stamp(newest)

    return {
        "queried_with": f"wevtutil gli {channel}"
        f" / wevtutil qe {channel} /c:1 /rd:false /f:text",
        "exit_code": fields["exit_code"],
        "reachable": fields["reachable"],
        "error": (
            fields["error"] or (fields["stderr"] or "").strip()[:200] or oldest["error"] or None
        ),
        "raw_document": (fields["stdout"] or "").strip()[:2000],
        "raw_document_sha256": _sha256_text(fields["stdout"] or ""),
        "answers_nothing": not (fields["stdout"] or "").strip(),
        "records_held": numbers["records_held"],
        "file_size_bytes": numbers["file_size_bytes"],
        "oldest_record_number": oldest_record_number,
        "oldest_retained_event_utc": oldest_utc,
        "oldest_retained_event_raw": oldest_raw,
        "newest_retained_event_utc": newest_utc,
        "newest_retained_event_raw": newest_raw,
        "host_utc_offset_minutes": int(local_offset.total_seconds() // 60),
        "event_date_reading": (
            "the tool prints an event's date in the host's local time and still ends it with a Z; "
            "the raw text is kept and the UTC instant beside it is that text minus the host's own "
            "offset, so no local instant is presented as a UTC one"
        ),
        "records_no_longer_present_before_the_oldest": None
        if oldest_record_number is None
        else max(0, oldest_record_number - 1),
        "records_lost_reading": (
            "the log is circular: when it fills, the oldest record is evicted and the number of the "
            "oldest record still present says how many have already gone. A record that rotated out "
            "is not recoverable from this host, and a log that was cleared by hand - a separate "
            "action, not performed here - would advance the same number."
        ),
    }


def channel_state() -> dict[str, Any]:
    """What each candidate channel says about itself, read through its own tooling."""
    channels: dict[str, Any] = {}
    for name in CHANNELS:
        query = powershell(f'wevtutil gl "{name}"')
        raw = query["stdout"]
        enabled: bool | None = None
        log_file: str | None = None
        retention: bool | None = None
        max_size: int | None = None
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("enabled:"):
                enabled = stripped.split(":", 1)[1].strip().lower() == "true"
            elif stripped.lower().startswith("logfilename:"):
                log_file = stripped.split(":", 1)[1].strip()
            elif stripped.lower().startswith("retention:"):
                retention = stripped.split(":", 1)[1].strip().lower() == "true"
            elif stripped.lower().startswith("maxsize:"):
                try:
                    max_size = int(stripped.split(":", 1)[1].strip())
                except ValueError:
                    max_size = None
        records = powershell(
            f"try {{ (Get-WinEvent -LogName '{name}' -MaxEvents 1 -ErrorAction Stop).RecordId }} "
            "catch { 'NO_EVENTS_OR_DENIED' }"
        )
        channels[name] = {
            "queried_with": f"wevtutil gl {name}",
            "query_exit_code": query["exit_code"],
            "query_error": query["error"],
            "enabled": enabled,
            "log_file_as_declared": log_file,
            "raw_document_sha256": _sha256_text(raw),
            "raw_document": raw.strip()[:4000],
            "file": _channel_file_state(name),
            "latest_record_probe": records["stdout"].strip()[:200] or records["error"],
            "retention_is_archive": retention,
            "retention_reading": (
                "archive: the log keeps what it has"
                if retention
                else "circular: the oldest record is evicted when the log fills"
            ),
            "max_size_bytes": max_size,
            "depth": channel_depth(name),
        }
    # the Security channel would carry a process-creation record (4688) if that audit subcategory
    # were on; reading it needs a privilege this session does not hold, and that is recorded rather
    # than glossed over: an unreadable source is not an empty source.
    security = powershell(
        "try { (Get-WinEvent -LogName Security -MaxEvents 1 -ErrorAction Stop).RecordId } "
        "catch { 'DENIED_OR_UNAVAILABLE: ' + $_.Exception.Message }"
    )
    # readable means the channel answered with a record: an error, an empty answer and a denial are
    # all *not* readable, and the difference between them is kept in the probe beside it
    readable = security["exit_code"] == 0 and bool(security["stdout"].strip())
    return {
        "channels": channels,
        "security_log_readable": readable and not security["stdout"].startswith(
            "DENIED_OR_UNAVAILABLE"
        ),
        "security_log_probe": (
            security["stdout"].strip()[:300] or security["error"] or "no answer from the channel"
        )[:300],
        "security_log_reading": (
            "the Security channel is not readable from this session, so a per-run process-creation "
            "record could not be used even if the audit subcategory were enabled"
        ),
    }


TASK_REPORT_SCRIPT = (
    "$i = Get-ScheduledTaskInfo -TaskName '{task}'; "
    "$s = Get-ScheduledTask -TaskName '{task}'; "
    "[pscustomobject]@{{ "
    "last_run = $i.LastRunTime; next_run = $i.NextRunTime; last_result = $i.LastTaskResult; "
    "missed = $i.NumberOfMissedRuns; state = $s.State.ToString(); "
    "triggers = @($s.Triggers | ForEach-Object {{ @{{ interval = $_.Repetition.Interval; "
    "duration = $_.Repetition.Duration; start = $_.StartBoundary }} }}); "
    "actions = @($s.Actions | ForEach-Object {{ @{{ execute = $_.Execute; "
    "arguments = $_.Arguments; working_directory = $_.WorkingDirectory }} }}) }} | "
    "ConvertTo-Json -Depth 5 -Compress"
)

OFFSET_SCRIPT = "[int]([DateTimeOffset]::Now.Offset.TotalMinutes)"

BOOT_SCRIPT = (
    "(Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).LastBootUpTime"
)

PROCESS_SCRIPT = (
    "$pattern = 'st6_forward_regime.py'; "
    "$found = @(); "
    "foreach ($p in Get-CimInstance Win32_Process) {{ "
    "if ($p.CommandLine -and $p.CommandLine -match $pattern) {{ "
    "$parent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $p.ParentProcessId) "
    "-ErrorAction SilentlyContinue; "
    "$found += [pscustomobject]@{{ pid = $p.ProcessId; parent_pid = $p.ParentProcessId; "
    "parent_name = $(if ($parent) {{ $parent.Name }} else {{ 'GONE' }}); "
    "created_at = $p.CreationDate; command_line = $p.CommandLine }} }} }}; "
    "@($found) | ConvertTo-Json -Depth 4 -Compress"
)


def _cim_epoch_ms(value: Any) -> datetime | None:
    """A CIM date as a UTC instant, or ``None`` when it is not one.

    Two shapes arrive from Windows: the ``/Date(ms)/`` form that PowerShell's JSON writer produces
    for a DateTime, and the DMTF form ``yyyymmddHHMMSS.ffffff+ooo`` that ``Win32_OperatingSystem``
    and ``Win32_Process`` carry.  Both are read here, because a boot instant that silently came back
    as ``None`` would hide a restart inside a slot — and a restart is exactly the discontinuity that
    stops the external record carrying an absence.
    """
    text = str(value or "").strip()
    if text.startswith("/Date(") and text.endswith(")/"):
        try:
            return datetime.fromtimestamp(int(text[6:-2]) / 1000.0, UTC)
        except (TypeError, ValueError):
            return None
    dmtf = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\.\d+([+-]\d{1,4})?", text)
    if dmtf is None:
        return None
    year, month, day, hour, minute, second, offset = dmtf.groups()
    try:
        moment = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second), tzinfo=UTC
        )
    except ValueError:
        return None
    if offset:
        sign = 1 if offset.startswith("+") else -1
        minutes = int(offset[1:]) if len(offset) > 3 else int(offset[1:]) * 60
        moment -= timedelta(minutes=sign * minutes)
    return moment


def task_report() -> dict[str, Any]:
    """The scheduler's own answer about the task, kept raw and interpreted beside it."""
    answer = powershell(TASK_REPORT_SCRIPT.format(task=TASK_NAME))
    document: dict[str, Any] = {}
    parse_error = None
    if answer["stdout"].strip():
        try:
            document = json.loads(answer["stdout"].strip())
        except json.JSONDecodeError as exc:
            parse_error = f"JSONDecodeError: {exc}"
    last_run = _cim_epoch_ms(document.get("last_run"))
    next_run = _cim_epoch_ms(document.get("next_run"))
    return {
        "raw_document": answer["stdout"].strip(),
        "raw_document_sha256": _sha256_text(answer["stdout"]),
        "query_exit_code": answer["exit_code"],
        "query_error": answer["error"],
        "parse_error": parse_error,
        "last_run_at_utc": last_run.strftime("%Y-%m-%dT%H:%M:%SZ") if last_run else None,
        "next_run_at_utc": next_run.strftime("%Y-%m-%dT%H:%M:%SZ") if next_run else None,
        "last_task_result": document.get("last_result"),
        "number_of_missed_runs": document.get("missed"),
        "state": document.get("state"),
        "triggers": document.get("triggers"),
        "actions": document.get("actions"),
        "reading": (
            "the last run instant and the last result are the scheduler's own record of the task; "
            "they are the strongest external evidence this host can give, and they describe only "
            "the most recent run"
        ),
    }


def tick_processes(declared_arguments: str | None) -> dict[str, Any]:
    """The tick's process, if it is running, and the process that launched it."""
    answer = powershell(PROCESS_SCRIPT)
    rows: list[dict[str, Any]] = []
    parse_error = None
    if answer["stdout"].strip() and answer["stdout"].strip() != "null":
        try:
            parsed = json.loads(answer["stdout"].strip())
            rows = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError as exc:
            parse_error = f"JSONDecodeError: {exc}"
    observed: list[dict[str, Any]] = []
    for row in rows:
        created = _cim_epoch_ms(row.get("created_at"))
        parent_name = str(row.get("parent_name") or "").lower()
        command_line = str(row.get("command_line") or "")
        observed.append(
            {
                "pid": row.get("pid"),
                "parent_pid": row.get("parent_pid"),
                "parent_name": row.get("parent_name"),
                "created_at_utc": created.strftime("%Y-%m-%dT%H:%M:%SZ") if created else None,
                "command_line_sha256": _sha256_text(command_line),
                "command_line": command_line[:600],
                "launched_by_the_task_scheduler_service": parent_name == "svchost.exe",
                "carries_the_declared_arguments": bool(declared_arguments)
                and declared_arguments in command_line,
            }
        )
    return {
        "observed": observed,
        "count": len(observed),
        "parse_error": parse_error,
        "reading": (
            "a tick whose parent process is svchost.exe was launched by the Task Scheduler service, "
            "not by a person; the parent's own command line is not readable from this session, so "
            "the service is identified by the parent's image name and by the process creation "
            "instant"
        ),
    }


# ---------------------------------------------------------------------------------------------
# the sample
# ---------------------------------------------------------------------------------------------


def take_sample(previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """One dated observation of the operating system, with its raw answers and their hashes."""
    sampled_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    report = task_report()
    declared_arguments = None
    actions = report.get("actions")
    if isinstance(actions, list) and actions:
        declared_arguments = str(actions[0].get("arguments") or "") or None
    processes = tick_processes(declared_arguments)
    boot_probe = powershell(BOOT_SCRIPT)
    boot_time = _cim_epoch_ms(boot_probe["stdout"].strip())
    offset_probe = powershell(OFFSET_SCRIPT)
    offset_minutes: int | None = None
    try:
        offset_minutes = int(offset_probe["stdout"].strip())
    except (TypeError, ValueError):
        offset_minutes = None
    repeats = None
    if (
        previous is not None
        and previous.get("scheduler_raw_document_sha256") == report["raw_document_sha256"]
        and previous.get("processes_sha256") == _sha256_text(json.dumps(processes["observed"], sort_keys=True))
    ):
        repeats = previous.get("sampled_at_utc")
    record: dict[str, Any] = {
        "artifact": "ST6_SCHEDULER_WITNESS_SAMPLE",
        "sample_id": f"{sampled_at}-{uuid.uuid4().hex[:8]}",
        "sampled_at_utc": sampled_at,
        "sampled_at_epoch_s": int(time.time()),
        "task_name": TASK_NAME,
        "collector": str(Path(__file__).relative_to(REPO)).replace("\\", "/"),
        "scheduler_reported_last_run_utc": report["last_run_at_utc"],
        "scheduler_reported_next_run_utc": report["next_run_at_utc"],
        "scheduler_reported_last_result": report["last_task_result"],
        "scheduler_reported_missed_runs": report["number_of_missed_runs"],
        "scheduler_reported_state": report["state"],
        "scheduler_raw_document_sha256": report["raw_document_sha256"],
        "scheduler_query_exit_code": report["query_exit_code"],
        "scheduler_query_error": report["query_error"],
        "scheduler_parse_error": report["parse_error"],
        "tick_processes": processes["observed"],
        "tick_process_count": processes["count"],
        "processes_sha256": _sha256_text(json.dumps(processes["observed"], sort_keys=True)),
        "any_tick_launched_by_the_scheduler_service": any(
            entry["launched_by_the_task_scheduler_service"] for entry in processes["observed"]
        ),
        "system_local_offset_minutes": offset_minutes,
        "system_local_offset_probe": offset_probe["stdout"].strip()[:40],
        # a restart inside a slot is an evidence discontinuity: the machine was down, so the
        # scheduler's persisted last-run field still says what it last ran, but an absence of a
        # launch inside the slot is no longer proof that nothing was due
        "system_last_boot_utc": boot_time.strftime("%Y-%m-%dT%H:%M:%SZ") if boot_time else None,
        "unchanged_since_utc": repeats,
        "reading": (
            "a point-in-time reading of the scheduler's own record and of the process table; it "
            "proves what the host said at this instant and nothing about any other instant"
        ),
        "system_time_utc_used_for_conversion": _utc(),
    }
    if repeats is None:
        # the raw answer is kept whenever it changed: identical samples are the common case and an
        # identical answer adds no evidence, only bytes
        record["scheduler_raw_document"] = report["raw_document"][:4000]
    return record


def coverage(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """What the witness log covers, stated as an interval rather than as a claim."""
    stamps = sorted(str(row["sampled_at_utc"]) for row in samples)
    observed_runs = sorted(
        {
            str(row["scheduler_reported_last_run_utc"])
            for row in samples
            if row.get("scheduler_reported_last_run_utc")
        }
    )
    service_launches = [
        row["sampled_at_utc"]
        for row in samples
        if row.get("any_tick_launched_by_the_scheduler_service")
    ]
    return {
        "samples": len(samples),
        "covered_from_utc": stamps[0] if stamps else None,
        "covered_to_utc": stamps[-1] if stamps else None,
        "distinct_scheduler_last_run_instants_observed": observed_runs,
        "scheduler_engine_launches_observed": len(service_launches),
        "launch_instants_observed": service_launches[:50],
        "reading": (
            "the witness can corroborate a run only inside the interval it covers, and it records "
            "the instant the scheduler reported for each launch it saw"
        ),
    }


#: The per-run events the operational channel would carry, with the meaning the provider declares
#: for each.  None of them exists on this host: the channel has never recorded, so what is written
#: here is the declared schema of the provider and it could **not** be verified against a single
#: event of this installation, which is a limitation and is recorded as one.
PER_RUN_EVENT_IDS = (
    {"id": 100, "meaning": "the task's action started: a run of this task began"},
    {"id": 102, "meaning": "the task's action completed, with the result code it returned"},
    {"id": 107, "meaning": "the task's trigger fired on its own schedule"},
    {"id": 110, "meaning": "the task was launched because a person asked for it"},
    {"id": 200, "meaning": "the action's executable was started"},
    {"id": 201, "meaning": "the action's executable finished, with its exit code"},
)


#: The task identifier a reader must match on: the scheduler records a task by its full path, and a
#: name alone matches more than one registration.
TASK_IDENTIFIER_READING = (
    "a per-run record has to be correlated by the task's full name, its own instance and its action, "
    "with the timestamps of the start and of the action's start and finish; LastTaskResult and "
    "LastRunTime alone are the most recent values of a task, not a history, and an event id on its "
    "own — 100 against 110, a scheduled trigger against a launch asked for by hand — does not "
    "establish that the run was scheduled"
)


def rotation_assessment(channels: dict[str, Any]) -> dict[str, Any]:
    """What the log files themselves say about evidence already lost to rotation."""
    lapsed: dict[str, Any] = {}
    for name, entry in channels["channels"].items():
        depth = entry["depth"]
        lost = depth.get("records_no_longer_present_before_the_oldest")
        # a source that cannot be read is not a source that never recorded, and neither of them is
        # an empty log: the three are told apart here because only the last one can support the
        # reading "this channel holds no run of this task"
        if depth.get("reachable") is False:
            state = "EXTERNAL_RECORD_NOT_READABLE"
        elif depth["answers_nothing"]:
            state = "NEVER_RECORDED"
        elif lost:
            state = "RECORDS_ROTATED_OUT"
        else:
            state = "NO_ROTATION_LOSS_OBSERVED"
        if state != "NO_ROTATION_LOSS_OBSERVED":
            bigger = entry.get("max_size_bytes") or 0
            lapsed[name] = {
                "state": state,
                "error": depth.get("error"),
                "records_no_longer_present_before_the_oldest": lost,
                "oldest_retained_event_utc": depth["oldest_retained_event_utc"],
                "newest_retained_event_utc": depth["newest_retained_event_utc"],
                "circular": entry["retention_is_archive"] is False,
                "full": bigger > 0 and (depth.get("file_size_bytes") or 0) >= bigger,
            }
    return {
        "artifact": "ST6_EXTERNAL_ROTATION_ASSESSMENT",
        "generated_at_utc": _utc(),
        "status": "EXTERNAL_RECORD_ROTATION_LOSS_RECORDED" if lapsed else "NO_ROTATION_LOSS_OBSERVED",
        "channels": lapsed,
        "reading": (
            "where a log is circular and has filled, its oldest records are already gone: the "
            "number of the oldest record still present is the count of what this host can no longer "
            "answer for. A channel that cannot be read at all is kept apart from one that never "
            "recorded and from an empty log — only a readable, empty channel could support the "
            "reading that it holds no run. Either way the loss is a property of the evidence, "
            "recorded so that a slot the surviving record does not cover is never called provably "
            "unattended"
        ),
        "does_not_authorise": (
            "clearing, resizing, re-enabling or pruning any log: this reading is taken read-only and "
            "the loss it names cannot be repaired for the instants that have already passed"
        ),
    }


def build_evidence() -> dict[str, Any]:
    """The dated statement of what external evidence exists, and of what does not."""
    channels = channel_state()
    registration = powershell(f'schtasks /query /tn "{TASK_NAME}" /xml')
    report = task_report()
    samples = _read_jsonl(WITNESS_LOG)
    operational = channels["channels"][CHANNELS[0]]
    unavailable = (
        operational["enabled"] is False or not operational["file"]["exists"]
    )
    document: dict[str, Any] = {
        "artifact": "ST6_SCHEDULER_EVIDENCE",
        "generated_at_utc": _utc(),
        "generated_by": "scripts/st6_scheduler_witness.py",
        "task_name": TASK_NAME,
        "task_registration": {
            "queried_with": f'schtasks /query /tn "{TASK_NAME}" /xml',
            "exit_code": registration["exit_code"],
            "error": registration["error"],
            "xml_sha256": _sha256_text(registration["stdout"]),
            "xml": registration["stdout"].lstrip("\ufeff").strip()[:8000],
        },
        "scheduler_reporting_now": report,
        "channels": channels,
        "per_run_external_evidence": {
            "status": "SCHEDULER_EVIDENCE_UNAVAILABLE" if unavailable else "AVAILABLE",
            "reason": (
                f"{CHANNELS[0]} is disabled on this host and no event file exists for it, so the "
                "channel has never recorded a single run of this task; the enabled "
                f"{CHANNELS[1]} channel holds only its own maintenance events, which name no task; "
                "and the Security channel, which would carry a process-creation record if that "
                "audit subcategory were enabled and if this session could read it, is not readable "
                "here"
            ),
            "covers_runs_before_utc": None,
            "covers_runs_from_utc": None,
            "cannot_support": [
                "an absence of execution inside any slot of this period: no external source covers "
                "those hours, so a slot with no internal event is UNKNOWN, not proven unattended",
                "a distinction between a time-trigger launch and an engine launch asked for by hand: "
                "both are started by the Task Scheduler service and neither leaves an event here",
                "a per-run exit status: only the most recent result is readable, and only while it "
                "is the most recent",
            ],
            "can_support": [
                "the task's registration: it exists, it is enabled, its action is the declared "
                "interpreter and script, and it repeats every fifteen minutes",
                "the most recent run, as the scheduler itself records it, sampled as often as the "
                "witness runs",
                "a live launch, from the process table: a tick whose parent is the Task Scheduler "
                "service was launched by the schema, not by a person",
            ],
            "event_ids_that_would_carry_a_per_run_record": list(PER_RUN_EVENT_IDS),
            "event_ids_verified_against_this_installation": False,
            "event_ids_reading": (
                "the provider declares these per-run events, but this installation holds none of "
                "them: the semantics could not be verified event by event here, and no claim about "
                "any particular run is derived from an id alone"
            ),
            "correlation_rule": TASK_IDENTIFIER_READING,
        },
        "rotation_assessment": rotation_assessment(channels),
        "witness_coverage": coverage(samples),
        "witness_log": {
            "path": str(WITNESS_LOG.relative_to(REPO)).replace("\\", "/"),
            "bound": WITNESS_KEPT,
            "bound_reading": (
                "the witness log is bounded; the durable per-slot record is the slot ledger, and a "
                "sample that is pruned stops being evidence for the slot it covered"
            ),
        },
        "remediation": REMEDIATION,
        "system_time_utc": _utc(),
    }
    return document


def render_retention_audit(evidence: dict[str, Any]) -> str:
    channels = evidence["channels"]["channels"]
    status = evidence["per_run_external_evidence"]
    rows = []
    for name, entry in channels.items():
        file_state = entry["file"]
        rows.append(
            f"| `{name}` | {'enabled' if entry['enabled'] else 'disabled'} | "
            f"{'present' if file_state['exists'] else 'absent'} | "
            f"{file_state['bytes'] if file_state['bytes'] is not None else '-'} | "
            f"{file_state['last_write_utc'] or '-'} |"
        )
    samples = evidence["witness_coverage"]
    report = evidence["scheduler_reporting_now"]
    rotation = evidence["rotation_assessment"]
    lines = [
        "# ST-6 — retention of the external scheduler evidence",
        "",
        f"Generated {evidence['generated_at_utc']} by `scripts/st6_scheduler_witness.py`, read-only.",
        "",
        f"## 01 — Status: `{status['status']}`",
        "",
        status["reason"],
        "",
        "| channel | state | event file | bytes | last written |",
        "| --- | --- | --- | --- | --- |",
        *rows,
        "",
        "The Security channel, which would carry a per-run process-creation record, is "
        f"{'readable' if evidence['channels']['security_log_readable'] else 'not readable'} from this "
        f"session: {evidence['channels']['security_log_probe']}",
        "",
        "## 02 — What the loss is, exactly",
        "",
        "Per-run external evidence for this period does not exist and cannot be recovered:",
        "",
        "- the operational channel was never enabled on this host, so no run of this task has ever "
        "left an event, and a slot that already ended cannot be corroborated run by run;",
        "- the scheduler keeps only the **most recent** run instant and result for a task, so even "
        "that single field describes one run at a time;",
        "- the maintenance channel that is enabled carries only its own maintenance events;",
        "- the per-run events that would settle it are declared by the provider and listed below, "
        "but not one of them exists here to be read, so their fields and semantics could not be "
        "verified against this installation;",
        "",
        "| event id | what the provider declares it means | present on this host |",
        "| --- | --- | --- |",
        *[
            f"| {entry['id']} | {entry['meaning']} | no |"
            for entry in evidence["per_run_external_evidence"][
                "event_ids_that_would_carry_a_per_run_record"
            ]
        ],
        "",
        f"Correlation, when a record does exist: {evidence['per_run_external_evidence']['correlation_rule']}.",
        "",
        "This is recorded as a limitation of the evidence, not as evidence of absence: no slot of "
        "this period may be called *provably* unattended from these sources.",
        "",
        "## 02b — How far back the surviving record reaches",
        "",
        "Period actually covered, per channel, read from the log itself:",
        "",
        "| channel | retention | records held | oldest record number | oldest retained event | newest retained event |",
        "| --- | --- | --- | --- | --- | --- |",
        *[
            f"| `{name}` | {'archive' if entry['retention_is_archive'] else 'circular'} | "
            f"{entry['depth']['records_held'] if entry['depth']['records_held'] is not None else '-'} | "
            f"{entry['depth']['oldest_record_number'] if entry['depth']['oldest_record_number'] is not None else '-'} | "
            f"{entry['depth']['oldest_retained_event_utc'] or '-'} | "
            f"{entry['depth']['newest_retained_event_utc'] or '-'} |"
            for name, entry in channels.items()
        ],
        "",
        "## 03 — What is retained instead",
        "",
        "| retained | form | hash |",
        "| --- | --- | --- |",
        f"| the task's registration | the scheduler's own XML, verbatim | `{evidence['task_registration']['xml_sha256']}` |",
        f"| the channel states | the raw `wevtutil gl` answer per channel | "
        f"`{channels[CHANNELS[0]]['raw_document_sha256']}` |",
        f"| the scheduler's reporting | a dated sample of last run / result / missed runs | "
        f"`{report['raw_document_sha256']}` |",
        f"| the witness log | {samples['samples']} sample(s), "
        f"{samples['covered_from_utc'] or 'never'} → {samples['covered_to_utc'] or 'never'} | "
        "`data/st6/ST6_SCHEDULER_WITNESS.jsonl` |",
        "",
        f"Distinct scheduler last-run instants observed so far: "
        f"{len(samples['distinct_scheduler_last_run_instants_observed'])}; launches seen with a tick "
        f"in flight: {samples['scheduler_engine_launches_observed']}.",
        "",
        "## 04 — The one remediation, and why it is not applied here",
        "",
        f"`{REMEDIATION['command']}` — needs an administrator, changes a machine-wide audit setting, "
        f"and is **not authorised** in this work: {REMEDIATION['why_not_applied']}.",
        "",
        f"What it would give: {REMEDIATION['what_it_would_give']}",
        "",
        "Until an operator authorises it, the external evidence of this period stays what it is: "
        "point-in-time samples of the scheduler's own record, bounded by the witness's own coverage, "
        "with `SCHEDULER_EVIDENCE_UNAVAILABLE` recorded wherever a per-run record would be needed.",
        "",
        "## 05 — Rotation: the loss that has already happened elsewhere",
        "",
        f"Status: `{rotation['status']}`.",
        "",
        *(
            [
                f"- `{name}`: {entry['state']}"
                + (
                    f", {entry['records_no_longer_present_before_the_oldest']} record(s) no longer "
                    "present before the oldest one still held"
                    if entry["records_no_longer_present_before_the_oldest"]
                    else ""
                )
                + (
                    f", oldest retained event {entry['oldest_retained_event_utc']}"
                    if entry["oldest_retained_event_utc"]
                    else ""
                )
                + (
                    ", log circular and full"
                    if entry["circular"] and entry["full"]
                    else (", log circular" if entry["circular"] else "")
                )
                for name, entry in rotation["channels"].items()
            ]
            or ["- no channel examined has rotated a record away"]
        ),
        "",
        rotation["reading"],
        "",
        f"Recorded, not applied: {rotation['does_not_authorise']}.",
        "",
        "Research only: no orders, no credentials, no capital.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------------------------


def sample_once() -> dict[str, Any]:
    rows = _read_jsonl(WITNESS_LOG)
    record = take_sample(rows[-1] if rows else None)
    dropped = _append_jsonl_atomic(WITNESS_LOG, record, WITNESS_KEPT)
    return {
        "sample_id": record["sample_id"],
        "sampled_at_utc": record["sampled_at_utc"],
        "scheduler_reported_last_run_utc": record["scheduler_reported_last_run_utc"],
        "scheduler_reported_last_result": record["scheduler_reported_last_result"],
        "tick_process_count": record["tick_process_count"],
        "pruned_samples": dropped,
    }


def watch(seconds: float, interval: float) -> dict[str, Any]:
    """Sample for a bounded while: the loop stops on its own, so it cannot become a second daemon."""
    deadline = time.monotonic() + seconds
    taken: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        taken.append(sample_once())
        print(
            f"sample {taken[-1]['sampled_at_utc']} last_run={taken[-1]['scheduler_reported_last_run_utc']} "
            f"result={taken[-1]['scheduler_reported_last_result']} processes={taken[-1]['tick_process_count']}",
            flush=True,
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
    return {"samples_taken": len(taken), "from_utc": taken[0]["sampled_at_utc"] if taken else None,
            "to_utc": taken[-1]["sampled_at_utc"] if taken else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", action="store_true", help="write the evidence and retention audit")
    parser.add_argument("--once", action="store_true", help="take one sample and exit")
    parser.add_argument("--watch", type=float, default=0.0, help="sample for this many seconds")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S)
    args = parser.parse_args(argv)

    did_something = False
    if args.once:
        print(json.dumps(sample_once(), sort_keys=True))
        did_something = True
    if args.watch:
        print(json.dumps(watch(args.watch, args.interval), sort_keys=True))
        did_something = True
    if args.export or not did_something:
        evidence = build_evidence()
        _write_json_atomic(EVIDENCE_JSON, evidence)
        RETENTION_MD.write_text(render_retention_audit(evidence), encoding="utf-8")
        print(
            f"per-run external evidence: {evidence['per_run_external_evidence']['status']}; "
            f"witness samples: {evidence['witness_coverage']['samples']}; "
            f"written -> {EVIDENCE_JSON.relative_to(REPO)}, {RETENTION_MD.relative_to(REPO)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
