"""Canonical POC01 observation metrics (DEF-POC01-OBS-006 repair).

POC01-RECOVERY-AND-EVIDENCE-01 (observation/reporting semantics ONLY —
no trading behavior change; raw observations stay immutable).

Canonical invariants (section 1 of the checkpoint):

- COMPLETED_VALID_DAYS = count of FINALIZED + COUNTED + VALID UTC days.
  Validity MUST NOT depend on the number of trades: a day is VALID when it
  was observed under the preregistered contract (finalized, counted, no
  day-invalidating outage). Zero-trade valid days count.
- DAYS_GE_3 = count of valid completed days with trades >= 3 (frequency is
  a SEPARATE metric).
- PERCENT_DAYS_GE_3 = DAYS_GE_3 / COMPLETED_VALID_DAYS (0 when no valid days).
- Burn-in days and the current partial day are excluded from everything.
- Coverage is ADDITIONAL evidence (expected/observed/downtime minutes,
  ratio, outage intervals) — it never redefines validity and does not
  introduce a new threshold.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "CoverageRecord",
    "DayStatus",
    "FrequencyKpis",
    "ObservationDay",
    "build_daily_table",
    "compute_frequency_kpis",
]

BURN_IN_DATE = "2026-09-06"  # preregistered; excluded from everything


class DayStatus:
    COUNTED = "COUNTED"
    BURN_IN = "BURN_IN"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True, slots=True)
class CoverageRecord:
    """Coverage evidence for one UTC day (never a validity override)."""

    expected_observation_minutes: float
    observed_minutes: float
    downtime_minutes: float
    coverage_ratio: float  # observed / expected (0..1)
    scans_expected: float | None  # None when cadence not preregistered
    scans_observed: int
    provider_failures: int
    data_gaps: int
    stale_events: int
    future_events: int
    runtime_outage_intervals: tuple[tuple[str, str], ...]  # (start_iso, end_iso)


@dataclass(frozen=True, slots=True)
class ObservationDay:
    """One UTC day row of the canonical finalized daily table."""

    date: str
    counted: bool  # False for BURN_IN and PARTIAL days
    status: str  # COUNTED / BURN_IN / PARTIAL
    finalized: bool
    valid: bool  # preregistered observation contract only (NOT trade count)
    validity_reason: str
    coverage: CoverageRecord
    scans: int
    proposals: int
    selected: int
    risk_accepts: int
    risk_rejects: int
    paper_opens: int
    paper_closes: int
    trades: int
    realized_pnl: float
    trades_ge_3: bool
    provider_failures: int
    runtime_downtime_minutes: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "status": self.status,
            "counted": self.counted,
            "finalized": self.finalized,
            "valid": self.valid,
            "validity_reason": self.validity_reason,
            "coverage": {
                "expected_observation_minutes": self.coverage.expected_observation_minutes,
                "observed_minutes": self.coverage.observed_minutes,
                "downtime_minutes": self.coverage.downtime_minutes,
                "coverage_ratio": self.coverage.coverage_ratio,
                "scans_expected": self.coverage.scans_expected,
                "scans_observed": self.coverage.scans_observed,
                "provider_failures": self.coverage.provider_failures,
                "data_gaps": self.coverage.data_gaps,
                "stale_events": self.coverage.stale_events,
                "future_events": self.coverage.future_events,
                "runtime_outage_intervals": [
                    [s, e] for s, e in self.coverage.runtime_outage_intervals
                ],
            },
            "activity": {
                "scans": self.scans,
                "proposals": self.proposals,
                "selected": self.selected,
                "risk_accepts": self.risk_accepts,
                "risk_rejects": self.risk_rejects,
                "paper_opens": self.paper_opens,
                "paper_closes": self.paper_closes,
                "trades": self.trades,
                "realized_pnl": self.realized_pnl,
                "trades_ge_3": self.trades_ge_3,
                "provider_failures": self.provider_failures,
            },
            "runtime_downtime_minutes": self.runtime_downtime_minutes,
        }


@dataclass(frozen=True, slots=True)
class FrequencyKpis:
    completed_valid_days: int
    days_ge_3: int
    percent_days_ge_3: float
    total_trades: int
    avg_trades_per_valid_day: float


def compute_frequency_kpis(days: list[ObservationDay]) -> FrequencyKpis:
    """KPIs over FINALIZED + COUNTED + VALID days only (zero-trade days count)."""
    valid = [
        d for d in days if d.finalized and d.counted and d.valid
    ]
    completed = len(valid)
    days_ge_3 = sum(1 for d in valid if d.trades >= 3)
    total_trades = sum(d.trades for d in valid)
    return FrequencyKpis(
        completed_valid_days=completed,
        days_ge_3=days_ge_3,
        percent_days_ge_3=(days_ge_3 / completed) if completed else 0.0,
        total_trades=total_trades,
        avg_trades_per_valid_day=(total_trades / completed) if completed else 0.0,
    )


def build_daily_table(
    *,
    campaign_start: str,
    current_utc_day: str,
    finalized_days: dict[str, dict[str, Any]],
    outage_intervals: Sequence[tuple[str, str]],
    partial_day_reason: str = "current UTC day; observation still in progress",
) -> list[ObservationDay]:
    """Assemble the canonical table from campaign start through today.

    ``finalized_days`` maps date -> activity payload (scans, trades, pnl, ...,
    valid, validity_reason). Days without a finalized entry are PARTIAL.
    ``outage_intervals`` is a FLAT list of (start_iso, end_iso) outages;
    each day reports only its own share (intervals are clipped at UTC
    midnight, so a cross-midnight outage is split honestly per day).
    """
    start = datetime.fromisoformat(campaign_start).replace(tzinfo=UTC)
    today = datetime.fromisoformat(current_utc_day).replace(tzinfo=UTC)
    all_outages = tuple(outage_intervals)
    table: list[ObservationDay] = []
    day = start
    while day <= today:
        date = day.strftime("%Y-%m-%d")
        outages = tuple(o for o in all_outages if _overlaps_day(o, date))
        downtime_min = _outage_minutes(all_outages, date)
        if date == BURN_IN_DATE:
            table.append(
                ObservationDay(
                    date=date,
                    counted=False,
                    status=DayStatus.BURN_IN,
                    finalized=True,
                    valid=False,
                    validity_reason="preregistered burn-in day; excluded from all KPIs",
                    coverage=_coverage_for(date, 0.0, downtime_min, outages, 0),
                    scans=0, proposals=0, selected=0, risk_accepts=0, risk_rejects=0,
                    paper_opens=0, paper_closes=0, trades=0, realized_pnl=0.0,
                    trades_ge_3=False, provider_failures=0,
                    runtime_downtime_minutes=downtime_min,
                )
            )
        elif date in finalized_days:
            payload = finalized_days[date]
            valid = bool(payload.get("valid", False))
            reason = str(payload.get("validity_reason", ""))
            table.append(
                ObservationDay(
                    date=date,
                    counted=True,
                    status=DayStatus.COUNTED,
                    finalized=True,
                    valid=valid,
                    validity_reason=reason,
                    coverage=_coverage_for(
                        date,
                        float(payload.get("scans", 0)),
                        downtime_min,
                        outages,
                        int(payload.get("provider_failures", 0)),
                    ),
                    scans=int(payload.get("scans", 0)),
                    proposals=int(payload.get("proposals", 0)),
                    selected=int(payload.get("selected", 0)),
                    risk_accepts=int(payload.get("risk_accepts", 0)),
                    risk_rejects=int(payload.get("risk_rejects", 0)),
                    paper_opens=int(payload.get("paper_opens", 0)),
                    paper_closes=int(payload.get("paper_closes", 0)),
                    trades=int(payload.get("trades", 0)),
                    realized_pnl=float(payload.get("realized_pnl", 0.0)),
                    trades_ge_3=int(payload.get("trades", 0)) >= 3,
                    provider_failures=int(payload.get("provider_failures", 0)),
                    runtime_downtime_minutes=downtime_min,
                )
            )
        else:
            table.append(
                ObservationDay(
                    date=date,
                    counted=False,
                    status=DayStatus.PARTIAL,
                    finalized=False,
                    valid=False,
                    validity_reason=partial_day_reason,
                    coverage=_coverage_for(date, 0.0, downtime_min, outages, 0),
                    scans=0, proposals=0, selected=0, risk_accepts=0, risk_rejects=0,
                    paper_opens=0, paper_closes=0, trades=0, realized_pnl=0.0,
                    trades_ge_3=False, provider_failures=0,
                    runtime_downtime_minutes=downtime_min,
                )
            )
        day = datetime.fromtimestamp(day.timestamp() + 86400, tz=UTC)
    return table


def _overlaps_day(outage: tuple[str, str], date: str) -> bool:
    day_start = datetime.fromisoformat(f"{date}T00:00:00+00:00")
    day_end = datetime.fromisoformat(f"{date}T23:59:59.999999+00:00")
    s = datetime.fromisoformat(outage[0])
    e = datetime.fromisoformat(outage[1])
    return s <= day_end and e >= day_start


def _outage_minutes(outages: tuple[tuple[str, str], ...], date: str) -> float:
    """Downtime within ONE UTC day: intervals are clipped at midnight so
    each day reports only its own outage share (honest per-day coverage)."""
    day_start = datetime.fromisoformat(f"{date}T00:00:00+00:00")
    day_end = datetime.fromisoformat(f"{date}T23:59:59.999999+00:00")
    total = 0.0
    for start_iso, end_iso in outages:
        s = datetime.fromisoformat(start_iso)
        e = datetime.fromisoformat(end_iso)
        clipped_start = max(s, day_start)
        clipped_end = min(e, day_end)
        if clipped_end > clipped_start:
            total += (clipped_end - clipped_start).total_seconds() / 60.0
    return total


def _coverage_for(
    date: str,
    scans: float,
    downtime_min: float,
    outages: tuple[tuple[str, str], ...],
    provider_failures: int,
) -> CoverageRecord:
    expected = 1440.0  # full UTC day under continuous observation
    observed = max(0.0, expected - downtime_min)
    return CoverageRecord(
        expected_observation_minutes=expected,
        observed_minutes=observed,
        downtime_minutes=downtime_min,
        coverage_ratio=observed / expected if expected else 0.0,
        scans_expected=None,  # no scan cadence is preregistered; not invented
        scans_observed=int(scans),
        provider_failures=provider_failures,
        data_gaps=0,
        stale_events=0,
        future_events=0,
        runtime_outage_intervals=tuple(outages),
    )
