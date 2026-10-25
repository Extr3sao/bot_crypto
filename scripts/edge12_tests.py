"""WP-EDGE-12 — run this package's regressions and record what the subprocesses returned.

RFC-EDGE-012's definition of done asks for TEST beside IMPLEMENTATION, and the distance
between those two words is a recorded run: a report that says "the tests passed" without
the run is a claim about somebody's memory of a terminal. This step executes the modules
named below and writes the exit status, the counts and the tail of the output into
``evidence/TEST_RUNS.json``, which the run report then quotes rather than paraphrasing.

The selection is declared here and nowhere else, and it is deliberately narrow: this
package's own regressions plus the lint that guards them. A pass figure produced from a
different selection than the one named would be evidence of a run nobody can reproduce,
which is worse than no figure at all.

    python scripts/edge12_tests.py              run, record, print
    python scripts/edge12_tests.py --json       print the record

Read-only with respect to everything except ``evidence/TEST_RUNS.json``.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge12 import evidence as ev  # noqa: E402

#: The regression modules this package owns. Both are named, never globbed: a glob would
#: silently start passing once a file was renamed away, and a test run that reports zero
#: failures because it collected zero tests is the failure mode worth designing against.
TEST_MODULES: tuple[str, ...] = (
    "tests/unit/research/test_edge12_continuity.py",
    "tests/unit/research/test_edge12_runner.py",
)

#: What the lint is asked to check: the package and the regressions, not the whole tree.
#: The whole tree carries other work packages' findings, which belong to their owners.
LINT_PATHS: tuple[str, ...] = (
    "src/trading_bot/research/edge12/",
    "scripts/edge12_verify.py",
    "scripts/edge12_reports.py",
    "scripts/edge12_tests.py",
    *TEST_MODULES,
)

EVIDENCE_FILENAME = "TEST_RUNS.json"
SCHEMA_VERSION = "EDGE12_TEST_RUNS_V1"

#: pytest's own summary vocabulary. The counts are read from the run's output rather than
#: inferred from its exit status, because a report quotes a number and an exit code does not
#: say which number it was.
SUMMARY_COUNTS = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped)\b")
COUNT_NAMES = {
    "passed": "passed",
    "failed": "failed",
    "error": "errors",
    "errors": "errors",
    "skipped": "skipped",
}


def _run(command: list[str], *, timeout: int) -> dict[str, object]:
    """Run one command and keep what it said, whatever it said."""
    try:
        proc = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "command": " ".join(command),
            "exit_code": None,
            "passed": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "tail": "",
        }
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return {
        "command": " ".join(command),
        "exit_code": proc.returncode,
        "passed": proc.returncode == 0,
        "reason": None,
        "tail": "\n".join(text.splitlines()[-12:]),
    }


def _pytest_counts(run: dict[str, object]) -> dict[str, int | None]:
    """The counts pytest itself reported, or nulls when it did not report any.

    ``None`` rather than ``0``: a run that collected nothing and a run whose summary could
    not be read are different facts, and a report that printed ``0 failures`` for both
    would be indistinguishable from a passing suite. The last occurrence of each count wins,
    because that is the line pytest prints after it has finished rather than while running.
    """
    counts: dict[str, int | None] = {
        "passed": None,
        "failed": None,
        "errors": None,
        "skipped": None,
    }
    for value, word in SUMMARY_COUNTS.findall(str(run.get("tail") or "")):
        name = COUNT_NAMES.get(word)
        if name:
            counts[name] = int(value)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reports", default=str(ev.DEFAULT_REPORTS))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)

    reports = ev.repo_path(args.reports)
    evidence_dir = reports / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    missing = [name for name in TEST_MODULES if not (REPO_ROOT / name).is_file()]
    if missing:
        print(f"the declared regression module(s) are absent: {missing}", file=sys.stderr)
        return 3

    pytest_run = _run([sys.executable, "-m", "pytest", "-q", *TEST_MODULES], timeout=args.timeout)
    lint_run = _run(
        [sys.executable, "-m", "ruff", "check", *LINT_PATHS],
        timeout=min(args.timeout, 120),
    )
    counts = _pytest_counts(pytest_run)
    # A suite that collected nothing is not a suite that passed, and neither is one whose
    # summary could not be read: both would publish a figure nobody could tie to a run.
    collected_nothing = counts["passed"] in (None, 0)
    passed = (
        bool(pytest_run["passed"])
        and bool(lint_run["passed"])
        and not collected_nothing
        and counts["failed"] in (None, 0)
        and counts["errors"] in (None, 0)
    )
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": ev.now_utc(),
        "work_package": "WP-EDGE-12",
        "campaign": "RFC-EDGE-012",
        "selection": {
            "test_modules": list(TEST_MODULES),
            "lint_paths": list(LINT_PATHS),
            "declared_in": "scripts/edge12_tests.py",
            "why_narrow": (
                "these are this package's own regressions and the lint that guards them; the rest "
                "of the tree carries other work packages' findings and their owners report them"
            ),
        },
        "pytest": {**pytest_run, **counts},
        "lint": lint_run,
        "collected_nothing": collected_nothing,
        "verdict": "TESTS_PASS" if passed else "TESTS_FAILED",
        "read_only": (
            "no network, no live state root, no live store, no scheduler; this step runs the "
            "package's own regressions and the lint over its own paths"
        ),
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }
    ev.write_json(evidence_dir / EVIDENCE_FILENAME, payload)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0 if passed else 5
    print(
        f"pytest            {counts['passed']} passed, {counts['failed']} failed, "
        f"{counts['errors']} error(s), exit {pytest_run['exit_code']}"
    )
    print(f"lint              exit {lint_run['exit_code']}")
    print(f"verdict           {payload['verdict']}")
    print(f"evidence          {evidence_dir / EVIDENCE_FILENAME}")
    return 0 if passed else 5


if __name__ == "__main__":
    raise SystemExit(main())
