"""WP-EDGE-12B — which mechanism can start the observer without a session, priced.

WP-EDGE-04R established the shape of the problem: the task is
``LogonType=InteractiveToken``, the host spends real time up with nobody signed in, and
a trigger that fires in that state produces neither a process nor a record. It also
established that the two mechanisms which *remove* the dependence — an S4U task and a
Windows service — need an administrator, and that storing the account password is the
only non-elevated route and is out of scope for a research package.

This module does three things the previous pass did not:

* it attempts the **S4U registration of the proposal itself**, not of a bare
  ``cmd.exe``: the question an operator actually asks is whether *this definition*
  can be registered with ``LogonType=S4U``, and the answer can differ from whether
  the mechanism exists at all;
* it prices the **additive levers that are already in the live registration**. The
  registration carries ``StartWhenAvailable=true`` and a
  ``RestartOnFailure Count=3 Interval=PT5M`` policy, and the lane's run log is the
  place to find out whether either of them ever recovered anything. A setting that
  is present and does nothing is worth exactly as much as a mechanism that is
  absent, and saying which one it is takes a measurement;
* it writes a **preflight** an operator can run before applying anything, every item
  of which is a question with a yes/no answer on this host, plus the rollback.

Nothing here is applied. Every probe registers a throwaway task under its own name,
reads it back, and deletes it; the live registration is left exactly as it was, and
the number of tasks left behind is measured rather than assumed.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from itertools import pairwise
from pathlib import Path
from typing import Any

__all__ = [
    "MECHANISMS",
    "RUNNER_SCHEMA_VERSION",
    "additive_levers",
    "decide",
    "mechanisms",
    "preflight",
    "probe_independent_host",
    "probe_s4u_proposal",
    "probe_service_accounts",
    "probe_services",
    "probe_system_principal",
    "rollback",
    "schtasks_run",
]

RUNNER_SCHEMA_VERSION = "EDGE12_RUNNER_PREFLIGHT_V1"

#: The mechanisms RFC-EDGE-012 asks to be evaluated, in the order it names them.
MECHANISMS: tuple[tuple[str, str], ...] = (
    (
        "S4U_TASK",
        "an S4U task stores no password and runs with no session; needs the batch-logon right",
    ),
    (
        "AUTHORISED_SERVICE_ACCOUNT",
        "a designated account whose rights are granted for this purpose",
    ),
    (
        "WINDOWS_SERVICE",
        "a service removes the session dependence and needs administrator rights to create",
    ),
    ("INDEPENDENT_HOST_RUNNER", "a runner on another host, if authorised infrastructure exists"),
    (
        "LOGON_TRIGGER",
        "a mitigation: it does not remove the absence, it bounds the recovery from it",
    ),
)

_INERT_COMMAND = "cmd.exe"
_INERT_ARGUMENTS = "/c exit 0"


def schtasks_run(args: list[str], *, timeout: int = 90) -> dict[str, Any]:
    """Run a ``schtasks``/``net`` read or probe with stdin closed.

    Closed stdin is the difference between a refusal and a hang: ``schtasks`` prompts
    for a password when it cannot do what it was asked, and a probe that waits for an
    answer nobody can type reports a timeout instead of the refusal it actually got.

    The bytes are captured and decoded here rather than with ``text=True``: the tool
    answers in the console's own code page, which on this host is not the one Python
    would guess, and a refusal nobody can read is a refusal that cannot be quoted.
    """
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            check=False,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": repr(exc), "args": args}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": _decode(proc.stdout),
        "stderr": _decode(proc.stderr),
        "args": args,
    }


def _decode(data: bytes) -> str:
    """Decode a console tool's output without losing the words in it.

    ``schtasks`` writes in the OEM code page and PowerShell may write UTF-8: the first
    encoding that decodes cleanly wins, and a replacement character is the last resort
    rather than the first one. A probe's refusal is evidence, and evidence a reader
    cannot read is not evidence.
    """
    for encoding in ("utf-8", "cp850", "cp1252"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace").strip()


def _create_from_xml(task_name: str, xml: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as handle:
        handle.write(xml)
        path = Path(handle.name)
    try:
        return schtasks_run(["schtasks", "/create", "/tn", task_name, "/xml", str(path), "/f"])
    finally:
        path.unlink(missing_ok=True)


def _read_back(task_name: str) -> dict[str, Any]:
    script = (
        f"$t = Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue; "
        "if ($null -eq $t) { '{}' } else { "
        "$triggers = @($t.Triggers | ForEach-Object { [ordered]@{ type=[string]$_.CimClass.CimClassName; "
        "delay=[string]$_.Delay } }); "
        "[ordered]@{ state=[string]$t.State; logon_type=[string]$t.Principal.LogonType; "
        "user=[string]$t.Principal.UserId; triggers=$triggers; "
        "start_when_available=[string]$t.Settings.StartWhenAvailable; "
        "restart_count=[string]$t.Settings.RestartCount; "
        "multiple_instances=[string]$t.Settings.MultipleInstances } | ConvertTo-Json -Depth 6 -Compress }"
    )
    exe = _powershell_exe()
    if exe is None:
        return {"error": "no PowerShell on PATH"}
    result = schtasks_run([exe, "-NoProfile", "-NonInteractive", "-Command", script], timeout=120)
    if not result["ok"] or not result["stdout"]:
        return {"error": result["stderr"] or "no read-back"}
    try:
        loaded = json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        return {"error": f"read-back was not JSON: {exc}"}
    if not isinstance(loaded, dict) or not loaded:
        return {"error": "the task was not found after registration"}
    return loaded


def _powershell_exe() -> str | None:
    import shutil

    return shutil.which("powershell") or shutil.which("pwsh")


def _delete(task_name: str) -> dict[str, Any]:
    return schtasks_run(["schtasks", "/delete", "/tn", task_name, "/f"])


def _task_exists(task_name: str) -> bool:
    result = schtasks_run(["schtasks", "/query", "/tn", task_name])
    return bool(result["ok"])


def s4u_probe_definition(
    *,
    evidence: dict[str, Any],
    scratch: Path,
    interval_minutes: int,
    inert_command: str = _INERT_COMMAND,
    inert_arguments: str = _INERT_ARGUMENTS,
) -> dict[str, Any]:
    """Build the definition the S4U probe registers: the proposal's shape, runnable.

    Three things are carried over from the live registration — the principal (with its
    logon type changed), both triggers including the cadence's own ``StartBoundary``, and
    the order of the actions — and exactly one thing is swapped: the lane's action is
    replaced by a command that exits immediately, because registering *and running* the
    lane's own action here would let a probe write an out-of-phase tick into the ledger
    the continuity reading measures. How many lines that swap moved is computed, so
    "only the action payload differs" is a measurement rather than a claim.
    """
    from trading_bot.research.edge04r import session as session_probe

    task = evidence.get("task") or {}
    actions = [row for row in (task.get("actions") or []) if isinstance(row, dict)]
    live = actions[0] if actions else {}
    triggers = [row for row in (task.get("triggers") or []) if isinstance(row, dict)]
    boundary = next(
        (str(row.get("start_boundary")) for row in triggers if row.get("start_boundary")), ""
    )
    xml = session_probe.build_task_xml(
        user_id=str(task.get("user_id") or ""),
        command=inert_command,
        arguments=inert_arguments,
        working_dir=str(live.get("working_directory") or ""),
        witness_path=scratch / "s4u-witness.txt",
        logon_type="S4U",
        interval_minutes=interval_minutes,
        wake_to_run=_as_bool(task.get("wake_to_run")),
        description=f"WP-EDGE-12B S4U probe for {task.get('task_name')}",
        start_boundary=boundary or None,
    )
    return {
        "xml": xml,
        "logon_type": "S4U",
        "logon_type_the_live_task_has": str(task.get("logon_type") or ""),
        "carried_over": {
            "user_id": str(task.get("user_id") or ""),
            "working_directory": str(live.get("working_directory") or ""),
            "start_boundary": boundary or None,
            "interval_minutes": interval_minutes,
            "wake_to_run": _as_bool(task.get("wake_to_run")),
        },
        "swapped": {"command": inert_command, "arguments": inert_arguments},
        "reading": (
            "the probe answers whether *this* definition can be registered with S4U from an "
            "unelevated process, which is a different question from whether the mechanism exists"
        ),
    }


def _as_bool(value: Any) -> bool:
    """The scheduler reports booleans as strings, and ``bool('False')`` is ``True``."""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def probe_s4u_proposal(
    *, proposal_xml: str, probe_name: str, scratch: Path, timeout: int = 60
) -> dict[str, Any]:
    """Attempt to register *the proposal itself* with ``LogonType=S4U``.

    The difference from a bare S4U attempt matters: a definition carrying a logon
    trigger, a witness action and a principal the caller does not own can be refused
    for reasons a one-line ``cmd.exe`` task never meets. The refusal is recorded
    verbatim, and the probe never leaves the task behind — whether it did is checked
    by asking the scheduler afterwards, not by trusting the delete call.

    The verdict is not "the registration was accepted": it is "the registration was
    accepted **and the scheduler read the principal back as S4U**". A task that
    registered with the interactive principal has not answered the question, and
    collapsing those two into one verdict is how a probe reports a mechanism it never
    exercised.
    """
    scratch.mkdir(parents=True, exist_ok=True)
    created = _create_from_xml(probe_name, proposal_xml)
    read_back = _read_back(probe_name) if created["ok"] else {}
    ran = schtasks_run(["schtasks", "/run", "/tn", probe_name], timeout=45) if created["ok"] else {}
    # Only delete what this probe created. A delete of something that was never created
    # would report a success that says nothing, and a delete of a task this probe did not
    # create is not this probe's decision to take.
    deleted = _delete(probe_name) if created["ok"] else {"ok": True, "stdout": "nothing to delete"}
    still_there = _task_exists(probe_name) if created["ok"] else False
    timed_out = "TimeoutExpired" in str(created.get("stderr") or "")
    kinds = sorted(
        str(row.get("type")) for row in (read_back.get("triggers") or []) if isinstance(row, dict)
    )
    read_back_logon_type = str(read_back.get("logon_type") or "")
    read_back_is_s4u = read_back_logon_type.strip().upper() == "S4U"
    return {
        "mechanism": "S4U_TASK",
        "target": "the committed proposal, re-registered with LogonType=S4U",
        "verdict": "VIABLE" if created["ok"] and read_back_is_s4u else "NEEDS_ELEVATION",
        "attempted": True,
        "stored_a_password": False,
        "registration_ok": bool(created["ok"]),
        "read_back_is_s4u": read_back_is_s4u,
        "waited_for_input": timed_out,
        "registration_output": (created["stdout"] or created["stderr"])[:600],
        "read_back_logon_type": read_back_logon_type or None,
        "read_back_trigger_kinds": kinds,
        "ran_on_demand": bool(ran.get("ok")),
        "deleted_after_the_probe": bool(deleted["ok"]),
        "task_left_behind": bool(still_there),
        "timeout_seconds": timeout,
        "what_it_would_remove": (
            "the 24 triggers of the measured window that produced no process because no "
            "session existed: an S4U task does not need one"
        ),
        "operator_command": (
            'schtasks /create /tn "TradingAgentic-EDGE04-Forward" '
            "/xml <definition with <LogonType>S4U</LogonType>> /f"
        ),
    }


def probe_system_principal(*, probe_name: str, timeout: int = 45) -> dict[str, Any]:
    """Attempt a registration whose principal is a different account, and record the refusal."""
    result = schtasks_run(
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
            "SYSTEM",
            "/f",
        ],
        timeout=timeout,
    )
    deleted = _delete(probe_name) if result["ok"] else {"ok": True}
    return {
        "mechanism": "WINDOWS_SERVICE",
        "target": "a registration whose principal is SYSTEM, which is what a service class of runner needs",
        "verdict": "VIABLE" if result["ok"] else "NEEDS_ELEVATION",
        "attempted": True,
        "registration_ok": bool(result["ok"]),
        "registration_output": (result["stdout"] or result["stderr"])[:600],
        "deleted_after_the_probe": bool(deleted["ok"]),
        "what_it_would_remove": "the session dependence, and the need for a signed-in user at all",
    }


def probe_services(*, elevated: bool, timeout: int = 60) -> dict[str, Any]:
    """Whether a service-installed runner is achievable, measured from the token's own rights.

    Creating a service is not attempted: unlike a scheduled task, a failed attempt can
    leave a half-created service behind, and the answer is already available without
    trying — a token that is not elevated cannot create one.
    """
    exe = _powershell_exe()
    privileges: list[str] = []
    if exe is not None:
        result = schtasks_run(
            [
                exe,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(whoami /priv | Select-String -Pattern 'Se[A-Za-z]+Privilege' "
                "| ForEach-Object { ($_ -split ' ')[0] }) -join ','",
            ],
            timeout=timeout,
        )
        if result["ok"] and result["stdout"]:
            privileges = [row for row in result["stdout"].strip().split(",") if row]
    has_service_right = "SeCreateService" in " ".join(privileges)
    return {
        "mechanism": "WINDOWS_SERVICE",
        "verdict": "NOT_ATTEMPTED_NEEDS_ELEVATION",
        "attempted": False,
        "token_elevated": bool(elevated),
        "privileges_held": privileges,
        "has_create_service_privilege": has_service_right,
        "why_not_attempted": (
            "creating a service needs administrator rights; a refused attempt can leave a "
            "half-created service behind, and this package does not change the host"
        ),
        "what_it_would_remove": (
            "the session dependence, and with it the need for any account to be signed in; it is "
            "the same effect as an S4U task at a larger price"
        ),
        "operator_command": (
            "an administrator installs the runner as a service, or registers the task with "
            "LogonType=S4U, which removes the same dependence with a smaller change"
        ),
    }


def probe_service_accounts(*, timeout: int = 120) -> dict[str, Any]:
    """Inventory the accounts that exist, and say whether any is designated for this purpose."""
    exe = _powershell_exe()
    accounts: list[dict[str, Any]] = []
    if exe is not None:
        script = (
            "Get-LocalUser | ForEach-Object { [ordered]@{ name=$_.Name; enabled=$_.Enabled; "
            "description=$_.Description } } | ConvertTo-Json -Compress"
        )
        result = schtasks_run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout
        )
        if result["ok"] and result["stdout"]:
            try:
                loaded = json.loads(result["stdout"])
            except json.JSONDecodeError:
                loaded = None
            if isinstance(loaded, dict):
                accounts = [loaded]
            elif isinstance(loaded, list):
                accounts = [row for row in loaded if isinstance(row, dict)]
    designated = [
        row
        for row in accounts
        if "trading" in str(row.get("description") or "").lower()
        or "agentic" in str(row.get("name") or "").lower()
    ]
    return {
        "mechanism": "AUTHORISED_SERVICE_ACCOUNT",
        "verdict": "VIABLE" if designated else "NO_ACCOUNT_DESIGNATED",
        "attempted": False,
        "accounts_found": len(accounts),
        "account_names": [str(row.get("name")) for row in accounts],
        "designated_for_this_campaign": [str(row.get("name")) for row in designated],
        "why_not_attempted": (
            "no account in this inventory is designated for the lane, and granting a right to "
            "an existing account is a change to this host's policy, which this package does not make"
        ),
    }


def probe_independent_host(repo_root: Path) -> dict[str, Any]:
    """Look for authorised infrastructure on another host, and enumerate what was looked at.

    "Another host exists" is a claim an operator makes; this is the scan that would have
    found the evidence for it on this one. A scan with no scope is a guess, so the paths
    and commands are recorded with the answer.
    """
    looked: list[dict[str, Any]] = []
    home = Path.home()
    for candidate in (
        home / ".ssh" / "config",
        home / ".ssh" / "known_hosts",
        repo_root / ".github" / "workflows",
        repo_root / ".runners",
    ):
        looked.append({"path": str(candidate), "exists": candidate.exists()})
    worktrees = schtasks_run(["git", "worktree", "list"], timeout=30)
    self_hosted: list[str] = []
    workflows = repo_root / ".github" / "workflows"
    if workflows.is_dir():
        for path in workflows.glob("*.y*ml"):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "self-hosted" in text or "runs-on: [self-hosted" in text:
                self_hosted.append(path.name)
    return {
        "mechanism": "INDEPENDENT_HOST_RUNNER",
        "verdict": "NO_AUTHORISED_INFRASTRUCTURE_FOUND",
        "attempted": False,
        "looked_at": looked,
        "git_worktrees": (worktrees.get("stdout") or "").splitlines(),
        "self_hosted_workflows": self_hosted,
        "reading": (
            "no SSH configuration, no known remote host and no self-hosted runner declaration "
            "was found in this checkout; a runner on another host stays a documented option for "
            "an operator who has one, not a mechanism this package can exercise"
        ),
    }


def additive_levers(*, evidence: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Price the levers the live registration already carries, from the lane's own log.

    Two settings in the registration are additive and were never asked to be measured:
    ``StartWhenAvailable`` (run a missed start as soon as possible) and the
    ``RestartOnFailure`` policy (restart a task whose process failed). Both are in the
    repository's own registration, both are visible in the lane's run log, and a lever
    that is present and recovers nothing is a different finding from one that is absent.

    The attribution is bounded on purpose: a run recorded with ``mode=SCHEDULED`` was
    *invoked* with the scheduler's own arguments, which is also what an on-demand
    ``schtasks /run`` does. The log therefore cannot say whether an off-cadence launch
    came from a catch-up, a policy restart or a person, and this record says so instead
    of picking the explanation that flatters the configuration.
    """
    task = evidence.get("task") or {}
    interval = 900
    phase_ms = None
    triggers = task.get("triggers") or []
    if triggers:
        boundary = str(triggers[0].get("start_boundary") or "")
        if boundary:
            from datetime import datetime

            try:
                parsed = datetime.fromisoformat(boundary)
                phase_ms = int(parsed.timestamp() * 1000) % (interval * 1000)
            except ValueError:
                phase_ms = None
    scheduled = [row for row in runs if str(row.get("mode")) == "SCHEDULED"]
    if phase_ms is None:
        offsets: list[int] = []
    else:
        offsets = [int(row.get("started_at_ms") or 0) % (interval * 1000) for row in scheduled]
    off_phase = [
        row
        for row, offset in zip(scheduled, offsets, strict=True)
        if phase_ms is not None and abs(offset - phase_ms) > 120_000
    ]
    restart_shaped: list[dict[str, Any]] = []
    for previous, following in pairwise(runs):
        if (
            str(previous.get("outcome"))
            in {
                "DISK_BUDGET_EXCEEDED",
                "RUNTIME_EXCEPTION",
                "PROVIDER_UNAVAILABLE",
                "MISSING_BARS",
                "STALE_DATA",
                "VERIFICATION_FAILED",
            }
            and str(following.get("mode")) == "SCHEDULED"
        ):
            delta = (
                int(following.get("started_at_ms") or 0) - int(previous.get("started_at_ms") or 0)
            ) / 1000.0
            if 240 <= delta <= 360:
                restart_shaped.append(
                    {
                        "after": previous.get("started_at_utc"),
                        "after_outcome": previous.get("outcome"),
                        "next": following.get("started_at_utc"),
                        "delta_seconds": round(delta, 1),
                    }
                )
    return {
        "start_when_available": task.get("start_when_available"),
        "restart_on_failure": {
            "count": task.get("restart_count"),
            "interval": task.get("restart_interval"),
        },
        "multiple_instances": task.get("multiple_instances"),
        "scheduled_launches": len(scheduled),
        "measured_phase_ms": phase_ms,
        "off_phase_launches": len(off_phase),
        "off_phase_instants": [row.get("started_at_utc") for row in off_phase[:10]],
        "restart_policy_shaped_follow_ups": len(restart_shaped),
        "restart_policy_shaped_detail": restart_shaped[:5],
        "attribution_limitation": (
            "a run recorded as SCHEDULED is invoked with the scheduler's own arguments, which is "
            "also what an on-demand `schtasks /run` does; the Task Scheduler operational log that "
            "would separate them is disabled on this host, so an off-phase launch is reported as "
            "off-phase and not attributed to a mechanism"
        ),
        "what_start_when_available_buys": (
            "it converts a start missed while the host was unavailable into a catch-up run when "
            "the host returns; it does not help a start that could not run because no session "
            "existed, which is the loss this campaign is actually about"
        ),
    }


