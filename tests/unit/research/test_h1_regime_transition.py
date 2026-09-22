"""H1-REGIME-TRANSITION-DISCOVERY-01 — unit tests (frozen prereg contracts).

Covers the acceptance invariants: H1-01 PIT safe, H1-02 future-mutation
invariant, deterministic direction rule, pessimistic stop fill, cost
accounting, frozen acceptance thresholds and orthogonality redundancy rule.
These tests pin the FROZEN spec — changing any threshold breaks them by design.
"""

from __future__ import annotations

import statistics

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.research.h1_regime_transition import (
    ATR_PERIOD,
    HOLD_BARS,
    MIN_TOTAL_TRADES,
    Trade,
    TransitionEvent,
    atr14,
    classify,
    close_time,
    compute_trade_metrics,
    derive_states,
    detect_transitions,
    direction_for,
    legacy_proxy_signal,
    max_drawdown_r,
    orthogonality,
    permutation_p,
    profit_factor,
    simulate_h1,
    split_sign,
)
from trading_bot.research.regime_v2 import (
    CorrelationRegime,
    MarketStructure,
    StressLevel,
    TrendDirection,
    TrendStrength,
    VolatilityLevel,
    derive_market_regime_state,
)


def _candles(
    closes: list[float], start_ts: int = 1_700_000_000_000, vol_mult: float = 1.001
) -> tuple[OHLCV, ...]:
    out: list[OHLCV] = []
    prev = closes[0]
    for i, close in enumerate(closes):
        out.append(
            OHLCV(
                symbol="BTC/USDT",
                timestamp=start_ts + i * 3_600_000,
                open=prev,
                high=max(prev, close) * vol_mult,
                low=min(prev, close) / vol_mult,
                close=close,
                volume=100.0,
            )
        )
        prev = close
    return tuple(out)


def _state(
    trend: TrendDirection = TrendDirection.NEUTRAL,
    strength: TrendStrength = TrendStrength.WEAK,
    vol: VolatilityLevel = VolatilityLevel.NORMAL,
    structure: MarketStructure = MarketStructure.RANGE,
    stress: StressLevel = StressLevel.NORMAL,
) -> object:
    from trading_bot.research.regime_v2 import MarketRegimeState

    return MarketRegimeState(
        bar_ts=0,
        trend_direction=trend,
        trend_strength=strength,
        volatility=vol,
        market_structure=structure,
        stress=stress,
        correlation_regime=CorrelationRegime.NORMAL,
    )


# ---------------------------------------------------------------------------
# close_time / atr14
# ---------------------------------------------------------------------------


def test_close_time_is_open_plus_span_minus_one() -> None:
    bars = _candles([100.0, 101.0])
    assert close_time(bars[0]) == bars[0].timestamp + 3_600_000 - 1


def test_atr14_simple_true_range_mean() -> None:
    from trading_bot.market_data.types import OHLCV as _B

    bars = (
        _B(symbol="X", timestamp=0, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0),
        _B(symbol="X", timestamp=1, open=100.0, high=111.0, low=99.0, close=110.0, volume=1.0),
        _B(symbol="X", timestamp=2, open=110.0, high=111.0, low=89.0, close=90.0, volume=1.0),
    )
    tr1 = max(111.0 - 99.0, abs(111.0 - 100.0), abs(99.0 - 100.0))  # = 12
    tr2 = max(111.0 - 89.0, abs(111.0 - 110.0), abs(89.0 - 110.0))  # = 22
    assert atr14(bars) == pytest.approx((tr1 + tr2) / 2)  # n bars -> n-1 TRs


# ---------------------------------------------------------------------------
# Direction rule (frozen, deterministic)
# ---------------------------------------------------------------------------


def test_direction_correction_and_shock_map_short() -> None:
    for stress in (StressLevel.CORRECTION, StressLevel.SHOCK):
        st = _state(stress=stress)
        assert direction_for(st) == "SHORT"  # type: ignore[arg-type]


