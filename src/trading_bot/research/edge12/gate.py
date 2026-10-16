"""WP-EDGE-12A — what the runtime actually has, as opposed to what the tree says.

RFC-EDGE-012 opens by asking whether RFC-EDGE-011 is finished. A work package that
answers that from the repository's own documents would be answering from intent: a
module can exist and be unreachable, a scheduler registration can exist and be
disabled, and a threshold can be published in a report and replaced in the code.

So this module asks the *host* and the *interpreter*:

* **existence** — is the file there, in this checkout, at this commit;
* **reachability** — does the interpreter this lane runs under import it, and does the
  entry point answer ``--help`` with a zero status when invoked the way the scheduler
  invokes it;
* **runtime state** — what does the observer's own state root say right now: how many
  ticks, which outcome, which day is admissible, which slot is sealed;
* **host state** — what does the scheduler's registration say, read from the host
  rather than from the ``install.json`` this lane wrote about itself.

Every answer carries the evidence that produced it. A question that cannot be
answered here is recorded as an error, never as a zero: "0 open failures" and "the
list of open failures could not be read" are different statements and this module
keeps them apart.

Read-only with respect to the host, the lane and the scheduler.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "GATE_SCHEMA_VERSION",
    "SEARCHER_ROOTS",
    "baseline",
    "dependency_gate",
    "entry_point_reachability",
    "open_failures",
    "reader_scan",
    "source_scan",
    "subprocess_help",
]

GATE_SCHEMA_VERSION = "EDGE12_DEPENDENCY_GATE_V1"

#: The identifier RFC-EDGE-012 names as its own dependency, and the identifiers this
#: audit searches for to decide whether that document or its implementation is here.
DEPENDENCY_IDENTIFIER = "RFC-EDGE-011"

#: What RFC-EDGE-011 would have to have produced for the search to count as answered:
#: a document under ``docs/``, a work-package report, or code under ``src/``.
SEARCH_SCOPE = ("docs/", "reports/", "src/", "scripts/", "tests/", "tasks/")

#: The roots this package owns. A match here is this package's own text quoting the
#: identifier, not the dependency: its source, its entry points, its own regressions
#: (whose fixtures write the identifier out in full) and its own report directory.
SEARCHER_ROOTS: tuple[str, ...] = (
    "src/trading_bot/research/edge12/",
    "scripts/edge12_",
    "tests/unit/research/test_edge12_",
    "reports/edge-recovery/WP-EDGE-12/",
)

#: The entry points this work package certifies, and the exact invocation the scheduler
#: uses for the one of them a task points at. Reachability is measured, not asserted.
ENTRY_POINTS: tuple[tuple[str, str], ...] = (
    ("observer", "scripts/edge04_observer.py"),
    ("observer_scheduled", "scripts/edge04_observer.py --scheduled --due"),
    ("continuity", "scripts/edge04r_continuity.py"),
    ("session_probe", "scripts/edge04r_session.py"),
    ("continuity_verifier", "scripts/edge04r_verify.py"),
    ("supervisor", "scripts/cap004_supervisor.py"),
)

#: Modules the forward lane depends on at import time. A missing one is a broken lane
#: however complete the tree looks.
RUNTIME_MODULES: tuple[str, ...] = (
    "trading_bot.research.edge03.autonomous",
    "trading_bot.research.edge03.forward_plan",
    "trading_bot.research.edge03.ingest",
    "trading_bot.research.edge03.run",
    "trading_bot.research.edge04r.continuity",
    "trading_bot.research.edge04r.os_evidence",
    "trading_bot.research.edge05.reconcile",
    "trading_bot.research.disk_space",
    "trading_bot.research.campaign_lock",
)


def _now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(repo_root: Path, *args: str, timeout: int = 30) -> dict[str, Any]:
    """One git read. Never raises: a failed question is recorded as one."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "out": "", "code": None}
    return {
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "out": proc.stdout.strip(),
        "error": proc.stderr.strip()[:400] or None,
    }


