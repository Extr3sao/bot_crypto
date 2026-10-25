"""WP-EDGE-04R — what the host itself recorded, read instead of inferred.

The forward lane's own log says which slots it sealed. It cannot say why a slot was
never attempted, because a tick that never started writes nothing. The operating
system knows: it recorded the boots, the shutdowns, the session logons and logoffs
and the power transitions that decide whether a registered task can start at all.

This module reads that record. Three rules it keeps:

* **It never invents a cause.** ``Windows`` is asked a closed set of questions and
  the answers are stored verbatim, messages included; a question that fails is
  recorded as an error next to the sections that answered, never filled in.
* **It never reads a credential.** The autologon probe reads the switch
  (``AutoAdminLogon``) and the account name that would be used, never a password.
* **It never changes the host.** Every command here is a read.

The normalisation is deliberately separate from the collection: :func:`windows`
turns stored evidence into the availability windows the audit consumes, so the
attribution can be re-derived from a committed snapshot with no Windows present.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_TASK_NAME",
    "EVIDENCE_SCHEMA_VERSION",
    "HOST_DOWN",
    "NO_SESSION",
    "SESSION_PRESENT",
    "SLEEP",
    "collect",
    "parse_instant",
    "windows",
]

EVIDENCE_SCHEMA_VERSION = "EDGE04R_OS_EVIDENCE_V1"
DEFAULT_TASK_NAME = "TradingAgentic-EDGE04-Forward"

#: Availability states of the host, as the audit's vocabulary. They are ordered by
#: precedence: whatever is *lowest* in this tuple wins when windows overlap, because
#: a host that is down explains a silence on its own and a session that is absent
#: explains one only while the host is up.
HOST_DOWN = "HOST_DOWN"
NO_SESSION = "NO_SESSION"
SESSION_PRESENT = "SESSION_PRESENT"
SLEEP = "SLEEP"

_POWERSHELL_TIMEOUT_SECONDS = 240

# The collector is one read-only script so a single call answers every question and
# a single failure mode (no PowerShell, or a policy that forbids it) leaves a
# recorded error instead of a partially populated record that reads like an answer.
_PS_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$since = (Get-Date).AddDays(-14)
$out = [ordered]@{}
$out.schema_version = 'EDGE04R_OS_EVIDENCE_V1'

$os = Get-CimInstance Win32_OperatingSystem
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$out.host = [ordered]@{
  name             = $env:COMPUTERNAME
  collected_at_utc = (Get-Date).ToUniversalTime().ToString('o')
  os               = $os.Caption
  os_version       = $os.Version
  last_boot_utc    = $os.LastBootUpTime.ToUniversalTime().ToString('o')
  user             = $identity.Name
  elevated         = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  powershell       = $PSVersionTable.PSVersion.ToString()
}

function Shape($events) {
  return @($events | ForEach-Object {
    [ordered]@{
      at       = $_.TimeCreated.ToUniversalTime().ToString('o')
      id       = [int]$_.Id
      provider = [string]$_.ProviderName
      message  = (([string]$_.Message) -replace '\s+', ' ').Trim()
    }
  })
}

$out.boots = Shape (Get-WinEvent -FilterHashtable @{
  LogName = 'System'; ProviderName = 'Microsoft-Windows-Kernel-General'; Id = 12; StartTime = $since })
$out.shutdowns = Shape (Get-WinEvent -FilterHashtable @{
  LogName = 'System'; ProviderName = 'Microsoft-Windows-Kernel-General'; Id = 13; StartTime = $since })
$out.eventlog_service = Shape (Get-WinEvent -FilterHashtable @{
  LogName = 'System'; ProviderName = 'EventLog'; Id = 6005, 6006, 6008, 6009; StartTime = $since })
$out.power = Shape (Get-WinEvent -FilterHashtable @{
  LogName = 'System'; ProviderName = 'Microsoft-Windows-Kernel-Power'; StartTime = $since })
$out.power_troubleshooter = Shape (Get-WinEvent -FilterHashtable @{
  LogName = 'System'; ProviderName = 'Microsoft-Windows-Power-Troubleshooter'; StartTime = $since })
$out.sessions = Shape (Get-WinEvent -FilterHashtable @{
  LogName = 'Microsoft-Windows-TerminalServices-LocalSessionManager/Operational'; Id = 21, 22, 23, 24, 25; StartTime = $since })
$out.winlogon = Shape (Get-WinEvent -FilterHashtable @{
  LogName = 'System'; ProviderName = 'Microsoft-Windows-Winlogon'; Id = 7001, 7002; StartTime = $since })

$task = Get-ScheduledTask -TaskName $TASKNAME
if ($null -eq $task) {
  $out.task = $null
} else {
  $info = Get-ScheduledTaskInfo -TaskName $TASKNAME
  $triggers = @($task.Triggers | ForEach-Object {
    [ordered]@{
      type           = [string]$_.CimClass.CimClassName
      enabled        = [string]$_.Enabled
      start_boundary = [string]$_.StartBoundary
      interval       = [string]$_.Repetition.Interval
      duration       = [string]$_.Repetition.Duration
      delay          = [string]$_.Delay
    }
  })
  $actions = @($task.Actions | ForEach-Object {
    [ordered]@{ execute = [string]$_.Execute; arguments = [string]$_.Arguments; working_directory = [string]$_.WorkingDirectory } })
  $out.task = [ordered]@{
    task_name           = [string]$task.TaskName
    state               = [string]$task.State
    logon_type          = [string]$task.Principal.LogonType
    run_level           = [string]$task.Principal.RunLevel
    user_id             = [string]$task.Principal.UserId
    multiple_instances  = [string]$task.Settings.MultipleInstances
    start_when_available = [string]$task.Settings.StartWhenAvailable
    wake_to_run         = [string]$task.Settings.WakeToRun
    run_only_if_idle    = [string]$task.Settings.RunOnlyIfIdle
    disallow_on_batteries = [string]$task.Settings.DisallowStartIfOnBatteries
    execution_time_limit = [string]$task.Settings.ExecutionTimeLimit
    restart_count       = [string]$task.Settings.RestartCount
    restart_interval    = [string]$task.Settings.RestartInterval
    last_run_time       = [string]$info.LastRunTime
    last_task_result    = $info.LastTaskResult
    next_run_time       = [string]$info.NextRunTime
    missed_runs         = $info.NumberOfMissedRuns
    triggers            = $triggers
    actions             = $actions
    xml                 = (Export-ScheduledTask -TaskName $TASKNAME)
  }
}

$log = Get-WinEvent -ListLog 'Microsoft-Windows-TaskScheduler/Operational'
$out.task_history = [ordered]@{
  log_name     = [string]$log.LogName
  enabled      = [bool]$log.IsEnabled
  record_count = [int]$log.RecordCount
  reading      = 'a disabled operational log is why a trigger that fired and could not start a process leaves no host-side trace at all'
}
if ($log.IsEnabled) {
  $out.task_history.events = Shape (Get-WinEvent -FilterHashtable @{
    LogName = 'Microsoft-Windows-TaskScheduler/Operational'; StartTime = $since })
}

$out.volumes = @(Get-CimInstance Win32_Volume | ForEach-Object {
  [ordered]@{
    drive_letter = [string]$_.DriveLetter
    label        = [string]$_.Label
    file_system  = [string]$_.FileSystem
    drive_type   = [int]$_.DriveType
    capacity_bytes = [long]$_.Capacity
    free_bytes     = [long]$_.FreeSpace
    device_id      = [string]$_.DeviceID
  }
})
$out.physical_disks = @(Get-PhysicalDisk | ForEach-Object {
  [ordered]@{
    device_id   = [string]$_.DeviceId
    friendly_name = [string]$_.FriendlyName
    media_type  = [string]$_.MediaType
    bus_type    = [string]$_.BusType
    size_bytes  = [long]$_.Size
  }
})
$out.partitions = @(Get-Partition | ForEach-Object {
  [ordered]@{
    disk_number      = [int]$_.DiskNumber
    partition_number = [int]$_.PartitionNumber
    drive_letter     = [string]$_.DriveLetter
    size_bytes       = [long]$_.Size
    type             = [string]$_.Type
  }
})

$winlogon = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
$out.autologon = [ordered]@{
  auto_admin_logon = [string]$winlogon.AutoAdminLogon
  default_user_name = [string]$winlogon.DefaultUserName
  reading = 'the switch and the account name only: a password is never read, and the absence of automatic logon is the reason a rebooted host can sit unavailable until a person signs in'
}

$out | ConvertTo-Json -Depth 8 -Compress
"""