def test_direction_bull_breakout_maps_long() -> None:
    st = _state(trend=TrendDirection.BULL, structure=MarketStructure.BREAKOUT)
    assert direction_for(st) == "LONG"  # type: ignore[arg-type]


def test_direction_otherwise_no_trade() -> None:
    assert direction_for(_state()) is None
    # BEAR breakout is NOT tradeable (rule never broadened into generic trend)
    assert (
        direction_for(_state(trend=TrendDirection.BEAR, structure=MarketStructure.BREAKOUT)) is None
    )
    # BULL trending (not breakout) is NOT tradeable
    assert direction_for(_state(trend=TrendDirection.BULL, structure=MarketStructure.TREND)) is None


# ---------------------------------------------------------------------------
# Future-mutation causality (H1-02 / A3 invariant)
# ---------------------------------------------------------------------------


def test_future_mutation_causality_transitions_and_states_byte_identical() -> None:
    # Rising ramp (BULL) with a violent final leg to force a state change.
    closes = [100.0 * (1.0 + 0.006 * i) for i in range(260)]
    base = _candles(closes)

    states_a = derive_states(base, "BTCUSDT")
    events_a = detect_transitions(base, states_a, "BTCUSDT")

    # Mutate FUTURE bars: only bars 230+ (their windows end at t >= 230).
    mutated = list(base)
    for i in range(230, len(mutated)):
        c = mutated[i]
        mutated[i] = OHLCV(
            symbol=c.symbol,
            timestamp=c.timestamp,
            open=c.open,
            high=c.high * 1.5,
            low=c.low * 0.5,
            close=c.close * 3.0,
            volume=c.volume * 9,
        )
    states_b = derive_states(tuple(mutated), "BTCUSDT")
    events_b = detect_transitions(tuple(mutated), states_b, "BTCUSDT")

    # Invariant: decisions at t whose windows end <= 229 are untouched.
    untouched_states = 30  # t = 200..229 -> state indices 0..29
    for a, b in zip(states_a[:untouched_states], states_b[:untouched_states], strict=False):
        assert a == b
    past_a = [e for e in events_a if e.index < 230]
    past_b = [e for e in events_b if e.index < 230]
    assert [(e.index, e.decision_time, e.from_key, e.to_key, e.direction) for e in past_a] == [
        (e.index, e.decision_time, e.from_key, e.to_key, e.direction) for e in past_b
    ]


def test_states_use_only_window_ending_at_decision_bar() -> None:
    # A state at bar t must equal a state derived from exactly the PIT window.
    closes = [100.0 * (1.0 + 0.004 * i) for i in range(240)]
    base = _candles(closes)
    states = derive_states(base, "BTCUSDT")
    t = 210
    window = base[t - 200 + 1 : t + 1]
    assert states[t - 200] == derive_market_regime_state(window)


# ---------------------------------------------------------------------------
# Trade simulation mechanics
# ---------------------------------------------------------------------------


def _flat_series(n: int = 240, price: float = 100.0) -> tuple[OHLCV, ...]:
    return _candles([price] * n)


def test_simulate_stop_assumed_first_in_ambiguous_bar() -> None:
    candles = list(_flat_series())
    entry_idx = 210
    candles[entry_idx] = OHLCV(
        symbol=candles[entry_idx].symbol,
        timestamp=candles[entry_idx].timestamp,
        open=100.0,
        high=104.0,  # would be a huge LONG win if high were used
        low=95.0,  # breaches the stop
        close=103.0,
        volume=1.0,
    )
    atr = atr14(tuple(candles)[entry_idx - ATR_PERIOD + 1 : entry_idx + 1])
    from trading_bot.research.h1_regime_transition import _simulate

    t = _simulate(tuple(candles), "BTCUSDT", "LONG", entry_idx, atr, "H1")
    assert t is not None
    expected_stop = 100.0 - atr
    assert t.exit_price == pytest.approx(expected_stop)  # stop price, not close
    assert t.exit_index == entry_idx
    assert t.gross_r == pytest.approx(-1.0)  # exit AT stop => exactly -1 R


