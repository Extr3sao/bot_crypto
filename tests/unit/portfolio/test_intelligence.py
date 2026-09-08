from __future__ import annotations

import pytest

from trading_bot.portfolio.correlation import (
    CorrelationState,
)
from trading_bot.portfolio.intelligence import (
    PositionExposure,
    build_correlation_clusters,
    build_snapshot,
    compute_marginal_portfolio_value,
    measure_strategy_correlation,
    project_portfolio,
)


def _returns(corr: float, n: int = 60, *, start_ts: int = 0) -> tuple[tuple[int, float], ...]:
    ts = tuple(start_ts + i * 60_000 for i in range(n))
    base = [((i * 37) % 11 - 5) / 50 for i in range(n)]
    other = [corr * x + (1 - abs(corr)) * (((i * 53) % 13 - 6) / 60) for i, x in enumerate(base)]
    return tuple(zip(ts, other, strict=True))


def _identical(n: int = 60, *, start_ts: int = 0) -> tuple[tuple[int, float], ...]:
    ts = tuple(start_ts + i * 60_000 for i in range(n))
    vals = [((i * 37) % 11 - 5) / 50 for i in range(n)]
    return tuple(zip(ts, vals, strict=True))


def _positions() -> tuple[PositionExposure, ...]:
    return (
        PositionExposure(symbol="BTC/USDT", strategy_id="momentum", strategy_family="momentum", direction="long", notional_usdt=1_000.0),
        PositionExposure(symbol="ETH/USDT", strategy_id="trend", strategy_family="trend", direction="long", notional_usdt=800.0),
        PositionExposure(symbol="SOL/USDT", strategy_id="breakout", strategy_family="breakout", direction="short", notional_usdt=600.0),
    )


def test_gross_net_long_short_exposure() -> None:
    snapshot = build_snapshot(
        portfolio_id="p1",
        timestamp=1.0,
        positions=_positions(),
        returns_by_asset={"BTC/USDT": _identical(), "ETH/USDT": _identical(), "SOL/USDT": _identical()},
    )
    assert snapshot.gross_exposure == pytest.approx(2_400.0)
    assert snapshot.long_exposure == pytest.approx(1_800.0)
    assert snapshot.short_exposure == pytest.approx(600.0)
    assert snapshot.net_exposure == pytest.approx(1_200.0)


def test_exposure_by_asset_strategy_family_and_concentration() -> None:
    snapshot = build_snapshot(
        portfolio_id="p1",
        timestamp=1.0,
        positions=_positions(),
        returns_by_asset={"BTC/USDT": _identical(), "ETH/USDT": _identical(), "SOL/USDT": _identical()},
    )
    assert snapshot.exposure_by_asset["BTC/USDT"] == 1_000.0
    assert snapshot.exposure_by_strategy["momentum"] == 1_000.0
    assert snapshot.exposure_by_family["trend"] == 800.0
    assert snapshot.concentration_by_asset["BTC/USDT"] == pytest.approx(1_000.0 / 2_400.0)
    assert snapshot.concentration_by_strategy["breakout"] == pytest.approx(600.0 / 2_400.0)


def test_fused_cluster_collapses_effective_independent_risk() -> None:
    # BTC and ETH strongly fused; SOL independent-ish series.
    returns = {
        "BTC/USDT": _identical(),
        "ETH/USDT": _identical(),
        "SOL/USDT": _returns(0.0, 60, start_ts=0),
    }
    # Force SOL to be a different series: use alternating pattern.
    ts = tuple(i * 60_000 for i in range(60))
    returns["SOL/USDT"] = tuple(zip(ts, [((i * 71 + 13) % 17 - 8) / 40 for i in range(60)], strict=True))
    clusters = build_correlation_clusters(returns, {"BTC/USDT": 1_000.0, "ETH/USDT": 800.0, "SOL/USDT": 600.0})
    btc_eth = next(c for c in clusters if "BTC/USDT" in c.assets and "ETH/USDT" in c.assets)
    assert btc_eth.correlation_state is CorrelationState.FUSED
    assert btc_eth.physical_positions == 2
    assert btc_eth.effective_independent_positions == 1.0  # physical != effective
    sol = next(c for c in clusters if c.assets == ("SOL/USDT",))
    assert sol.effective_independent_positions == 1.0


def test_insufficient_overlap_stays_singleton_never_forced_merge() -> None:
    returns = {
        "BTC/USDT": _identical(n=60),
        "ZZZ/USDT": _identical(n=10, start_ts=1_000_000_000),  # no overlap
    }
    clusters = build_correlation_clusters(returns, {"BTC/USDT": 100.0, "ZZZ/USDT": 100.0})
    assert len(clusters) == 2
    assert all(c.correlation_state is CorrelationState.NORMAL for c in clusters)


def test_cluster_exposure_sums_members() -> None:
    returns = {
        "BTC/USDT": _identical(),
        "ETH/USDT": _identical(),
    }
    clusters = build_correlation_clusters(returns, {"BTC/USDT": 1_000.0, "ETH/USDT": 800.0})
    fused = next(c for c in clusters if len(c.assets) == 2)
    assert fused.total_exposure_usdt == pytest.approx(1_800.0)


