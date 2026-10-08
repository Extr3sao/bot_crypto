"""ST-6 — an immutable, dated snapshot of the live runtime state of the forward period.

The autonomous tick rewrites part of its own state every fifteen minutes: the run log grows, the
health artefact is rewritten, the scheduler report is rebuilt.  Those files are *live runtime
state*, and versioning them in git would commit a moving target.  This program therefore separates
the three kinds of artefact the phase produces, makes a dated copy of the live state, and records
the sha256 of every original byte so that a reader can tell later what the state was at this
instant:

``IMMUTABLE_EVIDENCE``
    the raw window bytes under ``data/st6/raw`` — never rewritten, only added to, and each one is
    re-hashed here to prove it still reproduces the hash inside the window index;
``VERSIONED_IMPLEMENTATION``
    the programs, the tests and the declared contracts of the phase: the things a commit should
    carry;
``LIVE_RUNTIME_STATE``
    everything the tick rewrites or appends to: snapshotted and hashed here, deliberately *not*
    committed as if it were a static report.

It is read-only with respect to the campaign: it takes no sample, takes no lease, changes no
threshold, repairs no hash and moves no file.  Its only writes are inside
``data/st6/snapshots``.

Run:  python scripts/st6_state_snapshot.py           (write the snapshot and its manifest)
      python scripts/st6_state_snapshot.py --check   (re-verify the newest snapshot only)

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "st6"
RAW = DATA / "raw"
SNAPSHOT_DIR = DATA / "snapshots"
PERIOD = DATA / "ST6_PERIOD.json"
WINDOWS = DATA / "ST6_WINDOWS.jsonl"

#: What the phase implemented: the commit is the place for these.
VERSIONED_IMPLEMENTATION = (
    "scripts/st6_forward_regime.py",
    "scripts/st6_health_check.py",
    "scripts/st6_scheduler_verify.py",
    "scripts/st6_state_snapshot.py",
    "scripts/st6_close_replay.py",
    "scripts/st6_close_verify.py",
    "tests/unit/research/test_st6_scheduler.py",
    "data/st6/ST6_TASK_DEFINITION.xml",
)

#: Live runtime state: rewritten or appended to by the running tick, never committed as static.
LIVE_RUNTIME_STATE = (
    "data/st6/ST6_PERIOD.json",
    "data/st6/ST6_WINDOWS.jsonl",
    "data/st6/ST6_OBSERVATIONS.jsonl",
    "data/st6/ST6_RUNS.jsonl",
    "data/st6/ST6_HEALTH.jsonl",
    "data/st6/ST6_HEALTH_STATUS.json",
    "data/st6/ST6_MISSED_WINDOWS.jsonl",
    "data/st6/ST6_PERIOD_CLOSURE.json",
    "data/st6/ST6_REGIME_COVERAGE.json",
    "data/st6/ST6_MODEL_DRIFT.json",
    "data/st6/ST6_FORWARD_REGIME_REPORT.json",
    "data/st6/ST6_FORWARD_REGIME_REPORT.md",
    "data/st6/ST6_SCHEDULER_REPORT.json",
    "data/st6/ST6_SCHEDULER_REPORT.md",
    "data/st6/ST6_SCHEDULER_VERIFICATION.json",
    "data/st6/ST6_INDEPENDENT_VERIFICATION.json",
    "data/st6/ST6_INDEPENDENT_VERIFICATION.md",
)

#: The lock is transient coordination, not evidence: hashed for completeness, never copied.
TRANSIENT = ("data/st6/scheduler_lock/CAMPAIGN_LOCK.json",)

SNAPSHOT_VERSION = "ST6_LIVE_STATE_SNAPSHOT_V1"
HASH_ALGORITHM = "sha256"


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:  # pragma: no cover - a non-git checkout still produces an artefact
        return "UNKNOWN"


def _git_blob(path: Path) -> str | None:
    """The blob hash git will record for the file's current bytes: the commit's own identity."""
    try:
        return subprocess.run(
            ["git", "hash-object", str(path)],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:  # pragma: no cover - git may be unavailable
        return None


def _describe(relative: str) -> dict[str, Any]:
    path = REPO / relative
    if not path.exists():
        return {"path": relative, "present": False}
    return {
        "path": relative,
        "present": True,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "git_blob_sha1": _git_blob(path),
        "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }


def raw_evidence_inventory(windows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-hash every raw snapshot and require it to reproduce the hash recorded in the index."""
    rows: list[dict[str, Any]] = []
    for path in sorted(RAW.glob("*.json.gz")):
        window_id = path.name[: -len(".json.gz")]
        with gzip.open(path, "rb") as handle:
            payload = handle.read()
        uncompressed = hashlib.sha256(payload).hexdigest()
        recorded = windows.get(window_id, {}).get("raw", {})
        rows.append(
            {
                "window_id": window_id,
                "path": str(path.relative_to(REPO)),
                "compressed_bytes": path.stat().st_size,
                "compressed_sha256": _sha256(path),
                "uncompressed_sha256": uncompressed,
                "recorded_uncompressed_sha256": recorded.get("uncompressed_sha256"),
                "reproduces_the_recorded_hash": uncompressed
                == recorded.get("uncompressed_sha256"),
                "indexed": window_id in windows,
            }
        )
    return rows


def build_snapshot() -> dict[str, Any]:
    stamp = _stamp()
    period = json.loads(PERIOD.read_text(encoding="utf-8")) if PERIOD.exists() else {}
    window_rows = [
        json.loads(line)
        for line in WINDOWS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if WINDOWS.exists() else []
    windows = {row["window_id"]: row for row in window_rows}

    live: list[dict[str, Any]] = [_describe(relative) for relative in LIVE_RUNTIME_STATE]
    implementation = [_describe(relative) for relative in VERSIONED_IMPLEMENTATION]
    transient = [_describe(relative) for relative in TRANSIENT]
    evidence = raw_evidence_inventory(windows)

    copy_root = SNAPSHOT_DIR / f"ST6_LIVE_STATE_{stamp}"
    copy_root.mkdir(parents=True, exist_ok=True)
    copies: list[str] = []
    for entry in live:
        if not entry["present"]:
            continue
        source = REPO / entry["path"]
        target = copy_root / Path(entry["path"]).relative_to("data/st6")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copies.append(entry["path"])

    document: dict[str, Any] = {
        "artifact": SNAPSHOT_VERSION,
        "snapshot_id": f"ST6_LIVE_STATE_{stamp}",
        "generated_at_utc": _utc(),
        "current_head": _head(),
        "hash_algorithm": HASH_ALGORITHM,
        "purpose": (
            "a dated, immutable picture of the ST-6 live runtime state so the moving state is not "
            "committed as if it were static, and so a later reader can tell which bytes the "
            "implementation was reading"
        ),
        "period": {
            "started_at_utc": period.get("started_at_utc"),
            "ends_at_utc": period.get("ends_at_utc"),
            "period_days": period.get("period_days"),
            "slots_per_day": period.get("slots_per_day"),
        },
        "classification": {
            "IMMUTABLE_EVIDENCE": evidence,
            "VERSIONED_IMPLEMENTATION": implementation,
            "LIVE_RUNTIME_STATE": live,
            "TRANSIENT_COORDINATION": transient,
        },
        "windows_index_rows": len(window_rows),
        "copied_live_files": copies,
        "copy_root": str(copy_root.relative_to(REPO)),
        "reading": (
            "the live files are copied and hashed, not committed; the raw evidence is re-hashed and "
            "required to reproduce the hash recorded in the window index; the implementation files "
            "carry the git blob hash the commit will record"
        ),
    }
    manifest_path = SNAPSHOT_DIR / f"ST6_LIVE_STATE_{stamp}.json"
    manifest_path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    document["manifest_path"] = str(manifest_path.relative_to(REPO))
    return document


def newest_manifest() -> Path | None:
    candidates = sorted(SNAPSHOT_DIR.glob("ST6_LIVE_STATE_*.json"))
    return candidates[-1] if candidates else None


def check_snapshot(manifest_path: Path) -> dict[str, Any]:
    """Re-verify a snapshot: the copy must still hash to the recorded original."""
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    findings: list[str] = []
    for entry in document["classification"]["LIVE_RUNTIME_STATE"]:
        if not entry.get("present"):
            continue
        if _sha256(REPO / entry["path"]) != entry["sha256"]:
            findings.append(f"{entry['path']} no longer hashes to the snapshot's original")
        copy = REPO / document["copy_root"] / Path(entry["path"]).relative_to("data/st6")
        if not copy.exists():
            findings.append(f"{entry['path']} is missing from the snapshot copy")
        elif _sha256(copy) != entry["sha256"]:
            findings.append(f"{entry['path']} hashes differently inside the snapshot copy")
    for entry in document["classification"]["IMMUTABLE_EVIDENCE"]:
        if not entry["reproduces_the_recorded_hash"]:
            findings.append(f"{entry['path']} does not reproduce its recorded window hash")
    return {
        "artifact": "ST6_LIVE_STATE_SNAPSHOT_CHECK",
        "checked_at_utc": _utc(),
        "manifest": str(manifest_path.relative_to(REPO)),
        "snapshot_id": document.get("snapshot_id"),
        "checks": len(document["classification"]["LIVE_RUNTIME_STATE"])
        + len(document["classification"]["IMMUTABLE_EVIDENCE"]),
        "findings": findings,
        "status": "PASS" if not findings else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="re-verify the newest snapshot only")
    args = parser.parse_args(argv)
    if args.check:
        manifest = newest_manifest()
        if manifest is None:
            print("no snapshot exists yet; run without --check first")
            return 1
        result = check_snapshot(manifest)
        for finding in result["findings"]:
            print(f"  FAIL {finding}")
        print(f"{result['status']} {result['checks']} checks -> {manifest.name}")
        return 0 if result["status"] == "PASS" else 1

    document = build_snapshot()
    live = document["classification"]["LIVE_RUNTIME_STATE"]
    evidence = document["classification"]["IMMUTABLE_EVIDENCE"]
    print(
        f"snapshot {document['snapshot_id']} at {document['current_head']}: "
        f"{sum(1 for entry in live if entry['present'])} live files copied and hashed, "
        f"{len(evidence)} raw snapshots re-hashed, "
        f"{'every raw hash reproduces' if all(e['reproduces_the_recorded_hash'] for e in evidence) else 'A RAW HASH DOES NOT REPRODUCE'}"
    )
    print(f"written -> {document['manifest_path']} and {document['copy_root']}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
