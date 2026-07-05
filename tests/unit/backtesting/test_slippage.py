"""Tests for slippage models (TSK-104 F2).

Pine contract:
- ``FlatBpsSlippage`` matches F1 semantics exactly (price * bps / 10_000).
- ``VolumeImpactSlippage`` adds a square-root impact term based on
  qty/volume ratio. Clamps volume to 1e-8 to avoid ZeroDivisionError.
- Both models pass ``isinstance(x, SlippageModel)``.
- Engine applies the sign based on side (model returns absolute
  distance; engine sums/subtracts).
"""

from __future__ import annotations

import pytest

from trading_bot.backtesting.slippage import (
    FlatBpsSlippage,
    SlippageModel,
    VolumeImpactSlippage,
)

# ===========================================================================
# FlatBpsSlippage
# ===========================================================================


def test_flat_bps_isinstance_slippage_model() -> None:
    """FlatBpsSlippage must pass isinstance(x, SlippageModel)."""
    assert isinstance(FlatBpsSlippage(bps=5.0), SlippageModel)


def test_flat_bps_default_bps() -> None:
    """Default bps = 5.0 (0.05%)."""
    model = FlatBpsSlippage()
    assert model.bps == 5.0


def test_flat_bps_basic_math() -> None:
    """slippage = price * (bps / 10_000)."""
    model = FlatBpsSlippage(bps=5.0)
    # 100.0 * (5.0 / 10_000) = 0.05
    assert model.calculate(price=100.0, qty=1.0, side="buy", volume=10.0) == pytest.approx(0.05)


def test_flat_bps_zero_bps() -> None:
    """Zero bps -> zero slippage (no friction)."""
    model = FlatBpsSlippage(bps=0.0)
    assert model.calculate(price=100.0, qty=1.0, side="buy", volume=10.0) == 0.0


def test_flat_bps_ignores_qty_and_volume() -> None:
    """FlatBpsSlippage is qty/volume/side-agnostic (F1 behavior preserved)."""
    model = FlatBpsSlippage(bps=5.0)
    s1 = model.calculate(price=100.0, qty=1.0, side="buy", volume=10.0)
    s2 = model.calculate(price=100.0, qty=1000.0, side="sell", volume=0.001)
    assert s1 == s2


def test_flat_bps_negative_bps_raises() -> None:
    """Negative bps is invalid."""
    with pytest.raises(ValueError, match="bps must be >= 0"):
        FlatBpsSlippage(bps=-1.0)


def test_flat_bps_repr() -> None:
    """Repr includes bps for debugging."""
    assert "5.0" in repr(FlatBpsSlippage(bps=5.0))


# ===========================================================================
# VolumeImpactSlippage
# ===========================================================================


def test_volume_impact_isinstance_slippage_model() -> None:
    """VolumeImpactSlippage must pass isinstance(x, SlippageModel)."""
    assert isinstance(VolumeImpactSlippage(base_bps=2.0, impact_coef=0.01), SlippageModel)


def test_volume_impact_small_order_equals_base_bps() -> None:
    """qty << volume -> impact term ~ 0, slippage ~ base_bps * price."""
    model = VolumeImpactSlippage(base_bps=2.0, impact_coef=0.01)
    # qty=0.001, volume=1.0 -> qty/volume = 0.001, sqrt(0.001) ~ 0.0316
    # impact = 0.01 * 0.0316 = 0.000316
    # base = 100 * (2 / 10_000) = 0.02
    # total = 0.020316
    s = model.calculate(price=100.0, qty=0.001, side="buy", volume=1.0)
    assert s == pytest.approx(0.020316, abs=1e-5)


def test_volume_impact_large_order_higher_slippage() -> None:
    """qty close to volume -> impact term dominates, slippage >> base."""
    model = VolumeImpactSlippage(base_bps=2.0, impact_coef=0.01)
    # qty=1.0, volume=1.0 -> qty/volume = 1.0, sqrt(1.0) = 1.0
    # impact = 0.01 * 1.0 = 0.01
    # base = 100 * 0.0002 = 0.02
    # total = 0.03
    s_large = model.calculate(price=100.0, qty=1.0, side="buy", volume=1.0)
    s_small = model.calculate(price=100.0, qty=0.001, side="buy", volume=1.0)
    assert s_large > s_small  # larger qty -> higher slippage
    assert s_large == pytest.approx(0.03, abs=1e-6)


def test_volume_impact_zero_volume_does_not_crash() -> None:
    """volume=0 must not raise ZeroDivisionError; clamps to 1e-8."""
    model = VolumeImpactSlippage(base_bps=2.0, impact_coef=0.01)
    # Should not raise; clamps volume to 1e-8, so impact is huge but finite.
    s = model.calculate(price=100.0, qty=1.0, side="buy", volume=0.0)
    # base = 0.02
    # impact = 0.01 * sqrt(1.0 / 1e-8) = 0.01 * 10_000 = 100.0
    # total = 100.02
    assert s == pytest.approx(100.02, abs=0.01)


def test_volume_impact_side_symmetric() -> None:
    """VolumeImpactSlippage returns the same value for buy and sell
    (the engine applies the sign based on side; the model is
    side-agnostic by design)."""
    model = VolumeImpactSlippage(base_bps=2.0, impact_coef=0.01)
    s_buy = model.calculate(price=100.0, qty=1.0, side="buy", volume=1.0)
    s_sell = model.calculate(price=100.0, qty=1.0, side="sell", volume=1.0)
    assert s_buy == s_sell


def test_volume_impact_negative_base_bps_raises() -> None:
    """Negative base_bps is invalid."""
    with pytest.raises(ValueError, match="base_bps must be >= 0"):
        VolumeImpactSlippage(base_bps=-1.0, impact_coef=0.01)


def test_volume_impact_negative_impact_coef_raises() -> None:
    """Negative impact_coef is invalid."""
    with pytest.raises(ValueError, match="impact_coef must be >= 0"):
        VolumeImpactSlippage(base_bps=2.0, impact_coef=-0.01)


def test_volume_impact_repr() -> None:
    """Repr includes both params for debugging."""
    r = repr(VolumeImpactSlippage(base_bps=2.0, impact_coef=0.01))
    assert "2.0" in r
    assert "0.01" in r
