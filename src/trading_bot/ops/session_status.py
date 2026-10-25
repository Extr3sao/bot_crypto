"""ops.session_status — what a PAPER session directory is doing, read-only.

An operator looking at a crashed session had two sources of truth and both were poor: the
tail of a log, and ``*.lock`` files whose owner could be alive, dead, or a stranger that
inherited the pid. Neither answers the three questions that decide what to do next:

* may I start the session (**nobody** holds a lock, and no claim is unverifiable)?
* is this a *recovery* (a proved-abandoned lock is waiting) or a normal start?
* did the last recovery actually happen (a ``LOCK_RECLAIMED`` row with a fence), or did
  somebody delete a lock and hope?

This module answers those from the artefacts alone, and it is **strictly read-only**: it
opens files for reading, never acquires, releases, deletes or rewrites a lock, never breaks
an arbiter and never runs a recovery. Asking "what is the state?" must not change it — a
diagnostic that heals is a diagnostic you cannot trust, and one that reaps while another
writer is running is worse than no diagnostic at all.

States, in the order they are decided:

``FAILED``      the hash chain is broken, or the last finished attempt refused/aborted.
``RUNNING``     a lock exists whose owner is live on this host (``HELD``).
``RECOVERING``  a lock exists whose owner is proved gone, or cannot be named here.
``RECOVERED``   no lock remains and the newest session was a resume.
``READY``       a session ran before, ended cleanly, and was never resumed.
``ABSENT``      nothing has run here yet.

``RECOVERING`` deliberately covers both ``ABANDONED`` and ``UNATTRIBUTED``: the operator's
next action is the same (recovery is due) while the *permission* to recover is not. The
reason column says which, and only ``ABANDONED`` will actually be reclaimed by the runtime.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.ops.single_writer import SingleWriter, diagnose_lock
from trading_bot.vision.ledger import read_entries, verify_chain

__all__ = ["SCHEMA_VERSION", "session_status"]

SCHEMA_VERSION = "TAP_PAPER_SESSION_STATUS_V1"

FAILED = "FAILED"
RUNNING = "RUNNING"
RECOVERING = "RECOVERING"
RECOVERED = "RECOVERED"
READY = "READY"
ABSENT = "ABSENT"

ABANDONED_REASONS = ("OWNER_PROCESS_DEAD", "PID_REUSED")


def _utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _locks(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every lock and fence under ``root``, with the verdict on its recorded owner."""

    locks: list[dict[str, Any]] = []
    fences: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.lock")):
        record = SingleWriter(path, purpose="status").read()
        verdict = diagnose_lock(record)
        locks.append(
            {
                "path": path.relative_to(root).as_posix(),
                "state": verdict["state"],
                "reason": verdict["reason"],
                "owner_pid": (record or {}).get("pid"),
                "owner_host": (record or {}).get("host"),
                "owner_start_ms": (record or {}).get("process_start_ms"),
                "token": (record or {}).get("token"),
                "fence": (record or {}).get("fence"),
                "acquired_at_utc": (record or {}).get("acquired_at_utc"),
                "purpose": (record or {}).get("purpose"),
                "bytes": path.stat().st_size,
            }
        )
    for path in sorted(root.rglob("*.lock.fence")):
        try:
            value = int(path.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            value = None
        fences.append({"path": path.relative_to(root).as_posix(), "fence": value})
    return locks, fences


def _cycle_dirs(root: Path) -> list[int]:
    directory = root / "cycles"
    if not directory.is_dir():
        return []
    out: list[int] = []
    for item in directory.glob("cycle-*"):
        suffix = item.name.split("-")[-1]
        if suffix.isdigit():
            out.append(int(suffix))
    return sorted(out)


def session_status(out_dir: Path | str) -> dict[str, Any]:
    """Describe a session directory without touching it. Safe to call on a live session."""

    root = Path(out_dir)
    stream = root / "STREAM.jsonl"
    chain = verify_chain(stream)
    rows = read_entries(stream)
    entries = [row["entry"] for row in rows]
    seqs = [int(row["seq"]) for row in rows]

    starts = [entry for entry in entries if entry.get("kind") == "SESSION_START"]
    cycles = [entry for entry in entries if entry.get("kind") == "CYCLE"]
    ends = [entry for entry in entries if entry.get("kind") == "SESSION_END"]

    locks, fences = _locks(root) if root.is_dir() else ([], [])
    held = [item for item in locks if item["state"] == "HELD"]
    waiting = [
        item for item in locks if item["state"] in ("ABANDONED", "UNATTRIBUTED")
    ]

    #: An attempt's outcome only describes the attempt that wrote it. A refusal or an abort
    #: that predates the newest stream write is history, not the current state — otherwise a
    #: recovered session would be reported as failed forever.
    stream_mtime = _mtime_ns(stream)
    def _active(name: str) -> dict[str, Any]:
        path = root / name
        stamp = _mtime_ns(path)
        if stamp is None:
            return {}
        if stream_mtime is not None and stamp < stream_mtime:
            return {}
        return _read_json(path)

    refused = _active("REFUSED.json")
    aborted = _active("ABORTED.json")
    result = _read_json(root / "RUN_RESULT.json")
    exit_code = result.get("exit_code")
    exit_code = int(exit_code) if isinstance(exit_code, int) else None

    persisted = sorted({int(entry.get("cycle")) for entry in cycles if entry.get("cycle") is not None})
    directories = _cycle_dirs(root)
    interrupted = [index for index in directories if index not in persisted]

    #: Only the cycles that reached a ``CYCLE`` row are claimed to be complete ledgers; a
    #: cycle a crash interrupted has a directory and no row, and is reported as such rather
    #: than judged as corrupt.
    ledger_checks: dict[str, dict[str, Any]] = {}
    for index in persisted:
        path = root / "cycles" / f"cycle-{index:04d}" / "ledger.jsonl"
        verdict = verify_chain(path)
        ledger_checks[f"cycle-{index:04d}"] = {
            "ok": bool(verdict.get("ok")),
            "reason": verdict.get("reason"),
            "lines": verdict.get("lines"),
        }

    claims = [
        {
            "seq": int(row["seq"]),
            "scope": entry.get("scope") or "session",
            "cycle": entry.get("cycle"),
            "locks": list(entry.get("locks") or []),
        }
        for row, entry in zip(rows, entries, strict=True)
        if entry.get("kind") == "LOCK_RECLAIMED"
    ]
    last_recovery = claims[-1] if claims else None

    runtime_hashes = {str(entry.get("runtime_sha256")) for entry in starts}
    digests = {
        str((entry.get("provenance") or {}).get("runtime_digest")) for entry in starts
    }

    why: list[str] = []
    if chain.get("ok") is not True:
        why.append(f"CHAIN_{chain.get('reason')}")
    if refused:
        why.append(f"REFUSED:{refused.get('reason')}")
    if aborted:
        why.append(f"ABORTED:{aborted.get('reason')}")
    if exit_code is not None and exit_code not in (0, 2):
        why.append(f"EXIT_{exit_code}")
    if held:
        why.append("LIVE_OWNER")
    for item in waiting:
        why.append(f"{item['state']}:{item['reason']}:{item['path']}")

    if not rows and not locks:
        state = ABSENT
    elif (
        chain.get("ok") is not True
        or refused
        or aborted
        or (exit_code is not None and exit_code not in (0, 2))
    ):
        state = FAILED
    elif held:
        state = RUNNING
    elif waiting:
        state = RECOVERING
    elif starts and (starts[-1].get("provenance") or {}).get("resumed") is True:
        state = RECOVERED
    else:
        state = READY

    newest = starts[-1] if starts else {}
    provenance = newest.get("provenance") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "checked_at_utc": _utc_now(),
        "out_dir": str(root),
        "read_only": True,
        "state": state,
        "why": why,
        "session": {
            "session_id": provenance.get("session_id"),
            "run_id": provenance.get("run_id"),
            "pinned_identity": provenance.get("pinned_identity"),
            "runtime_digest": provenance.get("runtime_digest"),
            "resumed": provenance.get("resumed"),
            "starts": len(starts),
            "resumed_starts": sum(
                1 for entry in starts if (entry.get("provenance") or {}).get("resumed") is True
            ),
            "started_at_utc": newest.get("started_at_utc"),
            "ended_at_utc": ends[-1].get("ended_at_utc") if ends else None,
            "runtime_stable": len(runtime_hashes) == 1 and len(digests) == 1,
        },
        "owner": {
            "pid": held[0]["owner_pid"] if held else (locks[0]["owner_pid"] if locks else None),
            "process_start_ms": (
                held[0]["owner_start_ms"] if held else (locks[0]["owner_start_ms"] if locks else None)
            ),
            "host": held[0]["owner_host"] if held else (locks[0]["owner_host"] if locks else None),
            "fence": held[0]["fence"] if held else (locks[0]["fence"] if locks else None),
            "acquired_at_utc": (
                held[0]["acquired_at_utc"] if held else (locks[0]["acquired_at_utc"] if locks else None)
            ),
            "live": bool(held),
        },
        "fencing": {
            "max_fence_in_reclaims": max(
                [
                    int(lock.get("fence") or 0)
                    for claim in claims
                    for lock in claim["locks"]
                    if isinstance(lock.get("fence"), int)
                ]
                or [0]
            ),
            "fence_files": fences,
            "stream_fence": next(
                (
                    item["fence"]
                    for item in fences
                    if item["path"].endswith("STREAM.jsonl.lock.fence")
                ),
                None,
            ),
        },
        "recoveries": {
            "count": len(claims),
            "last": last_recovery,
            "last_reason": (
                (last_recovery["locks"][0].get("reason") if last_recovery["locks"] else None)
                if last_recovery
                else None
            ),
            "last_fence": (
                (last_recovery["locks"][0].get("fence") if last_recovery["locks"] else None)
                if last_recovery
                else None
            ),
            "scopes": sorted({claim["scope"] for claim in claims}),
        },
        "ledger": {
            "rows": len(rows),
            "chain_ok": bool(chain.get("ok")),
            "chain_reason": chain.get("reason"),
            "head_sha256": chain.get("head_sha256"),
            "seq_continuous": bool(seqs) and seqs == list(range(1, len(seqs) + 1)),
            "kinds": chain.get("kinds") or {},
            "cycles": persisted,
            "last_cycle": persisted[-1] if persisted else None,
            "cycle_directories": directories,
            "interrupted_cycles": interrupted,
            "cycle_ledgers": ledger_checks,
            "cycle_ledgers_ok": all(item["ok"] for item in ledger_checks.values()),
        },
        "locks": {
            "all": locks,
            "active": held,
            "awaiting_recovery": waiting,
            "abandoned_paths": [item["path"] for item in waiting],
        },
        "last_attempt": {
            "refused": bool(refused),
            "aborted": bool(aborted),
            "exit_code": exit_code,
        },
    }
