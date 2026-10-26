"""WP-EDGE-12E — read what the lane actually did over a declared window.

    python scripts/edge12_operational.py                     the window is the log's own
    python scripts/edge12_operational.py --from <instant>    declare the window's start
    python scripts/edge12_operational.py --until <instant>   declare the window's end
    python scripts/edge12_operational.py --json              print the reading

The window is declared because every figure is a function of it: a reading that ended at
whatever time the reader ran the command would grow by however long the reader took. Git
is not touched, the store is opened read-only, and no tick is taken.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge12 import evidence as ev  # noqa: E402
from trading_bot.research.edge12 import operational, render  # noqa: E402

TASK_NAME = "TradingAgentic-EDGE04-Forward"


def _rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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
    parser.add_argument("--from", dest="window_from", default=None, help="ISO-8601 UTC")
    parser.add_argument("--until", default=None, help="ISO-8601 UTC")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    reports = ev.repo_path(args.reports)
    state_root = ev.repo_path(args.state_root)
    store_root = ev.repo_path(args.store_root)
    evidence_dir = reports / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    from trading_bot.research.edge01.data import ASSETS
    from trading_bot.research.edge03 import autonomous as AUTO
    from trading_bot.research.edge03 import forward_plan as FP
    from trading_bot.research.edge03.run import FORWARD_SERIES

    # The live log is copied first and read from the copy: the lane keeps ticking while this
    # runs, and a reading that mixed two instants of the lane with one instant of the report
    # would not reconcile against itself.
    live_runs = state_root / "runs.jsonl"
    if live_runs.is_file():
        shutil.copyfile(live_runs, evidence_dir / "RUN_LOG_SNAPSHOT.jsonl")
    rows = _rows(evidence_dir / "RUN_LOG_SNAPSHOT.jsonl")

    host_evidence = ev.load_json(evidence_dir / "OS_EVIDENCE.json")
    if not host_evidence:
        from trading_bot.research.edge04r import os_evidence

        host_evidence = os_evidence.collect(task_name=TASK_NAME)
        ev.write_json(evidence_dir / "OS_EVIDENCE.json", host_evidence)

    until_ms = (
        int(operational._parse_ms(args.until) or 0)
        if args.until
        else (int(rows[-1].get("started_at_ms") or 0) if rows else 0)
    )
    window_from = operational._parse_ms(args.window_from) if args.window_from else None
    reading = operational.operational_reading(
        runs=rows,
        evidence=host_evidence,
        interval_seconds=AUTO.SCHEDULE_INTERVAL_SECONDS,
        until_ms=until_ms,
        store_root=store_root,
        series=tuple(FORWARD_SERIES),
        primary_assets=tuple(ASSETS),
        coverage_required=FP.OBSERVATION_COVERAGE,
        forward_days_required=FP.MIN_OBSERVATION_DAYS,
        window_from_ms=window_from,
    )

    ev.write_json(reports / "OPERATIONAL_VALIDATION.json", reading)
    ev.write_json(reports / "FORWARD_COVERAGE.json", reading["coverage"])
    (reports / "OPERATIONAL_VALIDATION.md").write_text(
        render.operational_validation_md(reading), encoding="utf-8"
    )

    if args.json:
        print(json.dumps(reading, indent=2, sort_keys=True, default=str))
        return 0
    levels = reading["levels"]
    print(
        f"window            {reading['window']['from_utc']} -> {reading['window']['to_utc']}"
        f" ({reading['window']['hours']} h)"
    )
    print(
        f"level 1           {levels['one_triggers_fired']['expected_instants']} expected,"
        f" {levels['one_triggers_fired']['answered_by_a_tick']} answered,"
        f" {levels['one_triggers_fired']['never_answered']} never answered"
    )
    print(f"  causes          {reading['losses']['causes']}")
    print(
        f"level 2           {levels['two_observations_made']['slot_consuming_ticks']} slot-consuming,"
        f" {levels['two_observations_made']['fired_and_refused']} fired and refused"
    )
    print(
        f"level 3           {levels['three_days_admissible']['prospectively_observed_days']}"
        f" of {levels['three_days_admissible']['required_days']} admissible days"
    )
    print(f"reconciles        {levels['one_triggers_fired']['equals_the_whole']}")
    print(f"orders            {reading['invariants']['orders_recorded']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
