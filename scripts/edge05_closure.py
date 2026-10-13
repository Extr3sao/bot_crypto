"""WP-EDGE-05 — the closure artefacts: what was observed, what it costs, and what the host allows.

    python scripts/edge05_closure.py                     write into reports/edge-recovery/WP-EDGE-05
    python scripts/edge05_closure.py --out DIR           somewhere else
    python scripts/edge05_closure.py --json              the payloads on stdout

This program decides nothing. It reads the lane's own evidence, the watchdog's own readings and the
operating system's own description of the scheduled task, and writes:

* ``EDGE05_WATCHDOG_STATUS.json`` — the newest verdict, its history and the alert log's shape;
* ``EDGE05_RESOURCE_BUDGET.json`` — measured growth, the declared thresholds and what each one does;
* ``EDGE05_WINDOWS_CONTINUITY.json`` / ``.md`` — the task's registered settings, the operating
  system's own statement about the logon mode, what that permits, and the one change that would
  remove the limitation (which needs the owner's password and is therefore not applied here);
* ``evidence/FASE5_TIMELINE.md`` — the ticks, the checks and the alerts on one page;
* ``evidence/STORE_SLICE.json`` — the bars after each series' epoch with the digest of the file
  they came from: the whole of the store the reconciliation reads, kept small enough to version;
* ``evidence/SNAPSHOT.json`` — the digest and size of every artefact it wrote, so the set can be
  checked rather than trusted.

Research only: no orders, no credentials, no capital, no promotion.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from edge05_verify import (  # noqa: E402  (the verifier's own store-slice renderer, reused)
    SERIES,
    Evidence,
    Verifier,
    read_json,
    read_jsonl,
    sha256_file,
    snapshot_store,
    stamp_ms,
)

LANE_TASK = "TradingAgentic-EDGE04-Forward"
WATCHDOG_TASK = "TradingAgentic-EDGE05-Watchdog"
GIB = 1024**3


def now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def which(name: str) -> str:
    return shutil.which(name) or name


def powershell(script: str, *, timeout: int = 90) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [which("powershell"), "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - environmental
        return {"ok": False, "error": repr(exc)}
    return {
        "ok": proc.returncode == 0,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "returncode": proc.returncode,
    }


def task_xml(task_name: str) -> dict[str, Any]:
    """The task's own registration, exported verbatim. Read-only; changes nothing."""
    result = powershell(f"Export-ScheduledTask -TaskName '{task_name}'")
    if not result.get("ok") or not result.get("stdout"):
        return {"available": False, "result": result}
    text = result["stdout"]
    return {
        "available": True,
        "task_name": task_name,
        "sha256": __import__("hashlib").sha256(text.encode("utf-8")).hexdigest(),
        "xml": text,
        "settings": _settings_from_xml(text),
    }


#: What the platform omits from an export when the value is the schema default, with that default.
#: A task's exported XML is *normalised*: an absent element is not an absent behaviour, and reading
#: "not present" as "not set" would misdescribe a task that is behaving exactly as configured.
XML_DEFAULTS: dict[str, Any] = {
    "Enabled": "true",
    "RunLevel": "LeastPrivilege",
    "AllowHardTerminate": "true",
    "WakeToRun": "false",
    "RunOnlyIfNetworkAvailable": "false",
    "Hidden": "false",
    "AllowStartOnDemand": "true",
    "Priority": "7",
    "StartWhenAvailable": "false",
}