def test_snapshot_regime_and_health_binding() -> None:
    snapshot = build_snapshot(
        portfolio_id="p1",
        timestamp=1.0,
        positions=(),
        returns_by_asset={},
        market_regime="BULL|STRONG|NORMAL|TREND|NORMAL|NORMAL",
        strategy_health_summary={"momentum": "MONITORING", "trend": "DEGRADED"},
    )
    assert snapshot.market_regime.startswith("BULL|")
    assert snapshot.strategy_health_summary["trend"] == "DEGRADED"
    assert snapshot.gross_exposure == 0.0


def test_future_mutation_does_not_change_past_clusters() -> None:
    cut = 40 * 60_000
    returns_before = {"BTC/USDT": _identical(), "ETH/USDT": _identical()}
    exposures = {"BTC/USDT": 100.0, "ETH/USDT": 100.0}
    clusters_before = build_correlation_clusters(returns_before, exposures)
    # Mutate ALL future observations.
    def mutate(series: tuple[tuple[int, float], ...]) -> tuple[tuple[int, float], ...]:
        return tuple((t, v * 7 + 3) if t > cut else (t, v) for t, v in series)
    returns_after = {"BTC/USDT": mutate(_identical()), "ETH/USDT": mutate(_identical())}
    clusters_after = build_correlation_clusters(returns_after, exposures)
    # Past-decision equivalence: cluster membership and state identical.
    assert [c.assets for c in clusters_before] == [c.assets for c in clusters_after]
    assert [c.correlation_state for c in clusters_before] == [c.correlation_state for c in clusters_after]


def test_marginal_value_flags_correlated_exposure() -> None:
    snapshot = build_snapshot(
        portfolio_id="p1",
        timestamp=1.0,
        positions=(
            PositionExposure(symbol="BTC/USDT", strategy_id="momentum", strategy_family="momentum", direction="long", notional_usdt=1_000.0),
        ),
        returns_by_asset={"BTC/USDT": _identical(), "ETH/USDT": _identical()},
    )
    candidate = PositionExposure(symbol="ETH/USDT", strategy_id="trend", strategy_family="trend", direction="long", notional_usdt=500.0)
    sig_series = tuple((i * 60_000, 1.0 if i % 2 else -1.0) for i in range(20))
    existing = {"momentum": tuple((i * 60_000, 1.0 if i % 2 else -1.0) for i in range(20))}
    mpv = compute_marginal_portfolio_value(snapshot, candidate, {"BTC/USDT": _identical(), "ETH/USDT": _identical()}, sig_series, existing)
    assert mpv.incremental_exposure_usdt == 500.0
    assert mpv.incremental_correlated_exposure_usdt == 500.0  # ETH sits in the FUSED BTC+ETH cluster
    assert mpv.incremental_signal_diversity == pytest.approx(0.0)  # identical signals
    assert mpv.incremental_opportunity == 0.0  # asset already exposed


def test_marginal_value_diverse_candidate() -> None:
    snapshot = build_snapshot(
        portfolio_id="p1",
        timestamp=1.0,
        positions=(
            PositionExposure(symbol="BTC/USDT", strategy_id="momentum", strategy_family="momentum", direction="long", notional_usdt=1_000.0),
        ),
        returns_by_asset={"BTC/USDT": _identical(), "ETH/USDT": _identical()},
    )
    candidate = PositionExposure(symbol="BTC/USDT", strategy_id="alpha_new", strategy_family="other", direction="short", notional_usdt=300.0)
    sig_series = tuple((i * 60_000, 1.0 if i % 3 else -1.0) for i in range(20))
    existing = {"momentum": tuple((i * 60_000, 1.0 if i % 2 else -1.0) for i in range(20))}
    mpv = compute_marginal_portfolio_value(snapshot, candidate, {"BTC/USDT": _identical(), "ETH/USDT": _identical()}, sig_series, existing)
    assert mpv.incremental_signal_diversity > 0.0
    # Context only: no decision field exists.
    assert not hasattr(mpv, "decision")


def test_strategy_correlation_dimensions_stay_separate() -> None:
    result = measure_strategy_correlation(
        pnl_a={1: 10.0, 2: -5.0, 3: 8.0, 4: -2.0},
        pnl_b={1: 12.0, 2: -4.0, 3: 9.0, 4: -1.0},
        open_intervals_a=((1, 10),),
        open_intervals_b=((1, 10),),
        drawdown_days_a={1, 2},
        drawdown_days_b={1, 2},
    )
    assert result.trade_time_overlap == pytest.approx(1.0)
    assert result.pnl_correlation > 0.9
    assert result.drawdown_overlap == pytest.approx(1.0)
    assert result.classification in ("SIGNAL_OVERLAP", "STRATEGY_CORRELATION", "ASSET_CORRELATION")
    # Dimensions are separate fields, not one score.
    assert result.signal_overlap == 0.0


def test_projection_is_read_only_with_warnings() -> None:
    snapshot = build_snapshot(
        portfolio_id="p1",
        timestamp=1.0,
        positions=_positions(),
        returns_by_asset={"BTC/USDT": _identical(), "ETH/USDT": _identical(), "SOL/USDT": _identical()},
        strategy_health_summary={"trend": "DEGRADED", "momentum": "MONITORING"},
    )
    proj = project_portfolio(snapshot)
    assert proj["read_only"] is True
    assert "trend: DEGRADED" in proj["health_warnings"]
    assert "momentum" not in " ".join(proj["health_warnings"])
    assert proj["effective_diversification_ratio"] < 1.0 or proj["physical_positions"] == 0
    payload = snapshot.to_dict()
    assert payload["read_only"] is True
