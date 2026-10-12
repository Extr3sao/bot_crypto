"""EDGE-01 causality and book tests (WP-EDGE-01).

These tests are what make the campaign numbers mean anything. A feature value is
re-derived on the truncated series (the only bars a decision at index ``i`` could
have seen) and must match the cached one, so a value that peeked at a later bar
fails here instead of appearing in the report as an edge. The book tests pin the
two accounting defects found while running the campaign: a fill happens at the
open of the next bar, and opening a position pays for it, so the equity curve is
a real P&L instead of counting an open position twice.
"""

from __future__ import annotations

from typing import Any

import pytest

from trading_bot.research.edge01.candidates import (
    FROZEN_PARAMS,
    CandidateSignal,
    build_candidates,
    build_context,
)
from trading_bot.research.edge01.costs import cost_plane
from trading_bot.research.edge01.data import BAR_MS, OHLCVBar
from trading_bot.research.edge01.features import (
    atr,
    build_feature_series,
    confirmed_swings,
    fvg_bullish_at,
    prior_extreme,
)
from trading_bot.research.edge01.simulator import (
    EXIT_REASONS,
    RiskPolicy,
    buy_and_hold,
    run_portfolio,
)

STEP = BAR_MS["15m"]


def bar(ts: int, *, o: float, h: float, low: float, c: float, v: float = 10.0) -> OHLCVBar:
    return OHLCVBar(ts=ts, open=o, high=h, low=low, close=c, volume=v)


def swings_series(n: int) -> list[OHLCVBar]:
    """Deterministic, non-monotonic series: nothing accidental about its pivots."""
    return [
        bar(i * STEP + 1_000_000, o=100.0 + i, h=101.0 + i, low=99.0 + i, c=100.0 + i)
        for i in range(n)
    ]


def policy(**overrides: Any) -> RiskPolicy:
    values: dict[str, Any] = {
        "risk_per_trade_pct": 0.25,
        "max_open_positions": 3,
        "max_total_exposure_pct": 25.0,
        "max_asset_exposure_pct": 10.0,
        "min_notional_usdt": 25.0,
        "max_notional_usdt": 500.0,
        "drawdown_halt_pct": 5.0,
        "max_consecutive_losses": 3,
        "consecutive_loss_cooldown_minutes": 120.0,
        "max_trades_per_day": 20,
        "start_equity": 10_000.0,
    }
    values.update(overrides)
    return RiskPolicy(**values)


class OneShot:
    """Minimal candidate: prints one long signal on one bar, then nothing.

    Handing the simulator a signal whose entry bar and stop are known exactly is
    what makes the fill and book assertions below checks instead of observations.
    """

    id = "stub"
    timeframe = "15m"

    def __init__(self, bar_index: int, *, stop_pct: float = 0.01, target_pct: float = 0.02) -> None:
        self.bar_index = bar_index
        self.stop_pct = stop_pct
        self.target_pct = target_pct
        self.fired = 0

    def prepare(self, bars: list[OHLCVBar]) -> None:
        del bars  # the contract method; this stub needs no warm-up
        return None

    def on_bar(
        self,
        bars: list[OHLCVBar],
        i: int,
        context: Any = None,
        plane: Any = None,
    ) -> CandidateSignal | None:
        del context, plane  # the stub needs neither a higher timeframe nor costs
        if self.fired or i != self.bar_index:
            return None
        self.fired += 1
        reference = bars[i].close
        return CandidateSignal(
            candidate=self.id,
            symbol="",
            bar_index=i,
            decision_ts=bars[i].ts + STEP,
            decision_timeframe=self.timeframe,
            entry_reference=reference,
            direction="LONG",
            stop=reference * (1 - self.stop_pct),
            targets=(reference * (1 + self.target_pct),),
            invalidations=(),
            risk_reward=self.target_pct / self.stop_pct,
            expected_gross_bps=100.0,
            expected_cost_bps=25.0,
            expected_net_bps=75.0,
            regime="UP",
        )


# --------------------------------------------------------------------------- #
# Causal features: a value at i must equal the value computed on bars[:i+1]
# --------------------------------------------------------------------------- #


def test_features_are_truncation_invariant() -> None:
    bars = swings_series(120)
    full = build_feature_series(
        bars, lookback=20, atr_period=14, volume_lookback=20, with_swings=True
    )
    for i in (19, 20, 21, 40, 61, 90, 119):
        window = bars[: i + 1]
        part = build_feature_series(
            window, lookback=20, atr_period=14, volume_lookback=20, with_swings=True
        )
        assert full.atr[i] == pytest.approx(part.atr[-1])
        assert full.resistance[i] == part.resistance[-1]
        assert full.support[i] == part.support[-1]
        assert full.volume_avg[i] == part.volume_avg[-1]
        assert full.confirmed_swings_before(i) == part.confirmed_swings_before(len(window) - 1)


