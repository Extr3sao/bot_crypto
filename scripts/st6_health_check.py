"""ST-6 — independent health check for the autonomous forward observation.

A separate program from the tick and from the verifier, and read-only with respect to the campaign:
it takes no sample, renews no lease, changes no threshold and repairs no hash.  It answers one
question — *is the observation programme still doing what it declared, and is the evidence it claims
actually there?* — and it answers it from the files on disk and from the scheduler's own
registration, never from a heartbeat:

* the scheduler's registration is read from the task definition (installed, enabled, enabled
  interval) and is explicitly **not** treated as evidence that a measurement was taken: a tick that
  ran and skipped the exchange is a healthy tick that observed nothing, and the health artefact says
  so instead of pretending otherwise;
* windows come from the window index and their raw bytes are re-hashed before they are counted;
* every declared slot that has already ended is required to be either an observed window or a
  recorded ``MISSED_WINDOW``; an end-of-slot that is in neither state is a CRITICAL divergence
  between what the programme says and what it recorded;
* storage is read through the campaign's existing disk guard, not a second threshold set;
* the heartbeat age is a *hint* about the tick, and a missing tick is a WARNING about the schedule,
  never a claim about the data.

States and exit codes (§33 of this repository's convention):

    0 = HEALTHY, 10 = WARNING, 20 = CRITICAL, 30 = PERIOD_COMPLETED, 40 = CHECK_FAILED

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.disk_space import disk_report  # noqa: E402

DATA = REPO / "data" / "st6"
PERIOD = DATA / "ST6_PERIOD.json"
WINDOWS = DATA / "ST6_WINDOWS.jsonl"
OBSERVATIONS = DATA / "ST6_OBSERVATIONS.jsonl"
RUN_LOG = DATA / "ST6_RUNS.jsonl"
MISSED_LOG = DATA / "ST6_MISSED_WINDOWS.jsonl"
CLOSURE = DATA / "ST6_PERIOD_CLOSURE.json"
HEALTH_STATUS = DATA / "ST6_HEALTH_STATUS.json"
HEALTH_LOG = DATA / "ST6_HEALTH.jsonl"
SCHEDULER_REPORT = DATA / "ST6_SCHEDULER_REPORT.json"
SCHEDULER_VERIFICATION = DATA / "ST6_SCHEDULER_VERIFICATION.json"
TASK_NAME = "TradingAgentic-ST6-Forward"

SLOT_HOURS = 4
SLOTS_PER_DAY = 6
TICK_GRACE_SECONDS = 45 * 60  # three missed ticks before the schedule is called stale
HEALTH_EVENTS_KEPT = 400
MAX_MISSED_FRACTION = 0.2
CONSECUTIVE_FAILURES_CRITICAL = 3

HEALTHY, WARNING, CRITICAL, PERIOD_COMPLETED = (
    "HEALTHY",
    "WARNING",
    "CRITICAL",
    "PERIOD_COMPLETED",
)
STATES = (HEALTHY, WARNING, CRITICAL, PERIOD_COMPLETED)
EXIT_HEALTHY = 0
EXIT_WARNING = 10
EXIT_CRITICAL = 20
EXIT_PERIOD_COMPLETED = 30
EXIT_CHECK_FAILED = 40


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def raw_evidence_state(windows: list[dict[str, Any]]) -> dict[str, Any]:
    """Re-hash the raw evidence of every window: the health of the programme is the health of its bytes."""
    missing: list[str] = []
    mismatched: list[str] = []
    for window in windows:
        path = Path(window["raw"]["path"])
        if not path.is_absolute():
            path = REPO / path
        if not path.exists():
            missing.append(window["raw"]["path"])
            continue
        with gzip.open(path, "rb") as handle:
            payload = handle.read()
        if hashlib.sha256(payload).hexdigest() != window["raw"]["uncompressed_sha256"]:
            mismatched.append(window["raw"]["path"])
    return {
        "windows": len(windows),
        "missing": missing,
        "mismatched": mismatched,
        "reading": "every window's uncompressed bytes were re-hashed before it was counted",
    }


def scheduler_registration() -> dict[str, Any]:
    """Exactly what the host says about the task.  Never evidence of a measurement."""
    state: dict[str, Any] = {
        "task_name": TASK_NAME,
        "installed": False,
        "enabled": None,
        "repetition_interval": None,
        "query_exit_code": None,
        "query_error": None,
    }
    try:
        result = __import__("subprocess").run(
            ["schtasks", "/query", "/tn", TASK_NAME, "/xml"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:  # a missing scheduler is reported, never hidden
        state["query_error"] = f"{type(exc).__name__}: {exc}"
        return state
    state["query_exit_code"] = result.returncode
    if result.returncode != 0:
        state["query_error"] = (result.stderr or result.stdout or "").strip()[:200]
        return state
    try:
        root = ElementTree.fromstring(result.stdout.lstrip("\ufeff"))
    except ElementTree.ParseError as exc:
        state["query_error"] = f"ParseError: {exc}"
        return state
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    state["installed"] = True
    settings = root.find("t:Settings", ns)
    if settings is not None:
        enabled = settings.find("t:Enabled", ns)
        state["enabled"] = (
            True if enabled is None else (enabled.text or "").strip().lower() == "true"
        )
    repetition = root.find("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", ns)
    state["repetition_interval"] = None if repetition is None else (repetition.text or "").strip()
    return state


def declared_slots_upto(period: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """The declared slots up to ``now``, bounded by the plan: days x slots per day, no more.

    The partial slot the period's end falls into is not a planned window, so it can never be
    counted as pending, missed or unaccounted.
    """
    start = _parse(period["started_at_utc"])
    last = min(now, _parse(period["ends_at_utc"]))
    planned = int(period["period_days"]) * int(period["slots_per_day"])
    cursor = start.replace(minute=0, second=0, microsecond=0)
    slots: list[dict[str, Any]] = []
    while cursor <= last and len(slots) < planned:
        index = cursor.hour // SLOT_HOURS
        slots.append(
            {
                "key": f"{cursor.strftime('%Y-%m-%d')}#{index}",
                "day": cursor.strftime("%Y-%m-%d"),
                "slot_index": index,
                "ends_at_utc": (cursor + timedelta(hours=SLOT_HOURS)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        )
        cursor += timedelta(hours=SLOT_HOURS)
    return slots


def closure_of_declared_period(period: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Read the consolidation by identity: only the closure *of this period* counts.

    A closure file on disk can belong to a rehearsal, a test period or an earlier run; its mere
    existence must never be read as "the period was consolidated".
    """
    document = read_json(CLOSURE)
    if document is None:
        return None, "absent"
    closed = document.get("period") or {}
    declared = (period.get("started_at_utc"), period.get("ends_at_utc"))
    found = (closed.get("started_at_utc"), closed.get("ends_at_utc"))
    if found != declared:
        return None, f"belongs to another period: {found[0]} -> {found[1]}"
    return document, "belongs to the declared period"


