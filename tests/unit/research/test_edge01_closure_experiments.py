"""WP-EDGE-01 closure rules: the retest plan, the resting limit book, the verdicts.

These tests pin the three things H6 and the OOS review rest on:

* the variant changes the EXECUTION and nothing else — the frozen ruleset, its hash
  and every refusal the frozen rule printed are untouched;
* a planned limit order is never assumed to fill: it fills only on a bar that trades
  at or through the level, at the level and never better, it expires at the end of
  its declared window and it is cancelled when the measured window ends;
* the two decision rules are pure functions of the published numbers, so a verdict
  cannot depend on which numbers the run happened to produce.
"""

from __future__ import annotations

from typing import Any

import pytest

from trading_bot.research.edge01.candidates import (
    FROZEN_PARAMS,
    CandidateSignal,
    build_candidates,
)
from trading_bot.research.edge01.closure import (
    RETEST_H6_DECISION,
    oos_trend_verdict,
    retest_verdict,
)
from trading_bot.research.edge01.costs import cost_plane
from trading_bot.research.edge01.data import BAR_MS, OHLCVBar
from trading_bot.research.edge01.retest import RETEST_PARAMS, RetestEntry
from trading_bot.research.edge01.simulator import RiskPolicy, run_portfolio

STEP = BAR_MS["15m"]
T0 = 1_700_000_000_000


def bar(ts: int, *, o: float, h: float, low: float, c: float, v: float = 10.0) -> OHLCVBar:
    return OHLCVBar(ts=ts, open=o, high=h, low=low, close=c, volume=v)


def policy() -> RiskPolicy:
    return RiskPolicy(
        risk_per_trade_pct=0.25,
        max_open_positions=1,
        max_total_exposure_pct=50.0,
        max_asset_exposure_pct=50.0,
        min_notional_usdt=10.0,
        max_notional_usdt=500.0,
        drawdown_halt_pct=100.0,
        max_consecutive_losses=99,
        consecutive_loss_cooldown_minutes=0.0,
        max_trades_per_day=99,
        start_equity=10_000.0,
    )


class _Scripted:
    """A candidate that prints exactly one planned limit entry, on a chosen bar."""

    id = "scripted"
    timeframe = "15m"
    context_timeframe = None

    def __init__(self, *, signal_bar: int, level: float, expiry_bars: int) -> None:
        self.params: dict[str, Any] = {}
        self.signal_bar = signal_bar
        self.level = level
        self.expiry_bars = expiry_bars
        self.bars_evaluated = 0
        self.warmup_bars = 0

    def prepare(self, bars: list[OHLCVBar]) -> None:
        return None

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: Any, plane: Any
    ) -> CandidateSignal | None:
        self.bars_evaluated += 1
        if i != self.signal_bar:
            return None
        return CandidateSignal(
            candidate=self.id,
            symbol="",
            bar_index=i,
            decision_ts=bars[i].ts + STEP,
            decision_timeframe=self.timeframe,
            entry_reference=self.level,
            direction="LONG",
            stop=self.level * 0.99,
            targets=(self.level * 1.05,),
            invalidations=(),
            risk_reward=5.0,
            expected_gross_bps=500.0,
            expected_cost_bps=10.0,
            expected_net_bps=490.0,
            regime="UP",
            evidence={},
            trailing_atr=None,
            trailing_atr_value=None,
            hard_invalidation=self.level,
            entry_limit=self.level,
            limit_expiry_bars=self.expiry_bars,
        )


def run_scripted(
    bars: list[OHLCVBar], *, level: float, signal_bar: int = 0, expiry_bars: int = 3,
    limit_entries: bool = True,
) -> Any:
    candidate = _Scripted(signal_bar=signal_bar, level=level, expiry_bars=expiry_bars)
    return run_portfolio(
        candidate=candidate,  # type: ignore[arg-type]
        bars_by_asset={"BTC": bars},
        plane=cost_plane(size_usd=1000.0, horizon_minutes=240.0),
        policy=policy(),
        window_start_ts=bars[0].ts,
        window_end_ts=bars[-1].ts,
        limit_entries=limit_entries,
    )