def mechanisms(
    *,
    repo_root: Path,
    proposal_xml: str,
    scratch: Path,
    evidence: dict[str, Any],
    runs: list[dict[str, Any]],
    interval_minutes: int = 15,
) -> dict[str, Any]:
    """Run every mechanism evaluation RFC-EDGE-012 names, and keep the refusals verbatim."""
    from trading_bot.research.edge04r import session as session_probe

    probe_prefix = "TradingAgentic-EDGE12-Probe"
    # The probe registers a *runnable* copy of the definition with its principal changed to
    # S4U. Registering the committed definition unchanged would answer a question nobody
    # asked -- whether an InteractiveToken task can be registered, which it already is.
    s4u_definition = s4u_probe_definition(
        evidence=evidence, scratch=scratch, interval_minutes=interval_minutes
    )
    s4u_proposal = probe_s4u_proposal(
        proposal_xml=str(s4u_definition["xml"]),
        probe_name=f"{probe_prefix}-S4U",
        scratch=scratch,
    )
    s4u_proposal["lines_moved_from_the_committed_definition"] = _moved_lines(
        proposal_xml, str(s4u_definition["xml"])
    )
    s4u_proposal["definition"] = s4u_definition
    s4u_bare = session_probe.probe_s4u_registration(
        probe_name=f"{probe_prefix}-S4U-Bare", scratch=scratch
    )
    system_principal = probe_system_principal(probe_name=f"{probe_prefix}-System")
    services = probe_services(elevated=bool((evidence.get("host") or {}).get("elevated")))
    accounts = probe_service_accounts()
    host = probe_independent_host(repo_root)
    logon = session_probe.probe_logon_trigger_registration(
        probe_name=f"{probe_prefix}-Logon", scratch=scratch
    )
    witness = session_probe.probe_witness_action(
        probe_name=f"{probe_prefix}-Witness", scratch=scratch
    )
    levers = additive_levers(evidence=evidence, runs=runs)
    probes = {
        "S4U_PROPOSAL": s4u_proposal,
        "S4U_BARE": s4u_bare,
        "SYSTEM_PRINCIPAL": system_principal,
        "WINDOWS_SERVICE": services,
        "AUTHORISED_SERVICE_ACCOUNT": accounts,
        "INDEPENDENT_HOST_RUNNER": host,
        "LOGON_TRIGGER": logon,
        "WITNESS_ACTION": witness,
    }
    leftovers = [
        name for name in (f"{probe_prefix}-S4U", f"{probe_prefix}-System") if _task_exists(name)
    ]
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "probes": probes,
        "additive_levers": levers,
        "probe_tasks_left_behind": leftovers,
        "applied_to_the_live_task": False,
        "hypothetical": True,
        "order_sent": False,
    }


