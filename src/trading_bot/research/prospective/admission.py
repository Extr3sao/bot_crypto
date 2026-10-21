"""Day classification: dense is not the same word as observed.

WP-EDGE-04 already stated the rule, and this module applies it without loosening it:

    a day counts only if every series holds at least 90 % of the bars the calendar expects,
    and every one of those bars was stored within its timeframe's lag bound of closing.

Two failure modes are separated here that a single "coverage" number confuses:

* ``DENSE_BUT_BACKFILLED`` — the bars exist and arrived long after their close. History.
* ``INCOMPLETE`` — the bars are not there at all. Absence.

Both are non-admissible, but only the first is dangerous, because a count of rows per day
cannot distinguish it from a day that was genuinely watched. The lag is what distinguishes it,
and the lag is recomputed from the store on every run rather than read from a summary file that
somebody could have regenerated.

A third state exists only in :func:`accumulate`: ``PENDING``. A day is left pending until the
latest bar that could still legitimately arrive has arrived, so that sealing a day can never be
premature. Sealing early is how a backfill would get promoted: the missing bars would be added
later with a lag that disqualifies them, but the attestation would already say the day was
complete.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .store import DEFAULT_LAG_BOUND_MS, INTERVAL_MS, SeriesIndex

__all__ = [
    "ADMISSIBLE",
    "DENSE_BUT_BACKFILLED",
    "INCOMPLETE",
    "PENDING",
    "PROSPECTIVELY_OBSERVED",
    "Accumulation",
    "DayAdmission",
    "accumulate",
    "classify_day",
    "expected_bars",
    "intersection_epoch",
    "utc_date",
]

PROSPECTIVELY_OBSERVED = "PROSPECTIVELY_OBSERVED"
DENSE_BUT_BACKFILLED = "DENSE_BUT_BACKFILLED"
INCOMPLETE = "INCOMPLETE"
PENDING = "PENDING"

#: The only classification that may be counted toward a confirmatory day requirement.
ADMISSIBLE = (PROSPECTIVELY_OBSERVED,)

DAY_MS = 86_400_000


def expected_bars(interval: str) -> int:
    """Bars a UTC calendar day should hold for this timeframe."""
    try:
        span = INTERVAL_MS[interval]
    except KeyError as error:
        raise ValueError(f"unknown interval {interval!r}") from error
    if DAY_MS % span:
        raise ValueError(f"{interval} does not divide a UTC day")
    return DAY_MS // span


def utc_date(value: str | datetime | date) -> date:
    """A date from ``YYYY-MM-DD``, an ISO timestamp, or a date. Naive timestamps are refused."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("a naive datetime has no calendar day that can be trusted")
        return value.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        return utc_date(datetime.fromisoformat(text.replace("Z", "+00:00")))
    return date.fromisoformat(text[:10])


@dataclass(frozen=True, slots=True)
class SeriesDay:
    """One series' contribution to one day."""

    interval: str
    asset: str
    expected: int
    stored: int
    prospective: int
    byte_end: int | None

    @property
    def stored_coverage(self) -> float:
        return round(self.stored / self.expected, 6) if self.expected else 0.0

    @property
    def prospective_coverage(self) -> float:
        return round(self.prospective / self.expected, 6) if self.expected else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "interval": self.interval,
            "expected_bars": self.expected,
            "stored_bars": self.stored,
            "prospectively_observed_bars": self.prospective,
            "stored_coverage": self.stored_coverage,
            "prospective_coverage": self.prospective_coverage,
            "byte_end": self.byte_end,
        }


