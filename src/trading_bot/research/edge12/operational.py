"""WP-EDGE-12E — what the lane actually did, with the three levels kept apart.

RFC-EDGE-012 says the operational result must be separated from the economic result and
that a trigger which fired, an observation which was made and a day which is admissible
are three different things. They are also the three things a reader conflates most
readily, because each of them is a count of "something that happened" in the same log:

* a **trigger fired** — the schedule's own instant, whether or not anything started.
  This is a property of the calendar and the registration;
* an **observation was made** — a tick ran the pipeline and consumed its slot. This is
  a property of a process;
* a **day is admissible** — every primary asset met the declared coverage with bars
  that were stored as they closed. This is a property of the store, and it is the only
  one of the three that a later decision is allowed to count.

The reading is taken over a *declared* window. Nothing here extrapolates: the window,
its cadence and its phase are inputs, and every figure is a function of them plus the
lane's own logs and the host's own record.

This module does not re-publish WP-EDGE-04R's continuity audit and is not a substitute
for it: that audit attributes every instant of its own frozen window from a committed
snapshot, while this one reads the live lane over a window declared here. Where they
disagree, the disagreement is the finding.

Read-only with respect to the lane, the store and the host.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

__all__ = [
    "OPERATIONAL_SCHEMA_VERSION",
    "attributed_losses",
    "expected_instants",
    "forward_coverage",
    "operational_reading",
]

OPERATIONAL_SCHEMA_VERSION = "EDGE12_OPERATIONAL_VALIDATION_V1"

#: Outcomes that mean the guard or the pipeline refused after the trigger fired. They
#: cost a slot and produce no observation, which is why they are counted apart.
REFUSAL_OUTCOMES = (
    "DISK_BUDGET_EXCEEDED",
    "PROVIDER_UNAVAILABLE",
    "MISSING_BARS",
    "STALE_DATA",
    "VERIFICATION_FAILED",
    "RUNTIME_EXCEPTION",
)


def _stamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ms(value: str | None) -> int | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def expected_instants(
    *, first_ms: int, phase_ms: int, interval_ms: int, until_ms: int
) -> list[int]:
    """Every instant the declared cadence should have fired, from the first to ``until``.

    The phase is supplied rather than assumed: the registration's ``StartBoundary``
    decides which quarter-hour the task fires in, and a reader who assumes :00 will find
    different losses from one who reads the boundary. The list starts at the first
    instant strictly after ``first_ms`` — the launch that established the phase is the
    observation of it, not one of its own successors.
    """
    if interval_ms <= 0:
        raise ValueError("interval_ms must be positive")
    instant = first_ms - ((first_ms - phase_ms) % interval_ms) + interval_ms
    out: list[int] = []
    while instant <= until_ms:
        out.append(instant)
        instant += interval_ms
    return out


def _windows(evidence: dict[str, Any]) -> dict[str, Any]:
    from trading_bot.research.edge04r import os_evidence

    return os_evidence.windows(evidence)


def attributed_losses(
    *,
    instants: list[int],
    answered: dict[int, str],
    evidence: dict[str, Any],
    until_ms: int,
) -> dict[str, Any]:
    """Give every unanswered instant a cause the host wrote, or say it has none.

    Precedence is by strength of the record, not by convenience: a host that was down
    explains a silence on its own, a session that was absent explains one only while the
    host is up, and anything left is unattributable rather than guessed. The three
    windows come from the host's own event log; a cause is never extended past the
    evidence for it.
    """
    windows = _windows(evidence)
    host_down = windows["host_down"]
    session_absent = windows["session_absent"]
    sleep = windows["sleep"]

    def covered(instant: int, ranges: list[tuple[int, int, str]]) -> bool:
        for start, end, _reason in ranges:
            stop = until_ms if not end else min(end, until_ms)
            if start <= instant < stop:
                return True
        return False

    causes: dict[str, list[int]] = {
        "HOST_DOWN": [],
        "NO_SESSION": [],
        "SLEEP": [],
        "SILENT_UNATTRIBUTABLE": [],
    }
    for instant in instants:
        if instant in answered:
            continue
        if covered(instant, host_down):
            causes["HOST_DOWN"].append(instant)
        elif covered(instant, sleep):
            causes["SLEEP"].append(instant)
        elif covered(instant, session_absent):
            causes["NO_SESSION"].append(instant)
        else:
            causes["SILENT_UNATTRIBUTABLE"].append(instant)
    return {
        "causes": {name: len(values) for name, values in causes.items()},
        "instants_by_cause": {
            name: [_stamp(value) for value in values] for name, values in causes.items()
        },
        "windows": {
            "host_down": [
                {"from_utc": _stamp(start), "to_utc": _stamp(end or until_ms), "reason": reason}
                for start, end, reason in host_down
            ],
            "session_absent": [
                {"from_utc": _stamp(start), "to_utc": _stamp(end or until_ms), "reason": reason}
                for start, end, reason in session_absent
            ],
            "sleep": [
                {"from_utc": _stamp(start), "to_utc": _stamp(end or until_ms), "reason": reason}
                for start, end, reason in sleep
            ],
        },
        "counts": windows["counts"],
        "total_lost": sum(len(values) for values in causes.values()),
        "reading": (
            "an instant with no host-side record stays SILENT_UNATTRIBUTABLE; the operational log "
            "that would name its cause is disabled on this host, which is a limit of the evidence "
            "rather than of the attribution"
        ),
    }


def operational_reading(
    *,
    runs: list[dict[str, Any]],
    evidence: dict[str, Any],
    interval_seconds: int,
    until_ms: int,
    store_root: Path,
    series: tuple[tuple[str, str], ...],
    primary_assets: tuple[str, ...],
    coverage_required: float,
    forward_days_required: int,
    window_from_ms: int | None = None,
) -> dict[str, Any]:
    """The operational reading: triggers, observations, days, and the cost of the gaps."""
    rows = sorted(runs, key=lambda row: int(row.get("started_at_ms") or 0))
    first_ms = int(rows[0].get("started_at_ms") or 0) if rows else until_ms
    window_from = int(window_from_ms) if window_from_ms is not None else first_ms
    in_window = [
        row for row in rows if window_from <= int(row.get("started_at_ms") or 0) <= until_ms
    ]
    interval_ms = interval_seconds * 1000

    from trading_bot.research.edge03 import autonomous as AUTO

    # The phase is measured from the registration's own StartBoundary when the host
    # answered, and from the launches otherwise. Both are reported so a reader can see
    # which one the counts used.
    phase_from_registration: int | None = None
    triggers = (evidence.get("task") or {}).get("triggers") or []
    boundary = str((triggers[0] if triggers else {}).get("start_boundary") or "")
    if boundary:
        parsed = _parse_ms(boundary)
        if parsed is not None:
            phase_from_registration = parsed % interval_ms
    launches = [
        int(row.get("started_at_ms") or 0) % interval_ms
        for row in in_window
        if str(row.get("mode")) == "SCHEDULED"
    ]
    phase_source = "registration"
    phase = phase_from_registration
    if phase is None or not launches:
        phase_source = "launches"
        phase = _mode_of(launches) if launches else 0
    instants = expected_instants(
        first_ms=first_ms,
        phase_ms=int(phase),
        interval_ms=interval_ms,
        until_ms=until_ms,
    )

    # One-to-one matching, in order: each tick answers the one instant it falls inside,
    # and each instant is answered by at most one tick. The match is positional rather
    # than searched, because a tick is late for the instant before it and early for the
    # one after it, and only the pair it sits inside is real.
    answered: dict[int, str] = {}
    refused: dict[int, str] = {}
    claimed: set[int] = set()
    for instant in instants:
        for index, row in enumerate(in_window):
            if index in claimed:
                continue
            started = int(row.get("started_at_ms") or 0)
            if not (instant <= started < instant + interval_ms):
                continue
            outcome = str(row.get("outcome"))
            answered[instant] = outcome
            if outcome in REFUSAL_OUTCOMES or outcome == "ALREADY_RUNNING":
                refused[instant] = outcome
            claimed.add(index)
            break

    losses = attributed_losses(
        instants=instants, answered=answered, evidence=evidence, until_ms=until_ms
    )
    consuming = [
        row for row in in_window if str(row.get("outcome")) in AUTO.SLOT_CONSUMING_OUTCOMES
    ]
    observations = [row for row in consuming if str(row.get("outcome")) == "OBSERVED"]

    gaps: list[dict[str, Any]] = []
    for previous, following in pairwise(in_window):
        delta = (
            int(following.get("started_at_ms") or 0) - int(previous.get("started_at_ms") or 0)
        ) / 1000.0
        if delta > AUTO.GAP_WARNING_SECONDS:
            gaps.append(
                {
                    "from_utc": previous.get("finished_at_utc") or previous.get("started_at_utc"),
                    "to_utc": following.get("started_at_utc"),
                    "seconds": round(delta, 3),
                    "missed_instants": max(0, int(delta // interval_seconds) - 1),
                    "severity": "CRITICAL" if delta > AUTO.GAP_CRITICAL_SECONDS else "WARNING",
                }
            )

    durations = [float(row.get("duration_seconds") or 0) for row in in_window]
    outcomes: dict[str, int] = {}
    for row in in_window:
        outcome = str(row.get("outcome"))
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    errors = [row.get("errors") for row in in_window if row.get("errors")]
    stale = sum(1 for row in in_window if row.get("stale_series"))
    daily: list[dict[str, Any]] = []

    day_keys = sorted({str(row.get("day_utc") or _day(row)) for row in in_window})
    for day in day_keys:
        day_rows = [row for row in in_window if str(row.get("day_utc") or _day(row)) == day]
        day_instants = [instant for instant in instants if _day_ms(instant) == day]
        day_durations = [float(row.get("duration_seconds") or 0) for row in day_rows]
        daily.append(
            {
                "day": day,
                "expected_instants": len(day_instants),
                "ticks": len(day_rows),
                "observed": sum(1 for row in day_rows if str(row.get("outcome")) == AUTO.OBSERVED),
                "consuming": sum(
                    1 for row in day_rows if str(row.get("outcome")) in AUTO.SLOT_CONSUMING_OUTCOMES
                ),
                "refused": sum(
                    1 for row in day_rows if str(row.get("outcome")) in REFUSAL_OUTCOMES
                ),
                "new_bars": sum(int(row.get("new_bars") or 0) for row in day_rows),
                "market_requests": sum(int(row.get("market_requests") or 0) for row in day_rows),
                "disk_lowest_gib": _minimum(
                    [
                        (row.get("disk_after") or {}).get("free_gib")
                        for row in day_rows
                        if isinstance((row.get("disk_after") or {}).get("free_gib"), (int, float))
                    ]
                ),
                "median_tick_seconds": _median(day_durations),
                "coverage_of_the_calendar": (
                    round(
                        sum(
                            1
                            for row in day_rows
                            if str(row.get("outcome")) in AUTO.SLOT_CONSUMING_OUTCOMES
                        )
                        / len(day_instants),
                        4,
                    )
                    if day_instants
                    else None
                ),
            }
        )

    coverage = forward_coverage(
        store_root=store_root,
        series=series,
        primary_assets=primary_assets,
        coverage_required=coverage_required,
        forward_days_required=forward_days_required,
    )

    answered_count = len(answered)
    lost = losses["total_lost"]
    return {
        "schema_version": OPERATIONAL_SCHEMA_VERSION,
        "generated_at_utc": _stamp(until_ms),
        "window": {
            "from_utc": _stamp(window_from),
            "to_utc": _stamp(until_ms),
            "hours": round((until_ms - window_from) / 3_600_000, 4),
            "interval_seconds": interval_seconds,
            "phase_ms": int(phase),
            "phase_source": phase_source,
        },
        "levels": {
            "one_triggers_fired": {
                "expected_instants": len(instants),
                "answered_by_a_tick": answered_count,
                "never_answered": lost,
                "causes": losses["causes"],
                "equals_the_whole": answered_count + lost == len(instants),
            },
            "two_observations_made": {
                "slot_consuming_ticks": len(consuming),
                "of_which_observed": len(observations),
                "of_which_no_new_data": len(consuming) - len(observations),
                "fired_and_refused": sum(
                    1 for row in in_window if str(row.get("outcome")) in REFUSAL_OUTCOMES
                ),
                "reading": (
                    "this level counts processes, not instants: an on-demand run of the same task "
                    "produces a real observation and does not answer a scheduled instant"
                ),
            },
            "three_days_admissible": {
                "prospectively_observed_days": coverage["prospectively_observed"],
                "required_days": coverage["required_days"],
                "remaining_days": coverage["remaining_days"],
                "densely_covered_but_backfilled": coverage["densely_covered_but_backfilled"],
                "reading": (
                    "only this level may be compared with an admission criterion, and reaching it "
                    "makes a later decision possible without making it"
                ),
            },
        },
        "losses": losses,
        "outcomes": dict(sorted(outcomes.items())),
        "bars": {
            "new_bars": sum(int(row.get("new_bars") or 0) for row in in_window),
            "missing_bars_reported": sum(int(row.get("missing_bars") or 0) for row in in_window),
            "ticks_reporting_stale_series": stale,
            "market_requests": sum(int(row.get("market_requests") or 0) for row in in_window),
        },
        "continuity": {
            "gaps": gaps,
            "worst_gap_seconds": max((gap["seconds"] for gap in gaps), default=None),
            "highest_severity": max((gap["severity"] for gap in gaps), default=None),
        },
        "latency": {
            "median_tick_seconds": _median(durations),
            "p95_tick_seconds": _percentile(durations, 0.95),
            "maximum_tick_seconds": max(durations, default=None),
            "ticks_over_the_interval": sum(1 for value in durations if value >= interval_seconds),
        },
        "storage": {
            "refused_ticks": sum(
                1 for row in in_window if str(row.get("outcome")) == "DISK_BUDGET_EXCEEDED"
            ),
            "lowest_free_gib": _minimum(
                [
                    (row.get("disk_after") or {}).get("free_gib")
                    for row in in_window
                    if isinstance((row.get("disk_after") or {}).get("free_gib"), (int, float))
                ]
            ),
            "status_counts": _status_counts(in_window),
        },
        "errors": {"ticks_with_errors": len(errors), "detail": errors[:5]},
        "daily": daily,
        "coverage": coverage,
        "invariants": {
            "orders_recorded": sum(1 for row in in_window if row.get("order_sent")),
            "non_hypothetical_ticks": sum(1 for row in in_window if not row.get("hypothetical")),
            "promotions": sorted({str(row.get("promotion")) for row in in_window}),
        },
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }


def _day(row: dict[str, Any]) -> str:
    ms = int(row.get("started_at_ms") or 0)
    return _day_ms(ms)


def _day_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def _mode_of(values: list[int]) -> int:
    counts: dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return 0
    # Rounded to the minute before the mode is taken: the scheduler's own jitter is tens
    # of seconds, and a mode over raw milliseconds would pick a jitter sample and call it
    # the phase.
    rounded: dict[int, int] = {}
    for value, count in counts.items():
        bucket = (value // 60_000) * 60_000
        rounded[bucket] = rounded.get(bucket, 0) + count
    return max(rounded, key=lambda key: (rounded[key], -key))


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 3)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 3)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return round(ordered[index], 3)


def _minimum(values: list[Any]) -> float | None:
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    return round(min(numeric), 4) if numeric else None


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str((row.get("disk_after") or {}).get("status") or "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def forward_coverage(
    *,
    store_root: Path,
    series: tuple[tuple[str, str], ...],
    primary_assets: tuple[str, ...],
    coverage_required: float,
    forward_days_required: int,
) -> dict[str, Any]:
    """The forward coverage, re-derived from the store with the lane's own declared rule.

    The rule is not restated here: :func:`trading_bot.research.edge03.autonomous.prospective_days`
    is the lane's own implementation of "a day counts only if its bars were stored as they
    closed", and re-implementing it would let this reading and the lane's own coverage
    artefact disagree about what an admissible day is.
    """
    from trading_bot.research.edge03.autonomous import prospective_days
    from trading_bot.research.edge03.ingest import ForwardStore

    store = ForwardStore(store_root)
    rows = {f"{timeframe}:{symbol}": store.read(timeframe, symbol) for timeframe, symbol in series}
    timeframes = {f"{timeframe}:{symbol}": timeframe for timeframe, symbol in series}
    reading = prospective_days(
        stored_by_series=rows,
        timeframes=timeframes,
        primary_assets=list(primary_assets),
        coverage=coverage_required,
    )
    reading["required_days"] = forward_days_required
    reading["remaining_days"] = max(
        0, forward_days_required - int(reading["prospectively_observed"])
    )
    reading["reached"] = int(reading["prospectively_observed"]) >= forward_days_required
    reading["reading_rule"] = (
        "a bar counts as prospectively observed only when it was stored within its "
        "timeframe's lag bound of closing; a dense day whose bars arrived later is "
        "backfilled and is not an observation of the future"
    )
    reading["hypothetical"] = True
    reading["order_sent"] = False
    reading["promotion"] = "NONE"
    # Trim the per-day list to the days that matter, so the artefact does not grow with the
    # observation: the ten most recent, and every day that is not INCOMPLETE.
    days = reading.get("days") or []
    interesting = [row for row in days if row.get("class") != "INCOMPLETE"][-15:]
    reading["recent_days"] = interesting
    reading["days_total"] = len(days)
    reading.pop("days", None)
    return reading