def _settings_from_xml(xml: str) -> dict[str, Any]:
    """The task's registration, read by element path rather than by first-match text search.

    A first-match search finds whichever element the platform happened to write first: the
    repetition interval of the failure-restart policy and the repetition interval of the trigger
    are both spelled ``<Interval>``, and an audit that confuses them reports a fifteen-minute
    schedule as a five-minute one.
    """
    import xml.etree.ElementTree as ET

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    out: dict[str, Any] = {
        "settings": {},
        "principals": {},
        "trigger": {},
        "action": {},
        "explicit": [],
        "defaulted": [],
    }
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return {**out, "parse_error": repr(exc)}
    for section in root:
        name = local(section.tag)
        if name == "Principals":
            for principal in section:
                for child in principal:
                    key = local(child.tag)
                    if key in ("UserId", "LogonType", "RunLevel"):
                        out["principals"][key] = (child.text or "").strip()
                        out["explicit"].append(f"Principals/{key}")
        elif name == "Triggers":
            for trigger in section:
                for child in trigger.iter():
                    key = local(child.tag)
                    if key in ("StartBoundary", "Interval", "Duration", "Enabled"):
                        if key == "Interval" and local(child.tag) and child.text:
                            out["trigger"]["repetition_interval"] = child.text.strip()
                        else:
                            out["trigger"][key] = (child.text or "").strip()
        elif name == "Settings":
            for child in section:
                key = local(child.tag)
                if key == "RestartOnFailure":
                    out["settings"]["RestartOnFailure"] = {
                        local(grand.tag): (grand.text or "").strip() for grand in child
                    }
                    out["explicit"].append("Settings/RestartOnFailure")
                elif key == "IdleSettings":
                    out["settings"]["IdleSettings"] = {
                        local(grand.tag): (grand.text or "").strip() for grand in child
                    }
                    out["explicit"].append("Settings/IdleSettings")
                elif len(child) == 0:
                    out["settings"][key] = (child.text or "").strip()
                    out["explicit"].append(f"Settings/{key}")
        elif name == "Actions":
            for action in section:
                for child in action:
                    out["action"][local(child.tag)] = (child.text or "").strip()
    for key, value in XML_DEFAULTS.items():
        if key not in out["settings"] and key not in out["principals"] and key not in out["trigger"]:
            out["settings"].setdefault(f"{key}_defaulted", value)
            out["defaulted"].append(f"{key}={value}")
    out["reading"] = (
        "read by element path from the platform's own export; an element the platform omits is at "
        "its schema default, which is listed under *_defaulted rather than recorded as unset"
    )
    return out


def logon_mode(task_name: str) -> dict[str, Any]:
    """The operating system's own statement about how the task may run."""
    result = powershell(f"schtasks /query /tn '{task_name}' /v /fo LIST")
    fields: dict[str, str] = {}
    for line in (result.get("stdout") or "").splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    interesting = {
        key: value
        for key, value in fields.items()
        if key
        in (
            "Nombre de tarea",
            "TaskName",
            "Estado",
            "Status",
            "Modo de inicio de sesión",
            "Logon Mode",
            "Ejecutar como usuario",
            "Run As User",
            "Estado de la tarea",
            "Scheduled Task State",
            "Última hora de ejecución",
            "Last Run Time",
            "Último resultado",
            "Last Result",
            "Próxima hora de ejecución",
            "Next Run Time",
        )
    }
    return {
        "available": bool(interesting),
        "fields": interesting,
        "raw_sha256": __import__("hashlib")
        .sha256(((result.get("stdout") or "")).encode("utf-8"))
        .hexdigest(),
        "reading": (
            "the platform's own description of the task, read verbatim; the language of this host "
            "is Spanish, so the field names are the ones it prints"
        ),
        "result": {"ok": result.get("ok"), "returncode": result.get("returncode")},
    }


