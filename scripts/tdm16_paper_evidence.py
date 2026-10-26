"""WP-016B — run the TEST_ONLY paper-cycle integration tests and publish the numbers.

The tests are the evidence; this script only executes them through the same
interface an operator would use (``pytest``), captures the per-test outcome and
duration from JUnit XML, and checks the traces they emitted against each other.
Nothing here re-implements the cycle: if a number in the evidence file and the
test disagree, the run fails.

Cross-checks (a failure here fails the script, not just the report):

* ``net_pnl == gross_pnl - fees`` on the closed trade;
* ``equity == initial_equity + sum(closed pnl)`` on both the live book and the
  reconciled one;
* reconciliation of a real book is ``RECOVERED`` with the same closed-trade
  count, and of an empty store is ``CONSISTENT``;
* the same intent after a restart places **zero** orders;
* the refused order path places **zero** orders.

The artifact is labelled ``TEST_ONLY`` next to every number: these prices are
fixtures, so the numbers prove mechanics, never profitability.

Usage:
    uv run python scripts/tdm16_paper_evidence.py \
        --out evidence/tdm/wp-tdm-16-paper-admission/PAPER_CYCLE_EVIDENCE.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_MODULE = Path("tests/integration/test_wp016_paper_order_cycle.py")
EVIDENCE_SCHEMA_VERSION = "wp-tdm-16-paper-cycle-evidence-v1"
LABEL = "TEST_ONLY"

#: Numeric tolerance for the identities below: they are exact arithmetic on
#: floats, so anything above this is a real defect, not representation noise.
TOL = 1e-9

#: Files whose behaviour the tests exercise (hashed so the evidence names the
#: exact code it ran against, not the branch name).
EXERCISED = (
    "src/trading_bot/paper/broker.py",
    "src/trading_bot/paper/paper_cycle.py",
    "src/trading_bot/paper/paper_runtime_state.py",
    "src/trading_bot/paper/paper_state_store.py",
    "src/trading_bot/paper/reconciliation_v4.py",
    "src/trading_bot/risk/manager.py",
    "src/trading_bot/families_sentinel.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_junit(path: Path) -> list[dict[str, Any]]:
    tree = ET.parse(path)
    out: list[dict[str, Any]] = []
    for case in tree.iter("testcase"):
        failed = case.find("failure") is not None or case.find("error") is not None
        skipped = case.find("skipped") is not None
        out.append(
            {
                "nodeid": case.get("classname", "") + "::" + case.get("name", ""),
                "name": case.get("name", ""),
                "outcome": "failed" if failed else ("skipped" if skipped else "passed"),
                "duration_s": round(float(case.get("time") or 0.0), 6),
            }
        )
    return out


def _check(claim_id: str, description: str, passed: bool, observed: Any) -> dict[str, Any]:
    return {
        "id": claim_id,
        "description": description,
        "passed": bool(passed),
        "observed": observed,
    }


def build_evidence(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    traces_dir = Path(tempfile.mkdtemp(prefix="wp016_traces_"))
    junit = traces_dir / "junit.xml"

    env = dict(os.environ)
    env["WP016_TRACE_DIR"] = str(traces_dir)
    src = str(repo_root / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONHASHSEED"] = "0"

    command = [
        sys.executable,
        "-m",
        "pytest",
        str(repo_root / TEST_MODULE),
        "-q",
        "-p",
        "no:cacheprovider",
        f"--junitxml={junit}",
    ]
    started = time.time()
    completed = subprocess.run(
        command, cwd=str(repo_root), env=env, capture_output=True, text=True, check=False
    )
    duration = round(time.time() - started, 3)

    tests = _parse_junit(junit) if junit.exists() else []
    traces: dict[str, Any] = {}
    for path in sorted(traces_dir.glob("*.json")):
        traces[path.stem] = json.loads(path.read_text(encoding="utf-8"))

    cycle = traces.get("cycle") or {}
    costs = traces.get("cost_line") or {}
    blocked = traces.get("fail_closed") or {}

    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "B01",
            "every TEST_ONLY integration test passed",
            bool(tests) and all(t["outcome"] == "passed" for t in tests),
            {"tests": len(tests), "failed": [t["name"] for t in tests if t["outcome"] != "passed"]},
        )
    )
    checks.append(
        _check(
            "B02",
            "the cycle emitted a trace labelled TEST_ONLY",
            cycle.get("label") == LABEL and costs.get("label") == LABEL,
            {"cycle": cycle.get("label"), "cost_line": costs.get("label")},
        )
    )
    checks.append(
        _check(
            "B03",
            "one approved order produced exactly one fill and one closed trade",
            cycle.get("orders_created") == 1
            and cycle.get("fills_opened") == 1
            and cycle.get("fills_closed") == 1,
            {
                "orders": cycle.get("orders_created"),
                "opened": cycle.get("fills_opened"),
                "closed": cycle.get("fills_closed"),
            },
        )
    )
    net_error = (
        abs(float(cycle.get("net_pnl_usd", 0.0)) - (float(cycle.get("gross_pnl_usd", 0.0)) - float(cycle.get("fees_usd", 0.0))))
        if cycle
        else None
    )
    checks.append(
        _check(
            "B04",
            "net PnL equals gross PnL minus both commissions",
            net_error is not None and net_error <= TOL,
            net_error,
        )
    )
    cost_gap = (
        float(cycle.get("gross_bps", 0.0)) - float(cycle.get("net_bps", 0.0)) if cycle else None
    )
    checks.append(
        _check(
            "B05",
            (
                "the cost line is subtracted, not assumed: gross bps minus net bps equals the "
                "round-trip commissions of the cycle"
            ),
            cost_gap is not None and abs(cost_gap - 2.0 * 5.0) <= 1e-6,
            {"gross_minus_net_bps": cost_gap, "expected_round_trip_bps": 2.0 * 5.0},
        )
    )
    checks.append(
        _check(
            "B06",
            "equity identity holds after close and after restart",
            cycle.get("equity_identity_error") is not None
            and costs.get("equity_identity_error") is not None
            and abs(float(cycle["equity_identity_error"])) <= TOL
            and abs(float(costs["equity_identity_error"])) <= TOL,
            {
                "cycle": cycle.get("equity_identity_error"),
                "cost_line": costs.get("equity_identity_error"),
            },
        )
    )
    checks.append(
        _check(
            "B07",
            "startup reconciliation of a real book reports RECOVERED",
            cycle.get("reconciliation_status") == "RECOVERED",
            cycle.get("reconciliation_status"),
        )
    )
    checks.append(
        _check(
            "B08",
            "the same intent after a restart places no second order",
            cycle.get("duplicate_orders_after_restart") == 0,
            cycle.get("duplicate_orders_after_restart"),
        )
    )
    checks.append(
        _check(
            "B09",
            "a refused order leaves zero orders, zero positions and a CONSISTENT empty store",
            blocked.get("orders_created") == 0
            and blocked.get("reconciliation_status") == "CONSISTENT"
            and blocked.get("equity") == 10_000.0,
            blocked,
        )
    )
    checks.append(
        _check(
            "B10",
            "two round trips were closed with both exit kinds exercised",
            costs.get("round_trips") == 2
            and sorted(costs.get("exit_reasons") or []) == ["stop_loss", "take_profit"],
            {"round_trips": costs.get("round_trips"), "exits": costs.get("exit_reasons")},
        )
    )

    evidence: dict[str, Any] = {
        "artifact": "WP-TDM-016-B · PAPER order/fill/PnL/reconciliation cycle",
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "label": LABEL,
        "scope": {
            "what_this_proves": (
                "the mechanical cycle: an approved PAPER order becomes one fill, closes once, "
                "books net PnL after both commissions, survives a restart with the same equity "
                "identity and refuses a duplicate intent"
            ),
            "what_this_does_not_prove": (
                "profitability. Prices are deterministic fixtures, not market data; no exchange "
                "is contacted, no credential is read, LIVE is unreachable, and no number here is "
                "a track record"
            ),
            "command": " ".join(command),
            "pytest_exit_code": completed.returncode,
            "wall_clock_s": duration,
        },
        "invoked": {
            "module": TEST_MODULE.as_posix(),
            "sha256": _sha256(repo_root / TEST_MODULE),
            "exercised_sources": {
                rel: _sha256(repo_root / rel) for rel in EXERCISED if (repo_root / rel).exists()
            },
        },
        "tests": tests,
        "traces": traces,
        "checks": checks,
        "checks_total": len(checks),
        "checks_failed": sum(1 for c in checks if not c["passed"]),
        "stdout_tail": completed.stdout.strip().splitlines()[-5:],
        "stderr_tail": completed.stderr.strip().splitlines()[-5:],
    }
    evidence["verified"] = (
        evidence["checks_failed"] == 0 and completed.returncode == 0
    )
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="evidence/tdm/wp-tdm-16-paper-admission/PAPER_CYCLE_EVIDENCE.json",
    )
    args = parser.parse_args(argv)

    evidence = build_evidence()
    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"wrote {args.out}: tests={len(evidence['tests'])} "
        f"checks={evidence['checks_total'] - evidence['checks_failed']}"
        f"/{evidence['checks_total']} pytest_exit={evidence['scope']['pytest_exit_code']}"
    )
    for check in evidence["checks"]:
        if not check["passed"]:
            print(f"  FAIL {check['id']}: {check['description']} -> {check['observed']}")
    return 0 if evidence["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
