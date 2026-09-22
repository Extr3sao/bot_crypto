from __future__ import annotations

from trading_bot.paper.health_projection import project_health_row, project_health_table
from trading_bot.strategies.health import (
    HealthIdentity,
    StrategyHealthSnapshot,
    StrategyHealthState,
)


def _identity(**overrides: str) -> HealthIdentity:
    base = {
        "strategy_id": "momentum",
        "version": "v1",
        "asset": "SOL",
        "timeframe": "5m",
        "regime": "TREND_BULL",
        "observation_window": "2026-09-01/2026-09-08",
    }
    base.update(overrides)
    return HealthIdentity(**base)  # type: ignore[arg-type]


def _snapshot() -> StrategyHealthSnapshot:
    return StrategyHealthSnapshot(
        identity=_identity(),
        sample_size=42,
        rolling_expectancy=0.35,
        baseline_expectancy=0.5,
        rolling_sharpe=1.1,
        baseline_sharpe=1.5,
        profit_factor=1.4,
        win_rate=0.52,
        drawdown=0.08,
        slippage_adjusted_expectancy=0.3,
        trade_frequency=3.2,
        cost_degradation=1.5,
    )


def test_projection_shape_is_frontend_ready() -> None:
    row = project_health_row(
        _identity(),
        _snapshot(),
        StrategyHealthState.MONITORING,
        last_transition="admitted",
        reason="clean",
    )
    payload = row.to_dict()
    assert payload["strategy"] == "momentum"
    assert payload["health_state"] == "MONITORING"
    assert payload["read_only"] is True
    metrics = payload["metrics"]
    assert metrics["sample_size"] == 42
    assert metrics["rolling_expectancy"] == 0.35
    assert metrics["baseline_expectancy"] == 0.5
    transition = payload["transition"]
    assert transition["last"] == "admitted"
    assert "DEGRADED proposal" in transition["next_gate"]


def test_next_gate_is_informational_per_state() -> None:
    quarantined = project_health_row(_identity(), _snapshot(), StrategyHealthState.QUARANTINED)
    assert "revalidation" in quarantined.next_gate
    retired = project_health_row(_identity(), _snapshot(), StrategyHealthState.RETIRED)
    assert "terminal" in retired.next_gate
    insufficient = project_health_row(
        _identity(), _snapshot(), StrategyHealthState.INSUFFICIENT_EVIDENCE
    )
    assert "sample_size" in insufficient.next_gate


def test_table_projection_is_deterministic_and_sorted() -> None:
    a = (_identity(asset="SOL"), _snapshot(), StrategyHealthState.MONITORING, "admitted", "clean")
    b = (
        _identity(asset="BTC"),
        _snapshot(),
        StrategyHealthState.DEGRADED,
        "degraded",
        "2 bad windows",
    )
    c = (
        _identity(strategy_id="alpha", asset="ETH"),
        _snapshot(),
        StrategyHealthState.QUARANTINED,
        "quarantined",
        "governance",
    )
    rows = project_health_table((a, b, c))
    keys = [(r["strategy"], r["asset"], r["timeframe"]) for r in rows]
    assert keys == sorted(keys)
    again = project_health_table((a, b, c))
    assert rows == again


def test_projection_has_no_trading_controls() -> None:
    import trading_bot.paper.health_projection as mod

    public = {name for name in dir(mod) if not name.startswith("_")}
    forbidden = {
        "disable",
        "enable",
        "promote",
        "quarantine",
        "retire",
        "execute",
        "submit",
        "order",
    }
    assert not (public & forbidden), public & forbidden