def resource_budget(*, lane: Path, watch: Path, store: Path) -> dict[str, Any]:
    """Measured growth against declared thresholds — and what each threshold actually does."""
    lane_budget = read_json(lane / "resource_budget.json")
    samples = lane_budget.get("samples") or []
    measured: dict[str, Any] = {}
    lane_bytes = sum(path.stat().st_size for path in lane.rglob("*") if path.is_file())
    watch_bytes = sum(path.stat().st_size for path in watch.rglob("*") if path.is_file()) if watch.is_dir() else 0
    store_bytes = sum(path.stat().st_size for path in store.rglob("*.jsonl") if path.is_file())
    bars_per_file = {
        f"{tf}:{sym}": len(read_jsonl(store / tf / f"{sym}.jsonl")) for tf, sym in SERIES
    }
    if len(samples) >= 2:
        first, last = samples[0], samples[-1]
        delta_bytes = int(last.get("bytes") or 0) - int(first.get("bytes") or 0)
        delta_seconds = (int(last.get("ts_ms") or 0) - int(first.get("ts_ms") or 0)) / 1000.0
        measured = {
            "window_seconds": round(delta_seconds, 3),
            "window_hours": round(delta_seconds / 3600.0, 3),
            "lane_growth_bytes": delta_bytes,
            "bytes_per_hour": round(delta_bytes / (delta_seconds / 3600.0), 3)
            if delta_seconds > 0
            else None,
            "bytes_per_day": round(delta_bytes / (delta_seconds / 86400.0), 3)
            if delta_seconds > 0
            else None,
        }
    disk = shutil.disk_usage(lane if lane.is_dir() else REPO_ROOT)
    return {
        "schema_version": "EDGE05_RESOURCE_BUDGET_V1",
        "generated_at_utc": stamp_ms(now_ms()),
        "measured": {
            "lane_tree_bytes": lane_bytes,
            "watchdog_tree_bytes": watch_bytes,
            "store_bytes": store_bytes,
            "store_bars": bars_per_file,
            "store_bars_total": sum(bars_per_file.values()),
            "from_the_lanes_own_samples": measured,
            "lane_samples_on_file": len(samples),
        },
        "volume": {
            "free_bytes": int(disk.free),
            "free_gib": round(disk.free / GIB, 4),
            "total_bytes": int(disk.total),
            "used_percent": round((disk.total - disk.free) / disk.total * 100, 2),
        },
        "thresholds": {
            "measured_growth": {
                "warn_bytes_per_day": 16 * 1024 * 1024,
                "stop_bytes_per_day": 64 * 1024 * 1024,
                "action": (
                    "alert an operator; nothing is deleted, and the declared 256 MiB lane budget "
                    "spread over the sixty days this lane observes is 4.37 MiB/day"
                ),
            },
            "free_space": {
                "warn_free_bytes": 5 * GIB,
                "critical_free_bytes": 2 * GIB,
                "action": (
                    "below the warning floor the lane keeps ingesting and the heavy publication "
                    "waits; below the critical floor the tick records DISK_BUDGET_EXCEEDED and "
                    "makes no market request at all"
                ),
            },
        },
        "snapshots": {
            "policy": (
                "a snapshot that would be identical to the previous one is refused and the refusal "
                "recorded; the watchdog copies its own readings, never the store"
            ),
            "store_slice_bytes": (watch / "STORE_SLICE.json").stat().st_size
            if (watch / "STORE_SLICE.json").is_file()
            else None,
        },
        "never_deleted": [
            "the forward store",
            "daily/<date>.json, the lane's durable coverage record",
            "every published report",
            "the run log, the slot ledger and the ingest ledger of the lane",
        ],
        "pruned": [
            "the lane's bounded operational logs, at their declared caps",
            "the watchdog's own readings and alerts, at its own declared caps",
        ],
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }


def windows_continuity(*, task: dict[str, Any], mode: dict[str, Any]) -> dict[str, Any]:
    settings = task.get("settings") or {}
    internals = settings.get("settings") or {}
    principals = settings.get("principals") or {}
    trigger = settings.get("trigger") or {}
    action = settings.get("action") or {}
    settings = {
        **internals,
        **{key: f"{value} (element absent: schema default)" for key, value in internals.items() if key.endswith("_defaulted")},
        "logon_type": principals.get("LogonType"),
        "run_level": principals.get("RunLevel") or "LeastPrivilege (element absent: schema default)",
        "user_id": principals.get("UserId"),
        "start_boundary": trigger.get("StartBoundary"),
        "trigger_repetition_interval": trigger.get("repetition_interval"),
        "trigger_duration": trigger.get("Duration"),
        "action_command": action.get("Command"),
        "action_arguments": action.get("Arguments"),
    }
    return {
        "schema_version": "EDGE05_WINDOWS_CONTINUITY_V1",
        "generated_at_utc": stamp_ms(now_ms()),
        "task": LANE_TASK,
        "registered_settings": settings,
        "logon_mode_as_the_platform_prints_it": mode.get("fields"),
        "what_the_platform_says_it_allows": {
            "logged_on_user_session": (
                "the task runs: the tick has been observed firing unattended on a schedule, "
                "without any agent or terminal open"
            ),
            "screen_locked_but_session_alive": (
                "EXPECTED to run — a locked screen does not end the session — and NOT EXERCISED: "
                "locking this host's screen would interrupt the person using it, so the work "
                "package records the expectation and does not measure it"
            ),
            "logged_off": (
                "does NOT run: LogonType=InteractiveToken means the task needs the user's session, "
                "and no stored credential exists for it. This is the single largest caveat on the "
                "sixty-day requirement"
            ),
            "machine_rebooted": (
                "NOT EXERCISED: a reboot would end this session and every other process on the "
                "host, which is an operator's decision and not a work package's"
            ),
            "machine_asleep": (
                "the trigger is missed and StartWhenAvailable fires it on wake; that path is "
                "declared by the registration and NOT EXERCISED here"
            ),
            "machine_off_across_several_slots": (
                "the next tick ingests every bar that closed after the store's high-water mark, so "
                "the gap is latency and not data — EXERCISED by this work package as a real "
                "scheduler outage, see OUTAGE_REHEARSAL_*.json"
            ),
        },
        "safe_unattended_modes": [
            {
                "mode": "a host that stays logged in, with the screen locked",
                "needs": "nothing beyond what is registered",
                "limitation": "a logoff, a reboot without an auto-logon, or a session that is "
                "closed ends the observation until somebody logs back in",
                "authorisation": "the owner's decision; this work package leaves it registered as it is",
            },
            {
                "mode": "run whether the user is logged on or not",
                "needs": "the account's password stored for the task, or a dedicated low-privilege "
                "service account, and the policy to allow it",
                "limitation": "a credential would have to be stored on this host; the WP was not "
                "authorised to hold one and did not",
                "authorisation": "REQUIRED — operator. The commands are in `commands_for_the_owner`",
            },
            {
                "mode": "a Linux host with systemd --user",
                "needs": "the same command under a timer, with Persistent=true",
                "limitation": "still a user session; the durable form is a system service",
                "authorisation": "not available on this host and NOT EXERCISED",
            },
        ],
        "commands_for_the_owner": [
            f"schtasks /change /tn \"{LANE_TASK}\" /ru \"<DOMAIN\\user>\" /rp \"<password>\"",
            f"schtasks /change /tn \"{WATCHDOG_TASK}\" /ru \"<DOMAIN\\user>\" /rp \"<password>\"",
            (
                "# or, from PowerShell, which also needs the password interactively:\n"
                f"$c = Get-Credential; Set-ScheduledTask -TaskName '{LANE_TASK}' -User $c.UserName "
                "-Password $c.GetNetworkCredential().Password"
            ),
        ],
        "not_applied_because": (
            "storing an account credential on this host is exactly what the security rules of this "
            "project forbid an automated agent to do; the change is spelled out for a person to "
            "make, and until it is made the sixty-day accumulation depends on the session staying "
            "alive"
        ),
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }


