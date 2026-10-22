"""WP-EDGE-04 — assemble the work package's own artefacts from the live state.

    python scripts/edge04_closure.py --reports reports/edge-recovery/WP-EDGE-04

Writes, from what the observer actually recorded:

* ``EDGE04_FORWARD_COVERAGE.json`` — the forward reading: the freeze, the epoch, the days that
  count, the days that do not and why, the per-period hashes, and the continuity of the schedule;
* ``EDGE04_RESOURCE_BUDGET.json``  — the declared policy next to the measured occupancy, growth,
  per-tick cost and the forecast;
* ``EDGE04_HEALTH_REPORT.json``    — the health reading, the outcome histogram and the alterations;
* ``evidence/``                    — a dated snapshot of the live evidence, digests and all;
* ``evidence/FASE7_TIMELINE.md``   — the tick-by-tick record of the validation window, generated
  rather than recalled;
* ``INDEPENDENT_VERIFICATION.json``— what the verifier that does not share this module's code
  concluded about that snapshot.

It decides nothing and changes nothing: it reads ``data/forward/edge04``, writes under
``--reports`` and runs the verifier. A reader can re-run it after any tick.

Research only: no orders, no credentials, no capital, no promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge01.data import ASSETS  # noqa: E402
from trading_bot.research.edge03 import forward_plan as FP  # noqa: E402
from trading_bot.research.edge03.autonomous import (  # noqa: E402
    GAP_WARNING_SECONDS,
    ForwardObserver,
    read_jsonl,
    stamp,
)

DEFAULT_REPORTS = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-04"
VERIFIER = REPO_ROOT / "scripts" / "edge04_verify.py"
CLOSURE_SCHEMA = "EDGE04_CLOSURE_V1"


def generated_at() -> str:
    return stamp(int(datetime.now(tz=UTC).timestamp() * 1000))


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"corrupt": True}
    return loaded if isinstance(loaded, dict) else {}


def traffic(observer: ForwardObserver) -> dict[str, Any]:
    """What the ticks actually did: outcomes, requests spent, bars appended, slots consumed."""
    runs, corrupt_runs = read_jsonl(observer.runs_path)
    slots, corrupt_slots = read_jsonl(observer.slots_path)
    alerts, corrupt_alerts = read_jsonl(observer.alerts_path)
    keys = [str(row.get("slot_key")) for row in slots]
    return {
        "ticks": len(runs),
        "ticks_by_outcome": dict(sorted(Counter(str(r.get("outcome")) for r in runs).items())),
        "ticks_by_mode": dict(sorted(Counter(str(r.get("mode")) for r in runs).items())),
        "market_requests": sum(int(r.get("market_requests") or 0) for r in runs),
        "bars_appended": sum(int(r.get("new_bars") or 0) for r in runs),
        "slot_rows": len(slots),
        "duplicate_slots": sorted({key for key in keys if keys.count(key) > 1}),
        "alerts": len(alerts),
        "alerts_by_kind": dict(sorted(Counter(str(a.get("kind")) for a in alerts).items())),
        "corrupt_lines": {
            "runs": corrupt_runs,
            "slots": corrupt_slots,
            "alerts": corrupt_alerts,
        },
        "first_tick_utc": runs[0].get("finished_at_utc") if runs else None,
        "last_tick_utc": runs[-1].get("finished_at_utc") if runs else None,
    }


def continuity(observer: ForwardObserver) -> dict[str, Any]:
    """Silence between the ticks that consumed a slot: the schedule's own heart rate."""
    runs, _ = read_jsonl(observer.runs_path)
    observing = [r for r in runs if r.get("outcome") in ("OBSERVED", "NO_NEW_DATA")]
    gaps: list[dict[str, Any]] = []
    for previous, current in pairwise(observing):
        silence = (int(current["finished_at_ms"]) - int(previous["finished_at_ms"])) / 1000.0
        gaps.append(
            {
                "from_utc": previous.get("finished_at_utc"),
                "to_utc": current.get("finished_at_utc"),
                "silence_seconds": round(silence, 3),
            }
        )
    longest = max(gaps, key=lambda g: g["silence_seconds"], default=None)
    over = [g for g in gaps if g["silence_seconds"] > GAP_WARNING_SECONDS]
    failures = [r.get("outcome") for r in runs if r.get("outcome") not in ("OBSERVED",)]
    return {
        "consuming_ticks": len(observing),
        "silences": gaps,
        "longest_silence_seconds": longest["silence_seconds"] if longest else None,
        "silences_over_warning_seconds": over,
        "unavailability_seconds": round(sum(g["silence_seconds"] for g in over), 3),
        "non_observing_outcomes": dict(sorted(Counter(str(f) for f in failures).items())),
        "reading": (
            "silence is measured between the ticks that consumed a slot, because a trigger that "
            "found its slot already sealed is not a gap in the observation"
        ),
    }