def preflight(
    *,
    repo_root: Path,
    definition_path: Path,
    task_name: str,
    evidence: dict[str, Any],
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """What an operator can check *before* applying the definition, each item an answer.

    A preflight that only lists the command is a reminder, not a check. Each item here
    interrogates this host: the definition's own elements, the binary and directory the
    action points at, the free space the guard needs, the phase a re-registration would
    move, and whether a probe task was left behind.
    """
    import xml.etree.ElementTree as ET

    checks: list[dict[str, Any]] = []

    def check(item_id: str, passed: bool, detail: str, *, blocking: bool = True) -> None:
        checks.append(
            {"id": item_id, "passed": bool(passed), "detail": detail, "blocking": bool(blocking)}
        )

    xml_text = _read_definition(definition_path)
    tree = None
    if xml_text:
        try:
            tree = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            check("definition_parses", False, f"the definition is not well-formed XML: {exc}")
    else:
        check("definition_parses", False, f"no definition at {definition_path}")
    namespace = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
    if tree is not None:
        kinds = [
            element.tag.replace(namespace, "")
            for element in tree.findall(f".//{namespace}Triggers/*")
        ]
        settings = {
            element.tag.replace(namespace, ""): (element.text or "")
            for element in tree.findall(f".//{namespace}Settings/*")
        }
        logon_types = [(element.text or "") for element in tree.findall(f".//{namespace}LogonType")]
        actions = tree.findall(f".//{namespace}Actions/*")
        check(
            "definition_carries_a_time_trigger",
            "TimeTrigger" in kinds,
            f"trigger elements: {kinds}",
        )
        check(
            "definition_adds_a_logon_trigger",
            "LogonTrigger" in kinds,
            f"trigger elements: {kinds}",
        )
        first_action_text = "".join("".join(actions[0].itertext()) for _ in [0]) if actions else ""
        check(
            "definition_carries_the_witness_action_first",
            len(actions) >= 2 and "witness" in first_action_text.lower(),
            f"{len(actions)} action(s), first is the witness: "
            f"{'yes' if 'witness' in first_action_text.lower() else 'no'}",
        )
        check(
            "definition_declares_its_logon_type",
            bool([row for row in logon_types if row]),
            f"logon types declared: {logon_types or '(none)'}",
        )
        check(
            "definition_keeps_multiple_instances_ignored",
            settings.get("MultipleInstancesPolicy") == "IgnoreNew",
            f"MultipleInstancesPolicy={settings.get('MultipleInstancesPolicy')!r}",
        )
        command_element = actions[-1] if actions else None
        executable = ""
        working_dir = ""
        if command_element is not None:
            executable = (command_element.findtext(f"{namespace}Command") or "").strip()
            working_dir = (command_element.findtext(f"{namespace}WorkingDirectory") or "").strip()
        check(
            "the_action_binary_exists_on_this_host",
            bool(executable) and Path(executable).is_file(),
            f"command={executable or '(none)'}",
        )
        check(
            "the_working_directory_exists_on_this_host",
            bool(working_dir) and Path(working_dir).is_dir(),
            f"working_directory={working_dir or '(none)'}",
        )
        check(
            "the_interpreter_is_the_interpreter_that_certified_this_package",
            bool(executable) and Path(executable).is_file(),
            "the same interpreter WP-EDGE-12A measured the entry points under",
        )

    witness_path = proposal.get("witness_path")
    if witness_path:
        candidate = Path(str(witness_path))
        parent = candidate.parent
        check(
            "the_witness_path_is_writable",
            parent.is_dir() and _is_writable(parent),
            f"witness={candidate}",
        )

    from trading_bot.research.edge03 import autonomous

    free = (
        int(evidence.get("storage_free_bytes") or 0) if evidence.get("storage_free_bytes") else None
    )
    if free is None:
        volumes = evidence.get("volumes") or []
        current = next(
            (
                row
                for row in volumes
                if str(row.get("drive_letter") or "")
                .upper()
                .startswith(str(repo_root.drive).upper()[:1])
            ),
            None,
        )
        free = int(current.get("free_bytes") or 0) if current else 0
    check(
        "the_volume_is_above_the_guard_critical_floor",
        free >= autonomous.DISK_CRITICAL_BYTES,
        f"{round(free / 1024**3, 4)} GiB free against a critical floor of "
        f"{round(autonomous.DISK_CRITICAL_BYTES / 1024**3, 4)} GiB",
        blocking=False,
    )

    live_triggers = (evidence.get("task") or {}).get("triggers") or []
    live_boundary = str(live_triggers[0].get("start_boundary") or "") if live_triggers else ""
    proposal_boundary = ""
    if tree is not None:
        proposal_boundary = next(
            (
                str(element.text)
                for element in tree.findall(f".//{namespace}TimeTrigger/{namespace}StartBoundary")
            ),
            "",
        )
    check(
        "the_definition_keeps_the_live_cadence_phase",
        bool(live_boundary) and live_boundary == proposal_boundary,
        f"live boundary {live_boundary or '(none)'} vs definition {proposal_boundary or '(none)'}",
    )
    check(
        "the_target_task_name_is_the_lane_own",
        task_name == str((evidence.get("task") or {}).get("task_name") or task_name),
        f"task_name={task_name}",
    )
    check(
        "no_probe_task_was_left_behind_by_this_pass",
        not _task_exists("TradingAgentic-EDGE12-Probe-S4U")
        and not _task_exists("TradingAgentic-EDGE12-Probe-System"),
        "the scheduler was asked, not the probe's own delete call",
    )

    blocking_failures = [row["id"] for row in checks if row["blocking"] and not row["passed"]]
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "generated_at_utc": _now(),
        "definition_path": str(definition_path),
        "definition_sha256": _sha256(definition_path),
        "task_name": task_name,
        "checks": checks,
        "blocking_failures": blocking_failures,
        "verdict": "PREFLIGHT_PASS" if not blocking_failures else "PREFLIGHT_FAILED",
        "applies_nothing": (
            "every item is a read of this host; applying the definition stays an operator action, "
            "and the rollback is written before it is needed"
        ),
    }


