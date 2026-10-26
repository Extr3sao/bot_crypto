"""Run the phase's quality gates and record their real output as an artifact.

The closing summary cites a test count and a lint/type verdict. A number typed by
hand into a document is a claim; the same number measured by a command that
leaves its output behind is evidence. This script runs the three gates over the
tree it is invoked in, captures the exact summary lines each one printed, and
writes ``reports/microstructure-forward/quality_gates.json``.

It writes nothing else: no file under ``src``, ``tests`` or the capture is
touched, so it can be run against a checked-out tree without changing it.

Usage::

    uv run python scripts/forward_quality_gates.py [--dry-run]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "reports" / "microstructure-forward"

#: The gate commands, in the order the phase reports them.
GATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ruff", (sys.executable, "-m", "ruff", "check", "src", "scripts", "tests")),
    ("mypy", (sys.executable, "-m", "mypy", "src", "scripts")),
    ("pytest", (sys.executable, "-m", "pytest", "-q")),
)

_PASSED = re.compile(r"(\d+) passed")


def _run(command: tuple[str, ...]) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = round(time.monotonic() - started, 3)
    tail = [line for line in completed.stdout.splitlines() if line.strip()][-4:]
    return {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "elapsed_seconds": elapsed,
        "summary_lines": tail,
        "stderr_tail": [
            line for line in completed.stderr.splitlines() if line.strip()
        ][-8:],
    }


def _pytest_count(gate: dict[str, Any]) -> int | None:
    for line in reversed(gate["summary_lines"]):
        match = _PASSED.search(line)
        if match:
            return int(match.group(1))
    return None


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    gates: dict[str, dict[str, Any]] = {}
    for name, command in GATES:
        gate = _run(command)
        gates[name] = gate
        verdict = "PASS" if gate["exit_code"] == 0 else "FAIL"
        print(f"{name}: {verdict} ({gate['elapsed_seconds']}s)")
        for line in gate["summary_lines"]:
            print(f"  {line}")

    tests_recorded = _pytest_count(gates.get("pytest", {}))
    payload = {
        "kind": "FORWARD_QUALITY_GATES",
        "head": _head(),
        "gates": gates,
        "tests_passed": tests_recorded,
        "all_pass": all(gate["exit_code"] == 0 for gate in gates.values()),
    }
    print(
        json.dumps(
            {
                "head": payload["head"],
                "tests_passed": payload["tests_passed"],
                "all_pass": payload["all_pass"],
            },
            indent=2,
        )
    )
    if dry_run:
        return 0 if payload["all_pass"] else 1
    FORWARD.mkdir(parents=True, exist_ok=True)
    target = FORWARD / "quality_gates.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"written -> {target}")
    return 0 if payload["all_pass"] else 1


def _head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
