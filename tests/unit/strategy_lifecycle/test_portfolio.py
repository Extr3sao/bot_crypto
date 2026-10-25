"""Portfolio manager tests: correlation, concentration, merged exposure (§10)."""

from __future__ import annotations

from trading_bot.strategy_lifecycle.contracts import RationaleCode
from trading_bot.strategy_lifecycle.portfolio import (
    PortfolioProposal,
    StrategyPortfolioManager,
    pearson_correlation,
)


def _p(sid, *, asset="BTC", direction="LONG", notional=100.0, edge=10.0, series=()):
    return PortfolioProposal(
        strategy_id=sid,
        asset=asset,
        direction=direction,
        notional_usdt=notional,
        expected_net_edge_bps=edge,
        net_return_series=series,
    )


def test_three_uncorrelated_bets_survive_if_within_budget() -> None:
    mgr = StrategyPortfolioManager(equity=10_000, max_asset_exposure_pct=10, max_total_exposure_pct=25)
    decision = mgr.arbitrate(
        [
            _p("mom", notional=100.0, series=(1.0, -1.0, 2.0, -2.0)),
            _p("trend", asset="ETH", notional=100.0, series=(-1.0, 1.0, -2.0, 2.0)),
            _p("breakout", asset="SOL", notional=100.0, series=(2.0, 2.0, -1.0, -1.0)),
        ]
    )
    assert len(decision.accepted_proposals) == 3
    assert decision.rejected_proposals == ()


def test_correlated_same_asset_proposals_are_rejected() -> None:
    mgr = StrategyPortfolioManager(equity=10_000, max_asset_exposure_pct=100, correlation_threshold=0.7)
    series = [1.0, 2.0, 3.0, 4.0, 5.0]
    decision = mgr.arbitrate(
        [
            _p("a", notional=50.0, edge=20.0, series=series),
            _p("b", notional=50.0, edge=10.0, series=series),
        ]
    )
    assert decision.accepted_proposals == ("a",)
    assert "b" in decision.rejected_proposals
    assert RationaleCode.CORRELATION_CONFLICT.value in decision.reason_codes
    assert decision.correlation_flags


def test_per_asset_concentration_is_enforced() -> None:
    mgr = StrategyPortfolioManager(equity=10_000, max_asset_exposure_pct=1.0, max_total_exposure_pct=50)
    # 1% of 10_000 = 100 budget on BTC; second proposal of 60 would exceed it.
    decision = mgr.arbitrate(
        [
            _p("a", notional=60.0, edge=20.0),
            _p("b", notional=60.0, edge=10.0),
        ]
    )
    assert decision.accepted_proposals == ("a",)
    assert RationaleCode.CONCENTRATION_CONFLICT.value in decision.reason_codes


def test_total_exposure_budget_is_enforced() -> None:
    mgr = StrategyPortfolioManager(
        equity=1_000, max_asset_exposure_pct=100, max_total_exposure_pct=5, max_same_direction_per_asset=10
    )
    # total budget = 50
    decision = mgr.arbitrate(
        [
            _p("a", asset="BTC", notional=40.0, edge=20.0),
            _p("b", asset="ETH", notional=40.0, edge=10.0),
        ]
    )
    assert decision.accepted_proposals == ("a",)
    assert RationaleCode.PORTFOLIO_CONFLICT.value in decision.reason_codes


def test_same_direction_cluster_is_capped() -> None:
    mgr = StrategyPortfolioManager(
        equity=10_000, max_asset_exposure_pct=100, max_total_exposure_pct=100, max_same_direction_per_asset=2
    )
    decision = mgr.arbitrate(
        [
            _p("a", notional=10.0, edge=30.0),
            _p("b", notional=10.0, edge=20.0),
            _p("c", notional=10.0, edge=10.0),
        ]
    )
    assert set(decision.accepted_proposals) == {"a", "b"}
    assert "c" in decision.rejected_proposals


def test_merged_exposure_is_reported() -> None:
    mgr = StrategyPortfolioManager(equity=10_000, max_asset_exposure_pct=100, max_total_exposure_pct=100)
    decision = mgr.arbitrate(
        [
            _p("a", asset="BTC", notional=40.0, edge=20.0),
            _p("b", asset="BTC", direction="SHORT", notional=30.0, edge=10.0),
        ]
    )
    assert decision.merged_exposure["BTC"] == 70.0


def test_empty_arbitration_is_not_an_error() -> None:
    decision = StrategyPortfolioManager().arbitrate([])
    assert decision.accepted_proposals == ()
    assert decision.notes


def test_pearson_correlation_definition() -> None:
    import pytest

    assert pearson_correlation([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert pearson_correlation([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)
    assert pearson_correlation([1, 2], [1, 2]) is None
    assert pearson_correlation([1, 1, 1, 1], [1, 2, 3, 4]) is None