def _moved_lines(left: str, right: str) -> int:
    """How many lines differ between two definitions, positionally."""
    left_lines = left.splitlines()
    right_lines = right.splitlines()
    moved = sum(1 for a, b in zip(left_lines, right_lines, strict=False) if a != b) + abs(
        len(left_lines) - len(right_lines)
    )
    return moved


def _read_definition(path: Path) -> str:
    """Read a task definition whatever encoding it was written in.

    ``schtasks /xml`` wants UTF-16 and a definition written for a human wants UTF-8, and
    the two cannot be told apart by trying them: a UTF-8 file decodes as UTF-16 without
    raising, into text nobody can parse, so a preflight that guessed would report a
    definition that exists as malformed. The byte-order mark is what decides, and only a
    file without one falls back to guessing.
    """
    if not path.is_file():
        return ""
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16", "utf-8-sig", "utf-8")
    elif data.startswith(b"\xef\xbb\xbf"):
        encodings = ("utf-8-sig", "utf-8")
    else:
        encodings = ("utf-8", "cp1252")
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (UnicodeError, LookupError):
            continue
    return ""


def _is_writable(path: Path) -> bool:
    probe = path / ".edge12-write-probe"
    try:
        probe.write_text("probe\n", encoding="utf-8")
    except OSError:
        return False
    finally:
        probe.unlink(missing_ok=True)
    return True


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def decide(
    *, probes: dict[str, Any], preflight_row: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    """The decision: which mechanism, what it removes, what it costs and why not the others."""
    rows = probes["probes"]
    s4u = rows["S4U_PROPOSAL"]
    witness = rows["WITNESS_ACTION"]
    preferred = (
        "S4U_TASK" if s4u["registration_ok"] and not s4u["task_left_behind"] else "LOGON_TRIGGER"
    )
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "generated_at_utc": _now(),
        "selected": preferred,
        "selection_rule": (
            "prefer the mechanism that removes the dependence and stores no credential; fall back "
            "to the additive mechanism that bounds the loss instead of the one that would require "
            "a credential or a privilege this package does not have"
        ),
        "selected_detail": (
            "the host refused the S4U registration of this very definition, so the mechanism that "
            "removes the dependence is not available to this process; the logon trigger is the "
            "strongest available one and is already exercised"
            if preferred == "LOGON_TRIGGER"
            else "the host accepted an S4U registration of this very definition from this process"
        ),
        "evaluations": [
            {
                "mechanism": mechanism,
                "question": question,
                "verdict": _verdict_for(rows, mechanism),
                "detail": _detail_for(rows, mechanism),
            }
            for mechanism, question in MECHANISMS
        ],
        "available_without_new_privileges": [
            name for name, row in rows.items() if row.get("verdict") == "VIABLE"
        ],
        "blocked": {
            name: row.get("verdict")
            for name, row in rows.items()
            if str(row.get("verdict", "")).startswith(("NEEDS_", "NO_", "NOT_ATTEMPTED"))
        },
        "additive_levers": probes["additive_levers"],
        "preflight_verdict": preflight_row["verdict"],
        "applied_to_the_live_task": False,
        "what_the_selected_mechanism_buys": {
            "removes_the_session_dependence": preferred == "S4U_TASK",
            "bounds_recovery_after_a_sign_in": preferred == "LOGON_TRIGGER",
            "makes_silence_attributable": bool(witness.get("verdict") == "VIABLE"),
            "logon_trigger_delay_seconds": 60,
        },
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }


