"""CAP-004B — independent verification of the persistent campaign supervisor.

This verifier never calls the supervisor.  It re-reads the artifacts from disk and
answers a narrow operational question: *is the campaign really being kept alive,
without the experiment having moved?*

It checks, independently:

* the operations ledger re-derives its own hash chain from the written bytes;
* the operating system really has the supervisor registered, enabled, invoked with
  the right command, from the repo, forbidding concurrent instances, and carrying
  no embedded secret;
* the frozen experiment manifest has not moved (its digest is pinned here);
* the decision/outcome/evaluation ledger has no duplicates, no backfilled slot and
  no outcome stamped in the future;
* CAP-003 and CAP-004 verify as separate processes;
* the campaign heartbeat is a real record (never future-dated) while the
  supervisor keeps its own, separate, freshness verdict.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
LEDGER_ROOT = REPO / "evidence" / "real_decisions"
REPORTS = REPO / "reports"
CAP004B_ROOT = REPORTS / "cap004b"
CAP004_ROOT = REPORTS / "cap004"
CAP003_VERIFICATION = REPORTS / "agentic-campaign-cap003" / "CAP003_VERIFICATION.json"
CAP004_VERIFICATION = CAP004_ROOT / "CAP004_VERIFICATION.json"

# --- independently re-declared frozen contract ------------------------------ #
MANIFEST_FILENAME = "CAMPAIGN_MANIFEST.json"
DECISIONS_FILENAME = "decisions.jsonl"
OUTCOMES_FILENAME = "outcomes.jsonl"
EVALUATIONS_FILENAME = "evaluations.jsonl"
HEARTBEAT_FILENAME = "heartbeat.json"
OPERATIONS_FILENAME = "operations.jsonl"
SUPERVISOR_STATUS_FILENAME = "SUPERVISOR_STATUS.json"

CAMPAIGN_ID = "CAP004-REAL-DECISIONS-V1"
CAMPAIGN_VERSION = "1.0"
OPS_VERSION_PATTERN = r"^CAP004B-\d+$"
MANIFEST_DIGEST = "59b7b3582f043d0e17c1a783bfc698ace70f9de37595c500bc9459a839fbddef"
SLOT_UTC_HOUR = 16
SEAL_WINDOW_SECONDS = 14_400
GENESIS_HASH = "0" * 64
TASK_NAME = "TradingAgentic-CAP004-Campaign"
TASK_NS = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"

CAMPAIGN_STATUSES = {
    "INITIALIZING",
    "RUNNING",
    "DEGRADED",
    "BLOCKED",
    "INTEGRITY_FAILURE",
    "COMPLETE_100",
}
SUPERVISOR_STATES = {"HEALTHY", "DEGRADED", "RECOVERING", "BLOCKED", "STOPPED"}
FORBIDDEN_SUPERVISOR_WORDS = (
    "PROFITABLE",
    "EDGE_CONFIRMED",
    "STRATEGY_VALIDATED",
    "PAPER_READY",
    "LIVE_READY",
)
SECRET_PATTERNS = (
    r"api[_-]?key",
    r"api[_-]?secret",
    r"\bsecret\b",
    r"\bpassword\b",
    r"\btoken\s*=",
    r"BEGIN [A-Z ]*PRIVATE KEY",
)

CHECKS: list[dict[str, Any]] = []
LIMITATIONS: list[str] = []
DIAGNOSTICS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append({"check": name, "passed": bool(ok), "detail": detail})
    return bool(ok)


def limit(note: str) -> None:
    LIMITATIONS.append(note)


def diagnose(note: str) -> None:
    DIAGNOSTICS.append(note)


# --------------------------------------------------------------------------- #
# independent canonicalisation and hashing (never imported from the supervisor)
# --------------------------------------------------------------------------- #


def canonical(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def event_hash(record: dict[str, Any]) -> str:
    body = {key: value for key, value in record.items() if key != "event_hash"}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def verify_chain(entries: list[dict[str, Any]]) -> dict[str, Any]:
    previous = GENESIS_HASH
    for index, entry in enumerate(entries):
        if str(entry.get("previous_hash")) != previous:
            return {"status": "BROKEN", "index": index, "reason": "previous_hash"}
        if str(entry.get("event_hash")) != event_hash(entry):
            return {"status": "BROKEN", "index": index, "reason": "event_hash"}
        previous = str(entry["event_hash"])
    return {"status": "INTACT", "events": len(entries), "head": previous}


def heartbeat_integrity(stamp: int, now: int) -> bool:
    """A heartbeat must be a real record, never future-dated (CAP-004 §33)."""
    return 0 < int(stamp) <= int(now)


# --------------------------------------------------------------------------- #
# independent scheduler query
# --------------------------------------------------------------------------- #


def _run(args: list[str], *, timeout: int = 60) -> tuple[int | None, str, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "", repr(exc)
    return proc.returncode, proc.stdout, proc.stderr


def scheduler_type() -> str:
    if os.name == "nt":
        return "windows_task_scheduler"
    if sys.platform.startswith("linux") and shutil.which("systemctl"):
        return "systemd_user"
    return "none"


def _text(node: ET.Element | None) -> str | None:
    return node.text if node is not None else None


def _child(parent: ET.Element | None, tag: str) -> ET.Element | None:
    return parent.find(tag) if parent is not None else None


def scheduler_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {
        "scheduler_type": scheduler_type(),
        "installed": False,
        "enabled": False,
    }
    if result["scheduler_type"] != "windows_task_scheduler":
        return result
    code, stdout, stderr = _run(["schtasks", "/query", "/tn", TASK_NAME, "/xml", "ONE"])
    if code != 0:
        result["reason"] = stderr.strip()
        return result
    result["install_xml_code"] = code
    result["raw_xml"] = stdout
    try:
        root = ET.fromstring(stdout)
    except ET.ParseError as exc:
        result["parse_error"] = repr(exc)
        return result
    settings = root.find(f"{TASK_NS}Settings")
    exec_node = root.find(f".//{TASK_NS}Actions/{TASK_NS}Exec")
    principal = root.find(f".//{TASK_NS}Principal")
    result["installed"] = True
    result["enabled_xml"] = _text(_child(settings, f"{TASK_NS}Enabled"))
    result["multiple_instances"] = _text(_child(settings, f"{TASK_NS}MultipleInstancesPolicy"))
    result["start_when_available"] = _text(_child(settings, f"{TASK_NS}StartWhenAvailable"))
    result["command"] = _text(_child(exec_node, f"{TASK_NS}Command"))
    result["arguments"] = _text(_child(exec_node, f"{TASK_NS}Arguments"))
    result["working_directory"] = _text(_child(exec_node, f"{TASK_NS}WorkingDirectory"))
    result["run_level"] = _text(_child(principal, f"{TASK_NS}RunLevel"))
    ps = (
        f"$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue; "
        "if ($null -ne $t) { "
        "$i = Get-ScheduledTaskInfo -TaskName '"
        + TASK_NAME
        + "'; [pscustomobject]@{ State=[string]$t.State; LastRunTime=[string]$i.LastRunTime; "
        "LastTaskResult=$i.LastTaskResult; NextRunTime=[string]$i.NextRunTime } | ConvertTo-Json -Compress }"
    )
    ps_exe = shutil.which("powershell") or "powershell"
    code, stdout, _ = _run([ps_exe, "-NoProfile", "-NonInteractive", "-Command", ps])
    if code == 0 and stdout.strip():
        try:
            info = json.loads(stdout.strip())
            if isinstance(info, dict):
                result.update(
                    {
                        "state": info.get("State"),
                        "last_run_time": info.get("LastRunTime"),
                        "last_task_result": info.get("LastTaskResult"),
                        "next_run_time": info.get("NextRunTime"),
                    }
                )
        except json.JSONDecodeError:
            pass
    # The exported XML omits <Enabled>: task state is authoritative (PowerShell).
    result["enabled"] = str(result.get("state") or "") not in ("", "Disabled")
    # The exported XML also omits <RunLevel> when it is the default (least privilege).
    result["privilege"] = str(result.get("run_level") or "LeastPrivilege")
    return result


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    now = int(time.time())
    decisions = read_jsonl(LEDGER_ROOT / DECISIONS_FILENAME)
    outcomes = read_jsonl(LEDGER_ROOT / OUTCOMES_FILENAME)
    evaluations = read_jsonl(LEDGER_ROOT / EVALUATIONS_FILENAME)
    operations = read_jsonl(LEDGER_ROOT / OPERATIONS_FILENAME)
    heartbeat = load_json(LEDGER_ROOT / HEARTBEAT_FILENAME)
    supervisor_status = load_json(CAP004B_ROOT / SUPERVISOR_STATUS_FILENAME)
    manifest = load_json(LEDGER_ROOT / MANIFEST_FILENAME)

    # --- §A operations ledger --------------------------------------------- #
    check("the operations ledger exists", (LEDGER_ROOT / OPERATIONS_FILENAME).is_file())
    chain = verify_chain(operations)
    check(
        "the operations hash chain re-derives independently",
        chain["status"] == "INTACT",
        f"status={chain['status']} events={chain.get('events')}",
    )
    check("the operations ledger is non-empty", len(operations) > 0)
    check(
        "every operations event names the campaign",
        all(str(item.get("campaign_id")) == CAMPAIGN_ID for item in operations),
    )
    check(
        "every operations event carries a CAP-004B ops version",
        all(
            re.fullmatch(OPS_VERSION_PATTERN, str(item.get("ops_version", "")))
            for item in operations
        ),
    )
    ops_versions = {str(item.get("ops_version")) for item in operations}
    check(
        "ops_version is separate from the frozen campaign version",
        bool(ops_versions) and CAMPAIGN_VERSION not in ops_versions,
        f"ops_versions={sorted(ops_versions)}",
    )
    check(
        "no operations event is dated in the future",
        all(
            int(item.get("started_at", 0)) <= now + 5 and int(item.get("ended_at", 0)) <= now + 5
            for item in operations
        ),
    )
    check(
        "the operations ledger records real supervisor runs",
        any(
            str(item.get("action")) in ("RUN", "NOOP", "PREFLIGHT_BLOCKED", "STOPPED")
            for item in operations
        ),
    )
    check(
        "the supervisor status file records the same ops version",
        str(supervisor_status.get("ops_version", "")) in ops_versions,
    )
    check(
        "the supervisor status keeps campaign_version frozen",
        supervisor_status.get("campaign_version") == CAMPAIGN_VERSION
        or supervisor_status.get("experiment_version") == CAMPAIGN_VERSION,
    )

    # --- §B scheduler ------------------------------------------------------ #
    sched = scheduler_snapshot()
    check(
        "a native scheduler is available on this host",
        sched["scheduler_type"] in ("windows_task_scheduler", "systemd_user"),
        str(sched["scheduler_type"]),
    )
    check("the supervisor is registered in the OS scheduler", bool(sched.get("installed")))
    check(
        "the registered task is enabled", bool(sched.get("enabled")), f"state={sched.get('state')}"
    )
    expected_script = "cap004_supervisor.py"
    arguments = str(sched.get("arguments") or "")
    check(
        "the registered command invokes this supervisor",
        expected_script in arguments and arguments.rstrip().endswith("run"),
        arguments,
    )
    check(
        "the registered working directory is the repository",
        os.path.normcase(str(sched.get("working_directory") or "")) == os.path.normcase(str(REPO)),
        str(sched.get("working_directory")),
    )
    check(
        "the task forbids concurrent instances",
        str(sched.get("multiple_instances")) == "IgnoreNew",
        str(sched.get("multiple_instances")),
    )
    check(
        "the task starts as soon as possible after a missed run",
        str(sched.get("start_when_available")).lower() == "true",
        str(sched.get("start_when_available")),
    )
    check(
        "the task runs with least privilege",
        str(sched.get("privilege") or "") in ("LeastPrivilege", "Limited"),
        str(sched.get("privilege")),
    )
    definition_text = " ".join(
        str(sched.get(key) or "")
        for key in ("command", "arguments", "working_directory", "raw_xml")
    )
    check(
        "the task definition embeds no credential",
        not any(re.search(pattern, definition_text, re.IGNORECASE) for pattern in SECRET_PATTERNS),
    )

    # --- §C the experiment has not moved ---------------------------------- #
    manifest_digest = (
        hashlib.sha256(canonical(manifest).encode("utf-8")).hexdigest() if manifest else None
    )
    check(
        "the frozen campaign manifest is unchanged",
        manifest_digest == MANIFEST_DIGEST,
        f"digest={manifest_digest}",
    )
    check(
        "the campaign identity is unchanged",
        manifest.get("campaign_id") == CAMPAIGN_ID
        and str(manifest.get("campaign_version")) == CAMPAIGN_VERSION,
    )
    check(
        "the manifest still declares the four real assets",
        [str(item) for item in manifest.get("assets", [])]
        == ["BINANCE:BTCUSDT", "BINANCE:ETHUSDT", "BINANCE:SOLUSDT", "BINANCE:XRPUSDT"],
    )

    # --- §D ledger integrity (independent of the CAP-004 verifier) -------- #
    decision_keys = [
        f"{item.get('asset')}|{int(item.get('decision_time', 0))}|{item.get('horizon')}"
        for item in decisions
    ]
    check("no decision slot was sealed twice", len(set(decision_keys)) == len(decision_keys))
    outcome_keys = [f"{item.get('decision_id')}|{item.get('horizon')}" for item in outcomes]
    check("no outcome was settled twice", len(set(outcome_keys)) == len(outcome_keys))
    evaluation_keys = [f"{item.get('decision_id')}|{item.get('horizon')}" for item in evaluations]
    check("no evaluation was written twice", len(set(evaluation_keys)) == len(evaluation_keys))
    check(
        "every decision sits on the 16:00 UTC slot grid",
        all(
            dt.datetime.fromtimestamp(int(item.get("decision_time", 0)), dt.UTC).hour
            == SLOT_UTC_HOUR
            and dt.datetime.fromtimestamp(int(item.get("decision_time", 0)), dt.UTC).minute == 0
            for item in decisions
        ),
    )
    check(
        "no CAP-004 decision was backfilled after its seal window",
        all(
            int(item.get("delay_seconds") or 0) <= SEAL_WINDOW_SECONDS
            for item in decisions
            if str((item.get("provenance") or {}).get("campaign_id") or "") == CAMPAIGN_ID
        ),
    )
    check(
        "no outcome is stamped in the future",
        all(int(item.get("exit_close_time", 0)) <= now for item in outcomes),
    )
    settled_total = sum(int(item.get("settled", 0)) for item in operations)
    check(
        "the supervisor never settled more decisions than exist",
        settled_total <= len(outcomes),
        f"sum(settled)={settled_total} n_outcomes={len(outcomes)}",
    )
    if settled_total == len(outcomes) and len(outcomes) > 0:
        diagnose(f"every settled outcome was settled under the supervisor ({settled_total})")

    # --- §E campaign heartbeat -------------------------------------------- #
    stamp = int(heartbeat.get("timestamp", 0)) if heartbeat else 0
    check("the campaign heartbeat is a real record", heartbeat_integrity(stamp, now), str(stamp))
    check(
        "the campaign heartbeat uses the campaign vocabulary",
        heartbeat.get("process_status") in CAMPAIGN_STATUSES,
        str(heartbeat.get("process_status")),
    )
    diagnose(f"campaign heartbeat age = {now - stamp}s (liveness, not integrity)")

    # --- §F the two shipped verifiers still pass -------------------------- #
    if CAP004_VERIFICATION.is_file():
        cap004 = load_json(CAP004_VERIFICATION)
        check(
            "the CAP-004 verifier passes",
            cap004.get("status") == "PASS",
            f"status={cap004.get('status')} passed={cap004.get('passed')}/{cap004.get('total')}",
        )
        check(
            "the CAP-004 verifier reports no false success",
            int(cap004.get("false_success", 1)) == 0,
            str(cap004.get("false_success")),
        )
    else:
        limit("the CAP-004 verification report is absent locally; CAP-004 re-check deferred")

    if CAP003_VERIFICATION.is_file():
        cap003 = load_json(CAP003_VERIFICATION)
        check(
            "the CAP-003 verifier passes", cap003.get("status") == "PASS", str(cap003.get("status"))
        )
    else:
        limit("the CAP-003 verification report is absent locally; CAP-003 re-check deferred")

    # --- §G no promotional vocabulary ------------------------------------- #
    check(
        "the supervisor vocabulary contains no promotional word",
        not any(
            word in " ".join(str(value) for value in supervisor_status.values())
            for word in FORBIDDEN_SUPERVISOR_WORDS
        ),
    )
    check(
        "the supervisor does not trade",
        int(manifest.get("trades_authorized", 0)) == 0
        and str(manifest.get("alpha_claimed")) == "NONE",
    )

    # --- declared limitations --------------------------------------------- #
    limit(
        "the operations ledger is operational state (evidence/real_decisions/operations.jsonl is "
        "gitignored, like the heartbeat) and lives only on this host; the verifier can only check "
        "what this machine recorded"
    )
    limit(
        "scheduler state is host-local: another machine running the same repository would register "
        "its own task, so this check is only meaningful on the host it runs on"
    )
    limit(
        "the model temperature is NOT_EXPOSED, so no operational check can detect temperature drift"
    )
    limit(
        f"the campaign holds {len(evaluations)} evaluable decisions; no operational check can make "
        "an edge verdict available before 100"
    )

    # --- false success ---------------------------------------------------- #
    false_success: list[str] = []
    if chain["status"] != "INTACT":
        false_success.append("the operations hash chain does not re-derive")
    if not sched.get("installed") or not sched.get("enabled"):
        false_success.append("the scheduler task is not installed and enabled")
    if manifest_digest != MANIFEST_DIGEST:
        false_success.append("the frozen campaign manifest moved")
    if len(set(decision_keys)) != len(decision_keys):
        false_success.append("a decision slot was sealed twice")
    if settled_total > len(outcomes):
        false_success.append("an outcome was settled more than once")
    if any(
        int(item.get("delay_seconds") or 0) > SEAL_WINDOW_SECONDS
        for item in decisions
        if str((item.get("provenance") or {}).get("campaign_id") or "") == CAMPAIGN_ID
    ):
        false_success.append("a decision was backfilled after its seal window")
    if not heartbeat_integrity(stamp, now):
        false_success.append("the campaign heartbeat is not a real record")
    if any(re.search(pattern, definition_text, re.IGNORECASE) for pattern in SECRET_PATTERNS):
        false_success.append("the scheduler task embeds a credential")

    passed = sum(1 for entry in CHECKS if entry["passed"])
    total = len(CHECKS)
    mismatches = [entry for entry in CHECKS if not entry["passed"]]
    status_name = "PASS" if not mismatches and not false_success else "FAIL"

    payload = {
        "capability": "CAP-004B",
        "verifier": "scripts/cap004b_verify.py",
        "status": status_name,
        "passed": passed,
        "total": total,
        "mismatches": len(mismatches),
        "mismatch_detail": mismatches,
        "false_success": len(false_success),
        "false_success_detail": false_success,
        "limitations": LIMITATIONS,
        "diagnostics": DIAGNOSTICS,
        "scheduler": {key: value for key, value in sched.items() if key != "raw_xml"},
        "operations": chain,
        "population": {
            "n_decisions": len(decisions),
            "n_outcomes": len(outcomes),
            "n_evaluations": len(evaluations),
            "n_operations": len(operations),
        },
        "checks": CHECKS,
    }
    CAP004B_ROOT.mkdir(parents=True, exist_ok=True)
    (CAP004B_ROOT / "CAP004B_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )

    lines = [
        "CAP-004B INDEPENDENT VERIFICATION",
        "",
        f"STATUS = {status_name}",
        f"CHECKS = {passed}/{total}",
        f"MISMATCHES = {len(mismatches)}",
        f"FALSE_SUCCESS = {len(false_success)}",
        f"LIMITATIONS = {len(LIMITATIONS)}",
        "",
    ]
    for bad in mismatches:
        lines.append(f"- MISMATCH: {bad['check']} — {bad['detail']}")
    for trigger in false_success:
        lines.append(f"- FALSE_SUCCESS: {trigger}")
    for note in LIMITATIONS:
        lines.append(f"- LIMITATION: {note}")
    for note in DIAGNOSTICS:
        lines.append(f"- DIAGNOSTIC: {note}")
    lines.append("")
    (CAP004B_ROOT / "CAP004B_VERIFICATION.md").write_text("\n".join(lines), encoding="utf-8")

    print("CAP-004B INDEPENDENT VERIFICATION")
    print(f"STATUS = {status_name}")
    print(f"CHECKS = {passed}/{total}")
    print(f"MISMATCHES = {len(mismatches)}")
    print(f"FALSE_SUCCESS = {len(false_success)}")
    print(f"LIMITATIONS = {len(LIMITATIONS)}")
    for bad in mismatches:
        print(f"  MISMATCH: {bad['check']} — {bad['detail']}")
    for trigger in false_success:
        print(f"  FALSE_SUCCESS: {trigger}")
    for note in LIMITATIONS:
        print(f"  LIMITATION: {note}")
    for note in DIAGNOSTICS:
        print(f"  DIAGNOSTIC: {note}")
    return 0 if status_name == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