def test_resistance_excludes_the_evaluated_bar() -> None:
    # bar 25 is the highest high of the series: it must not be part of its own level.
    bars = swings_series(26)
    bars[25] = bar(25 * STEP + 1_000_000, o=200.0, h=210.0, low=199.0, c=205.0)
    level = prior_extreme(bars, 25, 20, want_high=True)
    assert level is not None
    assert level == max(b.high for b in bars[5:25])
    assert level < bars[25].high


def test_pivot_is_only_confirmed_k_bars_later() -> None:
    bars = swings_series(24)
    bars[10] = bar(10 * STEP + 1_000_000, o=100.0, h=150.0, low=99.0, c=149.0)
    assert confirmed_swings(bars, 10) == []
    assert confirmed_swings(bars, 12) == []
    assert confirmed_swings(bars, 13) == [10]


def test_fvg_is_knowable_only_at_its_third_close() -> None:
    bars = [
        bar(0, o=100.0, h=101.0, low=99.0, c=100.0),
        bar(STEP, o=101.0, h=102.0, low=100.5, c=101.5),
        bar(2 * STEP, o=104.0, h=106.0, low=105.0, c=105.5),
    ]
    assert fvg_bullish_at(bars, 1) is None  # the third bar has not closed yet
    gap = fvg_bullish_at(bars, 2)
    assert gap is not None
    assert (gap.bottom, gap.top) == (101.0, 105.0)
    assert gap.formed_index == 2
    assert gap.contains(103.0) and not gap.contains(107.0)


def test_context_bar_is_unreadable_until_it_closes() -> None:
    hour = BAR_MS["1h"]
    context = build_context(
        [
            bar(i * hour, o=100.0 + i, h=101.0 + i, low=99.0 + i, c=100.0 + i)
            for i in range(10)
        ],
        timeframe="1h",
        fast=2,
        slow=3,
    )
    open_ts = context.bars[3].ts
    forming = context.state_at(open_ts + STEP)  # close of the 15m bar inside that hour
    assert forming.index == 2
    assert forming.close == context.bars[2].close
    closed = context.state_at(open_ts + hour)
    assert closed.index == 3
    assert closed.close == context.bars[3].close


def test_atr_uses_only_closed_bars_before_the_index() -> None:
    bars = swings_series(30)
    assert atr(bars, 5, 14) is None  # not enough history: reported, not guessed
    assert atr(bars, 14, 14) is not None
    assert atr(bars, 14, 14) == atr(bars[:15], 14, 14)


# --------------------------------------------------------------------------- #
# Candidate state
# --------------------------------------------------------------------------- #


def test_state_is_per_series() -> None:
    candidate = build_candidates()["edge_intra_01"]
    first = swings_series(40)
    second = swings_series(40)
    candidate.prepare(first)
    candidate.prepare(first)
    candidate.prepare(second)
    assert set(candidate._states) == {id(first), id(second)}
    assert len(candidate._states) == 2