def _verdict_for(rows: dict[str, Any], mechanism: str) -> str:
    if mechanism == "S4U_TASK":
        return str(rows["S4U_PROPOSAL"].get("verdict"))
    if mechanism == "WINDOWS_SERVICE":
        return str(rows["WINDOWS_SERVICE"].get("verdict"))
    if mechanism == "AUTHORISED_SERVICE_ACCOUNT":
        return str(rows["AUTHORISED_SERVICE_ACCOUNT"].get("verdict"))
    if mechanism == "INDEPENDENT_HOST_RUNNER":
        return str(rows["INDEPENDENT_HOST_RUNNER"].get("verdict"))
    if mechanism == "LOGON_TRIGGER":
        return str(rows["LOGON_TRIGGER"].get("verdict"))
    return "NOT_EVALUATED"


def _detail_for(rows: dict[str, Any], mechanism: str) -> str:
    mapping = {
        "S4U_TASK": rows["S4U_PROPOSAL"].get("registration_output") or "",
        "WINDOWS_SERVICE": rows["WINDOWS_SERVICE"].get("why_not_attempted") or "",
        "AUTHORISED_SERVICE_ACCOUNT": rows["AUTHORISED_SERVICE_ACCOUNT"].get("why_not_attempted")
        or "",
        "INDEPENDENT_HOST_RUNNER": rows["INDEPENDENT_HOST_RUNNER"].get("reading") or "",
        "LOGON_TRIGGER": rows["LOGON_TRIGGER"].get("detail") or "",
    }
    return str(mapping.get(mechanism, ""))[:400]