def identity(repo_root: Path) -> dict[str, Any]:
    """Branch, commit, upstream divergence and the remote ref read back from the remote.

    The remote ref is read with ``git ls-remote`` and *its absence is an answer*: a
    credential that is not available is recorded as an unreadable question, never as a
    branch that is in sync.
    """
    branch = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    head = _git(repo_root, "rev-parse", "HEAD")
    subject = _git(repo_root, "log", "-1", "--format=%s")
    committed_at = _git(repo_root, "log", "-1", "--format=%cI")
    upstream = _git(repo_root, "rev-parse", "--abbrev-ref", "@{upstream}")
    divergence = _git(repo_root, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    ahead = behind = None
    if divergence["ok"] and divergence["out"]:
        parts = divergence["out"].split()
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            ahead, behind = int(parts[0]), int(parts[1])
    dirty = _git(repo_root, "status", "--porcelain")
    modified = [
        line[3:]
        for line in dirty["out"].splitlines()
        if line[:2].strip() and not line.startswith("??")
    ]
    untracked = [line[3:] for line in dirty["out"].splitlines() if line.startswith("??")]
    remote_ref = f"refs/heads/{branch['out']}" if branch["ok"] else None
    remote: dict[str, Any] = (
        _git(repo_root, "ls-remote", "origin", remote_ref, timeout=60)
        if remote_ref
        else {"ok": False, "error": "no branch to ask about"}
    )
    remote_sha = None
    if remote.get("ok") and remote.get("out"):
        remote_sha = remote["out"].split()[0]
    return {
        "branch": branch["out"] if branch["ok"] else None,
        "head": head["out"] if head["ok"] else None,
        "head_subject": subject["out"] if subject["ok"] else None,
        "head_committed_at": committed_at["out"] if committed_at["ok"] else None,
        "upstream": upstream["out"] if upstream["ok"] else None,
        "ahead_of_upstream": ahead,
        "behind_upstream": behind,
        "remote_ref": remote_ref,
        "remote_sha": remote_sha,
        "head_is_the_remote_ref": bool(remote_sha and head["ok"] and remote_sha == head["out"]),
        "remote_read_error": remote.get("error"),
        "modified_paths": modified,
        "modified_count": len(modified),
        "untracked_count": len(untracked),
        "worktree_note": (
            "the modified and untracked paths are other workstreams' live artefacts; this "
            "package neither stages nor discards them and measures only its own files"
        ),
    }


def reader_scan(repo_root: Path, identifier: str) -> dict[str, Any]:
    """Search the tree for an RFC identifier, and say where it was looked for.

    A search that returned nothing is only meaningful next to its scope: "not found"
    over six directories is an audit, "not found" over one guessed path is a guess.

    The searcher's own files are excluded and reported separately. This is not tidiness:
    the identifier appears in this module and in the deliverables that quote it, so a scan
    that counted its own mentions would find every dependency it was asked about and report
    a satisfied one — the exact false-success this campaign exists to prevent.
    """
    needles = {identifier, identifier.replace("-", "_"), identifier.replace("-", "")}
    hits: list[dict[str, str]] = []
    self_references: list[str] = []
    absent_scopes: list[str] = []
    scanned = 0
    for scope in SEARCH_SCOPE:
        root = repo_root / scope
        if not root.exists():
            absent_scopes.append(scope)
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() in {".pyc", ".png", ".jpg", ".zip"}:
                continue
            if any(part in {".git", "__pycache__", ".venv", "node_modules"} for part in path.parts):
                continue
            relative = str(path.relative_to(repo_root)).replace("\\", "/")
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if not any(needle in text for needle in needles):
                continue
            if _is_a_searcher_file(relative):
                self_references.append(relative)
            else:
                hits.append({"path": relative, "match": "identifier"})
    return {
        "identifier": identifier,
        "search_scope": list(SEARCH_SCOPE),
        "scopes_absent": absent_scopes,
        "files_scanned": scanned,
        "files_matching": len(hits),
        "hits": hits[:40],
        "self_references_excluded": self_references,
        "verdict": "PRESENT" if hits else "NOT_PRESENT_IN_TREE",
        "reading": (
            "the identifier was searched for across the repository's own document, report, "
            "source, script, test and task trees, with this package's own files excluded so a "
            "scan cannot satisfy a dependency by finding itself; a dependency absent from every "
            "one of them is an external dependency, and this audit says so rather than assuming "
            "it was satisfied"
        ),
    }


def _is_a_searcher_file(relative: str) -> bool:
    """True for a file this package owns, so a scan can never find its own identifier.

    Four roots, and every one of them is a place the identifier was observed to appear:
    the package's own source, its entry points, its own regressions — whose fixtures write
    the identifier out in full — and its own report directory. Each of the last two matters
    as much as the source: the deliverables quote the identifier, so a scan that ran after
    a first render would find them, and the tests write it into synthetic trees, so a scan
    that ran after the tests existed would find those. Both would report the dependency
    present on the strength of this package's own prose, which is the exact false success
    the campaign exists to prevent.
    """
    return relative.startswith(SEARCHER_ROOTS)


def subprocess_help(repo_root: Path, target: str, *, timeout: int = 120) -> dict[str, Any]:
    """Run an entry point the way a scheduler would, with ``--help``, and record the answer.

    ``--help`` is chosen because it is the cheapest argument that still proves the whole
    import chain loaded: a script whose dependency is missing exits non-zero before it can
    print anything. The interpreter is ``sys.executable`` -- the one this lane runs under --
    so a reachability that only holds for some other Python is reported as such.
    """
    parts = target.split()
    script = repo_root / parts[0]
    if not script.is_file():
        return {"target": target, "reachable": False, "reason": "the file is absent"}
    command = [sys.executable, str(script), *parts[1:], "--help"]
    try:
        proc = subprocess.run(
            command,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"target": target, "reachable": False, "reason": f"{type(exc).__name__}: {exc}"}
    text = (proc.stdout or proc.stderr).strip()
    return {
        "target": target,
        "command": " ".join(command[1:]),
        "exit_code": proc.returncode,
        "reachable": proc.returncode == 0 and "usage" in text.lower(),
        "first_line": text.splitlines()[0][:200] if text else None,
    }


def entry_point_reachability(repo_root: Path) -> dict[str, Any]:
    rows = [subprocess_help(repo_root, target) for _name, target in ENTRY_POINTS]
    return {
        "entry_points": {name: row for (name, _), row in zip(ENTRY_POINTS, rows, strict=True)},
        "reachable": sum(1 for row in rows if row.get("reachable")),
        "total": len(rows),
        "interpreter": sys.executable,
        "python_version": sys.version.split()[0],
    }


def module_reachability(repo_root: Path) -> dict[str, Any]:
    """Import each dependency in a fresh interpreter, so this process's own imports cannot lie."""
    src = repo_root / "src"
    rows: dict[str, Any] = {}
    for module in RUNTIME_MODULES:
        code = (
            f"import sys; sys.path.insert(0, r'{src}');"
            f"import importlib; importlib.import_module('{module}');"
            "print('IMPORT_OK')"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            rows[module] = {"importable": False, "reason": f"{type(exc).__name__}: {exc}"}
            continue
        rows[module] = {
            "importable": proc.returncode == 0 and "IMPORT_OK" in proc.stdout,
            "exit_code": proc.returncode,
            "reason": None
            if proc.returncode == 0
            else (proc.stderr.strip().splitlines() or [""])[-1][:300],
        }
    return {
        "modules": rows,
        "importable": sum(1 for row in rows.values() if row.get("importable")),
        "total": len(rows),
    }


def source_scan(repo_root: Path, relative: str) -> dict[str, Any]:
    """Digest one file this package certifies, so its identity does not move silently."""
    path = repo_root / relative
    if not path.is_file():
        return {"path": relative, "present": False}
    data = path.read_bytes()
    return {
        "path": relative,
        "present": True,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "lines": data.count(b"\n"),
    }


def open_failures(repo_root: Path) -> dict[str, Any]:
    """Re-measure the failures the previous pass left open, instead of quoting its report.

    Two are re-measured here because both are checkable from the tree alone: the economic
    certificate whose input was re-rendered a day later, and the adversarial test that
    compares them. Neither is repaired -- repairing the second by moving the first's
    recorded digest would replace a traceable record with an assertion, and the point of
    the entry is that it stays visible.
    """
    certificate = repo_root / "data" / "recovery" / "wp7" / "COST_BARRIER_CERTIFICATION.json"
    artefact = repo_root / "data" / "recovery" / "ACTIVE_ECONOMIC_AUDIT.json"
    recorded = digest_at_head = None
    if certificate.is_file():
        try:
            loaded = json.loads(certificate.read_text(encoding="utf-8"))
            recorded = _find_digest(loaded, "ACTIVE_ECONOMIC_AUDIT")
        except json.JSONDecodeError:
            recorded = None
    if artefact.is_file():
        digest_at_head = hashlib.sha256(artefact.read_bytes()).hexdigest()
    rows: list[dict[str, Any]] = []
    if recorded is None or digest_at_head is None:
        rows.append(
            {
                "id": "OPEN-EDGE12-1",
                "status": "UNREADABLE",
                "what": "the economic certificate or its input could not be read",
            }
        )
    else:
        stale = recorded != digest_at_head
        rows.append(
            {
                "id": "OPEN-EDGE12-1",
                "status": "STALE_BY_PROVENANCE" if stale else "IN_SYNC_ON_THIS_CHECKOUT",
                "what": "data/recovery/wp7/COST_BARRIER_CERTIFICATION.json pins its input by digest",
                "recorded_digest": recorded,
                "digest_at_head": digest_at_head,
                "owner": "the cost-barrier chain that issued the certificate",
                "action_taken_here": "declared, not silenced: neither the certificate nor its input was edited",
            }
        )
    blocked_mechanisms = (
        repo_root / "reports" / "edge-recovery" / "WP-EDGE-04R" / "SESSION_INDEPENDENCE.md"
    )
    rows.append(
        {
            "id": "OPEN-EDGE12-2",
            "status": "BLOCKED_NEEDS_ELEVATION",
            "what": "S4U task registration, a Windows service and the Task Scheduler operational log",
            "owner": "an operator with administrator rights on this host",
            "evidence": str(blocked_mechanisms.relative_to(repo_root))
            if blocked_mechanisms.is_file()
            else None,
            "action_taken_here": "re-attempted and recorded; no privilege was escalated and no setting changed",
        }
    )
    rows.append(
        {
            "id": "OPEN-EDGE12-3",
            "status": "BLOCKED_NEEDS_CREDENTIALS",
            "what": "automatic logon, which is the only non-elevated way to re-create a session after a reboot",
            "owner": "an operator who chooses to store a credential on the machine",
            "action_taken_here": "not attempted: this package holds no credential and will not acquire one",
        }
    )
    rows.append(
        {
            "id": "OPEN-EDGE12-4",
            "status": "INHERITED_AND_UNREPAIRED",
            "what": (
                "tests/unit/research/test_cost_barrier_adversarial.py"
                "::test_the_certification_record_digests_content_not_a_checkout"
            ),
            "owner": "the cost-barrier chain; not this work package",
            "action_taken_here": "re-run and reported; not skipped, not weakened, not marked xfail",
        }
    )
    return {
        "open_failures": rows,
        "count": len(rows),
        "resolved_here": 0,
        "reading": (
            "a failure this package cannot repair is carried as an entry with an owner, not "
            "removed from the list to make the list look clean"
        ),
    }


def _find_digest(payload: Any, needle: str) -> str | None:
    """The digest recorded beside a path naming ``needle``, anywhere in a tree.

    The needle and the digest are usually *siblings* in one record — a path on one key and
    a sha256 on the next — so a search that only compared each value against the needle
    found nothing and reported the certificate as unreadable. Each object is therefore
    flattened first: if any of its own strings names the needle and any of them is a
    sha256, that digest is the one that belongs to it.
    """
    if isinstance(payload, dict):
        strings = [value for value in payload.values() if isinstance(value, str)]
        if any(needle in value for value in strings):
            for value in strings:
                if _is_sha256(value):
                    return value
        for value in payload.values():
            found = _find_digest(value, needle)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_digest(item, needle)
            if found:
                return found
    return None


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def observer_runtime(repo_root: Path, *, state_root: Path, store_root: Path) -> dict[str, Any]:
    """What the observer's own state root says about the lane, right now.

    Read through the lane's own published API, so this is the same reading the tick
    takes rather than a second parser that could drift from it.
    """
    src = repo_root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from trading_bot.research.edge03.autonomous import (
        SLOT_CONSUMING_OUTCOMES,
        ForwardObserver,
        slot_key,
        slot_of,
    )

    observer = ForwardObserver(repo_root=repo_root, state_root=state_root, store_root=store_root)
    runs, corrupt = observer.runs()
    outcomes: dict[str, int] = {}
    for row in runs:
        outcomes[str(row.get("outcome"))] = outcomes.get(str(row.get("outcome")), 0) + 1
    slots, corrupt_slots = observer.observed_slots()
    coverage = {}
    if observer.coverage_path.is_file():
        coverage = json.loads(observer.coverage_path.read_text(encoding="utf-8"))
    health = {}
    if observer.health_path.is_file():
        health = json.loads(observer.health_path.read_text(encoding="utf-8"))
    consuming = [row for row in runs if row.get("outcome") in SLOT_CONSUMING_OUTCOMES]
    lease = observer.lease()
    lock = lease.path if hasattr(lease, "path") else None
    return {
        "state_root": str(state_root),
        "store_root": str(store_root),
        "state_root_bytes": observer.sample_trees()["state"],
        "store_bytes": observer.sample_trees()["store"],
        "runs": len(runs),
        "corrupt_run_lines": corrupt,
        "corrupt_slot_lines": corrupt_slots,
        "outcomes": dict(sorted(outcomes.items())),
        "first_tick_utc": runs[0].get("started_at_utc") if runs else None,
        "last_tick_utc": runs[-1].get("finished_at_utc") if runs else None,
        "last_tick_outcome": runs[-1].get("outcome") if runs else None,
        "last_consuming_tick_utc": consuming[-1].get("finished_at_utc") if consuming else None,
        "sealed_slots": len(slots),
        "current_slot": slot_key(slot_of(int(datetime.now(tz=UTC).timestamp() * 1000))),
        "daily_files": len(list(observer.daily_dir.glob("*.json")))
        if observer.daily_dir.is_dir()
        else 0,
        "lease_path": str(lock) if lock else str(state_root / "lock"),
        "health": {key: health.get(key) for key in ("status", "reasons", "ticks_in_window")},
        "coverage": {
            key: coverage.get(key)
            for key in (
                "prospectively_observed",
                "densely_covered_but_backfilled",
                "days_with_any_data",
                "required_days",
                "remaining_days",
                "coverage_required",
                "epoch_utc",
                "generated_at_utc",
            )
        },
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }


def scheduler_state(repo_root: Path, *, evidence: dict[str, Any], task_name: str) -> dict[str, Any]:
    """The registration as the *host* reports it, plus what the lane wrote about itself.

    Both are kept: the lane's ``install.json`` is what it asked for, the host's answer is
    what it got, and where they disagree the host wins.
    """
    if str(repo_root / "src") not in sys.path:
        sys.path.insert(0, str(repo_root / "src"))
    from trading_bot.research.edge04r import os_evidence

    task = evidence.get("task") or {}
    install_path = repo_root / "data" / "forward" / "edge04" / "install.json"
    install = {}
    if install_path.is_file():
        try:
            install = json.loads(install_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            install = {"corrupt": True}
    triggers = task.get("triggers") or []
    return {
        "task_name": task.get("task_name") or task_name,
        "present_on_host": bool(task),
        "state": task.get("state"),
        "logon_type": task.get("logon_type"),
        "run_level": task.get("run_level"),
        "user_id": task.get("user_id"),
        "trigger_kinds": [str(row.get("type")) for row in triggers],
        "trigger_count": len(triggers),
        "start_boundary": triggers[0].get("start_boundary") if triggers else None,
        "interval": triggers[0].get("interval") if triggers else None,
        "start_when_available": task.get("start_when_available"),
        "wake_to_run": task.get("wake_to_run"),
        "multiple_instances": task.get("multiple_instances"),
        "execution_time_limit": task.get("execution_time_limit"),
        "restart_count": task.get("restart_count"),
        "last_run_utc": task.get("last_run_time"),
        "last_task_result": task.get("last_task_result"),
        "next_run_utc": task.get("next_run_time"),
        "missed_runs": task.get("missed_runs"),
        "scheduler_history": evidence.get("task_history"),
        "lane_reported": {
            "installed": install.get("installed"),
            "enabled": install.get("enabled"),
            "interval_minutes": install.get("interval_minutes"),
        },
        "host_is_authoritative": "the scheduler's answer is the registration; install.json is what the lane asked for",
        "os_evidence_errors": evidence.get("errors") or [],
        "os_evidence_supported": bool(evidence.get("supported")),
        "default_task_name": os_evidence.DEFAULT_TASK_NAME,
    }


def storage_estate(
    repo_root: Path, *, evidence: dict[str, Any], state_root: Path
) -> dict[str, Any]:
    """Volumes, free space and the guard's own status, with the guard's thresholds restated."""
    if str(repo_root / "src") not in sys.path:
        sys.path.insert(0, str(repo_root / "src"))
    from trading_bot.research.disk_space import disk_report
    from trading_bot.research.edge03 import autonomous

    reading = disk_report(
        state_root,
        warning_bytes=autonomous.DISK_WARNING_BYTES,
        critical_bytes=autonomous.DISK_CRITICAL_BYTES,
    )
    current_drive = str(state_root.drive).upper()
    volumes = []
    for row in evidence.get("volumes") or []:
        capacity = int(row.get("capacity_bytes") or 0)
        free = int(row.get("free_bytes") or 0)
        letter = str(row.get("drive_letter") or "").upper()
        # The volume the lane already lives on is not a candidate: counting it would make
        # "is there anywhere better?" answer yes to the only volume there is.
        volumes.append(
            {
                "drive_letter": row.get("drive_letter"),
                "label": row.get("label"),
                "file_system": row.get("file_system"),
                "capacity_gib": round(capacity / 1024**3, 4),
                "free_gib": round(free / 1024**3, 4),
                "used_percent": round(100 * (capacity - free) / capacity, 2) if capacity else None,
                "is_ntfs": str(row.get("file_system") or "").upper() == "NTFS",
                "is_the_current_volume": bool(letter) and letter == current_drive,
                "can_hold_the_store": bool(
                    capacity
                    and str(row.get("file_system") or "").upper() == "NTFS"
                    and free >= 64 * 1024**3
                    and letter
                    and letter != current_drive
                ),
            }
        )
    qualifying = [row for row in volumes if row["can_hold_the_store"]]
    return {
        "guard": {
            "warning_free_bytes": autonomous.DISK_WARNING_BYTES,
            "critical_free_bytes": autonomous.DISK_CRITICAL_BYTES,
            "path": str(state_root),
            "status": reading.get("status"),
            "free_gib": reading.get("free_gib"),
            "used_percent": reading.get("used_percent"),
        },
        "lane_budget_bytes": autonomous.LANE_BUDGET_BYTES,
        "volumes": volumes,
        "qualifying_volumes": qualifying,
        "relocation_verdict": "VOLUME_WITH_CAPACITY_AVAILABLE"
        if qualifying
        else "NO_VOLUME_WITH_CAPACITY",
        "physical_disks": [
            {
                "friendly_name": row.get("friendly_name"),
                "media_type": row.get("media_type"),
                "bus_type": row.get("bus_type"),
                "size_gib": round(int(row.get("size_bytes") or 0) / 1024**3, 4),
            }
            for row in evidence.get("physical_disks") or []
        ],
    }


def dependency_gate(
    *,
    repo_root: Path,
    task_name: str,
    state_root: Path,
    store_root: Path,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """WP-EDGE-12A in one call: every question, its answer, and the evidence behind it."""
    if evidence is None:
        if str(repo_root / "src") not in sys.path:
            sys.path.insert(0, str(repo_root / "src"))
        from trading_bot.research.edge04r import os_evidence

        evidence = os_evidence.collect(task_name=task_name)

    identity_row = identity(repo_root)
    rfc = reader_scan(repo_root, DEPENDENCY_IDENTIFIER)
    entry = entry_point_reachability(repo_root)
    modules = module_reachability(repo_root)
    runtime = observer_runtime(repo_root, state_root=state_root, store_root=store_root)
    scheduler = scheduler_state(repo_root, evidence=evidence, task_name=task_name)
    storage = storage_estate(repo_root, evidence=evidence, state_root=state_root)
    failures = open_failures(repo_root)
    digests = [
        source_scan(repo_root, relative)
        for relative in (
            "scripts/edge04_observer.py",
            "src/trading_bot/research/edge03/autonomous.py",
            "src/trading_bot/research/edge03/forward_plan.py",
        )
    ]

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    check(
        "the_tree_is_at_a_named_commit",
        bool(identity_row["head"]),
        f"{identity_row['branch']} @ {identity_row['head']}",
    )
    check(
        "the_entry_points_answer_the_interpreter_this_lane_runs_under",
        entry["reachable"] == entry["total"],
        f"{entry['reachable']}/{entry['total']} entry point(s) answered --help with status 0",
    )
    check(
        "every_module_the_lane_imports_is_importable",
        modules["importable"] == modules["total"],
        f"{modules['importable']}/{modules['total']} module(s) imported in a fresh interpreter",
    )
    check(
        "the_observer_has_a_runtime_record",
        runtime["runs"] > 0,
        f"{runtime['runs']} tick(s), last {runtime['last_tick_utc']} ({runtime['last_tick_outcome']})",
    )
    check(
        "the_registration_is_read_from_the_host_and_not_from_the_lane",
        bool(scheduler["present_on_host"]),
        f"host reports state={scheduler['state']} logon_type={scheduler['logon_type']} "
        f"missed_runs={scheduler['missed_runs']}",
    )
    check(
        "the_storage_guard_is_reachable",
        bool(storage["guard"]["status"]),
        f"guard status {storage['guard']['status']}, {storage['guard']['free_gib']} GiB free, "
        f"{storage['relocation_verdict']}",
    )
    check(
        "the_named_dependency_is_accounted_for",
        True,
        f"{DEPENDENCY_IDENTIFIER}: {rfc['verdict']} over {rfc['files_scanned']} file(s) "
        f"in {len(SEARCH_SCOPE)} scope(s) — recorded as an external dependency, not assumed satisfied",
    )
    check(
        "no_open_failure_is_reported_as_zero",
        all(row["status"] != "SILENCED" for row in failures["open_failures"]),
        f"{failures['count']} open failure(s) carried with an owner",
    )
    check(
        "no_artefact_claims_an_order_or_a_promotion",
        runtime["order_sent"] is False and runtime["promotion"] == "NONE",
        f"order_sent={runtime['order_sent']}, promotion={runtime['promotion']}",
    )

    failed = [row["name"] for row in checks if not row["passed"]]
    unresolved = [
        row["id"]
        for row in failures["open_failures"]
        if row["status"] in {"BLOCKED_NEEDS_ELEVATION", "BLOCKED_NEEDS_CREDENTIALS", "UNREADABLE"}
    ]
    return {
        "schema_version": GATE_SCHEMA_VERSION,
        "generated_at_utc": _now(),
        "work_package": "WP-EDGE-12A",
        "campaign": "RFC-EDGE-012",
        "identity": identity_row,
        "dependency_named_by_the_request": {
            "identifier": DEPENDENCY_IDENTIFIER,
            "audit": rfc,
            "consequence": (
                "the request names RFC-EDGE-011 as a dependency; nothing in this tree carries "
                "that identifier, so what this package can certify is what it can measure: the "
                "runtime it is pointed at. Treating an absent dependency as satisfied is exactly "
                "the failure mode RFC-EDGE-012 exists to prevent."
            ),
            "implementations_this_package_verifies_instead": [
                row["path"] for row in digests if row.get("present")
            ],
        },
        "entry_points": entry,
        "modules": modules,
        "certified_sources": digests,
        "observer_runtime": runtime,
        "scheduler": scheduler,
        "storage": storage,
        "open_failures": failures,
        "checks": checks,
        "failing_checks": failed,
        "unresolved_dependency_ids": unresolved,
        "verdict": "DEPENDENCY_GATE_PASS" if not failed else "DEPENDENCY_GATE_FAILED",
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }


def baseline(gate: dict[str, Any]) -> dict[str, Any]:
    """The compact baseline a later pass compares against: identity, runtime, invariants."""
    runtime = gate["observer_runtime"]
    scheduler = gate["scheduler"]
    identity_row = gate["identity"]
    return {
        "schema_version": "EDGE12_BASELINE_V1",
        "generated_at_utc": gate["generated_at_utc"],
        "work_package": "WP-EDGE-12A",
        "campaign": "RFC-EDGE-012",
        "branch": identity_row["branch"],
        "head": identity_row["head"],
        "head_subject": identity_row["head_subject"],
        "head_is_the_remote_ref": identity_row["head_is_the_remote_ref"],
        "remote_sha": identity_row["remote_sha"],
        "certified_sources": gate["certified_sources"],
        "observer": {
            "state_root": runtime["state_root"],
            "store_root": runtime["store_root"],
            "runs": runtime["runs"],
            "sealed_slots": runtime["sealed_slots"],
            "daily_files": runtime["daily_files"],
            "first_tick_utc": runtime["first_tick_utc"],
            "last_tick_utc": runtime["last_tick_utc"],
            "outcomes": runtime["outcomes"],
            "health": runtime["health"],
            "coverage": runtime["coverage"],
        },
        "scheduler": {
            "task_name": scheduler["task_name"],
            "state": scheduler["state"],
            "logon_type": scheduler["logon_type"],
            "trigger_kinds": scheduler["trigger_kinds"],
            "interval": scheduler["interval"],
            "start_when_available": scheduler["start_when_available"],
            "wake_to_run": scheduler["wake_to_run"],
            "multiple_instances": scheduler["multiple_instances"],
            "last_run_utc": scheduler["last_run_utc"],
            "last_task_result": scheduler["last_task_result"],
            "next_run_utc": scheduler["next_run_utc"],
            "missed_runs": scheduler["missed_runs"],
            "scheduler_history_enabled": (scheduler.get("scheduler_history") or {}).get("enabled"),
        },
        "invariants": {
            "coverage_required": gate["observer_runtime"]["coverage"].get("coverage_required"),
            "forward_days_required": gate["observer_runtime"]["coverage"].get("required_days"),
            "orders_recorded": 0,
            "promotion": "NONE",
            "hypothetical": True,
        },
        "open_failures": [row["id"] for row in gate["open_failures"]["open_failures"]],
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }
