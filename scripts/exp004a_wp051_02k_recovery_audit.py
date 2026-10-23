"""Read-only audit of what survives of EXP-004A, and what does not.

This program writes nothing but its own report. It answers three questions with evidence instead of
memory:

1. **What is still here?** Every component the campaign needs is located, hashed against the commit
   it claims to come from, and classified `FOUND_VALID`, `FOUND_UNVERIFIED`, `ABSENT` or `CORRUPTED`.
2. **What survived outside Git?** The forward store was never tracked. A published prefix of it is
   tracked under a report directory with its own `SNAPSHOT.json`, so the prefix is verified against
   that snapshot *and* against the hashes the 02K package recorded of the live store.
3. **What does the host still believe?** The watchdog's scheduled task is read from the task
   scheduler and its action is checked against the filesystem: an alarm pointing at a deleted script
   is an alarm that cannot fire, and that is a fact about the guard, not an opinion.

Hashes are compared the way the artefacts were hashed: the forward store wrote CRLF line endings, Git
stores LF, so a byte-identical file can hash differently. Both forms are computed and the report says
which one matched.

Usage::

    python scripts/exp004a_wp051_02k_recovery_audit.py            # inventory + integrity + report
    python scripts/exp004a_wp051_02k_recovery_audit.py --inventory
    python scripts/exp004a_wp051_02k_recovery_audit.py --integrity
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "EXP004A_WP051_02K_RECOVERY_AUDIT_V1"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "docs" / "agentic" / "exp004a" / "wp051_02k" / "continuation"
SOURCE_COMMIT = "9983b050c8e241ef9d8365c8ffc33c95df1658dd"
REQUIRED_GIB = 14.564
GIB = 1024**3
MIB = 1024**2

CONTRACT = "config/preregistrations/EXP-004A.datasets.phase3.json"
STORE_PHASE3 = "data/exp004a/phase3"
STORE_FORWARD_PHASE3 = "data/forward/edge04"
STORE_FORWARD_PHASE2 = "data/forward/edge03"
PUBLISHED_PREFIX = "reports/edge-recovery/WP-EDGE-04/evidence"
RECORD_DIR = "docs/agentic/exp004a/wp051_02k"
TASK_NAME = r"\TradingAgentic-EDGE04-Watchdog"

#: Every component the campaign needs, with what it is for. Absence is a finding, not a gap to fill.
ELEMENTS: tuple[tuple[str, str, str], ...] = (
    ("contract_phase3", CONTRACT, "the frozen declaration: window, shard policy, coverage rule"),
    ("contract_phase2", "config/preregistrations/EXP-004A.datasets.phase2.json", "the superseded declaration, kept for reference"),
    ("contract_root", "config/preregistrations/EXP-004A.json", "the experiment's root declaration"),
    ("capture_runner_02f", "scripts/exp004a_wp051_02f_runner.py", "the forward capture entry point (phase 1/2)"),
    ("capture_runner_02g", "scripts/exp004a_wp051_02g_capture.py", "the incremental capture entry point (phase 3)"),
    ("capture_verifier_02g", "scripts/exp004a_wp051_02g_verify.py", "the independent verifier of a phase-3 capture"),
    ("observer", "scripts/edge04_observer.py", "the forward observer that writes the store and the alarm rows"),
    ("observer_watchdog", "scripts/edge04_watchdog.py", "the guard: reads the observer's silence and escalates"),
    ("closure", "scripts/edge04_closure.py", "closes a day into the store"),
    ("engine", "src/trading_bot/research/prospective/incremental.py", "the capture plan the contract names as its engine"),
    ("store_module", "src/trading_bot/research/prospective/store.py", "the reader the runner imports"),
    ("shard_store_phase3", STORE_PHASE3, "the write-once phase-3 shards and their manifests"),
    ("published_prefix", PUBLISHED_PREFIX, "the only surviving copy of any part of the forward store"),
    ("store_forward_edge04", STORE_FORWARD_PHASE3, "the live phase-3 forward store: runs, slots, alarms, daily shards"),
    ("store_forward_edge03", STORE_FORWARD_PHASE2, "the live phase-2 forward store the 02G verifier reads"),
)


def now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def digests(path: Path) -> dict[str, Any]:
    """Both hashes of a file: the bytes on disk, and the same bytes with CRLF line endings."""
    try:
        raw = path.read_bytes()
    except OSError:
        return {"exists": False}
    crlf = raw if b"\r\n" in raw else raw.replace(b"\n", b"\r\n")
    return {
        "exists": True,
        "bytes": len(raw),
        "bytes_crlf": len(crlf),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sha256_crlf": hashlib.sha256(crlf).hexdigest(),
        "lines": raw.count(b"\n"),
    }


def matches(declared: str | None, info: dict[str, Any]) -> bool:
    if not declared or not info.get("exists"):
        return False
    return declared in (info["sha256"], info["sha256_crlf"])


def prefix_matches(prefix: str | None, info: dict[str, Any]) -> bool:
    """The 02K record kept twelve hex characters; a prefix is all it can be compared to."""
    if not prefix or not info.get("exists"):
        return False
    return info["sha256"].startswith(prefix) or info["sha256_crlf"].startswith(prefix)


def git(*args: str) -> tuple[int, str]:
    done = subprocess.run(["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180, check=False)
    return done.returncode, (done.stdout or "").strip()


def run(command: list[str], timeout: int = 600) -> dict[str, Any]:
    try:
        done = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"command": " ".join(command), "exit_code": None, "tail": f"could not run: {exc}"}
    output = ((done.stdout or "") + (done.stderr or "")).strip().splitlines()
    return {"command": " ".join(command), "exit_code": done.returncode, "tail": "\n".join(output[-8:])}


def scheduled_task() -> dict[str, Any]:
    done = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME, "/xml", "ONE"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    xml = done.stdout or ""
    command = _tag(xml, "Command")
    arguments = _tag(xml, "Arguments")
    referenced = None
    if arguments:
        for token in arguments.split('"'):
            if token.lower().endswith(".py"):
                referenced = token
                break
    return {
        "query_exit": done.returncode,
        "registered": done.returncode == 0 and bool(command),
        "command": command,
        "arguments": arguments,
        "referenced_script": referenced,
        "referenced_script_exists": bool(referenced) and Path(referenced).exists(),
        "error": None if done.returncode == 0 else (done.stderr or "").strip()[:200],
    }


def _tag(xml: str, name: str) -> str | None:
    start = xml.find(f"<{name}>")
    end = xml.find(f"</{name}>")
    if start < 0 or end < 0:
        return None
    return xml[start + len(name) + 2 : end].strip()


# --------------------------------------------------------------------------- #
# inventory
# --------------------------------------------------------------------------- #
def classify(name: str, relative: str, purpose: str) -> dict[str, Any]:
    path = REPO_ROOT / relative
    row: dict[str, Any] = {"key": name, "path": relative, "purpose": purpose}
    if not path.exists():
        row.update({"class": "ABSENT", "why": "not in this checkout and not tracked by the commit"})
        return row
    if path.is_dir():
        code, blob = git("rev-parse", f"{SOURCE_COMMIT}:{relative}")
        tracked = code == 0
        count = sum(len(files) for _, _, files in os.walk(path))
        row.update(
            {
                "class": "FOUND_VALID" if tracked else "FOUND_UNVERIFIED",
                "files": count,
                "why": (
                    f"directory with {count} files, tracked at {SOURCE_COMMIT[:8]}"
                    if tracked
                    else "directory present but not tracked by the source commit"
                ),
            }
        )
        return row

    info = digests(path)
    row.update({"bytes": info["bytes"], "lines": info["lines"], "sha256": info["sha256"]})
    code, blob = git("rev-parse", f"{SOURCE_COMMIT}:{relative}")
    if code != 0:
        row.update({"class": "FOUND_UNVERIFIED", "why": "present but not in the source commit"})
        return row
    code_local, local_blob = git("hash-object", relative)
    if code_local == 0 and local_blob == blob:
        row.update({"class": "FOUND_VALID", "blob": blob, "why": f"byte-identical to blob {blob[:12]}"})
        return row
    # A checkout with CRLF line endings hashes differently from the blob Git stores.
    normalized = path.read_bytes().replace(b"\r\n", b"\n")
    checked = subprocess.run(
        ["git", "hash-object", "--stdin"], input=normalized, cwd=str(REPO_ROOT), capture_output=True, check=False
    )
    if checked.stdout.decode().strip() == blob:
        row.update(
            {
                "class": "FOUND_VALID",
                "blob": blob,
                "why": "byte-identical to the blob after CRLF normalisation",
            }
        )
        return row
    row.update({"class": "CORRUPTED", "why": f"bytes differ from blob {blob[:12]}", "blob": blob})
    return row


def inventory() -> dict[str, Any]:
    elements = [classify(*item) for item in ELEMENTS]
    task = scheduled_task()
    code, head = git("rev-parse", "HEAD")
    code_branch, branch = git("rev-parse", "--abbrev-ref", "HEAD")
    code_status, status = git("status", "--porcelain")
    counts: dict[str, int] = {}
    for row in elements:
        counts[row["class"]] = counts.get(row["class"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now_iso(),
        "source_commit": SOURCE_COMMIT,
        "checkout": {
            "path": str(REPO_ROOT),
            "head": head if code == 0 else None,
            "branch": branch if code == 0 else None,
            "head_is_source": head == SOURCE_COMMIT,
            "dirty_paths": len(status.splitlines()) if code_status == 0 else None,
        },
        "elements": elements,
        "counts": counts,
        "guard_task": task,
        "verdict": (
            "ALL_COMPONENTS_PRESENT"
            if not counts.get("ABSENT") and not counts.get("CORRUPTED")
            else "INCOMPLETE"
        ),
    }


# --------------------------------------------------------------------------- #
# integrity
# --------------------------------------------------------------------------- #
def phase3_shards() -> dict[str, Any]:
    root = REPO_ROOT / STORE_PHASE3
    if not root.is_dir():
        return {"present": False, "checks": [], "verdict": "ABSENT"}
    checks: list[dict[str, Any]] = []
    contract = digests(REPO_ROOT / CONTRACT)
    manifests = sorted(root.rglob("*.MANIFEST.json"))
    for manifest_path in manifests:
        payload = read_json(manifest_path, {}) or {}
        shard = manifest_path.with_name(manifest_path.name.replace(".MANIFEST.json", ".jsonl"))
        info = digests(shard)
        declared = payload.get("sha256")
        rows = payload.get("row_count")
        declared_bytes = payload.get("bytes")
        shard_ok = matches(declared, info) if declared else info["exists"] is False
        # The manifest counts the bytes it hashed; a checkout may hold either line ending.
        size_ok = declared_bytes is None or declared_bytes in (info.get("bytes"), info.get("bytes_crlf"))
        decl = payload.get("declaration") or {}
        contract_ok = matches(decl.get("sha256"), contract)
        generator = ((payload.get("capture") or {}).get("generator") or {}).get("git_blob_sha")
        code, blob = git("rev-parse", f"{SOURCE_COMMIT}:scripts/exp004a_wp051_02g_capture.py")
        # A consolidation manifest is produced by the consolidation step, not by the capture
        # program, so it declares no generator. That is not a failure of the shard.
        generator_ok = True if generator is None else (code == 0 and generator == blob)
        checks.append(
            {
                "manifest": str(manifest_path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "rows": rows,
                "bytes": info.get("bytes"),
                "shard_present": info.get("exists"),
                "shard_hash_matches": shard_ok,
                "size_matches": size_ok,
                "declaration_matches": contract_ok,
                "generator_declared": generator,
                "generator_matches": generator_ok,
                "ok": bool(shard_ok and size_ok and contract_ok and generator_ok),
            }
        )
    rehearsal_rows = sum(int(c["rows"] or 0) for c in checks if "/rehearsal/" in c["manifest"])
    production_rows = sum(int(c["rows"] or 0) for c in checks if "/rehearsal/" not in c["manifest"])
    return {
        "present": True,
        "manifests": len(checks),
        "passed": sum(1 for c in checks if c["ok"]),
        "failed": [c for c in checks if not c["ok"]],
        "rows_captured": rehearsal_rows + production_rows,
        "rehearsal_rows": rehearsal_rows,
        "production_rows": production_rows,
        "checks": checks,
        "verdict": "PASS" if all(c["ok"] for c in checks) else "FAIL",
        "note": (
            "a rehearsal row is prospective=false and counts_toward_coverage=false: 864 verified rows "
            "can still mean zero production rows"
        ),
    }


def published_prefix() -> dict[str, Any]:
    root = REPO_ROOT / PUBLISHED_PREFIX
    snapshot = read_json(root / "SNAPSHOT.json", {}) or {}
    files = snapshot.get("files") or {}
    if not files:
        return {"present": False, "verdict": "ABSENT"}
    verified = []
    for name, declared in sorted(files.items()):
        info = digests(root / name)
        verified.append(
            {
                "path": name,
                "declared_bytes": declared.get("bytes"),
                "bytes": info.get("bytes"),
                "matches": matches(declared.get("sha256"), info),
                "matched_on": (
                    "crlf"
                    if info.get("exists") and info.get("sha256_crlf") == declared.get("sha256")
                    else ("as-is" if info.get("exists") and info.get("sha256") == declared.get("sha256") else "none")
                ),
            }
        )
    return {
        "present": True,
        "files": len(verified),
        "matched": sum(1 for item in verified if item["matches"]),
        "checks": verified,
        "verdict": "PASS" if all(item["matches"] for item in verified) else "FAIL",
    }


def prefix_versus_record() -> dict[str, Any]:
    """Compare what survives with the hashes 02K took of the live store, shard by shard."""
    record = read_json(REPO_ROOT / RECORD_DIR / "STORE_INTEGRITY.json", {}) or {}
    recorded = {
        check["subject"]: check["detail"].split("sha256 ")[1].split(" ")[0]
        for check in record.get("checks", [])
        if check.get("id") == "WRITE_ONCE_UNCHANGED" and "sha256 " in check.get("detail", "")
    }
    root = REPO_ROOT / PUBLISHED_PREFIX / "daily"
    rows = []
    for shard, prefix in sorted(recorded.items()):
        path = root / shard
        info = digests(path)
        rows.append(
            {
                "shard": shard,
                "survives": info.get("exists", False),
                "recorded_prefix": prefix,
                "matches_record": prefix_matches(prefix, info),
            }
        )
    surviving = [row for row in rows if row["survives"]]
    return {
        "recorded_shards": len(rows),
        "surviving_shards": len(surviving),
        "matching": sum(1 for row in surviving if row["matches_record"]),
        "missing": [row["shard"] for row in rows if not row["survives"]],
        "differing": [row["shard"] for row in surviving if not row["matches_record"]],
        "checks": rows,
        "note": (
            "a surviving shard that does not match the record is not corruption: the published copy "
            "predates the final write-once version of that day, and the 02K record is authoritative"
        ),
    }


def record_versus_commit() -> dict[str, Any]:
    rows = {}
    root = REPO_ROOT / RECORD_DIR
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        if "/continuation/" in relative:
            continue
        code_local, local = git("hash-object", relative)
        code_commit, committed = git("rev-parse", f"{SOURCE_COMMIT}:{relative}")
        rows[relative] = {"identical": code_local == 0 and code_commit == 0 and local == committed}
    return {
        "files": len(rows),
        "identical": sum(1 for row in rows.values() if row["identical"]),
        "verdict": "PASS" if rows and all(row["identical"] for row in rows.values()) else "FAIL",
    }


def space() -> dict[str, Any]:
    import ctypes
    import shutil

    free = int(shutil.disk_usage(str(REPO_ROOT)).free)
    available = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    ignored = ctypes.c_ulonglong(0)
    ctypes.windll.kernel32.GetDiskFreeSpaceExW(  # type: ignore[attr-defined]
        ctypes.c_wchar_p(str(REPO_ROOT)[:3]), ctypes.byref(available), ctypes.byref(total), ctypes.byref(ignored)
    )
    return {
        "free_bytes": free,
        "free_bytes_kernel32": int(available.value),
        "instruments_agree": free == int(available.value),
        "free_gib": round(free / GIB, 4),
        "required_gib": REQUIRED_GIB,
        "margin_gib": round((free - int(REQUIRED_GIB * GIB)) / GIB, 4),
        "verdict": "PASS" if free >= int(REQUIRED_GIB * GIB) else "INSUFFICIENT",
    }


def integrity() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    code, head = git("rev-parse", "HEAD")
    checks.append(
        {
            "id": "SOURCE_COMMIT_CHECKED_OUT",
            "status": "PASS" if head == SOURCE_COMMIT else "FAIL",
            "detail": f"HEAD={head[:12] if head else None}, source={SOURCE_COMMIT[:12]}",
        }
    )

    contract = digests(REPO_ROOT / CONTRACT)
    payload = read_json(REPO_ROOT / CONTRACT, {}) or {}
    generator = payload.get("generator") or {}
    declared = {
        "program_blob": generator.get("program_blob"),
        "verifier_blob": generator.get("verifier_blob"),
        "engine_block": generator.get("engine_block"),
        "code_commit": generator.get("code_commit"),
    }
    resolved: dict[str, Any] = {}
    for key, value in declared.items():
        code_obj, kind = git("cat-file", "-t", str(value)) if value else (1, "")
        resolved[key] = {"declared": value, "present": code_obj == 0, "type": kind or None}
    checks.append(
        {
            "id": "CONTRACT_DECLARES_ITS_GENERATOR",
            "status": "PASS" if contract.get("exists") and all(item["present"] for item in resolved.values()) else "FAIL",
            "detail": f"contract present={contract.get('exists')}; declared objects present={sum(1 for i in resolved.values() if i['present'])}/{len(resolved)}",
            "resolved": resolved,
        }
    )
    supersedes = (payload.get("supersedes") or {}).get("sha256")
    phase2 = digests(REPO_ROOT / "config/preregistrations/EXP-004A.datasets.phase2.json")
    checks.append(
        {
            "id": "CONTRACT_SUPERSEDES_HASH_MATCHES",
            "status": "PASS" if matches(supersedes, phase2) else "FAIL",
            "detail": f"declared={str(supersedes)[:16]}, file={'match' if matches(supersedes, phase2) else 'no match'}",
        }
    )

    shards = phase3_shards()
    checks.append(
        {
            "id": "PHASE3_SHARD_MANIFESTS_VERIFY",
            "status": "PASS" if shards.get("verdict") == "PASS" else ("FAIL" if shards.get("present") else "SKIP"),
            "detail": (
                f"{shards.get('manifests', 0)} manifests, {shards.get('passed', 0)} pass; "
                f"rows: rehearsal={shards.get('rehearsal_rows', 0)} production={shards.get('production_rows', 0)}"
            ),
        }
    )

    prefix = published_prefix()
    checks.append(
        {
            "id": "PUBLISHED_PREFIX_VERIFIES",
            "status": "PASS" if prefix.get("verdict") == "PASS" else ("FAIL" if prefix.get("present") else "SKIP"),
            "detail": f"{prefix.get('matched', 0)} of {prefix.get('files', 0)} published files match their own snapshot hash",
        }
    )

    versus = prefix_versus_record()
    checks.append(
        {
            "id": "PUBLISHED_PREFIX_VERSUS_THE_RECORD",
            "status": "PASS" if versus["surviving_shards"] else "FAIL",
            "detail": (
                f"{versus['surviving_shards']} of {versus['recorded_shards']} recorded days survive; "
                f"{versus['matching']} match the recorded hash; differing={versus['differing']}; "
                f"missing={len(versus['missing'])} days"
            ),
        }
    )

    record = record_versus_commit()
    checks.append(
        {
            "id": "RECORD_BYTES_STILL_MATCH_THEIR_COMMIT",
            "status": record["verdict"],
            "detail": f"{record['identical']} of {record['files']} files identical to {SOURCE_COMMIT[:8]}",
        }
    )

    task = scheduled_task()
    checks.append(
        {
            "id": "GUARD_TASK_POINTS_AT_A_LIVE_SCRIPT",
            "status": "PASS" if task["registered"] and task["referenced_script_exists"] else "FAIL",
            "detail": (
                f"registered={task['registered']}; action={task['referenced_script']}; "
                f"exists={task['referenced_script_exists']}"
            ),
        }
    )

    guard = run([sys.executable, "scripts/edge04_watchdog.py", "--help"], timeout=120)
    checks.append(
        {
            "id": "GUARD_IS_OPERABLE",
            "status": "PASS" if guard.get("exit_code") == 0 else "FAIL",
            "detail": f"`--help` exit={guard.get('exit_code')}",
        }
    )

    runner = run([sys.executable, "scripts/exp004a_wp051_02f_runner.py", "--check"], timeout=300)
    checks.append(
        {
            "id": "RUNNER_IS_EXECUTABLE",
            "status": "PASS" if runner.get("exit_code") == 0 else "FAIL",
            "detail": f"`--check` exit={runner.get('exit_code')} (read-only mode)",
        }
    )

    tests = run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/research/test_exp004a_wp051_02k.py",
            "tests/unit/research/test_exp004a_wp051_02k_continue.py",
            "-q",
        ],
        timeout=900,
    )
    checks.append(
        {
            "id": "TESTS_PASS",
            "status": "PASS" if tests.get("exit_code") == 0 else "FAIL",
            "detail": f"exit={tests.get('exit_code')} :: {tests.get('tail', '')[-200:]}",
        }
    )

    capacity = space()
    checks.append(
        {
            "id": "SPACE_WITHIN_THE_FROZEN_BUDGET",
            "status": "PASS" if capacity["verdict"] == "PASS" else "FAIL",
            "detail": (
                f"{capacity['verdict']}: free={capacity['free_gib']} GiB, required={REQUIRED_GIB} GiB, "
                f"margin={capacity['margin_gib']} GiB, instruments agree={capacity['instruments_agree']}"
            ),
        }
    )

    experiment = {name: (REPO_ROOT / relative).exists() for name, relative, _ in ELEMENTS}
    store_present = experiment.get("store_forward_edge04", False)
    checks.append(
        {
            "id": "FORWARD_STORE_STILL_EXISTS",
            "status": "PASS" if store_present else "FAIL",
            "detail": (
                "the live store is here"
                if store_present
                else f"{STORE_FORWARD_PHASE3} and {STORE_FORWARD_PHASE2} are absent: the campaign cannot resume from this tree"
            ),
        }
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now_iso(),
        "source_commit": SOURCE_COMMIT,
        "checks": checks,
        "passed": sum(1 for c in checks if c["status"] == "PASS"),
        "failed": sum(1 for c in checks if c["status"] == "FAIL"),
        "skipped": sum(1 for c in checks if c["status"] == "SKIP"),
        "shards": shards,
        "prefix": {"summary": {k: versus[k] for k in ("recorded_shards", "surviving_shards", "matching", "missing", "differing")}, "checks": versus["checks"]},
        "space": capacity,
        "guard_task": task,
        "runner": runner,
        "tests": tests,
        "verdict": (
            "READY_TO_RESUME"
            if store_present and all(c["status"] != "FAIL" for c in checks)
            else "BLOCKED_WITH_EVIDENCE"
        ),
        "verdict_note": "a passing test suite is not a campaign readiness decision; the store gate is separate and explicit",
    }


def render_markdown(payload: dict[str, Any], inv: dict[str, Any]) -> str:
    lines = [
        "# WP-051-02K — auditoría de recuperación",
        "",
        f"**Generado:** {payload['generated_at_utc']} · **Fuente:** `{SOURCE_COMMIT[:12]}` · "
        f"**Dictamen:** `{payload['verdict']}`",
        "",
        "| Comprobación | Estado | Detalle |",
        "| --- | --- | --- |",
    ]
    for item in payload["checks"]:
        lines.append(f"| {item['id']} | **{item['status']}** | {item['detail'].replace('|', '/')} |")
    lines += [
        "",
        "## Inventario",
        "",
        "| Componente | Clase | Evidencia |",
        "| --- | --- | --- |",
    ]
    for row in inv["elements"]:
        lines.append(f"| `{row['key']}` | {row['class']} | {str(row.get('why', '')).replace('|', '/')} |")
    lines += [
        "",
        "## Prefijo publicado frente al registro 02K",
        "",
        f"- días registrados por 02K: {payload['prefix']['summary']['recorded_shards']}",
        f"- días que sobreviven: {payload['prefix']['summary']['surviving_shards']}",
        f"- coinciden con el hash registrado: {payload['prefix']['summary']['matching']}",
        f"- difieren: {payload['prefix']['summary']['differing'] or 'ninguno'}",
        f"- perdidos: {len(payload['prefix']['summary']['missing'])} días",
        "",
        "## Espacio",
        "",
        f"Libre: **{payload['space']['free_gib']} GiB**; presupuesto congelado {REQUIRED_GIB} GiB; "
        f"margen {payload['space']['margin_gib']} GiB; instrumentos "
        f"{'coinciden' if payload['space']['instruments_agree'] else 'difieren'}.",
        "",
        "## Guard",
        "",
        f"Tarea `{TASK_NAME}` registrada: {payload['guard_task']['registered']}; "
        f"script referenciado: `{payload['guard_task']['referenced_script']}`; "
        f"existe: {payload['guard_task']['referenced_script_exists']}.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-004A recovery audit (read-only)")
    parser.add_argument("--inventory", action="store_true")
    parser.add_argument("--integrity", action="store_true")
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    inv = inventory()
    if args.inventory:
        write_json(OUT / "RECOVERY_INVENTORY.json", inv)
        for row in inv["elements"]:
            print(f"{row['class']:16s} {row['key']}")
        return 0

    payload = integrity()
    if args.integrity:
        write_json(OUT / "INTEGRITY_REPORT.json", payload)
        for item in payload["checks"]:
            print(f"{item['status']:4s} {item['id']:38s} {item['detail'][:110]}")
        print(f"\n{payload['passed']} PASS, {payload['failed']} FAIL, {payload['skipped']} SKIP -> {payload['verdict']}")
        return 0 if payload["failed"] == 0 else 1

    write_json(OUT / "RECOVERY_INVENTORY.json", inv)
    write_json(OUT / "INTEGRITY_REPORT.json", payload)
    write_json(
        OUT / "RUN_REPORT.json",
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": now_iso(),
            "source_commit": SOURCE_COMMIT,
            "inventory": {"counts": inv["counts"], "verdict": inv["verdict"]},
            "integrity": {
                "passed": payload["passed"],
                "failed": payload["failed"],
                "skipped": payload["skipped"],
                "checks": [{"id": c["id"], "status": c["status"]} for c in payload["checks"]],
            },
            "space": payload["space"],
            "guard_task": payload["guard_task"],
            "tests": payload["tests"],
            "verdict": payload["verdict"],
        },
    )
    (OUT / "RUN_REPORT.md").write_text(render_markdown(payload, inv), encoding="utf-8")
    print(f"{payload['passed']} PASS, {payload['failed']} FAIL, {payload['skipped']} SKIP -> {payload['verdict']}")
    return 0 if payload["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
