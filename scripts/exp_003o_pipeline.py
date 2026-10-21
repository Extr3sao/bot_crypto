"""exp_003o_pipeline — the ordered entry points of EXP-003O.

Each phase is also a script of its own; this module only fixes the order and refuses to
skip ahead. In particular it refuses to compare before the protocol is committed, because a
protocol frozen after the numbers is a summary, not a preregistration.

Usage
-----
``python scripts/exp_003o_pipeline.py status``
``python scripts/exp_003o_pipeline.py all``
``python scripts/exp_003o_pipeline.py tests``
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003o_contract import OUT, read_json, sha256_file, write_json  # noqa: E402

PYTHON = sys.executable
ARTEFACTS = (
    "BASELINE_MANIFEST.json",
    "SOURCE_DEPENDENCY_MAP.md",
    "CELL_COVERAGE_MANIFEST.csv",
    "SIGNAL_SPECIFICATIONS.md",
    "design/PROTOCOL.json",
    "design/PREREGISTRATION.md",
    "design/DESIGN.sha256",
    "signals/original_evaluations.jsonl.gz",
    "signals/independent_evaluations.jsonl.gz",
    "SIGNAL_PARITY.csv",
    "SIGNAL_PARITY_SUMMARY.json",
    "PIT_AUDIT.json",
    "NEGATIVE_CONTROLS.json",
    "INDEPENDENCE_AUDIT.md",
    "INDEPENDENT_VERIFICATION.md",
    "CLEAN_CHECKOUT_REPRODUCTION.json",
    "RUN_REPORT.md",
    "RUN_REPORT.json",
    "FINAL_REPORT.md",
    "SHA256SUMS.txt",
)


def _run(args: list[str], *, label: str) -> int:
    print(f"[003o-pipeline] {label}: {' '.join(args[1:])}")
    completed = subprocess.run([PYTHON, *args], cwd=str(REPO), check=False)
    if completed.returncode != 0:
        print(f"[003o-pipeline] FAIL — {label} exited {completed.returncode}", file=sys.stderr)
    return int(completed.returncode)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(REPO), capture_output=True, text=True, check=False
    ).stdout.strip()


def _protocol_committed(out: Path) -> bool:
    relative = str((out / "design" / "PROTOCOL.json").relative_to(REPO)).replace("\\", "/")
    return bool(_git("log", "-1", "--format=%H", "--", relative))


def run_tests(out: Path) -> int:
    """The suites that matter, with their real exit codes, written to evidence/TESTS.json."""

    evidence = out / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "executed_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    commands = {
        "pytest_reports": [
            PYTHON,
            "-m",
            "pytest",
            "tests/unit/reports",
            "tests/unit/research/test_edge16_pit.py",
            "-q",
        ],
        #: Scoped to the files this RFC owns. ``scripts`` as a whole carries 146 pre-existing
        #: lint findings from unrelated experiments; folding them into this gate would make it
        #: fail for reasons EXP-003O cannot fix, which is a different kind of false signal.
        "ruff": [
            PYTHON,
            "-m",
            "ruff",
            "check",
            *sorted(str(path) for path in (REPO / "scripts").glob("exp_003o_*.py")),
            "tests/unit/reports",
        ],
        "mypy": [
            PYTHON,
            "-m",
            "mypy",
            "--strict",
            *sorted(str(path) for path in (REPO / "scripts").glob("exp_003o_*.py")),
        ],
    }
    failed: list[str] = []
    for name, command in commands.items():
        completed = subprocess.run(
            command, cwd=str(REPO), capture_output=True, text=True, check=False
        )
        (evidence / f"{name}.log").write_text(
            completed.stdout + "\n" + completed.stderr, encoding="utf-8", newline="\n"
        )
        results[name] = {
            "exit_code": completed.returncode,
            "tail": (completed.stdout.strip().splitlines() or [""])[-1][:300],
        }
        if completed.returncode != 0:
            failed.append(name)
    results["state"] = "PASS" if not failed else "FAIL"
    results["failed"] = failed
    write_json(evidence / "TESTS.json", results)
    print(
        f"[003o-pipeline] tests {results['state']} {json.dumps({k: v.get('exit_code') for k, v in results.items() if isinstance(v, dict)})}"
    )
    return 0 if not failed else 4


def status(out: Path) -> int:
    print(
        f"[003o-pipeline] run={out.name} branch={_git('rev-parse', '--abbrev-ref', 'HEAD')} head={_git('rev-parse', '--short', 'HEAD')}"
    )
    for name in ARTEFACTS:
        path = out / name
        if path.exists():
            print(f"[003o-pipeline]   present  {name:48s} {sha256_file(path)[:16]}…")
        else:
            print(f"[003o-pipeline]   MISSING  {name}")
    if (out / "design" / "PROTOCOL.json").exists():
        check = subprocess.run(
            [
                PYTHON,
                str(REPO / "scripts" / "exp_003o_preregister.py"),
                "--check",
                "--out",
                str(out),
            ],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        print(f"[003o-pipeline]   {check.stdout.strip() or check.stderr.strip()}")
    if (out / "VERIFICATION.json").exists():
        verdict = read_json(out / "VERIFICATION.json")
        print(
            f"[003o-pipeline]   technical={verdict['technical_signal_parity']} "
            f"full={verdict['full_independent_certification']} "
            f"controls={verdict['negative_controls_effective']}/12 "
            f"pit={verdict['pit_violations']}"
        )
    if (out / "RUN_REPORT.json").exists():
        report = read_json(out / "RUN_REPORT.json")
        print(f"[003o-pipeline]   status={report['status']} verdict={report['verdict']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003O pipeline")
    parser.add_argument(
        "phase",
        choices=(
            "status",
            "baseline",
            "preregister",
            "rebuild",
            "original",
            "compare",
            "verify",
            "tests",
            "report",
            "seal",
            "all",
        ),
    )
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--skip-prefix", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    scripts = REPO / "scripts"

    if args.phase == "status":
        return status(out)
    if args.phase == "baseline":
        return _run([str(scripts / "exp_003o_baseline.py"), "--out", str(out)], label="baseline")
    if args.phase == "preregister":
        return _run(
            [str(scripts / "exp_003o_preregister.py"), "--out", str(out)], label="preregister"
        )
    if args.phase == "rebuild":
        return _run(
            [
                str(scripts / "exp_003o_rebuilder.py"),
                "--out",
                str(out / "signals" / "independent_evaluations.jsonl.gz"),
            ],
            label="rebuild",
        )
    if args.phase == "original":
        return _run(
            [
                str(scripts / "exp_003o_original.py"),
                "--out",
                str(out / "signals" / "original_evaluations.jsonl.gz"),
                "--check-published",
            ],
            label="original",
        )
    if args.phase == "compare":
        if not _protocol_committed(out):
            print(
                "[003o-pipeline] REFUSED — the protocol is not committed; a comparison now would "
                "not be prospective",
                file=sys.stderr,
            )
            return 6
        return _run([str(scripts / "exp_003o_compare.py"), "--out", str(out)], label="compare")
    if args.phase == "verify":
        extra = ["--skip-prefix"] if args.skip_prefix else []
        return _run(
            [str(scripts / "exp_003o_verify.py"), "--out", str(out), *extra], label="verify"
        )
    if args.phase == "tests":
        return run_tests(out)
    if args.phase == "report":
        return _run([str(scripts / "exp_003o_report.py"), "--out", str(out)], label="report")
    if args.phase == "seal":
        return _run(
            [str(scripts / "exp_003o_report.py"), "--out", str(out), "--seal"], label="seal"
        )
    if args.phase == "all":
        for phase in (
            "baseline",
            "rebuild",
            "original",
            "compare",
            "verify",
            "tests",
            "report",
            "seal",
        ):
            code = main(
                [phase, "--out", str(out)] + (["--skip-prefix"] if args.skip_prefix else [])
            )
            if code != 0:
                return code
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