def consecutive_failures(runs: list[dict[str, Any]]) -> int:
    streak = 0
    for run in reversed(runs):
        if run.get("errors"):
            streak += 1
        else:
            break
    return streak


def evaluate(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC).replace(microsecond=0)
    period = read_json(PERIOD)
    if period is None:
        return {
            "artifact": "ST6_HEALTH_STATUS",
            "generated_at_utc": _utc(),
            "status": "CHECK_FAILED",
            "reasons": ["no period is declared, so there is nothing to observe"],
            "exit_code": EXIT_CHECK_FAILED,
        }
    windows = read_jsonl(WINDOWS)
    observations = read_jsonl(OBSERVATIONS)
    runs = read_jsonl(RUN_LOG)
    missed = read_jsonl(MISSED_LOG)
    closure, closure_reading = closure_of_declared_period(period)
    registration = scheduler_registration()
    disk = disk_report(REPO)
    evidence = raw_evidence_state(windows)
    slots = declared_slots_upto(period, now)
    all_slots = declared_slots_upto(period, _parse(period["ends_at_utc"]))
    observed = {f"{row['day']}#{row['slot_index']}" for row in windows}
    recorded_missed = {row["slot_key"] for row in missed}
    ended = [entry for entry in slots if _parse(entry["ends_at_utc"]) <= now]
    # what the programme still has to collect before its declared end, which is what a reader of a
    # pending count expects to see
    pending = [
        entry
        for entry in all_slots
        if entry["key"] not in observed and _parse(entry["ends_at_utc"]) > now
    ]
    unaccounted = [
        entry["key"]
        for entry in ended
        if entry["key"] not in observed and entry["key"] not in recorded_missed
    ]
    missed_fraction = (
        round(len([entry for entry in ended if entry["key"] not in observed]) / len(ended), 6)
        if ended
        else None
    )
    last_run = runs[-1] if runs else None
    heartbeat_age_s = None
    if last_run and last_run.get("actual_end_utc"):
        heartbeat_age_s = int((now - _parse(last_run["actual_end_utc"])).total_seconds())
    period_over = now >= _parse(period["ends_at_utc"])
    streak = consecutive_failures(runs)
    scheduler_verification = read_json(SCHEDULER_VERIFICATION) or {}
    live = scheduler_verification.get("live_tests", {})

    critical: list[str] = []
    warning: list[str] = []
    if evidence["missing"] or evidence["mismatched"]:
        critical.append(
            f"raw evidence does not reproduce for {len(evidence['missing'])} window(s) missing and "
            f"{len(evidence['mismatched'])} mismatched"
        )
    if unaccounted:
        critical.append(
            f"{len(unaccounted)} declared slot(s) ended without a window and without a "
            f"MISSED_WINDOW record: {unaccounted[:6]}"
        )
    if disk["status"] == "CRITICAL":
        critical.append(f"disk is CRITICAL: {disk['free_gib']} GiB free")
    if streak >= CONSECUTIVE_FAILURES_CRITICAL:
        critical.append(f"{streak} consecutive runs recorded an error")
    if missed_fraction is not None and missed_fraction > MAX_MISSED_FRACTION:
        critical.append(
            f"{missed_fraction:.0%} of the ended slots have no window, above the declared maximum"
        )
    if not period_over and not registration["installed"]:
        critical.append("the period is open and the scheduled task is not installed")
    if not period_over and registration["installed"] and registration["enabled"] is False:
        critical.append("the scheduled task is disabled while the period is open")
    if period_over and closure is None:
        # a missing consolidation, or one that belongs to another period, is a divergence between
        # what the programme declared and what it left behind: never a silent pass
        critical.append(
            "the period has ended and no consolidation of this period is on disk"
            if closure_reading == "absent"
            else f"the period has ended and the consolidation on disk {closure_reading}"
        )

    if registration["installed"] and registration["enabled"] is not True:
        warning.append("the scheduled task exists but is not enabled")
    if heartbeat_age_s is not None and heartbeat_age_s > TICK_GRACE_SECONDS and not period_over:
        warning.append(
            f"the last tick ended {heartbeat_age_s} s ago, beyond the {TICK_GRACE_SECONDS} s grace: "
            "the schedule looks stale (this is a hint about the tick, not about the data)"
        )
    if not runs:
        warning.append("no run event has been recorded yet")
    if recorderrors := (last_run.get("errors") if last_run else None):
        warning.append(f"the last run recorded an error: {recorderrors}"[:200])
    if disk["status"] == "WARNING":
        warning.append(f"disk is WARNING: {disk['free_gib']} GiB free")
    if missed and missed_fraction is not None and missed_fraction <= MAX_MISSED_FRACTION:
        warning.append(f"{len(missed)} window(s) are recorded as MISSED_WINDOW")
    if not live:
        warning.append(
            "the scheduler has not been verified with live tests yet, so autonomous collection is "
            "not established"
        )
    if not SCHEDULER_REPORT.exists():
        warning.append("the scheduler report has not been written yet")

    if period_over and closure is not None:
        status = PERIOD_COMPLETED
        reasons = [
            f"the declared period ended at {period['ends_at_utc']} and the consolidation exists"
        ]
    elif critical:
        status = CRITICAL
        reasons = critical + warning
    elif warning:
        status = WARNING
        reasons = warning
    else:
        status = HEALTHY
        reasons = [
            "every declared slot so far is either observed or recorded as missed, the raw "
            "evidence reproduces, the task is installed and enabled, and storage is healthy"
        ]
    exit_code = {
        HEALTHY: EXIT_HEALTHY,
        WARNING: EXIT_WARNING,
        CRITICAL: EXIT_CRITICAL,
        PERIOD_COMPLETED: EXIT_PERIOD_COMPLETED,
    }[status]
    return {
        "artifact": "ST6_HEALTH_STATUS",
        "generated_at_utc": _utc(),
        "status": status,
        "exit_code": exit_code,
        "reasons": reasons,
        "heartbeat_is_not_evidence": True,
        "reading": (
            "a tick that ran and skipped the exchange observed nothing: health is about the schedule "
            "and about the evidence on disk, and no heartbeat is ever counted as a sample"
        ),
        "evidence": {
            "windows_completed": len(windows),
            "observations": len(observations),
            "declared_slots_ended": len(ended),
            "declared_slots_pending": len(pending),
            "missed_windows_recorded": len(missed),
            "unaccounted_slots": unaccounted,
            "missed_fraction_of_ended_slots": missed_fraction,
            "raw_evidence": evidence,
            "run_events": len(runs),
            "consecutive_failures": streak,
            "last_run": {
                "run_id": last_run.get("run_id"),
                "result": last_run.get("result"),
                "actual_end_utc": last_run.get("actual_end_utc"),
                "exit_code": last_run.get("exit_code"),
            }
            if last_run
            else None,
            "heartbeat_age_seconds": heartbeat_age_s,
            "tick_grace_seconds": TICK_GRACE_SECONDS,
            "scheduler": registration,
            "disk": disk,
        },
        "period": {
            "started_at_utc": period["started_at_utc"],
            "ends_at_utc": period["ends_at_utc"],
            "over": period_over,
            "consolidation_present": closure is not None,
            "consolidation_reading": closure_reading,
        },
        "next_expected_window": pending[0] if pending else None,
        "standing_state": {
            "DISCOVERY_CAMPAIGN_FAILED": True,
            "NEXT_CAMPAIGN": "NOT_AUTHORIZED",
            "TRADES_AUTHORIZED": 0,
            "LIVE_TRADING": "DISABLED",
            "PROFITABILITY_VERIFIED": False,
        },
        "orders_sent": 0,
        "credentials_used": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(HEALTH_STATUS))
    args = parser.parse_args(argv)

    try:
        document = evaluate()
    except Exception as exc:  # the checker's own failure is a state, not a crash
        document = {
            "artifact": "ST6_HEALTH_STATUS",
            "generated_at_utc": _utc(),
            "status": "CHECK_FAILED",
            "exit_code": EXIT_CHECK_FAILED,
            "reasons": [f"{type(exc).__name__}: {exc}"],
            "heartbeat_is_not_evidence": True,
        }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with HEALTH_LOG.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "generated_at_utc": document["generated_at_utc"],
                    "status": document["status"],
                    "exit_code": document["exit_code"],
                    "reasons": document["reasons"][:3],
                },
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n"
        )
    events = read_jsonl(HEALTH_LOG)
    if len(events) > HEALTH_EVENTS_KEPT:
        HEALTH_LOG.write_text(
            "".join(
                json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n"
                for event in events[-HEALTH_EVENTS_KEPT:]
            ),
            encoding="utf-8",
        )
    print(f"{document['status']} (exit {document['exit_code']})")
    for reason in document["reasons"][:5]:
        print(f"  - {reason}")
    print(f"written -> {out}")
    return int(document["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
