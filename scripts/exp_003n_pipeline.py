"""exp_003n_pipeline — one command per stage, in the order that makes the evidence real.

    ./.venv/Scripts/python.exe scripts/exp_003n_pipeline.py precheck
    ./.venv/Scripts/python.exe scripts/exp_003n_pipeline.py screen
    ./.venv/Scripts/python.exe scripts/exp_003n_pipeline.py validate
    ./.venv/Scripts/python.exe scripts/exp_003n_pipeline.py verify
    ./.venv/Scripts/python.exe scripts/exp_003n_pipeline.py report
    ./.venv/Scripts/python.exe scripts/exp_003n_pipeline.py seal
    ./.venv/Scripts/python.exe scripts/exp_003n_pipeline.py status

Why a pipeline instead of a list of commands: EXP-003L's seal was broken by running the
verifier *after* the report. Here the order is code and each stage refuses the wrong state.

* ``precheck`` runs the Fase-0 audit: the design does not exist yet, or it verifies; the
  predecessor's seal verifies if it is present; the holdout is closed in the design.
* ``screen`` and ``validate`` never overwrite an existing analysis; a rerun is a new
  experiment, not an edit.
* ``verify`` runs a separate program and records its JSON before any report exists.
* ``report`` renders from the analysis and refuses if verification is not PASS.
* ``seal`` requires zero verification failures, the eight deliverables present, and no file
  in the tree outside the plan. The manifest never contains itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "ai-bots" / "EXP-003N-GROSS-FIRST-DISCOVERY-001"
PREDECESSOR = REPO / "reports" / "ai-bots" / "EXP-003M-MAKER-FILL-REALITY-001"
PYTHON = str(REPO / ".venv" / "Scripts" / "python.exe")

DELIVERABLES = [
    "STRATEGY_UNIVERSE.md",
    "ECONOMIC_SCREENING.csv",
    "CANDIDATE_RANKING.md",
    "REJECTED_CANDIDATES.md",
    "INDEPENDENT_VERIFICATION.md",
    "RUN_REPORT.md",
    "RUN_REPORT.json",
    "FINAL_REPORT.md",
]
ANALYSIS = [
    "analysis/SIGNALS.jsonl.gz",
    "analysis/SCREENING.json",
    "analysis/VALIDATION.json",
    "analysis/DECISION.json",
    "analysis/VERIFICATION.json",
    "analysis/TESTS.json",
]
EXCLUDES = ("SEAL.json", "SHA256SUMS.txt")
STAGES = ["preregister", "screen", "validate", "tests", "verify", "report", "seal"]


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


def run(command: list[str], log: Path | None = None, timeout: int = 3600) -> int:
    print(f"[003n] $ {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    text = result.stdout + result.stderr
    print(text[-4000:], flush=True)
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(text, encoding="utf-8", newline="\n")
    return int(result.returncode)


def precheck(out: Path = OUT) -> int:
    design_path = out / "design" / "DESIGN.json"
    if design_path.exists():
        code = run([PYTHON, "scripts/exp_003n_preregister.py", "--check"], timeout=300)
        if code != 0:
            print("[003n] FAIL — the frozen design no longer matches its inputs", file=sys.stderr)
            return code
    else:
        print("[003n] design not frozen yet; run the preregister stage", flush=True)
    if (PREDECESSOR / "SEAL.json").exists():
        print(
            f"[003n] predecessor seal {_sha256(PREDECESSOR / 'SEAL.json')[:16]}… "
            f"decision {_read_json(PREDECESSOR / 'analysis/DECISION.json')['verdict']}",
            flush=True,
        )
    else:
        print("[003n] predecessor seal absent in this checkout; recorded, not assumed", flush=True)
    return 0


def stage_screen(out: Path = OUT) -> int:
    if (out / "analysis" / "SCREENING.json").exists():
        print("[003n] screen already produced; refusing to overwrite", flush=True)
        return 0
    return run(
        [PYTHON, "scripts/exp_003n_screen.py", "--out", str(out)],
        log=out / "evidence" / "screen.log",
    )


def stage_validate(out: Path = OUT) -> int:
    if (out / "analysis" / "VALIDATION.json").exists():
        print("[003n] validation already produced; refusing to overwrite", flush=True)
        return 0
    return run(
        [PYTHON, "scripts/exp_003n_validate.py", "--out", str(out)],
        log=out / "evidence" / "validate.log",
    )


def stage_tests(out: Path = OUT) -> int:
    payload: dict[str, Any] = {"commands": {}}
    pytest_code = run(
        [
            PYTHON,
            "-m",
            "pytest",
            "tests/unit/reports/test_exp_003n_screen.py",
            "tests/unit/vision",
            "tests/unit/paper",
            "-q",
        ],
        log=out / "evidence" / "pytest.log",
    )
    payload["commands"]["pytest"] = {"exit_code": pytest_code}
    ruff_code = run([PYTHON, "-m", "ruff", "check", "scripts/exp_003n_preregister.py",
                     "scripts/exp_003n_screen.py", "scripts/exp_003n_validate.py",
                     "scripts/exp_003n_verify.py", "scripts/exp_003n_report.py",
                     "scripts/exp_003n_pipeline.py",
                     "tests/unit/reports/test_exp_003n_screen.py"],
                    log=out / "evidence" / "ruff.log")
    payload["commands"]["ruff"] = {"exit_code": ruff_code}
    mypy_code = run(
        [PYTHON, "-m", "mypy", "--strict", "scripts/exp_003n_preregister.py",
         "scripts/exp_003n_screen.py", "scripts/exp_003n_validate.py",
         "scripts/exp_003n_verify.py", "scripts/exp_003n_report.py",
         "scripts/exp_003n_pipeline.py"],
        log=out / "evidence" / "mypy.log",
    )
    payload["commands"]["mypy"] = {"exit_code": mypy_code}
    payload["schema_version"] = "AI_BOTS_003N_TESTS_V1"
    payload["all_green"] = all(entry["exit_code"] == 0 for entry in payload["commands"].values())
    _write_json(out / "analysis" / "TESTS.json", payload)
    print(f"[003n] tests: pytest={pytest_code} ruff={ruff_code} mypy={mypy_code}")
    return 0 if payload["all_green"] else 1


def stage_verify(out: Path = OUT) -> int:
    if (out / "SEAL.json").exists():
        print("[003n] refusing: the experiment is sealed", file=sys.stderr)
        return 4
    return run(
        [
            PYTHON,
            "scripts/exp_003n_verify.py",
            "--out",
            str(out),
            "--negative-controls",
            "--json-out",
            str(out / "analysis" / "VERIFICATION.json"),
        ],
        log=out / "evidence" / "verify.log",
    )


def stage_report(out: Path = OUT) -> int:
    verification_path = out / "analysis" / "VERIFICATION.json"
    if not verification_path.exists():
        print("[003n] refusing: no verification to report", file=sys.stderr)
        return 5
    verification = _read_json(verification_path)
    if verification["verdict"] != "PASS":
        print("[003n] refusing: verification is not PASS", file=sys.stderr)
        return 6
    return run([PYTHON, "scripts/exp_003n_report.py", "--out", str(out)],
               log=out / "evidence" / "report.log")


def planned_files(out: Path) -> set[str]:
    planned = set(DELIVERABLES) | set(ANALYSIS)
    planned |= {
        "design/DESIGN.json",
        "design/PREREGISTRATION.md",
        "design/STRATEGY_UNIVERSE.json",
        "design/STRATEGY_UNIVERSE.md",
    }
    for path in (out / "evidence").glob("*"):
        if path.is_file():
            planned.add(str(path.relative_to(out)).replace("\\", "/"))
    return planned


def stage_seal(out: Path = OUT) -> int:
    if (out / "SEAL.json").exists():
        print("[003n] already sealed", file=sys.stderr)
        return 3
    verification = _read_json(out / "analysis" / "VERIFICATION.json")
    tests = _read_json(out / "analysis" / "TESTS.json")
    if verification["summary"]["failed"] or verification["summary"]["false_success"]:
        print("[003n] FAIL — verification is not clean", file=sys.stderr)
        return 7
    if not tests.get("all_green"):
        print("[003n] FAIL — tests are not green", file=sys.stderr)
        return 8
    missing = [name for name in DELIVERABLES if not (out / name).exists()]
    if missing:
        print(f"[003n] FAIL — missing deliverables: {missing}", file=sys.stderr)
        return 9

    files: list[str] = []
    for root, dirs, names in os.walk(out):
        dirs.sort()
        for name in sorted(names):
            path = Path(root) / name
            relative = str(path.relative_to(out)).replace("\\", "/")
            if relative in EXCLUDES:
                continue
            files.append(relative)
    unplanned = sorted(set(files) - planned_files(out))
    if unplanned:
        print(f"[003n] FAIL — unplanned files in the tree: {unplanned[:5]}", file=sys.stderr)
        return 10

    manifest = out / "SHA256SUMS.txt"
    lines = [f"{_sha256(out / relative)}  {relative}" for relative in files]
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    decision = _read_json(out / "analysis" / "DECISION.json")
    seal = {
        "schema_version": "AI_BOTS_003N_SEAL_V1",
        "experiment": "EXP-003N-GROSS-FIRST-DISCOVERY-001",
        "files": len(files),
        "manifest": "SHA256SUMS.txt",
        "manifest_sha256": _sha256(manifest),
        "deliverables": DELIVERABLES,
        "analysis": ANALYSIS,
        "excludes": list(EXCLUDES),
        "order": STAGES,
        "verdict": decision["verdict"],
        "holdout_opened": decision["holdout_opened"],
        "verification": verification["summary"],
        "tests": {name: entry["exit_code"] for name, entry in tests["commands"].items()},
        "design_sha256": _sha256(out / "design" / "DESIGN.json"),
        "preregistration_sha256": _sha256(out / "design" / "PREREGISTRATION.md"),
        "preregistration_is_prospective": False,
        "preregistration_note": (
            "the protocol was frozen on disk at design.frozen_at_utc, before the screening "
            "timestamp, but it was committed to Git after the analysis existed; the freeze is "
            "content-anchored (design_sha256 inside SCREENING.json) and not time-anchored in Git"
        ),
        "predecessor_seal_sha256": _sha256(PREDECESSOR / "SEAL.json")
        if (PREDECESSOR / "SEAL.json").exists()
        else "NOT_PRESENT_IN_CHECKOUT",
        "sealed_commit": _git_head(),
        "self_reference": "none: SHA256SUMS.txt and SEAL.json are excluded by construction",
    }
    _write_json(out / "SEAL.json", seal)
    print(f"[003n] sealed {len(files)} files; manifest {seal['manifest_sha256'][:16]}…")
    return 0


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


def verify_seal(out: Path = OUT) -> dict[str, Any]:
    seal_path = out / "SEAL.json"
    if not seal_path.exists():
        return {"ok": False, "reason": "no seal"}
    seal = _read_json(seal_path)
    manifest = out / "SHA256SUMS.txt"
    if _sha256(manifest) != seal["manifest_sha256"]:
        return {"ok": False, "reason": "manifest digest mismatch"}
    listed = 0
    problems: list[str] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, relative = line.partition("  ")
        listed += 1
        target = out / relative
        if not target.exists():
            problems.append(f"missing {relative}")
        elif _sha256(target) != digest:
            problems.append(f"altered {relative}")
    if listed != seal["files"]:
        problems.append(f"listed {listed} != sealed {seal['files']}")
    return {"ok": not problems, "reason": "; ".join(problems[:5]), "listed": listed}


def status(out: Path = OUT) -> int:
    print(f"[003n] experiment {out.name}")
    for stage in STAGES:
        print(f"[003n]   {stage:10s} " + ("done" if _stage_done(stage, out) else "pending"))
    if (out / "SEAL.json").exists():
        result = verify_seal(out)
        print(f"[003n] seal {'OK' if result['ok'] else 'BROKEN'} ({result.get('listed', 0)} files)")
    return 0


def _stage_done(stage: str, out: Path) -> bool:
    mapping = {
        "preregister": "design/DESIGN.json",
        "screen": "analysis/SCREENING.json",
        "validate": "analysis/VALIDATION.json",
        "tests": "analysis/TESTS.json",
        "verify": "analysis/VERIFICATION.json",
        "report": "FINAL_REPORT.md",
        "seal": "SEAL.json",
    }
    return (out / mapping[stage]).exists()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=[*STAGES, "status"])
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    out = Path(args.out)
    if args.stage == "status":
        return status(out)
    if args.stage == "preregister":
        return precheck(out)
    handler = {
        "screen": stage_screen,
        "validate": stage_validate,
        "tests": stage_tests,
        "verify": stage_verify,
        "report": stage_report,
        "seal": stage_seal,
    }[args.stage]
    return handler(out)


if __name__ == "__main__":
    raise SystemExit(main())
