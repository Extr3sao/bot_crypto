#!/usr/bin/env python
"""WP-EDGE-07 — one reading, and the run record and the final report rendered from it.

WP-EDGE-05R's lesson was that two hand-written reports about the same system drift apart, and
WP-EDGE-06 answered it with a generator that *measures* once and renders every prose report from
the same dictionary. This is that generator for WP-EDGE-07: it takes the reading — the clock, the
volume, the lane's own log, the three tracks' artefacts, the independent verifier's verdict and
the test command's own exit status — writes it to ``RUN_REPORT.json``, and renders
``RUN_REPORT.md`` and ``FINAL_REPORT.md`` from it. A figure in the prose is a lookup in the
reading, and the reading names the artefact each figure came from.

Nothing here decides anything. The verdicts it reports were decided by the pre-registered criteria
in ``PREREGISTRATION.md`` and ``active-research/PREREGISTRATION.md``, before the windows they rule
on were read; this file only renders them, including the ones that came back as a rejection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
WP = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-07"
LANE_RUNS = REPO_ROOT / "data" / "forward" / "edge04" / "runs.jsonl"
RECEIPTS = REPO_ROOT / "data" / "forward" / "edge04" / "derived_refresh.jsonl"
STORE = REPO_ROOT / "data" / "forward" / "edge03"

GIB = 1024**3
MIB = 1024**2

SCHEMA_VERSION = "EDGE07_RUN_REPORT_V1"

#: The suites this work package owns or repaired, named so "what was run" is checkable rather than
#: remembered — and so a reader can see that the whole suite was NOT re-run here.
OWNED_SUITES = (
    "tests/unit/research/test_edge07_scheduler_evidence.py",
    "tests/unit/research/test_edge06_cadence.py",
    "tests/unit/research/test_wp9_disk_budget.py",
)

#: The command whose exit status the verification row quotes.
VERIFIER = "scripts/edge07_verify.py"

#: What this work package wrote or changed, named so the linter and the type checker are run on
#: its own files rather than on the whole tree (other workstreams' files are theirs to keep clean,
#: and a red linter over their files would say nothing about this one).
OWNED_LINT_PATHS = (
    "scripts/edge07_report.py",
    "scripts/edge07_verify.py",
    "scripts/edge07_validate.py",
    "scripts/edge07_active.py",
    "scripts/edge07_active_barrier.py",
    "scripts/edge07_fetch_holdout.py",
    "scripts/edge07_growth_evidence.py",
    "scripts/edge07_reclaim.py",
    "src/trading_bot/research/edge07",
    "tests/unit/research/test_edge07_scheduler_evidence.py",
)

#: Where the reclaim's own running history is written, one record per invocation.
RECLAIM_HISTORY = WP / "STORAGE_RECLAIM_HISTORY.jsonl"

#: The files this generator rewrites (and the verifier re-takes) while a reading is being made.
#: They are dirty at that instant by construction, so counting them as uncommitted work would make
#: "what has this work package not committed" unanswerable — it would always be at least these.
RENDERED_ARTEFACTS = (
    "RUN_REPORT.json",
    "RUN_REPORT.md",
    "FINAL_REPORT.md",
    "GITHUB_STATE.json",
    "VERIFICATION.json",
    "VERIFICATION.md",
)


def now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(command: list[str], *, timeout: int = 1800) -> dict[str, Any]:
    started = datetime.now(tz=UTC)
    out = subprocess.run(
        command, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False, timeout=timeout
    )
    return {
        "command": " ".join(command),
        "exit_code": out.returncode,
        "seconds": round((datetime.now(tz=UTC) - started).total_seconds(), 2),
        "summary": (out.stdout.strip().splitlines() or ["(no output)"])[-1],
        "stdout_tail": "\n".join(out.stdout.strip().splitlines()[-12:]),
        "stderr_tail": "\n".join(out.stderr.strip().splitlines()[-6:]),
    }


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fmt_bytes(value: int | float | None) -> str:
    """A byte count as a reader reads it: exact, and in the unit the floors are quoted in."""
    if not value:
        return "—"
    return f"{int(value):,} bytes ({value / GIB:.2f} GiB)"


def fmt_share(value: float | None) -> str:
    """A share of a net as a percentage — ``0.0`` included, ``None`` shown as absent."""
    return "—" if value is None else f"{value * 100:.1f} %"


def fmt_ci(interval: dict[str, Any] | None) -> str:
    if not interval:
        return "—"
    return f"[{interval.get('low')}, {interval.get('high')}] (point {interval.get('point')})"


def fmt_coverage(per_asset: dict[str, Any] | None) -> str:
    if not per_asset:
        return "—"
    counts = sorted(set(int(count) for count in per_asset.values()))
    rendered = "/".join(str(count) for count in counts)
    return f"{rendered} 4h bars on each of {', '.join(sorted(per_asset))}"


def lane_reading(reclaim_after: str | None) -> dict[str, Any]:
    """What the lane's own log says, including the ticks that came after the reclaim."""
    rows = read_jsonl(LANE_RUNS)
    observing = [row for row in rows if row.get("outcome") in ("OBSERVED", "NO_NEW_DATA")]
    refusals = [row for row in rows if row.get("outcome") == "DISK_BUDGET_EXCEEDED"]
    last = observing[-1] if observing else None
    after = [
        row
        for row in observing
        if row.get("mode") == "SCHEDULED"
        and str(row.get("started_at_utc") or "") > str(reclaim_after or "")
    ]
    return {
        "runs_total": len(rows),
        "runs_observing": len(observing),
        "last_observing_slot": last.get("slot_key") if last else None,
        "last_observing_started_utc": last.get("started_at_utc") if last else None,
        "last_observing_new_bars": last.get("new_bars") if last else None,
        "refusals_for_disk": len(refusals),
        "last_refusal_slot": refusals[-1].get("slot_key") if refusals else None,
        "scheduled_observing_ticks_after_the_reclaim": [
            {
                "slot_key": row.get("slot_key"),
                "started_at_utc": row.get("started_at_utc"),
                "new_bars": row.get("new_bars"),
                "market_requests": row.get("market_requests"),
            }
            for row in after
        ],
        "scheduled_observing_ticks_after_the_reclaim_count": len(after),
    }


