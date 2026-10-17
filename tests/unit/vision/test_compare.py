"""The verdict must be readable in one sentence and must refuse to flatter a mismatch."""

from __future__ import annotations

import pytest

from trading_bot.vision.compare import comparison


def run(net: float, fills: int, drawdown: float | None = 2.0, **extra) -> dict:
    return {
        "net_realised_usdt": net,
        "fills": fills,
        "drawdown_pct": drawdown if drawdown is not None else "UNKNOWN",
        **extra,
    }


def test_a_better_net_result_is_named_as_value_added():
    result = comparison(run(-100.0, 40), run(-250.0, 40))

    assert result["verdict"] == "VISION_ADDS_VALUE"
    assert result["delta_net_usdt"] == pytest.approx(150.0)
    assert "150.00 USDT better" in result["reading"]


def test_a_worse_net_result_is_named_without_euphemism():
    result = comparison(run(-300.0, 40), run(-250.0, 40))

    assert result["verdict"] == "VISION_DESTROYS_VALUE"
    assert result["delta_net_usdt"] == pytest.approx(-50.0)
    assert "No restated edge" in result["reading"]


def test_a_negligible_difference_is_not_called_an_edge():
    result = comparison(run(-250.0, 40), run(-250.004, 40))

    assert result["verdict"] == "NO_MEASURABLE_DIFFERENCE"


def test_a_missing_net_result_makes_the_comparison_unknown():
    result = comparison({"fills": 3}, run(-250.0, 40))

    assert result["verdict"] == "UNKNOWN"
    assert "no measurable net result" in result["reason"]


def test_different_cost_models_invalidate_the_comparison():
    result = comparison(
        run(-100.0, 40),
        run(-250.0, 40),
        same_inputs={"bars": True, "cost_model": False, "risk_policy": True},
    )

    assert result["inputs_match"] is False
    assert result["input_mismatches"] == ["cost_model"]
    assert result["reading"].startswith("NOT_A_COMPARISON")
    assert result["verdict"] == "VISION_ADDS_VALUE"


def test_net_per_trade_exposes_a_result_that_only_traded_less():
    """Fewer fills can look better on net while being worse per unit of risk taken."""
    result = comparison(run(-10.0, 1), run(-100.0, 100))

    assert result["vision"]["net_per_trade_usdt"] == pytest.approx(-10.0)
    assert result["baseline"]["net_per_trade_usdt"] == pytest.approx(-1.0)


def test_an_unknown_drawdown_is_not_reported_as_zero():
    result = comparison(run(-100.0, 10, drawdown=None), run(-90.0, 10, drawdown=None))

    assert result["vision"]["drawdown_pct"] == "UNKNOWN"
    assert result["baseline"]["drawdown_pct"] == "UNKNOWN"


def test_non_finite_results_are_treated_as_missing():
    result = comparison(run(float("nan"), 5), run(-10.0, 5))

    assert result["verdict"] == "UNKNOWN"


def test_the_verdict_always_carries_the_single_realisation_caveat():
    result = comparison(run(-100.0, 10), run(-90.0, 10))

    assert any("significance" in caveat for caveat in result["caveats"])
