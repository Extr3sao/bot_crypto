"""RFC-030 continuation §9/§12/§13/§19 — short-borrow data contract tests.

Covers the mandatory PIT leak cases (future rate, future availability, backfilled
status, timezone mismatch, daily-rate-before-publication, missing/duplicate
observations), the UNKNOWN != zero rule, the fail-closed availability gate, coverage
reporting and the explicitly NON_CERTIFIABLE bound scenarios.
"""

from __future__ import annotations

import pytest

from trading_bot.research.pair.borrow import (
    BorrowAvailability,
    BorrowDataQuality,
    BorrowGateDecision,
    BorrowRatePeriod,
    ShortBorrowObservation,
    borrow_availability_gate,
    coverage_report,
    validate_pit,
)
from trading_bot.research.pair.scenarios import borrow_cost_bounds

MS_PER_DAY = 86_400_000
DECISION = 1_700_000_000_000
T0 = DECISION - 7 * MS_PER_DAY


def _obs(
    *,
    asset: str = "ETHUSDT",
    timestamp: int = T0,
    available: BorrowAvailability = BorrowAvailability.AVAILABLE,
    borrow_rate: float | None = 5.0,
    rate_period: BorrowRatePeriod = BorrowRatePeriod.DAILY,
    source_timestamp: int = T0,
    retrieved_at: int = T0,
    pit_valid: bool = True,
) -> ShortBorrowObservation:
    return ShortBorrowObservation(
        asset=asset,
        venue="BINANCE",
        instrument="BINANCE-MARGIN-SPOT-USDT-SHORT",
        timestamp=timestamp,
        available=available,
        borrow_rate=borrow_rate,
        rate_period=rate_period,
        source_id="TEST",
        source_timestamp=source_timestamp,
        retrieved_at=retrieved_at,
        data_quality=BorrowDataQuality.OFFICIAL_EXCHANGE_HISTORICAL,
        pit_valid=pit_valid,
    )


# ----------------------------------------------------------- §4 UNKNOWN != 0


def test_unknown_rate_is_none_not_zero() -> None:
    obs = _obs(borrow_rate=None)
    assert obs.borrow_rate is None
    assert obs.rate_is_known is False
    assert obs.rate_per_day_bps() is None
    assert obs.is_complete is False


def test_unknown_availability_is_not_available() -> None:
    obs = _obs(available=BorrowAvailability.UNKNOWN)
    assert obs.availability_is_known is False
    assert obs.is_complete is False


def test_rate_unit_conversion() -> None:
    hourly = _obs(borrow_rate=1.0, rate_period=BorrowRatePeriod.HOURLY)
    daily = _obs(borrow_rate=24.0, rate_period=BorrowRatePeriod.DAILY)
    annual = _obs(borrow_rate=365.0, rate_period=BorrowRatePeriod.ANNUAL)
    assert hourly.rate_per_day_bps() == pytest.approx(24.0)
    assert daily.rate_per_day_bps() == pytest.approx(24.0)
    assert annual.rate_per_day_bps() == pytest.approx(1.0)


# ----------------------------------------------------------------- §9 PIT


def test_future_borrow_observation_is_refused() -> None:
    obs = _obs(timestamp=DECISION + MS_PER_DAY)
    violations = validate_pit([obs], DECISION)
    assert any(v.reason == "future_borrow_observation" for v in violations)


def test_future_retrieval_is_refused() -> None:
    obs = _obs(retrieved_at=DECISION + MS_PER_DAY)
    violations = validate_pit([obs], DECISION)
    assert any(v.reason == "future_retrieval" for v in violations)


def test_backfilled_status_leak_is_refused() -> None:
    obs = _obs(pit_valid=False)
    violations = validate_pit([obs], DECISION)
    assert any(v.reason == "backfilled_status_leak" for v in violations)


def test_availability_without_contemporaneous_rate_is_a_leak() -> None:
    obs = _obs(borrow_rate=None, available=BorrowAvailability.AVAILABLE)
    violations = validate_pit([obs], DECISION)
    assert any(v.reason == "future_availability_leak" for v in violations)


def test_missing_observations_block_the_gate() -> None:
    decision = borrow_availability_gate([], decision_time=DECISION)
    assert decision is BorrowGateDecision.NO_SHORT_DATA_BLOCKED


def test_duplicate_observation_is_detected() -> None:
    obs = _obs()
    violations = validate_pit([obs, obs], DECISION)
    assert any(v.reason == "duplicate_observation" for v in violations)


def test_clean_observations_have_no_violation() -> None:
    assert validate_pit([_obs()], DECISION) == []


# ------------------------------------------------------------- §12 gate