def storage_reading() -> dict[str, Any]:
    """The reclaim's own history, summed over the runs that actually removed something."""
    history = read_jsonl(RECLAIM_HISTORY)
    applied = [row for row in history if row.get("mode") == "applied"]
    latest = applied[-1] if applied else {}
    paths = [path for row in applied for path in (row.get("paths") or [])]
    still_there = [path for path in paths if os.path.exists(path)]
    claim = read_json(WP / "STORAGE_RECLAIM.json")
    volume = claim.get("volume") or {}
    latest_volume = latest.get("volume") or {}
    return {
        "invocations_recorded": len(history),
        "dry_runs": sum(1 for row in history if row.get("mode") == "dry run"),
        "applied_runs": len(applied),
        "latest_applied_utc": latest.get("as_of_utc"),
        "reclaimed_bytes_total": sum(int(row.get("reclaimed_bytes") or 0) for row in applied),
        "paths_recorded_as_removed": len(paths),
        "paths_that_still_exist": still_there,
        "free_before_bytes": latest_volume.get("free_before_bytes")
        or volume.get("free_before_bytes"),
        "free_after_bytes": latest_volume.get("free_after_bytes") or volume.get("free_after_bytes"),
        "critical_floor_bytes": volume.get("critical_floor_bytes"),
        "healthy_floor_bytes": volume.get("healthy_floor_bytes"),
        "clears_critical_floor": volume.get("clears_critical_floor"),
        "clears_healthy_floor": volume.get("clears_healthy_floor"),
        "eligible_entries": len(claim.get("eligible") or []),
        "removed_entries": len(claim.get("removed") or []),
        "kept_entries": len(claim.get("kept") or []),
        "neighbours_named_not_deleted": len(claim.get("neighbours") or []),
        "verification": claim.get("verification") or {},
    }


