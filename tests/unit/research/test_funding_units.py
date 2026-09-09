"""C5 carry unit-contract tests (resolves DEF-DISCOVERY-001)."""

from __future__ import annotations

import pytest

from trading_bot.research.funding_units import (
    FUNDING_UNIT_CONTRACT_V2,
    FundingObservation,
    accrue_long,
    annualized_rate,
    contract_fingerprint,
    periods_per_day,
)


def _obs(rate: float, interval_hours: float = 8.0) -> FundingObservation:
    return FundingObservation(
        timestamp_ms=1_700_000_000_000,
        rate_decimal=rate,
        source="binanceusdm",
        interval_hours=interval_hours,
    )


# --------------------------------------------------------------------------
# sign correctness (LONG/SHORT)
# --------------------------------------------------------------------------

def test_positive_funding_long_pays() -> None:
    # 1bp per 8h on 10k notional -> long pays 1.0 USDT per period.
    assert accrue_long(rate_decimal=0.0001, notional=10_000.0) == -1.0


def test_negative_funding_long_receives() -> None:
    assert accrue_long(rate_decimal=-0.0001, notional=10_000.0) == 1.0


def test_zero_funding_is_zero() -> None:
    assert accrue_long(rate_decimal=0.0, notional=50_000.0) == 0.0


def test_short_is_negation_of_long() -> None:
    long_pnl = accrue_long(rate_decimal=0.0001, notional=10_000.0)
    assert -long_pnl == accrue_long(rate_decimal=0.0001, notional=-10_000.0)


# --------------------------------------------------------------------------
# interval handling (8h vs other)
# --------------------------------------------------------------------------

def test_periods_per_day_8h_vs_4h_vs_1h() -> None:
    assert periods_per_day(_obs(0.0001, 8.0)) == 3.0
    assert periods_per_day(_obs(0.0001, 4.0)) == 6.0
    assert periods_per_day(_obs(0.0001, 1.0)) == 24.0


def test_annualization_is_derived_from_observed_interval() -> None:
    # 1bp per 8h -> 3 periods/day -> 0.0001*3*365 = 10.95% annualized.
    assert abs(annualized_rate(_obs(0.0001, 8.0)) - 0.1095) < 1e-9
    # same rate on 1h interval triples the annualized figure.
    assert abs(annualized_rate(_obs(0.0001, 1.0)) - 0.876) < 1e-9


# --------------------------------------------------------------------------
# unit guard (bps vs decimal)
# --------------------------------------------------------------------------

def test_bps_vs_decimal_confusion_rejected() -> None:
    # 1.0 would be "100%" — must be caught as unit misuse.
    with pytest.raises(ValueError):
        _obs(1.0)
    with pytest.raises(ValueError):
        _obs(0.5)
    # 4.999% per period is still accepted (extreme but possible).
    _obs(0.0499)


def test_invalid_interval_rejected() -> None:
    with pytest.raises(ValueError):
        _obs(0.0001, 0.0)
    with pytest.raises(ValueError):
        _obs(0.0001, -8.0)


# --------------------------------------------------------------------------
# contract identity
# --------------------------------------------------------------------------

def test_contract_fingerprint_stable() -> None:
    fp = contract_fingerprint(FUNDING_UNIT_CONTRACT_V2)
    assert len(fp) == 64
    assert fp == contract_fingerprint(FUNDING_UNIT_CONTRACT_V2)


def test_contract_records_decimal_units_and_real_source() -> None:
    d = FUNDING_UNIT_CONTRACT_V2.to_dict()
    assert d["rate_unit"] == "decimal_per_period"
    assert "binanceusdm" in d["data_source"]
    assert "never an input" in d["annualization"]


# --------------------------------------------------------------------------
# PIT: observation timestamps
# --------------------------------------------------------------------------

def test_pit_timestamp_invariant_documented() -> None:
    # The contract requires observation.timestamp_ms <= decision time;
    # FundingObservation enforces validity at construction.
    o = _obs(0.0001)
    assert o.timestamp_ms <= 1_700_000_000_001  # decision time >= obs time
    with pytest.raises(ValueError):
        FundingObservation(
            timestamp_ms=-1, rate_decimal=0.0001, source="x", interval_hours=8.0
        )