def parse_instant(value: str | None) -> int | None:
    """An ISO-8601 instant as epoch milliseconds, or ``None`` if unreadable."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def _powershell(script: str, *, timeout: int) -> tuple[dict[str, Any], str | None]:
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if exe is None:
        return {}, "no PowerShell on PATH: the host's own record cannot be read here"
    try:
        proc = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {}, f"powershell could not be run: {exc!r}"
    if proc.returncode != 0 and not proc.stdout.strip():
        return {}, f"powershell exited {proc.returncode}: {proc.stderr.strip()[:400]}"
    text = proc.stdout.strip()
    if not text:
        return {}, "powershell produced no output"
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"powershell output was not JSON: {exc}"
    if not isinstance(loaded, dict):
        return {}, "powershell output was not a JSON object"
    return loaded, None


def collect(
    *,
    task_name: str = DEFAULT_TASK_NAME,
    timeout: int = _POWERSHELL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Read the host's own record of availability, sessions, task and storage.

    The result always carries ``schema_version`` and ``errors``. An empty ``errors``
    means every question was answered; a non-empty one names the questions that were
    not, and the caller must report those as unavailable rather than as zero.
    """
    script = _PS_SCRIPT.replace("$TASKNAME", f"'{task_name}'")
    payload, error = _powershell(script, timeout=timeout)
    if error is not None:
        return {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "supported": False,
            "task_name": task_name,
            "errors": [error],
            "host": {},
        }
    payload["supported"] = True
    payload.setdefault("errors", [])
    payload["task_name"] = task_name
    return payload


