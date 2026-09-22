"""C5 carry unit-contract tests (resolves DEF-DISCOVERY-001)."""

from __future__ import annotations

import pytest

from trading_bot.research.funding_units import (
    FundingUnitContract,
    annualized_rate,
    canon_funding_interval_s,
    canon_rate_per_period,
    contract_fingerprint,
    funding_pnl,
)

# --------------------------------------------------------------------------
# sign correctness (LONG/SHORT) — DB2-06
# --------------------------------------------------------------------------


def test_positive_funding_long_pays() -> None:
    # 1bp per interval on 10k notional -> long pays 1.0 quote per settlement.
    assert funding_pnl("LONG", 10_000.0, 0.0001) == -1.0


def test_negative_funding_long_receives() -> None:
    assert funding_pnl("LONG", 10_000.0, -0.0001) == 1.0


def test_zero_funding_is_zero() -> None:
    assert funding_pnl("LONG", 50_000.0, 0.0) == 0.0


def test_short_receives_positive_funding() -> None:
    assert funding_pnl("SHORT", 10_000.0, 0.0001) == 1.0
    assert funding_pnl("SHORT", 10_000.0, -0.0001) == -1.0


def test_short_is_exact_negation_of_long() -> None:
    assert funding_pnl("SHORT", 10_000.0, 0.0001) == -funding_pnl("LONG", 10_000.0, 0.0001)


def test_invalid_side_rejected() -> None:
    with pytest.raises(ValueError):
        funding_pnl("long", 10_000.0, 0.0001)  # lowercase is not the enum
    with pytest.raises(ValueError):
        funding_pnl("FLAT", 10_000.0, 0.0001)
    with pytest.raises(ValueError):
        funding_pnl("LONG", -1.0, 0.0001)


# --------------------------------------------------------------------------
# unit canonicalization (bps vs percent vs decimal)
# --------------------------------------------------------------------------


def test_canon_rate_decimal_passthrough() -> None:
    assert canon_rate_per_period(0.0001, source_unit="decimal_per_interval") == 0.0001


def test_canon_rate_percent_converts() -> None:
    assert canon_rate_per_period(0.01, source_unit="percent_per_interval") == 0.0001


def test_canon_rate_bps_converts() -> None:
    assert canon_rate_per_period(1.0, source_unit="bps_per_interval") == 0.0001


def test_canon_rate_unknown_unit_fails_closed() -> None:
    with pytest.raises(ValueError):
        canon_rate_per_period(1.0, source_unit="satoshis")
    with pytest.raises(ValueError):
        canon_rate_per_period(float("nan"), source_unit="decimal_per_interval")
    with pytest.raises(ValueError):
        canon_rate_per_period(float("inf"), source_unit="decimal_per_interval")


# --------------------------------------------------------------------------
# interval canonicalization (8h vs other; never assumed)
# --------------------------------------------------------------------------


def test_canon_interval_seconds_and_durations() -> None:
    assert canon_funding_interval_s(28_800) == 28_800
    assert canon_funding_interval_s("8h") == 28_800
    assert canon_funding_interval_s("4h") == 14_400
    assert canon_funding_interval_s("1h") == 3_600
    assert canon_funding_interval_s("30m") == 1_800


def test_canon_interval_none_requires_explicit_default() -> None:
    with pytest.raises(ValueError):
        canon_funding_interval_s(None)
    assert canon_funding_interval_s(None, default_s=28_800) == 28_800


def test_canon_interval_invalid_fails_closed() -> None:
    with pytest.raises(ValueError):
        canon_funding_interval_s(0)
    with pytest.raises(ValueError):
        canon_funding_interval_s(-3600)


# --------------------------------------------------------------------------
# derived annualization (never an input)
# --------------------------------------------------------------------------


def test_annualization_8h_vs_1h() -> None:
    # 1bp per 8h -> 3 intervals/day -> 0.0001 * (365*86400/28800) = 0.1095
    assert abs(annualized_rate(0.0001, 28_800) - 0.1095) < 1e-9
    # same rate on 1h triples it
    assert abs(annualized_rate(0.0001, 3_600) - 0.876) < 1e-9


def test_annualization_invalid_interval_rejected() -> None:
    with pytest.raises(ValueError):
        annualized_rate(0.0001, 0)


# --------------------------------------------------------------------------
# contract identity (fingerprint)
# --------------------------------------------------------------------------


def test_contract_fingerprint_stable_and_deterministic() -> None:
    fp = contract_fingerprint()
    assert len(fp) == 64
    assert fp == contract_fingerprint()
    assert fp == contract_fingerprint(FundingUnitContract())


def test_contract_documents_pit_and_sign_conventions() -> None:
    c = FundingUnitContract()
    assert "funding_time <= t" in c.pit_invariant
    assert "PAYS" in c.long_positive_funding
    assert "RECEIVES" in c.short_positive_funding
    assert "never assumed" in c.assumption_policy
    assert "DEF-DISCOVERY-001" in c.notes
