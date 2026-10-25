"""RFC-TDM-013 — the six negative controls the verifier must survive.

Every control injects a specific corruption into a throwaway copy, runs the real
verifier against that copy, and records three things: a non-zero exit, the failure
identifier the code emitted, and the evidence that the intended control — not some
unrelated crash — is what fired. A control that "fails" for the wrong reason is
recorded as NOT_PROVEN.

Nothing here touches the worktree: each sandbox is created under
``.tdm13/controls/`` and removed afterwards, whatever the outcome.

Usage::  python scripts/tdm13_negative_controls.py [--keep]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ART = REPO_ROOT / ".tdm13"
EVIDENCE = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-13"
VERIFIER = REPO_ROOT / "scripts" / "tdm13_independent_verify.py"
INPUTS = REPO_ROOT / "scripts" / "tdm13_inputs.py"
REPLAY = REPO_ROOT / "scripts" / "tdm13_replay.py"
PYTHON = sys.executable

#: Tasks copied into a sandbox: only what the audits read.
COPIED_TREES = (
    "evidence/tdm/wp-tdm-12",
    "evidence/tdm/wp-tdm-11",
    "evidence/tdm/wp-tdm-13",
    "scripts",
)


def _run(args: list[str], *, env_extra: dict[str, str], cwd: Path) -> dict[str, Any]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", **env_extra}
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env, check=False)
    return {
        "command": " ".join(str(a) for a in args),
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip().splitlines()[-12:],
        "stderr": proc.stderr.strip().splitlines()[-6:],
    }


def _sandbox(name: str) -> Path:
    base = ART / "controls"
    base.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=base))
    for rel in COPIED_TREES:
        source = REPO_ROOT / rel
        if source.is_dir():
            shutil.copytree(source, path / rel, dirs_exist_ok=True)
        elif source.is_file():
            (path / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, path / rel)
    return path


def _control(
    control_id: str,
    name: str,
    injected: str,
    run: dict[str, Any],
    expected_token: str,
) -> dict[str, Any]:
    """A control is PROVEN only when the run fails *and* names the expected cause."""
    # Search only what the run actually printed: including the expected token in
    # the haystack would make every control look proven, which is the exact
    # failure mode this file exists to prevent.
    haystack = "\n".join(run.get("stdout") or []) + "\n" + "\n".join(run.get("stderr") or [])
    token_seen = expected_token in haystack
    rejected = run["exit_code"] != 0
    status = "PROVEN" if rejected and token_seen else "NOT_PROVEN"
    return {
        "id": control_id,
        "name": name,
        "injected": injected,
        "run": run,
        "expected_token": expected_token,
        "rejected": rejected,
        "expected_token_seen": token_seen,
        "status": status,
    }


# ---------------------------------------------------------------------------
# 1. one mutated dataset byte -> SHA-256 rejection
# ---------------------------------------------------------------------------
def control_dataset_byte(sandbox: Path) -> dict[str, Any]:
    manifest_path = sandbox / "evidence/tdm/wp-tdm-13/DATASET_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = sandbox / manifest["datasets"][0]["path"]
    data = bytearray(target.read_bytes())
    data[0] = data[0] ^ 0xFF
    target.write_bytes(bytes(data))
    run = _run(
        [PYTHON, str(INPUTS), "verify"],
        env_extra={"TDM13_REPO": str(sandbox)},
        cwd=sandbox,
    )
    return _control(
        "NC-01", "mutated dataset byte", f"flipped first byte of {target.name}", run, "FAIL"
    )


# ---------------------------------------------------------------------------
# 2. a required dataset removed -> missing-input rejection
# ---------------------------------------------------------------------------
def control_dataset_missing(sandbox: Path) -> dict[str, Any]:
    manifest = json.loads(
        (sandbox / "evidence/tdm/wp-tdm-13/DATASET_MANIFEST.json").read_text(encoding="utf-8")
    )
    victim = sandbox / manifest["datasets"][1]["path"]
    victim.unlink()
    run = _run(
        [PYTHON, str(INPUTS), "verify"],
        env_extra={"TDM13_REPO": str(sandbox)},
        cwd=sandbox,
    )
    return _control("NC-02", "required dataset removed", f"deleted {victim.name}", run, "missing")


# ---------------------------------------------------------------------------
# 3. a claim in RUN_REPORT.json altered -> inconsistency rejection
# ---------------------------------------------------------------------------
def control_claim_altered(sandbox: Path) -> dict[str, Any]:
    path = sandbox / "evidence/tdm/wp-tdm-12/RUN_REPORT.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    original = document["metrics"]["tdm11_review"]["net_mean"]
    document["metrics"]["tdm11_review"]["net_mean"] = round(original + 1.0, 4)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    run = _run(
        [PYTHON, str(VERIFIER), "audit-claims", "--from-dir", str(sandbox)],
        env_extra={"TDM13_REPO": str(sandbox)},
        cwd=sandbox,
    )
    return _control(
        "NC-03",
        "altered claim in RUN_REPORT.json",
        f"net_mean {original} -> {document['metrics']['tdm11_review']['net_mean']}",
        run,
        "net_mean_matches_manifest",
    )


# ---------------------------------------------------------------------------
# 4. unresolvable / non-ancestor commit -> lineage rejection
# ---------------------------------------------------------------------------
def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def control_lineage(sandbox: Path) -> dict[str, Any]:
    _git(["init", "-q", "-b", "evidence/tdm12"], sandbox)
    _git(["-c", "user.email=verifier@tdm13", "-c", "user.name=tdm13", "add", "-A"], sandbox)
    _git(
        [
            "-c",
            "user.email=verifier@tdm13",
            "-c",
            "user.name=tdm13",
            "commit",
            "-q",
            "-m",
            "sandbox baseline",
        ],
        sandbox,
    )
    orphan_base = _git(["rev-parse", "HEAD"], sandbox)
    (sandbox / "sandbox_marker.txt").write_text("second commit\n", encoding="utf-8")
    _git(["-c", "user.email=verifier@tdm13", "-c", "user.name=tdm13", "add", "-A"], sandbox)
    _git(
        [
            "-c",
            "user.email=verifier@tdm13",
            "-c",
            "user.name=tdm13",
            "commit",
            "-q",
            "-m",
            "sandbox target",
        ],
        sandbox,
    )
    target = _git(["rev-parse", "HEAD"], sandbox)
    # Declare a baseline that is NOT the parent of the target.
    run = _run(
        [PYTHON, str(VERIFIER), "audit-git"],
        env_extra={
            "TDM13_REPO": str(sandbox),
            "TDM13_TARGET": target,
            "TDM13_BASELINE": target,
        },
        cwd=sandbox,
    )
    return _control(
        "NC-04",
        "non-ancestor baseline commit",
        f"declared baseline={target[:8]} (real parent {orphan_base[:8]})",
        run,
        "target_parent_is_baseline",
    )


# ---------------------------------------------------------------------------
# 5. altered evidence blob -> digest rejection naming the file
# ---------------------------------------------------------------------------
def control_digest(sandbox: Path) -> dict[str, Any]:
    _git(["init", "-q", "-b", "evidence/tdm12"], sandbox)
    _git(["-c", "user.email=verifier@tdm13", "-c", "user.name=tdm13", "add", "-A"], sandbox)
    _git(
        [
            "-c",
            "user.email=verifier@tdm13",
            "-c",
            "user.name=tdm13",
            "commit",
            "-q",
            "-m",
            "sandbox baseline",
        ],
        sandbox,
    )
    baseline = _git(["rev-parse", "HEAD"], sandbox)
    manifest_before = json.loads(
        (sandbox / "evidence/tdm/wp-tdm-12/RUN_REPORT.json").read_text(encoding="utf-8")
    )
    victim_name = sorted(manifest_before["evidence_sha256"])[0]
    victim = sandbox / "evidence/tdm/wp-tdm-12" / victim_name
    victim.write_bytes(victim.read_bytes() + b"\nmutated by NC-05\n")
    _git(["-c", "user.email=verifier@tdm13", "-c", "user.name=tdm13", "add", "-A"], sandbox)
    _git(
        [
            "-c",
            "user.email=verifier@tdm13",
            "-c",
            "user.name=tdm13",
            "commit",
            "-q",
            "-m",
            "sandbox evidence",
        ],
        sandbox,
    )
    target = _git(["rev-parse", "HEAD"], sandbox)
    run = _run(
        [PYTHON, str(VERIFIER), "audit-git"],
        env_extra={
            "TDM13_REPO": str(sandbox),
            "TDM13_TARGET": target,
            "TDM13_BASELINE": baseline,
        },
        cwd=sandbox,
    )
    return _control(
        "NC-05",
        "altered evidence blob",
        f"appended bytes to {victim_name}",
        run,
        victim_name,
    )


# ---------------------------------------------------------------------------
# 6. timeout -> INCOMPLETE, never PASS
# ---------------------------------------------------------------------------
def control_timeout(sandbox: Path) -> dict[str, Any]:
    """A hanging phase must end as TIMEOUT/INCOMPLETE and never write PASS."""
    hang = sandbox / "scripts" / "tdm12_review.py"
    hang.write_text(
        "import time\n\n\ntime.sleep(30)\nprint('this should never be reached')\n",
        encoding="utf-8",
    )
    # The sandbox is also the clone: a stub manifest with no datasets keeps the
    # input gate out of the way, so the only thing under test is the timeout.
    (sandbox / "evidence/tdm/wp-tdm-13").mkdir(parents=True, exist_ok=True)
    (sandbox / "evidence/tdm/wp-tdm-13/DATASET_MANIFEST.json").write_text(
        json.dumps({"schema_version": "stub", "datasets": [], "input_state": "UNKNOWN"}),
        encoding="utf-8",
    )
    (sandbox / ".tdm12").mkdir(parents=True, exist_ok=True)
    (sandbox / "evidence/tdm/wp-tdm-12").mkdir(parents=True, exist_ok=True)
    (sandbox / "evidence/tdm/wp-tdm-12/RUN_REPORT.json").write_text(
        json.dumps({"metrics": {"tdm11_review": {}}, "independence_status": "x"}),
        encoding="utf-8",
    )
    _git(["init", "-q", "-b", "evidence/tdm12"], sandbox)
    _git(["-c", "user.email=verifier@tdm13", "-c", "user.name=tdm13", "add", "-A"], sandbox)
    _git(
        [
            "-c",
            "user.email=verifier@tdm13",
            "-c",
            "user.name=tdm13",
            "commit",
            "-q",
            "-m",
            "timeout sandbox",
        ],
        sandbox,
    )
    stub_head = _git(["rev-parse", "HEAD"], sandbox)
    started = time.time()
    run = _run(
        [
            PYTHON,
            str(REPLAY),
            "--clone",
            str(sandbox),
            "--target-commit",
            stub_head,
            "--review-timeout",
            "2",
            "--inventory-timeout",
            "2",
            "--out",
            str(sandbox / ".tdm13" / "replay.json"),
            "--python",
            PYTHON,
        ],
        env_extra={"TDM13_REPO": str(sandbox)},
        cwd=sandbox,
    )
    replay_payload: dict[str, Any] = {}
    produced = sandbox / ".tdm13" / "replay.json"
    if produced.is_file():
        replay_payload = json.loads(produced.read_text(encoding="utf-8"))
    control = _control(
        "NC-06",
        "inventory/review timeout",
        "replaced tdm12_review.py with a 30s sleep, timeout fixed at 2s",
        run,
        "TIMEOUT",
    )
    control["observed_status"] = replay_payload.get("status")
    control["observed_phase_status"] = [
        {"phase": p["phase"], "status": p["status"]} for p in replay_payload.get("phases", [])
    ]
    control["elapsed_seconds"] = round(time.time() - started, 1)
    control["never_pass"] = replay_payload.get("status") != "PASS"
    if control["status"] == "PROVEN" and not control["never_pass"]:
        control["status"] = "NOT_PROVEN"
    return control


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", action="store_true", help="keep sandboxes for inspection")
    args = parser.parse_args(argv)

    ART.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    controls = (
        ("NC-01", control_dataset_byte),
        ("NC-02", control_dataset_missing),
        ("NC-03", control_claim_altered),
        ("NC-04", control_lineage),
        ("NC-05", control_digest),
        ("NC-06", control_timeout),
    )
    for control_id, function in controls:
        sandbox = _sandbox(control_id.lower())
        try:
            result = function(sandbox)
        finally:
            if not args.keep:
                shutil.rmtree(sandbox, ignore_errors=True)
            else:
                print(f"  kept {sandbox}")
        results.append(result)
        print(
            f"  {result['id']} {result['status']:10s} exit={result['run']['exit_code']} "
            f"{result['name']}"
        )

    proven = [r for r in results if r["status"] == "PROVEN"]
    payload = {
        "rfc_id": "RFC-TDM-013",
        "phase": "WP-13C negative controls",
        "verifier_id": "tdm13-independent-verifier/1",
        "python": sys.version.split()[0],
        "controls": results,
        "proven": len(proven),
        "total": len(results),
        "status": "PASS" if len(proven) == len(results) else "FAIL",
        "failures": [
            {"id": r["id"], "name": r["name"], "status": r["status"]}
            for r in results
            if r["status"] != "PROVEN"
        ],
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "NEGATIVE_CONTROLS.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (ART / "negative_controls.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(f"negative controls {payload['proven']}/{payload['total']} proven -> {payload['status']}")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
