"""ST-6 — the lossless slot ledger, and the provenance of every declared slot.

Eighty-four slots are declared for this period.  The run log that describes the ticks is bounded and
front-truncated, and the witness log that describes the scheduler is bounded too, so neither of them
can be the record of what happened to a slot: the ledger is.  It is rebuilt from the sources on
every run and written atomically, so it is never half-written; it is keyed by the declared slot grid
so a rebuild is idempotent; and it keeps one entry per declared slot with the evidence that slot
rests on, which is exactly what the end-of-period consolidation needs and what the truncated logs
would have lost.

Each entry carries what a reader needs to check it without believing any single program:

* the slot's identity and declared bounds;
* the expected trigger, the observed scheduler instants, the instance evidence available on this
  host and the status of the external record;
* the internal run identity, the process start, the result and the exit status;
* the window that was collected, its raw evidence hash, and whether that hash reproduces;
* the failure reason and the attendance classification, with the policy version that produced it and
  the classification it corrected, when a correction was made;
* the references the entry was derived from, and the verifier's status for the slot.

It never invents a slot, never drops one, and never claims an absence the external record cannot
carry.  After the declared period closes, the same document is archived beside it with the period's
identity, so the record survives the pruning of the logs it was derived from.

Run:  python scripts/st6_slot_ledger.py                 (build the ledger and the provenance)
      python scripts/st6_slot_ledger.py --archive       (also freeze the closing copy)
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from st6_scheduler_evidence import (  # noqa: E402  the external record of the schedule
    EXTERNAL_COVERAGE_COMPLETE,
    EXTERNAL_COVERAGE_NOT_YET_STARTED,
    EXTERNAL_COVERAGE_PARTIAL,
    SCHEDULER_EVIDENCE_UNAVAILABLE,
    corroborate_run,
    external_launch_evidence,
    load_samples,
    read_json,
    read_jsonl,
    slot_external_coverage,
    witness_inventory,
)

DATA = REPO / "data" / "st6"
PERIOD_PATH = DATA / "ST6_PERIOD.json"
WINDOWS = DATA / "ST6_WINDOWS.jsonl"
OBSERVATIONS = DATA / "ST6_OBSERVATIONS.jsonl"
RUN_LOG = DATA / "ST6_RUNS.jsonl"
MISSED_LOG = DATA / "ST6_MISSED_WINDOWS.jsonl"
WITNESS_LOG = DATA / "ST6_SCHEDULER_WITNESS.jsonl"
SCHEDULER_EVIDENCE = DATA / "ST6_SCHEDULER_EVIDENCE.json"
CLOSURE = DATA / "ST6_PERIOD_CLOSURE.json"
LEDGER = DATA / "ST6_SLOT_LEDGER.json"
LEDGER_ARCHIVE = DATA / "ST6_SLOT_LEDGER_ARCHIVE.json"
PROVENANCE_JSON = DATA / "ST6_SCHEDULER_PROVENANCE.json"
PROVENANCE_MD = DATA / "ST6_SCHEDULER_PROVENANCE.md"
INDUCED_RUNS = DATA / "ST6_VERIFIER_INDUCED_RUNS.jsonl"
TASK_NAME = "TradingAgentic-ST6-Forward"
SLOT_HOURS = 4
LEDGER_VERSION = "ST6_SLOT_LEDGER_V1"
#: The slot states.  There is no ``MISSED`` here: a slot is either measured, or lost with a stated
#: class, or still ahead.  The classification carries the *why* and never pretends to be one.
STATE_COLLECTED = "COLLECTED"
STATE_LOST = "LOST_NO_WINDOW"
STATE_PENDING = "PENDING"
STATE_UNACCOUNTED = "UNACCOUNTED"
#: Where a run event's origin stands.  The tick writes its own log, so its declaration of being the
#: schedule is a claim, not proof; an engine launch the scheduler's own record named at that instant
#: is corroboration; and a run this repository's own verifier asked the scheduler for is neither.
ORIGIN_CORROBORATED = "CORROBORATED_ENGINE_LAUNCH"
ORIGIN_SELF_DECLARED = "SELF_DECLARED_UNVERIFIED"
ORIGIN_MANUAL = "MANUAL"
ORIGIN_INDUCED = "INDUCED_BY_THE_VERIFIER"
ORIGIN_UNATTRIBUTED = "UNATTRIBUTED"
#: The declared vocabulary, in the order a reader should read it: every origin is reported, and none
#: is dropped from the report because it happened to be empty.
ORIGINS = (
    ORIGIN_CORROBORATED,
    ORIGIN_SELF_DECLARED,
    ORIGIN_MANUAL,
    ORIGIN_INDUCED,
    ORIGIN_UNATTRIBUTED,
)


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> datetime:
    text = str(stamp)
    if "." in text:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    """Replace through a temporary file in the same directory: a reader never sees half a ledger."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def declared_slots(period: dict[str, Any]) -> list[dict[str, Any]]:
    """The declared grid: days x slots per day from the slot that contains the period's start.

    The partial slot the period's end falls into is not a planned window, so it is not a slot of the
    ledger at all — nothing may be expected, lost or penalised inside it.
    """
    start = _parse(period["started_at_utc"])
    planned = int(period["period_days"]) * int(period["slots_per_day"])
    cursor = start.replace(minute=0, second=0, microsecond=0)
    slots: list[dict[str, Any]] = []
    while len(slots) < planned:
        index = cursor.hour // SLOT_HOURS
        slots.append(
            {
                "slot_id": f"{cursor.strftime('%Y-%m-%d')}#{index}",
                "day": cursor.strftime("%Y-%m-%d"),
                "slot_index": index,
                "slot_utc": f"{index * SLOT_HOURS:02d}:00-{(index + 1) * SLOT_HOURS:02d}:00 UTC",
                "starts_at": cursor,
                "starts_at_utc": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "ends_at": cursor + timedelta(hours=SLOT_HOURS),
                "ends_at_utc": (cursor + timedelta(hours=SLOT_HOURS)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        )
        cursor += timedelta(hours=SLOT_HOURS)
    return slots


def trigger_grid(period: dict[str, Any], evidence: dict[str, Any] | None) -> dict[str, Any]:
    """The declared cadence, read from the scheduler's own registration rather than assumed."""
    triggers = ((evidence or {}).get("scheduler_reporting_now") or {}).get("triggers") or []
    first = triggers[0] if isinstance(triggers, list) and triggers else {}
    actions = ((evidence or {}).get("scheduler_reporting_now") or {}).get("actions") or []
    action = actions[0] if isinstance(actions, list) and actions else {}
    interval = str(first.get("interval") or "") if isinstance(first, dict) else ""
    minutes = 15
    if interval.startswith("PT") and interval.endswith("M"):
        try:
            minutes = int(interval[2:-1])
        except ValueError:
            minutes = 15
    return {
        "task_name": TASK_NAME,
        "repetition_interval": interval or None,
        "interval_minutes": minutes,
        "start_boundary_local": first.get("start") if isinstance(first, dict) else None,
        "duration": first.get("duration") if isinstance(first, dict) else None,
        "action_command": action.get("execute") if isinstance(action, dict) else None,
        "action_arguments": action.get("arguments") if isinstance(action, dict) else None,
        "reading": (
            "the expected trigger of a slot is the declared cadence across the slot: its number is "
            "arithmetic on the registration, and no trigger is counted as having fired unless the "
            "scheduler's own record named the instant"
        ),
    }


def expected_triggers(slot: dict[str, Any], grid: dict[str, Any]) -> int:
    minutes = int(grid.get("interval_minutes") or 15)
    return max(1, int(SLOT_HOURS * 60 / minutes))


def induced_runs() -> dict[str, dict[str, Any]]:
    """The runs this repository's own verifier asked the scheduler for, by run id and by instant.

    A verifier that exercises the task leaves real run events behind.  They are legitimate tests and
    they are *not* the schedule's own ticks, so they are recorded as they happen and subtracted from
    the attendance arithmetic instead of being counted as the campaign working.
    """
    rows = read_jsonl(INDUCED_RUNS)
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        run_id = row.get("run_id")
        if run_id:
            by_id[str(run_id)] = row
    return by_id


def raw_evidence_ok(window: dict[str, Any]) -> dict[str, Any]:
    """Re-hash a window's raw bytes: a ledger entry that quotes a hash must have checked it."""
    path = REPO / str(window.get("raw", {}).get("path") or "")
    if not path.exists():
        return {"path": str(window.get("raw", {}).get("path")), "present": False, "reproduces": False}
    with gzip.open(path, "rb") as handle:
        payload = handle.read()
    digest = _sha256_bytes(payload)
    recorded = window.get("raw", {}).get("uncompressed_sha256")
    return {
        "path": str(window.get("raw", {}).get("path")),
        "present": True,
        "uncompressed_sha256": digest,
        "recorded_uncompressed_sha256": recorded,
        "reproduces": digest == recorded,
    }


def _coverage_rank(status: str | None) -> int:
    """How strong a coverage statement is, so that a rebuild never weakens a recorded one."""
    return {
        EXTERNAL_COVERAGE_COMPLETE: 3,
        EXTERNAL_COVERAGE_PARTIAL: 2,
        SCHEDULER_EVIDENCE_UNAVAILABLE: 1,
        EXTERNAL_COVERAGE_NOT_YET_STARTED: 0,
    }.get(str(status), 0)


def carry_forward(
    entry: dict[str, Any], previous: dict[str, Any] | None
) -> tuple[dict[str, Any], list[str]]:
    """Keep what an earlier read could see and this one cannot.

    The ledger is rebuilt from logs that are bounded: the run log keeps a few hundred events and the
    witness log has a declared bound, so a later rebuild can hold *less* than an earlier one.  The
    ledger is the durable record, so it must not lose ground: the runs already recorded are kept
    beside the ones still readable, and a coverage statement is never weakened by a rebuild.  Every
    field that came from an earlier read says so, with the instant it was read.
    """
    if not isinstance(previous, dict):
        return entry, []
    carried: list[str] = []
    known = {str(row.get("internal_run_id")): row for row in previous.get("runs") or []}
    for row in entry.get("runs") or []:
        known[str(row.get("internal_run_id"))] = row
    merged_runs = sorted(
        known.values(), key=lambda row: str(row.get("process_start_utc") or "")
    )
    if len(merged_runs) != len(entry.get("runs") or []):
        carried.append("runs")
        entry["runs_carried_forward_from_utc"] = previous.get("read_at_utc")
    entry["runs"] = merged_runs
    previous_status = (previous.get("external_evidence") or {}).get("status")
    if _coverage_rank(previous_status) > _coverage_rank(
        (entry.get("external_evidence") or {}).get("status")
    ):
        entry["external_evidence"] = previous.get("external_evidence")
        entry["external_evidence_status"] = previous_status
        entry["external_evidence_carried_forward_from_utc"] = previous.get("read_at_utc")
        carried.append("external_evidence")
    for field in ("attendance_evidence", "attendance_classification", "failure_reason"):
        if entry.get(field) is None and previous.get(field) is not None:
            entry[field] = previous[field]
            entry[f"{field}_carried_forward_from_utc"] = previous.get("read_at_utc")
            carried.append(field)
    if carried:
        entry["first_recorded_at_utc"] = previous.get("first_recorded_at_utc") or previous.get(
            "read_at_utc"
        )
    return entry, carried


def build_slot_entry(
    slot: dict[str, Any],
    period: dict[str, Any],
    windows_by_slot: dict[str, dict[str, Any]],
    runs: list[dict[str, Any]],
    missed_by_slot: dict[str, dict[str, Any]],
    samples: list[dict[str, Any]],
    evidence: dict[str, Any] | None,
    grid: dict[str, Any],
    induced: dict[str, dict[str, Any]],
    now: datetime,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    coverage = slot_external_coverage(
        slot["starts_at"], slot["ends_at"], samples, evidence, now
    )
    launches = external_launch_evidence(slot["starts_at"], slot["ends_at"], samples)
    window = windows_by_slot.get(slot["slot_id"])
    missed = missed_by_slot.get(slot["slot_id"])
    in_slot = [run for run in runs if run.get("slot_key") == slot["slot_id"]]
    ended = slot["ends_at"] <= now

    run_rows: list[dict[str, Any]] = []
    for run in in_slot:
        run_id = str(run.get("run_id") or "")
        declaration = str(run.get("invocation") or "").upper()
        if run_id and run_id in induced:
            origin = ORIGIN_INDUCED
            origin_evidence: dict[str, Any] = {
                "detail": induced[run_id].get("reason"),
                "recorded_by": str(INDUCED_RUNS.relative_to(REPO)).replace("\\", "/"),
            }
        elif declaration == "MANUAL":
            origin = ORIGIN_MANUAL
            origin_evidence = {"detail": "the event declares itself a manual invocation"}
        else:
            corroboration = corroborate_run(
                run, samples, boundary_local=grid.get("start_boundary_local")
            )
            if corroboration["status"].startswith("CORROBORATED"):
                origin = ORIGIN_CORROBORATED
            elif declaration == "SCHEDULED":
                origin = ORIGIN_SELF_DECLARED
            else:
                origin = ORIGIN_UNATTRIBUTED
            origin_evidence = corroboration
        run_rows.append(
            {
                "internal_run_id": run_id or None,
                "process_start_utc": run.get("actual_start_utc"),
                "process_end_utc": run.get("actual_end_utc"),
                "result": run.get("result"),
                "exit_code": run.get("exit_code"),
                "market_requests": run.get("market_requests"),
                "raw_evidence_hash": run.get("raw_evidence_hash"),
                "errors": run.get("errors"),
                "declared_invocation": declaration or None,
                "origin": origin,
                "origin_evidence": origin_evidence,
            }
        )
    run_rows.sort(key=lambda row: str(row["process_start_utc"] or ""))

    if window is not None:
        state = STATE_COLLECTED
    elif missed is not None:
        state = STATE_LOST
    elif ended:
        state = STATE_UNACCOUNTED
    else:
        state = STATE_PENDING

    attendance = (missed or {}).get("attendance") or {}
    recorded_class = attendance.get("classification")
    derived_class = None
    correction: dict[str, Any] | None = None
    if missed is not None:
        from st6_forward_regime import slot_attendance  # the builder's rule, used as its own oracle

        derived = slot_attendance(runs, {**slot, "key": slot["slot_id"]}, coverage)
        derived_class = derived["classification"]
        if recorded_class != derived_class:
            correction = {
                "corrected_at_utc": _utc(),
                "previous_classification": recorded_class,
                "re_derived_classification": derived_class,
                "cause": (
                    "the classification recorded at accounting time does not match the one the "
                    "declared policy re-derives from the same evidence; the previous value is kept "
                    "here rather than overwritten in the append-only missed log"
                ),
                "policy_version_at_recording": (missed or {}).get("attendance_policy_version"),
                "policy_version_now": derived.get("policy_version"),
            }

    entry: dict[str, Any] = {
        "slot_id": slot["slot_id"],
        "day": slot["day"],
        "slot_index": slot["slot_index"],
        "slot_utc": slot["slot_utc"],
        "slot_start_utc": slot["starts_at_utc"],
        "slot_end_utc": slot["ends_at_utc"],
        "state": state,
        "expected_trigger": {
            "cadence": grid.get("repetition_interval"),
            "expected_triggers_in_slot": expected_triggers(slot, grid),
            "declared_action": grid.get("action_arguments"),
            "trigger_type_observable": False,
            "why_not_observable": (
                "the Task Scheduler operational channel is disabled on this host, so no event names "
                "the trigger that fired; a launch is known to be the engine's and its trigger type "
                "stays unknown"
            ),
        },
        "scheduler_instance_id": None,
        "scheduler_event_ids": [],
        "external_evidence_status": coverage["status"],
        "external_evidence": coverage,
        "scheduler_instants_reported_in_slot": launches["instants"],
        "internal_run_id": run_rows[0]["internal_run_id"] if run_rows else None,
        "process_start_utc": run_rows[0]["process_start_utc"] if run_rows else None,
        "result": (
            "COLLECTED"
            if window is not None
            else (run_rows[-1]["result"] if run_rows else None)
        ),
        "exit_code": run_rows[-1]["exit_code"] if run_rows else None,
        "collection_window_id": (window or {}).get("window_id"),
        "raw_evidence_hash": ((window or {}).get("raw") or {}).get("uncompressed_sha256"),
        "failure_reason": (missed or {}).get("reason"),
        "attendance_classification": recorded_class,
        "attendance_classification_re_derived": derived_class,
        "attendance_classification_reading": (
            f"not a loss: the slot produced its own window {window['window_id']} and its raw "
            "evidence, so the loss vocabulary has no class for it"
            if window is not None
            else (
                f"the slot was lost: {recorded_class}"
                if recorded_class
                else (
                    "the slot has not ended: nothing can be said about its attendance yet"
                    if not ended
                    else "the slot ended, produced no window and holds no missed record: "
                    "UNACCOUNTED, and no class is claimed for it"
                )
            )
        ),
        "attendance_evidence": attendance or None,
        "attendance_correction": correction,
        "evidence_refs": {
            "window_index": str(WINDOWS.relative_to(REPO)).replace("\\", "/") if window else None,
            "run_log": str(RUN_LOG.relative_to(REPO)).replace("\\", "/") if run_rows else None,
            "missed_log": str(MISSED_LOG.relative_to(REPO)).replace("\\", "/") if missed else None,
            "witness_log": str(WITNESS_LOG.relative_to(REPO)).replace("\\", "/")
            if coverage["external_samples_in_slot"]
            else None,
            "raw": ((window or {}).get("raw") or {}).get("path"),
        },
        "runs": run_rows,
        "concurrent_runs_in_slot": len(
            [
                row
                for row in run_rows
                if row["process_end_utc"]
                and row["process_start_utc"]
                and any(
                    other["process_start_utc"]
                    and other["process_end_utc"]
                    and other is not row
                    and row["process_start_utc"] < other["process_end_utc"]
                    and other["process_start_utc"] < row["process_end_utc"]
                    for other in run_rows
                )
            ]
        ),
        "verifier_status": None,
        "read_at_utc": _utc(),
    }
    if window is not None:
        entry["raw_evidence"] = raw_evidence_ok(window)
        verifier = (window.get("freshness") or {}).get("observation_path_latency_ok")
        entry["verifier_status"] = (
            "WINDOW_BYTES_REPRODUCE" if entry["raw_evidence"]["reproduces"] else "HASH_MISMATCH"
        )
        entry["freshness_ok"] = verifier
    entry, carried = carry_forward(entry, previous)
    entry["carried_forward_fields"] = carried
    entry["first_recorded_at_utc"] = entry.get("first_recorded_at_utc") or entry["read_at_utc"]
    return entry


def reconcile_with_ledger(ledger: dict[str, Any] | None) -> dict[str, Any]:
    """Read the ledger as a record, not as a claim: reject one that is corrupt or duplicated."""
    if ledger is None:
        return {"readable": False, "reason": "the ledger does not exist yet", "entries": 0}
    if not isinstance(ledger.get("slots"), list):
        return {"readable": False, "reason": "the ledger carries no slot list", "entries": 0}
    rows = ledger["slots"]
    ids = [str(row.get("slot_id")) for row in rows if isinstance(row, dict)]
    duplicates = sorted({slot for slot in ids if ids.count(slot) > 1})
    malformed = [index for index, row in enumerate(rows) if not isinstance(row, dict)]
    return {
        "readable": True,
        "entries": len(rows),
        "duplicate_slot_ids": duplicates,
        "malformed_entries": malformed,
        "previous_generated_at_utc": ledger.get("generated_at_utc"),
        "previous_ledger_version": ledger.get("ledger_version"),
    }


def build_ledger(now: datetime | None = None) -> dict[str, Any]:
    moment = now or datetime.now(UTC).replace(microsecond=0)
    period = read_json(PERIOD_PATH)
    if period is None:
        raise SystemExit("no period is declared; there is nothing to account for")
    evidence = read_json(SCHEDULER_EVIDENCE)
    samples = load_samples(WITNESS_LOG)
    windows = read_jsonl(WINDOWS)
    runs = read_jsonl(RUN_LOG)
    missed = read_jsonl(MISSED_LOG)
    induced = induced_runs()
    grid = trigger_grid(period, evidence)
    windows_by_slot = {f"{row['day']}#{row['slot_index']}": row for row in windows}
    missed_by_slot = {row["slot_key"]: row for row in missed}
    previous_ledger = read_json(LEDGER)
    previous = reconcile_with_ledger(previous_ledger)
    previous_by_slot = {
        str(row.get("slot_id")): row
        for row in (previous_ledger or {}).get("slots") or []
        if isinstance(row, dict)
    }

    slots = declared_slots(period)
    entries = [
        build_slot_entry(
            slot,
            period,
            windows_by_slot,
            runs,
            missed_by_slot,
            samples,
            evidence,
            grid,
            induced,
            moment,
            previous_by_slot.get(slot["slot_id"]),
        )
        for slot in slots
    ]
    states: dict[str, int] = {}
    for entry in entries:
        states[entry["state"]] = states.get(entry["state"], 0) + 1
    origins: dict[str, int] = {}
    for entry in entries:
        for row in entry["runs"]:
            origins[row["origin"]] = origins.get(row["origin"], 0) + 1
    classifications: dict[str, int] = {}
    for entry in entries:
        if entry["attendance_classification"]:
            token = str(entry["attendance_classification"])
            classifications[token] = classifications.get(token, 0) + 1
    document: dict[str, Any] = {
        "artifact": "ST6_SLOT_LEDGER",
        "ledger_version": LEDGER_VERSION,
        "generated_at_utc": _utc(),
        "generated_by": "scripts/st6_slot_ledger.py",
        "purpose": (
            "one durable entry per declared slot, so that the record of what happened to a slot "
            "survives the pruning of the run log and of the witness log it was derived from"
        ),
        "period": {
            "started_at_utc": period["started_at_utc"],
            "ends_at_utc": period["ends_at_utc"],
            "period_days": period["period_days"],
            "slots_per_day": period["slots_per_day"],
            "planned_slots": len(slots),
        },
        "declared_trigger": grid,
        "external_evidence": witness_inventory(WITNESS_LOG),
        "per_run_external_status": ((evidence or {}).get("per_run_external_evidence") or {}).get(
            "status"
        )
        or SCHEDULER_EVIDENCE_UNAVAILABLE,
        "induced_runs_recorded": sorted(induced),
        "summary": {
            "planned_slots": len(slots),
            "states": states,
            "attendance_classifications": classifications,
            "run_origins": origins,
            "slots_carrying_forward": sorted(
                entry["slot_id"] for entry in entries if entry["carried_forward_fields"]
            ),
            "external_coverage": {
                status: sum(1 for entry in entries if entry["external_evidence_status"] == status)
                for status in (
                    EXTERNAL_COVERAGE_COMPLETE,
                    EXTERNAL_COVERAGE_PARTIAL,
                    SCHEDULER_EVIDENCE_UNAVAILABLE,
                    EXTERNAL_COVERAGE_NOT_YET_STARTED,
                )
            },
        },
        "slots": entries,
        "reading": (
            "the ledger is rebuilt from the sources on every run and replaced atomically; it is "
            "keyed by the declared grid, so rebuilding is idempotent and no slot is invented or "
            "dropped; a slot still ahead is PENDING and a slot that ended with neither a window nor "
            "a recorded loss is UNACCOUNTED, which is a defect of the programme and not a state of "
            "the schedule"
        ),
        "archive": {
            "path": str(LEDGER_ARCHIVE.relative_to(REPO)).replace("\\", "/"),
            "written_when": "after the declared period closes, frozen with the period's identity",
            "present": LEDGER_ARCHIVE.exists(),
        },
        "previous_ledger": previous,
        "previous_ledger_errors": [
            *(
                [f"duplicate slot ids: {previous['duplicate_slot_ids']}"]
                if previous.get("duplicate_slot_ids")
                else []
            ),
            *(
                [f"malformed entries: {previous['malformed_entries']}"]
                if previous.get("malformed_entries")
                else []
            ),
            *([] if previous.get("readable") or previous["entries"] == 0 else [previous["reason"]]),
        ],
    }
    return document


def _attendance_policy_version() -> int:
    """The attendance policy version the builder itself declares."""
    from st6_forward_regime import ATTENDANCE_POLICY_VERSION

    return int(ATTENDANCE_POLICY_VERSION)


def build_provenance(ledger: dict[str, Any]) -> dict[str, Any]:
    """The provenance of the schedule: what is corroborated, by what, and what is not."""
    evidence = read_json(SCHEDULER_EVIDENCE)
    inventory = witness_inventory(WITNESS_LOG)
    block = (evidence or {}).get("per_run_external_evidence") or {}
    # every origin is counted, including the one for an event that declares nothing at all: an
    # omitted bucket would render as a zero in the report, and a report that under-counts what it
    # cannot attribute is a report that hides work
    by_origin = {origin: [] for origin in ORIGINS}
    for entry in ledger["slots"]:
        for row in entry["runs"]:
            by_origin.setdefault(str(row["origin"]), []).append(row)
    corroborated = by_origin.get(ORIGIN_CORROBORATED, [])
    induced = by_origin.get(ORIGIN_INDUCED, [])
    document = {
        "artifact": "ST6_SCHEDULER_PROVENANCE",
        "generated_at_utc": _utc(),
        "generated_by": "scripts/st6_slot_ledger.py",
        "task_name": TASK_NAME,
        "declared_schedule": ledger["declared_trigger"],
        "external_record": {
            "status": block.get("status") or SCHEDULER_EVIDENCE_UNAVAILABLE,
            "reason": block.get("reason"),
            "can_support": block.get("can_support"),
            "cannot_support": block.get("cannot_support"),
            "channels": (evidence or {}).get("channels"),
            "remediation": (evidence or {}).get("remediation"),
            "rotation": (evidence or {}).get("rotation_assessment"),
            "event_ids_that_would_carry_a_per_run_record": block.get(
                "event_ids_that_would_carry_a_per_run_record"
            ),
            "event_ids_verified_against_this_installation": block.get(
                "event_ids_verified_against_this_installation"
            ),
            "correlation_rule": block.get("correlation_rule"),
            "witness": inventory,
        },
        "origins": {
            "definition": {
                ORIGIN_CORROBORATED: (
                    "a witness sample names the scheduler's own last-run instant at this event's "
                    "start, so the Task Scheduler engine launched the task then; the operational "
                    "channel is disabled, so the trigger type stays unknown"
                ),
                ORIGIN_SELF_DECLARED: (
                    "the event declares itself the schedule and nothing outside the run log "
                    "corroborates it: a declaration, not proof"
                ),
                ORIGIN_MANUAL: "the event declares itself a manual invocation",
                ORIGIN_INDUCED: (
                    "this repository's own verifier asked the scheduler to run the task; a real "
                    "launch, and not the schedule's own tick"
                ),
                ORIGIN_UNATTRIBUTED: "the event declares nothing and no witness sample reaches it",
            },
            "counts": {origin: len(by_origin.get(origin, [])) for origin in ORIGINS},
            "corroborated_runs": corroborated[:20],
            "induced_runs": induced[:20],
            "reading": (
                "a run event's origin is decided outside the tick: by the scheduler's own record, by "
                "the verifier's own record of what it induced, or by the event's own declaration, "
                "which is the weakest of the three and is labelled as such"
            ),
        },
        "slots": {
            "planned": ledger["summary"]["planned_slots"],
            "states": ledger["summary"]["states"],
            "external_coverage": ledger["summary"]["external_coverage"],
            "classifications": ledger["summary"]["attendance_classifications"],
        },
        "attendance_policy": {
            # the version the builder declares, read from it rather than repeated here
            "version": _attendance_policy_version(),
            "absence_requires_external_coverage": True,
            "statement": (
                "attendance may be read from the tick's own log; absence may not. A slot is called "
                "unattended only when the external record covers every instant of it and the "
                "scheduler's own last-run field named no run inside it. Where the external record "
                "does not reach, the class is UNKNOWN or UNKNOWN_RUN_LOG_TRUNCATED, and where the "
                "two records disagree the class is a conflict."
            ),
        },
        "what_is_not_claimed": [
            "that any past slot of this period was provably unattended: no per-run external record "
            "covers those hours on this host",
            "that a run the scheduler's record corroborated was time-triggered: the trigger type is "
            "not observable here",
            "that the schedule will tick in the future: a declared cadence is not a promise",
        ],
        "system_time_utc": _utc(),
    }
    return document


def render_provenance_markdown(document: dict[str, Any], ledger: dict[str, Any]) -> str:
    origins = document["origins"]
    inventory = document["external_record"]["witness"]
    coverage = ledger["summary"]["external_coverage"]
    states = ledger["summary"]["states"]
    can_support = [str(item) for item in document["external_record"]["can_support"] or []]
    cannot_support = [str(item) for item in document["external_record"]["cannot_support"] or []]
    while len(cannot_support) < len(can_support):
        cannot_support.append("")
    support_rows = [
        f"| {good} | {bad} |"
        for good, bad in zip(can_support or [""], cannot_support or [""], strict=False)
    ]
    lines = [
        "# ST-6 — provenance of the scheduled tick",
        "",
        f"Generated {document['generated_at_utc']} by `scripts/st6_slot_ledger.py`, read-only with "
        "respect to the campaign.",
        "",
        f"## 01 — External evidence: `{document['external_record']['status']}`",
        "",
        document["external_record"]["reason"] or "",
        "",
        "| what the external record can support | what it cannot |",
        "| --- | --- |",
        *support_rows,
        "",
        f"Witness samples: {inventory['witness_samples']} "
        f"({inventory['covered_from_utc']} → {inventory['covered_to_utc']}); scheduler instants "
        f"observed: {len(inventory['scheduler_instants_observed'])}; ticks seen in flight with the "
        f"Task Scheduler service as their parent: {inventory['service_launched_ticks_observed']}.",
        "",
        f"Rotation of the external record: "
        f"`{(document['external_record'].get('rotation') or {}).get('status')}`.",
        "",
        *[
            f"- `{name}`: {entry['state']}"
            + (
                f", {entry['records_no_longer_present_before_the_oldest']} record(s) no longer "
                "present before the oldest one still held"
                if entry.get("records_no_longer_present_before_the_oldest")
                else ""
            )
            + (
                f", oldest retained event {entry['oldest_retained_event_utc']}"
                if entry.get("oldest_retained_event_utc")
                else ""
            )
            for name, entry in sorted(
                ((document["external_record"].get("rotation") or {}).get("channels") or {}).items()
            )
        ],
        "",
        "## 02 — Where each run event's origin comes from",
        "",
        "| origin | runs | what it means |",
        "| --- | --- | --- |",
        *[
            f"| `{origin}` | {origins['counts'].get(origin, 0)} | {origins['definition'][origin]} |"
            for origin in ORIGINS
        ],
        "",
        origins["reading"],
        "",
        "## 03 — The slot grid",
        "",
        "| state | slots |",
        "| --- | --- |",
        *[f"| {state} | {count} |" for state, count in sorted(states.items())],
        "",
        "| external coverage | slots |",
        "| --- | --- |",
        *[f"| {status} | {count} |" for status, count in sorted(coverage.items())],
        "",
        "| attendance class | slots |",
        "| --- | --- |",
        *(
            [
                f"| `{token}` | {count} |"
                for token, count in sorted(ledger["summary"]["attendance_classifications"].items())
            ]
            or [
                "| none | 0 |"
                if not states.get("COLLECTED")
                else f"| none (the {states['COLLECTED']} collected slot(s) are not losses and have "
                "no class here) | 0 |"
            ]
        ),
        "",
        "The vocabulary classifies *losses*: a slot that produced its own window and its raw evidence",
        "is described by its state (`COLLECTED`), not by a loss class, and no class is claimed for a",
        "slot that has not ended.",
        "",
        "## 04 — What this document does not claim",
        "",
        *[f"- {item}" for item in document["what_is_not_claimed"]],
        "",
        f"Remediation (needs an administrator, not applied): "
        f"`{(document['external_record']['remediation'] or {}).get('command')}`",
        "",
        "Research only: no orders, no credentials, no capital.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", action="store_true", help="freeze the closing copy too")
    args = parser.parse_args(argv)

    ledger = build_ledger()
    write_json_atomic(LEDGER, ledger)
    provenance = build_provenance(ledger)
    write_json_atomic(PROVENANCE_JSON, provenance)
    PROVENANCE_MD.write_text(
        render_provenance_markdown(provenance, ledger), encoding="utf-8"
    )
    frozen = None
    if args.archive:
        closure = read_json(CLOSURE)
        archive = {
            **ledger,
            "artifact": "ST6_SLOT_LEDGER_ARCHIVE",
            "archived_at_utc": _utc(),
            "frozen_for_period": {
                "started_at_utc": ledger["period"]["started_at_utc"],
                "ends_at_utc": ledger["period"]["ends_at_utc"],
            },
            "period_closed": bool(closure),
            "closure_identity": (
                f"{(closure or {}).get('period', {}).get('started_at_utc')} -> "
                f"{(closure or {}).get('period', {}).get('ends_at_utc')}"
            ),
        }
        write_json_atomic(LEDGER_ARCHIVE, archive)
        frozen = str(LEDGER_ARCHIVE.relative_to(REPO))
    print(
        f"ledger: {ledger['summary']['planned_slots']} declared slots, states "
        f"{ledger['summary']['states']}, coverage {ledger['summary']['external_coverage']}; "
        f"provenance {provenance['external_record']['status']}"
    )
    print(
        f"written -> {LEDGER.relative_to(REPO)}, {PROVENANCE_JSON.relative_to(REPO)}, "
        f"{PROVENANCE_MD.relative_to(REPO)}" + (f", {frozen}" if frozen else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