def test_the_variant_changes_the_execution_and_nothing_else() -> None:
    """The frozen dict and the frozen hash key must not move for the variant."""
    variant = RetestEntry()
    assert variant.params == FROZEN_PARAMS["edge_intra_01"]
    assert "entry_limit" not in FROZEN_PARAMS["edge_intra_01"]
    assert "limit_expiry_bars" not in FROZEN_PARAMS["edge_intra_01"]
    assert RETEST_PARAMS["base_candidate"] == "edge_intra_01"
    assert variant.expiry_bars == RETEST_PARAMS["retest_expiry_bars"]
    # the frozen objects themselves still print market intents
    for candidate in build_candidates().values():
        assert candidate.id in ("edge_intra_01", "edge_intra_01_no_trend", "edge_intra_02",
                                "edge_intra_02_no_fvg", "edge_trend_01", "edge_trend_01")


def test_the_plan_rests_at_the_level_the_signal_named() -> None:
    frozen = build_candidates()["edge_intra_01"]
    signal = CandidateSignal(
        candidate="edge_intra_01",
        symbol="BTC",
        bar_index=7,
        decision_ts=1_000,
        decision_timeframe="15m",
        entry_reference=105.0,
        direction="LONG",
        stop=100.0,
        targets=(112.0,),
        invalidations=("close_below_broken_level",),
        risk_reward=1.4,
        expected_gross_bps=66.0,
        expected_cost_bps=12.0,
        expected_net_bps=54.0,
        regime="UP",
        evidence={"atr": 2.0},
        hard_invalidation=101.0,
    )
    planned = RetestEntry().plan(
        signal, plane=cost_plane(size_usd=1000.0, horizon_minutes=240.0)
    )
    assert isinstance(planned, CandidateSignal)
    assert planned.entry_limit == 101.0
    assert planned.entry_reference == 101.0
    assert planned.limit_expiry_bars == RETEST_PARAMS["retest_expiry_bars"]
    assert planned.stop == signal.stop and planned.targets == signal.targets
    assert planned.evidence["planned_entry"] == 101.0
    assert planned.evidence["breakout_entry_reference"] == 105.0
    # entering at the level is closer to the target and farther from the stop
    assert planned.risk_reward > signal.risk_reward
    assert planned.expected_gross_bps > signal.expected_gross_bps
    assert frozen.id == "edge_intra_01"


def test_a_signal_without_a_level_is_left_as_it_was_printed() -> None:
    signal = CandidateSignal(
        candidate="edge_intra_01",
        symbol="BTC",
        bar_index=3,
        decision_ts=1_000,
        decision_timeframe="15m",
        entry_reference=100.0,
        direction="LONG",
        stop=99.0,
        targets=(110.0,),
        invalidations=(),
        risk_reward=10.0,
        expected_gross_bps=990.0,
        expected_cost_bps=10.0,
        expected_net_bps=980.0,
        regime="UP",
        hard_invalidation=None,
    )
    planned = RetestEntry().plan(
        signal, plane=cost_plane(size_usd=1000.0, horizon_minutes=240.0)
    )
    assert planned is signal


def test_the_limit_fills_only_when_the_level_is_touched() -> None:
    """Nothing comes back to the level: no trade, and the order is published unfilled."""
    level = 100.0
    bars = [
        bar(T0, o=101.0, h=102.0, low=100.5, c=101.5),
        bar(T0 + STEP, o=101.5, h=103.0, low=101.2, c=102.5),
        bar(T0 + 2 * STEP, o=102.5, h=104.0, low=102.0, c=103.5),
        bar(T0 + 3 * STEP, o=103.5, h=105.0, low=103.0, c=104.5),
    ]
    result = run_scripted(bars, level=level, expiry_bars=2)
    assert result.trades == []
    assert [row["outcome"] for row in result.orders] == ["expired"]
    assert result.orders[0]["level"] == level
    assert result.orders[0]["bars_resting"] == 3  # the first bar past a 2-bar window


def test_the_limit_fills_at_the_level_and_never_better() -> None:
    """The level is touched by a bar that gapped below it: the fill is still the level."""
    level = 100.0
    bars = [
        bar(T0, o=101.0, h=102.0, low=100.5, c=101.5),
        bar(T0 + STEP, o=99.0, h=99.5, low=97.0, c=98.0),
        bar(T0 + 2 * STEP, o=98.0, h=99.0, low=97.5, c=98.5),
        bar(T0 + 3 * STEP, o=98.5, h=99.0, low=98.0, c=98.5),
    ]
    result = run_scripted(bars, level=level, expiry_bars=2)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade["entry_mid"] == level  # the level, not the better open at 99.0
    assert trade["entry_fill"] > level  # the modelled costs are charged on top
    assert trade["entry_ts"] == bars[1].ts
    assert result.orders[0]["outcome"] == "filled"
    assert result.orders[0]["outcome_bar"] == 1


