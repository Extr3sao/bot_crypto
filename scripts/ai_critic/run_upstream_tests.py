"""run_upstream_tests — execute the pinned upstream focal tests and record the receipt.

The receipt is what the audit reads: command, exit code, stdout, stderr and the SHA of
the checkout that produced them. It does not paraphrase the test result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

FOCAL_TESTS = (
    "tests/test_debate_opening.py",
    "tests/test_structured_agents.py",
    "tests/test_report_html.py",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(args.upstream_root).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    python = root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=False).stdout.strip()
    runs = []
    for test in FOCAL_TESTS:
        started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        proc = subprocess.run(
            [str(python), "-m", "pytest", test, "-q"],
            cwd=root, capture_output=True, text=True, check=False,
        )
        runs.append({
            "test_file": test,
            "command": f"{python} -m pytest {test} -q",
            "cwd": str(root),
            "started_at": started,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "network": "blocked by tests/conftest.py _no_network fixture",
        })
    record = {
        "schema_version": "TAP004_UPSTREAM_TESTS_V1",
        "source_commit": head,
        "source_commit_expected": "e8f5503e9b86d5c2710b0c76b1f686703968c9df",
        "interpreter": str(python),
        "python": sys.version,
        "runs": runs,
        "all_passed": all(run["exit_code"] == 0 for run in runs),
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    target = out / "UPSTREAM_TESTS.json"
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_passed": record["all_passed"],
                      "runs": [(r["test_file"], r["exit_code"]) for r in runs],
                      "sha256": sha256_file(target)}, indent=2))
    return 0 if record["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