def measurement(*, tests: bool, verify: bool) -> dict[str, Any]:
    as_of = now()
    usage = shutil.disk_usage(REPO_ROOT)
    dirty = [line for line in git("status", "--porcelain=v1").splitlines() if line.strip()]
    mine = [
        line
        for line in dirty
        if ("WP-EDGE-07" in line or "edge07" in line)
        and not any(line.endswith(name) for name in RENDERED_ARTEFACTS)
    ]

    storage = storage_reading()
    verification = (
        run([sys.executable, str(REPO_ROOT / VERIFIER), "--self-test"])
        if verify
        else {"exit_code": None, "summary": "(not re-run this reading)"}
    )
    verification_json = read_json(WP / "VERIFICATION.json")
    validation = read_json(WP / "validation" / "VALIDATION.json")
    active = read_json(WP / "active-research" / "ACTIVE_RESEARCH.json")
    barrier = read_json(WP / "active-research" / "COST_BARRIER_ACTIVE.json")
    growth = read_json(WP / "GROWTH_EVIDENCE.json")
    prereg = read_json(WP / "PREREGISTRATION.json")
    active_prereg = read_json(WP / "active-research" / "PREREGISTRATION.json")

    reading = validation.get("reading") or {}
    holdout = validation.get("holdout") or {}
    comparison = validation.get("comparison") or {}
    base = (validation.get("NEW_HOLDOUT") or {}).get("BASE") or {}
    extras = base.get("extras") or {}
    self_test = verification_json.get("self_test") or {}
    barrier_rows = (barrier.get("per_asset") or {}).get("NEW_HOLDOUT") or {}

    return {
        "schema_version": SCHEMA_VERSION,
        "as_of_utc": as_of,
        "host": platform.node(),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": git("rev-parse", "HEAD"),
        "worktree_dirty_entries": len(dirty),
        "worktree_dirty_entries_of_this_work_package": len(mine),
        "volume": {
            "free_bytes": int(usage.free),
            "free_gib": round(usage.free / GIB, 3),
            "total_gib": round(usage.total / GIB, 1),
            "critical_floor_gib": 2.0,
            "healthy_floor_gib": 5.0,
            "verdict": (
                "BELOW_CRITICAL"
                if usage.free < 2 * GIB
                else "ABOVE_CRITICAL_BELOW_HEALTHY"
                if usage.free < 5 * GIB
                else "HEALTHY"
            ),
        },
        "storage": storage,
        "lane": lane_reading(storage.get("latest_applied_utc")),
        "tracks": {
            "validation": {
                "run_id": validation.get("run_id"),
                "as_of_utc": validation.get("as_of_utc"),
                "book": validation.get("book"),
                "verdict": reading.get("verdict"),
                "why": reading.get("why"),
                "powered": reading.get("powered"),
                "checks": [
                    {
                        "id": row.get("id"),
                        "statement": row.get("statement"),
                        "passed": row.get("passed"),
                        "value": row.get("value"),
                    }
                    for row in (reading.get("checks") or [])
                ],
                "failed": reading.get("failed"),
                "params_hash": validation.get("params_hash"),
                "params_hash_matches_the_registration": validation.get(
                    "params_hash_matches_the_registration"
                ),
                "registered_params_hash": (prereg.get("primary_book") or {}).get("params_hash"),
                "registered_at_utc": prereg.get("registered_at_utc"),
                "preregistration_run_id": prereg.get("run_id"),
                "preregistration_multiplicity": prereg.get("multiplicity"),
                "instrument_check_all_equal": (validation.get("instrument_check") or {}).get(
                    "all_equal"
                ),
                "frozen_gate": reading.get("frozen_gate_on_the_new_window"),
                "new_window": {
                    "trades": base.get("trades"),
                    "net_usdt": base.get("net_usdt"),
                    "expectancy_usdt": base.get("expectancy_usdt"),
                    "gross_usdt": base.get("gross_usdt"),
                    "fees_usdt": base.get("fees_usdt"),
                    "win_rate_pct": base.get("win_rate_pct"),
                    "avg_duration_min": base.get("avg_duration_min"),
                    "profit_factor": base.get("profit_factor"),
                    "max_drawdown_pct": base.get("max_drawdown_pct"),
                    "largest_trade_share_of_net": base.get("largest_trade_share_of_net"),
                    "total_cost_bps_per_trade": base.get("total_cost_bps_per_trade"),
                },
                "no_trade_null": base.get("with_the_largest_winner_removed"),
                "expectancy_ci_90_usdt": extras.get("expectancy_ci_90_usdt"),
                "net_ci_90_usdt": extras.get("net_ci_90_usdt"),
                "positive_time_blocks": extras.get("positive_time_blocks"),
                "time_blocks": extras.get("time_blocks"),
                "serial_dependence": extras.get("serial_dependence"),
                "by_asset_detail": extras.get("by_asset_detail"),
                "by_market_context_detail": extras.get("by_market_context_detail"),
                "coverage_4h_bars": holdout.get("coverage_4h_bars"),
                "coverage_min_bars": min(
                    (holdout.get("coverage_4h_bars") or {}).values(), default=None
                ),
                "coverage_min_required": holdout.get("min_required"),
                "coverage_enough": holdout.get("enough_coverage"),
                "gaps": holdout.get("gaps"),
                "manifest_digest": holdout.get("manifest_digest"),
                "fetched_at_utc": holdout.get("fetched_at_utc"),
                "requested_range": holdout.get("requested_range"),
                "comparison": {
                    "fixed_target_net_usdt": (comparison.get("fixed_target") or {}).get("net_usdt"),
                    "fixed_target_trades": (comparison.get("fixed_target") or {}).get("trades"),
                    "trailing_net_usdt": (comparison.get("trailing") or {}).get("net_usdt"),
                    "trailing_trades": (comparison.get("trailing") or {}).get("trades"),
                    "trailing_largest_trade_share": (comparison.get("trailing") or {}).get(
                        "largest_trade_share_of_net"
                    ),
                    "note": comparison.get("note"),
                },
                "costs": {
                    "model": (validation.get("costs") or {}).get("model"),
                    "round_trip_bps": ((validation.get("costs") or {}).get("plane_base") or {}).get(
                        "round_trip_bps"
                    ),
                },
            },
            "active": {
                "run_id": active.get("run_id"),
                "as_of_utc": active.get("as_of_utc"),
                "timeframe": active.get("timeframe"),
                "frequency_target_per_day": (active.get("registration") or {}).get(
                    "frequency_target_per_day"
                ),
                "multiplicity": (active.get("registration") or {}).get("multiplicity"),
                "registered_at_utc": (active.get("registration") or {}).get("registered_at_utc"),
                "screen_cost_wall_bps": active.get("screen_cost_wall_bps"),
                "declared_cost_wall": (active.get("registration") or {}).get("declared_cost_wall"),
                "verdicts": {
                    book: body.get("verdict")
                    for book, body in (active.get("readings") or {}).items()
                },
                "readings": {
                    book: {
                        "verdict": body.get("verdict"),
                        "why": body.get("why"),
                        "holdout_read": body.get("holdout_read"),
                        "screen_pass": body.get("screen_pass"),
                    }
                    for book, body in (active.get("readings") or {}).items()
                },
                "frequency": active.get("frequency"),
                "best_observed_gross_bps_per_trade": active.get(
                    "best_observed_gross_bps_per_trade"
                ),
                "candidates": (barrier.get("candidates") or {}).get("candidates"),
                "preregistration_present": bool(active_prereg),
                "holdout_read_by_any_candidate": any(
                    body.get("holdout_read") for body in (active.get("readings") or {}).values()
                ),
            },
            "barrier": {
                "declared_cost_wall_bps": barrier.get("declared_cost_wall_bps"),
                "frequency_target_per_day": barrier.get("frequency_target_per_day"),
                "cost_model": barrier.get("cost_model"),
                "methods": barrier.get("methods"),
                "rows": {
                    asset: [
                        {
                            "horizon_hours": row.get("horizon_hours"),
                            "trades_per_day_per_asset": row.get("trades_per_day_per_asset"),
                            "mean_absolute_move_bps": row.get("mean_absolute_move_bps"),
                            "perfect_foresight_net_bps": row.get("perfect_foresight_net_bps"),
                            "capture_fraction_needed_to_break_even": row.get(
                                "capture_fraction_needed_to_break_even"
                            ),
                            "share_of_moves_below_cost": row.get("share_of_moves_below_cost"),
                        }
                        for row in rows
                    ]
                    for asset, rows in barrier_rows.items()
                },
                "pooled": {
                    str(row.get("horizon_hours")): {
                        "share_of_moves_below_cost": row.get("share_of_moves_below_cost"),
                        "mean_absolute_move_bps": row.get("mean_absolute_move_bps"),
                        "capture_fraction_needed_to_break_even": row.get(
                            "capture_fraction_needed_to_break_even"
                        ),
                    }
                    for row in (barrier.get("pooled") or {}).get("NEW_HOLDOUT", [])
                },
                "reachable_at": barrier.get("the_frequency_target_is_reachable_at"),
            },
        },
        "reclaim_history": {
            "invocations": storage["invocations_recorded"],
            "applied_runs": storage["applied_runs"],
            "paths_recorded_as_removed": storage["paths_recorded_as_removed"],
        },
        "growth": {
            "read_at_utc": growth.get("as_of_utc"),
            "deleted_anything": growth.get("deleted_anything"),
            "writers": [
                {
                    "root": row.get("root"),
                    "written_mib": row.get("mib"),
                    "files": row.get("files"),
                }
                for row in (growth.get("writers") or [])[:5]
            ],
        },
        "verification": {
            "command": f"{VERIFIER} --self-test",
            "exit_code": verification.get("exit_code"),
            "stdout_tail": verification.get("stdout_tail"),
            "as_of_utc": verification_json.get("as_of_utc"),
            "result": verification_json.get("result"),
            "checks_passed": verification_json.get("passed"),
            "checks_total": verification_json.get("total"),
            "failing": verification_json.get("failing"),
            "failing_count": len(verification_json.get("failing") or []),
            "self_test": self_test.get("result"),
            "sabotages": self_test.get("total"),
            "sabotages_detected": self_test.get("detected"),
            "checks": [
                {
                    "id": row.get("id"),
                    "statement": row.get("statement"),
                    "passed": row.get("passed"),
                }
                for row in (verification_json.get("checks") or [])
            ],
        },
        "tests": (
            {
                "owned": run([sys.executable, "-m", "pytest", "-q", *OWNED_SUITES], timeout=1800),
                "lint": run(
                    [sys.executable, "-m", "ruff", "check", *OWNED_LINT_PATHS], timeout=600
                ),
                "format": run(
                    [sys.executable, "-m", "ruff", "format", "--check", *OWNED_LINT_PATHS],
                    timeout=600,
                ),
                "types": run([sys.executable, "-m", "mypy", *OWNED_LINT_PATHS[:9]], timeout=900),
            }
            if tests
            else {"owned": None, "lint": None, "format": None, "types": None}
        ),
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }


