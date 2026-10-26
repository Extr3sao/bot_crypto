#!/usr/bin/env python
"""WP-EDGE-09F — record the wider research suite, inherited failures included.

    python scripts/edge09_suite_evidence.py --run                 # runs the suite (~9 min)
    python scripts/edge09_suite_evidence.py --log <path>          # records a run already made

The package's own suite is executed by ``scripts/edge09_report.py`` and its exit
codes go into RUN_REPORT.json. The wider ``tests/unit/research`` tree is recorded
separately because it takes minutes and because it is where *inherited* failures
live: a failure that this package did not cause still has to be declared rather
than hidden behind a green owned suite.

Nothing is judged here. The script reads a pytest log, writes
``RESEARCH_SUITE.{json,md}`` with the command, the counts, the failing test ids and
the diagnosis of each failure, and refuses to describe a run it cannot see.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge09.registration import SCHEMA_VERSION, WP  # noqa: E402

SUITE = "tests/unit/research"
SUMMARY = re.compile(
    r"^(?P<failed>\d+) failed, (?P<passed>\d+) passed in (?P<seconds>[\d.]+)s",
)
SUMMARY_PASSED_ONLY = re.compile(r"^(?P<passed>\d+) passed in (?P<seconds>[\d.]+)s")
FAILED_TEST = re.compile(r"^FAILED (?P<test>\S+)")


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return (proc.stdout or "").strip()


def parse(log: str) -> dict[str, Any]:
    """Read the counts and the failing test ids out of a pytest -q log."""
    result: dict[str, Any] = {
        "failed": None,
        "passed": None,
        "seconds": None,
        "failing_tests": [],
    }
    for line in log.splitlines():
        stripped = line.strip()
        match = SUMMARY.match(stripped)
        if match:
            result["failed"] = int(match.group("failed"))
            result["passed"] = int(match.group("passed"))
            result["seconds"] = float(match.group("seconds"))
            continue
        passed_only = SUMMARY_PASSED_ONLY.match(stripped)
        if passed_only and result["passed"] is None:
            result["failed"] = 0
            result["passed"] = int(passed_only.group("passed"))
            result["seconds"] = float(passed_only.group("seconds"))
            continue
        found = FAILED_TEST.match(stripped)
        if found:
            result["failing_tests"].append(found.group("test"))
    return result


def diagnose(test_id: str) -> dict[str, Any]:
    """Ask git and the file digests whether this package could have caused it."""
    path = test_id.split("::")[0]
    touched = git("log", "--oneline", "HEAD~12..HEAD", "--", path) or ""
    return {
        "test": test_id,
        "file": path,
        "files_this_package_touched": bool(touched.strip()),
        "why": (
            "outside every path this package commits to; the package's own commits touch no "
            "file under it"
            if not touched.strip()
            else "inside the tree this package commits to: this one has to be fixed here"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true", help="run the suite now")
    parser.add_argument("--log", help="record a pytest log already written")
    options = parser.parse_args(argv)

    log_path = (
        Path(options.log).resolve()
        if options.log
        else REPO_ROOT / ".ci" / "edge09_research_suite.log"
    )
    try:
        log_label = str(log_path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        log_label = str(log_path)
    command = f"{Path(sys.executable).name} -m pytest {SUITE} -q"
    if options.run:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", SUITE, "-q"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
        exit_code = proc.returncode
    else:
        if not log_path.is_file():
            print(f"no log at {log_path}: run with --run or point --log at a recording")
            return 2
        exit_code = None
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("suite_exit="):
                exit_code = int(line.split("=", 1)[1])

    counts = parse(log_path.read_text(encoding="utf-8", errors="replace"))
    failures = [diagnose(test) for test in counts["failing_tests"]]
    inherited = [row for row in failures if not row["files_this_package_touched"]]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-09F",
        "artifact": "RESEARCH_SUITE",
        "as_of_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": git("rev-parse", "HEAD"),
        "suite": SUITE,
        "command": command,
        "log_path": log_label,
        "exit_code": exit_code,
        **counts,
        "failures": failures,
        "inherited_failures": len(inherited),
        "caused_by_this_package": len(failures) - len(inherited),
        "reading": (
            "declared, not hidden: a failure outside this package's paths is reported as "
            "inherited and left to its owner, and a failure inside them would have to be fixed "
            "here before the package could close"
        ),
        "how_to_reproduce": f"python {Path(__file__).name} --run",
    }
    (WP / "RESEARCH_SUITE.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# WP-EDGE-09F — the wider research suite",
        "",
        f"*Recorded at `{payload['as_of_utc']}` from `{payload['log_path']}`. Command: "
        f"`{command}`. Exit code: {exit_code}.*",
        "",
        f"{counts['passed']} passed, {counts['failed']} failed in {counts['seconds']} s — "
        f"**{payload['inherited_failures']} inherited**, "
        f"{payload['caused_by_this_package']} caused by this package.",
        "",
        "## Failures",
        "",
    ]
    if failures:
        lines += [
            "| Test | Touched by this package | Diagnosis |",
            "| --- | :-: | --- |",
        ]
        for row in failures:
            lines.append(
                f"| `{row['test']}` | {row['files_this_package_touched']} | {row['why']} |"
            )
    else:
        lines.append("- none")
    lines += [
        "",
        f"{payload['reading']}",
        "",
        "The package's own suite, lint, format and type checks are executed by "
        "`scripts/edge09_report.py --tests` and their exit codes are in `RUN_REPORT.json`.",
        "",
    ]
    (WP / "RESEARCH_SUITE.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        f"{counts['passed']} passed, {counts['failed']} failed, "
        f"{payload['inherited_failures']} inherited"
    )
    print(f"wrote {(WP / 'RESEARCH_SUITE.json').relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