@dataclass(frozen=True, slots=True)
class DayAdmission:
    """The verdict on one UTC day, with the per-series arithmetic that produced it."""

    day: str
    classification: str
    series: tuple[SeriesDay, ...]
    coverage_required: float
    lag_bounds: Mapping[str, int] = field(default_factory=dict)

    @property
    def admissible(self) -> bool:
        return self.classification in ADMISSIBLE

    @property
    def worst_prospective_coverage(self) -> float:
        return min((row.prospective_coverage for row in self.series), default=0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "class": self.classification,
            "admissible": self.admissible,
            "coverage_required": self.coverage_required,
            "worst_prospective_coverage": self.worst_prospective_coverage,
            "lag_bounds_ms": dict(self.lag_bounds),
            "series": {
                f"{row.interval}:{row.asset}": row.as_dict() for row in self.series
            },
        }


def classify_day(
    day: str,
    indexes: Sequence[SeriesIndex],
    *,
    lag_bounds: Mapping[str, int] | None = None,
    coverage_required: float = 0.90,
) -> DayAdmission:
    """Classify one day from the store alone.

    ``indexes`` is the complete set of series the experiment declares. A series with no bar
    for the day is reported as zero stored bars, not skipped: skipping a missing series is how
    a two-asset day gets counted as a three-asset one.
    """
    if not indexes:
        raise ValueError("a day cannot be classified against no series")
    bounds = dict(DEFAULT_LAG_BOUND_MS if lag_bounds is None else lag_bounds)
    rows: list[SeriesDay] = []
    for index in indexes:
        expected = expected_bars(index.interval)
        try:
            bound = int(bounds[index.interval])
        except KeyError as error:
            raise ValueError(f"no lag bound declared for {index.interval!r}") from error
        bars = index.bars_on(day)
        prospective = sum(1 for bar in bars if bar.closed and 0 <= bar.lag_ms <= bound)
        rows.append(
            SeriesDay(
                interval=index.interval,
                asset=index.asset,
                expected=expected,
                stored=len(bars),
                prospective=prospective,
                byte_end=index.day_end(day),
            )
        )

    dense = all(row.stored_coverage >= coverage_required for row in rows)
    observed = all(row.prospective_coverage >= coverage_required for row in rows)
    if not dense:
        classification = INCOMPLETE
    elif observed:
        classification = PROSPECTIVELY_OBSERVED
    else:
        classification = DENSE_BUT_BACKFILLED
    return DayAdmission(
        day=day,
        classification=classification,
        series=tuple(rows),
        coverage_required=coverage_required,
        lag_bounds={key: bounds[key] for key in sorted({row.interval for row in rows})},
    )