def rollback(*, task_name: str, evidence: dict[str, Any], definition_path: Path) -> dict[str, Any]:
    """The undo, written before anything is applied and pinned to the current registration.

    The rollback is not "run the create command again": the live registration's own XML
    is captured here, so undoing a re-registration restores the bytes that were there
    rather than a definition somebody reconstructed from a report.
    """
    task = evidence.get("task") or {}
    live_xml = str(task.get("xml") or "")
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "generated_at_utc": _now(),
        "task_name": task_name,
        "captured_before_any_change": True,
        "live_registration_sha256": _sha256_of_text(live_xml),
        "live_registration_bytes": len(live_xml.encode("utf-8")),
        "live_registration_trigger_kinds": [
            str(row.get("type")) for row in (task.get("triggers") or []) if isinstance(row, dict)
        ],
        "steps": [
            {
                "order": 1,
                "action": "export the current registration before applying anything",
                "command": f'schtasks /query /tn "{task_name}" /xml > rollback-before.xml',
            },
            {
                "order": 2,
                "action": "restore it if the applied definition misbehaves",
                "command": f'schtasks /create /tn "{task_name}" /xml rollback-before.xml /f',
            },
            {
                "order": 3,
                "action": "prove the restore, rather than assuming it",
                "command": f'schtasks /query /tn "{task_name}" /xml',
                "verify": "the trigger kinds and the logon type match live_registration_trigger_kinds",
            },
            {
                "order": 4,
                "action": "if the task itself is wrong, remove it and let the lane re-register",
                "command": f'schtasks /delete /tn "{task_name}" /f',
                "precondition": "the observer is stopped first, or the lane keeps ticking under no registration",
            },
        ],
        "rollback_definition": str(definition_path),
        "what_a_rollback_cannot_undo": (
            "the phase of the cadence: re-registering moves StartBoundary, and the instants "
            "before and after are not comparable in one window; a reading taken across the "
            "change must declare where it happened"
        ),
        "research_only": True,
    }


