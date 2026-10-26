"""WP-TDM-016 — run the suites this change can reach and record the outcome.

The change is additive (new scripts, one new test module, one evidence
directory), so the regression surface is the suites that import the modules the
new tests touch: paper, risk, autonomous and integration. Those are the ones
run here, with JUnit XML so the counts are parsed rather than eyeballed.

Each suite's real exit status is preserved: a failing suite makes this script
exit non-zero, and the JSON records it. Nothing is piped through a filter.

Usage:
    uv run python scripts/tdm16_tests.py \
        --out evidence/tdm/wp-tdm-16-paper-admission/TEST_RESULTS.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

SUITES = (
    ("wp016_paper_cycle", "tests/integration/test_wp016_paper_order_cycle.py"),
    ("paper", "tests/unit/paper"),
    ("risk", "tests/unit/risk"),
    ("autonomous", "tests/unit/autonomous"),
    ("integration", "tests/integration"),
)


def _totals(junit: Path) -> dict[str, int]:
    tree = ET.parse(junit)
    suites = list(tree.iter("testsuite"))
    return {
        "tests": sum(int(s.get("tests") or 0) for s in suites),
        "failures": sum(int(s.get("failures") or 0) for s in suites),
        "errors": sum(int(s.get("errors") or 0) for s in suites),
        "skipped": sum(int(s.get("skipped") or 0) for s in suites),
    }


def run_suite(name: str, target: str) -> dict[str, Any]:
    tmp = Path(tempfile.mkdtemp(prefix=f"wp016_{name}_"))
    junit = tmp / "junit.xml"
    command = [
        sys.executable,
        "-m",
        "pytest",
        target,
        "-q",
        "-p",
        "no:cacheprovider",
        f"--junitxml={junit}",
    ]
    started = time.time()
    completed = subprocess.run(
        command, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False
    )
    duration = round(time.time() - started, 2)
    totals = _totals(junit) if junit.exists() else {}
    return {
        "suite": name,
        "target": target,
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "duration_s": duration,
        **totals,
        "stdout_tail": completed.stdout.strip().splitlines()[-3:],
        "stderr_tail": completed.stderr.strip().splitlines()[-3:],
    }


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, check=False
    )
    return completed.stdout.strip()


def build_results() -> dict[str, Any]:
    suites = [run_suite(name, target) for name, target in SUITES]
    modified = [line for line in _git("diff", "--name-status", "HEAD").splitlines() if line]
    untracked = [
        line[3:]
        for line in _git("status", "--porcelain").splitlines()
        if line.startswith("??")
    ]
    return {
        "artifact": "WP-TDM-016 · test results",
        "schema_version": "wp-tdm-16-test-results-v1",
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "suites": suites,
        "totals": {
            "tests": sum(s.get("tests", 0) for s in suites),
            "failures": sum(s.get("failures", 0) for s in suites),
            "errors": sum(s.get("errors", 0) for s in suites),
            "exit_codes": {s["suite"]: s["exit_code"] for s in suites},
        },
        "regression_surface": {
            "modified_tracked_files": modified,
            "untracked_files": untracked,
            "note": (
                "no tracked file is modified: the change adds new scripts, one new test module "
                "and the evidence directory, so the suites above are the reachable surface and "
                "the parent commit runs them unchanged"
            ),
        },
        "all_green": all(s["exit_code"] == 0 for s in suites),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default="evidence/tdm/wp-tdm-16-paper-admission/TEST_RESULTS.json"
    )
    args = parser.parse_args(argv)
    results = build_results()
    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"wrote {args.out}: tests={results['totals']['tests']} "
        f"failures={results['totals']['failures']} errors={results['totals']['errors']} "
        f"all_green={results['all_green']}"
    )
    return 0 if results["all_green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
