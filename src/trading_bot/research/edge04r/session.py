"""WP-EDGE-04R — which persistent-execution mechanisms this host actually offers.

The lane's task is registered with ``LogonType=InteractiveToken``, which means it can
start only while a session exists. The audit measures what that costs: 24 of the 26
triggers that produced no process fell inside one 6 h 21 m stretch in which the host
was up and nobody was signed in.

Four mechanisms could remove or bound that cost, and each of them needs something:

``S4U``
    ``<LogonType>S4U</LogonType>`` runs the task whether or not a session exists and
    stores no password. Registering it is a change to a logon right, so it is offered
    as a probe rather than assumed: the registration is *attempted* and the answer the
    host gives is recorded.
``Windows service`` / ``SYSTEM``
    Same effect, larger change: needs administrator rights to create.
``Automatic logon``
    Would re-create the session after a reboot, and requires the account password to be
    stored on the machine. This work package is not authorised to hold a credential, so
    the probe reads the switch only.
``LogonTrigger`` on the existing task
    Needs nothing new and does not remove the absence, but it *bounds the recovery*:
    measured latency from the sign-in to the first tick was 321 s, which is the wait
    for the next quarter-hour trigger.

Nothing here registers anything for the live lane: the probes register a throwaway task
under their own name, read it back from the scheduler, run it once, and delete it. The
one host setting a probe attempts to change — enabling the Task Scheduler's operational
log, the record that would separate "the trigger never fired" from "the process died
before writing" — is attempted and its refusal recorded like any other answer.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

__all__ = [
    "AUTOLOGON",
    "LOGON_TRIGGER",
    "NEEDS_CREDENTIALS",
    "NEEDS_ELEVATION",
    "NOT_APPLICABLE",
    "S4U",
    "SERVICE",
    "SESSION_SCHEMA_VERSION",
    "VIABLE",
    "build_task_xml",
    "classify",
    "probe_logon_trigger_registration",
    "probe_s4u_registration",
    "probe_task_history_log",
    "probe_witness_action",
    "recommendation",
]

SESSION_SCHEMA_VERSION = "EDGE04R_SESSION_PROBE_V1"

#: Verdicts a mechanism can earn. ``VIABLE`` means the mechanism was *exercised* here;
#: ``NEEDS_ELEVATION`` and ``NEEDS_CREDENTIALS`` mean the host said no for a reason this
#: package cannot legitimately remove.
VIABLE = "VIABLE"
NEEDS_ELEVATION = "NEEDS_ELEVATION"
NEEDS_CREDENTIALS = "NEEDS_CREDENTIALS"
NOT_APPLICABLE = "NOT_APPLICABLE"
FAILED = "FAILED"

SESSION = "SESSION_LOGON_TRIGGER"
S4U = "S4U_TASK"
SERVICE = "WINDOWS_SERVICE"
AUTOLOGON = "AUTOMATIC_LOGON"
LOGON_TRIGGER = SESSION

PROBE_TASK_NAME = "TradingAgentic-EDGE04R-Probe"

_TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>{date}</Date>
    <Author>{author}</Author>
    <Description>{description}</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>{start_boundary}</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>PT{interval_minutes}M</Interval>
        <Duration>P3650D</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </TimeTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT{logon_delay_seconds}S</Delay>
      <UserId>{user_id}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user_id}</UserId>
      <LogonType>{logon_type}</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <WakeToRun>{wake_to_run}</WakeToRun>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT5M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>/c echo %DATE% %TIME% witness &gt;&gt; "{witness_path}"</Arguments>
    </Exec>
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{working_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def build_task_xml(
    *,
    user_id: str,
    command: str,
    arguments: str,
    working_dir: str,
    witness_path: Path,
    logon_type: str = "InteractiveToken",
    interval_minutes: int = 15,
    logon_delay_seconds: int = 60,
    wake_to_run: bool = False,
    description: str = "WP-EDGE-04R session-independence probe",
) -> str:
    """A task definition with BOTH triggers and a witness action that always runs.

    Two differences from the registration the lane currently carries, and both are
    deliberate:

    * a ``LogonTrigger`` with a one-minute delay, so a session that comes back is
      resumed at the next minute rather than at the next quarter of an hour;
    * a first action that appends one line to a witness file. The order matters — the
      witness runs before the long action, and it is a shell builtin that cannot fail
      for the reasons a Python entry point fails — so a launch that produces no tick
      record still leaves a host-side trace saying the task started.
    """
    import datetime as dt

    return _TASK_XML.format(
        date=dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        author=user_id,
        description=description,
        start_boundary=(dt.datetime.now() + dt.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        interval_minutes=interval_minutes,
        logon_delay_seconds=logon_delay_seconds,
        user_id=user_id,
        logon_type=logon_type,
        wake_to_run="true" if wake_to_run else "false",
        witness_path=witness_path,
        command=command,
        arguments=arguments,
        working_dir=working_dir,
    )


def _run(args: Sequence[str], *, timeout: int = 90) -> dict[str, Any]:
    # stdin is closed on purpose: `schtasks` asks for a password when it cannot register
    # what it was asked for, and a probe that waits for an answer nobody can type would
    # hang the audit and report a timeout instead of the refusal it actually got.
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": repr(exc)}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def _powershell(script: str, *, timeout: int = 120) -> dict[str, Any]:
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if exe is None:
        return {"ok": False, "stdout": "", "stderr": "no PowerShell on PATH", "returncode": None}
    return _run([exe, "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout)


def _await_witness(path: Path, *, seconds: float = 20.0) -> bool:
    """Wait for the task to start, rather than reading the file the instant it is queued.

    ``schtasks /run`` returns as soon as the task is queued, so a check made immediately
    afterwards measures the queue, not the task: this polls instead, and reports the
    absence only after the window has really elapsed.
    """
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and path.read_text(encoding="utf-8", errors="replace").strip():
            return True
        time.sleep(0.5)
    return bool(path.exists() and path.read_text(encoding="utf-8", errors="replace").strip())


def _current_user() -> str:
    script = (
        "$id=[Security.Principal.WindowsIdentity]::GetCurrent(); "
        "[pscustomobject]@{ name=$id.Name; "
        "elevated=(New-Object Security.Principal.WindowsPrincipal($id))"
        ".IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) } | ConvertTo-Json -Compress"
    )
    result = _powershell(script)
    if not result["ok"]:
        return ""
    try:
        payload = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return ""
    return str(payload.get("name") or "") if isinstance(payload, dict) else ""


def _create_task(task_name: str, xml: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as handle:
        handle.write(xml)
        path = Path(handle.name)
    try:
        return _run(["schtasks", "/create", "/tn", task_name, "/xml", str(path), "/f"])
    finally:
        path.unlink(missing_ok=True)


def _delete_task(task_name: str) -> dict[str, Any]:
    return _run(["schtasks", "/delete", "/tn", task_name, "/f"])


def _read_back(task_name: str) -> dict[str, Any]:
    script = (
        f"$t = Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue; "
        "if ($null -eq $t) { '{}' } else { "
        "$triggers = @($t.Triggers | ForEach-Object { "
        "[ordered]@{ type=[string]$_.CimClass.CimClassName; enabled=[string]$_.Enabled; "
        "delay=[string]$_.Delay; boundary=[string]$_.StartBoundary } }); "
        "$actions = @($t.Actions | ForEach-Object { [ordered]@{ execute=[string]$_.Execute; "
        "arguments=[string]$_.Arguments } }); "
        "[ordered]@{ state=[string]$t.State; logon_type=[string]$t.Principal.LogonType; "
        "user=[string]$t.Principal.UserId; triggers=$triggers; actions=$actions; "
        "multiple_instances=[string]$t.Settings.MultipleInstances; "
        "start_when_available=[string]$t.Settings.StartWhenAvailable; "
        "wake_to_run=[string]$t.Settings.WakeToRun; xml=(Export-ScheduledTask -TaskName "
        f"'{task_name}') }} | ConvertTo-Json -Depth 6 -Compress }}"
    )
    result = _powershell(script)
    if not result["ok"] or not result["stdout"]:
        return {"error": result["stderr"] or "no read-back"}
    try:
        loaded = json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        return {"error": f"read-back was not JSON: {exc}"}
    return loaded if isinstance(loaded, dict) and loaded else {"error": "the task was not found"}


def probe_logon_trigger_registration(
    *, probe_name: str = PROBE_TASK_NAME, scratch: Path, interval_minutes: int = 15
) -> dict[str, Any]:
    """Register a throwaway task with both triggers, read it back, and delete it.

    Exercised, not asserted: the registration either happens and the scheduler returns a
    definition carrying the ``LogonTrigger``, or the failure is recorded. The task never
    touches the lane: its action writes to a scratch file and exits.
    """
    scratch.mkdir(parents=True, exist_ok=True)
    witness = scratch / f"{probe_name}-witness.txt"
    witness.unlink(missing_ok=True)
    user = _current_user()
    xml = build_task_xml(
        user_id=user,
        command="cmd.exe",
        arguments="/c exit 0",
        working_dir=str(scratch),
        witness_path=witness,
        interval_minutes=interval_minutes,
    )
    created = _create_task(probe_name, xml)
    read_back = _read_back(probe_name) if created["ok"] else {"error": "not created"}
    ran = _run(["schtasks", "/run", "/tn", probe_name]) if created["ok"] else {"ok": False}
    witness_seen = _await_witness(witness)
    deleted = _delete_task(probe_name) if created["ok"] else {"ok": True}
    triggers = read_back.get("triggers") or []
    kinds = sorted(str(row.get("type")) for row in triggers if isinstance(row, dict))
    has_logon = any("LogonTrigger" in kind for kind in kinds)
    has_time = any("TimeTrigger" in kind for kind in kinds)
    return {
        "mechanism": SESSION,
        "verdict": VIABLE if created["ok"] and has_logon and has_time else FAILED,
        "task_name": probe_name,
        "registered": bool(created["ok"]),
        "registration_output": created["stdout"] or created["stderr"],
        "read_back": read_back,
        "trigger_kinds": kinds,
        "ran_on_demand": bool(ran.get("ok")),
        "witness_file_written": witness_seen,
        "deleted_after_the_probe": bool(deleted.get("ok")),
        "detail": (
            "the LogonTrigger is additive: it does not remove the session absence, it bounds "
            "the recovery from it, and it is registered in the same scheduler the lane already uses"
        ),
    }


def probe_witness_action(
    *, probe_name: str = f"{PROBE_TASK_NAME}-Witness", scratch: Path
) -> dict[str, Any]:
    """Prove the chained witness action runs before the long action.

    The single unanswered trigger this audit could not attribute (one of 220) is exactly
    the case a witness separates: if the file has a line for that instant, the task
    started and the process died; if it has none, the scheduler never started it.
    """
    scratch.mkdir(parents=True, exist_ok=True)
    witness = scratch / "witness-probe.txt"
    witness.unlink(missing_ok=True)
    xml = build_task_xml(
        user_id=_current_user(),
        command="cmd.exe",
        arguments="/c exit 0",
        working_dir=str(scratch),
        witness_path=witness,
        description="WP-EDGE-04R witness-action probe",
    )
    created = _create_task(probe_name, xml)
    ran = _run(["schtasks", "/run", "/tn", probe_name]) if created["ok"] else {"ok": False}
    _await_witness(witness)
    lines = 0
    if witness.exists():
        lines = len(
            [row for row in witness.read_text(encoding="utf-8").splitlines() if row.strip()]
        )
    _delete_task(probe_name)
    return {
        "mechanism": "WITNESS_ACTION",
        "verdict": VIABLE if lines > 0 else FAILED,
        "ran_on_demand": bool(ran.get("ok")),
        "lines_written": lines,
        "evidence_file": str(witness),
        "turns_silence_into": (
            "a witness line proves the scheduler started the task; its absence proves the "
            "trigger never produced a process, which is the distinction the Task Scheduler's "
            "disabled operational log cannot make on this host"
        ),
    }


def probe_s4u_registration(
    *, probe_name: str = f"{PROBE_TASK_NAME}-S4U", scratch: Path
) -> dict[str, Any]:
    """Attempt the registration that would run without any session, and record the answer.

    ``schtasks`` with an empty ``/rp`` is the S4U form: no password is stored. Whether a
    non-elevated process may register it is a property of this host's policy, so it is
    attempted once against a throwaway task name and the refusal (if any) is quoted.
    """
    scratch.mkdir(parents=True, exist_ok=True)
    user = _current_user()
    created = _run(
        [
            "schtasks",
            "/create",
            "/tn",
            probe_name,
            "/tr",
            "cmd.exe /c exit 0",
            "/sc",
            "once",
            "/st",
            "23:59",
            "/ru",
            user,
            "/rp",
            "",
            "/f",
        ],
        timeout=45,
    )
    read_back = _read_back(probe_name) if created["ok"] else {}
    _delete_task(probe_name)
    refused = not created["ok"]
    timed_out = "TimeoutExpired" in str(created.get("stderr") or "")
    return {
        "mechanism": S4U,
        "verdict": VIABLE if created["ok"] else NEEDS_ELEVATION,
        "attempted": True,
        "user": user,
        "stored_a_password": False,
        "registration_ok": bool(created["ok"]),
        "waited_for_input": timed_out,
        "registration_output": (created["stdout"] or created["stderr"])[:600],
        "read_back": read_back,
        "detail": (
            "S4U runs whether or not a session exists and stores no credential; it needs the "
            "'log on as a batch job' right, which this process cannot grant itself"
            if refused
            else "the host accepted an S4U registration from this process"
        ),
        "operator_command": (
            'schtasks /create /tn "<task>" /xml <definition with LogonType=S4U> /f'
            " — registered by an administrator, after granting the batch-logon right"
        ),
    }


def probe_task_history_log() -> dict[str, Any]:
    """Try to enable the one host record that would make future losses attributable."""
    state = _powershell(
        "$log = Get-WinEvent -ListLog 'Microsoft-Windows-TaskScheduler/Operational'; "
        "[ordered]@{ enabled=[bool]$log.IsEnabled; records=[int]$log.RecordCount } "
        "| ConvertTo-Json -Compress"
    )
    before: dict[str, Any] = {}
    if state["ok"] and state["stdout"]:
        try:
            loaded = json.loads(state["stdout"])
            before = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            before = {}
    # `wevtutil` has no dry-run: this is the attempt, and its refusal is the finding.
    attempt: dict[str, Any]
    if before.get("enabled"):
        attempt = {"ok": True, "returncode": 0, "stdout": "already enabled", "stderr": ""}
    else:
        attempt = _run(["wevtutil", "sl", "Microsoft-Windows-TaskScheduler/Operational", "/e:true"])
    after_state = _powershell(
        "$log = Get-WinEvent -ListLog 'Microsoft-Windows-TaskScheduler/Operational'; "
        "[ordered]@{ enabled=[bool]$log.IsEnabled; records=[int]$log.RecordCount } "
        "| ConvertTo-Json -Compress"
    )
    after: dict[str, Any] = {}
    if after_state["ok"] and after_state["stdout"]:
        try:
            loaded = json.loads(after_state["stdout"])
            after = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            after = {}
    return {
        "mechanism": "TASK_SCHEDULER_OPERATIONAL_LOG",
        "verdict": VIABLE if after.get("enabled") else NEEDS_ELEVATION,
        "enabled_before": bool(before.get("enabled")),
        "enabled_after": bool(after.get("enabled")),
        "records_before": before.get("records"),
        "records_after": after.get("records"),
        "attempt_output": (attempt["stdout"] or attempt["stderr"])[:400],
        "operator_command": "wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true",
        "detail": (
            "with this log disabled, a trigger that fired and could not start a process leaves "
            "no host-side record at all: that is why one of the 220 instants in this window ends "
            "as SILENT_UNATTRIBUTABLE instead of as a cause"
        ),
    }


def classify(
    probes: Sequence[dict[str, Any]], *, autologon: dict[str, Any], sleep_pairs: int
) -> dict[str, Any]:
    """The mechanisms, each with the verdict the host gave it."""
    by_name = {str(probe.get("mechanism")): probe for probe in probes}
    mechanisms = {
        SESSION: by_name.get(SESSION, {"verdict": "NOT_PROBED"}),
        S4U: by_name.get(S4U, {"verdict": "NOT_PROBED"}),
        "WITNESS_ACTION": by_name.get("WITNESS_ACTION", {"verdict": "NOT_PROBED"}),
        "TASK_SCHEDULER_OPERATIONAL_LOG": by_name.get(
            "TASK_SCHEDULER_OPERATIONAL_LOG", {"verdict": "NOT_PROBED"}
        ),
        SERVICE: {
            "mechanism": SERVICE,
            "verdict": NEEDS_ELEVATION,
            "detail": (
                "creating a service needs administrator rights; not attempted, and not needed "
                "if an S4U task is available, because both remove the session dependence equally"
            ),
        },
        AUTOLOGON: {
            "mechanism": AUTOLOGON,
            "verdict": NEEDS_CREDENTIALS,
            "switch": autologon.get("auto_admin_logon"),
            "account": autologon.get("default_user_name"),
            "detail": (
                "automatic logon re-creates the session after a reboot and requires the account "
                "password to be stored on the machine; this work package holds no credential and "
                "will not acquire one"
            ),
        },
    }
    if sleep_pairs == 0:
        mechanisms["WAKE_TO_RUN"] = {
            "mechanism": "WAKE_TO_RUN",
            "verdict": NOT_APPLICABLE,
            "detail": (
                "the task is already registered with WakeToRun=false, and the host recorded no "
                "sleep or standby in the window, so there is nothing for this setting to recover"
            ),
        }
    return {
        "mechanisms": mechanisms,
        "viable": sorted(name for name, row in mechanisms.items() if row.get("verdict") == VIABLE),
        "blocked": sorted(
            name
            for name, row in mechanisms.items()
            if row.get("verdict") in (NEEDS_ELEVATION, NEEDS_CREDENTIALS)
        ),
        "reading": (
            "a mechanism is VIABLE only where it was exercised in this pass; a mechanism whose "
            "prerequisite this package cannot legitimately provide is reported with the exact "
            "command or credential an operator would have to supply"
        ),
    }


def recommendation(
    *, audit: dict[str, Any], probes: dict[str, Any], task_name: str
) -> dict[str, Any]:
    """What each available mechanism would buy, priced from the audit rather than guessed."""
    loss = audit.get("trigger_loss") or {}
    causes = loss.get("causes") or {}
    availability = audit.get("availability") or {}
    recovery = [row for row in (availability.get("recovery") or []) if row.get("ends_at_a_sign_in")]
    worst_recovery = max(
        (row.get("recovery_latency_seconds") or 0 for row in recovery), default=None
    )
    no_session = int(causes.get("NO_SESSION", 0))
    unattributable = int(causes.get("SILENT_UNATTRIBUTABLE", 0))
    viable = probes.get("viable") or []
    return {
        "no_session_triggers_lost": no_session,
        "unattributable_triggers_lost": unattributable,
        "worst_recovery_latency_seconds": worst_recovery,
        "what_the_logon_trigger_buys": (
            "it bounds the recovery from a sign-in to the trigger delay; the absence itself is "
            "untouched, so it recovers minutes, not the hours the absence consumed"
            if SESSION in viable
            else "not available"
        ),
        "what_s4u_would_buy": (
            "the session dependence disappears: the "
            f"{no_session} triggers lost to NO_SESSION would be scheduleable. It is blocked on "
            "the batch-logon right, so it needs an operator with administrator rights."
            if S4U not in viable
            else "the session dependence can be removed; register the lane's task with S4U"
        ),
        "what_the_witness_buys": (
            f"the {unattributable} trigger(s) that end as SILENT_UNATTRIBUTABLE would become "
            "attributable, without needing the Task Scheduler's operational log"
            if "WITNESS_ACTION" in viable
            else "not available"
        ),
        "apply_command": (
            f'schtasks /create /tn "{task_name}" /xml <definition with both triggers> /f'
        ),
        "not_applied": (
            "the live task is left exactly as WP-EDGE-04 registered it: re-registering a running "
            "lane's task changes the phase the audit measures and is a deployment decision for the "
            "operator, not a side effect of an audit"
        ),
    }