def write_coverage(observer: ForwardObserver, outdir: Path, *, now: str) -> dict[str, Any]:
    live = _read_json(observer.coverage_path)
    payload = {
        "schema_version": CLOSURE_SCHEMA,
        "artefact": "EDGE04_FORWARD_COVERAGE.json",
        "work_package": "WP-EDGE-04",
        "generated_at_utc": now,
        "live_coverage_path": str(observer.coverage_path),
        "declared_rule": {
            "required_days": FP.MIN_OBSERVATION_DAYS,
            "coverage_required": FP.OBSERVATION_COVERAGE,
            "prospective_lag_bound_ms": {
                "1h": 2 * 3_600_000,
                "15m": 30 * 60_000,
            },
            "stale_after_ms": {"1h": 4 * 3_600_000, "15m": 4 * 3_600_000},
            "series": [f"{tf}:{sym}" for tf, sym in observer.series],
            "primary_assets": list(ASSETS),
            "reading": (
                "a day counts only if every primary asset holds at least 90% of the bars the "
                "calendar expects for its timeframe, and only if those bars reached the store "
                "while they were still fresh; the frozen corpora are older than the epoch and no "
                "day before it is a forward observation day"
            ),
        },
        "freeze": live.get("freeze"),
        "epoch_utc": live.get("epoch_utc"),
        "prospectively_observed": live.get("prospectively_observed"),
        "prospectively_observed_days": live.get("prospectively_observed_days"),
        "remaining_days": live.get("remaining_days"),
        "densely_covered_but_backfilled": live.get("densely_covered_but_backfilled"),
        "days_with_any_data": live.get("days_with_any_data"),
        "not_counted": live.get("not_counted"),
        "not_an_admission": live.get("not_an_admission"),
        "promotion": "NONE",
        "store_digests": live.get("store_digests"),
        "period_hashes": live.get("period_hashes"),
        "traffic": traffic(observer),
        "continuity": continuity(observer),
        "live_coverage_full": live,
        "hypothetical": True,
        "order_sent": False,
    }
    (outdir / "EDGE04_FORWARD_COVERAGE.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return payload


def write_budget(observer: ForwardObserver, outdir: Path, *, now: str) -> dict[str, Any]:
    live = _read_json(observer.budget_path)
    runs, _ = read_jsonl(observer.runs_path)
    durations = sorted(float(r.get("duration_seconds") or 0.0) for r in runs)
    publication_bytes = sum(
        p.stat().st_size for p in observer.publication_dir.rglob("*") if p.is_file()
    )
    payload = {
        "schema_version": CLOSURE_SCHEMA,
        "artefact": "EDGE04_RESOURCE_BUDGET.json",
        "work_package": "WP-EDGE-04",
        "generated_at_utc": now,
        "live_budget_path": str(observer.budget_path),
        "declared": live.get("declared"),
        "disk": live.get("disk"),
        "measured": live.get("measured"),
        "growth": live.get("growth"),
        "forecast": live.get("forecast"),
        "policy": live.get("policy"),
        "over_budget": live.get("over_budget"),
        "tick_cost": {
            "ticks_measured": len(durations),
            "median_seconds": durations[len(durations) // 2] if durations else None,
            "max_seconds": durations[-1] if durations else None,
            "sum_seconds": round(sum(durations), 3),
            "reading": (
                "wall time of the tick as it recorded it, including the fetch; the disk cost of "
                "one tick is a few kilobytes of bounded logs, because the heavy report set is "
                "rendered once a day and not once a tick"
            ),
        },
        "publication_bytes": publication_bytes,
        "projection": {
            "measured_bytes_per_day": (live.get("growth") or {}).get("bytes_per_day"),
            "lane_bytes_now": (live.get("measured") or {}).get("lane_bytes"),
            "lane_budget_bytes": (live.get("declared") or {}).get("lane_bytes"),
            "days_to_lane_budget": (live.get("forecast") or {}).get("lane_days_to_budget"),
            "days_to_warning_free": (live.get("forecast") or {}).get("days_to_warning_free"),
            "days_to_critical_free": (live.get("forecast") or {}).get("days_to_critical_free"),
            "reading": (
                "the projection is published only when the measured rate is stable; a null is a "
                "measurement that does not exist yet, not a zero"
            ),
        },
        "live_budget_full": live,
        "hypothetical": True,
        "order_sent": False,
    }
    (outdir / "EDGE04_RESOURCE_BUDGET.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return payload


def write_health(
    observer: ForwardObserver, outdir: Path, *, now: str, traffic_row: dict[str, Any]
) -> dict[str, Any]:
    live = _read_json(observer.health_path)
    runs, corrupt = read_jsonl(observer.runs_path)
    failures = [
        {
            "run_id": r.get("run_id"),
            "outcome": r.get("outcome"),
            "reason": r.get("outcome_reason"),
            "at_utc": r.get("finished_at_utc"),
        }
        for r in runs
        if r.get("outcome") not in ("OBSERVED", "NO_NEW_DATA", "ALREADY_OBSERVED")
    ]
    payload = {
        "schema_version": CLOSURE_SCHEMA,
        "artefact": "EDGE04_HEALTH_REPORT.json",
        "work_package": "WP-EDGE-04",
        "generated_at_utc": now,
        "live_health_path": str(observer.health_path),
        "status": live.get("status"),
        "reasons": live.get("reasons"),
        "last_tick": live.get("last_tick"),
        "last_observation_utc": live.get("last_observation_utc"),
        "consecutive_non_observations": live.get("consecutive_non_observations"),
        "ticks_in_window": live.get("ticks_in_window"),
        "expected_ticks_in_window": live.get("expected_ticks_in_window"),
        "outcomes_in_window": live.get("outcomes_in_window"),
        "disk": live.get("disk"),
        "budget_growth_status": (live.get("budget") or {}).get("growth", {}).get("status"),
        "corrupt_log_lines": corrupt,
        "failures": failures,
        "failure_count": len(failures),
        "traffic": {
            "ticks_by_outcome": traffic_row["ticks_by_outcome"],
            "alerts_by_kind": traffic_row["alerts_by_kind"],
            "duplicate_slots": traffic_row["duplicate_slots"],
        },
        "scheduler": observer.install(),
        "verification": {
            "independent_verifier": "scripts/edge04_verify.py",
            "verdict_path": "INDEPENDENT_VERIFICATION.json",
            "reading": (
                "the health artefact is the observer's own reading; the verdict that counts is "
                "the verifier's, which does not share this module's code"
            ),
        },
        "live_health_full": live,
        "hypothetical": True,
        "order_sent": False,
    }
    (outdir / "EDGE04_HEALTH_REPORT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return payload


def write_timeline(observer: ForwardObserver, outdir: Path, *, now: str) -> Path:
    """The validation window, as the run log recorded it rather than as anyone remembers it."""
    runs, _ = read_jsonl(observer.runs_path)
    slots, _ = read_jsonl(observer.slots_path)
    install = observer.install()
    receipts = install.get("receipts") or []
    lines = [
        "# WP-EDGE-04 — FASE 7 timeline (generated)",
        "",
        f"Generated at `{now}` from `{observer.runs_path}` and `{observer.slots_path}`.",
        "Every row below is a tick that really ran; nothing in this file is reconstructed.",
        "",
        f"Registered task: `{install.get('task_name')}` · installed `{install.get('installed')}` · "
        f"enabled `{install.get('enabled')}` · interval `{install.get('interval_minutes')}` min",
        "",
        "## Registration receipts",
        "",
        "| at (UTC) | status | command | arguments | next run (host local) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for receipt in receipts:
        task = receipt.get("task") or {}
        lines.append(
            f"| {receipt.get('at_utc')} | {receipt.get('status')} | `{receipt.get('command')}` | "
            f"`{receipt.get('arguments')}` | {task.get('next_run_time')} |"
        )
    lines += [
        "",
        "## Ticks",
        "",
        "| # | started (UTC) | mode | outcome | slot | requests | new bars | health | exit | lease |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, row in enumerate(runs, start=1):
        lease = (row.get("lease") or {}).get("status") or "—"
        lines.append(
            f"| {index} | {row.get('started_at_utc')} | {row.get('mode')} | "
            f"`{row.get('outcome')}` | {row.get('slot_key')} | {row.get('market_requests')} | "
            f"{row.get('new_bars')} | {row.get('health_status')} | {row.get('exit_code')} | {lease} |"
        )
    lines += [
        "",
        "## Slots consumed",
        "",
        "| slot (UTC) | run | outcome | new bars | requests |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in slots:
        lines.append(
            f"| {row.get('slot_key')} | {row.get('run_id')} | {row.get('outcome')} | "
            f"{row.get('new_bars')} | {row.get('market_requests')} |"
        )
    lines += [
        "",
        "## Alerts raised in the window",
        "",
        "```jsonl",
    ]
    alerts, _ = read_jsonl(observer.alerts_path)
    lines += [json.dumps(row, sort_keys=True) for row in alerts] or ["(none)"]
    lines += ["```", ""]
    path = outdir / "evidence" / "FASE7_TIMELINE.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_verifier(*, evidence: Path, repo: Path, outdir: Path, self_test: bool) -> dict[str, Any]:
    command = [
        sys.executable,
        str(VERIFIER),
        "--state-root",
        str(evidence),
        "--repo",
        str(repo),
        "--install",
        str(evidence / "install.json"),
        "--json-out",
        str(outdir / "INDEPENDENT_VERIFICATION.json"),
    ]
    if self_test:
        command.append("--self-test")
    proc = subprocess.run(command, capture_output=True, text=True, check=False, timeout=600)
    (outdir / "VERIFIER_STDOUT.txt").write_text(
        f"$ {' '.join(command)}\n\n{proc.stdout}\n{proc.stderr}", encoding="utf-8"
    )
    for line in proc.stdout.splitlines():
        print(line)
    return {
        "command": " ".join(command),
        "returncode": proc.returncode,
        "stdout_path": "VERIFIER_STDOUT.txt",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reports", default=str(DEFAULT_REPORTS))
    parser.add_argument("--state-root", default=None)
    parser.add_argument("--store-root", default=None)
    parser.add_argument("--no-snapshot", action="store_true")
    parser.add_argument("--skip-verifier", action="store_true")
    parser.add_argument("--no-self-test", action="store_true")
    args = parser.parse_args(argv)

    outdir = Path(args.reports).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    observer = ForwardObserver(
        repo_root=REPO_ROOT,
        state_root=Path(args.state_root) if args.state_root else None,
        store_root=Path(args.store_root) if args.store_root else None,
    )
    now = generated_at()
    traffic_row = traffic(observer)
    coverage = write_coverage(observer, outdir, now=now)
    budget = write_budget(observer, outdir, now=now)
    health = write_health(observer, outdir, now=now, traffic_row=traffic_row)
    raced: list[str] = []
    if not args.no_snapshot:
        # The schedule keeps ticking while this runs. A snapshot taken across a write is not one
        # instant, so the files are watched: a copy that raced is said to have raced rather than
        # passed off as a reading of a state that never existed.
        watched = (observer.runs_path, observer.slots_path, observer.health_path, observer.budget_path)
        before = {path.name: _digest(path) for path in watched}
        copied = observer.snapshot(outdir / "evidence")
        after = {path.name: _digest(path) for path in watched}
        raced = sorted(name for name in before if before[name] != after[name])
        print(f"snapshot  {len(copied)} files -> {outdir / 'evidence'}")
        if raced:
            print(
                f"snapshot  RACED: a tick wrote {raced} while the copy was taken; the snapshot is "
                "not one instant"
            )
    timeline = write_timeline(observer, outdir, now=now)

    print(f"state root      {observer.state_root}")
    print(f"store root      {observer.store_root}")
    print(f"ticks           {traffic_row['ticks']}  {traffic_row['ticks_by_mode']}")
    print(f"outcomes        {traffic_row['ticks_by_outcome']}")
    print(
        f"slots           {traffic_row['slot_rows']}  duplicates {traffic_row['duplicate_slots']}"
    )
    print(f"requests/bars   {traffic_row['market_requests']} / {traffic_row['bars_appended']}")
    print(f"health          {health.get('status')} ({health.get('reasons')})")
    print(
        f"forward days    {coverage.get('prospectively_observed')} of "
        f"{FP.MIN_OBSERVATION_DAYS} (remaining {coverage.get('remaining_days')})"
    )
    print(
        f"lane / budget   {budget['measured'].get('lane_bytes')} / {budget['declared'].get('lane_bytes')}"
    )
    print(f"free space      {budget['disk'].get('free_gib')} GiB ({budget['disk'].get('status')})")
    print(f"timeline        {timeline}")
    print(f"snapshot raced  {raced or 'no'}")

    if args.skip_verifier:
        print("verifier        skipped")
        return 0
    verdict = run_verifier(
        evidence=outdir / "evidence",
        repo=REPO_ROOT,
        outdir=outdir,
        self_test=not args.no_self_test,
    )
    return 0 if verdict["returncode"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
