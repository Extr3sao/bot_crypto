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
  between what the programme says and what it recorded, and a missed window whose stated cause the
  run log does not support is a CRITICAL divergence too — the cause is re-derived here from the run
  events rather than taken on trust, so an unattended slot and an attended-but-unmeasured slot do
  not collapse into the same claim;
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

if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from st6_scheduler_evidence import (  # noqa: E402  the external record of the schedule
    EXTERNAL_COVERAGE_COMPLETE,
    SCHEDULER_EVIDENCE_UNAVAILABLE,
    slot_external_coverage,
)
from st6_scheduler_evidence import extract_samples as normalise_samples  # noqa: E402  external
from st6_scheduler_evidence import load_samples as load_witness_samples  # noqa: E402  external
from st6_scheduler_evidence import read_json as read_external_json  # noqa: E402  external

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
#: The vocabulary a missed window may use for its cause, and what the classes mean.  A slot nobody
#: attended is a failure of the host or of the task; a slot the tick visited and still did not
#: measure is a failure of the tick; an absent event in an old slot proves nothing at all; and when
#: the tick's own log and the scheduler's own reporting disagree, the record says so instead of
#: choosing a side.
MISSED_ATTENDANCE_CLASSES = (
    "ATTENDED_NOT_COLLECTED",
    "ATTENDED_REQUEST_FAILED",
    "UNATTENDED_NO_RUN_EVENT",
    "ATTENDANCE_UNKNOWN",
    "ATTENDANCE_UNKNOWN_RUN_LOG_TRUNCATED",
    "ATTENDANCE_EVIDENCE_CONFLICT",
)
ATTENDANCE_POLICY_VERSION = 2
#: The classes whose claim is an *absence*, and which therefore require the external record to cover
#: the whole slot.  Kept beside the checker's own implementation of the rule so a reader can see
#: which claims carry the heavier burden.
ABSENCE_CLASSES = ("UNATTENDED_NO_RUN_EVENT",)
WITNESS_LOG = DATA / "ST6_SCHEDULER_WITNESS.jsonl"
SCHEDULER_EVIDENCE = DATA / "ST6_SCHEDULER_EVIDENCE.json"

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


def _request_count(run: dict[str, Any]) -> int:
    """A run's market-request count, read defensively: a corrupt field must not stop the audit."""
    try:
        return int(run.get("market_requests") or 0)
    except (TypeError, ValueError):
        return 0


