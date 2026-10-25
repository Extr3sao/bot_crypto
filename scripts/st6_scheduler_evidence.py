"""ST-6 — the external evidence a slot may rest on, and the arithmetic of its coverage.

One loader, shared by the tick, the health check, the independent verifier and the slot ledger, so
that all four read the same external record — and a policy that stays duplicated on purpose: what a
classification *means* is implemented separately in each program, while *which bytes* count as
external evidence has exactly one definition.

The external record of this host is:

* ``data/st6/ST6_SCHEDULER_WITNESS.jsonl`` — dated samples of the Task Scheduler's own reporting for
  the task and of the operating system's process table, taken by ``st6_scheduler_witness.py``, a
  process that is not the tick;
* ``data/st6/ST6_SCHEDULER_EVIDENCE.json`` — the channel state, the task's registration and the
  declared status of per-run external evidence.

Nothing here invents coverage.  A slot is externally covered only when the witness sampled the
scheduler *inside* every declared tick of that slot, so that a trigger the scheduler ran could not
have happened unseen; otherwise the slot's external status is partial or unavailable, and the
programs that classify a lost slot must say ``ATTENDANCE_UNKNOWN`` rather than claim an absence.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "st6"
WITNESS_LOG = DATA / "ST6_SCHEDULER_WITNESS.jsonl"
EVIDENCE_JSON = DATA / "ST6_SCHEDULER_EVIDENCE.json"

SLOT_HOURS = 4
TICK_INTERVAL_S = 15 * 60
#: How much of a sampling interval may be missing at the edges of a slot and still count as
#: coverage.  The witness samples every minute by default; a gap of more than one declared tick
#: means a trigger could have run between two samples without being seen, and then the slot is not
#: covered — that is the whole point of the bound.
MAX_COVERAGE_GAP_S = TICK_INTERVAL_S

SCHEDULER_EVIDENCE_UNAVAILABLE = "SCHEDULER_EVIDENCE_UNAVAILABLE"
EXTERNAL_COVERAGE_COMPLETE = "EXTERNAL_COVERAGE_COMPLETE"
EXTERNAL_COVERAGE_PARTIAL = "EXTERNAL_COVERAGE_PARTIAL"
EXTERNAL_COVERAGE_NOT_YET_STARTED = "EXTERNAL_COVERAGE_NOT_YET_STARTED"
SCHEDULER_EVIDENCE_CONFLICT = "SCHEDULER_EVIDENCE_CONFLICT"


def _parse(stamp: str) -> datetime:
    text = str(stamp)
    if "." in text:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL log line by line.

    A line that cannot be parsed is dropped rather than allowed to destroy the file's other lines:
    a witness log written while a sample is in flight can end mid-record, and losing the whole log
    to one torn line would be worse than losing that line.  Dropping it can only *weaken* coverage —
    the gap shows up in the arithmetic as a partial or unavailable slot — so the failure direction is
    the safe one.
    """
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return document
    except json.JSONDecodeError:
        return None


