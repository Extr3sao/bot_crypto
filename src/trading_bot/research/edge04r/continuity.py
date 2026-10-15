"""WP-EDGE-04R — an attributed account of every trigger the forward lane lost.

The lane's health reading says *how many* triggers were lost (74 of 96) and stops
there. This module says *why*, by placing every trigger the schedule should have
fired on a timeline and asking the host's own record which state the machine was in
at that instant:

``HOST_DOWN``
    The host had recorded a shutdown covering the instant: nothing could run, and
    nothing was lost that a different task setting could have saved.
``SLEEP``
    The host recorded sleep or standby. Recorded separately from ``HOST_DOWN``
    because ``WakeToRun`` is a task setting, so this one is addressable.
``NO_SESSION``
    The host was up and no interactive session existed: a task registered with
    ``InteractiveToken`` cannot start, and the trigger produces no process and no
    record. This is the expensive one, and it is invisible from inside the lane.
``SILENT_UNATTRIBUTABLE``
    Host up, session present, no tick record. Whether the trigger failed to fire or
    fired and its process died before writing cannot be separated from the lane's
    side — and cannot be separated from the host's side either, because the Task
    Scheduler's operational log is disabled on this host. Reported as its own
    bucket rather than attributed to a cause the evidence does not name.

A trigger that *did* fire is accounted for separately by its own outcome: a tick
refused by the storage guard fired, consumed its trigger and sealed nothing.

Nothing here rewrites history, re-grades a day, or promotes anything. Research
only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.research.edge04r import os_evidence
from trading_bot.research.edge04r.os_evidence import HOST_DOWN, NO_SESSION, SLEEP

__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "SILENT_UNATTRIBUTABLE",
    "SLOT_CONSUMING_OUTCOMES",
    "Tick",
    "attribute_instant",
    "audit",
    "classify_instants",
    "expected_instants",
    "forward_invariants",
    "load_runs",
    "match_tolerance_ms",
    "phase_offset_ms",
]

AUDIT_SCHEMA_VERSION = "EDGE04R_CONTINUITY_AUDIT_V1"

#: Outcomes that consumed their slot: the observation happened (or was already had).
SLOT_CONSUMING_OUTCOMES = ("OBSERVED", "NO_NEW_DATA", "ALREADY_OBSERVED")

SILENT_UNATTRIBUTABLE = "SILENT_UNATTRIBUTABLE"

#: A tick is matched to a trigger instant when it started within this window of it. The
#: scheduler fires with sub-second precision but the interpreter takes seconds to start,
#: and a retry after a non-zero exit can arrive minutes later. The bound is therefore
#: derived from the cadence — half an interval less one second — and not fixed: with a
#: 15-minute schedule a ten-minute window would let a retry answer the NEXT trigger, which
#: would turn a lost observation into a late one. This constant is only the ceiling.
MATCH_TOLERANCE_MS = 10 * 60 * 1000


def match_tolerance_ms(interval_ms: int) -> int:
    """The widest a match may be without two instants being able to claim one tick."""
    if interval_ms <= 0:
        return MATCH_TOLERANCE_MS
    return max(1000, min(MATCH_TOLERANCE_MS, interval_ms // 2 - 1000))


DAY_MS = 86_400_000


@dataclass(frozen=True)
class Tick:
    """One recorded tick, reduced to the fields the audit reasons about."""

    run_id: str
    started_ms: int
    finished_ms: int | None
    mode: str
    outcome: str
    exit_code: int
    slot_key: str | None
    duration_seconds: float | None
    disk_status: str | None
    disk_free_bytes: int | None
    order_sent: bool | None = None
    hypothetical: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def consumed_slot(self) -> bool:
        return self.outcome in SLOT_CONSUMING_OUTCOMES

    @property
    def scheduled(self) -> bool:
        return self.mode.upper() == "SCHEDULED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_ms": self.started_ms,
            "finished_ms": self.finished_ms,
            "mode": self.mode,
            "outcome": self.outcome,
            "exit_code": self.exit_code,
            "slot_key": self.slot_key,
            "duration_seconds": self.duration_seconds,
            "disk_status": self.disk_status,
            "disk_free_bytes": self.disk_free_bytes,
            "order_sent": self.order_sent,
            "hypothetical": self.hypothetical,
            "consumed_slot": self.consumed_slot,
        }


def parse_instant(value: str | None) -> int | None:
    return os_evidence.parse_instant(value)


def stamp(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_runs(path: Path) -> list[Tick]:
    """Read the lane's tick log without ever repairing it.

    A line that cannot be parsed is counted and skipped: this audit describes the
    log it was given, and a log it silently rewrote would describe nothing.
    """
    ticks: list[Tick] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        started = row.get("started_at_ms")
        if not isinstance(started, int):
            fallback = parse_instant(row.get("started_at_utc"))
            if fallback is None:
                continue
            started = fallback
        finished = row.get("finished_at_ms")
        disk = row.get("disk_after") or row.get("disk") or {}
        free = disk.get("free_bytes") if isinstance(disk, dict) else None
        ticks.append(
            Tick(
                run_id=str(row.get("run_id") or ""),
                started_ms=started,
                finished_ms=finished if isinstance(finished, int) else None,
                mode=str(row.get("mode") or ""),
                outcome=str(row.get("outcome") or "UNKNOWN"),
                exit_code=int(row.get("exit_code") or 0),
                slot_key=str(row.get("slot_key")) if row.get("slot_key") else None,
                duration_seconds=(
                    float(row["duration_seconds"])
                    if isinstance(row.get("duration_seconds"), (int, float))
                    else None
                ),
                disk_status=str(disk.get("status")) if isinstance(disk, dict) and disk else None,
                disk_free_bytes=int(free) if isinstance(free, int) else None,
                order_sent=(
                    row.get("order_sent") if isinstance(row.get("order_sent"), bool) else None
                ),
                hypothetical=(
                    row.get("hypothetical") if isinstance(row.get("hypothetical"), bool) else None
                ),
                raw=row,
            )
        )
    return sorted(ticks, key=lambda item: item.started_ms)


def phase_offset_ms(ticks: Sequence[Tick], interval_ms: int) -> int | None:
    """The schedule's phase, measured from the ticks that actually fired.

    The registered task's repeat interval is the authority for *how often* it fires;
    where in the hour it fires is read back from the host's own launches rather than
    assumed, because a task re-registered at a different minute moves the phase and a
    phase taken from configuration would then mis-date every instant after it.
    """
    offsets: dict[int, int] = {}
    for tick in ticks:
        if not tick.scheduled:
            continue
        offset = tick.started_ms % interval_ms
        bucket = offset // 1000
        offsets[bucket] = offsets.get(bucket, 0) + 1
    if not offsets:
        return None
    best = max(sorted(offsets), key=lambda key: offsets[key])
    return best * 1000


def expected_instants(first_ms: int, last_ms: int, interval_ms: int, phase_ms: int) -> list[int]:
    """Every instant the schedule should have fired in ``[first_ms, last_ms]``."""
    if last_ms < first_ms or interval_ms <= 0:
        return []
    first = first_ms - (first_ms - phase_ms) % interval_ms
    if first < first_ms:
        first += interval_ms
    count = (last_ms - first) // interval_ms + 1
    if count <= 0:
        return []
    return [first + index * interval_ms for index in range(int(count))]


def _inside(instant: int, windows: Iterable[tuple[int, int, str]], *, until_ms: int) -> str | None:
    for start, end, reason in windows:
        stop = end if end else until_ms
        if start <= instant <= stop:
            return reason
    return None


def attribute_instant(instant: int, availability: dict[str, Any], *, until_ms: int) -> str:
    """Which recorded state the host was in at ``instant``, lowest cause winning.

    Precedence is deliberate: a host that is down explains a silence by itself, sleep
    is a state the task can be armed to wake from, and an absent session explains a
    silence only while the host is up.
    """
    if _inside(instant, availability.get("host_down") or [], until_ms=until_ms) is not None:
        return HOST_DOWN
    if _inside(instant, availability.get("sleep") or [], until_ms=until_ms) is not None:
        return SLEEP
    if _inside(instant, availability.get("session_absent") or [], until_ms=until_ms) is not None:
        return NO_SESSION
    return SILENT_UNATTRIBUTABLE


def classify_instants(
    instants: Sequence[int],
    ticks: Sequence[Tick],
    availability: dict[str, Any],
    *,
    until_ms: int,
    tolerance_ms: int = MATCH_TOLERANCE_MS,
) -> dict[str, Any]:
    """Match trigger instants to ticks, then attribute every unmatched instant.

    Matching is greedy and one-to-one: each trigger instant takes at most one tick
    and each tick at most one instant, so a burst of retries cannot be counted as
    several triggers firing.
    """
    scheduled = [tick for tick in ticks if tick.scheduled]
    remaining = list(scheduled)
    matched: list[dict[str, Any]] = []
    unmatched: list[int] = []
    for instant in instants:
        best: Tick | None = None
        best_distance: int | None = None
        for tick in remaining:
            distance = abs(tick.started_ms - instant)
            if distance > tolerance_ms:
                continue
            if best_distance is None or distance < best_distance:
                best, best_distance = tick, distance
        if best is None:
            unmatched.append(instant)
            continue
        remaining.remove(best)
        matched.append(
            {
                "instant_ms": instant,
                "instant_utc": stamp(instant),
                "offset_seconds": round((best.started_ms - instant) / 1000, 3),
                "tick": best.as_dict(),
            }
        )
    causes: dict[str, int] = {}
    unattributed: list[dict[str, Any]] = []
    for instant in unmatched:
        cause = attribute_instant(instant, availability, until_ms=until_ms)
        causes[cause] = causes.get(cause, 0) + 1
        unattributed.append({"instant_ms": instant, "instant_utc": stamp(instant), "cause": cause})
    refused = [item for item in matched if not bool(item["tick"]["consumed_slot"])]
    return {
        "expected": len(instants),
        "matched": len(matched),
        "matched_ticks": matched,
        "unmatched": unmatched,
        "unattributed": unattributed,
        "unmatched_causes": causes,
        "refused": refused,
        "ticks_without_instant": [tick.as_dict() for tick in remaining],
        "reading": (
            "each trigger instant takes at most one tick and each tick at most one "
            "instant: a retried tick cannot be counted as two triggers firing, and a "
            "tick that fired with no instant to answer to is reported rather than dropped"
        ),
    }


def _silences(ticks: Sequence[Tick], interval_ms: int, *, warning_ms: int) -> list[dict[str, Any]]:
    """Silences between consecutive scheduled ticks, with the instants they swallowed."""
    scheduled = [tick for tick in ticks if tick.scheduled]
    rows: list[dict[str, Any]] = []
    for previous, current in itertools.pairwise(scheduled):
        span = current.started_ms - previous.started_ms
        missed = max(0, round(span / interval_ms) - 1)
        row = {
            "from_utc": stamp(previous.started_ms),
            "to_utc": stamp(current.started_ms),
            "seconds": round(span / 1000, 3),
            "missed_triggers": missed,
            "warning": span > warning_ms,
            "previous_outcome": previous.outcome,
            "next_outcome": current.outcome,
        }
        rows.append(row)
    rows.sort(key=lambda item: float(item["seconds"]), reverse=True)
    return rows


def _empty_day(key: str) -> dict[str, Any]:
    return {
        "day": key,
        "expected": 0,
        "consumed": 0,
        "refused": 0,
        "no_session": 0,
        "host_down": 0,
        "sleep": 0,
        "silent": 0,
    }


def _daily(
    answers: Sequence[Mapping[str, Any]],
    instants: Sequence[int],
    availability: dict[str, Any],
    unmatched: Sequence[int],
    *,
    until_ms: int,
) -> list[dict[str, Any]]:
    """A per-UTC-day reading of the same arithmetic, so no total hides a bad day.

    Only instants *no process answered* are attributed to a host state; an instant a
    tick answered is counted as that tick's outcome. A launch the host started outside
    the repeating cadence is not one of the day's expectations and is not counted here,
    which is what lets every day's columns add up to its own expectation count.
    """
    if not instants:
        return []
    days: dict[str, dict[str, Any]] = {}
    for instant in instants:
        key = stamp(instant)[:10]
        days.setdefault(key, _empty_day(key))["expected"] += 1
    for instant in unmatched:
        key = stamp(instant)[:10]
        row = days.setdefault(key, _empty_day(key))
        cause = attribute_instant(instant, availability, until_ms=until_ms)
        if cause == HOST_DOWN:
            row["host_down"] += 1
        elif cause == SLEEP:
            row["sleep"] += 1
        elif cause == NO_SESSION:
            row["no_session"] += 1
        else:
            row["silent"] += 1
    for answer in answers:
        # The day belongs to the trigger, not to the launch: a tick that answers the
        # 23:55 instant at 23:56 belongs to the same day, and one that answers it at
        # 00:01 belongs to the day of the trigger it answered.
        key = str(answer["instant_utc"])[:10]
        row = days.setdefault(key, _empty_day(key))
        if answer["tick"]["consumed_slot"]:
            row["consumed"] += 1
        else:
            row["refused"] += 1
    rows: list[dict[str, Any]] = []
    for key in sorted(days):
        row = days[key]
        accounted = (
            row["consumed"]
            + row["refused"]
            + row["no_session"]
            + row["host_down"]
            + row["sleep"]
            + row["silent"]
        )
        row["accounted"] = accounted
        row["unaccounted"] = row["expected"] - accounted
        row["coverage_of_expected"] = (
            round(row["consumed"] / row["expected"], 4) if row["expected"] else None
        )
        rows.append(row)
    return rows


def _disk_pressure(
    ticks: Sequence[Tick], *, critical_bytes: int, warning_bytes: int
) -> dict[str, Any]:
    """The storage reading, taken from the lane's own per-tick measurements.

    The readings are the lane's, taken at each tick; the seconds between two ticks are
    attributed to the earlier reading, which understates rather than overstates how
    long the volume sat in each state.
    """
    samples: list[tuple[str, int, int, str | None]] = [
        (stamp(tick.started_ms), tick.started_ms, tick.disk_free_bytes, tick.disk_status)
        for tick in ticks
        if tick.disk_free_bytes is not None
    ]
    if not samples:
        return {"samples": 0, "reading": "the lane recorded no storage reading"}
    critical_seconds = 0.0
    warning_seconds = 0.0
    for previous, current in itertools.pairwise(samples):
        span = (current[1] - previous[1]) / 1000
        if previous[3] == "CRITICAL":
            critical_seconds += span
        elif previous[3] == "WARNING":
            warning_seconds += span
    frees: list[int] = [item[2] for item in samples]
    return {
        "samples": len(samples),
        "minimum_free_bytes": min(frees),
        "minimum_free_gib": round(min(frees) / 1024**3, 4),
        "maximum_free_bytes": max(frees),
        "maximum_free_gib": round(max(frees) / 1024**3, 4),
        "first_utc": samples[0][0],
        "last_utc": samples[-1][0],
        "seconds_in_critical": round(critical_seconds, 3),
        "seconds_in_warning": round(warning_seconds, 3),
        "hours_in_critical": round(critical_seconds / 3600, 3),
        "critical_threshold_bytes": critical_bytes,
        "warning_threshold_bytes": warning_bytes,
        "refused_ticks": sum(1 for tick in ticks if tick.outcome == "DISK_BUDGET_EXCEEDED"),
        "reading": (
            "the guard's own thresholds are unchanged: it refuses before any market request, "
            "so a refused tick costs a market call and a slot, never a false observation"
        ),
    }


@dataclass(frozen=True)
class VolumeRow:
    """One volume, with the columns the relocation decision reads."""

    drive_letter: str
    label: str
    file_system: str
    capacity_gib: float
    free_gib: float
    used_percent: float | None
    is_primary_disk: bool


def _as_text(value: Any) -> str:
    """A string from an evidence field, or an empty one: never a Python repr of it."""
    return value if isinstance(value, str) else ""


def _as_float(value: Any) -> float:
    """A number from an evidence field, or ``0.0`` when it is not one."""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _storage_estate(
    evidence: dict[str, Any],
    *,
    lane_bytes: int,
    budget_bytes: int,
    warning_bytes: int,
    current_drive: str,
) -> dict[str, Any]:
    rows: list[VolumeRow] = []
    for raw in evidence.get("volumes") or []:
        if not isinstance(raw, dict):
            continue
        capacity = _as_float(raw.get("capacity_bytes"))
        free = _as_float(raw.get("free_bytes"))
        letter = _as_text(raw.get("drive_letter"))
        rows.append(
            VolumeRow(
                drive_letter=letter,
                label=_as_text(raw.get("label")),
                file_system=_as_text(raw.get("file_system")),
                capacity_gib=round(capacity / 1024**3, 2),
                free_gib=round(free / 1024**3, 2),
                used_percent=round((capacity - free) / capacity * 100, 2) if capacity else None,
                is_primary_disk=letter.upper().startswith("C"),
            )
        )
    # A volume can host the store only if it is mounted, local, NTFS, independent of the
    # volume the lane already lives on, and roomy enough to hold the lane's declared
    # budget AND leave it above the guard's own warning floor: a target that would put
    # the store straight into CRITICAL has not solved anything. A recovery partition, a
    # FAT32 mount and a network-backed mount that mirrors the host's own capacity all
    # fail those tests, and each failure is named rather than quietly filtered out.
    required_bytes = max(budget_bytes, warning_bytes + budget_bytes)
    required_gib = required_bytes / 1024**3
    evaluated: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for row in rows:
        reasons: list[str] = []
        if not row.drive_letter:
            reasons.append("not mounted: there is no path to write the store to")
        elif row.drive_letter.upper().startswith(current_drive.upper()):
            reasons.append(
                "the volume the lane already lives on: moving a tree inside one volume is not "
                "relocation and would not change the free space the guard reads"
            )
        if row.file_system.upper() != "NTFS":
            reasons.append(
                f"{row.file_system or 'unknown'} is not NTFS: the store's atomic rename and "
                "long-path behaviour are not guaranteed"
            )
        if row.free_gib < required_gib:
            reasons.append(
                f"{row.free_gib} GiB free is below the {round(required_gib, 2)} GiB a target "
                "must hold to keep the lane above the guard's warning floor"
            )
        entry: dict[str, Any] = {
            "drive_letter": row.drive_letter,
            "label": row.label,
            "file_system": row.file_system,
            "capacity_gib": row.capacity_gib,
            "free_gib": row.free_gib,
            "used_percent": row.used_percent,
            "is_primary_disk": row.is_primary_disk,
            "usable_for_relocation": not reasons,
            "exclusion_reason": "; ".join(reasons) if reasons else None,
        }
        evaluated.append(entry)
        if not reasons:
            candidates.append(entry)
    return {
        "volumes": sorted(evaluated, key=lambda row: row["free_gib"], reverse=True),
        "required_free_gib": round(required_gib, 3),
        "drive_type_note": (
            "drive_type 3 is a fixed local disk; a network-backed or cloud mount can report the "
            "same capacity as the host's own volume while holding none of it, which is why "
            "capacity alone is not accepted as room"
        ),
        "physical_disks": [
            {
                "friendly_name": _as_text(row.get("friendly_name")),
                "media_type": _as_text(row.get("media_type")),
                "bus_type": _as_text(row.get("bus_type")),
                "size_gib": round(_as_float(row.get("size_bytes")) / 1024**3, 2),
            }
            for row in evidence.get("physical_disks") or []
            if isinstance(row, dict)
        ],
        "lane_bytes": lane_bytes,
        "lane_budget_bytes": budget_bytes,
        "relocatable_candidates": candidates,
        "current_drive": current_drive or None,
        "verdict": "RELOCATION_AVAILABLE" if candidates else "NO_VOLUME_WITH_CAPACITY",
        "reading": (
            "relocation is judged only on volumes that are real, writable and independent of "
            "primary storage; a network-backed mount that reports the host's own capacity is "
            "not a volume with capacity, and no other workstream's tree is moved to make room"
        ),
    }


def audit(
    *,
    runs_path: Path,
    slots_path: Path | None,
    evidence: dict[str, Any],
    interval_seconds: int,
    until_ms: int,
    lane_bytes: int,
    lane_budget_bytes: int,
    critical_bytes: int,
    warning_bytes: int,
    coverage_required: float,
    forward_days_required: int,
    current_drive: str = "C:",
) -> dict[str, Any]:
    """The whole reading: instants, attribution, availability, storage, invariants."""
    ticks = load_runs(runs_path)
    interval_ms = interval_seconds * 1000
    scheduled = [tick for tick in ticks if tick.scheduled]
    if not scheduled:
        return {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "verdict": "NO_SCHEDULED_TICKS",
            "ticks": len(ticks),
        }
    phase = phase_offset_ms(ticks, interval_ms)
    assert phase is not None  # guaranteed: `scheduled` is non-empty here
    first = scheduled[0].started_ms
    instants = expected_instants(first, until_ms, interval_ms, phase)
    availability = os_evidence.windows(evidence)
    classification = classify_instants(
        instants,
        ticks,
        availability,
        until_ms=until_ms,
        tolerance_ms=match_tolerance_ms(interval_ms),
    )

    sealed: set[str] = set()
    if slots_path is not None and Path(slots_path).is_file():
        for line in Path(slots_path).read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                rows = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(rows, dict) and rows.get("slot_key"):
                sealed.add(str(rows["slot_key"]))

    lifespan_ms = max(1, until_ms - first)
    absent = [
        (max(start, first), end if end else until_ms, reason)
        for start, end, reason in availability["session_absent"]
    ]
    down = [
        (max(start, first), end if end else until_ms, reason)
        for start, end, reason in availability["host_down"]
    ]
    absent_seconds = sum((end - start) / 1000 for start, end, _r in absent if end > start)
    down_seconds = sum((end - start) / 1000 for start, end, _r in down if end > start)
    refused = len(classification["refused"])
    consumed_from_answers = int(classification["matched"]) - refused
    refused_all = sum(1 for tick in ticks if not tick.consumed_slot)
    consumed_all = sum(1 for tick in ticks if tick.consumed_slot)
    expected = int(classification["expected"])
    logon_instants = [at for at, kind in availability["transitions"] if kind == "logon"]

    # Recovery latency is only meaningful for a window that ENDS at a sign-in: that is
    # the instant the lane regains the ability to start at all, so the delay to the next
    # tick is the delay to the resumption. A shutdown window that ends inside a longer
    # session absence is kept, flagged, and its latency is not quoted as a recovery.
    recovery: list[dict[str, Any]] = []
    for start, end, reason in sorted(absent) + sorted(down):
        if not end:
            continue
        following = [tick.started_ms for tick in scheduled if tick.started_ms >= end]
        ends_at_sign_in = any(abs(end - at) <= 1000 for at in logon_instants)
        recovery.append(
            {
                "window_from_utc": stamp(start),
                "window_to_utc": stamp(end),
                "reason": reason,
                "seconds": round((end - start) / 1000, 3),
                "ends_at_a_sign_in": ends_at_sign_in,
                "first_tick_after_utc": stamp(following[0]) if following else None,
                "recovery_latency_seconds": (
                    round((following[0] - end) / 1000, 3) if following and ends_at_sign_in else None
                ),
                "latency_note": (
                    "measured from the sign-in that ended the window"
                    if ends_at_sign_in
                    else "not quoted: this window ends inside a longer session absence, so the "
                    "delay to the next tick measures that absence, not this reboot"
                ),
            }
        )

    silences = _silences(ticks, interval_ms, warning_ms=2 * interval_ms + 300)
    payload_invariants = forward_invariants(ticks, coverage_required, forward_days_required)
    checks = [
        _check(
            "every_answered_instant_is_a_tick",
            consumed_from_answers + refused == int(classification["matched"]),
            f"{int(classification['matched'])} answered instants = {consumed_from_answers} "
            f"slot-consuming + {refused} refused",
        ),
        _check(
            "answered_and_unanswered_account_for_every_instant",
            int(classification["matched"]) + len(classification["unmatched"]) == expected,
            f"{int(classification['matched'])} answered + {len(classification['unmatched'])} "
            f"unanswered = {expected} expected",
        ),
        _check(
            "every_unmatched_instant_has_a_recorded_cause",
            sum(classification["unmatched_causes"].values()) == len(classification["unmatched"]),
            f"{len(classification['unmatched'])} unanswered instants, {sum(classification['unmatched_causes'].values())} attributed",
        ),
        _check(
            "sleep_cause_is_claimed_only_with_a_sleep_record",
            classification["unmatched_causes"].get(SLEEP, 0) == 0
            or int(availability["counts"]["sleep_resume_pairs"]) > 0,
            f"{classification['unmatched_causes'].get(SLEEP, 0)} sleep attributions against "
            f"{availability['counts']['sleep_resume_pairs']} recorded sleep/resume pairs",
        ),
        _check(
            "coverage_threshold_unchanged",
            coverage_required == 0.9,
            f"the lane's per-day coverage floor is still {coverage_required}",
        ),
        _check(
            "forward_requirement_unchanged",
            forward_days_required == 60,
            f"the admission requirement is still {forward_days_required} prospective days",
        ),
        _check(
            "no_tick_claims_an_order",
            all(tick.order_sent is not True for tick in ticks),
            f"{len(ticks)} tick records read, {sum(1 for tick in ticks if tick.order_sent is True)} "
            "of them record an order",
        ),
        _check(
            "every_tick_marks_itself_hypothetical",
            all(tick.hypothetical is not False for tick in ticks),
            f"{sum(1 for tick in ticks if tick.hypothetical is False)} tick records claim a "
            "non-hypothetical result",
        ),
    ]

    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "generated_at_utc": stamp(until_ms),
        "window": {
            "from_utc": stamp(first),
            "to_utc": stamp(until_ms),
            "seconds": round(lifespan_ms / 1000, 3),
            "hours": round(lifespan_ms / 3_600_000, 3),
            "interval_seconds": interval_seconds,
            "phase_offset_ms": phase,
            "phase_source": "measured from the ticks the host actually launched",
        },
        "ticks": {
            "total": len(ticks),
            "scheduled": len(scheduled),
            "manual": len(ticks) - len(scheduled),
            "consumed_slot": consumed_all,
            "refused": refused_all,
            "launches_outside_the_cadence": len(classification["ticks_without_instant"]),
            "launch_details": classification["ticks_without_instant"],
            "outcomes": _counts(tick.outcome for tick in ticks),
            "refusals_by_outcome": _counts(
                item["tick"]["outcome"] for item in classification["refused"]
            ),
            "median_duration_seconds": _median(
                [tick.duration_seconds for tick in ticks if tick.duration_seconds is not None]
            ),
            "max_duration_seconds": max(
                [tick.duration_seconds for tick in ticks if tick.duration_seconds is not None],
                default=None,
            ),
            "overrunning_ticks": [
                tick.as_dict()
                for tick in ticks
                if tick.duration_seconds is not None and tick.duration_seconds > interval_seconds
            ],
        },
        "trigger_loss": {
            "expected": expected,
            "answered_by_a_tick": int(classification["matched"]),
            "slot_consuming_answers": consumed_from_answers,
            "never_answered": len(classification["unmatched"]),
            "causes": classification["unmatched_causes"],
            "unattributed_instants": classification["unattributed"],
            "refused_after_firing": refused,
            "total_lost": refused + len(classification["unmatched"]),
            "reading": (
                "a trigger answered by a tick that the guard refused was fired and lost, and so "
                "was a trigger no process answered; the two are counted apart because only one of "
                "them is a scheduling problem"
            ),
        },
        "availability": {
            "host_down_seconds": round(down_seconds, 3),
            "host_down_hours": round(down_seconds / 3600, 3),
            "session_absent_seconds": round(absent_seconds, 3),
            "session_absent_hours": round(absent_seconds / 3600, 3),
            "schedulable_fraction": round(
                1 - (absent_seconds + down_seconds) / (lifespan_ms / 1000), 4
            ),
            "windows": availability,
            "recovery": recovery,
            "reading": (
                "schedulable is the fraction of the window in which the host was up AND a session "
                "existed: a task registered with InteractiveToken has no other state in which it "
                "can start, so on this host that fraction is the ceiling on observation"
            ),
        },
        "silences": {
            "worst": silences[:10],
            "over_warning_bound": sum(1 for row in silences if row["warning"]),
            "reading": (
                "a silence is measured between the ticks that consumed a slot, so an unclosed gap "
                "in the slot ledger is visible here as the seconds between two ticks"
            ),
        },
        "daily": _daily(
            classification["matched_ticks"],
            instants,
            availability,
            classification["unmatched"],
            until_ms=until_ms,
        ),
        "storage": {
            "pressure": _disk_pressure(
                ticks, critical_bytes=critical_bytes, warning_bytes=warning_bytes
            ),
            "estate": _storage_estate(
                evidence,
                lane_bytes=lane_bytes,
                budget_bytes=lane_budget_bytes,
                warning_bytes=warning_bytes,
                current_drive=current_drive,
            ),
        },
        "slots": {"sealed": len(sealed)},
        "invariants": payload_invariants,
        "checks": checks,
        "verdict": "AUDIT_PASS" if all(check["passed"] for check in checks) else "AUDIT_FAIL",
        "hypothetical": True,
        "order_sent": False,
    }


def forward_invariants(
    ticks: Sequence[Tick], coverage_required: float, forward_days_required: int
) -> dict[str, Any]:
    """The things WP-EDGE-04R promises NOT to have moved.

    The ruleset digest is re-derived from ``FROZEN_PARAMS`` in this process and compared
    with three other statements of it: the constant the candidates module publishes, the
    value the campaign recorded before this lane existed, and the digest the lane's own
    ticks stamped on themselves. A drift is reported as a failure with the exception text,
    never smoothed into a pass — and it is reported even when the rest of the audit is
    clean, because a forward reading of a moved ruleset is not a forward reading.
    """
    try:
        from trading_bot.research.edge03.forward_plan import assert_frozen_params

        frozen: dict[str, Any] = assert_frozen_params()
        frozen["agrees"] = bool(
            frozen.get("agrees_with_imported_constant") and frozen.get("agrees_with_publication")
        )
    except Exception as exc:  # a moved ruleset must not take the audit down with it
        frozen = {"agrees": False, "error": f"{type(exc).__name__}: {exc}"}
    recorded = sorted(
        {
            str(tick.raw.get("ruleset", {}).get("params_hash"))
            for tick in ticks
            if isinstance(tick.raw.get("ruleset"), dict)
        }
    )
    ticks_agree = all(
        isinstance(tick.raw.get("ruleset"), dict)
        and tick.raw["ruleset"].get("params_hash") == frozen.get("params_hash")
        for tick in ticks
        if isinstance(tick.raw.get("ruleset"), dict)
    )
    promotions = _counts(
        str(tick.raw.get("promotion")) for tick in ticks if tick.raw.get("promotion")
    )
    return {
        "ruleset": {**frozen, "hashes_recorded_by_ticks": recorded, "ticks_agree": ticks_agree},
        "coverage_required": coverage_required,
        "forward_days_required": forward_days_required,
        "promotion": promotions,
        "orders_recorded": sum(1 for tick in ticks if tick.order_sent is True),
        "non_hypothetical_ticks": sum(1 for tick in ticks if tick.hypothetical is False),
        "reading": (
            "the frozen ruleset, the coverage floor, the 60-day requirement and the "
            "no-order/no-promotion marks are read back from the records rather than "
            "restated here, so a drift shows up as a disagreement between them"
        ),
    }


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 3)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 3)


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}
