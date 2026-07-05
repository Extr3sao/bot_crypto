"""Tests for commission models (TSK-104 F2).

Pine contract:
- ``FlatPctCommission`` matches F1 semantics exactly.
- ``TieredCommission`` selects the right tier based on notional,
  falls back to last tier if over max, and adds ``fixed_fee``.
- Both models pass ``isinstance(x, CommissionModel)``.
"""

from __future__ import annotations

import pytest

from trading_bot.backtesting.commissions import (
    CommissionModel,
    FlatPctCommission,
    TieredCommission,
)

# ===========================================================================
# FlatPctCommission
# ===========================================================================


def test_flat_pct_isinstance_commission_model() -> None:
    """FlatPctCommission must pass isinstance(x, CommissionModel)."""
    assert isinstance(FlatPctCommission(rate=0.001), CommissionModel)


def test_flat_pct_default_rate() -> None:
    """Default rate = 0.001 (10 bps, Binance spot taker tipico)."""
    model = FlatPctCommission()
    assert model.rate == 0.001


def test_flat_pct_basic_math() -> None:
    """commission = notional * rate."""
    model = FlatPctCommission(rate=0.001)
    # 1000 USDT * 0.001 = 1.0 USDT
    assert model.calculate(notional=1000.0, qty=1.0, price=1000.0) == pytest.approx(1.0)


def test_flat_pct_zero_notional() -> None:
    """Zero notional -> zero commission (no trade, no fee)."""
    model = FlatPctCommission(rate=0.001)
    assert model.calculate(notional=0.0, qty=0.0, price=0.0) == 0.0


def test_flat_pct_zero_rate() -> None:
    """Zero rate -> zero commission (free trading, e.g. some promos)."""
    model = FlatPctCommission(rate=0.0)
    assert model.calculate(notional=10_000.0, qty=1.0, price=10_000.0) == 0.0


def test_flat_pct_negative_rate_raises() -> None:
    """Negative rate is invalid (would be a rebate, not a commission)."""
    with pytest.raises(ValueError, match="rate must be >= 0"):
        FlatPctCommission(rate=-0.001)


def test_flat_pct_repr() -> None:
    """Repr includes rate for debugging."""
    assert "0.001" in repr(FlatPctCommission(rate=0.001))


# ===========================================================================
# TieredCommission
# ===========================================================================


def test_tiered_isinstance_commission_model() -> None:
    """TieredCommission must pass isinstance(x, CommissionModel)."""
    tiers = [(10_000.0, 0.001), (float("inf"), 0.0005)]
    assert isinstance(TieredCommission(tiers=tiers), CommissionModel)


def test_tiered_basic_first_tier() -> None:
    """Notional below first tier max -> use first tier rate."""
    tiers = [(10_000.0, 0.001), (100_000.0, 0.0009), (float("inf"), 0.0008)]
    model = TieredCommission(tiers=tiers)
    # 5_000 USDT < 10_000 -> tier 0 rate (0.001)
    assert model.calculate(notional=5_000.0, qty=1.0, price=5_000.0) == pytest.approx(5.0)


def test_tiered_basic_middle_tier() -> None:
    """Notional in middle tier -> use middle rate."""
    tiers = [(10_000.0, 0.001), (100_000.0, 0.0009), (float("inf"), 0.0008)]
    model = TieredCommission(tiers=tiers)
    # 50_000 USDT -> tier 1 rate (0.0009)
    assert model.calculate(notional=50_000.0, qty=1.0, price=50_000.0) == pytest.approx(45.0)


def test_tiered_fallback_to_last_tier() -> None:
    """Notional over all tier maxes -> use last tier rate (no reject)."""
    tiers = [(10_000.0, 0.001), (100_000.0, 0.0009)]  # no inf
    model = TieredCommission(tiers=tiers)
    # 1_000_000 USDT > 100_000 -> fallback to last tier (0.0009)
    assert model.calculate(notional=1_000_000.0, qty=1.0, price=1_000_000.0) == pytest.approx(900.0)


def test_tiered_with_fixed_fee() -> None:
    """fixed_fee is added on top of pct commission."""
    tiers = [(float("inf"), 0.001)]
    model = TieredCommission(tiers=tiers, fixed_fee=0.5)
    # 1000 * 0.001 + 0.5 = 1.5
    assert model.calculate(notional=1_000.0, qty=1.0, price=1_000.0) == pytest.approx(1.5)


def test_tiered_empty_tiers_raises() -> None:
    """At least one tier is required."""
    with pytest.raises(ValueError, match="tiers must be non-empty"):
        TieredCommission(tiers=[])


def test_tiered_unsorted_raises() -> None:
    """Tiers must be sorted ascending by max_notional."""
    tiers = [(100_000.0, 0.0009), (10_000.0, 0.001)]  # wrong order
    with pytest.raises(ValueError, match="sorted ascending"):
        TieredCommission(tiers=tiers)


def test_tiered_negative_rate_raises() -> None:
    """Negative rate in any tier is invalid."""
    tiers = [(10_000.0, -0.001)]
    with pytest.raises(ValueError, match="rate must be >= 0"):
        TieredCommission(tiers=tiers)


def test_tiered_negative_fixed_fee_raises() -> None:
    """Negative fixed_fee is invalid."""
    tiers = [(10_000.0, 0.001)]
    with pytest.raises(ValueError, match="fixed_fee must be >= 0"):
        TieredCommission(tiers=tiers, fixed_fee=-0.1)


def test_tiered_repr() -> None:
    """Repr includes tiers + fixed_fee for debugging."""
    tiers = [(10_000.0, 0.001), (float("inf"), 0.0005)]
    r = repr(TieredCommission(tiers=tiers, fixed_fee=0.1))
    assert "10000" in r
    assert "0.1" in r