def attendance_class_from_runs(
    runs: list[dict[str, Any]],
    slot_key: str,
    starts_at_utc: str,
    external: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Re-derive, from the run log and the external record, what happened inside one slot.

    This is deliberately a second implementation of the builder's rule: the health check must be
    able to disagree with the record, otherwise it is decoration.  A run that explicitly declares
    itself ``MANUAL`` is not the schedule and is not counted as attendance; an event with no
    declaration at all is kept, so the check never manufactures a gap in the evidence.

    The rule this implementation enforces, in its own words: attendance can be read from the tick's
    log, absence cannot.  ``UNATTENDED_NO_RUN_EVENT`` is reachable here only when the external
    record covers every instant of the slot and the scheduler's own last-run field never named a run
    inside it; a slot where the two records disagree is a conflict, not a verdict.
    """
    coverage = external if isinstance(external, dict) else {
        "status": SCHEDULER_EVIDENCE_UNAVAILABLE,
        "scheduler_engine_launch_count": 0,
    }
    external_status = str(coverage.get("status") or SCHEDULER_EVIDENCE_UNAVAILABLE)
    launches = int(coverage.get("scheduler_engine_launch_count") or 0)
    events = [run for run in runs if isinstance(run, dict)]
    in_slot = [run for run in events if run.get("slot_key") == slot_key]
    attended = [run for run in in_slot if str(run.get("invocation", "")).upper() != "MANUAL"]
    starts = sorted(str(run.get("actual_start_utc")) for run in events if run.get("actual_start_utc"))
    # only a log that reaches back to the slot's own start can speak for its whole length: pruning
    # removes the oldest events, so a slot whose head was pruned cannot be called unattended
    covers_whole_slot = bool(starts) and starts[0] <= starts_at_utc
    requests = sum(_request_count(run) for run in attended)
    failing = [run for run in attended if run.get("errors")]
    results: dict[str, int] = {}
    for run in attended:
        token = str(run.get("result") or "UNRECORDED")
        results[token] = results.get(token, 0) + 1
    if attended and external_status == EXTERNAL_COVERAGE_COMPLETE and launches == 0:
        classification = "ATTENDANCE_EVIDENCE_CONFLICT"
    elif attended:
        classification = (
            "ATTENDED_REQUEST_FAILED" if requests and failing else "ATTENDED_NOT_COLLECTED"
        )
    elif external_status == EXTERNAL_COVERAGE_COMPLETE and launches > 0:
        classification = "ATTENDANCE_EVIDENCE_CONFLICT"
    elif external_status == EXTERNAL_COVERAGE_COMPLETE:
        classification = "UNATTENDED_NO_RUN_EVENT"
    elif not covers_whole_slot:
        classification = "ATTENDANCE_UNKNOWN_RUN_LOG_TRUNCATED"
    else:
        classification = "ATTENDANCE_UNKNOWN"
    # a claim of absence that the external record cannot carry is a divergence, and the checker
    # names it as one rather than quietly lowering the class
    absence_unsupported = (
        classification in ABSENCE_CLASSES
        and external_status != EXTERNAL_COVERAGE_COMPLETE
    )
    return {
        "classification": classification,
        "scheduled_runs_in_slot": len(attended),
        "manual_runs_in_slot": len(in_slot) - len(attended),
        "market_requests_in_slot": requests,
        "results_in_slot": results,
        "log_covers_whole_slot": covers_whole_slot,
        "run_log_events_retained": len(starts),
        "run_log_first_utc": starts[0] if starts else None,
        "external_evidence_status": external_status,
        "external_samples_in_slot": coverage.get("external_samples_in_slot"),
        "scheduler_engine_launch_count": launches,
        "absence_claim_supported_by_external_coverage": not absence_unsupported,
        "policy_version": ATTENDANCE_POLICY_VERSION,
    }


def audit_missed_attendance(
    period: dict[str, Any],
    missed: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    samples: list[dict[str, Any]] | None = None,
    external_evidence: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Check every missed window's stated cause against the run log, and against the declared grid.

    The claim is audited on four counts: it must name a class from the declared vocabulary, its own
    counters must agree with the events, the slot's bounds must be the declared ones, and the class
    itself must match what is re-derived here.  A claim the evidence does not support is a
    divergence, never a pass with a note.
    """
    planned = {
        entry["key"]: entry
        for entry in declared_slots_upto(period, _parse(period["ends_at_utc"]))
    }
    moment = now or datetime.now(UTC).replace(microsecond=0)
    # the samples are normalised here whatever their source: the arithmetic below compares datetimes,
    # and a raw witness row carries strings
    witness = (
        normalise_samples(samples) if samples is not None else load_witness_samples(WITNESS_LOG)
    )
    evidence = (
        external_evidence if external_evidence is not None else read_external_json(SCHEDULER_EVIDENCE)
    )
    by_classification: dict[str, int] = {}
    unattended: list[str] = []
    unknown: list[str] = []
    conflicts: list[str] = []
    unsupported: list[str] = []
    for row in missed:
        key = str(row.get("slot_key"))
        recorded = row.get("attendance")
        if not isinstance(recorded, dict):
            unsupported.append(f"{key}: no attendance evidence is recorded at all")
            continue
        classification = str(recorded.get("classification"))
        by_classification[classification] = by_classification.get(classification, 0) + 1
        if classification not in MISSED_ATTENDANCE_CLASSES:
            unsupported.append(f"{key}: the recorded cause {classification!r} is not declared")
            continue
        entry = planned.get(key)
        if entry is None:
            unsupported.append(f"{key}: the slot is not in the declared plan")
            continue
        expected_start = (_parse(entry["ends_at_utc"]) - timedelta(hours=SLOT_HOURS)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        if (row.get("ends_at_utc"), row.get("starts_at_utc")) != (
            entry["ends_at_utc"],
            expected_start,
        ):
            unsupported.append(
                f"{key}: the recorded bounds ({row.get('starts_at_utc')} -> "
                f"{row.get('ends_at_utc')}) are not the declared ones ({expected_start} -> "
                f"{entry['ends_at_utc']})"
            )
        coverage = slot_external_coverage(
            _parse(expected_start), _parse(entry["ends_at_utc"]), witness, evidence, moment
        )
        derived = attendance_class_from_runs(runs, key, expected_start, coverage)
        if classification != derived["classification"]:
            unsupported.append(
                f"{key}: the record claims {classification} while the run log says "
                f"{derived['classification']}"
            )
        for field in (
            "scheduled_runs_in_slot",
            "manual_runs_in_slot",
            "market_requests_in_slot",
            "log_covers_whole_slot",
        ):
            if recorded.get(field) != derived[field]:
                unsupported.append(
                    f"{key}: the record claims {field}={recorded.get(field)!r} while the run log "
                    f"says {derived[field]!r}"
                )
        # the class the slot would take from the external record alone, which is what a reader can
        # check without believing the tick's own log
        if derived["absence_claim_supported_by_external_coverage"] is False:
            unsupported.append(
                f"{key}: the record claims {classification} without external coverage of the slot "
                f"(external status {derived['external_evidence_status']})"
            )
        # the lists describe what the evidence supports, not what the record asserts: a claim this
        # checker does not accept is reported in `unsupported` and nowhere else, so a wrong claim can
        # neither raise nor lower the status of the campaign by being written down
        supported = str(derived["classification"])
        if supported == "UNATTENDED_NO_RUN_EVENT":
            unattended.append(key)
        if supported in ("ATTENDANCE_UNKNOWN", "ATTENDANCE_UNKNOWN_RUN_LOG_TRUNCATED"):
            unknown.append(key)
        if supported == "ATTENDANCE_EVIDENCE_CONFLICT":
            conflicts.append(key)
    return {
        "claims": len(missed),
        "by_classification": by_classification,
        "unattended_slots": unattended,
        "unattended_reading": (
            "a slot nobody attended is a failure of the host or of the task — and it is only claimed "
            "when the external record covers every instant of the slot and the scheduler's own "
            "reporting named no run inside it"
        ),
        "unknown_slots": unknown,
        "unknown_reading": (
            "a slot is recorded as unknown when the tick's own log holds no event for it and the "
            "external record cannot cover it: an absent line in a program's own diary is not proof "
            "that nothing ran"
        ),
        "conflict_slots": conflicts,
        "conflict_reading": (
            "the tick's log and the scheduler's own reporting disagreed about the slot; the record "
            "says so instead of choosing a side"
        ),
        "unsupported": unsupported,
        "vocabulary": list(MISSED_ATTENDANCE_CLASSES),
        "policy_version": ATTENDANCE_POLICY_VERSION,
        "external_status": (evidence or {}).get("per_run_external_evidence", {}).get("status")
        or SCHEDULER_EVIDENCE_UNAVAILABLE,
        "witness_samples_considered": len(witness),
        "reading": (
            "the cause of every missed window was re-derived from the run events, from the declared "
            "grid and from the external record of the scheduler, never taken from the record on trust"
        ),
    }


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


def is_manual(run: dict[str, Any]) -> bool:
    """An invocation that did not declare itself the schedule.

    The run log is append-only and shared: the fixture that provokes a deliberate
    ``REFUSED_INVALID_ARGUMENTS`` writes a real event, and every event written before the field
    existed carries no provenance at all.  A manual event is therefore excluded from the failure
    streak and from the heartbeat, while an unrecorded one is *kept*: dropping it could hide a real
    failure.  This reads a declaration, so a fixture that emulates the task's command line is
    counted as the schedule — the limit is declared rather than papered over.
    """
    return str(run.get("invocation", "")).upper() == "MANUAL"


def error_warnings(runs: list[dict[str, Any]]) -> list[str]:
    """The schedule's own last failure, if any: a manual or verification run is not the programme.

    The run log is shared with the fixtures, so a deliberate refusal can be the newest event while
    the campaign's own tick is perfectly healthy.  Only the schedule's runs raise the status; what a
    manual invocation did is reported as information beside it, never as a verdict on the campaign.
    """
    scheduled = [run for run in runs if not is_manual(run)]
    if scheduled and scheduled[-1].get("errors"):
        return [f"the last scheduled run recorded an error: {str(scheduled[-1]['errors'])[:200]}"]
    return []


def provenance_information(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """What the manual invocations did — information about the harness, not about the campaign."""
    manual = [run for run in runs if is_manual(run)]
    failing = [run for run in manual if run.get("errors")]
    return {
        "manual_invocations": len(manual),
        "manual_invocations_with_errors": len(failing),
        "newest_event_is_manual": bool(runs) and is_manual(runs[-1]),
        "last_manual_error": str(failing[-1]["errors"])[:200] if failing else None,
        "reading": (
            "a manual or verification invocation is not the schedule: it neither raises the status "
            "of the observation programme nor refreshes its heartbeat"
        ),
    }


def run_provenance(runs: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"SCHEDULED": 0, "MANUAL": 0, "UNRECORDED": 0}
    for run in runs:
        label = str(run.get("invocation", "")).upper()
        counts[label if label in ("SCHEDULED", "MANUAL") else "UNRECORDED"] += 1
    return counts


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
    witness = load_witness_samples(WITNESS_LOG)
    scheduler_evidence = read_external_json(SCHEDULER_EVIDENCE)
    attendance_audit = audit_missed_attendance(
        period, missed, runs, witness, scheduler_evidence, now
    )
    external_block = (scheduler_evidence or {}).get("per_run_external_evidence") or {}
    external_status = str(external_block.get("status") or SCHEDULER_EVIDENCE_UNAVAILABLE)
    closure, closure_reading = closure_of_declared_period(period)
    registration = scheduler_registration()
    disk = disk_report(REPO)
    evidence = raw_evidence_state(windows)
    slots = declared_slots_upto(period, now)
    all_slots = declared_slots_upto(period, _parse(period["ends_at_utc"]))
    observed = {f"{row['day']}#{row['slot_index']}" for row in windows}
    recorded_missed = {row["slot_key"] for row in missed}
    ended = [entry for entry in slots if _parse(entry["ends_at_utc"]) <= now]
    witness_covered_slots = [entry["key"] for entry in ended]
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
    # the campaign's own ticks: a manual invocation is not the schedule, so it neither extends
    # the failure streak nor refreshes the heartbeat
    scheduled_runs = [run for run in runs if not is_manual(run)]
    provenance = run_provenance(runs)
    last_run = runs[-1] if runs else None
    last_scheduled_run = scheduled_runs[-1] if scheduled_runs else None
    heartbeat_age_s = None
    heartbeat_basis = "NO_RUN_RECORDED"
    if last_scheduled_run and last_scheduled_run.get("actual_end_utc"):
        heartbeat_age_s = int((now - _parse(last_scheduled_run["actual_end_utc"])).total_seconds())
        heartbeat_basis = "LAST_NON_MANUAL_RUN"
    period_over = now >= _parse(period["ends_at_utc"])
    streak = consecutive_failures(scheduled_runs)
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
    if attendance_audit["unsupported"]:
        critical.append(
            f"{len(attendance_audit['unsupported'])} missed window(s) state a cause the run log "
            f"does not support: {attendance_audit['unsupported'][:4]}"
        )
    if disk["status"] == "CRITICAL":
        critical.append(f"disk is CRITICAL: {disk['free_gib']} GiB free")
    if streak >= CONSECUTIVE_FAILURES_CRITICAL:
        critical.append(f"{streak} consecutive runs recorded an error")
    if missed_fraction is not None and missed_fraction > MAX_MISSED_FRACTION:
        critical.append(
            f"{missed_fraction:.0%} of the ended slots have no window, above the declared maximum"
        )
    unobserved_ended = [entry["key"] for entry in ended if entry["key"] not in observed]
    if external_status == SCHEDULER_EVIDENCE_UNAVAILABLE and unobserved_ended and not period_over:
        # the limitation is recorded always, and it raises the status exactly when it bites: a slot
        # ended without a window and no external record can carry the reason
        warning.append(
            f"{len(unobserved_ended)} ended slot(s) have no window and per-run external evidence is "
            "SCHEDULER_EVIDENCE_UNAVAILABLE on this host: the Task Scheduler operational channel is "
            "disabled and no witness covered those slots, so their attendance is UNKNOWN rather "
            "than proven unattended"
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
    if provenance["MANUAL"] and not provenance["SCHEDULED"]:
        warning.append(
            f"every one of the {provenance['MANUAL']} run event(s) on record is a manual or "
            "verification invocation: the schedule itself has not ticked yet"
        )
    warning.extend(error_warnings(runs))
    if disk["status"] == "WARNING":
        warning.append(f"disk is WARNING: {disk['free_gib']} GiB free")
    if missed and missed_fraction is not None and missed_fraction <= MAX_MISSED_FRACTION:
        warning.append(
            f"{len(missed)} window(s) are recorded as MISSED_WINDOW: "
            + ", ".join(
                f"{token} {count}"
                for token, count in sorted(attendance_audit["by_classification"].items())
            )
        )
    if attendance_audit["unattended_slots"]:
        warning.append(
            f"{len(attendance_audit['unattended_slots'])} slot(s) went unattended with the external "
            "record covering them and naming no run inside "
            f"{attendance_audit['unattended_slots'][:6]}"
        )
    if attendance_audit["conflict_slots"]:
        critical.append(
            f"{len(attendance_audit['conflict_slots'])} slot(s) are carried as evidence conflicts: "
            "the tick's own log and the scheduler's own reporting disagree about them "
            f"{attendance_audit['conflict_slots'][:6]}"
        )
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
            "missed_window_attendance": attendance_audit,
            "external_evidence": {
                "status": external_status,
                "reason": external_block.get("reason"),
                "witness_samples": len(witness),
                "witness_covered_from_utc": witness[0]["sampled_at_utc"] if witness else None,
                "witness_covered_to_utc": witness[-1]["sampled_at_utc"] if witness else None,
                "slots_ended_that_the_witness_could_cover": witness_covered_slots,
                "reading": (
                    "a claim of absence needs the external record to cover the whole slot; where it "
                    "does not, the class is UNKNOWN and no cause is asserted"
                ),
            },
            "unaccounted_slots": unaccounted,
            "missed_fraction_of_ended_slots": missed_fraction,
            "raw_evidence": evidence,
            "run_events": len(runs),
            "run_events_by_provenance": provenance,
            "invocation_provenance": provenance_information(runs),
            "consecutive_failures": streak,
            "consecutive_failures_over": "non-manual run events only",
            "last_run": {
                "run_id": last_run.get("run_id"),
                "result": last_run.get("result"),
                "actual_end_utc": last_run.get("actual_end_utc"),
                "exit_code": last_run.get("exit_code"),
            }
            if last_run
            else None,
            "last_scheduled_run": {
                "run_id": last_scheduled_run.get("run_id"),
                "result": last_scheduled_run.get("result"),
                "actual_end_utc": last_scheduled_run.get("actual_end_utc"),
                "exit_code": last_scheduled_run.get("exit_code"),
                "errors": last_scheduled_run.get("errors"),
            }
            if last_scheduled_run
            else None,
            "heartbeat_age_seconds": heartbeat_age_s,
            "heartbeat_basis": heartbeat_basis,
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