def timeline(*, lane: Path, watch: Path, alerts: list[dict[str, Any]]) -> str:
    runs = read_jsonl(lane / "runs.jsonl")
    checks = read_jsonl(watch / "watchdog.jsonl")
    lines = [
        "# WP-EDGE-05 — the timeline: what the lane did, what the watchdog said",
        "",
        "| instant (UTC) | actor | what it did |",
        "| --- | --- | --- |",
    ]
    rows: list[tuple[str, str, str]] = []
    for row in runs:
        rows.append(
            (
                str(row.get("finished_at_utc") or row.get("started_at_utc") or ""),
                "lane",
                f"`{row.get('outcome')}` {row.get('run_id')} · {row.get('new_bars')} new bar(s) · "
                f"{row.get('market_requests')} request(s) · slot {row.get('slot_key')}",
            )
        )
    for row in checks:
        rows.append(
            (
                str(row.get("at_utc") or ""),
                "watchdog",
                f"`{row.get('verdict')}` ({row.get('category')}) · "
                f"{'; '.join(str(item) for item in (row.get('findings') or [])) or 'no finding'}",
            )
        )
    for row in alerts:
        rows.append(
            (
                str(row.get("at_utc") or ""),
                "alert",
                f"`{row.get('kind')}` {row.get('state')} ({row.get('severity')})",
            )
        )
    for instant, actor, text in sorted(rows):
        lines.append(f"| {instant} | {actor} | {text} |")
    lines += [
        "",
        f"*{len(runs)} lane tick(s), {len(checks)} watchdog reading(s), {len(alerts)} alert(s).*",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", default=None)
    parser.add_argument("--lane-state-root", default=None)
    parser.add_argument("--watch-state-root", default=None)
    parser.add_argument("--store-root", default=None)
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)

    out = Path(options.out) if options.out else REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-05"
    lane = Path(options.lane_state_root) if options.lane_state_root else REPO_ROOT / "data" / "forward" / "edge04"
    watch = (
        Path(options.watch_state_root)
        if options.watch_state_root
        else REPO_ROOT / "data" / "forward" / "edge05"
    )
    store = Path(options.store_root) if options.store_root else REPO_ROOT / "data" / "forward" / "edge03"
    evidence_dir = out / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}

    def write_json(name: str, payload: dict[str, Any], *, directory: Path) -> None:
        path = directory / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        written[name] = path

    status = read_json(watch / "LATEST.json")
    checks = read_jsonl(watch / "watchdog.jsonl")
    alerts = read_jsonl(watch / "watch_alerts.jsonl")
    write_json(
        "EDGE05_WATCHDOG_STATUS.json",
        {
            "schema_version": "EDGE05_WATCHDOG_STATUS_V1",
            "generated_at_utc": stamp_ms(now_ms()),
            "latest": status,
            "readings_on_file": len(checks),
            "alerts_on_file": len(alerts),
            "alert_kinds": sorted({str(row.get("kind")) for row in alerts}),
            "verdicts_seen": sorted({str(row.get("verdict")) for row in checks}),
            "task": WATCHDOG_TASK,
            "watching": LANE_TASK,
            "hypothetical": True,
            "order_sent": False,
            "promotion": "NONE",
        },
        directory=out,
    )

    budget = resource_budget(lane=lane, watch=watch, store=store)
    write_json("EDGE05_RESOURCE_BUDGET.json", budget, directory=out)

    task = task_xml(LANE_TASK)
    watchdog_task = task_xml(WATCHDOG_TASK)
    mode = logon_mode(LANE_TASK)
    continuity = windows_continuity(task=task, mode=mode)
    continuity["watchdog_task"] = {
        "available": watchdog_task.get("available"),
        "settings": watchdog_task.get("settings"),
    }
    write_json("EDGE05_WINDOWS_CONTINUITY.json", continuity, directory=out)
    (out / "EDGE05_WINDOWS_CONTINUITY.md").write_text(
        render_continuity(continuity), encoding="utf-8"
    )
    written["EDGE05_WINDOWS_CONTINUITY.md"] = out / "EDGE05_WINDOWS_CONTINUITY.md"
    write_json("EDGE05_TASK_REGISTRATION.json", {"lane_task": task, "watchdog_task": watchdog_task, "logon_mode": mode}, directory=evidence_dir)

    (evidence_dir / "FASE5_TIMELINE.md").write_text(timeline(lane=lane, watch=watch, alerts=alerts), encoding="utf-8")
    written["FASE5_TIMELINE.md"] = evidence_dir / "FASE5_TIMELINE.md"

    report = read_json(watch / "reconciliation" / "RECONCILIATION.json")
    if report:
        write_json("STORE_SLICE.json", snapshot_store(report, store, lane), directory=evidence_dir)
    (watch / "STORE_SLICE.json").write_text(
        json.dumps(read_json(evidence_dir / "STORE_SLICE.json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    snapshot = {
        "schema_version": "EDGE05_EVIDENCE_SNAPSHOT_V1",
        "generated_at_utc": stamp_ms(now_ms()),
        "files": {
            name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for name, path in sorted(written.items())
        },
        "inputs": {
            "lane_state_root": str(lane),
            "watch_state_root": str(watch),
            "store_root": str(store),
        },
        "reading": (
            "every artefact this closure wrote, with its digest: the set can be checked rather "
            "than trusted, and the verifier can be pointed at this directory with the same "
            "command it uses on the live tree"
        ),
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }
    write_json("SNAPSHOT.json", snapshot, directory=evidence_dir)

    if options.json:
        print(json.dumps({"written": {k: str(v) for k, v in sorted(written.items())}}, indent=2))
    else:
        print(f"wrote {len(written)} artefact(s) into {out}")
        for name, path in sorted(written.items()):
            print(f"  {path.stat().st_size:>9}  {path}")
    return 0


def render_continuity(payload: dict[str, Any]) -> str:
    settings = payload.get("registered_settings") or {}
    lines = [
        "# WP-EDGE-05 — Windows continuity: what the host actually permits",
        "",
        f"*Task `{payload['task']}`, read from the platform's own registration. Read-only.*",
        "",
        "## The registered settings",
        "",
        "| setting | value |",
        "| --- | --- |",
    ]
    for key, value in settings.items():
        lines.append(f"| `{key}` | `{value}` |")
    lines += ["", "## What that permits, measured or declared", ""]
    for key, value in (payload.get("what_the_platform_says_it_allows") or {}).items():
        lines.append(f"* **{key.replace('_', ' ')}** — {value}")
    lines += ["", "## The safe unattended modes, and what each needs", ""]
    for mode in payload.get("safe_unattended_modes") or []:
        lines += [
            f"* **{mode['mode']}**",
            f"  * needs: {mode['needs']}",
            f"  * limitation: {mode['limitation']}",
            f"  * authorisation: {mode['authorisation']}",
        ]
    lines += [
        "",
        "## Not applied, and why",
        "",
        payload.get("not_applied_because", ""),
        "",
        "```",
        *(payload.get("commands_for_the_owner") or []),
        "```",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