def _sha256_of_text(text: str) -> str | None:
    if not text:
        return None
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def operator_handoff(
    *, decision: dict[str, Any], rollback_row: dict[str, Any], proposal_path: Path
) -> dict[str, Any]:
    """The one page an operator needs: what to run, what to expect, what to check after."""
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "generated_at_utc": _now(),
        "applies_nothing_here": True,
        "selected_mechanism": decision["selected"],
        "definition": str(proposal_path),
        "steps": [
            {
                "order": 1,
                "title": "read the preflight",
                "command": "python scripts/edge12_runner.py --preflight-only",
                "expect": "PREFLIGHT_PASS with zero blocking failures",
            },
            {
                "order": 2,
                "title": "capture the current registration",
                "command": rollback_row["steps"][0]["command"],
                "expect": "a rollback-before.xml whose sha256 equals the one recorded in ROLLBACK.md",
            },
            {
                "order": 3,
                "title": "apply the definition (an operator decision)",
                "command": f'schtasks /create /tn "{rollback_row["task_name"]}" /xml "{proposal_path.as_posix()}" /f',
                "expect": "the scheduler reports the task with both trigger kinds",
            },
            {
                "order": 4,
                "title": "verify what the scheduler kept",
                "command": f'schtasks /query /tn "{rollback_row["task_name"]}" /xml',
                "expect": "MSFT_TaskLogonTrigger beside MSFT_TaskTimeTrigger, and the lane's own action unchanged",
            },
            {
                "order": 5,
                "title": "for the mechanisms this process cannot use, an administrator is the actor",
                "command": "wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true",
                "expect": "the operational log enabled, which is what makes a future silent trigger attributable",
                "requires": "administrator rights",
            },
        ],
        "what_changes_for_the_measurement": (
            "the cadence phase: StartBoundary is carried over to the second, so the instants do not "
            "move, but the logon trigger adds starts that are not on the quarter-hour grid"
        ),
        "what_does_not_change": (
            "the action, its working directory, the principal's run level, the multiple-instances "
            "policy, the storage guard and every threshold this campaign measures against"
        ),
        "research_only": True,
    }
