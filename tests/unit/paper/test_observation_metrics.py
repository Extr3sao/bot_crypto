"""Tests: canonical POC01 observation metrics (DEF-POC01-OBS-006 repair)."""

from __future__ import annotations

import pytest

from trading_bot.paper.observation_metrics import (
    BURN_IN_DATE,
    ObservationDay,
    build_daily_table,
    compute_frequency_kpis,
)


def _day_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "scans": 24,
        "proposals": 0,
        "selected": 0,
        "risk_accepts": 0,
        "risk_rejects": 0,
        "paper_opens": 0,
        "paper_closes": 0,
        "trades": 0,
        "realized_pnl": 0.0,
        "valid": True,
        "validity_reason": "finalized under preregistered observation contract",
        "provider_failures": 0,
    }
    base.update(overrides)
    return base


class TestValidDaySemantics:
    def test_zero_trade_valid_day_counts(self) -> None:
        """THE DEF-POC01-OBS-006 invariant: validity is NOT trade-coupled."""
        days = build_daily_table(
            campaign_start="2026-09-07",
            current_utc_day="2026-09-08",
            finalized_days={
                "2026-09-07": _day_payload(trades=0),  # D1: valid, zero trades
            },
            outage_intervals={},
        )
        d1 = next(d for d in days if d.date == "2026-09-07")
        assert d1.valid is True
        assert d1.trades == 0
        kpis = compute_frequency_kpis(days)
        assert kpis.completed_valid_days == 1  # zero-trade valid day COUNTS
        assert kpis.days_ge_3 == 0  # frequency is SEPARATE
        assert kpis.percent_days_ge_3 == 0.0
        assert kpis.total_trades == 0
        assert kpis.avg_trades_per_valid_day == 0.0

    def test_validity_independent_of_trade_count(self) -> None:
        days = build_daily_table(
            campaign_start="2026-09-07",
            current_utc_day="2026-09-10",
            finalized_days={
                "2026-09-07": _day_payload(trades=0, valid=True),
                "2026-09-08": _day_payload(trades=5, valid=True),
                "2026-09-09": _day_payload(trades=1, valid=True),
            },
            outage_intervals={},
        )
        kpis = compute_frequency_kpis(days)
        assert kpis.completed_valid_days == 3
        assert kpis.days_ge_3 == 1  # only 09-08 has >= 3
        assert kpis.percent_days_ge_3 == 1.0 / 3.0
        assert kpis.total_trades == 6
        assert kpis.avg_trades_per_valid_day == 2.0

    def test_invalid_day_excluded_but_zero_trades_still_ok(self) -> None:
        days = build_daily_table(
            campaign_start="2026-09-07",
            current_utc_day="2026-09-08",
            finalized_days={
                "2026-09-07": _day_payload(
                    trades=0,
                    valid=False,
                    validity_reason="day-invalidating outage",
                ),
            },
            outage_intervals={},
        )
        kpis = compute_frequency_kpis(days)
        assert kpis.completed_valid_days == 0
        assert kpis.days_ge_3 == 0


class TestExclusions:
    def test_burn_in_excluded(self) -> None:
        assert BURN_IN_DATE == "2026-09-06"
        days = build_daily_table(
            campaign_start="2026-09-06",
            current_utc_day="2026-09-07",
            finalized_days={
                "2026-09-06": _day_payload(trades=9, valid=True),  # even if busy
                "2026-09-07": _day_payload(trades=0, valid=True),
            },
            outage_intervals={},
        )
        burn = next(d for d in days if d.date == "2026-09-06")
        assert burn.status == "BURN_IN"
        assert burn.counted is False
        assert burn.valid is False
        kpis = compute_frequency_kpis(days)
        assert kpis.completed_valid_days == 1  # only 09-07

    def test_partial_day_excluded(self) -> None:
        days = build_daily_table(
            campaign_start="2026-09-07",
            current_utc_day="2026-09-08",
            finalized_days={"2026-09-07": _day_payload(trades=0, valid=True)},
            outage_intervals={},
        )
        partial = next(d for d in days if d.date == "2026-09-08")
        assert partial.status == "PARTIAL"
        assert partial.finalized is False
        assert partial.counted is False
        kpis = compute_frequency_kpis(days)
        assert kpis.completed_valid_days == 1


class TestCoverageAccounting:
    def test_downtime_recorded_not_hidden(self) -> None:
        days = build_daily_table(
            campaign_start="2026-09-08",
            current_utc_day="2026-09-08",
            finalized_days={},
            outage_intervals=[("2026-09-08T17:12:49+00:00", "2026-09-08T23:59:59+00:00")],
        )
        row = days[0]
        assert row.status == "PARTIAL"
        cov = row.coverage
        assert cov.downtime_minutes > 400  # ~6.8h of the outage within 09-08
        assert cov.coverage_ratio < 0.72
        assert cov.runtime_outage_intervals
        assert cov.scans_expected is None  # no cadence preregistered; not invented

    def test_coverage_is_evidence_not_validity(self) -> None:
        # A day with heavy downtime but finalized+valid stays valid; coverage
        # is reported separately (no new threshold invented).
        days = build_daily_table(
            campaign_start="2026-09-07",
            current_utc_day="2026-09-08",
            finalized_days={
                "2026-09-07": _day_payload(
                    trades=0,
                    valid=True,
                    validity_reason="finalized; outage did not invalidate day",
                ),
            },
            outage_intervals=[("2026-09-07T00:00:00+00:00", "2026-09-07T06:00:00+00:00")],
        )
        d1 = days[0]
        assert d1.valid is True
        assert d1.coverage.downtime_minutes == 360.0
        assert d1.coverage.coverage_ratio == 0.75
        kpis = compute_frequency_kpis(days)
        assert kpis.completed_valid_days == 1

    def test_outage_split_across_midnight(self) -> None:
        days = build_daily_table(
            campaign_start="2026-09-08",
            current_utc_day="2026-09-09",
            finalized_days={},
            outage_intervals=[("2026-09-08T17:12:49+00:00", "2026-09-09T08:28:07+00:00")],
        )
        by_date = {d.date: d for d in days}
        # Outage clipped per-day: 09-08 gets ~6.79h, 09-09 gets ~8.47h.
        d8 = by_date["2026-09-08"].coverage.downtime_minutes
        d9 = by_date["2026-09-09"].coverage.downtime_minutes
        assert 400 < d8 < 410  # 17:12:49 -> 24:00
        assert 500 < d9 < 510  # 00:00 -> 08:28:07
        assert d8 + d9 == pytest.approx(54918 / 60.0, abs=0.1)  # total preserved


class TestTableShape:
    def test_table_fields_complete(self) -> None:
        days = build_daily_table(
            campaign_start="2026-09-07",
            current_utc_day="2026-09-07",
            finalized_days={
                "2026-09-07": _day_payload(
                    trades=4,
                    risk_rejects=2,
                    paper_opens=4,
                    paper_closes=2,
                    realized_pnl=12.5,
                    proposals=7,
                    selected=4,
                ),
            },
            outage_intervals={},
        )
        row: ObservationDay = days[0]
        payload = row.to_dict()
        for key in (
            "date",
            "status",
            "counted",
            "finalized",
            "valid",
            "validity_reason",
            "coverage",
            "activity",
            "runtime_downtime_minutes",
        ):
            assert key in payload
        assert row.trades_ge_3 is True
        assert row.risk_rejects == 2
        assert row.realized_pnl == 12.5
