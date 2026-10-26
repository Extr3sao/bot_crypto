"""RFC-030 continuation §4/§9/§10/§12/§13 — short-borrow data contract.

This module formalises what a *shortable* instrument needs before it can be
economically evaluated, and — more importantly — what it must do when that data is
missing. The frozen EXP-ARP-023 short leg is ``MARGIN_SPOT``: it needs historical,
point-in-time **borrow availability** and **borrow rate** evidence. That evidence
does not exist in the project's 1d USDT corpus.

Two rules are enforced here:

* **UNKNOWN is not zero.** A missing borrow rate or an unknown availability is
  ``UNKNOWN``/``BLOCKED``; it is never coerced to ``0`` (§4, §12, §23).
* **Availability gates execution.** ``UNKNOWN`` availability → ``NO_SHORT``. The
  only escape is an explicitly labelled, non-certifiable exploratory scenario
  (§13), which can never unlock a G3 promotion.

The module is research/PAPER only, deterministic, no clock, no RNG, no network.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "BorrowAvailability",
    "BorrowDataQuality",
    "BorrowGateDecision",
    "BorrowRatePeriod",
    "CoverageReport",
    "ShortBorrowObservation",
    "borrow_availability_gate",
    "coverage_report",
    "validate_pit",
]

MS_PER_DAY = 86_400_000


class BorrowAvailability(StrEnum):
    """Whether the asset could actually be borrowed at the observation time."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    #: No authoritative evidence exists. Distinct from UNAVAILABLE, and *not* 0.
    UNKNOWN = "UNKNOWN"


class BorrowRatePeriod(StrEnum):
    """The time base of a borrow rate, kept explicit so unit conversion is safe."""

    HOURLY = "HOURLY"
    DAILY = "DAILY"
    ANNUAL = "ANNUAL"


class BorrowDataQuality(StrEnum):
    """How the observation was obtained (drives the authority ranking, §2)."""

    OFFICIAL_EXCHANGE_HISTORICAL = "OFFICIAL_EXCHANGE_HISTORICAL"
    OFFICIAL_API_LIVE = "OFFICIAL_API_LIVE"
    INSTITUTIONAL_PROVIDER = "INSTITUTIONAL_PROVIDER"
    ACADEMIC_ARCHIVE = "ACADEMIC_ARCHIVE"
    THIRD_PARTY_AGGREGATOR = "THIRD_PARTY_AGGREGATOR"
    SCRAPE_APPROXIMATION = "SCRAPE_APPROXIMATION"
    UNKNOWN = "UNKNOWN"


class BorrowGateDecision(StrEnum):
    """The result of the availability gate (§12)."""

    SHORT_ALLOWED = "SHORT_ALLOWED"
    NO_SHORT_DATA_BLOCKED = "NO_SHORT_DATA_BLOCKED"
    NO_SHORT_UNAVAILABLE = "NO_SHORT_UNAVAILABLE"
    #: Exploratory only — can never unlock a certified G3 result (§13).
    NON_CERTIFIABLE = "NON_CERTIFIABLE"


@dataclass(frozen=True, slots=True)
class ShortBorrowObservation:
    """§4 — one point-in-time short-borrow observation.

    Not every field is populated by every source. The distinction that matters is
    ``UNKNOWN`` vs a real value: ``borrow_rate is None`` means the rate is
    **unknown**, never ``0``; ``available is BorrowAvailability.UNKNOWN`` means
    availability is **unknown**, never ``AVAILABLE``.

    ``pit_valid`` records whether the observation was actually knowable at
    ``timestamp`` (``retrieved_at <= timestamp`` and no later revision). A record
    with ``pit_valid=False`` is rejected by :func:`validate_pit`.
    """

    asset: str
    venue: str
    instrument: str
    timestamp: int
    available: BorrowAvailability = BorrowAvailability.UNKNOWN
    borrow_rate: float | None = None
    rate_period: BorrowRatePeriod = BorrowRatePeriod.DAILY
    borrow_limit: float | None = None
    source_id: str = "UNKNOWN"
    source_timestamp: int = 0
    retrieved_at: int = 0
    data_quality: BorrowDataQuality = BorrowDataQuality.UNKNOWN
    pit_valid: bool = False

    @property
    def rate_is_known(self) -> bool:
        return self.borrow_rate is not None

    @property
    def availability_is_known(self) -> bool:
        return self.available is not BorrowAvailability.UNKNOWN

    @property
    def is_complete(self) -> bool:
        """Both the availability *and* the rate are authoritative (not UNKNOWN)."""
        return self.availability_is_known and self.rate_is_known

    def rate_per_day_bps(self) -> float | None:
        """Convert the borrow rate to bps/day. ``None`` when the rate is unknown."""
        if self.borrow_rate is None:
            return None
        if self.rate_period is BorrowRatePeriod.DAILY:
            return self.borrow_rate
        if self.rate_period is BorrowRatePeriod.HOURLY:
            return self.borrow_rate * 24.0
        # ANNUAL: the convention is a 365-day year (Binance margin uses 365).
        return self.borrow_rate / 365.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "venue": self.venue,
            "instrument": self.instrument,
            "timestamp": self.timestamp,
            "available": self.available.value,
            "borrow_rate": self.borrow_rate,
            "rate_period": self.rate_period.value,
            "borrow_limit": self.borrow_limit,
            "source_id": self.source_id,
            "source_timestamp": self.source_timestamp,
            "retrieved_at": self.retrieved_at,
            "data_quality": self.data_quality.value,
            "pit_valid": self.pit_valid,
            "is_complete": self.is_complete,
        }


@dataclass(frozen=True, slots=True)
class PITViolation:
    """One reason an observation may not be used at a decision time (§9)."""

    reason: str
    detail: str
    asset: str = ""