def extract_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The samples of a witness log, normalised, with an unreadable row turning into no sample.

    Normalising an already-normalised sample is a no-op on purpose: every field is read under both the
    name the witness writes and the name this module gives it.  A single-pass conversion would
    silently drop the launch instants the second time round, and a dropped launch is the difference
    between a slot the scheduler demonstrably fired in and one this module has to call unknown.
    """
    samples: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        stamp = row.get("sampled_at_utc")
        if not stamp:
            continue
        try:
            moment = _parse(stamp)
        except ValueError:
            continue
        last_run = row.get("scheduler_reported_last_run_utc") or row.get(
            "scheduler_last_run_utc"
        )
        last_result = row.get("scheduler_reported_last_result")
        if last_result is None:
            last_result = row.get("scheduler_last_result")
        offset = row.get("system_local_offset_minutes")
        if offset is None:
            offset = row.get("local_offset_minutes")
        samples.append(
            {
                "sampled_at": moment,
                "sampled_at_utc": str(stamp),
                "scheduler_last_run_utc": str(last_run) if last_run else None,
                "scheduler_last_result": last_result,
                "scheduler_state": row.get("scheduler_reported_state", row.get("scheduler_state")),
                "missed_runs_counter": row.get(
                    "scheduler_reported_missed_runs", row.get("missed_runs_counter")
                ),
                "service_launched_tick": bool(
                    row.get("any_tick_launched_by_the_scheduler_service")
                    or row.get("service_launched_tick")
                ),
                "sample_id": row.get("sample_id"),
                "local_offset_minutes": offset,
                "system_last_boot_utc": row.get("system_last_boot_utc"),
            }
        )
    samples.sort(key=lambda entry: entry["sampled_at"])
    return samples


def load_samples(path: Path | None = None) -> list[dict[str, Any]]:
    return extract_samples(read_jsonl(path or WITNESS_LOG))


def external_status(evidence: dict[str, Any] | None) -> dict[str, Any]:
    """The declared status of per-run external evidence, read from the evidence document."""
    block = (evidence or {}).get("per_run_external_evidence") or {}
    status = str(block.get("status") or SCHEDULER_EVIDENCE_UNAVAILABLE)
    return {
        "status": status,
        "reason": block.get("reason"),
        "channels": (evidence or {}).get("channels"),
        "remediation": (evidence or {}).get("remediation"),
        "generated_at_utc": (evidence or {}).get("generated_at_utc"),
    }


def slot_external_coverage(
    starts_at: datetime,
    ends_at: datetime,
    samples: list[dict[str, Any]],
    evidence: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """What the external record can say about one declared slot.

    ``EXTERNAL_COVERAGE_COMPLETE`` requires a continuous chain of samples across the whole slot, so
    that no declared trigger could have run between two of them unnoticed.  The chain must also
    start at or before the slot's first instant and reach the slot's end — a slot that is still
    running can never be fully covered, and that is deliberate: coverage of a future instant is not
    something a witness can have.
    """
    moment_now = now or datetime.now(UTC)
    # normalised here whatever the caller passed: the arithmetic below compares datetimes, and a raw
    # witness row carries strings.  Re-normalising an already-normalised row is a no-op.
    samples = extract_samples(samples)
    inside = [entry for entry in samples if starts_at <= entry["sampled_at"] <= ends_at]
    before = [entry for entry in samples if entry["sampled_at"] < starts_at]
    # only a run instant *inside* the slot counts as a launch the slot has to explain: a sample taken
    # at 12:00:30 still names the 11:48 run, and that run belongs to the previous slot
    launches = sorted(
        {
            entry["scheduler_last_run_utc"]
            for entry in inside
            if entry["scheduler_last_run_utc"]
            and starts_at <= _parse(entry["scheduler_last_run_utc"]) <= ends_at
        }
    )
    near_boundary = sorted(
        {
            entry["scheduler_last_run_utc"]
            for entry in inside
            if entry["scheduler_last_run_utc"]
            and not (starts_at <= _parse(entry["scheduler_last_run_utc"]) <= ends_at)
        }
    )
    latest_sample = inside[-1]["sampled_at_utc"] if inside else None
    chain_start = before[-1]["sampled_at"] if before else (inside[0]["sampled_at"] if inside else None)
    gaps: list[float] = []
    if inside:
        walk = [chain_start] if chain_start and chain_start < inside[0]["sampled_at"] else []
        walk = [*walk, *[entry["sampled_at"] for entry in inside]]
        gaps = [
            (walk[index] - walk[index - 1]).total_seconds() for index in range(1, len(walk))
        ]
    largest_gap = max(gaps) if gaps else None
    covers_start = chain_start is not None and chain_start <= starts_at
    covers_end = moment_now >= ends_at and bool(inside) and inside[-1]["sampled_at"] >= (
        ends_at - timedelta(seconds=MAX_COVERAGE_GAP_S)
    )
    contiguous = largest_gap is not None and largest_gap <= MAX_COVERAGE_GAP_S
    # a restart inside the slot is an evidence discontinuity: the machine was down, so the
    # scheduler's persisted last-run field still says what it last ran, but an absence of a launch
    # inside the slot stops being proof that nothing was due
    boots = sorted(
        {entry["system_last_boot_utc"] for entry in inside if entry.get("system_last_boot_utc")}
    )
    restarted_inside_slot = len(boots) > 1 or any(
        entry.get("system_last_boot_utc")
        and starts_at <= _parse(str(entry["system_last_boot_utc"])) <= ends_at
        for entry in inside
    )
    if moment_now < starts_at:
        # a slot that has not begun cannot be covered by anything: coverage of a future instant is
        # not something a witness can have, and saying so keeps the arithmetic honest
        status = EXTERNAL_COVERAGE_NOT_YET_STARTED
    elif not samples or (not inside and not covers_start):
        status = SCHEDULER_EVIDENCE_UNAVAILABLE
    elif not inside:
        status = EXTERNAL_COVERAGE_PARTIAL if moment_now < ends_at else SCHEDULER_EVIDENCE_UNAVAILABLE
    elif covers_start and covers_end and contiguous and not restarted_inside_slot:
        status = EXTERNAL_COVERAGE_COMPLETE
    else:
        status = EXTERNAL_COVERAGE_PARTIAL
    if status == EXTERNAL_COVERAGE_NOT_YET_STARTED:
        reading = (
            "the slot has not begun: nothing can be said about its attendance yet, and the entry is "
            "a declaration of what is expected rather than a record of what happened"
        )
    elif status == EXTERNAL_COVERAGE_COMPLETE and not launches:
        # the witness watched the whole slot and the scheduler's own record never named a run inside
        # it: that is an absence the external record can carry, and it is the only way one may be
        # claimed
        reading = (
            "the witness covered every instant of the slot with samples no further apart than a "
            "declared tick, and the scheduler's own last-run field never named a run inside it"
        )
    elif status == EXTERNAL_COVERAGE_COMPLETE:
        reading = (
            f"the witness covered the slot and named {len(launches)} scheduler run instant(s) inside "
            "it: the schedule demonstrably fired, so an absent window is a failure of the tick, not "
            "of the host"
        )
    elif status == EXTERNAL_COVERAGE_PARTIAL and restarted_inside_slot:
        reading = (
            "the host restarted inside the slot: the witness saw the slot, but a machine that was "
            "down cannot support a claim about what the schedule did not do, so attendance inside "
            "the slot is UNKNOWN from the external record"
        )
    elif status == EXTERNAL_COVERAGE_PARTIAL:
        reading = (
            "the witness saw part of the slot but not all of it, so a trigger could have run between "
            "two samples unseen: attendance inside the slot is UNKNOWN from the external record"
        )
    else:
        reading = (
            "no external record covers this slot: the operational channel of this host has never "
            "recorded, and the witness was not sampling when the slot ran"
        )
    return {
        "status": status,
        "external_samples_in_slot": len(inside),
        "external_samples_before_slot": len(before),
        "coverage_chain_started_at_utc": chain_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        if chain_start
        else None,
        "latest_sample_in_slot_utc": latest_sample,
        "largest_sample_gap_s": largest_gap,
        "max_gap_tolerated_s": MAX_COVERAGE_GAP_S,
        "scheduler_engine_launches_reported_in_slot": launches,
        "scheduler_engine_launch_count": len(launches),
        "scheduler_engine_launches_reported_outside_the_slot": near_boundary,
        "scheduler_engine_launches_outside_the_slot_count": len(near_boundary),
        "system_restart_inside_slot": restarted_inside_slot,
        "boot_instants_observed": boots,
        "missing_evidence_status": (
            (evidence or {}).get("per_run_external_evidence", {}).get("status")
            or SCHEDULER_EVIDENCE_UNAVAILABLE
        ),
        "reading": reading,
        "evidence_lifetime": (
            "the witness log is bounded; the samples this coverage rests on may be pruned after the "
            "period closes, which is why the slot ledger is the durable record"
        ),
    }


def external_launch_evidence(
    starts_at: datetime, ends_at: datetime, samples: list[dict[str, Any]]
) -> dict[str, Any]:
    """The instants the scheduler's own record named inside a slot, and the samples that named them."""
    samples = extract_samples(samples)
    inside = [entry for entry in samples if starts_at <= entry["sampled_at"] <= ends_at]
    per_instant: dict[str, list[str]] = {}
    for entry in inside:
        instant = entry["scheduler_last_run_utc"]
        if instant:
            per_instant.setdefault(instant, []).append(entry["sampled_at_utc"])
    return {
        "instants": sorted(per_instant),
        "first_seen_by_sample": {instant: stamps[0] for instant, stamps in sorted(per_instant.items())},
        "last_seen_by_sample": {instant: stamps[-1] for instant, stamps in sorted(per_instant.items())},
        "count": len(per_instant),
    }


