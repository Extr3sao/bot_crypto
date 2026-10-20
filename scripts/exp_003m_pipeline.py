"""exp_003m_pipeline — one command to generate, verify and seal, in that order.

    ./.venv/Scripts/python.exe scripts/exp_003m_pipeline.py generate
    ./.venv/Scripts/python.exe scripts/exp_003m_pipeline.py verify [--online]
    ./.venv/Scripts/python.exe scripts/exp_003m_pipeline.py seal
    ./.venv/Scripts/python.exe scripts/exp_003m_pipeline.py idempotent
    ./.venv/Scripts/python.exe scripts/exp_003m_pipeline.py status

Why a pipeline instead of a list of commands in a README: EXP-003L ended with a seal that
had been broken by running the verifier *after* the report, which rewrote a sealed file.
The repair was manual. Here the order is code:

* ``generate`` refuses to run if a seal already exists (a sealed experiment is not
  regenerated in place);
* ``verify`` writes nothing once ``SEAL.json`` exists — the verifier module refuses, and
  this entry point never overrides it;
* ``seal`` refuses unless the pre-seal verification has zero failures, all nine
  deliverables exist, and the tree has no unplanned files.

The manifest covers every file in the tree except ``raw/`` (download cache),
``SHA256SUMS.txt`` and ``SEAL.json``: a manifest that hashed itself would be a circular
hash, and a manifest built from ``ls | head`` would silently seal a truncated list.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "ai-bots" / "EXP-003M-MAKER-FILL-REALITY-001"
PREDECESSOR = REPO / "reports" / "ai-bots" / "EXP-003L-EXECUTION-ECONOMICS-001"
PYTHON = str(REPO / ".venv" / "Scripts" / "python.exe")

DELIVERABLES = [
    "BASELINE.md",
    "EXECUTION_MODEL.md",
    "FILL_REALISM.md",
    "ECONOMICS_COMPARISON.md",
    "CANDIDATE_DECISION.md",
    "RUN_REPORT.md",
    "RUN_REPORT.json",
    "INDEPENDENT_VERIFICATION.md",
    "FINAL_REPORT.md",
]
DERIVED = [
    "analysis/FILL_MODEL.json",
    "analysis/ECONOMICS.json",
    "analysis/DECISION.json",
]
EXCLUDES = ("raw/", "SHA256SUMS.txt", "SEAL.json", "DATASET_SHA256SUMS.txt")
STAGE_ORDER = ["preregister", "tape", "fills", "compare", "tests", "verify", "report", "seal"]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def run_stage(script: str, *args: str, out: Path) -> int:
    argv = [PYTHON, str(REPO / "scripts" / script), *args, "--out", str(out)]
    print(f"[003m] $ {' '.join(argv)}", flush=True)
    result = subprocess.run(argv, cwd=REPO, check=False)
    if result.returncode != 0:
        raise SystemExit(f"[003m] FAILED — {script} exited {result.returncode}")
    return result.returncode


# ---------------------------------------------------------------------------------------
# Tests: real subprocesses, real exit codes, recorded rather than asserted.
# ---------------------------------------------------------------------------------------

PYTEST_RE = re.compile(r"(\d+) (passed|failed|skipped|error)")


def execute_tests(out: Path) -> dict[str, Any]:
    scripts = sorted(glob.glob(str(REPO / "scripts" / "exp_003m_*.py")))
    tests = sorted(glob.glob(str(REPO / "tests" / "unit" / "reports" / "test_exp_003m_*.py")))
    if not tests:
        raise SystemExit("[003m] BLOCKED — no 003M tests found; nothing could be verified")
    commands: list[dict[str, Any]] = []

    def record(name: str, argv: list[str]) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, check=False)
        return result

    pytest_argv = [PYTHON, "-m", "pytest", *tests, "-q"]
    result = record("pytest", pytest_argv)
    counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    for match in PYTEST_RE.finditer(result.stdout):
        counts[match.group(2)] += int(match.group(1))
    commands.append(
        {
            "name": "pytest",
            "argv": "python -m pytest tests/unit/reports/test_exp_003m_*.py -q",
            "exit_code": result.returncode,
            "summary": (
                f"{counts['passed']} passed, {counts['failed']} failed, "
                f"{counts['skipped']} skipped"
            ),
            "counts": counts,
        }
    )

    ruff_argv = [PYTHON, "-m", "ruff", "check", *scripts, *tests]
    result = record("ruff", ruff_argv)
    commands.append(
        {
            "name": "ruff",
            "argv": "python -m ruff check scripts/exp_003m_*.py tests/unit/reports/test_exp_003m_*.py",
            "exit_code": result.returncode,
            "summary": "clean" if result.returncode == 0 else result.stdout.strip().splitlines()[-1:] or ["failed"],
            "counts": {},
        }
    )

    mypy_argv = [PYTHON, "-m", "mypy", "--strict", *scripts]
    result = record("mypy", mypy_argv)
    tail = [line for line in result.stdout.strip().splitlines() if line.strip()][-1:] or ["no output"]
    commands.append(
        {
            "name": "mypy",
            "argv": "python -m mypy --strict scripts/exp_003m_*.py",
            "exit_code": result.returncode,
            "summary": tail[0],
            "counts": {},
        }
    )

    totals = {
        "passed": sum(command["counts"].get("passed", 0) for command in commands),
        "failed": sum(command["counts"].get("failed", 0) for command in commands)
        + sum(1 for command in commands if command["exit_code"] != 0),
        "skipped": sum(command["counts"].get("skipped", 0) for command in commands),
    }
    payload = {
        "schema_version": "AI_BOTS_003M_TESTS_V1",
        "experiment": "EXP-003M-MAKER-FILL-REALITY-001",
        "commands": commands,
        "totals": totals,
        "all_passed": all(command["exit_code"] == 0 for command in commands),
        "note": "exit codes are recorded as produced; a failure stops the pipeline before the seal",
    }
    _write_json(out / "analysis" / "TESTS.json", payload)
    if not payload["all_passed"]:
        for command in commands:
            if command["exit_code"] != 0:
                print(
                    f"[003m] TESTS FAILED — {command['name']} exit {command['exit_code']}: "
                    f"{command['summary']}",
                    file=sys.stderr,
                )
        raise SystemExit(1)
    print(
        f"[003m] tests: {totals['passed']} passed, {totals['failed']} failed, "
        f"{totals['skipped']} skipped"
    )
    return payload


# ---------------------------------------------------------------------------------------
# Seal
# ---------------------------------------------------------------------------------------


def tree_files(out: Path) -> list[str]:
    """Every published file, complete: os.walk, not a truncated listing.

    The downloaded data is deliberately *not* in this list. It is regenerable, it is not
    published in git, and a manifest that sealed it would make a clean checkout fail
    ``sha256sum -c`` on files that are supposed to be re-fetched. Its digests live in
    ``DATASET_SHA256SUMS.txt`` and in ``dataset/TAPE_MANIFEST.json`` instead.
    """

    files: list[str] = []
    for root, _directories, names in os.walk(out):
        rel_root = Path(root).relative_to(out)
        if rel_root.parts and rel_root.parts[0] in ("raw",):
            continue
        for name in names:
            relative = (rel_root / name).as_posix() if rel_root.parts else name
            if any(relative == exclude or relative.startswith(exclude) for exclude in EXCLUDES):
                continue
            if rel_root.parts and rel_root.parts[0] == "dataset" and name.endswith(".gz"):
                continue
            files.append(relative)
    return sorted(files)


def dataset_files(out: Path) -> list[str]:
    """The downloaded rows: sealed separately, because they are regenerable and heavy."""

    root = out / "dataset"
    if not root.is_dir():
        return []
    return sorted(
        path.relative_to(out).as_posix() for path in root.rglob("*.gz") if path.is_file()
    )


def missing_deliverables(out: Path) -> list[str]:
    return [name for name in DELIVERABLES if not (out / name).exists()]


def seal(out: Path) -> int:
    marker = out / "SEAL.json"
    if marker.exists():
        print(f"[003m] already sealed: {marker} (delete it deliberately to reseal)")
        return 0
    verification_path = out / "analysis" / "VERIFICATION.json"
    if not verification_path.exists():
        raise SystemExit("[003m] REFUSED — verify before sealing")
    verification = _read_json(verification_path)
    summary = verification["summary"]
    if summary["failed"]:
        raise SystemExit(
            f"[003m] REFUSED — verification has {summary['failed']} failures: "
            f"{summary['failed_names']}"
        )
    missing = missing_deliverables(out)
    if missing:
        raise SystemExit(f"[003m] REFUSED — missing deliverables: {missing}")
    tests = _read_json(out / "analysis" / "TESTS.json")
    if not tests["all_passed"]:
        raise SystemExit("[003m] REFUSED — the recorded test run did not pass")

    data = dataset_files(out)
    data_manifest = out / "DATASET_SHA256SUMS.txt"
    if data:
        data_manifest.write_text(
            "\n".join(f"{_sha256(out / relative)}  {relative}" for relative in data) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    files = tree_files(out)
    lines = [f"{_sha256(out / relative)}  {relative}" for relative in files]
    manifest = out / "SHA256SUMS.txt"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    plan_digest = hashlib.sha256("\n".join(files).encode("utf-8")).hexdigest()
    provenance = _read_json(out / "analysis" / "PROVENANCE.json")
    _write_json(
        marker,
        {
            "schema_version": "AI_BOTS_003M_SEAL_V1",
            "experiment": "EXP-003M-MAKER-FILL-REALITY-001",
            "manifest": "SHA256SUMS.txt",
            "manifest_sha256": _sha256(manifest),
            "files": len(files),
            "dataset_manifest": "DATASET_SHA256SUMS.txt" if data else None,
            "dataset_manifest_sha256": _sha256(data_manifest) if data else None,
            "dataset_files": len(data),
            "excludes": list(EXCLUDES),
            "order": STAGE_ORDER,
            "plan_sha256": plan_digest,
            "deliverables": DELIVERABLES,
            "pre_seal_verification_sha256": _sha256(verification_path),
            "pre_seal_verification": {
                "checks": summary["checks"],
                "passed": summary["passed"],
                "failed": summary["failed"],
                "not_executed": summary["not_executed"],
                "negative_controls_detected": summary["negative_controls_detected"],
            },
            "tests_sha256": _sha256(out / "analysis" / "TESTS.json"),
            "sealed_commit": provenance["commit"],
            "sealed_dirty_paths_sha256": provenance["dirty_paths_sha256"],
            "predecessor_seal_sha256": _sha256(PREDECESSOR / "SHA256SUMS.txt"),
            "self_reference": "none: SHA256SUMS.txt and SEAL.json are excluded by construction",
        },
    )
    print(f"[003m] sealed {len(files)} files; manifest {_sha256(manifest)[:16]}")
    return 0


# ---------------------------------------------------------------------------------------
# Read-only verification of the seal
# ---------------------------------------------------------------------------------------


def verify_seal(out: Path) -> dict[str, Any]:
    manifest = out / "SHA256SUMS.txt"
    marker = out / "SEAL.json"
    if not manifest.exists() or not marker.exists():
        return {"status": "NOT_SEALED", "ok": False}
    payload = _read_json(marker)
    listed: dict[str, str] = {}
    problems: list[str] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split(maxsplit=1)
        listed[relative.strip()] = digest
    data_manifest = out / "DATASET_SHA256SUMS.txt"
    data_listed: dict[str, str] = {}
    if data_manifest.exists():
        for line in data_manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            digest, relative = line.split(maxsplit=1)
            data_listed[relative.strip()] = digest
    for relative, expected in {**listed, **data_listed}.items():
        target = out / relative
        if not target.exists():
            problems.append(f"missing: {relative}")
        elif _sha256(target) != expected:
            problems.append(f"altered: {relative}")
    actual = set(tree_files(out)) | set(dataset_files(out))
    extra = sorted(actual - set(listed) - set(data_listed))
    if extra:
        problems.append(f"unsealed files: {extra[:5]}")
    if payload.get("files") != len(listed):
        problems.append("manifest count disagrees with SEAL.json")
    if payload.get("dataset_files") != len(data_listed):
        problems.append("dataset count disagrees with SEAL.json")
    if payload.get("manifest_sha256") != _sha256(manifest):
        problems.append("manifest digest disagrees with SEAL.json")
    if data_listed and payload.get("dataset_manifest_sha256") != _sha256(data_manifest):
        problems.append("dataset manifest digest disagrees with SEAL.json")
    return {
        "status": "PASS" if not problems else "FAIL",
        "ok": not problems,
        "files": len(listed),
        "dataset_files": len(data_listed),
        "problems": problems[:10],
    }


# ---------------------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------------------


def generate(out: Path) -> int:
    if (out / "SEAL.json").exists():
        raise SystemExit(
            "[003m] REFUSED — the experiment is sealed; regenerate into a scratch --out "
            "instead of rewriting evidence"
        )
    run_stage("exp_003m_preregister.py", out=out)
    run_stage("exp_003m_tape.py", out=out)
    run_stage("exp_003m_fills.py", out=out)
    run_stage("exp_003m_compare.py", out=out)
    execute_tests(out)
    #: Verification runs *before* the report and before the seal, and it re-downloads a
    #: sample of the archives: a pre-seal pass that never touched the source would be a
    #: statement about this disk, not about the exchange's tape.
    run_stage("exp_003m_verify.py", "--write", "--online", out=out)
    run_stage("exp_003m_report.py", out=out)
    print("[003m] generated; run `verify` then `seal`")
    return 0


def verify(out: Path, *, online: bool) -> int:
    sys.path.insert(0, str(REPO / "scripts"))
    from exp_003m_verify import run

    payload = run(out, online=online)
    summary = payload["summary"]
    seal_result = verify_seal(out)
    print(
        f"[003m] checks: {summary['passed']}/{summary['checks']} PASS, "
        f"{summary['failed']} FAIL, {summary['not_executed']} NOT_EXECUTED; "
        f"controls {summary['negative_controls_detected']}/{summary['negative_controls']}"
    )
    print(f"[003m] seal: {seal_result['status']} ({seal_result.get('files', 0)} files)")
    if seal_result["problems"]:
        print(f"[003m] seal problems: {seal_result['problems']}")
    print(json.dumps({"checks": summary, "seal": seal_result}, indent=2, sort_keys=True))
    return 0 if summary["failed"] == 0 and seal_result.get("ok", True) else 1


def idempotent(out: Path) -> int:
    """Regenerate every derived artefact into a scratch tree and compare bytes."""

    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)
        for item in ("design", "dataset"):
            shutil.copytree(out / item, scratch / item)
        (scratch / "analysis").mkdir()
        for name in ("SIGNALS.json", "PROVENANCE.json", "TESTS.json"):
            shutil.copyfile(out / "analysis" / name, scratch / "analysis" / name)
        run_stage("exp_003m_fills.py", out=scratch)
        run_stage("exp_003m_compare.py", out=scratch)
        #: The report needs a verification file; copy the sealed one, it is not regenerated.
        shutil.copyfile(out / "analysis" / "VERIFICATION.json", scratch / "analysis" / "VERIFICATION.json")
        run_stage("exp_003m_report.py", out=scratch)
        targets = DELIVERABLES + DERIVED
        mismatched = [
            name
            for name in targets
            if _sha256(out / name) != _sha256(scratch / name)
        ]
        print(
            f"[003m] idempotent: {len(targets) - len(mismatched)}/{len(targets)} artefacts "
            f"byte-identical"
        )
        if mismatched:
            print(f"[003m] DIFFER: {mismatched}", file=sys.stderr)
            return 1
    return 0


def status(out: Path) -> int:
    state = {
        "design": (out / "design" / "DESIGN.json").exists(),
        "signals": (out / "analysis" / "SIGNALS.json").exists(),
        "tape_manifest": (out / "dataset" / "TAPE_MANIFEST.json").exists(),
        "fill_model": (out / "analysis" / "FILL_MODEL.json").exists(),
        "economics": (out / "analysis" / "ECONOMICS.json").exists(),
        "decision": (out / "analysis" / "DECISION.json").exists(),
        "verification": (out / "analysis" / "VERIFICATION.json").exists(),
        "tests": (out / "analysis" / "TESTS.json").exists(),
        "deliverables": not missing_deliverables(out),
        "sealed": (out / "SEAL.json").exists(),
    }
    print(json.dumps(state, indent=2, sort_keys=True))
    if state["sealed"]:
        print(json.dumps(verify_seal(out), indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("generate", "verify", "seal", "all", "idempotent", "status")
    )
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--online", action="store_true", help="verify: re-download a sample")
    args = parser.parse_args(argv)
    out = Path(args.out)
    if args.command == "generate":
        return generate(out)
    if args.command == "all":
        generate(out)
        return seal(out)
    if args.command == "verify":
        return verify(out, online=args.online)
    if args.command == "seal":
        return seal(out)
    if args.command == "idempotent":
        return idempotent(out)
    return status(out)


if __name__ == "__main__":
    raise SystemExit(main())
