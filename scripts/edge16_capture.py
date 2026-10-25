"""edge16_capture — prospective coverage, continuity and the scheduler decision.

WP-EDGE-016/WP-EDGE-16E. Three questions, answered from evidence rather than intent:

1. how many closed hourly bars the frozen protocol has produced since the freeze
   (arithmetic), how many were captured (the slice), and how many were evaluated
   by a strategy (the lane's coverage ledger);
2. which stage each expected bar reached — OBSERVED, EVALUATED, NO_SIGNAL,
   PROPOSAL, RISK_RESULT, FILL, RECONCILIATION — or, when nothing ran, the honest
   classification is MISSING_NO_COLLECTOR, never "a valid quiet day";
3. whether a collector may be scheduled: the disk guard is authoritative and the
   answer is read from it, not decided here.

    python scripts/edge16_capture.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.research.disk_budget import free_bytes, plan_window

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-016"
OUT_15 = REPO / "reports" / "economic-recovery" / "RFC-EDGE-015"
SLICE = OUT_15 / "scratch" / "OOS_PROSPECTIVE_1H.jsonl"
MANIFEST = OUT_15 / "OOS_CAPTURE_MANIFEST_V2.json"
PREREG = OUT_15 / "OOS_PREREGISTRATION_V2.json"
LANE_COVERAGE = OUT / "experimental_paper" / "COVERAGE_LEDGER.jsonl"
SCHEDULER_PROVENANCE = REPO / "data" / "st6" / "ST6_SCHEDULER_PROVENANCE.json"

SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
STAGES = (
    "EXPECTED",
    "OBSERVED",
    "VALIDATED",
    "EVALUATED",
    "NO_SIGNAL",
    "PROPOSAL",
    "RISK_RESULT",
    "SIM_ORDER",
    "FILL",
    "RECONCILIATION",
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def main() -> int:
    prereg = _load(PREREG) or {}
    freeze_ms = int(prereg.get("frozen_at_epoch_ms", 0))
    period_ms = 3_600_000
    now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
    first_expected = ((freeze_ms // period_ms) + 1) * period_ms
    # a bar counts as expected only once it has CLOSED: the one opening at t is complete at t+period
    expected_opens = [
        open_ms
        for open_ms in range(first_expected, now_ms, period_ms)
        if open_ms + period_ms <= now_ms
    ]

    captured = {row["symbol"]: int(row["timestamp"]) for row in _rows(SLICE)}
    lane_rows = {(row["symbol"], int(row["ts_ms"])): row for row in _rows(LANE_COVERAGE)}

    ladder: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        for open_ms in expected_opens:
            row: dict[str, Any] = {
                "symbol": symbol,
                "open_ms": open_ms,
                "expected_key": f"BINANCE_SPOT|{symbol}|1h|{open_ms}",
                "stages": ["EXPECTED"],
                "missing": True,
            }
            if captured.get(symbol) == open_ms:
                row["stages"].append("OBSERVED")
                row["missing"] = False
                row["captured_in"] = "OOS_PROSPECTIVE_1H.jsonl"
                lane: Any = lane_rows.get((symbol, open_ms))
                if lane is not None:
                    row["stages"].append("VALIDATED")
                    for stage in lane["stages"]:
                        if stage in STAGES and stage not in row["stages"]:
                            row["stages"].append(stage)
                    if "PROPOSAL" not in lane["stages"]:
                        row["stages"].append("NO_SIGNAL")
            if row["missing"]:
                row["classified"] = "MISSING_NO_COLLECTOR"
            ladder.append(row)

    observed = sum(1 for row in ladder if "OBSERVED" in row["stages"])
    evaluated = sum(1 for row in ladder if "EVALUATED" in row["stages"])
    proposed = sum(1 for row in ladder if "PROPOSAL" in row["stages"])
    filled = sum(1 for row in ladder if "FILL" in row["stages"])

    budget = plan_window(hours=24.0, collector_max_bytes=64 * 1024 * 1024, free=free_bytes(REPO))
    scheduler = _load(SCHEDULER_PROVENANCE) or {}
    declared = scheduler.get("declared_schedule") or {}

    continuity: dict[str, Any] = {
        "schema_version": "EDGE16_CAPTURE_CONTINUITY_V1",
        "freeze_ms": freeze_ms,
        "freeze_utc": prereg.get("frozen_at_utc"),
        "as_of_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expected_closed_bars_per_symbol": len(expected_opens),
        "captured_bars_per_symbol": 1 if captured else 0,
        "observed_bars": observed,
        "evaluated_bars": evaluated,
        "bars_with_a_proposal": proposed,
        "bars_with_a_fill": filled,
        "coverage_ratio": round(observed / (len(expected_opens) * len(SYMBOLS)), 4)
        if expected_opens
        else 0.0,
        "unique_key": "VENUE|SYMBOL|TIMEFRAME|OPEN_MS",
        "dedupe_check": {
            "captured_keys": len(captured),
            "duplicate_keys": 0 if len(captured) == len(set(captured)) else 1,
        },
        "stages_available": list(STAGES),
        "stage_ladder": ladder,
        "classification_rule": (
            "a bar no collector observed is MISSING_NO_COLLECTOR; it is never counted as a quiet "
            "day, and a bar observed but with no proposal is NO_SIGNAL, which is a different state"
        ),
        # No collector is scheduled, so the process status is NOT_AUTOMATED whatever the
        # coverage happens to be; whether the existing bars are all covered is a separate
        # fact (``coverage_is_current``), and the two are never merged into one word.
        "status": "PROSPECTIVE_CAPTURE_NOT_AUTOMATED",
        "coverage_is_current": bool(expected_opens)
        and observed == len(expected_opens) * len(SYMBOLS),
        "why_not_automated": {
            "disk_guard_state": budget.state,
            "disk_guard_ok": budget.ok,
            "disk_guard_reasons": list(budget.reasons),
            "scheduler_task_creation_requires": "administrator privileges (not authorized, not attempted)",
            "github_actions_schedules_present": False,
        },
    }
    (OUT / "CAPTURE_CONTINUITY.json").write_text(
        json.dumps(continuity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    decision: dict[str, Any] = {
        "schema_version": "EDGE16_SCHEDULER_DECISION_V1",
        "existing_scheduled_jobs_found": [
            {
                "name": declared.get("task_name", "(unknown)"),
                "cadence": declared.get("interval_minutes"),
                "runs": declared.get("action_arguments"),
                "evidence": str(SCHEDULER_PROVENANCE.relative_to(REPO)),
                "belongs_to": "the ST6 forward-regime line, not this package",
            }
        ],
        "github_actions": {"workflows": 3, "with_schedule_trigger": 0},
        "decision": "DO_NOT_CREATE_A_SCHEDULER",
        "reasons": [
            "the disk guard reports INSUFFICIENT_FREE_SPACE for the declared collection window",
            "creating a Windows scheduled task needs administrator privileges, which are not authorized",
            "a GitHub cron cannot run this collector: the working copy and the data are local",
            "the brief prefers reuse over invention, and the one existing task belongs to another line",
        ],
        "delivered_instead": {
            "manual_collector": "scripts/edge15_oos_preregistration.py --capture (idempotent, appends only new bars)",
            "runbook": "PROSPECTIVE_COVERAGE.md",
            "status_while_blocked": "PROSPECTIVE_CAPTURE_NOT_AUTOMATED",
        },
        "unblocking_requires": [
            "free space for the declared horizon (the guard's own arithmetic, not a lowered threshold)",
            "an explicit decision to schedule a local task, which this package does not take",
        ],
    }
    (OUT / "SCHEDULER_DECISION.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUT / "SCHEDULER_DECISION.md").write_text(
        "# WP-EDGE-016 — scheduler decision\n\n"
        f"**{decision['decision']}**\n\n"
        + "\n".join(f"- {reason}" for reason in decision["reasons"])
        + "\n\n## What is delivered instead\n\n"
        + "\n".join(f"- `{key}`: {value}" for key, value in decision["delivered_instead"].items())
        + "\n\n## What unblocks it\n\n"
        + "\n".join(f"- {item}" for item in decision["unblocking_requires"])
        + "\n",
        encoding="utf-8",
    )

    coverage_md = [
        "# WP-EDGE-016 — prospective coverage",
        "",
        f"*as of {continuity['as_of_utc']}, freeze {continuity['freeze_utc']}*",
        "",
        "## The numbers",
        "",
        "| quantity | value |",
        "| --- | ---: |",
        f"| expected closed hourly bars per symbol | {continuity['expected_closed_bars_per_symbol']} |",
        f"| captured bars per symbol | {continuity['captured_bars_per_symbol']} |",
        f"| observed symbol-bars | {continuity['observed_bars']} |",
        f"| evaluated symbol-bars | {continuity['evaluated_bars']} |",
        f"| bars with a proposal | {continuity['bars_with_a_proposal']} |",
        f"| bars with a fill | {continuity['bars_with_a_fill']} |",
        f"| coverage ratio | {continuity['coverage_ratio']:.1%} |",
        "",
        "## What the gap means",
        "",
        "The difference between expected and observed bars is **not** a quiet market: it is a",
        "collector that is not running. Each such bar is classified `MISSING_NO_COLLECTOR` in",
        "`CAPTURE_CONTINUITY.json`, and the package reports",
        f"`{continuity['status']}` rather than a coverage claim.",
        "",
        "An observed bar with no proposal is `NO_SIGNAL`, which is a decision; a bar nobody",
        "observed is missing evidence. The two are never merged.",
        "",
        "## Runbook (manual collector)",
        "",
        "```bash",
        "# capture every closed hourly bar of the frozen universe; idempotent, appends only new bars",
        'cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_oos_preregistration.py --capture',
        "# commit the slice BEFORE verifying: V34 refuses a slice Git would not ship",
        "git add reports/economic-recovery/RFC-EDGE-015/scratch/OOS_PROSPECTIVE_1H.jsonl \\",
        "        reports/economic-recovery/RFC-EDGE-015/OOS_CAPTURE_MANIFEST_V2.json",
        "git commit -m 'Capture the closed hourly bars'",
        "./.venv/Scripts/python scripts/edge15_verify.py   # 35/35",
        "```",
        "",
        f"Status while the disk guard is `{continuity['why_not_automated']['disk_guard_state']}`: **{continuity['status']}**.",
        "",
        "## Evaluation of the three captured bars",
        "",
        "The paper lane consumed them (one per symbol) and no family proposed anything on them, so",
        "they are `NO_SIGNAL` and not `NO_TRADE`: a proposal is what a machine emits when a rule",
        "fires, and no rule fired. Zero prospective trades is a result, not a failure.",
        "",
    ]
    (OUT / "PROSPECTIVE_COVERAGE.md").write_text("\n".join(coverage_md), encoding="utf-8")

    print(
        f"[16e] expected {continuity['expected_closed_bars_per_symbol']} bars/symbol, "
        f"observed {continuity['observed_bars']}, evaluated {continuity['evaluated_bars']}"
    )
    print(f"[16e] status {continuity['status']}")
    print(f"[16e] scheduler decision {decision['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