def test_frozen_params_are_the_ones_hashed() -> None:
    import hashlib
    import json

    payload = json.dumps(FROZEN_PARAMS, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert digest == "d073a2d686b9b198c36c9a3c6009d36130577ba247a2016c3f791813cb749d77"


# --------------------------------------------------------------------------- #
# The book: next-bar fills, cash conservation, conservative exits
# --------------------------------------------------------------------------- #


def _one_trade_run(
    bars: list[OHLCVBar], *, index: int = 3, **stop_target: float
) -> tuple[Any, RiskPolicy]:
    plane = cost_plane(size_usd=500.0, horizon_minutes=240.0)
    risk = policy()
    result = run_portfolio(
        candidate=OneShot(index, **stop_target),
        bars_by_asset={"BTC": bars},
        plane=plane,
        policy=risk,
    )
    return result, risk


def test_fill_happens_at_the_next_bar_open_not_the_decision_close() -> None:
    bars = swings_series(12)
    result, _risk = _one_trade_run(bars)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade["entry_bar"] == 4
    assert trade["entry_mid"] == bars[4].open
    assert trade["entry_mid"] != bars[3].close


def test_opening_a_position_pays_for_it_so_equity_does_not_jump() -> None:
    bars = swings_series(12)
    result, risk = _one_trade_run(bars)
    trade = result.trades[0]
    assert trade["notional"] == pytest.approx(500.0)
    equity_at_entry = next(e for ts, e in result.equity_curve if ts == trade["entry_ts"])
    # A book that never debited the entry would sit a whole notional (5% of
    # equity) above the truth; the only legitimate move is the entry price cost.
    assert abs(equity_at_entry - risk.start_equity) < trade["notional"] * 0.01
    final_equity = result.equity_curve[-1][1]
    assert final_equity == pytest.approx(
        risk.start_equity + sum(t["net"] for t in result.trades), abs=1e-6
    )


def test_trade_net_is_proceeds_minus_what_was_paid() -> None:
    bars = swings_series(12)
    result, _risk = _one_trade_run(bars)
    trade = result.trades[0]
    qty = trade["qty"]
    # The row is rounded to 8 decimals, so the identity is checked to that
    # precision rather than to float equality.
    expected = (trade["exit_fill"] - trade["entry_fill"]) * qty - trade["fees"]
    assert trade["net"] == pytest.approx(expected, abs=1e-6)
    assert trade["gross"] == pytest.approx(
        (trade["exit_mid"] - trade["entry_mid"]) * qty, abs=1e-6
    )
    assert trade["cost_bps_realised"] > 0


def test_a_bar_that_touches_stop_and_target_resolves_to_the_stop() -> None:
    bars = swings_series(12)
    bars[4] = bar(4 * STEP + 1_000_000, o=104.0, h=104.0, low=104.0, c=104.0)
    # bar 5 spans both the stop (1% below the fill) and the target (2% above).
    bars[5] = bar(5 * STEP + 1_000_000, o=104.0, h=110.0, low=90.0, c=105.0)
    result, _risk = _one_trade_run(bars)
    trade = result.trades[0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_mid"] < trade["entry_mid"]
    assert all(t["exit_reason"] in EXIT_REASONS for t in result.trades)


def test_a_gap_through_the_stop_fills_at_the_open() -> None:
    bars = swings_series(12)
    bars[4] = bar(4 * STEP + 1_000_000, o=104.0, h=104.0, low=104.0, c=104.0)
    bars[5] = bar(5 * STEP + 1_000_000, o=95.0, h=95.5, low=90.0, c=91.0)
    result, _risk = _one_trade_run(bars)
    trade = result.trades[0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_mid"] == bars[5].open
    assert trade["exit_mid"] < trade["stop_initial"]


def test_an_open_position_is_closed_as_end_of_data_not_as_a_real_exit() -> None:
    bars = swings_series(8)
    result, _risk = _one_trade_run(bars, index=6, stop_pct=0.5)
    assert [t["exit_reason"] for t in result.trades] == ["end_of_data"]


def test_end_of_window_settlement_stays_in_the_window() -> None:
    # The corpus runs to bar 11, but the measured window stops at bar 5: a position
    # still open then must be settled with an in-window price, not a later one
    # (DEF-EDGE01-08). The series falls, so neither the target nor the (50% away)
    # stop is reached and the position really is open when the window ends.
    bars = [
        bar(i * STEP + 1_000_000, o=100.0 - i, h=100.5 - i, low=99.0 - i, c=100.0 - i)
        for i in range(12)
    ]
    plane = cost_plane(size_usd=500.0, horizon_minutes=240.0)
    risk = policy()
    result = run_portfolio(
        candidate=OneShot(3, stop_pct=0.5),
        bars_by_asset={"BTC": bars},
        plane=plane,
        policy=risk,
        window_end_ts=bars[5].ts,
    )
    trade = result.trades[0]
    assert trade["exit_reason"] == "end_of_data"
    assert trade["exit_ts"] == bars[5].ts
    assert trade["exit_mid"] == bars[5].close
    assert result.equity_curve[-1][0] <= bars[5].ts
    assert result.equity_curve[-1][1] == pytest.approx(
        risk.start_equity + sum(t["net"] for t in result.trades), abs=1e-6
    )


def test_position_is_sized_by_the_policy_not_by_the_candidate() -> None:
    bars = swings_series(12)
    result, risk = _one_trade_run(bars)
    trade = result.trades[0]
    # 0.25% of 10k = 25 USDT of risk over a 1% stop would be 2,500 notional, so the
    # 500 USDT cap and the 10% asset cap are what bind: the candidate asked for no size.
    assert trade["notional"] == min(risk.max_notional_usdt, risk.start_equity * 0.10)
    assert trade["planned_risk_usdt"] == pytest.approx(risk.start_equity * 0.0025)


def test_buy_and_hold_pays_the_round_trip_cost_and_starts_at_the_first_open() -> None:
    bars = swings_series(12)
    plane = cost_plane(size_usd=500.0, horizon_minutes=1440.0)
    hold = buy_and_hold(bars=bars, plane=plane, start_equity=10_000.0)
    raw = (bars[-1].close / bars[0].open - 1.0) * 100.0
    assert hold["return_pct"] < raw
    assert hold["entry_mid"] == bars[0].open
    assert hold["exit_mid"] == bars[-1].close
    assert hold["equity_final"] == pytest.approx(10_000.0 * (1 + hold["return_pct"] / 100.0))
    assert "_bar_returns" in hold  # in memory only; the artefacts drop it (DEF-EDGE01-05)