def test_a_bar_beyond_the_window_cannot_fill_a_cancelled_order() -> None:
    """The order is live for exactly its declared window and expires before that."""
    level = 100.0
    bars = [
        bar(T0, o=101.0, h=102.0, low=100.5, c=101.5),
        bar(T0 + STEP, o=101.5, h=102.0, low=101.0, c=101.8),
        bar(T0 + 2 * STEP, o=101.8, h=102.5, low=101.2, c=102.0),
        bar(T0 + 3 * STEP, o=99.0, h=99.5, low=97.0, c=98.0),  # touches, one bar too late
        bar(T0 + 4 * STEP, o=98.0, h=99.0, low=97.5, c=98.5),
    ]
    result = run_scripted(bars, level=level, expiry_bars=2)
    assert result.trades == []
    assert result.orders[0]["outcome"] == "expired"


def test_the_last_bar_of_the_window_still_fills() -> None:
    level = 100.0
    bars = [
        bar(T0, o=101.0, h=102.0, low=100.5, c=101.5),
        bar(T0 + STEP, o=101.5, h=102.0, low=101.0, c=101.8),
        bar(T0 + 2 * STEP, o=100.2, h=101.0, low=99.8, c=100.5),  # last live bar, touched
        bar(T0 + 3 * STEP, o=100.5, h=101.5, low=100.2, c=101.0),
    ]
    result = run_scripted(bars, level=level, expiry_bars=2)
    assert len(result.trades) == 1
    assert result.orders[0]["outcome"] == "filled"
    assert result.orders[0]["bars_resting"] == 2


def test_an_order_still_resting_when_the_window_ends_is_cancelled() -> None:
    level = 100.0
    bars = [
        bar(T0, o=101.0, h=102.0, low=100.5, c=101.5),
        bar(T0 + STEP, o=101.5, h=102.0, low=101.0, c=101.8),
    ]
    result = run_scripted(bars, level=level, expiry_bars=8)
    assert result.trades == []
    assert [row["outcome"] for row in result.orders] == ["cancelled_window_end"]


def test_without_the_limit_mode_the_same_plan_is_crossed_at_market() -> None:
    """The plan can be measured as a market order, and then nothing rests."""
    level = 100.0
    bars = [
        bar(T0, o=101.0, h=102.0, low=100.5, c=101.5),
        bar(T0 + STEP, o=99.0, h=99.5, low=97.0, c=98.0),
        bar(T0 + 2 * STEP, o=98.0, h=99.0, low=97.5, c=98.5),
    ]
    result = run_scripted(bars, level=level, expiry_bars=2, limit_entries=False)
    assert result.orders == []
    assert len(result.trades) == 1
    assert result.trades[0]["entry_mid"] == bars[1].open  # the next open, not the level


def _arm(
    *, net: float, expectancy: float, orders: int, fills: int, trades: int = 100
) -> dict[str, Any]:
    return {
        "net_usdt": net,
        "expectancy_usdt": expectancy,
        "orders_placed": orders,
        "orders_filled": fills,
        "fill_rate": (fills / orders) if orders else None,
        "trades": trades,
    }


def test_the_retest_rule_labels_each_case_it_declares() -> None:
    rule = dict(RETEST_H6_DECISION)
    baseline = _arm(net=-500.0, expectancy=-1.7, orders=0, fills=0)
    starved = retest_verdict(
        {
            "frozen_market": baseline,
            "plan_market": baseline,
            "plan_limit": _arm(net=-100.0, expectancy=-0.5, orders=400, fills=80),
        },
        rule,
    )
    assert starved["verdict"] == "RETEST_IMPROVES_NET"
    assert starved["execution"] == "STARVED"  # 20% < the declared 40% floor

    better = retest_verdict(
        {
            "frozen_market": baseline,
            "plan_limit": _arm(net=-100.0, expectancy=-0.5, orders=200, fills=150),
        },
        rule,
    )
    assert (better["verdict"], better["execution"]) == ("RETEST_IMPROVES_NET", "VIABLE")

    per_trade_only = retest_verdict(
        {
            "frozen_market": baseline,
            "plan_limit": _arm(net=-700.0, expectancy=-0.2, orders=200, fills=150),
        },
        rule,
    )
    assert per_trade_only["verdict"] == "RETEST_IMPROVES_EXPECTANCY_ONLY"

    worse = retest_verdict(
        {
            "frozen_market": baseline,
            "plan_limit": _arm(net=-900.0, expectancy=-2.5, orders=200, fills=150),
        },
        rule,
    )
    assert worse["verdict"] == "RETEST_DOES_NOT_HELP"

    unpowered = retest_verdict(
        {
            "frozen_market": baseline,
            "plan_limit": _arm(net=500.0, expectancy=5.0, orders=10, fills=9),
        },
        rule,
    )
    assert unpowered["verdict"] == "RETEST_UNPOWERED"