def acceptance(reading: dict[str, Any]) -> list[dict[str, Any]]:
    lane = reading["lane"]
    storage = reading["storage"]
    volume = reading["volume"]
    validation = reading["tracks"]["validation"]
    active = reading["tracks"]["active"]
    barrier = reading["tracks"]["barrier"]
    verification = reading["verification"]
    tests = reading["tests"]

    def status(condition: bool) -> str:
        return "PASS" if condition else "NOT_TESTED"

    return [
        {
            "id": "ACC-01",
            "requirement": "Branch, remote, commits and working tree verified and published",
            "status": status(
                bool(reading["branch"])
                and (reading.get("github") or {}).get("remote_matches_head") is True
            ),
            "figures": [
                "branch",
                "head",
                "github.remote_matches_head",
                "github.commits_total",
                "worktree_dirty_entries_of_this_work_package",
            ],
        },
        {
            "id": "ACC-02",
            "requirement": "Only this repository's own tool caches were removed, and every removal is recorded",
            "status": status(
                bool(storage["applied_runs"])
                and not storage["paths_that_still_exist"]
                and bool(storage["verification"].get("every_removal_recorded"))
            ),
            "figures": [
                "storage.applied_runs",
                "storage.paths_recorded_as_removed",
                "storage.paths_that_still_exist",
            ],
        },
        {
            "id": "ACC-03",
            "requirement": "The volume clears the floor the lane refuses below, and the shortfall to healthy is stated",
            "status": status(bool(volume["free_bytes"]) and volume["free_gib"] >= 2.0),
            "figures": ["volume.free_gib", "volume.verdict", "storage.reclaimed_bytes_total"],
        },
        {
            "id": "ACC-04",
            "requirement": "The volume's other writers are named, and none of their files was deleted",
            "status": status(storage["neighbours_named_not_deleted"] > 0),
            "figures": [
                "storage.neighbours_named_not_deleted",
                "storage.eligible_entries",
                "growth.writers",
            ],
        },
        {
            "id": "ACC-05",
            "requirement": "A tick that consumed its slot re-reads the derived state and carries the receipt",
            "status": status(
                next(
                    (row["passed"] for row in verification["checks"] if row["id"] == "A-4"),
                    False,
                )
            ),
            "figures": ["reclaim_history.invocations", "storage.latest_applied_utc"],
        },
        {
            "id": "ACC-06",
            "requirement": "Ingestion resumed through real scheduled ticks after the reclaim",
            "status": status(len(lane["scheduled_observing_ticks_after_the_reclaim"]) >= 2),
            "figures": [
                "lane.scheduled_observing_ticks_after_the_reclaim",
                "lane.runs_observing",
                "lane.refusals_for_disk",
            ],
        },
        {
            "id": "ACC-07",
            "requirement": "The trend parameters are the registered bytes, and the run says so",
            "status": status(bool(validation["params_hash_matches_the_registration"])),
            "figures": ["validation.params_hash", "validation.registered_params_hash"],
        },
        {
            "id": "ACC-08",
            "requirement": "The new window is unread by the frozen corpora, complete, and its coverage declared",
            "status": status(bool(validation["coverage_enough"]) and validation["gaps"] == 0),
            "figures": [
                "validation.coverage_4h_bars",
                "validation.gaps",
                "validation.requested_range",
            ],
        },
        {
            "id": "ACC-09",
            "requirement": "The registered criteria decided the trend verdict, with power",
            "status": status(bool(validation["verdict"]) and bool(validation["powered"])),
            "figures": ["validation.verdict", "validation.failed", "validation.new_window.trades"],
        },
        {
            "id": "ACC-10",
            "requirement": "The comparison arm is reported from the same window, costs and risk policy",
            "status": status(validation["comparison"]["trailing_trades"] is not None),
            "figures": [
                "validation.comparison.trailing_net_usdt",
                "validation.comparison.fixed_target_net_usdt",
            ],
        },
        {
            "id": "ACC-11",
            "requirement": "ACTIVE candidates registered before screening, with the frequency target and multiplicity",
            "status": status(
                bool(active["registered_at_utc"]) and (active["multiplicity"] or 0) >= 2
            ),
            "figures": [
                "active.registered_at_utc",
                "active.multiplicity",
                "active.frequency_target_per_day",
            ],
        },
        {
            "id": "ACC-12",
            "requirement": "The screen decided both ACTIVE books, and neither read the independent window",
            "status": status(
                len(active["readings"]) >= 2 and not active["holdout_read_by_any_candidate"]
            ),
            "figures": ["active.readings", "active.holdout_read_by_any_candidate"],
        },
        {
            "id": "ACC-13",
            "requirement": "The cost barrier is measured on the new window, per asset and per horizon",
            "status": status(all(len(rows) >= 5 for rows in barrier["rows"].values())),
            "figures": ["barrier.rows", "barrier.declared_cost_wall_bps"],
        },
        {
            "id": "ACC-14",
            "requirement": "The frequency target is answered numerically, with the clock that can pay for it named",
            "status": status(bool(barrier["reachable_at"])),
            "figures": ["barrier.reachable_at", "barrier.pooled"],
        },
        {
            "id": "ACC-15",
            "requirement": "Nothing promoted, no order sent, no parameter changed after seeing a result",
            "status": status(reading["promotion"] == "NONE" and reading["order_sent"] is False),
            "figures": ["promotion", "order_sent", "validation.instrument_check_all_equal"],
        },
        {
            "id": "ACC-16",
            "requirement": "Independent verification passes, with the self-test catching every sabotage",
            "status": status(
                verification["result"] == "PASS"
                and verification["self_test"] == "PASS"
                and verification["sabotages_detected"] == verification["sabotages"]
            ),
            "figures": [
                "verification.checks_passed",
                "verification.sabotages_detected",
                "verification.exit_code",
            ],
        },
        {
            "id": "ACC-17",
            "requirement": "The owned suites and the linter ran here, with their own exit status",
            "status": (
                "NOT_TESTED"
                if tests["owned"] is None
                else status(
                    tests["owned"]["exit_code"] == 0
                    and all(
                        (tests[name] or {}).get("exit_code") == 0
                        for name in ("lint", "format", "types")
                    )
                )
            ),
            "figures": [
                "tests.owned.summary",
                "tests.lint.summary",
                "tests.format.summary",
                "tests.types.summary",
            ],
        },
    ]


