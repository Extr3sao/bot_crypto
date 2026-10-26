"""One operator-shaped status for the whole PAPER lab (§19, §26, §29, §58).

Three planes write three different kinds of artifact: PAPER writes a heartbeat and
a state file, the collector writes a resume state that doubles as a live
heartbeat, and the strategy lab writes a report. Reading them one at a time is
how an operator ends up not reading them at all.

This module folds them into a single payload with the questions an operator
actually asks — is it running, since when, what has it done, is the disk going to
run out, and what is the last error — and reports the four readiness verdicts
(§58) *separately*, because "PAPER is fine" and "the collector is fine" are
independent facts and a single green light would hide the difference.

It is deliberately read-only: every function here reads files and takes the
system's current state as it is. Nothing in it can start, stop, or change the
lab, which is what makes it safe to run it from a dashboard.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from trading_bot.autonomous.paper_loop import STOP_FILE_NAME
from trading_bot.autonomous.supervisor import (
    DEFAULT_DISK_THRESHOLDS,
    DiskLevel,
    DiskThresholds,
    ProcessState,
    disk_free_bytes,
)

__all__ = [
    "STATUS_SCHEMA",
    "allow_tolerant_console_output",
    "build_status",
    "latest_lab_run",
    "read_json",
]

STATUS_SCHEMA = "paper-lab-status-v1"

#: A child that has not published a heartbeat for this long is not "running" with
#: any confidence, whatever its process table entry says.
STALE_HEARTBEAT_SECONDS = 180.0


def read_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON object, or ``None``. A missing artifact is a finding, not a crash."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def latest_lab_run(lab_root: Path | str) -> Path | None:
    """The newest run directory that actually looks like a lab run."""
    root = Path(lab_root)
    if not root.exists():
        return None
    candidates = [
        path
        for path in root.iterdir()
        if path.is_dir()
        and (
            (path / "LAB_PLAN.json").exists()
            or (path / "SYSTEM_HEARTBEAT.json").exists()
            or (path / "LAB_RUN_REPORT.json").exists()
        )
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


#: How long a process table may be reused. One ``tasklist`` spawn costs ~0.3 s on
#: Windows, and the console asks about every child (twice: existence and image), so
#: on 2026-10-26 ``GET /healthz`` measured 12.8 s for 25 spawns. Identities do not
#: change inside a refresh, and an entry is at most this old.
PROCESS_TABLE_TTL_SECONDS: Final[float] = 2.0
_PROCESS_TABLE: dict[str, Any] = {"at": 0.0, "table": None}


def _windows_process_table(now: float) -> dict[int, str] | None:
    """``pid -> image`` for every process, from a single ``tasklist`` call.

    ``None`` means the probe could not answer; blindness is never cached, so the
    next caller looks again instead of inheriting a failed look.
    """
    cached = _PROCESS_TABLE.get("table")
    if cached is not None and now - float(_PROCESS_TABLE.get("at") or 0.0) <= PROCESS_TABLE_TTL_SECONDS:
        return cached
    try:
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - platform
        return None
    table: dict[int, str] = {}
    for line in (completed.stdout or "").splitlines():
        parts = [part.strip().strip('"') for part in line.split('","')]
        if len(parts) < 2:
            continue
        try:
            identifier = int(parts[1])
        except ValueError:
            continue
        table[identifier] = parts[0].lstrip('"').lower()
    if not table:
        return None
    _PROCESS_TABLE["at"] = now
    _PROCESS_TABLE["table"] = table
    return table


def process_image(pid: int | None) -> str | None:
    """Best-effort executable image name for a live PID, lower-cased.

    ``None`` means the probe could not answer (dead PID, unreadable tables, an
    unsupported platform). This is the identity half of liveness: a PID that
    exists is not the same thing as *this child* existing — Windows reuses PIDs,
    so ``svchost.exe`` can legitimately own a number a stopped child once had.
    """
    if pid is None or pid <= 0:
        return None
    if sys.platform.startswith("win"):
        table = _windows_process_table(time.monotonic())
        if table is None:
            return None
        return table.get(pid)
    try:
        comm = Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
    except OSError:  # pragma: no cover - platform dependent
        return None
    return comm.lower() or None


def _image_matches(expected: str | None, actual: str | None) -> bool | None:
    """``None`` when identity cannot be established (never claim a mismatch)."""
    if not expected or actual is None:
        return None
    return expected.lower() == actual.lower()


def pid_reused(pid: int | None, *, expected_image: str | None) -> bool:
    """True when the live PID now belongs to a different program than expected."""
    if pid is None or not expected_image:
        return False
    if process_alive(pid) is not True:
        return False
    return _image_matches(expected_image, process_image(pid)) is False


def process_alive(pid: int | None, *, expected_image: str | None = None) -> bool | None:
    """Best-effort liveness for a PID. ``None`` means "could not be determined".

    ``os.kill(pid, 0)`` does not exist on Windows, so the platform probe is used
    and a failure to probe is reported as unknown rather than as death: inferring
    a crash from our own inability to look would be the worst possible error in an
    operator console.

    When ``expected_image`` is supplied, a PID that exists but is running a
    *different* executable is reported as not alive (PID reuse, DEF-PID-REUSE-001)
    rather than as a healthy child. If the image cannot be read, the PID is left
    as alive/unknown — we never invent death from our own blindness.
    """
    if pid is None:
        return None
    if sys.platform.startswith("win"):
        table = _windows_process_table(time.monotonic())
        if table is None:
            return None
        exists: bool | None = pid in table
    else:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            exists = False
        except PermissionError:  # pragma: no cover - another user's process
            exists = True
        except OSError:  # pragma: no cover - platform dependent
            return None
        else:
            exists = True
    if not exists:
        return False
    return _image_matches(expected_image, process_image(pid)) is not False


def _age_seconds(stamp_ms: Any, *, now_ms: int) -> float | None:
    """Seconds since a timestamp, clamped at zero.

    A child that writes its heartbeat *while* this is being assembled produces a
    stamp a moment in the future; reporting a negative age would be a confusing
    way to say "current".
    """
    try:
        value = int(stamp_ms)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, (now_ms - value) / 1000.0), 3)


def _plan_forward_root(plan: dict[str, Any]) -> Path | None:
    """Where the capture writes, read out of the plan's own collector command."""
    for entry in plan.get("processes") or []:
        if entry.get("name") != "collector":
            continue
        command = [str(part) for part in entry.get("command") or []]
        for flag in ("--data-root", "--out"):
            if flag in command:
                index = command.index(flag)
                if index + 1 < len(command):
                    return Path(command[index + 1])
    return None


