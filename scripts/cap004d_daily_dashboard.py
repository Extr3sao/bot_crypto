"""CAP-004D daily dashboard: one markdown summary of the campaign's health.

Reads only decided, tail-bounded evidence (health journal, alert table,
supervisor status + operations ledger) and writes a single markdown file a
human can scan in ten seconds.  Observe-only: it never mutates campaign
state, and a missing input degrades to a noted gap instead of a crash.

Usage: python scripts/cap004d_daily_dashboard.py [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import cap004_supervisor as sup  # noqa: E402

from trading_bot.research import campaign_health as ch  # noqa: E402

REPORT_ROOT = REPO / "reports" / "cap004d"
SUPERVISOR_STATUS = REPO / "reports" / "cap004b" / "SUPERVISOR_STATUS.json"

SEVERITY_ORDER = {"CRITICAL": 0, "DEGRADED": 1, "INFO": 2}

#: Windows Task Scheduler results worth naming in the dashboard (the raw
#: numbers are otherwise indistinguishable from failures).  267009 = 0x41301
#: SCHED_S_TASK_RUNNING; 267011 = 0x41303 the task has not yet run; 3 =
#: ERROR_PATH_NOT_FOUND.  Unknown values render raw — honest over clever.
SCHEDULER_RESULT_NAMES = {
    0: "OK",
    3: "PATH_NOT_FOUND",
    267009: "RUNNING (0x41301)",
    267011: "NOT_RUN_YET (0x41303)",
    267014: "TERMINATED (0x41306)",
}


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _utc(ts: int | None) -> str:
    if not ts:
        return "—"
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts)))


def _scheduler_result_name(value: Any) -> Any:
    try:
        code = int(value)
    except (TypeError, ValueError):
        return value
    return f"{code} ({SCHEDULER_RESULT_NAMES.get(code, 'unknown')})"


def _health_section() -> list[str]:
    lines = ["## Campaign health (latest CAP-004D verdict)", ""]
    # The compact journal event omits scheduler/disk fields by design (§21);
    # the full snapshot carries them, so prefer it and fall back to the tail.
    snapshot = _load_json(REPORT_ROOT / "CAMPAIGN_HEALTH.json")
    events = ch.read_health_tail(REPORT_ROOT, limit=1)
    e = snapshot or (events[-1] if events else None)
    if e is None:
        return [*lines, "_no health event yet — run `scripts/cap004d_health_check.py`_", ""]
    lines += [
        f"- **verdict**: `{e.get('health_status')}` at {_utc(e.get('observed_at'))}",
        f"- reasons: `{','.join(e.get('reason_codes') or []) or 'none'}`",
        f"- scheduler: enabled={e.get('scheduler_enabled')} "
        f"last_result={_scheduler_result_name(e.get('scheduler_last_result'))}",
        f"- chain: `{e.get('chain_status')}` · verify: `{e.get('last_verify_status')}` "
        f"· disk: `{e.get('disk_status')}` (free {e.get('disk_free_bytes', 0) / 2**30:.1f} GiB)",
        f"- cycle age: {e.get('cycle_age_seconds')} s · heartbeat age: "
        f"{e.get('heartbeat_age_seconds')} s · pending settlements: "
        f"{e.get('pending_settlements')}",
        f"- days until warning/critical: {e.get('days_until_warning')} / "
        f"{e.get('days_until_critical')}",
        "",
    ]
    return lines


def _alerts_section() -> list[str]:
    lines = ["## Watchdog alerts", ""]
    store = ch.AlertStore(REPORT_ROOT / "ALERTS.jsonl")
    alerts = store.all()
    if not alerts:
        return [*lines, "_no alert episode ever recorded_", ""]
    open_alerts = sorted(
        store.open_alerts(), key=lambda a: (SEVERITY_ORDER.get(a.severity, 9), a.first_seen_at)
    )
    lines.append(f"- **open: {len(open_alerts)}** of {len(alerts)} episodes")
    lines += [
        "",
        "| status | reason | severity | first seen | last seen | occurs |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    recent = sorted(alerts, key=lambda a: a.last_seen_at, reverse=True)[:8]
    for a in recent:
        lines.append(
            f"| {a.status} | `{a.reason_code}` | {a.severity} | {_utc(a.first_seen_at)} | "
            f"{_utc(a.last_seen_at)} | {a.occurrence_count} |"
        )
    lines.append("")
    return lines


def _supervisor_section() -> list[str]:
    lines = ["## Supervisor (CAP-004B)", ""]
    status = _load_json(SUPERVISOR_STATUS)
    if status:
        sched = status.get("scheduler") or {}
        lines += [
            f"- state: `{status.get('supervisor_state')}` · campaign: "
            f"`{status.get('campaign_status')}` · chain: `{status.get('chain_status')}`",
            f"- last run: {status.get('last_run_utc')} · last success: "
            f"{status.get('last_success_utc')}",
            f"- task `{sched.get('task_name')}`: enabled={sched.get('enabled')} "
            f"result={_scheduler_result_name(sched.get('last_task_result'))} "
            f"next={sched.get('next_run_time')}",
        ]
    else:
        lines.append("_SUPERVISOR_STATUS.json not found_")
    try:
        ops = sup.read_operations(sup.OPS_LEDGER)[-6:]
        lines += ["", "| cycle (UTC) | action | exit | error |", "| --- | --- | --- | --- |"]
        for o in ops:
            lines.append(
                f"| {o.get('ended_at_utc')} | {o.get('action')} | {o.get('exit_code')} | "
                f"{o.get('error_type') or '—'} |"
            )
    except Exception as exc:  # observability must never crash the dashboard
        lines.append(f"_operations ledger unavailable: {exc}_")
    lines.append("")
    return lines


def _governance_section() -> list[str]:
    return [
        "## Governance",
        "",
        "TRADES_AUTHORIZED=0 · G_AGENTIC_EDGE=NOT_TESTED · ALPHA-004 not opened · "
        "NEXT_GATE=ACCUMULATE_REAL_DECISIONS",
        "",
        "_Generated by `scripts/cap004d_daily_dashboard.py`; observe-only, "
        "no analyst behaviour changed._",
        "",
    ]


def build_dashboard() -> str:
    lines = [
        "# CAP-004D — daily campaign dashboard",
        "",
        f"_generated {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}_",
        "",
    ]
    for section in (_health_section, _alerts_section, _supervisor_section, _governance_section):
        lines += section()
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPORT_ROOT / "DAILY_DASHBOARD.md",
        help="output markdown path (default: reports/cap004d/DAILY_DASHBOARD.md)",
    )
    args = parser.parse_args(argv)
    args.out.write_text(build_dashboard(), encoding="utf-8")
    print(f"dashboard written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
