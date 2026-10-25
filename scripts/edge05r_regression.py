#!/usr/bin/env python
"""WP-EDGE-05R — run the tests, and record what they said rather than what they should have said.

Two runs, one artefact:

* the **chain suites** — the lane's tests, the watchdog's and the reconciliation's — which are the
  regression net for the forward observation chain;
* the **whole research suite**, so that the failures elsewhere are visible, counted and attributed
  instead of being left as an impression.

The failing node ids are written down with the cause that was *demonstrated* for each: a host whose
volume is nearly full, or a committed artefact another workstream has left stale. A failure with no
demonstrated cause is recorded as `UNEXPLAINED`, because that is the honest label and the one that
should cost someone sleep.
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
SCHEMA_VERSION = "EDGE05R_REGRESSION_V1"

CHAIN_SUITES = (
    "tests/unit/research/test_edge04_autonomous.py",
    "tests/unit/research/test_edge05_watchdog.py",
    "tests/unit/research/test_edge05_reconcile.py",
)

#: What each known-elsewhere failure was shown to be. Keyed by the test file, because the cause is
#: a property of the suite, not of the individual assertion.
KNOWN_CAUSES: dict[str, dict[str, str]] = {
    "tests/unit/research/test_wp9_disk_budget.py": {
        "cause": "HOST_FREE_SPACE",
        "demonstrated": (
            "the launcher's own preflight reads the real volume, so on a host under its floors it "
            "refuses with INSUFFICIENT_FREE_SPACE before the valve arithmetic the test is about. The "
            "same class of defect this work package removed from the forward chain's fixtures."
        ),
        "owner": "WP-9B (paper lab disk budget)",
        "fix_stated": (
            "pin the volume inside the three tests that are about the valve: "
            "monkeypatch.setattr(launcher, 'free_bytes', lambda path: 10**12) and the same for "
            "disk_free_bytes. Not applied here: that file belongs to another workstream, and its "
            "CRLF endings make a fixture edit a riskier change than it looks."
        ),
    },
    "tests/unit/research/test_recovery_determinism.py": {
        "cause": "STALE_COMMITTED_ARTEFACT",
        "demonstrated": (
            "re-running the documented reproduction moves data/recovery/CAMPAIGN_STATE_VIEW.json and "
            "CAMPAIGN_STATE_VIEW_REPORT.md: the committed view was generated from an older state than "
            "the one on disk."
        ),
        "owner": "WP-8 (recovery)",
        "fix_stated": "regenerate the committed view from the current state and commit it.",
    },
    "tests/unit/research/test_active_recovery_wp.py": {
        "cause": "STALE_COMMITTED_ARTEFACT",
        "demonstrated": "the test's own message is the diagnosis: 'the committed view is stale'.",
        "owner": "WP-8 / campaign state view",
        "fix_stated": "re-run scripts/campaign_state_view.py and commit the result.",
    },
    "tests/unit/research/test_cost_barrier_adversarial.py": {
        "cause": "STALE_COMMITTED_ARTEFACT",
        "demonstrated": (
            "the certification record pins a digest (51ef35aa…) that the file on disk no longer "
            "hashes to (3fb11fc9…): the record and the artefact it certifies have drifted apart."
        ),
        "owner": "cost barrier",
        "fix_stated": "re-issue the certification record against the current artefact.",
    },
}


def now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def stamp(instant_ms: int) -> str:
    return datetime.fromtimestamp(instant_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_suite(repo_root: Path, targets: list[str], *, python: str) -> dict[str, Any]:
    command = [python, "-m", "pytest", *targets, "-q", "--tb=no", "-rf"]
    result = subprocess.run(command, cwd=repo_root, capture_output=True, text=True, check=False)
    output = result.stdout + result.stderr
    counts = {"passed": 0, "failed": 0, "error": 0, "deselected": 0, "skipped": 0}
    match = re.search(
        r"(\d+) failed.*?(\d+) passed|(\d+) passed", output
    )
    summary = next(
        (line for line in reversed(output.splitlines()) if "passed" in line or "failed" in line),
        "",
    )
    for key in counts:
        found = re.search(rf"(\d+) {key}", summary)
        if found:
            counts[key] = int(found.group(1))
    if counts["passed"] == 0 and match:
        counts["passed"] = int(match.group(3) or 0)
    failing = sorted(
        {
            line.split(" ", 1)[1].split(" ")[0]
            for line in output.splitlines()
            if line.startswith("FAILED ")
        }
    )
    return {
        "command": " ".join(command),
        "targets": targets,
        "exit_code": result.returncode,
        "counts": counts,
        "summary_line": summary.strip(),
        "failing_nodes": failing,
        "as_of_utc": stamp(now_ms()),
    }


def attribute(failing: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in failing:
        path = node.split("::", 1)[0]
        known = KNOWN_CAUSES.get(path)
        out.append(
            {
                "node": node,
                "suite": path,
                "cause": (known or {}).get("cause", "UNEXPLAINED"),
                "owner": (known or {}).get("owner", "unknown"),
                "demonstrated": (known or {}).get(
                    "demonstrated", "no cause has been demonstrated for this failure"
                ),
                "fix_stated": (known or {}).get("fix_stated", ""),
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--chain-only", action="store_true", help="skip the whole-suite run")
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)

    repo_root = Path(options.repo_root).resolve() if options.repo_root else REPO_ROOT
    out = (
        Path(options.out)
        if options.out
        else repo_root / "reports" / "edge-recovery" / "WP-EDGE-05R"
    )

    chain = run_suite(repo_root, list(CHAIN_SUITES), python=options.python)
    full = None
    if not options.chain_only:
        full = run_suite(repo_root, ["tests/unit/research"], python=options.python)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "as_of_utc": stamp(now_ms()),
        "host": __import__("os").environ.get("COMPUTERNAME", "unknown"),
        "chain": chain,
        "full": full,
        "failures_attributed": attribute((full or chain)["failing_nodes"]),
        "reading": (
            "the chain suites are the regression net for the forward observation chain; the whole "
            "research suite is run so that failures elsewhere are counted and attributed rather "
            "than left as an impression"
        ),
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }
    payload["unexplained"] = [
        row["node"] for row in payload["failures_attributed"] if row["cause"] == "UNEXPLAINED"
    ]

    if options.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0

    out.mkdir(parents=True, exist_ok=True)
    (out / "REGRESSION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(f"chain  : {chain['summary_line']} (exit {chain['exit_code']})")
    if full:
        print(f"full   : {full['summary_line']} (exit {full['exit_code']})")
        print(f"attributed: {len(payload['failures_attributed'])} failure(s), "
              f"{len(payload['unexplained'])} unexplained")
    print(f"wrote REGRESSION.json into {out}")
    return 1 if chain["exit_code"] != 0 else 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