def _oos_payload(*, oos_net: float, stress_net: float, trades: int, share: float,
                 assets: dict[str, float], hold_dd: float, candidate_dd: float,
                 periods: dict[str, float]) -> dict[str, Any]:
    return {
        "runs": {
            "OOS:BASE": {
                "combined": {
                    "net_usdt": oos_net,
                    "trades": trades,
                    "largest_trade_share_of_net": share,
                    "max_drawdown_pct": candidate_dd,
                },
                "assets": {name: {"net_usdt": net} for name, net in assets.items()},
                "buy_and_hold": {
                    name: {"max_drawdown_pct": hold_dd} for name in assets
                },
                "periods": [{"period": name, "net_usdt": net} for name, net in periods.items()],
            },
            "OOS:2X_FEES": {"combined": {"net_usdt": stress_net}},
        },
        "wp_admission": {"verdict": "INSUFFICIENT_EVIDENCE"},
    }


def test_the_paper_gate_needs_every_declared_requirement() -> None:
    good = _oos_payload(
        oos_net=500.0,
        stress_net=400.0,
        trades=52,
        share=0.20,
        assets={"BTC": 300.0, "ETH": 200.0, "SOL": -50.0},
        hold_dd=40.0,
        candidate_dd=5.0,
        periods={"2025H1": 100.0, "2025H2": 200.0, "2026Q1": 50.0},
    )
    verdict = oos_trend_verdict(good)
    assert verdict["verdict"] == "SUFFICIENT_EVIDENCE_FOR_PAPER"
    assert all(check["result"] == "PASS" for check in verdict["checks"])

    concentrated = dict(good)
    concentrated["runs"] = dict(good["runs"])
    concentrated["runs"]["OOS:BASE"] = dict(good["runs"]["OOS:BASE"])
    concentrated["runs"]["OOS:BASE"]["combined"] = dict(
        good["runs"]["OOS:BASE"]["combined"], largest_trade_share_of_net=0.80
    )
    verdict = oos_trend_verdict(concentrated)
    assert verdict["verdict"] == "NOT_SUFFICIENT_EVIDENCE"
    assert any("no_single_trade_carries_the_net" in reason for reason in verdict["reasons"])

    single_asset = _oos_payload(
        oos_net=500.0,
        stress_net=400.0,
        trades=52,
        share=0.10,
        assets={"BTC": 500.0, "ETH": -10.0, "SOL": -10.0},
        hold_dd=40.0,
        candidate_dd=5.0,
        periods={"2025H1": 100.0, "2025H2": 200.0, "2026Q1": 50.0},
    )
    verdict = oos_trend_verdict(single_asset)
    assert verdict["verdict"] == "NOT_SUFFICIENT_EVIDENCE"
    assert any("assets_positive" in reason for reason in verdict["reasons"])

    unpowered = _oos_payload(
        oos_net=500.0,
        stress_net=400.0,
        trades=5,
        share=0.10,
        assets={"BTC": 500.0, "ETH": 10.0, "SOL": 10.0},
        hold_dd=40.0,
        candidate_dd=5.0,
        periods={"2025H1": 100.0, "2025H2": 200.0, "2026Q1": 50.0},
    )
    assert oos_trend_verdict(unpowered)["verdict"] == "UNPOWERED"


def test_the_closure_verifier_sees_the_rules_it_checks() -> None:
    """The verifier's restated rule must be the rule the artefact declares."""
    from importlib import util
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    spec = util.spec_from_file_location(
        "edge01_closure_verify", root / "scripts" / "edge01_closure_verify.py"
    )
    assert spec and spec.loader
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.EXPECTED_H6_RULE["variant_arm"] == RETEST_H6_DECISION["variant_arm"]
    assert module.EXPECTED_H6_RULE["min_fill_rate"] == RETEST_H6_DECISION["min_fill_rate"]
    assert module.RETEST_EXPIRY_BARS == RETEST_PARAMS["retest_expiry_bars"]
    assert pytest.approx(module.TOL) == 0.05