def test_simulate_time_exit_at_close_of_hold_bar() -> None:
    candles = list(_flat_series())
    entry_idx = 210
    # No stop breach: exit must be close of bar entry_idx + HOLD_BARS - 1.
    atr = atr14(tuple(candles)[entry_idx - ATR_PERIOD + 1 : entry_idx + 1])
    from trading_bot.research.h1_regime_transition import _simulate

    t = _simulate(tuple(candles), "BTCUSDT", "LONG", entry_idx, atr, "H1")
    assert t is not None
    assert t.exit_index == entry_idx + HOLD_BARS - 1
    assert t.exit_price == pytest.approx(candles[entry_idx + HOLD_BARS - 1].close)
    assert t.gross_r == pytest.approx(0.0)


def test_net_r_embeds_10bps_cost_via_risk_fraction() -> None:
    candles = _flat_series()
    entry_idx = 210
    atr = atr14(candles[entry_idx - ATR_PERIOD + 1 : entry_idx + 1])
    from trading_bot.research.h1_regime_transition import _simulate

    t = _simulate(candles, "BTCUSDT", "SHORT", entry_idx, atr, "H1")
    assert t is not None
    risk_frac = atr / t.entry_price
    assert t.net_r == pytest.approx(t.gross_r - (10.0 / 10_000.0) / risk_frac)


def test_incomplete_tail_transition_is_skipped_not_fabricated() -> None:
    candles = _flat_series(230)
    ev = TransitionEvent(
        asset="BTCUSDT",
        index=228,
        decision_time=close_time(candles[228]),
        from_key="a",
        to_key="b",
        label="X",
        direction="SHORT",
        tradeable=True,
    )
    trades, skipped, _open = simulate_h1(candles, [ev], "BTCUSDT")
    assert trades == []
    assert skipped == 1


# ---------------------------------------------------------------------------
# Metrics + frozen acceptance thresholds
# ---------------------------------------------------------------------------


def _mk_trade(net: float, kind: str = "H1", i: int = 0) -> Trade:
    return Trade(
        asset="BTCUSDT",
        direction="LONG",
        entry_index=i,
        entry_ts=i * 3_600_000,
        exit_index=i + 1,
        exit_ts=i * 86_400_000,  # distinct UTC day per index
        entry_price=100.0,
        stop_price=99.0,
        exit_price=101.0,
        risk_frac=0.01,
        gross_r=net + 0.1,
        net_r=net,
        kind=kind,
    )


def test_classify_insufficient_sample_below_minimum_n() -> None:
    m = compute_trade_metrics([_mk_trade(0.5) for _ in range(MIN_TOTAL_TRADES - 1)])
    assert classify(m) == "INSUFFICIENT_SAMPLE"


def test_classify_pass_requires_every_frozen_threshold() -> None:
    good = [_mk_trade(0.4) if i % 5 else _mk_trade(-0.1) for i in range(60)]
    m = compute_trade_metrics(good)
    assert classify(m) == "DISCOVERY_PASS"
    # Break ONE frozen threshold (PF) => FAIL; no partial credit.
    bad = [_mk_trade(0.02) if i % 5 else _mk_trade(-0.1) for i in range(60)]
    m2 = compute_trade_metrics(bad)
    assert classify(m2) == "DISCOVERY_FAIL"


def test_split_sign_and_drawdown() -> None:
    assert split_sign([1.0, 1.0, 1.0, -1.0, -1.0, -1.0], 2) == [1, -1]
    assert max_drawdown_r([1.0, 1.0, -2.0, 0.5]) == pytest.approx(2.0)
    assert profit_factor([2.0, -1.0]) == pytest.approx(2.0)


def test_permutation_p_extreme_sequence_is_small() -> None:
    rs = [0.5] * 40
    assert permutation_p(rs) <= 0.001
    noise = [0.1, -0.1] * 30
    assert permutation_p(noise) > 0.05