def validate_pit(
    observations: Sequence[ShortBorrowObservation],
    decision_time: int,
) -> list[PITViolation]:
    """Return every PIT violation for ``observations`` at ``decision_time``.

    Empty list == clean. Non-empty == the caller must refuse to use the data.
    The checks are deliberately conservative: an observation is only usable when
    it was *retrieved* no later than the decision and declares ``pit_valid``.
    """
    violations: list[PITViolation] = []
    seen: set[tuple[str, int]] = set()
    for obs in observations:
        key = (obs.asset, obs.timestamp)
        if key in seen:
            violations.append(
                PITViolation("duplicate_observation", f"{obs.asset}@{obs.timestamp}", obs.asset)
            )
        seen.add(key)
        if obs.timestamp > decision_time:
            violations.append(
                PITViolation(
                    "future_borrow_observation",
                    f"observation {obs.timestamp} > decision {decision_time}",
                    obs.asset,
                )
            )
        if obs.retrieved_at and obs.retrieved_at > decision_time:
            violations.append(
                PITViolation(
                    "future_retrieval",
                    f"retrieved {obs.retrieved_at} > decision {decision_time}",
                    obs.asset,
                )
            )
        if not obs.pit_valid:
            violations.append(
                PITViolation(
                    "backfilled_status_leak",
                    "observation is not marked pit_valid (revision/backfill risk)",
                    obs.asset,
                )
            )
        if obs.source_timestamp and obs.availability_is_known and not obs.rate_is_known:
            # A rate that only became known later than the decision is a leak.
            violations.append(
                PITViolation(
                    "future_availability_leak",
                    "availability declared without a contemporaneous rate",
                    obs.asset,
                )
            )
    return violations


def borrow_availability_gate(
    observations: Sequence[ShortBorrowObservation],
    *,
    decision_time: int,
    require_rate: bool = True,
) -> BorrowGateDecision:
    """§12 — decide whether a short may proceed at ``decision_time``.

    Fail-closed: any missing evidence blocks. ``UNKNOWN`` availability is *never*
    treated as ``AVAILABLE``. A rate is required when ``require_rate`` (the default
    for an economic evaluation).
    """
    relevant = [o for o in observations if o.timestamp <= decision_time]
    if not relevant:
        return BorrowGateDecision.NO_SHORT_DATA_BLOCKED
    if validate_pit(relevant, decision_time):
        return BorrowGateDecision.NO_SHORT_DATA_BLOCKED
    latest = max(relevant, key=lambda o: o.timestamp)
    if latest.available is BorrowAvailability.UNAVAILABLE:
        return BorrowGateDecision.NO_SHORT_UNAVAILABLE
    if latest.available is BorrowAvailability.UNKNOWN:
        return BorrowGateDecision.NO_SHORT_DATA_BLOCKED
    if require_rate and not latest.rate_is_known:
        return BorrowGateDecision.NO_SHORT_DATA_BLOCKED
    return BorrowGateDecision.SHORT_ALLOWED


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """§10 — coverage of a required window by an observation set."""

    required_start: int
    required_end: int
    required_assets: int
    covered_assets: int
    covered_days: int
    required_days: int
    missing_days: int
    missing_observations: int
    duplicate_observations: int
    coverage_percent: float
    assets_missing: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_viable(self) -> bool:
        """A small fraction of the period is never declared viable (§10)."""
        return self.coverage_percent >= 90.0 and not self.assets_missing

    def as_dict(self) -> dict[str, Any]:
        return {
            "required_start": self.required_start,
            "required_end": self.required_end,
            "required_assets": self.required_assets,
            "covered_assets": self.covered_assets,
            "covered_days": self.covered_days,
            "required_days": self.required_days,
            "missing_days": self.missing_days,
            "missing_observations": self.missing_observations,
            "duplicate_observations": self.duplicate_observations,
            "coverage_percent": self.coverage_percent,
            "assets_missing": list(self.assets_missing),
            "is_viable": self.is_viable,
        }


def coverage_report(
    observations: Iterable[ShortBorrowObservation],
    *,
    required_start: int,
    required_end: int,
    required_assets: Sequence[str],
) -> CoverageReport:
    """Compute coverage of ``[required_start, required_end]`` per asset.

    A day is *covered* only when an asset has an observation whose timestamp falls
    on that day **and** the observation is complete (availability + rate known).
    """
    obs = list(observations)
    required_days = max(0, (required_end - required_start) // MS_PER_DAY)
    covered: dict[str, set[int]] = {a: set() for a in required_assets}
    seen: set[tuple[str, int]] = set()
    duplicates = 0
    for o in obs:
        key = (o.asset, o.timestamp)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        if o.asset in covered and o.is_complete and required_start <= o.timestamp <= required_end:
            day = (o.timestamp - required_start) // MS_PER_DAY
            covered[o.asset].add(day)

    assets_missing = tuple(a for a in required_assets if not covered[a])
    covered_assets = sum(1 for a in required_assets if covered[a])
    covered_days = sum(len(days) for days in covered.values())
    total_expected = max(1, required_days * max(1, len(required_assets)))
    missing_observations = total_expected - covered_days
    coverage_percent = 100.0 * covered_days / total_expected
    missing_days = max(0, required_days - math.floor(covered_days / max(1, len(required_assets))))
    return CoverageReport(
        required_start=required_start,
        required_end=required_end,
        required_assets=len(required_assets),
        covered_assets=covered_assets,
        covered_days=covered_days,
        required_days=required_days,
        missing_days=missing_days,
        missing_observations=missing_observations,
        duplicate_observations=duplicates,
        coverage_percent=coverage_percent,
        assets_missing=assets_missing,
    )
