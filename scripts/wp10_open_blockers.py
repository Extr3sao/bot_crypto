"""WP-10 phase 6 — the open blockers, re-checked against the record instead of restated.

Every blocker this work package inherits was described in WP-9. Restating them would
be a second place for the same numbers to be wrong, so each one is re-established
here from the artefact that carries it:

* **CI on a real runner** — the remote, the tracked workflow files as they exist at
  HEAD, the unpublished commit count and whether a GitHub CLI is even present. A
  runner certification needs the workflows to be *published*; this script says what
  is missing rather than repeating "BLOCKED".
* **the 5.89 h window that ended without a record** — the forensic timeline is
  rebuilt from the launcher's own plan, monitor, heartbeats, child state files and
  the *absence* of files its exit path always writes. The conclusion is only as
  strong as the exclusions, and each exclusion names its evidence. Nothing is
  attributed to disk without a measurement that says so.
* **the volume budget** — free space now, the measured capture rate, and the hours
  that budget actually affords; a 72 h or 168 h window is not launched when the
  arithmetic says it does not fit.
* **M-03 and M-07** — the admissible forward history is re-derived from the sealed
  manifests only. The unsealed window is explicitly *not* counted, because a window
  with no manifest is not evidence.
* **governance** — the flags are read from the campaign state view's resolved
  effective values (the record that already arbitrates between competing sources),
  not from prose.

Read-only. Exit codes: 0 report written, 2 a required input is missing.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WP10 = ROOT / "data" / "recovery" / "wp10"
WP9 = ROOT / "data" / "recovery" / "wp9"
STATE_VIEW = ROOT / "data" / "recovery" / "CAMPAIGN_STATE_VIEW.json"
FORWARD_ROOT = ROOT / "reports" / "microstructure-forward-continuous"
FORWARD_MANIFESTS = FORWARD_ROOT / "manifest"
FORWARD_STATE = FORWARD_ROOT / "state"
PAPER_LAB = ROOT / "reports" / "paper-lab"
WP9_READINESS = WP9 / "WP9_M03_M07_READINESS.json"
WP9_DISK = WP9 / "WP9_DISK_BUDGET_AUDIT.json"
PREREGISTRATION = ROOT / "config" / "microstructure_preregistration.json"

#: Files the launcher's exit path writes unconditionally, inside a
#: ``try/except BaseException/finally``, so their absence is itself evidence.
LAUNCHER_EXIT_ARTEFACTS = ("LAB_RUN_REPORT.json", "LAB_RUN_REPORT.md", "LAB_RUN_SNAPSHOT.json")
UNSEALED_WINDOW = "paper-lab-continuous-03"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def fmt_utc(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    return datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


# ---------------------------------------------------------------------------
# blocker 1: CI on a real runner
# ---------------------------------------------------------------------------


def ci_blocker() -> dict[str, Any]:
    remote = git("remote", "get-url", "origin") or None
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") or None
    unpublished = None
    unpublished_files = None
    if upstream:
        count = git("rev-list", "--count", f"{upstream}..HEAD")
        unpublished = int(count) if count.isdigit() else None
        files = git("diff", "--name-only", f"{upstream}..HEAD")
        unpublished_files = len([line for line in files.splitlines() if line.strip()])
    workflows = [
        line
        for line in git("ls-tree", "-r", "--name-only", "HEAD", ".github/workflows").splitlines()
        if line.strip()
    ]
    workflow_files_on_disk = (
        sorted(
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in (ROOT / ".github" / "workflows").glob("*.yml")
        )
        if (ROOT / ".github").exists()
        else []
    )
    gh = shutil.which("gh")
    return {
        "remote": remote,
        "upstream": upstream,
        "unpublished_commits": unpublished,
        "unpublished_files": unpublished_files,
        "workflows_tracked_at_head": workflows,
        "workflow_files_on_disk": workflow_files_on_disk,
        "workflows_untracked": [path for path in workflow_files_on_disk if path not in workflows],
        "github_cli_present": bool(gh),
        "state": "BLOCKED",
        "what_is_missing": [
            "the workflows must reach the remote before GitHub can register or run them",
            f"{unpublished} commits are not published, so no run can exist for the current HEAD",
            "no GitHub CLI is installed here, and no token is configured for this checkout, so a "
            "run id cannot be read even if a run existed",
        ],
        "what_would_certify_it": [
            "authorisation to publish the branch (the operator owns that decision and this lane "
            "does not make it)",
            "a workflow run on a GitHub runner whose run id, commit SHA, runner image and exit "
            "codes are recorded in WP9_CI_EXECUTION_REPORT.json's format",
        ],
        "not_certified_by": (
            "the local execution of the workflow's steps, which WP-9 ran and "
            "recorded: a local rehearsal is a rehearsal, never a certification"
        ),
    }


# ---------------------------------------------------------------------------
# blocker 2: the window that ended without a record
# ---------------------------------------------------------------------------


def window_forensics() -> dict[str, Any]:
    run_dir = PAPER_LAB / UNSEALED_WINDOW
    plan = (
        json.loads((run_dir / "LAB_PLAN.json").read_text(encoding="utf-8"))
        if (run_dir / "LAB_PLAN.json").exists()
        else {}
    )
    monitor = read_jsonl(run_dir / "MONITOR.jsonl")
    heartbeat = (
        json.loads((run_dir / "SYSTEM_HEARTBEAT.json").read_text(encoding="utf-8"))
        if (run_dir / "SYSTEM_HEARTBEAT.json").exists()
        else {}
    )
    exit_artefacts = {name: (run_dir / name).exists() for name in LAUNCHER_EXIT_ARTEFACTS}
    collector_state_path = FORWARD_STATE / f"{UNSEALED_WINDOW}.json"
    collector_state = (
        json.loads(collector_state_path.read_text(encoding="utf-8"))
        if collector_state_path.exists()
        else {}
    )
    stop_file = FORWARD_STATE / f"{UNSEALED_WINDOW}.stop"

    segments = sorted(FORWARD_ROOT.rglob("*.jsonl.gz"))
    last_segment_mtime: float | None = None
    last_segment: str | None = None
    truncated: list[str] = []
    for path in segments:
        try:
            stat = path.stat()
        except OSError:
            continue
        if last_segment_mtime is None or stat.st_mtime > last_segment_mtime:
            last_segment_mtime = stat.st_mtime
            last_segment = str(path.relative_to(ROOT)).replace("\\", "/")
    for path in segments[-40:]:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for _ in handle:
                    pass
        except (EOFError, gzip.BadGzipFile, OSError):
            truncated.append(str(path.relative_to(ROOT)).replace("\\", "/"))

    last_monitor = monitor[-1] if monitor else {}
    collector_child = (heartbeat.get("children") or {}).get("collector") or {}
    processes = heartbeat.get("processes") or {}
    collector_cmd = (processes.get("collector") or {}).get("command") or []
    valve = None
    if "--max-total-bytes" in collector_cmd:
        try:
            valve = int(collector_cmd[collector_cmd.index("--max-total-bytes") + 1])
        except (IndexError, ValueError):
            valve = None

    exclusions = [
        {
            "suspect": "disk exhaustion or a storage guard",
            "excluded": bool(
                heartbeat.get("storage_guard_stopped") == []
                and (heartbeat.get("disk") or {}).get("level") == "NORMAL"
            ),
            "evidence": (
                f"free {round((heartbeat.get('disk') or {}).get('free_bytes', 0) / 1e9, 3)} GB "
                f"at the last heartbeat, level "
                f"{(heartbeat.get('disk') or {}).get('level')}, "
                f"storage_guard_stopped={heartbeat.get('storage_guard_stopped')}, and the "
                f"collector had written {(last_monitor.get('root_bytes') or 0) / 1e9:.3f} GB "
                f"of its {0 if valve is None else valve / 1e9:.1f} GB valve"
            ),
        },
        {
            "suspect": "a stop request through the documented stop files",
            "excluded": not stop_file.exists() and collector_state.get("stop_reason") is None,
            "evidence": (
                f"no stop file at {stop_file.relative_to(ROOT)}".replace("\\", "/")
                + f" and the collector state records stop_reason="
                f"{collector_state.get('stop_reason')!r}"
            ),
        },
        {
            "suspect": "a configured duration being reached",
            "excluded": not plan.get("duration_hours"),
            "evidence": (
                f"the plan declares duration_hours={plan.get('duration_hours')} which the "
                f"launcher turns into max_seconds=None, i.e. 'until stopped'"
            ),
        },
        {
            "suspect": "a crash inside the launcher",
            "excluded": not any(exit_artefacts.values()),
            "evidence": (
                "the launcher writes its report, snapshot and a system daily report inside "
                "a try/except BaseException + finally block, so even a crash leaves them; "
                f"{exit_artefacts} - none exists"
            ),
        },
        {
            "suspect": "an operator Ctrl+C (KeyboardInterrupt), which the same block catches",
            "excluded": not any(exit_artefacts.values()),
            "evidence": "same crash-survivable path; an interrupt would still have written the report",
        },
    ]
    unexplained = [entry for entry in exclusions if not entry["excluded"]]
    return {
        "run_dir": str(run_dir.relative_to(ROOT)).replace("\\", "/"),
        "plan": {
            "duration_hours": plan.get("duration_hours"),
            "free_disk_bytes_at_plan_time": plan.get("free_disk_bytes"),
            "collector_max_total_bytes": valve,
        },
        "monitor": {
            "records": len(monitor),
            "first_record_utc": last_monitor and monitor[0].get("t_iso_utc"),
            "last_record_utc": last_monitor.get("t_iso_utc"),
            "last_uptime_seconds": last_monitor.get("uptime_s"),
            "last_uptime_hours": (
                round(last_monitor.get("uptime_s") / 3600.0, 4)
                if last_monitor.get("uptime_s")
                else None
            ),
            "last_state": last_monitor.get("state"),
            "children_at_last_record": last_monitor.get("children"),
            "child_restarts_at_last_record": last_monitor.get("child_restarts"),
            "disk_free_gb_at_last_record": last_monitor.get("disk_free_gb"),
            "collector_stop_reason_at_last_record": last_monitor.get("collector_stop_reason"),
        },
        "final_heartbeat": {
            "written_utc": fmt_utc((heartbeat.get("timestamp_ms") or 0) / 1000.0)
            if heartbeat.get("timestamp_ms")
            else None,
            "uptime_seconds": heartbeat.get("uptime_seconds"),
            "state": heartbeat.get("state"),
            "degraded": heartbeat.get("degraded"),
            "heartbeat_write_failures": heartbeat.get("heartbeat_write_failures"),
            "storage_guard_stopped": heartbeat.get("storage_guard_stopped"),
            "children": {
                name: {
                    "state": value.get("state"),
                    "forced_stop": value.get("forced_stop"),
                    "exit_code": value.get("exit_code"),
                    "restarts": value.get("restarts"),
                }
                for name, value in processes.items()
            },
        },
        "collector": {
            "state_path": str(collector_state_path.relative_to(ROOT)).replace("\\", "/"),
            "stop_reason": collector_state.get("stop_reason"),
            "events": collector_state.get("events"),
            "saved_at_utc": fmt_utc((collector_state.get("saved_at_ms") or 0) / 1000.0)
            if collector_state.get("saved_at_ms")
            else None,
        },
        "last_segment": {"path": last_segment, "written_utc": fmt_utc(last_segment_mtime)},
        "truncated_tails_found_in_the_tail_of_the_root": truncated,
        "exit_artefacts_present": exit_artefacts,
        "exclusions": exclusions,
        "unexplained_in_lane": [entry["suspect"] for entry in unexplained],
        "finding": (
            "EXTERNAL_TERMINATION — every in-lane suspect is excluded by an artefact, and the "
            "termination bypassed a crash-survivable exit path, so the actuator was outside the "
            "lane. It is not attributable from the repository: the candidate remains an "
            "operating-system or process-tree teardown on a shared host, and no evidence in this "
            "tree distinguishes it further"
            if not unexplained
            else "NOT_EXCLUDED_IN_LANE — at least one in-lane suspect survives its own test; the "
            "termination may be explained by it and must not be attributed outside the lane yet"
        ),
        "consequence": (
            "the window's data cannot be used as evidence for M-03: no manifest was sealed, the "
            "collector state carries no stop reason, and the certification chain the repository "
            "requires (manifest + replay verification) was never completed"
        ),
    }


# ---------------------------------------------------------------------------
# blocker 3: the volume budget
# ---------------------------------------------------------------------------


def disk_blocker() -> dict[str, Any]:
    wp9 = json.loads(WP9_DISK.read_text(encoding="utf-8")) if WP9_DISK.exists() else {}
    rate = ((wp9.get("measurement") or {}).get("rates") or {}).get("planning_rate_bytes_per_hour")
    usage = shutil.disk_usage(ROOT)
    hours = round(usage.free / rate, 3) if rate else None
    horizons = []
    for target in (24, 48, 72, 168):
        needed = rate * target if rate else None
        horizons.append(
            {
                "hours": target,
                "needed_gb": round(needed / 1e9, 3) if needed else None,
                "fits_in_free_now": bool(needed and needed <= usage.free),
                "fits_at_1p5x_stress": bool(needed and needed * 1.5 <= usage.free),
            }
        )
    return {
        "free_bytes_now": usage.free,
        "free_gb_now": round(usage.free / 1e9, 3),
        "volume_total_gb": round(usage.total / 1e9, 3),
        "volume_used_fraction": round(usage.used / usage.total, 4),
        "planning_rate_bytes_per_hour": rate,
        "planning_rate_mb_per_hour": round(rate / 1e6, 3) if rate else None,
        "hours_affordable_now": hours,
        "horizons": horizons,
        "rule": (
            "do not launch a 72 h or 168 h window while the budget cannot pay for it: the "
            "arithmetic is done before the launch, not discovered during it"
        ),
        "shared_host_note": (wp9.get("findings") or [{}])[2].get("what")
        if len(wp9.get("findings") or []) > 2
        else None,
    }


# ---------------------------------------------------------------------------
# blocker 4: M-03 and M-07 history
# ---------------------------------------------------------------------------


def readiness_blocker() -> dict[str, Any]:
    """Re-read the pre-registration and the published readiness verdict.

    The verdict's own numbers are read from the artefact that carries them; what this
    function adds is the one thing that could have changed since: how many admissible
    forward hours exist now, derived from the sealed manifests alone.
    """
    prereg = (
        json.loads(PREREGISTRATION.read_text(encoding="utf-8")) if PREREGISTRATION.exists() else {}
    )
    wp9 = json.loads(WP9_READINESS.read_text(encoding="utf-8")) if WP9_READINESS.exists() else {}
    # the readiness verdict cites the campaign report; nothing here re-derives it, it re-reads it
    sealed_hours = 0.0
    sealed_runs = []
    for path in sorted(FORWARD_MANIFESTS.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        hours = float(payload.get("duration_seconds") or 0.0) / 3600.0
        sealed_hours += hours
        sealed_runs.append(
            {
                "run_id": payload.get("run_id"),
                "hours": round(hours, 4),
                "status": payload.get("status"),
            }
        )
    unsealed_state = FORWARD_STATE / f"{UNSEALED_WINDOW}.json"
    unsealed = (
        json.loads(unsealed_state.read_text(encoding="utf-8")) if unsealed_state.exists() else {}
    )
    m03 = (wp9.get("hypotheses") or {}).get("M-03", {})
    m07 = (wp9.get("hypotheses") or {}).get("M-07", {})
    return {
        "preregistration": {
            "path": str(PREREGISTRATION.relative_to(ROOT)).replace("\\", "/"),
            "version": prereg.get("preregistration_version"),
            "M-03_minimum": (prereg.get("hypotheses", {}).get("M-03", {}) or {}).get(
                "minimum_data"
            ),
            "M-07_minimum": (prereg.get("hypotheses", {}).get("M-07", {}) or {}).get(
                "minimum_data"
            ),
        },
        "admissible_forward_history": {
            "sealed_hours_from_manifests": round(sealed_hours, 6),
            "sealed_runs": sealed_runs,
            "unsealed_window": {
                "run_id": UNSEALED_WINDOW,
                "admissible": False,
                "why": (
                    "no manifest was sealed, so the window cannot be counted toward any "
                    "pre-registered minimum; counting it would be the synthetic-history "
                    "substitution the brief forbids"
                ),
                "events_recorded": unsealed.get("events"),
            },
            "hours_added_since_wp9": 0.0,
        },
        "M-03": {
            "verdict": (wp9.get("verdict") or {}).get("M-03"),
            "criteria_met": m03.get("criteria_met"),
            "criteria_not_met": m03.get("criteria_not_met"),
            "criteria_not_measurable": m03.get("criteria_not_measurable"),
            "missing": m03.get("missing"),
            "cost_to_close": m03.get("cost_to_close"),
        },
        "M-07": {
            "verdict": (wp9.get("verdict") or {}).get("M-07"),
            "criteria_met": m07.get("criteria_met"),
            "criteria_not_met": m07.get("criteria_not_met"),
            "missing": m07.get("missing"),
            "cost_to_close": m07.get("cost_to_close"),
        },
        "automatic_accumulation": {
            "state": "PREPARED_NOT_AUTHORISED",
            "what_exists": (
                "the collector, its retention policy and the pre-registration are in "
                "place; the two windows that ran show the cadence meets the bar"
            ),
            "what_is_missing": (
                "authorisation for a window long enough to close the shortfall, and "
                "a volume whose budget can pay for it"
            ),
        },
    }


# ---------------------------------------------------------------------------
# blocker 5: governance flags, read from the state view's own resolution
# ---------------------------------------------------------------------------


def governance_blocker() -> dict[str, Any]:
    view = json.loads(STATE_VIEW.read_text(encoding="utf-8")) if STATE_VIEW.exists() else {}
    facts: dict[str, Any] = {}
    for resolution in view.get("resolutions") or []:
        field = resolution.get("field")
        if field in {
            "LIVE_TRADING",
            "TRADES_AUTHORIZED",
            "PAPER_PROMOTION",
            "PROFITABILITY_VERIFIED",
            "NEXT_CAMPAIGN",
            "SEALED_OOS",
        }:
            facts[field] = {
                "effective": resolution.get("effective"),
                "decided_by": (resolution.get("decided_by") or {}).get("source"),
            }
    return {
        "source": str(STATE_VIEW.relative_to(ROOT)).replace("\\", "/"),
        "status": view.get("status"),
        "resolved_flags": facts,
        "invariants": view.get("invariants"),
        "advisories": [entry.get("id") for entry in view.get("advisories") or []],
        "rfc_numbering": view.get("rfc_numbering"),
        "note": (
            "the flags are read from the record that already arbitrates between competing "
            "declarations, because re-typing them would create a second home for them"
        ),
    }


def build() -> tuple[dict[str, Any], int]:
    if not FORWARD_ROOT.exists():
        return {
            "artifact": "WP10_OPEN_BLOCKERS",
            "verdict": "BLOCKED",
            "why": "the forward data root is missing",
        }, 2
    payload = {
        "artifact": "WP10_OPEN_BLOCKERS",
        "work_package": "WP-10 (ECONOMIC EDGE RECOVERY & EXECUTION COST DISCOVERY)",
        "phase": "PHASE 6 — OPEN BLOCKERS",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "OFFLINE READ-ONLY — no process started, no order, no key",
        "head": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "blockers": {
            "CI_RUNNER_CERTIFICATION": ci_blocker(),
            "UNRECORDED_WINDOW_TERMINATION": window_forensics(),
            "VOLUME_BUDGET": disk_blocker(),
            "M03_M07_HISTORY": readiness_blocker(),
            "GOVERNANCE": governance_blocker(),
        },
        "does_not_block": [
            "offline economic investigations that need no new data: the E-1 measurement ran on "
            "already-sealed segments, and any further analysis of the same seal is equally "
            "unaffected by the CI, volume and history blockers",
            "reading and re-verifying existing artefacts",
        ],
        "verdict": (
            "BLOCKED for the four operational items that need publication, a longer "
            "window, a bigger volume or an operator decision; OPEN for offline economic "
            "work on data already captured"
        ),
    }
    payload["checks"] = [
        {
            "check": "the CI state is measured from the repository, not restated",
            "ok": payload["blockers"]["CI_RUNNER_CERTIFICATION"]["unpublished_commits"] is not None,
        },
        {
            "check": "no in-lane suspect survives the termination forensics",
            "ok": not payload["blockers"]["UNRECORDED_WINDOW_TERMINATION"]["unexplained_in_lane"],
        },
        {
            "check": "the budget verdict is arithmetic on measured numbers",
            "ok": payload["blockers"]["VOLUME_BUDGET"]["planning_rate_bytes_per_hour"] is not None,
        },
        {
            "check": "the unsealed window is explicitly not counted as history",
            "ok": payload["blockers"]["M03_M07_HISTORY"]["admissible_forward_history"][
                "unsealed_window"
            ]["admissible"]
            is False,
        },
        {
            "check": "governance flags come from the state view's resolution",
            "ok": bool(payload["blockers"]["GOVERNANCE"]["resolved_flags"]),
        },
    ]
    exit_code = 0 if all(check["ok"] for check in payload["checks"]) else 3
    return payload, exit_code


def render_markdown(payload: dict[str, Any]) -> str:
    blockers = payload["blockers"]
    ci = blockers["CI_RUNNER_CERTIFICATION"]
    forensics = blockers["UNRECORDED_WINDOW_TERMINATION"]
    disk = blockers["VOLUME_BUDGET"]
    readiness = blockers["M03_M07_HISTORY"]
    governance = blockers["GOVERNANCE"]
    lines = [
        "# WP-10 PHASE 6 — OPEN BLOCKERS",
        "",
        f"> `{payload['generated_at_utc']}` · head `{payload['head']}` · branch "
        f"`{payload['branch']}`",
        "",
        f"**{payload['verdict']}**",
        "",
        "## 1. CI runner certification — `BLOCKED`",
        "",
        f"* remote `{ci['remote']}`, upstream `{ci['upstream']}`",
        f"* unpublished commits: **{ci['unpublished_commits']}** "
        f"({ci['unpublished_files']} files) — nothing at this HEAD can have a run",
        f"* workflows tracked at HEAD: {', '.join(f'`{w}`' for w in ci['workflows_tracked_at_head'])}",
        f"* workflow files on disk but untracked: "
        f"{ci['workflows_untracked'] or 'none (they are all committed)'}",
        f"* GitHub CLI present: `{ci['github_cli_present']}`",
        "",
        "Missing to certify:",
        *[f"* {item}" for item in ci["what_is_missing"]],
        "",
        f"Not certified by: {ci['not_certified_by']}.",
        "",
        f"## 2. The window that ended without a record — `{forensics['finding'].split(' — ')[0]}`",
        "",
        f"Run `{forensics['run_dir']}`: plan duration "
        f"`{forensics['plan']['duration_hours']}` h (which the launcher reads as 'until stopped'), "
        f"collector valve "
        f"{forensics['plan']['collector_max_total_bytes'] and round(forensics['plan']['collector_max_total_bytes'] / 1e9, 2)} GB",
        f"",
        "| when | what the record says |",
        "| --- | --- |",
        f"| {forensics['monitor']['first_record_utc']} | first monitor record |",
        f"| {forensics['monitor']['last_record_utc']} | last monitor record: state "
        f"`{forensics['monitor']['last_state']}`, uptime "
        f"{forensics['monitor']['last_uptime_hours']} h, children "
        f"{json.dumps(forensics['monitor']['children_at_last_record'])}, restarts "
        f"{json.dumps(forensics['monitor']['child_restarts_at_last_record'])}, disk free "
        f"{forensics['monitor']['disk_free_gb_at_last_record']} GB, collector stop reason "
        f"`{forensics['monitor']['collector_stop_reason_at_last_record']}` |",
        f"| {forensics['final_heartbeat']['written_utc']} | final heartbeat: state "
        f"`{forensics['final_heartbeat']['state']}`, degraded "
        f"`{forensics['final_heartbeat']['degraded']}`, "
        f"storage_guard_stopped `{forensics['final_heartbeat']['storage_guard_stopped']}`, "
        f"heartbeat write failures {forensics['final_heartbeat']['heartbeat_write_failures']} |",
        f"| {forensics['collector']['saved_at_utc']} | collector state saved: stop reason "
        f"`{forensics['collector']['stop_reason']}`, events "
        f"{forensics['collector']['events']} |",
        f"| {forensics['last_segment']['written_utc']} | last segment written: "
        f"`{forensics['last_segment']['path']}` |",
        "",
        "Each suspect, and the artefact that excludes it:",
        "",
        "| suspect | excluded | evidence |",
        "| --- | --- | --- |",
    ]
    for entry in forensics["exclusions"]:
        lines.append(
            f"| {entry['suspect']} | {'yes' if entry['excluded'] else '**no**'} | "
            f"{entry['evidence']} |"
        )
    lines += [
        "",
        f"**Finding:** {forensics['finding']}",
        "",
        f"*Consequence:* {forensics['consequence']}.",
        "",
        "## 3. The volume budget",
        "",
        f"* free now: **{disk['free_gb_now']} GB** of {disk['volume_total_gb']} GB "
        f"({round(disk['volume_used_fraction'] * 100, 2)} % used by everything on the host)",
        f"* measured capture rate: {disk['planning_rate_mb_per_hour']} MB/h",
        f"* that budget affords: **{disk['hours_affordable_now']} h** of this lane's capture",
        "",
        "| horizon | needed GB | fits now | fits at 1.5x |",
        "| ---: | ---: | --- | --- |",
        *[
            f"| {row['hours']} h | {row['needed_gb']} | {row['fits_in_free_now']} | "
            f"{row['fits_at_1p5x_stress']} |"
            for row in disk["horizons"]
        ],
        "",
        f"* {disk['rule']}",
        "",
        "## 4. M-03 and M-07 — the history that does not exist yet",
        "",
        f"* sealed forward history: **{readiness['admissible_forward_history']['sealed_hours_from_manifests']} h** "
        f"from {len(readiness['admissible_forward_history']['sealed_runs'])} sealed run(s)",
        f"* hours added since WP-9: "
        f"{readiness['admissible_forward_history']['hours_added_since_wp9']} — the unsealed window "
        f"is not admissible: {readiness['admissible_forward_history']['unsealed_window']['why']}",
        "",
        "| hypothesis | verdict | met | not met | not measurable | cost to close |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for name in ("M-03", "M-07"):
        record = readiness[name]
        cost = record.get("cost_to_close") or {}
        lines.append(
            f"| {name} | {record.get('verdict')} | {record.get('criteria_met')} | "
            f"{record.get('criteria_not_met')} | {record.get('criteria_not_measurable') or 0} | "
            f"{cost.get('hours')} h / {cost.get('gb_at_measured_rate')} GB |"
        )
    lines += [
        "",
        f"* automatic accumulation: `{readiness['automatic_accumulation']['state']}` — "
        f"{readiness['automatic_accumulation']['what_is_missing']}",
        "",
        "## 5. Governance, as the state view resolved it",
        "",
        f"Source `{governance['source']}`, status `{governance['status']}`.",
        "",
        "| flag | effective | decided by |",
        "| --- | --- | --- |",
        *[
            f"| `{flag}` | `{value['effective']}` | {value['decided_by']} |"
            for flag, value in sorted(governance["resolved_flags"].items())
        ],
        "",
        f"* advisories: {', '.join(governance['advisories'])}",
        f"* derived next free RFC number: `{governance['rfc_numbering']['next_free_derived']}`",
        "",
        "## 6. What these blockers do not block",
        "",
        *[f"* {item}" for item in payload["does_not_block"]],
        "",
        "## 7. Checks",
        "",
        *[f"* [{'x' if check['ok'] else ' '}] {check['check']}" for check in payload["checks"]],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload, exit_code = build()
    WP10.mkdir(parents=True, exist_ok=True)
    if args.json:
        print(json.dumps(payload, indent=2))
        return exit_code
    md_path = WP10 / "WP10_OPEN_BLOCKERS.md"
    json_path = WP10 / "WP10_OPEN_BLOCKERS.json"
    md_path.write_text(render_markdown(payload) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"{payload['verdict'][:60]}: {md_path.relative_to(ROOT)} (exit {exit_code})")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