def _read_log_text(path: Path) -> str:
    """Read a child's log without inventing characters and without raising.

    A child's log is *not* reliably one encoding: its stdout is a redirected
    file handle, which on Windows uses the console code page, while the JSON
    artifacts the same child writes are UTF-8. Reading a cp1252 log as UTF-8
    with ``errors="replace"`` puts U+FFFD into the payload — a character nobody
    asked for and one a cp1252 console cannot print, so the operator's own
    status command dies with a ``UnicodeEncodeError``. Try the encodings the
    child could actually have used, strictly, and only then degrade.
    """
    raw = path.read_bytes()
    for encoding in ("utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def allow_tolerant_console_output() -> None:
    """§26 — the operator console must not be able to turn into a traceback.

    These payloads legitimately carry non-ASCII (a stop report's note cites the
    operations manual, and a log line is whatever the child printed). A code
    page that cannot represent one character must degrade that character, not
    kill the one command an operator reaches for mid-incident.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # pragma: no cover - not a TextIOWrapper
            continue
        with contextlib.suppress(Exception):
            reconfigure(errors="replace")


def _last_log_error(run_dir: Path, name: str) -> dict[str, Any] | None:
    """The last line of a child's log that looks like a failure, if any."""
    path = run_dir / "logs" / f"{name}.log"
    if not path.exists():
        return None
    try:
        tail = _read_log_text(path).splitlines()[-400:]
    except OSError:  # pragma: no cover - the file vanished under us
        return None
    markers = ("Traceback", "ERROR", "Error:", "refusing", "FAILED", "exception")
    for line in reversed(tail):
        if any(marker in line for marker in markers):
            return {"line": line.strip()[:400], "at": None}
    return None


@dataclass(frozen=True, slots=True)
class _PaperHeartbeat:
    payload: dict[str, Any] | None
    age_seconds: float | None


def _paper_heartbeat(paper_root: Path, run_id: str, *, now_ms: int) -> _PaperHeartbeat:
    candidates = [
        paper_root / run_id / "heartbeat.json",
        paper_root / run_id / "HEARTBEAT.json",
    ]
    for path in candidates:
        payload = read_json(path)
        if payload is not None:
            return _PaperHeartbeat(
                payload=payload,
                age_seconds=_age_seconds(payload.get("timestamp_ms"), now_ms=now_ms),
            )
    return _PaperHeartbeat(payload=None, age_seconds=None)


def _disk_status(run_dir: Path, thresholds: DiskThresholds, *, now_ms: int) -> dict[str, Any]:
    free = disk_free_bytes(run_dir if run_dir.exists() else Path.cwd())
    level = thresholds.level_for(free)
    report = read_json(run_dir / "reports" / "RETENTION_REPORT.json")
    rate_bytes_per_day: float | None = None
    if report:
        policy = report.get("policy") or {}
        capacity = report.get("capacity") or {}
        for key in ("compressed_bytes_per_day", "bytes_per_day"):
            value = capacity.get(key) or policy.get(key)
            if isinstance(value, (int, float)) and value > 0:
                rate_bytes_per_day = float(value)
                break
    hours_remaining: float | None = None
    if rate_bytes_per_day and rate_bytes_per_day > 0:
        per_hour = rate_bytes_per_day / 24.0
        hours_remaining = round(max(0.0, (free - thresholds.stop_bytes) / per_hour), 2)
    guidance = {
        DiskLevel.NORMAL: "no action",
        DiskLevel.WARNING: "watch: retention should be reclaiming faster than this",
        DiskLevel.CRITICAL: "stop the lab at the next safe point, or point --data-root elsewhere",
        DiskLevel.STOP: "the collector's guard will stop the capture; move the data root",
    }[level]
    return {
        "free_bytes": free,
        "free_gb": round(free / 1e9, 3),
        "level": level.value,
        "thresholds": thresholds.as_dict(),
        "guidance": guidance,
        "consumption_bytes_per_day": rate_bytes_per_day,
        "consumption_gb_per_day": (
            None if rate_bytes_per_day is None else round(rate_bytes_per_day / 1e9, 3)
        ),
        "estimated_hours_remaining": hours_remaining,
        "checked_at_ms": now_ms,
    }


def _collector_status(forward_root: Path | None, run_id: str, *, now_ms: int) -> dict[str, Any]:
    if forward_root is None:
        return {"available": False, "reason": "no capture root declared in the plan"}
    state = read_json(forward_root / "state" / f"{run_id}.json")
    report = read_json(forward_root / "reports" / "RETENTION_REPORT.json")
    manifest = read_json(forward_root / "manifest" / f"{run_id}.json")
    segment_bytes = 0
    segments = 0
    for path in (forward_root / "segments").rglob("*.jsonl*"):
        segments += 1
        try:
            segment_bytes += path.stat().st_size
        except OSError:  # pragma: no cover
            continue
    payload: dict[str, Any] = {
        "available": forward_root.exists(),
        "root": str(forward_root),
        "state_age_seconds": (
            None if state is None else _age_seconds(state.get("saved_at_ms"), now_ms=now_ms)
        ),
        "events": None if state is None else state.get("events"),
        "gaps": None if state is None else state.get("gaps"),
        "reconnects": None if state is None else state.get("reconnects"),
        "resnapshots": None if state is None else state.get("resnapshots"),
        "segments_on_disk": segments,
        "segment_bytes": segment_bytes,
        "segment_gb": round(segment_bytes / 1e9, 3),
        "stop_reason": None if state is None else state.get("stop_reason"),
        "fatal_failure": None if state is None else state.get("fatal_failure"),
        "manifest": (
            None
            if manifest is None
            else {
                "status": manifest.get("status"),
                "failure_kind": manifest.get("failure_kind"),
                "continuity": manifest.get("continuity"),
                "duration_seconds": manifest.get("duration_seconds"),
                "fingerprints": len(manifest.get("fingerprints") or []),
            }
        ),
    }
    if report:
        result = report.get("result") or {}
        payload["retention"] = {
            "deletion_enabled": report.get("deletion_enabled"),
            "compacted_windows": report.get("compacted"),
            "deleted_segments": report.get("deleted"),
            "freed_bytes": report.get("freed_bytes"),
            "preservation": (result.get("preservation") or [])[-1:],
        }
        payload["tiers"] = report.get("tiers")
    return payload


def _strategy_status(run_dir: Path) -> dict[str, Any]:
    report = read_json(run_dir / "STRATEGY_LAB_REPORT.json")
    if report is None:
        return {"available": False}
    # ``ledger`` is the *path* of the admission ledger the lab read, so the counts
    # come from the histogram and the lifecycle, never invented here.
    histogram = report.get("status_histogram") or {}
    lifecycle = report.get("lifecycle") or {}
    return {
        "available": True,
        "timestamp_ms": report.get("timestamp_ms"),
        "strategies_total": report.get("strategies_total"),
        "status_histogram": histogram,
        "strategies_not_paper_executable": report.get("strategies_not_paper_executable"),
        "ledger_path": report.get("ledger"),
        "admitted_for_paper": histogram.get("PAPER_ACTIVE", 0)
        + histogram.get("PAPER_CANDIDATE", 0),
        "paper_candidates": lifecycle.get("PAPER_CANDIDATE"),
        "paper_active": lifecycle.get("PAPER_ACTIVE"),
        "lifecycle": lifecycle,
        "all_checks_ok": report.get("all_checks_ok"),
        "research_cannot_change_a_running_strategy": report.get(
            "research_cannot_change_a_running_strategy"
        ),
    }


def _readiness_status(quality_path: Path, preregistration_path: Path) -> dict[str, Any]:
    quality = read_json(quality_path)
    readiness = (quality or {}).get("readiness")
    preregistration = read_json(preregistration_path) or {}
    hypotheses = preregistration.get("hypotheses") or {}
    out: dict[str, Any] = {
        "source": str(quality_path),
        "preregistration_version": preregistration.get("preregistration_version"),
        "not_yet_run": preregistration.get("not_yet_run"),
    }
    for name in ("M-03", "M-07"):
        measured = (readiness or {}).get(name) if isinstance(readiness, dict) else None
        out[name] = {
            "verdict": (measured or {}).get("verdict"),
            "state": (hypotheses.get(name) or {}).get("state"),
            "blocking": (measured or {}).get("blocking"),
            "collector_running_is_not_readiness": (
                "readiness is derived from coverage, quality and history in the "
                "quality report; a running collector is not evidence on its own"
            ),
        }
    if not isinstance(readiness, dict):
        out["note"] = (
            "no quality report under this root yet; readiness is unknown rather than "
            "assumed"
        )
    return out


def build_status(
    *,
    lab_root: Path | str = "reports/paper-lab",
    run_id: str | None = None,
    paper_root: Path | str = "reports/autonomous-paper",
    thresholds: DiskThresholds | None = None,
    quality_path: Path | str = "docs/FORWARD_DATA_QUALITY_REPORT.json",
    preregistration_path: Path | str = "config/microstructure_preregistration.json",
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Fold every plane into one read-only payload (§26, §58)."""
    now = int(time.time() * 1000) if now_ms is None else now_ms
    limits = thresholds or DEFAULT_DISK_THRESHOLDS
    lab = Path(lab_root)
    run_dir = (lab / run_id) if run_id else latest_lab_run(lab)
    payload: dict[str, Any] = {
        "schema_version": STATUS_SCHEMA,
        "generated_at_ms": now,
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now / 1000)),
        "mode": "PAPER",
        "live_control": False,
        "read_only": True,
        "run_id": None if run_dir is None else run_dir.name,
        "run_dir": None if run_dir is None else str(run_dir),
        "errors": [],
        "planes": {},
    }
    if run_dir is None:
        payload["errors"].append(f"no lab run found under {lab}")
        payload["system"] = {"state": "ABSENT", "running": False}
        payload["children"] = {}
        payload["disk"] = _disk_status(Path("."), limits, now_ms=now)
        payload["paper"] = {"available": False}
        payload["collector"] = {"available": False}
        payload["strategy_lab"] = {"available": False}
        payload["readiness"] = _readiness_status(Path(quality_path), Path(preregistration_path))
        payload["readiness_flags"] = _readiness_flags(payload)
        return payload

    plan = read_json(run_dir / "LAB_PLAN.json") or {}
    heartbeat = read_json(run_dir / "SYSTEM_HEARTBEAT.json") or {}
    report = read_json(run_dir / "LAB_RUN_REPORT.json")
    state = read_json(run_dir / "paper_state.json") or {}
    forward_root = _plan_forward_root(plan)
    resolved_run_id = run_dir.name
    paper_hb = _paper_heartbeat(Path(paper_root), resolved_run_id, now_ms=now)

    # The plan declares each child's executable; using it as the expected image
    # is what turns "a PID with this number exists" into "this child exists"
    # (DEF-PID-REUSE-001). Without it, a recycled PID (svchost.exe) reads alive.
    expected_images: dict[str, str] = {}
    for entry in plan.get("processes") or []:
        command = entry.get("command") or []
        if command:
            expected_images[str(entry.get("name"))] = Path(str(command[0])).name.lower()

    children: dict[str, Any] = {}
    for name, runtime in (heartbeat.get("processes") or {}).items():
        pid = runtime.get("pid")
        expected_image = expected_images.get(name)
        alive = process_alive(pid, expected_image=expected_image)
        last_error = runtime.get("failure_reason") or _last_log_error(run_dir, name)
        stop_file = (plan.get("graceful_stop") or {}).get("stop_files", {}).get(name)
        if stop_file is None:
            for entry in plan.get("processes") or []:
                if entry.get("name") == name:
                    stop_file = entry.get("stop_file")
                    break
        children[name] = {
            "state": runtime.get("state"),
            "critical": runtime.get("critical"),
            "pid": pid,
            "alive": alive,
            "pid_reused": pid_reused(pid, expected_image=expected_image),
            "expected_image": expected_image,
            "uptime_seconds": runtime.get("uptime_seconds"),
            "restarts": runtime.get("restarts"),
            "exit_code": runtime.get("exit_code"),
            "forced_stop": runtime.get("forced_stop"),
            "failure_reason": runtime.get("failure_reason"),
            "last_error": last_error,
            "last_log_error": _last_log_error(run_dir, name),
            "stop_file": stop_file,
        }

    paper_payload: dict[str, Any] = {
        "available": paper_hb.payload is not None,
        "heartbeat_age_seconds": paper_hb.age_seconds,
        "state_path": str(run_dir / "paper_state.json"),
        "state_age_seconds": _age_seconds(state.get("saved_at_ms"), now_ms=now),
        "mode": state.get("mode"),
    }
    if paper_hb.payload:
        hb = paper_hb.payload
        paper_payload.update(
            {
                "cycle": hb.get("cycle"),
                "uptime_seconds": hb.get("uptime_seconds"),
                "assets": hb.get("assets"),
                "timeframe": hb.get("timeframe"),
                "strategies_evaluated": hb.get("strategies_evaluated"),
                "decisions": hb.get("decisions"),
                "no_trade": hb.get("no_trade"),
                "no_trade_kinds": hb.get("no_trade_kinds"),
                "paper_trades": hb.get("paper_trades"),
                "shadow_trades": hb.get("shadow_trades"),
                "risk_vetoes": hb.get("risk_vetoes"),
                "runtime_failures": hb.get("runtime_failures"),
                "errors": hb.get("errors"),
                "paper_candidates": hb.get("paper_candidates"),
                "canonical_clock_lock": hb.get("canonical_clock_lock"),
            }
        )
    collector_payload = _collector_status(forward_root, resolved_run_id, now_ms=now)

    heartbeat_source = run_dir / "SYSTEM_HEARTBEAT.json"
    system_age = None
    if heartbeat:
        system_age = _age_seconds(heartbeat.get("timestamp_ms"), now_ms=now)
    system_state = heartbeat.get("state") or "UNKNOWN"
    running = any(
        child.get("state") == ProcessState.RUNNING.value and child.get("alive") is not False
        for child in children.values()
    )
    stale = system_age is not None and system_age > STALE_HEARTBEAT_SECONDS
    if not running and report is not None:
        system_state = report.get("final_state") or system_state
    payload.update(
        {
            "system": {
                "state": system_state,
                "running": running,
                "heartbeat_path": str(heartbeat_source),
                "heartbeat_age_seconds": system_age,
                "heartbeat_is_stale": stale,
                "uptime_seconds": heartbeat.get("uptime_seconds"),
                "restarts": sum(
                    int(child.get("restarts") or 0) for child in children.values()
                ),
                "memory_mb": heartbeat.get("memory_mb"),
                "stop_requested": (run_dir / STOP_FILE_NAME).exists(),
                "stale_heartbeat_note": (
                    "a heartbeat older than "
                    f"{STALE_HEARTBEAT_SECONDS:.0f}s is reported as stale rather than as "
                    "healthy: the last thing a crashed lab does is stop updating"
                ),
            },
            "children": children,
            "disk": _disk_status(run_dir, limits, now_ms=now),
            "paper": paper_payload,
            "collector": collector_payload,
            "strategy_lab": _strategy_status(run_dir),
            "retention": (heartbeat.get("stop_report") or None),
            "stop_report": heartbeat.get("stop_report"),
            "run_report": (
                None
                if report is None
                else {
                    "stop_reason": report.get("stop_reason"),
                    "final_state": report.get("final_state"),
                    "duration_seconds": report.get("duration_seconds"),
                    "ended_at_ms": report.get("ended_at_ms"),
                }
            ),
            "plan": {
                "duration_hours": plan.get("duration_hours"),
                "retention": plan.get("retention"),
                "collector_resume": plan.get("collector_resume"),
                "graceful_stop": plan.get("graceful_stop"),
                "no_live_path": plan.get("no_live_path"),
            },
            "readiness": _readiness_status(Path(quality_path), Path(preregistration_path)),
        }
    )
    if stale:
        payload["errors"].append(
            f"supervisor heartbeat is {system_age:.0f}s old: the lab may have died"
        )
    for name, child in children.items():
        if child.get("state") == ProcessState.FAILED.value:
            payload["errors"].append(f"{name}: {child.get('failure_reason') or 'FAILED'}")
        elif child.get("state") == ProcessState.STOPPED.value and report is None:
            payload["errors"].append(
                f"{name}: stopped (exit {child.get('exit_code')}) while the lab is still up"
            )
    payload["planes"] = {
        "paper": payload["paper"].get("available", False),
        "collector": payload["collector"].get("available", False),
        "strategy_lab": payload["strategy_lab"].get("available", False),
        "retention": bool((collector_payload.get("retention") or {}).get("deletion_enabled")),
    }
    payload["readiness_flags"] = _readiness_flags(payload)
    return payload


def _readiness_flags(payload: dict[str, Any]) -> dict[str, Any]:
    """§29/§58 — the five independent verdicts, never collapsed into one."""
    children = payload.get("children") or {}
    disk = payload.get("disk") or {}
    paper = payload.get("paper") or {}
    collector = payload.get("collector") or {}
    lab = payload.get("strategy_lab") or {}
    readiness = payload.get("readiness") or {}
    paper_ready = bool(paper.get("available")) and not payload.get("errors") and (
        children.get("paper", {}).get("state") in (ProcessState.RUNNING.value, "STOPPED")
    )
    # §57 — readiness has to come from the verdicts that actually exist. A
    # capture that dies on its *first* write never saves a state file, so keying
    # this off `fatal_failure` alone reported "COLLECTOR_READY: yes" next to a
    # supervisor that had already given up on the collector with a crash loop.
    collector_child = children.get("collector") or {}
    collector_manifest = collector.get("manifest") or {}
    collector_ready = (
        bool(collector.get("available"))
        and collector.get("fatal_failure") is None
        and collector_manifest.get("status") != "FAILED"
        and collector_child.get("state") != ProcessState.FAILED.value
    )
    storage_ready = disk.get("level") in (DiskLevel.NORMAL.value, DiskLevel.WARNING.value)
    lab_ready = bool(lab.get("available")) and lab.get("all_checks_ok") is not False
    return {
        "PAPER_READY": paper_ready,
        "COLLECTOR_READY": collector_ready,
        "STORAGE_READY": storage_ready,
        "STRATEGY_LAB_READY": lab_ready,
        "RESEARCH_READY": all(
            (readiness.get(name) or {}).get("verdict") not in (None, "NOT_READY")
            for name in ("M-03", "M-07")
        ),
        "note": (
            "these are independent: PAPER continuing while the collector is "
            "storage-blocked is a supported state (§22)"
        ),
        "storage_recommendation": (
            None
            if storage_ready
            else (
                "point --data-root at another volume; local capacity is below the "
                "configured warning threshold"
            )
        ),
    }


def _show(value: Any) -> str:
    """Render a possibly-absent measurement as a fact, not as the word "None".

    An operator reading "cycles=None ... state_age=Nones" has to work out whether
    the harness forgot to fill a field or the plane really has nothing to report.
    Absent is spelled "?"; everything else is itself.
    """
    return "?" if value is None else str(value)


def status_summary(status: dict[str, Any]) -> str:
    """A one-screen text rendering, for the CLI and for an operator's log."""
    disk = status.get("disk") or {}
    hours = disk.get("estimated_hours_remaining")
    rate = disk.get("consumption_gb_per_day")
    if rate is None:
        # §19 — "unknown" is a fact; "~None h" is a rendering bug an operator
        # has to decode at the worst possible moment.
        survival = "survival unknown: no retention rate measured yet"
    else:
        survival = f"~{hours} h at {rate} GB/day"
    lines = [
        f"PAPER LAB STATUS — {status.get('run_id') or 'no run'}  ({status.get('mode')})",
        f"  generated     : {status.get('generated_at_iso')}",
        f"  system        : {status.get('system', {}).get('state')} "
        f"running={status.get('system', {}).get('running')} "
        f"heartbeat_age={status.get('system', {}).get('heartbeat_age_seconds')}s",
        f"  run dir       : {status.get('run_dir')}",
        f"  disk          : {disk.get('free_gb')} GB free [{disk.get('level')}] {survival}",
        f"  guidance      : {disk.get('guidance')}",
    ]
    for name, child in (status.get("children") or {}).items():
        lines.append(
            f"  child {name:<13} {_show(child.get('state'))} pid={_show(child.get('pid'))} "
            f"alive={_show(child.get('alive'))} restarts={_show(child.get('restarts'))} "
            f"exit={_show(child.get('exit_code'))} error={_show(child.get('last_error'))}"
        )
    paper = status.get("paper") or {}
    lines.append(
        f"  paper         : cycles={_show(paper.get('cycle'))} "
        f"decisions={_show(paper.get('decisions'))} "
        f"no_trade={_show(paper.get('no_trade'))} trades={_show(paper.get('paper_trades'))} "
        f"failures={_show(paper.get('runtime_failures'))} "
        f"candidates={_show(paper.get('paper_candidates'))}"
    )
    collector = status.get("collector") or {}
    age = collector.get("state_age_seconds")
    # A unit suffix belongs to a measurement, not to its absence.
    state_age = "?" if age is None else f"{age}s"
    lines.append(
        f"  collector     : events={_show(collector.get('events'))} "
        f"gaps={_show(collector.get('gaps'))} "
        f"reconnects={_show(collector.get('reconnects'))} "
        f"segments={_show(collector.get('segments_on_disk'))} "
        f"({_show(collector.get('segment_gb'))} GB) "
        f"state_age={state_age}"
    )
    lab = status.get("strategy_lab") or {}
    lines.append(
        f"  strategy lab  : strategies={_show(lab.get('strategies_total'))} "
        f"admitted={_show(lab.get('admitted_for_paper'))} "
        f"histogram={_show(lab.get('status_histogram'))}"
    )
    for name in ("M-03", "M-07"):
        entry = (status.get("readiness") or {}).get(name) or {}
        lines.append(f"  {name}          : {_show(entry.get('verdict'))} / {_show(entry.get('state'))}")
    flags = status.get("readiness_flags") or {}
    lines.append(
        "  ready         : "
        + " ".join(
            f"{key}={'yes' if value else 'no'}"
            for key, value in flags.items()
            if isinstance(value, bool)
        )
    )
    for error in status.get("errors") or []:
        lines.append(f"  ERROR         : {error}")
    return "\n".join(lines)
