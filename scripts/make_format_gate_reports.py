#!/usr/bin/env python
"""Turn two JUnit runs plus the exemption audit into the WP-003-08 deliverables.

The comparison is by node id (`module::test`), never by count: a suite whose totals
match while the failing tests differ is a regression, not a pass.

Usage:
    python scripts/make_format_gate_reports.py \
        --base-xml .tmp/wp00308/base.xml --head-xml .tmp/wp00308/head.xml \
        --audit .tmp/wp00308/FORMAT_EXEMPTIONS_AUDIT.json \
        --base-sha 1d2192b0 --out reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00308

Writes `REGRESSION_COMPARISON.json` and `FORMAT_EXEMPTIONS_AUDIT.json` next to each
other, both derived only from the files named above.
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Run:
    """One JUnit run, reduced to counts and red node ids."""

    sha: str
    tests: int
    failures: int
    errors: int
    skipped: int
    red: set[str]

    @property
    def passed(self) -> int:
        return self.tests - self.failures - self.errors - self.skipped

    def as_dict(self) -> dict[str, Any]:
        return {
            "sha": self.sha,
            "tests": self.tests,
            "failures": self.failures,
            "errors": self.errors,
            "skipped": self.skipped,
            "passed": self.passed,
            "red_nodes": len(self.red),
        }


def read_junit(path: Path, sha: str) -> Run:
    """Reduce a JUnit XML file to counts and the set of red node ids."""
    root = ET.parse(path).getroot()
    tests = failures = errors = skipped = 0
    red: set[str] = set()
    for case in root.iter("testcase"):
        tests += 1
        classname = case.get("classname") or ""
        name = case.get("name") or ""
        node = f"{classname}::{name}"
        failed = case.find("failure") is not None
        broken = case.find("error") is not None
        if case.find("skipped") is not None:
            skipped += 1
        if failed:
            failures += 1
        if broken:
            errors += 1
        if failed or broken:
            red.add(node)
    return Run(sha=sha, tests=tests, failures=failures, errors=errors, skipped=skipped, red=red)


def compare(base: Run, head: Run) -> dict[str, Any]:
    """Node-level verdict for the two runs."""
    new_red = sorted(head.red - base.red)
    fixed_red = sorted(base.red - head.red)
    return {
        "base": base.as_dict(),
        "head": head.as_dict(),
        "delta": {
            "tests": head.tests - base.tests,
            "passed": head.passed - base.passed,
            "failed": head.failures - base.failures,
            "errors": head.errors - base.errors,
            "skipped": head.skipped - base.skipped,
            "red_nodes": len(head.red) - len(base.red),
        },
        "new_red_nodes": new_red,
        "fixed_red_nodes": fixed_red,
        "shared_red_nodes": len(base.red & head.red),
        "verdict": "NO_NEW_FAILURES" if not new_red else "REGRESSION",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-xml", required=True)
    parser.add_argument("--head-xml", required=True)
    parser.add_argument(
        "--audit", required=True, help="output of verify_format_exemptions.py --json"
    )
    parser.add_argument("--base-sha", default="1d2192b0")
    parser.add_argument(
        "--pin-xml",
        default=None,
        help="optional run made with every exempted file formatted: quantifies what the "
        "exemption buys",
    )
    parser.add_argument("--out", required=True, help="bundle directory")
    args = parser.parse_args(argv)

    base = read_junit(Path(args.base_xml), args.base_sha)
    head = read_junit(Path(args.head_xml), "HEAD")
    comparison = {
        "schema": "wp00308-regression-comparison/1",
        "method": (
            "both runs use the same interpreter, the same rebuilt repository .venv, the same "
            "command and the same markers; failures are compared by node id (module::test), not "
            "by count, so a test that fails on one side and is merely renumbered on the other "
            "cannot hide"
        ),
        "command": 'pytest -m "not slow and not market" -q --tb=no -p no:cacheprovider',
        **compare(base, head),
    }

    audit_path = Path(args.audit)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    bundle: dict[str, Any] = {
        "schema": "wp00308-format-exemptions-audit/1",
        "base": args.base_sha,
        "source": "scripts/verify_format_exemptions.py --self-test --json",
        "guard": audit,
        "regression": {
            "verdict": comparison["verdict"],
            "new_red_nodes": comparison["new_red_nodes"],
        },
    }
    if args.pin_xml:
        pinned = read_junit(Path(args.pin_xml), "base+" + args.base_sha + "+formatted_pins")
        bundle["pin_cost"] = {
            "method": (
                "scratch worktree at HEAD with every exempted file reformatted via "
                "`ruff format --config format.exclude=[]`; the difference in red nodes against "
                "the base run is exactly what the exemption buys"
            ),
            "run": pinned.as_dict(),
            "new_red_nodes": sorted(pinned.red - base.red),
            "fixed_red_nodes": sorted(base.red - pinned.red),
        }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "REGRESSION_COMPARISON.json").write_text(
        json.dumps(comparison, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "FORMAT_EXEMPTIONS_AUDIT.json").write_text(
        json.dumps(bundle, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"verdict": comparison["verdict"], "delta": comparison["delta"]}, indent=1))
    return 0 if comparison["verdict"] == "NO_NEW_FAILURES" else 1


if __name__ == "__main__":
    raise SystemExit(main())
