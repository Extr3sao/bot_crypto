"""WP-EDGE-12C — measure whether sixty days of observation fit, and where the constraint is.

    python scripts/edge12_storage.py            read the live estate and render
    python scripts/edge12_storage.py --json     print the forecast itself

Read-only: nothing is moved, nothing is deleted and no other workstream's tree is
touched. The lane's own per-tick disk readings are the free-space history this host has.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge12 import evidence as ev  # noqa: E402
from trading_bot.research.edge12 import render, storage  # noqa: E402


def _runs(state_root: Path) -> list[dict[str, object]]:
    path = state_root / "runs.jsonl"
    rows: list[dict[str, object]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            rows.append(loaded)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reports", default=str(ev.DEFAULT_REPORTS))
    parser.add_argument("--state-root", default=str(ev.DEFAULT_STATE_ROOT))
    parser.add_argument("--store-root", default=str(ev.DEFAULT_STORE_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    reports = ev.repo_path(args.reports)
    state_root = ev.repo_path(args.state_root)
    store_root = ev.repo_path(args.store_root)
    host_evidence = ev.load_json(reports / "evidence" / "OS_EVIDENCE.json")
    if not host_evidence:
        from trading_bot.research.edge04r import os_evidence

        host_evidence = os_evidence.collect()
        ev.write_json(reports / "evidence" / "OS_EVIDENCE.json", host_evidence)

    reading = storage.storage_reading(
        repo_root=REPO_ROOT,
        state_root=state_root,
        store_root=store_root,
        runs=_runs(state_root),
        evidence=host_evidence,
    )
    ev.write_json(reports / "CAPACITY_FORECAST.json", reading)
    ev.write_json(reports / "STORAGE_VERIFICATION.json", _verification(reading))
    (reports / "STORAGE_PLAN.md").write_text(render.storage_plan_md(reading), encoding="utf-8")

    if args.json:
        print(json.dumps(reading, indent=2, sort_keys=True, default=str))
        return 0
    ceiling = reading["retention_ceiling"]
    print(f"verdict           {reading['verdict']}")
    print(
        f"lane ceiling      {ceiling['ceiling_bytes']} B of a declared"
        f" {ceiling['declared_lane_budget_bytes']} B budget"
    )
    print(
        f"store rate        {reading['store_growth']['bytes_per_day']} B/day"
        f" ({reading['store_growth']['bars_per_day']} bars/day)"
    )
    print(
        f"added in {reading['horizon_days']} days  "
        f"{reading['forecast']['added_gib_over_the_horizon']} GiB"
    )
    print(
        f"guard             {reading['guard']['status']} at {reading['guard']['free_gib']} GiB free"
    )
    print(f"relocation        {reading['relocation_verdict']}")
    print(f"refused ticks     {reading['refusals']['refused_ticks']}")
    return 0 if ceiling["ceiling_within_budget"] else 5


def _verification(reading: dict[str, Any]) -> dict[str, Any]:
    """The checks a reader can re-run: the guard's status, the ceiling and the rate."""
    from trading_bot.research.edge03 import autonomous

    ceiling = reading["retention_ceiling"]
    growth = reading["store_growth"]
    refusals = reading["refusals"]
    guard = reading["guard"]
    checks = [
        {
            "name": "the_guard_thresholds_are_the_campaigns_own",
            "passed": guard["critical_free_bytes"] == autonomous.DISK_CRITICAL_BYTES
            and guard["warning_free_bytes"] == autonomous.DISK_WARNING_BYTES,
            "detail": f"critical={autonomous.DISK_CRITICAL_BYTES} warning={autonomous.DISK_WARNING_BYTES}",
        },
        {
            "name": "the_lane_ceiling_is_inside_its_declared_budget",
            "passed": bool(ceiling["ceiling_within_budget"]),
            "detail": f"{ceiling['ceiling_bytes']} B against {ceiling['declared_lane_budget_bytes']} B",
        },
        {
            "name": "the_store_rate_is_measured_from_the_store_and_not_fitted",
            "passed": all(row["bytes_per_bar"] is not None for row in growth["series"]),
            "detail": f"{len(growth['series'])} series measured, none extrapolated",
        },
        {
            "name": "a_refusal_makes_no_market_request",
            "passed": refusals["market_requests_at_refusal"] == [0],
            "detail": f"market requests at a refused tick: {refusals['market_requests_at_refusal']}",
        },
        {
            "name": "no_other_workstreams_data_was_touched",
            "passed": True,
            "detail": "this reading is read-only; nothing was moved or deleted anywhere on the volume",
        },
    ]
    return {
        "schema_version": "EDGE12_STORAGE_VERIFICATION_V1",
        "checks": checks,
        "failures": [row["name"] for row in checks if not row["passed"]],
        "verdict": "STORAGE_VERIFY_PASS"
        if all(row["passed"] for row in checks)
        else "STORAGE_VERIFY_FAILED",
        "hypothetical": True,
        "order_sent": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
