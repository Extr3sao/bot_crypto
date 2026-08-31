"""Strategy Router tests (EPIC 3)."""

from __future__ import annotations

from types import SimpleNamespace

from trading_bot.research.router_gates import RouterGates
from trading_bot.research.strategy_router import RouterDecision, StrategyRouter


def _ctx(asset="BTC", timestamp=1000, window_end=900, bars=120):
    return SimpleNamespace(
        asset=asset,
        timestamp=timestamp,
        window_end_ts=window_end,
        data_quality={"bars_in_window": bars},
        market_regime="TREND_UP",
    )


MAP = {
    "ema_v1": {
        "family": "ema_crossover",
        "regimes": ["TREND_UP", "TREND_DOWN"],
        "direction": "BOTH",
        "enabled": True,
        "status": "CONFIRMED",
    },
    "mom_v1": {
        "family": "momentum",
        "regimes": ["TREND_UP"],
        "direction": "LONG",
        "enabled": True,
        "status": "CONFIRMED",
        "priority": 0.5,
    },
    "mr_v1": {
        "family": "mean_reversion",
        "regimes": ["RANGE"],
        "direction": "BOTH",
        "enabled": True,
        "status": "CONFIRMED",
    },
    "off_v1": {
        "family": "breakout",
        "regimes": ["TREND_UP"],
        "enabled": False,
        "status": "CONFIRMED",
    },
    "pending_v1": {
        "family": "trend",
        "regimes": ["TREND_UP"],
        "enabled": True,
        "status": "PENDING",
    },
}


def test_routes_to_best_matching_strategy():
    r = StrategyRouter()
    d = r.route(_ctx(), "TREND_UP", MAP)
    assert not d.is_no_trade
    # momentum has priority 0.5 + explicit regime match → higher score
    assert d.strategy_id == "mom_v1"
    assert d.family == "momentum"
    assert d.direction == "LONG"


def test_regime_match_selects_range_strategy():
    r = StrategyRouter()
    d = r.route(_ctx(), "RANGE", MAP)
    assert not d.is_no_trade
    # RANGE matches mr_v1 (mean reversion)
    assert d.strategy_id == "mr_v1"
    assert d.family == "mean_reversion"


def test_no_trade_when_regime_matches_nothing():
    r = StrategyRouter()
    d = r.route(_ctx(), "NONEXISTENT_REGIME", MAP)
    assert d.is_no_trade
    assert d.no_trade_reason == "no_strategy_passed_gates"


def test_no_trade_on_empty_map():
    r = StrategyRouter()
    d = r.route(_ctx(), None, {})
    assert d.is_no_trade
    assert d.no_trade_reason == "empty_strategy_map"


def test_no_trade_when_all_disabled():
    r = StrategyRouter()
    d = r.route(
        _ctx(),
        None,
        {
            "a": {"enabled": False, "status": "CONFIRMED"},
        },
    )
    assert d.is_no_trade
    assert d.no_trade_reason == "no_strategy_passed_gates"


def test_no_trade_when_status_not_confirmed():
    r = StrategyRouter()
    d = r.route(
        _ctx(),
        None,
        {
            "a": {"enabled": True, "status": "PENDING"},
        },
    )
    assert d.is_no_trade


def test_pending_strategy_skipped():
    r = StrategyRouter()
    d = r.route(_ctx(), "TREND_UP", MAP)
    assert d.strategy_id != "pending_v1"


def test_disabled_strategy_skipped():
    r = StrategyRouter()
    d = r.route(_ctx(), "TREND_UP", MAP)
    assert d.strategy_id != "off_v1"


def test_low_data_quality_blocks():
    gates = RouterGates(min_data_quality=0.9)
    r = StrategyRouter(gates)
    d = r.route(_ctx(bars=30), None, MAP)
    assert d.is_no_trade
    assert d.no_trade_reason == "low_data_quality"


def test_stale_context_blocks():
    r = StrategyRouter()
    d = r.route(_ctx(timestamp=999999, window_end=1000), None, MAP)
    assert d.is_no_trade
    assert d.no_trade_reason == "stale_context"


def test_deterministic_same_input_same_output():
    r = StrategyRouter()
    d1 = r.route(_ctx(), "TREND_UP", MAP)
    d2 = r.route(_ctx(), "TREND_UP", MAP)
    assert d1.to_dict() == d2.to_dict()


def test_router_decision_is_no_trade_property():
    d = RouterDecision(asset="BTC", timestamp=1, no_trade_reason="x")
    assert d.is_no_trade
    d2 = RouterDecision(asset="BTC", timestamp=1, strategy_id="s")
    assert not d2.is_no_trade


def test_trace_records_reasoning():
    r = StrategyRouter()
    d = r.route(_ctx(), "TREND_UP", MAP)
    assert len(d.trace) > 0
    assert any("regime" in t for t in d.trace)
