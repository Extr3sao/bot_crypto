"""Operator status for the PAPER lab (§24, §26, §58).

    uv run python scripts/paper_lab_status.py
    uv run python scripts/paper_lab_status.py --json
    uv run python scripts/paper_lab_status.py --snapshot

Reads the artifacts the lab already writes and prints one screen an operator can
act on: which children are running with which PID, for how long, how far the
heartbeats have drifted, what PAPER has decided, what the collector has captured,
how full the disk is and how long that leaves — plus the five readiness verdicts,
reported separately because they are independent facts.

``--snapshot`` writes the same payload to ``CURRENT_RUN_SNAPSHOT.json`` inside the
run directory, so the operational state at a point in time is evidence instead of
a scrollback buffer.

Read-only by construction: nothing here takes a lock, writes to a running lab, or
can start or stop anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.autonomous.observability import (  # noqa: E402
    STATUS_SCHEMA,
    allow_tolerant_console_output,
    build_status,
    latest_lab_run,
    status_summary,
)
from trading_bot.autonomous.supervisor import DiskThresholds  # noqa: E402

REPO = REPO_ROOT


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", default="reports/paper-lab")
    parser.add_argument("--run-id", default=None, help="default: the newest lab run")
    parser.add_argument("--paper-root", default="reports/autonomous-paper")
    parser.add_argument("--json", action="store_true", help="print the payload, not the summary")
    parser.add_argument(
        "--out",
        default=None,
        help="write the JSON payload here (in addition to printing)",
    )
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="write CURRENT_RUN_SNAPSHOT.json inside the run directory (§24)",
    )
    parser.add_argument("--disk-warning-gb", type=float, default=1.5)
    parser.add_argument("--disk-critical-gb", type=float, default=0.8)
    parser.add_argument("--disk-stop-gb", type=float, default=0.3)
    parser.add_argument(
        "--exit-code-if-not-running",
        action="store_true",
        help="exit 1 when no lab run is found or nothing is running (for monitors)",
    )
    return parser.parse_args(argv)


def thresholds_from_args(args: argparse.Namespace) -> DiskThresholds:
    return DiskThresholds(
        warning_bytes=int(args.disk_warning_gb * 1e9),
        critical_bytes=int(args.disk_critical_gb * 1e9),
        stop_bytes=int(args.disk_stop_gb * 1e9),
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # A log line or a stop report's note can carry a character this code page
    # cannot print; degrading it is right, dying on it is not (§26).
    allow_tolerant_console_output()
    status = build_status(
        lab_root=REPO / args.lab_root,
        run_id=args.run_id,
        paper_root=REPO / args.paper_root,
        thresholds=thresholds_from_args(args),
        quality_path=REPO / "docs" / "FORWARD_DATA_QUALITY_REPORT.json",
        preregistration_path=REPO / "config" / "microstructure_preregistration.json",
    )
    assert status["schema_version"] == STATUS_SCHEMA
    if args.snapshot:
        run_dir = status.get("run_dir")
        if run_dir:
            target = Path(run_dir) / "CURRENT_RUN_SNAPSHOT.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            tmp.replace(target)
            print(f"[status] snapshot: {target}")
    if args.out:
        target = Path(args.out)
        if not target.is_absolute():
            target = REPO / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"[status] payload: {target}")
    if args.json:
        # ``--json`` exists to be piped into another tool, so it must not depend
        # on the console code page: a redirected stdout on Windows is cp1252, and
        # emitting U+2014 as a raw 0x97 byte makes the payload unparseable for
        # whatever reads it. Escaping non-ASCII keeps the bytes pure ASCII, and
        # the JSON means exactly the same thing.
        print(json.dumps(status, indent=2, ensure_ascii=True))
    else:
        print(status_summary(status))
    if args.exit_code_if_not_running:
        if latest_lab_run(REPO / args.lab_root) is None:
            return 1
        if not status.get("system", {}).get("running"):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