def cadence_position(
    instant_utc: str,
    boundary_local: str | None,
    offset_minutes: int | None,
    tolerance_s: int = 150,
) -> dict[str, Any]:
    """How the instant sits against the task's own declared repetition grid.

    The scheduler repeats every fifteen minutes from the trigger's start boundary, and it measures
    that grid in *local* wall-clock time.  A launch that lands on the grid is consistent with the
    time trigger; a launch at an arbitrary second is consistent with a run asked for by hand.  This
    is supporting evidence and it is reported with its tolerance, never as proof: an engine launch
    asked for by hand can land near the grid by accident, and a trigger can start its process
    seconds late.
    """
    if not boundary_local or offset_minutes is None:
        return {
            "status": "UNKNOWN",
            "detail": "the task's start boundary or the host's local offset is not recorded",
        }
    try:
        moment = _parse(instant_utc)
        boundary = datetime.strptime(boundary_local, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return {"status": "UNKNOWN", "detail": f"{instant_utc!r} is not a UTC timestamp"}
    # the arithmetic is in local wall-clock time, which carries no zone: the boundary the task
    # declares is a local time, and the trigger grid is drawn in the same space
    local = (moment + timedelta(minutes=offset_minutes)).replace(tzinfo=None)
    # the grid is the boundary shifted by whole multiples of the declared tick interval
    delta = (local - boundary).total_seconds()
    period_s = float(TICK_INTERVAL_S)
    grid_index = round(delta / period_s)
    grid_instant = boundary + timedelta(seconds=grid_index * period_s)
    offset_from_grid_s = abs((local - grid_instant).total_seconds())
    return {
        "status": "ON_DECLARED_GRID" if offset_from_grid_s <= tolerance_s else "OFF_DECLARED_GRID",
        "offset_from_grid_s": offset_from_grid_s,
        "tolerance_s": tolerance_s,
        "grid_instant_local": grid_instant.strftime("%Y-%m-%dT%H:%M:%S"),
        "grid_instant_utc": (grid_instant - timedelta(minutes=offset_minutes)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "tick_interval_s": TICK_INTERVAL_S,
        "reading": (
            "a launch on the declared grid is consistent with the time trigger; the operational "
            "channel is disabled on this host, so nothing here names the trigger"
        ),
    }


def local_offset_minutes(samples: list[dict[str, Any]]) -> int | None:
    """The host's UTC offset, read from the newest sample that recorded it."""
    for entry in reversed(samples):
        offset = entry.get("local_offset_minutes")
        if isinstance(offset, int):
            return offset
    return None


def corroborate_run(
    run: dict[str, Any],
    samples: list[dict[str, Any]],
    tolerance_s: int = 120,
    boundary_local: str | None = None,
) -> dict[str, Any]:
    """Can the scheduler's own record corroborate *this* run event, and as what?

    The run log says a process started at an instant; the witness says the scheduler's last-run
    field named an instant.  When the two agree to the second, the scheduler's own record has
    corroborated a launch at that instant — which is the one thing a declaration inside the run log
    cannot do for itself.  The engine does not record *why* it launched, and the operational channel
    that would name the trigger is disabled here, so a launch corroborated this way is reported as
    an engine launch of unknown trigger type rather than as a time-triggered run.
    """
    samples = extract_samples(samples)
    started = run.get("actual_start_utc")
    if not started:
        return {
            "status": "UNATTRIBUTED",
            "detail": "the run event carries no start instant, so nothing can be compared",
        }
    try:
        moment = _parse(str(started))
    except ValueError:
        return {
            "status": "UNATTRIBUTED",
            "detail": f"the run event's start instant {started!r} is not a UTC timestamp",
        }
    named: list[dict[str, Any]] = []
    for entry in samples:
        instant = entry["scheduler_last_run_utc"]
        if not instant:
            continue
        try:
            reported = _parse(instant)
        except ValueError:
            continue
        delta = abs((reported - moment).total_seconds())
        if delta <= tolerance_s:
            named.append(
                {
                    "sample_id": entry["sample_id"],
                    "sampled_at_utc": entry["sampled_at_utc"],
                    "scheduler_reported_instant_utc": instant,
                    "delta_s": delta,
                }
            )
    if not named:
        return {
            "status": "UNATTRIBUTED",
            "detail": (
                "no witness sample inside the tolerance names a scheduler run instant at this event's "
                "start; the scheduler keeps only its most recent run, so an old event cannot be "
                "corroborated after the fact"
            ),
            "tolerance_s": tolerance_s,
        }
    first = sorted(named, key=lambda entry: entry["delta_s"])[0]
    return {
        "status": "CORROBORATED_ENGINE_LAUNCH_TRIGGER_TYPE_UNKNOWN",
        "detail": (
            f"the scheduler's own last-run field named {first['scheduler_reported_instant_utc']} "
            f"while this run event started at {started} ({first['delta_s']} s apart), so the Task "
            "Scheduler service did launch the task at that instant; the operational channel is "
            "disabled here, so the record does not say whether a time trigger or an engine request "
            "asked for it"
        ),
        "tolerance_s": tolerance_s,
        "declared_grid": cadence_position(
            first["scheduler_reported_instant_utc"],
            boundary_local,
            local_offset_minutes(samples),
        ),
        "matches": named[:5],
    }


def witness_inventory(path: Path | None = None) -> dict[str, Any]:
    """A compact description of the external record, for the artefacts that quote it."""
    samples = load_samples(path)
    evidence = read_json(EVIDENCE_JSON)
    return {
        "witness_log": str(WITNESS_LOG.relative_to(REPO)).replace("\\", "/"),
        "witness_samples": len(samples),
        "covered_from_utc": samples[0]["sampled_at_utc"] if samples else None,
        "covered_to_utc": samples[-1]["sampled_at_utc"] if samples else None,
        "scheduler_instants_observed": sorted(
            {entry["scheduler_last_run_utc"] for entry in samples if entry["scheduler_last_run_utc"]}
        ),
        "service_launched_ticks_observed": sum(
            1 for entry in samples if entry["service_launched_tick"]
        ),
        "external_status": external_status(evidence)["status"],
        "evidence_generated_at_utc": (evidence or {}).get("generated_at_utc"),
        "evidence_document_sha256": _sha256_text(
            json.dumps(evidence or {}, sort_keys=True, ensure_ascii=False)
        ),
    }