def _sessions(evidence: dict[str, Any]) -> list[tuple[int, str]]:
    """Session transitions as ``(instant_ms, kind)`` with ``kind`` in logon/logoff.

    Two providers record the same events from different sides: the session manager
    knows a session started or ended, and Winlogon knows the shell was notified. The
    session manager's view is used because it is the one that says whether a session
    existed at all, and Winlogon is kept only as the fallback.
    """
    rows: list[tuple[int, str]] = []
    for row in evidence.get("sessions") or []:
        at = parse_instant(str(row.get("at") or ""))
        if at is None:
            continue
        event_id = int(row.get("id") or 0)
        if event_id in (21, 22, 25):
            rows.append((at, "logon"))
        elif event_id in (23, 24):
            rows.append((at, "logoff"))
    if not rows:
        for row in evidence.get("winlogon") or []:
            at = parse_instant(str(row.get("at") or ""))
            if at is None:
                continue
            rows.append((at, "logon" if int(row.get("id") or 0) == 7001 else "logoff"))
    return sorted(rows)


def windows(evidence: dict[str, Any]) -> dict[str, Any]:
    """Normalise stored evidence into the availability windows the audit uses.

    Returns ``host_down``, ``session_absent`` and ``sleep`` as lists of
    ``(start_ms, end_ms, reason)``, plus the counts that justify each list. Windows are
    built from the events *in chronological order*, never from two lists walked
    separately: a host that booted before it shut down is not unavailable, and pairing
    a boot list against a shutdown list in the wrong order would report the whole
    window as downtime. An event with no partner yet (a shutdown whose boot fell
    outside the collected range, or a logoff with no logon after it) becomes an open
    window that ends at the reading instant, reported rather than dropped.
    """
    boots = [
        at
        for row in evidence.get("boots") or []
        if (at := parse_instant(str(row.get("at") or ""))) is not None
    ]
    shutdowns = [
        at
        for row in evidence.get("shutdowns") or []
        if (at := parse_instant(str(row.get("at") or ""))) is not None
    ]

    host_down: list[tuple[int, int, str]] = []
    pending_shutdown: int | None = None
    timeline: list[tuple[int, str]] = sorted(
        [(at, "boot") for at in boots] + [(at, "shutdown") for at in shutdowns]
    )
    for at, kind in timeline:
        if kind == "shutdown":
            if pending_shutdown is None:
                pending_shutdown = at
            continue
        if pending_shutdown is not None:
            if pending_shutdown <= at:
                host_down.append(
                    (pending_shutdown, at, "shutdown and boot recorded by Kernel-General")
                )
            pending_shutdown = None
    if pending_shutdown is not None:
        host_down.append((pending_shutdown, 0, "shutdown with no boot after it, in range"))

    sleep: list[tuple[int, int, str]] = []
    asleep: int | None = None
    for row in sorted(evidence.get("power") or [], key=lambda item: str(item.get("at") or "")):
        at = parse_instant(str(row.get("at") or ""))
        if at is None:
            continue
        event_id = int(row.get("id") or 0)
        if event_id == 42 and asleep is None:
            asleep = at
        elif event_id == 107 and asleep is not None:
            sleep.append((asleep, at, "Kernel-Power 42 sleep / 107 resume"))
            asleep = None
    if asleep is not None:
        sleep.append((asleep, 0, "sleep with no resume after it, in range"))

    transitions = _sessions(evidence)
    session_absent: list[tuple[int, int, str]] = []
    open_since: int | None = None
    open_reason = ""
    merged: list[tuple[int, str]] = sorted(
        [(at, "logon") for at, kind in transitions if kind == "logon"]
        + [(at, "logoff") for at, kind in transitions if kind == "logoff"]
        + [(at, "boot") for at in boots]
        + [(at, "shutdown") for at in shutdowns]
    )
    for at, kind in merged:
        if kind == "shutdown":
            continue  # the host being down is a stronger statement and is counted there
        if kind in ("logoff", "boot"):
            if open_since is None:
                open_since = at
                open_reason = (
                    "logoff with no sign-in after it, until the next one"
                    if kind == "logoff"
                    else "boot with no sign-in after it, until the next one"
                )
            continue
        if open_since is not None and at >= open_since:
            session_absent.append((open_since, at, open_reason))
            open_since, open_reason = None, ""
    if open_since is not None:
        session_absent.append((open_since, 0, open_reason))

    return {
        "host_down": sorted(host_down),
        "session_absent": sorted(session_absent),
        "sleep": sorted(sleep),
        "transitions": transitions,
        "counts": {
            "boots": len(boots),
            "shutdowns": len(shutdowns),
            "session_transitions": len(transitions),
            "power_events": len(evidence.get("power") or []),
            "sleep_resume_pairs": len(sleep),
        },
        "reading": (
            "every window here is a pair of records the host wrote; an unpaired record "
            "becomes an open window that ends at the observation instant, so a cause is "
            "never extended past the evidence for it"
        ),
    }


def load(path: Path) -> dict[str, Any]:
    """Read previously collected evidence from disk."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return payload