def sealable_through(now: datetime, lag_bounds: Mapping[str, int]) -> date:
    """The last day whose every bar can no longer legitimately arrive late.

    The cutoff is ``now - (lag_bound + interval)`` measured from the end of the day, so a bar
    that closes at 23:00 and is still allowed two hours of lag must reach us by 01:00 the next
    day. Until then the day is pending, and pending days are not counted either way.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if not lag_bounds:
        raise ValueError("lag_bounds must not be empty")
    longest = max(
        int(bound) + _interval_ms(interval) for interval, bound in lag_bounds.items()
    )
    # A day D is sealable once ``end_of(D) + longest_lag <= now``. Today's end is in the future, so
    # today is never sealable, which is the property that stops a seal from being premature.
    limit = now.astimezone(UTC) - timedelta(milliseconds=longest) - timedelta(days=1)
    return limit.date()


def intersection_epoch(series_epochs: Mapping[str, str]) -> str:
    """The first day on which *every* declared series can have been observed.

    A 1h lane that reaches back to 2026-03-01 and a 15m lane that starts 2026-10-07 do not share
    235 days of evidence; they share 15. Taking the maximum is the only epoch under which a day
    is admissible for the whole declared set, and stating it explicitly is what stops a
    single-series figure from being quoted for a multi-series experiment.
    """
    if not series_epochs:
        raise ValueError("series_epochs must not be empty")
    return max(utc_date(value) for value in series_epochs.values()).isoformat()


def _interval_ms(interval: str) -> int:
    if interval not in INTERVAL_MS:
        raise ValueError(f"unknown interval {interval!r}")
    return INTERVAL_MS[interval]


@dataclass(frozen=True, slots=True)
class Accumulation:
    """How far a declared day requirement has actually got, and when it would finish."""

    epoch: str
    as_of_utc: str
    target_days: int
    coverage_required: float
    series: tuple[str, ...]
    days: tuple[DayAdmission, ...]
    pending: tuple[str, ...]

    @property
    def counts(self) -> dict[str, int]:
        counts = {
            PROSPECTIVELY_OBSERVED: 0,
            DENSE_BUT_BACKFILLED: 0,
            INCOMPLETE: 0,
            PENDING: len(self.pending),
        }
        for day in self.days:
            counts[day.classification] = counts.get(day.classification, 0) + 1
        return counts

    @property
    def admissible_days(self) -> tuple[str, ...]:
        return tuple(day.day for day in self.days if day.admissible)

    @property
    def admissible(self) -> int:
        return len(self.admissible_days)

    @property
    def remaining(self) -> int:
        return max(0, self.target_days - self.admissible)

    @property
    def satisfied(self) -> bool:
        return self.remaining == 0

    def projection(self) -> dict[str, Any]:
        """When the requirement would be met at the rate actually observed so far.

        ``None`` is a real answer: a rate of zero admissible days per elapsed day never
        finishes, and reporting a date for it would be arithmetic dressed as a forecast.
        """
        settled = len(self.days)
        if not self.admissible:
            return {"rate_admissible_per_day": 0.0, "projected_completion_utc": None,
                    "readable": "no day has been admitted yet, so there is no rate to project"}
        rate = self.admissible / settled
        if rate <= 0:
            return {"rate_admissible_per_day": 0.0, "projected_completion_utc": None,
                    "readable": "zero admissible days in the settled window"}
        needed = self.remaining / rate
        finish = datetime.fromisoformat(self.as_of_utc.replace("Z", "+00:00")) + timedelta(days=needed)
        return {
            "rate_admissible_per_day": round(rate, 6),
            "projected_completion_utc": finish.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "readable": (
                f"{self.admissible} admissible of {settled} settled days; at that rate "
                f"{self.remaining} more need {needed:.1f} days"
            ),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "epoch": self.epoch,
            "as_of_utc": self.as_of_utc,
            "target_days": self.target_days,
            "coverage_required": self.coverage_required,
            "series": list(self.series),
            "counts": self.counts,
            "admissible_days": list(self.admissible_days),
            "admissible": self.admissible,
            "remaining": self.remaining,
            "satisfied": self.satisfied,
            "pending_days": list(self.pending),
            "projection": self.projection(),
            "days": [day.as_dict() for day in self.days],
        }


def accumulate(
    *,
    indexes: Sequence[SeriesIndex],
    epoch: str | date,
    now: datetime,
    target_days: int,
    lag_bounds: Mapping[str, int] | None = None,
    coverage_required: float = 0.90,
) -> Accumulation:
    """Classify every day from ``epoch`` to the last sealable day, and count the admissible ones."""
    if target_days < 1:
        raise ValueError("target_days must be >= 1")
    if not indexes:
        raise ValueError("nothing to accumulate")
    bounds = dict(DEFAULT_LAG_BOUND_MS if lag_bounds is None else lag_bounds)
    first = utc_date(epoch)
    cutoff = sealable_through(now, bounds)
    declared = tuple(f"{index.interval}:{index.asset}" for index in indexes)
    days: list[DayAdmission] = []
    pending: list[str] = []
    cursor = first
    while cursor <= now.astimezone(UTC).date():
        label = cursor.isoformat()
        if cursor > cutoff:
            pending.append(label)
        else:
            days.append(classify_day(label, indexes, lag_bounds=bounds,
                                     coverage_required=coverage_required))
        cursor += timedelta(days=1)
    return Accumulation(
        epoch=first.isoformat(),
        as_of_utc=now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        target_days=target_days,
        coverage_required=coverage_required,
        series=declared,
        days=tuple(days),
        pending=tuple(pending),
    )