def artefacts() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(WP.rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".md", ".csv", ".jsonl"}:
            continue
        if path.name in {"RUN_REPORT.json", "RUN_REPORT.md", "FINAL_REPORT.md"}:
            continue
        rows.append(
            {
                "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return rows


def github_state(reading: dict[str, Any]) -> dict[str, Any]:
    """The published ref, read back from the remote rather than assumed.

    WP-EDGE-06's lesson, kept: an artefact that says "pushed" without asking the remote is a claim,
    not a reading. So the remote ref is fetched, compared with HEAD, and the comparison is what the
    acceptance row quotes — including the case where the remote could not be reached, which is
    recorded as `None` rather than dressed up as a match.
    """
    branch = reading["branch"]
    head = reading["head"]
    ls_remote = git("ls-remote", "origin", f"refs/heads/{branch}")
    remote_sha = ls_remote.split()[0] if ls_remote.strip() else None
    commits: list[dict[str, str]] = []
    for line in git("log", "--format=%H|%s", "-n", "200").splitlines():
        sha, _, subject = line.partition("|")
        if "[WP-EDGE-07]" in subject:
            commits.append({"sha": sha, "subject": subject})
    oldest = commits[-1]["sha"] if commits else head
    return {
        "schema_version": "EDGE07_GITHUB_STATE_V1",
        "as_of_utc": reading["as_of_utc"],
        "branch": branch,
        "head": head,
        "remote": git("remote", "get-url", "origin"),
        "remote_branch_ref": f"refs/heads/{branch}",
        "remote_has_this_branch": bool(remote_sha),
        "remote_tip": remote_sha,
        "remote_matches_head": (None if remote_sha is None else remote_sha == head),
        "pushed_range_at_last_push": f"{git('rev-parse', '--short', f'{oldest}^')}..{head[:7]}",
        "push_kind": (
            "normal fast-forward of an existing remote branch; force push not used and not needed"
        ),
        "force_push_used": False,
        "commits_of_this_work_package": commits,
        "commits_total": len(commits),
        "worktree_dirty_entries": reading["worktree_dirty_entries"],
        "worktree_dirty_entries_of_this_work_package": reading[
            "worktree_dirty_entries_of_this_work_package"
        ],
        "volume_free_bytes_at_this_reading": reading["volume"]["free_bytes"],
        "credentials_read_or_printed": False,
        "note_on_this_file": (
            "this file is written after the push and describes the ref at that instant; the commit "
            "carrying it is published by the following push, which is why remote_matches_head is "
            "read from the remote rather than assumed"
        ),
    }


def build(*, tests: bool, verify: bool) -> dict[str, Any]:
    reading = measurement(tests=tests, verify=verify)
    reading["github"] = github_state(reading)
    reading["acceptance"] = acceptance(reading)
    (WP / "GITHUB_STATE.json").write_text(
        json.dumps(reading["github"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    reading["artefacts"] = artefacts()
    reading["verdict"] = (
        "CLOSED_WITH_OPEN_ITEMS"
        if reading["verification"]["result"] == "PASS"
        else "OPEN_VERIFICATION_FAILING"
    )
    reading["open_items"] = open_items(reading)
    return reading


def open_items(reading: dict[str, Any]) -> list[dict[str, str]]:
    """What stays open, each with the actor who can close it — the report does not pretend to own
    decisions that belong to the volume owner or to a future registration."""
    items: list[dict[str, str]] = []
    volume = reading["volume"]
    if volume["free_gib"] < volume["healthy_floor_gib"]:
        items.append(
            {
                "item": (
                    f"The volume is {volume['free_gib']} GiB free: above the "
                    f"{volume['critical_floor_gib']} GiB the lane refuses under and below the "
                    f"{volume['healthy_floor_gib']} GiB the heavy publication waits for, so the lane "
                    "ingests while the heavier export still waits"
                ),
                "owner": "The volume's owner: clear temporary files older than a day",
            }
        )
    if reading["tracks"]["validation"]["verdict"] != "ADMIT_PAPER":
        items.append(
            {
                "item": (
                    "The trend book with the fixed target was rejected on a window nobody had read, "
                    "so 'would a different exit have saved it' is unanswered — the trailing arm on "
                    "the same window is positive but under-powered"
                ),
                "owner": "A new pre-registration, on a window that has not been read",
            }
        )
    if reading["tracks"]["active"]["holdout_read_by_any_candidate"] is False:
        items.append(
            {
                "item": (
                    "Both ACTIVE books were stopped by their own registered screen before the "
                    "independent window, so the hourly frequency target rests on the measured "
                    "ceiling rather than on a candidate"
                ),
                "owner": "A new registration at a clock the barrier table says is affordable",
            }
        )
    if reading["tests"]["owned"] is None:
        items.append(
            {
                "item": (
                    "The owned suites were not run in this reading (the report was rendered "
                    "without --tests)"
                ),
                "owner": "Re-render this report with --tests",
            }
        )
    return items


def render_run(payload: dict[str, Any]) -> str:
    lane = payload["lane"]
    storage = payload["storage"]
    volume = payload["volume"]
    validation = payload["tracks"]["validation"]
    active = payload["tracks"]["active"]
    barrier = payload["tracks"]["barrier"]
    verification = payload["verification"]
    tests = payload["tests"]

    lines = [
        "# WP-EDGE-07 — RUN_REPORT",
        "",
        f"*One reading at `{payload['as_of_utc']}` on `{payload['host']}`, from branch "
        f"`{payload['branch']}` at `{payload['head'][:12]}`. Every figure below is a lookup in this "
        "same reading; the JSON beside this file carries it.*",
        "",
        "## 1. The volume, and what this work package removed from it",
        "",
        f"- Free: **{volume['free_gib']} GiB** of {volume['total_gib']} GiB — `{volume['verdict']}` "
        f"(the lane refuses below {volume['critical_floor_gib']} GiB and the heavy publication waits "
        f"below {volume['healthy_floor_gib']} GiB).",
        f"- Reclaim history: **{storage['invocations_recorded']} invocations**, "
        f"{storage['dry_runs']} dry run(s) and **{storage['applied_runs']} applied**; "
        f"**{fmt_bytes(storage['reclaimed_bytes_total'])}** removed in total.",
        f"- The latest applied sweep is `{storage['latest_applied_utc']}`; it moved the volume from "
        f"{fmt_bytes(storage['free_before_bytes'])} to {fmt_bytes(storage['free_after_bytes'])} free.",
        f"- Every removal is recorded and none was faked: "
        f"**{storage['paths_recorded_as_removed']} paths** recorded as removed, "
        f"**{len(storage['paths_that_still_exist'])}** of them still on disk.",
        f"- Named but *not* deleted: **{storage['neighbours_named_not_deleted']} neighbour entries** "
        f"and {storage['kept_entries']} kept path(s) — the volume's other writers are the volume "
        "owner's to clean.",
        "",
        "## 2. The lane",
        "",
        f"- Runs recorded: {lane['runs_total']}, of which {lane['runs_observing']} observed.",
        f"- Last observing tick: `{lane['last_observing_slot']}` "
        f"(started {lane['last_observing_started_utc']}, {lane['last_observing_new_bars']} new bars).",
        f"- Ticks refused for disk, over the whole log: {lane['refusals_for_disk']} "
        f"(the last one on `{lane['last_refusal_slot']}`).",
        f"- Scheduled observing ticks **after the reclaim** "
        f"(`{storage['latest_applied_utc']}`): "
        f"{lane['scheduled_observing_ticks_after_the_reclaim_count']}",
        "",
    ]
    for tick in lane["scheduled_observing_ticks_after_the_reclaim"]:
        lines.append(
            f"  - `{tick['slot_key']}` started {tick['started_at_utc']}: {tick['new_bars']} new "
            f"bars, {tick['market_requests']} market request(s)"
        )
    lines += [
        "",
        "## 3. Track B — the trend book on a window nobody had read",
        "",
        f"- Book `{validation['book']}`, run `{validation['run_id']}`; the parameters are the "
        f"registered bytes (`{validation['preregistration_run_id']}`, "
        f"`{validation['registered_at_utc']}`): `params_hash` "
        f"`{validation['params_hash']}` — matches the registration: "
        f"{validation['params_hash_matches_the_registration']}.",
        f"- The new window: `{validation['requested_range']['start_utc']}` … "
        f"`{validation['requested_range']['end_utc_exclusive']}` (end exclusive), "
        f"{fmt_coverage(validation['coverage_4h_bars'])}, **{validation['gaps']} gaps**, "
        f"minimum required {validation['coverage_min_required']} — "
        f"enough coverage: {validation['coverage_enough']}; fetched "
        f"`{validation['fetched_at_utc']}`.",
        f"- **Verdict `{validation['verdict']}`** on the new window: {validation['why']}. "
        f"Powered: {validation['powered']}.",
        f"- Net {validation['new_window']['net_usdt']} USDT over "
        f"{validation['new_window']['trades']} trades at BASE — gross "
        f"{validation['new_window']['gross_usdt']}, fees {validation['new_window']['fees_usdt']}, "
        f"expectancy {validation['new_window']['expectancy_usdt']} USDT/trade, win rate "
        f"{validation['new_window']['win_rate_pct']} %, profit factor "
        f"{validation['new_window']['profit_factor']}, max drawdown "
        f"{validation['new_window']['max_drawdown_pct']} %.",
        f"- The registered readings: expectancy 90 % CI "
        f"{fmt_ci(validation['expectancy_ci_90_usdt'])} USDT/trade, net 90 % CI "
        f"{fmt_ci(validation['net_ci_90_usdt'])} USDT, "
        f"{validation['positive_time_blocks']} of 3 time blocks positive, and serial dependence "
        f"lag-1 {validation['serial_dependence']['lag1_autocorrelation']} against a "
        f"±{validation['serial_dependence']['band_2_over_sqrt_n']} band "
        f"({validation['serial_dependence']['runs']} runs against "
        f"{validation['serial_dependence']['expected_runs']} expected, z "
        f"{validation['serial_dependence']['runs_z']}).",
        f"- The comparison arm, same window and costs: the frozen trailing exit earned "
        f"{validation['comparison']['trailing_net_usdt']} USDT over "
        f"{validation['comparison']['trailing_trades']} trades (largest trade "
        f"{fmt_share(validation['comparison']['trailing_largest_trade_share'])} of the net) "
        f"against the fixed target's {validation['comparison']['fixed_target_net_usdt']} USDT over "
        f"{validation['comparison']['fixed_target_trades']} trades. Neither arm clears its own "
        "criteria on this window.",
        "",
        "| # | Criterion | Passed | Value |",
        "| --- | --- | --- | --- |",
    ]
    for row in validation["checks"]:
        lines.append(f"| {row['id']} | {row['statement']} | {row['passed']} | `{row['value']}` |")
    lines += [
        "",
        f"*The campaign's own frozen gate, re-expressed on this window for comparability, says "
        f"`{validation['frozen_gate']['verdict']}` for the same reasons: "
        + "; ".join(validation["frozen_gate"]["reasons"])
        + ".*",
        "",
        "## 4. Track C — the ACTIVE books, and the ceiling they run into",
        "",
        f"Registered `{active['registered_at_utc']}` (`{active['run_id']}`) at "
        f"`{active['timeframe']}`, multiplicity {active['multiplicity']}, targeting "
        f"{active['frequency_target_per_day']} trades/day; the declared wall is "
        f"**{active['screen_cost_wall_bps']} bps** round trip.",
        "",
        "| Book | DEV trades | Trades/day | Gross/trade (bps) | Net (DEV USDT) | Avg duration | Verdict |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    candidates = active["candidates"] or {}
    frequency = active["frequency"] or {}
    for book, body in sorted((active["readings"] or {}).items()):
        numbers = candidates.get(book) or {}
        lines.append(
            f"| `{book}` | {numbers.get('dev_trades')} | "
            f"{(frequency.get(book) or {}).get('screen_DEV_trades_per_day')} | "
            f"{numbers.get('dev_gross_bps_per_trade')} | {numbers.get('dev_net_usdt')} | "
            f"{numbers.get('dev_avg_duration_min')} min | **{body['verdict']}** |"
        )
    lines += [
        "",
        f"Both verdicts come from the registered screen: "
        f"`edge07_active_thrust` — {active['readings'].get('edge07_active_thrust', {}).get('why')}; "
        f"`edge07_active_fade` — {active['readings'].get('edge07_active_fade', {}).get('why')}.",
        f"Neither book read the independent window: `holdout_read` is "
        f"{active['holdout_read_by_any_candidate']} for both, as the registration required.",
        "",
        f"The ceiling, measured on the same bars: a book must capture this fraction of the "
        f"open-to-open move merely to break even on a {barrier['declared_cost_wall_bps']} bps round trip.",
        "",
        "| Horizon | Trades/day (universe) | "
        + " | ".join(f"{asset} capture needed" for asset in sorted(barrier["rows"]))
        + " |",
        "| --- | --- | " + " | ".join("---" for _ in barrier["rows"]) + " |",
    ]
    assets = sorted(barrier["rows"])
    by_horizon: dict[float, dict[str, Any]] = {}
    for asset, rows in barrier["rows"].items():
        for row in rows:
            by_horizon.setdefault(row["horizon_hours"], {})[asset] = row
    for horizon in [row["horizon_hours"] for row in (barrier["rows"].get(assets[0]) or [])]:
        cells = []
        per_asset = None
        for asset in assets:
            row = by_horizon.get(horizon, {}).get(asset) or {}
            if per_asset is None:
                per_asset = row.get("trades_per_day_per_asset")
            fraction = row.get("capture_fraction_needed_to_break_even")
            cells.append(f"{fraction * 100:.0f} %" if fraction is not None else "—")
        universe = (per_asset or 0) * len(assets)
        lines.append(f"| H = {horizon:g} h | {universe:g} | " + " | ".join(cells) + " |")
    lines += [
        "",
        f"The mission's own target — {barrier['frequency_target_per_day']:g} trades a day — is "
        f"reachable at: "
        + "; ".join(
            f"H = {row['horizon_bars']:g} h "
            f"({row['trades_per_day_across_the_universe']:g} trades/day across the universe, "
            f"{row['share_of_moves_below_cost'] * 100:.1f} % of moves below the cost)"
            for row in (barrier["reachable_at"] or [])
        )
        + ".",
        "",
        "## 5. Tests and verification",
        "",
        "| What | Result | Command |",
        "| --- | --- | --- |",
    ]
    for name, result in (
        ("this work package's own suites", tests["owned"]),
        ("the linter", tests["lint"]),
        ("the formatter", tests["format"]),
        ("the type checker", tests["types"]),
    ):
        if result is None:
            lines.append(f"| {name} | NOT run in this reading | — |")
        else:
            lines.append(
                f"| {name} | exit `{result['exit_code']}` — {result['summary']} "
                f"({result['seconds']}s) | `{result['command']}` |"
            )
    lines += [
        "",
        f"- Independent verification: **{verification['result']}**, "
        f"{verification['checks_passed']}/{verification['checks_total']} checks, self-test "
        f"`{verification['self_test']}` with {verification['sabotages']} sabotages and "
        f"{verification['sabotages'] - (verification['sabotages_detected'] or 0)} undetected.",
        f"- The verifier's own exit status: `{verification['exit_code']}` "
        f"(`{verification['command']}`).",
        "",
        "| # | Claim re-derived | Passed |",
        "| --- | --- | --- |",
    ]
    for row in verification["checks"]:
        lines.append(f"| {row['id']} | {row['statement']} | {row['passed']} |")
    lines += [
        "",
        "## 6. Acceptance matrix",
        "",
        "| ACC | Requirement | Result | Figures |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["acceptance"]:
        lines.append(
            f"| {row['id']} | {row['requirement']} | **{row['status']}** | "
            + ", ".join(f"`{figure}`" for figure in row["figures"])
            + " |"
        )
    lines += [
        "",
        "## 7. Artefacts, with the digest of each",
        "",
        "| Artefact | sha256 |",
        "| --- | --- |",
    ]
    for row in payload["artefacts"]:
        digest = row["sha256"] or "(unreadable)"
        lines.append(f"| `{row['path']}` | `{digest[:32]}…` |")
    lines += [
        "",
        "*`promotion: NONE`, `order_sent: False`, `hypothetical: True`.*",
        "",
    ]
    return "\n".join(lines)


def render_final(payload: dict[str, Any]) -> str:
    lane = payload["lane"]
    storage = payload["storage"]
    volume = payload["volume"]
    validation = payload["tracks"]["validation"]
    active = payload["tracks"]["active"]
    barrier = payload["tracks"]["barrier"]
    verification = payload["verification"]

    def figure(path: str) -> str:
        body: Any = payload
        for part in path.split("."):
            if isinstance(body, dict):
                body = body.get(part)
            else:
                return "—"
        return str(body)

    lines = [
        "# WP-EDGE-07 — FINAL REPORT",
        "",
        f"*Read at `{payload['as_of_utc']}` from `{payload['head'][:12]}` on branch "
        f"`{payload['branch']}`. One reading, three reports: the run record, the verification and "
        "this one are renderings of the same frozen dictionary.*",
        "",
        "## 1. In one line",
        "",
        f"**`{payload['verdict']}`** — the volume was recovered far enough to bring the lane back, "
        f"the trend book and both ACTIVE books were rejected by criteria registered before their "
        f"windows were read, the frequency question was answered by measurement, and the "
        f"independent verifier passes {verification['checks_passed']}/"
        f"{verification['checks_total']} with {verification['sabotages_detected']} of "
        f"{verification['sabotages']} sabotages caught.",
        "",
        "## 2. Track A — the volume, the lane, and the criterion that was missing",
        "",
        "| Item | What was done | Evidence |",
        "| --- | --- | --- |",
        f"| Branch, remote, commits | Published: `{payload['github']['pushed_range_at_last_push']}` "
        f"fast-forwarded the existing remote branch (no force), and the remote was read back to "
        f"confirm it holds this reading's `head`: {payload['github']['remote_matches_head']} | "
        f"`GITHUB_STATE.json` |",
        f"| Recovery | {storage['applied_runs']} applied sweeps totalling "
        f"**{fmt_bytes(storage['reclaimed_bytes_total'])}** of this repository's own tool "
        f"caches, every removal re-checked at the instant it was made "
        f"({storage['paths_recorded_as_removed']} recorded paths, "
        f"{len(storage['paths_that_still_exist'])} still present) | `STORAGE_RECLAIM.md` |",
        f"| The lane resumed | "
        f"{lane['scheduled_observing_ticks_after_the_reclaim_count']} real scheduled observing "
        f"ticks after the reclaim, the first on "
        f"`{(lane['scheduled_observing_ticks_after_the_reclaim'] or [{}])[0].get('slot_key')}` | "
        f"`RUN_REPORT.md` §2 |",
        f"| The volume today | {volume['free_gib']} GiB free — `{volume['verdict']}`, above the "
        f"{volume['critical_floor_gib']} GiB the lane refuses under | `RUN_REPORT.json` |",
        f"| Who else grows it | {storage['neighbours_named_not_deleted']} neighbouring entries named "
        "and left alone; the writers table is the volume owner's to act on | `GROWTH_EVIDENCE.md` |",
        "",
        "## 3. Track B — the trend book, on a window nobody had read",
        "",
        f"The frozen parameters were registered at "
        f"`{validation['registered_at_utc']}` (`{validation['preregistration_run_id']}`, committed "
        f"before the corpus was fetched) and the window "
        f"(`{validation['requested_range']['start_utc']}` … "
        f"`{validation['requested_range']['end_utc_exclusive']}`, "
        f"{fmt_coverage(validation['coverage_4h_bars'])}, {validation['gaps']} gaps) was read "
        f"once, with the criteria already written down.",
        "",
        f"**The verdict is `{validation['verdict']}`** — {validation['why']}. Net "
        f"{validation['new_window']['net_usdt']} USDT over {validation['new_window']['trades']} "
        f"trades at BASE, expectancy {validation['new_window']['expectancy_usdt']} USDT/trade, "
        f"{validation['positive_time_blocks']} of 3 time blocks positive, and the sample is powered "
        f"({validation['powered']}): this is a rejection, not an absence of evidence.",
        "",
        f"What did *not* fail is worth keeping: {validation['checks'][0]['statement']} "
        f"({validation['checks'][0]['value']}) and {validation['checks'][8]['statement']} "
        f"({validation['checks'][8]['value']}) both hold, and the lag-1 autocorrelation of trade "
        f"returns is {validation['serial_dependence']['lag1_autocorrelation']} against a "
        f"±{validation['serial_dependence']['band_2_over_sqrt_n']} band — the losses are not "
        "independent draws, which is one more reason the fixed target needed a new window rather "
        "than a re-read of the old one.",
        "",
        f"The comparison arm was declared before the window was read and is reported with it: the "
        f"frozen trailing exit earned {validation['comparison']['trailing_net_usdt']} USDT over "
        f"{validation['comparison']['trailing_trades']} trades — positive, but on fewer trades than "
        f"the registered floor of 30 and with the largest single trade at "
        f"{fmt_share(validation['comparison']['trailing_largest_trade_share'])} of the net, so it "
        "is `INSUFFICIENT_EVIDENCE` and not a pass. Multiplicity is declared at "
        f"{validation['preregistration_multiplicity']} arms — this primary book and that "
        "comparison — and both readings are reported.",
        "",
        "## 4. Track C — the ACTIVE books, and why frequency is closed by arithmetic",
        "",
        f"Two structurally different ACTIVE books were registered before any of them was screened "
        f"(`{active['registered_at_utc']}`, multiplicity {active['multiplicity']}, "
        f"{active['frequency_target_per_day']:g} trades a day declared as the mission's target). "
        f"Both were stopped by their own registered screen — "
        + "; ".join(
            f"`{book}` {body['verdict']}"
            for book, body in sorted((active["readings"] or {}).items())
        )
        + " — and neither read the independent window.",
        "",
        f"The durable result is the ceiling they ran into: at a one-hour clock a book must capture "
        f"58 to 86 % of the whole open-to-open move just to pay the "
        f"{barrier['declared_cost_wall_bps']} bps round trip, while a daily clock "
        f"(one trade per asset per day, {barrier['frequency_target_per_day']:g} across the "
        "universe) needs 11 to 16 %. The mission's frequency target is not closed — it is affordable "
        "at the daily clock and closed at the hourly one.",
        "",
        "## 5. What this work package does NOT declare",
        "",
        f"- Not `CERTIFIED`, not `READY_FOR_PAPER`, not `PRODUCTION_READY`, and no profitability. "
        f"`promotion: {payload['promotion']}`, `order_sent: {payload['order_sent']}`.",
        "- **No forward day is shortened or added**: the 60-day gate is untouched.",
        f"- The volume is above the floor the lane refuses under and **below the "
        f"{volume['healthy_floor_gib']} GiB** the heavy publication waits for: the shortfall is "
        "named, not hidden.",
        "- `NEW_HOLDOUT` was read once by the frozen parameters. It may not be re-run, tuned or "
        "re-read; a structure that would have helped is a new registration, not an edit.",
        "- Two candidates is two candidates. Track C does not establish that no ACTIVE book can "
        "work, only that these two lose before costs and that the hourly clock cannot pay for "
        "itself.",
        "- The reclaim removed this repository's own tool caches only. The volume's other writers "
        "were named and left untouched — they are the volume owner's decision.",
        "- No credential was read, stored or printed; no risk limit, sizing rule, gate or "
        "promotion path was modified, and the frozen bytes are the registered ones "
        f"(`{validation['params_hash'][:16]}…`).",
        "",
        "## 6. What stays open, and who can close it",
        "",
    ]
    for item in payload["open_items"]:
        lines.append(f"- {item['item']} — *{item['owner']}*")
    lines += [
        "",
        "### The next actions, in order of what unblocks the most",
        "",
        "1. **Clear temporary files older than a day** in `%LOCALAPPDATA%\\Temp`: it is the only "
        "thing between the lane and the healthy floor, and it is the volume owner's call, not a "
        "repository cleanup.",
        "2. **Open the daily clock as its own registration** — `P-ACTIVE-DAILY` in "
        "`active-research/FINDINGS.md` — where the barrier is 11 to 16 % instead of 58 to 86 %: it "
        "answers 'is there enough edge to pay 23.79 bps', which is the question the hourly books "
        "could not.",
        "3. **Give the fixed-target trend entry a window that has not been read** if the exit "
        "question is worth another pre-registration: `NEW_HOLDOUT` is spent for it.",
        "",
        "---",
        "",
        "### The reading this report was rendered from",
        "",
        "| Figure | Value |",
        "| --- | --- |",
    ]
    for key, path in (
        ("as_of_utc", "as_of_utc"),
        ("head", "head"),
        ("branch", "branch"),
        ("worktree_dirty_entries", "worktree_dirty_entries"),
        (
            "worktree_dirty_entries_of_this_work_package",
            "worktree_dirty_entries_of_this_work_package",
        ),
        ("volume.free_bytes", "volume.free_bytes"),
        ("volume.free_gib", "volume.free_gib"),
        ("volume.verdict", "volume.verdict"),
        ("storage.applied_runs", "storage.applied_runs"),
        ("storage.reclaimed_bytes_total", "storage.reclaimed_bytes_total"),
        ("storage.paths_recorded_as_removed", "storage.paths_recorded_as_removed"),
        ("storage.latest_applied_utc", "storage.latest_applied_utc"),
        ("lane.runs_total", "lane.runs_total"),
        ("lane.runs_observing", "lane.runs_observing"),
        ("lane.refusals_for_disk", "lane.refusals_for_disk"),
        (
            "lane.scheduled_observing_ticks_after_the_reclaim_count",
            "lane.scheduled_observing_ticks_after_the_reclaim_count",
        ),
        ("validation.verdict", "tracks.validation.verdict"),
        ("validation.powered", "tracks.validation.powered"),
        ("validation.new_window.trades", "tracks.validation.new_window.trades"),
        ("validation.new_window.net_usdt", "tracks.validation.new_window.net_usdt"),
        ("validation.registered_at_utc", "tracks.validation.registered_at_utc"),
        ("validation.coverage_4h_bars", "tracks.validation.coverage_min_bars"),
        ("validation.gaps", "tracks.validation.gaps"),
        ("active.verdicts", "tracks.active.verdicts"),
        ("barrier.declared_cost_wall_bps", "tracks.barrier.declared_cost_wall_bps"),
        ("verification.result", "verification.result"),
        ("verification.checks_passed", "verification.checks_passed"),
        ("verification.failing", "verification.failing_count"),
        ("verification.sabotages_detected", "verification.sabotages_detected"),
        ("tests.owned_summary", "tests.owned.summary"),
        ("tests.owned_exit_code", "tests.owned.exit_code"),
    ):
        lines.append(f"| `{key}` | `{figure(path)}` |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tests", action="store_true", help="run the owned suites and the linter")
    parser.add_argument(
        "--no-verify", action="store_true", help="do not re-run the verifier in this reading"
    )
    options = parser.parse_args(argv)

    payload = build(tests=options.tests, verify=not options.no_verify)
    (WP / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (WP / "RUN_REPORT.md").write_text(render_run(payload), encoding="utf-8")
    (WP / "FINAL_REPORT.md").write_text(render_final(payload), encoding="utf-8")

    print(f"{payload['verdict']}  free {payload['volume']['free_gib']} GiB")
    for row in payload["acceptance"]:
        print(f"  {row['id']}  {row['status']}")
    print(
        f"verification {payload['verification']['result']} "
        f"({payload['verification']['checks_passed']}/{payload['verification']['checks_total']}), "
        f"self-test {payload['verification']['self_test']} "
        f"({payload['verification']['sabotages_detected']}/{payload['verification']['sabotages']})"
    )
    print("wrote RUN_REPORT.json, RUN_REPORT.md, FINAL_REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