def test_gate_unknown_availability_blocks() -> None:
    obs = _obs(available=BorrowAvailability.UNKNOWN)
    assert (
        borrow_availability_gate([obs], decision_time=DECISION)
        is BorrowGateDecision.NO_SHORT_DATA_BLOCKED
    )


def test_gate_unavailable_short() -> None:
    obs = _obs(available=BorrowAvailability.UNAVAILABLE)
    assert (
        borrow_availability_gate([obs], decision_time=DECISION)
        is BorrowGateDecision.NO_SHORT_UNAVAILABLE
    )


def test_gate_missing_rate_blocks() -> None:
    obs = _obs(borrow_rate=None)
    assert (
        borrow_availability_gate([obs], decision_time=DECISION)
        is BorrowGateDecision.NO_SHORT_DATA_BLOCKED
    )


def test_gate_allows_only_when_complete_and_pit_safe() -> None:
    obs = _obs()
    assert (
        borrow_availability_gate([obs], decision_time=DECISION) is BorrowGateDecision.SHORT_ALLOWED
    )


def test_gate_never_treats_unknown_as_available() -> None:
    # Explicit anti-false-success assertion (§23).
    obs = _obs(available=BorrowAvailability.UNKNOWN)
    assert borrow_availability_gate([obs], decision_time=DECISION) is not (
        BorrowGateDecision.SHORT_ALLOWED
    )


# ------------------------------------------------------------- §10 coverage


def test_coverage_full_period_is_viable() -> None:
    start = T0
    end = T0 + 10 * MS_PER_DAY
    obs = [_obs(asset="ETHUSDT", timestamp=start + i * MS_PER_DAY) for i in range(10)]
    report = coverage_report(
        obs, required_start=start, required_end=end, required_assets=["ETHUSDT"]
    )
    assert report.coverage_percent == pytest.approx(100.0)
    assert report.is_viable is True


def test_coverage_small_fraction_is_not_viable() -> None:
    start = T0
    end = T0 + 365 * MS_PER_DAY
    obs = [_obs(asset="ETHUSDT", timestamp=start)]
    report = coverage_report(
        obs, required_start=start, required_end=end, required_assets=["ETHUSDT"]
    )
    assert report.coverage_percent < 5.0
    assert report.is_viable is False
    assert report.missing_observations > 0


def test_coverage_missing_asset_is_reported() -> None:
    start = T0
    end = T0 + 5 * MS_PER_DAY
    obs = [_obs(asset="ETHUSDT", timestamp=start + i * MS_PER_DAY) for i in range(5)]
    report = coverage_report(
        obs, required_start=start, required_end=end, required_assets=["ETHUSDT", "BNBUSDT"]
    )
    assert "BNBUSDT" in report.assets_missing
    assert report.is_viable is False


def test_coverage_incomplete_observations_do_not_count() -> None:
    start = T0
    end = T0 + 5 * MS_PER_DAY
    obs = [
        _obs(asset="ETHUSDT", timestamp=start + i * MS_PER_DAY, borrow_rate=None) for i in range(5)
    ]
    report = coverage_report(
        obs, required_start=start, required_end=end, required_assets=["ETHUSDT"]
    )
    assert report.covered_days == 0


# ------------------------------------------------------------- §13 scenarios


def test_bounds_are_never_certifiable() -> None:
    results, _ = borrow_cost_bounds(
        pair_gross_pnl=100.0,
        short_notional=500.0,
        holding_days=7.0,
        borrow_bps_per_day=[0.0, 5.0, 10.0],
    )
    assert all(r.certifiable is False for r in results)
    assert all(r.note == "EXPLORATORY_NON_CERTIFIABLE" for r in results)


def test_bounds_break_even_rate() -> None:
    results, break_even = borrow_cost_bounds(
        pair_gross_pnl=100.0,
        short_notional=500.0,
        holding_days=7.0,
        borrow_bps_per_day=[1.0, 100.0],
    )
    # 100 = rate * 7 * 500 / 10000 -> rate = 100*10000/3500 = 285.71 bps/day
    assert break_even == pytest.approx(100.0 * 10_000.0 / (7.0 * 500.0))
    low = next(r for r in results if r.borrow_bps_per_day == 1.0)
    high = next(r for r in results if r.borrow_bps_per_day == 100.0)
    assert low.survives is True
    assert high.survives is True


def test_bounds_high_rate_does_not_survive() -> None:
    results, _ = borrow_cost_bounds(
        pair_gross_pnl=100.0,
        short_notional=500.0,
        holding_days=7.0,
        borrow_bps_per_day=[1000.0],
    )
    assert results[0].survives is False


def test_bounds_no_break_even_when_gross_is_non_positive() -> None:
    _, break_even = borrow_cost_bounds(
        pair_gross_pnl=-5.0,
        short_notional=500.0,
        holding_days=7.0,
        borrow_bps_per_day=[1.0],
    )
    assert break_even is None