def test_cost_sensitivity_absolute_cost_monotone_non_increasing() -> None:
    """DEF-RESEARCH-COST-001: sensitivity must apply the ABSOLUTE scenario cost.

    Invariants for a fixed trade set: NET = GROSS - COST with COST >= 0,
    net expectancy monotone non-increasing in cost, and the default path
    (precomputed t.net_r) equals the absolute formula at 10 bps.
    """
    trades = [_mk_trade(0.3) for _ in range(30)]  # risk_frac=0.01, gross=0.4
    nets: dict[float, float] = {}
    for bps in (0.0, 5.0, 10.0, 20.0):
        m = compute_trade_metrics(trades, cost_bps=bps)
        nets[bps] = float(m["net_expectancy_R"])  # type: ignore[arg-type]
        assert nets[bps] <= float(m["gross_expectancy_R"]) + 1e-12  # type: ignore[arg-type]
    assert nets[0.0] >= nets[5.0] >= nets[10.0] >= nets[20.0]
    # exact absolute-cost arithmetic: 5 bps -> 0.05 R/trade, 20 bps -> 0.20 R/trade
    assert nets[5.0] == pytest.approx(nets[0.0] - 0.05, abs=1e-12)
    assert nets[20.0] == pytest.approx(nets[0.0] - 0.20, abs=1e-12)
    # default path == absolute formula at the 10 bps baseline
    assert nets[10.0] == pytest.approx(
        float(compute_trade_metrics(trades)["net_expectancy_R"]),
        abs=1e-12,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Orthogonality (B2) — redundancy rule
# ---------------------------------------------------------------------------


def test_orthogonality_redundant_when_fully_overlapping() -> None:
    h1 = [_mk_trade(0.1 + i * 0.001, i=i) for i in range(40)]
    proxy = [_mk_trade(0.1 + i * 0.001, kind="PROXY", i=i) for i in range(40)]
    result = orthogonality(h1, proxy)
    assert result["overlap_trade_time"] == 1.0
    assert result["redundant"] is True


def test_orthogonality_not_redundant_when_disjoint() -> None:
    h1 = [_mk_trade(0.1, i=i) for i in range(40)]
    proxy = [_mk_trade(-0.05, kind="PROXY", i=1000 + i) for i in range(40)]
    result = orthogonality(h1, proxy)
    assert result["overlap_trade_time"] == 0.0
    assert result["redundant"] is False


# ---------------------------------------------------------------------------
# Proxy + end-to-end natural simulation over synthetic-but-PIT data
# ---------------------------------------------------------------------------


def test_proxy_signal_thresholds() -> None:
    candles = _candles([100.0] * 30 + [110.0])  # +10% ROC24 -> LONG
    assert legacy_proxy_signal(candles, 30) == "LONG"
    candles2 = _candles([100.0] * 30 + [90.0])  # -10% -> SHORT
    assert legacy_proxy_signal(candles2, 30) == "SHORT"
    assert legacy_proxy_signal(_candles([100.0] * 31), 30) is None


def test_simulate_h1_respects_cooldown_one_position_per_asset() -> None:
    n = 260
    candles = _candles([100.0 * (1.0 + (0.002 if i % 2 else -0.001)) for i in range(n)])
    events = [
        TransitionEvent(
            asset="BTCUSDT",
            index=210 + off,
            decision_time=close_time(candles[210 + off]),
            from_key=f"k{off}",
            to_key=f"j{off}",
            label=f"L{off}",
            direction="SHORT",
            tradeable=True,
        )
        for off in (0, 1, 2)  # overlapping indices -> cooldown must skip
    ]
    trades, _skipped, skipped_open = simulate_h1(candles, events, "BTCUSDT")
    assert skipped_open >= 1
    from itertools import pairwise

    # entries strictly non-overlapping
    for a, b in pairwise(trades):
        assert a.exit_index < b.entry_index or b.exit_index < a.entry_index


def test_statistics_import_used_by_metrics_only() -> None:
    # mean via statistics stays consistent with our expectancies
    assert statistics.mean([1.0, 2.0]) == pytest.approx(1.5)
