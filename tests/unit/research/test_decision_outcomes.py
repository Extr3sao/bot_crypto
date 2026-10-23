"""CAP-003 — focused tests for the deterministic outcome evaluator + scorecard.

What is pinned here is the *measurement*, not the strategy: the outcome window is
causal and stops exactly at the horizon, a premature horizon is refused, the
frozen deterministic rule has no look-ahead, costs are shared and cash pays
nothing, the evaluator never guesses a free-text invalidation, hashes are
sensitive to any change, comparator D matches the analyst's own distribution, and
the scorecard refuses an edge verdict below its declared sample floor.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.research import agentic_baselines as ab
from trading_bot.research import agentic_contracts as ac
from trading_bot.research import alpha_scorecard as asc
from trading_bot.research import decision_outcomes as do
from trading_bot.research import real_market_context as rmc

BAR = 14_400
#: Aligned to a 4H boundary, so every horizon lands on a real bar close.
DT = BAR * 118_055
ROUND_TRIP = ab.DEFAULT_COST_MODEL.round_trip_fraction


def _bar(
    open_time: int, close: float, *, high: float | None = None, low: float | None = None
) -> OHLCV:
    return OHLCV(
        symbol="BTC/USDT",
        timestamp=open_time * 1_000,
        open=close,
        high=close * 1.001 if high is None else high,
        low=close * 0.999 if low is None else low,
        close=close,
        volume=1.0,
    )


def _rows_4h(
    *, n_before: int = 8, n_after: int = 6, start: float = 100.0, step: float = 1.0
) -> list[OHLCV]:
    rows: list[OHLCV] = []
    open_time = DT - n_before * BAR
    price = start
    for _ in range(n_before + n_after):
        rows.append(_bar(open_time, price))
        open_time += BAR
        price += step
    return rows


def _zigzag_rows(
    *, n_before: int = 40, n_after: int = 10, up: float = 0.6, down: float = -0.4
) -> list[OHLCV]:
    """A drift with a sawtooth, so RSI stays in range while MACD keeps a sign."""
    rows: list[OHLCV] = []
    open_time = DT - n_before * BAR
    price = 100.0
    for index in range(n_before + n_after):
        rows.append(_bar(open_time, price))
        open_time += BAR
        price += up if index % 2 == 0 else down
    return rows


def _daily_rows(count: int = 220, *, final: float = 130.0) -> list[OHLCV]:
    rows = [_bar(DT - (count - index) * 86_400, 100.0) for index in range(count)]
    rows[-1] = _bar(DT - 86_400, final)
    return rows


def _record(
    direction: str = "LONG", *, horizon: str = "24H", confidence: float = 0.6
) -> ac.DecisionRecord:
    return ac.seal_decision_record(
        timestamp=DT,
        prompt_version="CAP-003-TEST-NOT-AN-LLM-RUN",
        evidence_snapshot_hash=ac.payload_digest({"test": True}),
        agent_output={
            "analyst": {
                "asset": "BINANCE:BTCUSDT",
                "decision": direction,
                "horizon": horizon,
                "confidence": confidence,
                "decision_time": DT,
            }
        },
        critic_output=None,
        decision=direction,
    )


def _outcome(direction: str = "LONG", **overrides: Any) -> do.DecisionOutcome:
    base: dict[str, Any] = {
        "record": _record(direction),
        "asset": "BINANCE:BTCUSDT",
        "horizon": "24H",
        "rows": _rows_4h(),
    }
    base.update(overrides)
    return do.evaluate_decision(**base)


# --------------------------------------------------------------------------- #
# the causal window
# --------------------------------------------------------------------------- #


def test_window_entry_closes_at_the_decision_time() -> None:
    window = do.build_window(rows=_rows_4h(), decision_time=DT, horizon="24H")
    assert window.entry_close_time == DT
    assert window.exit_close_time == DT + 86_400
    assert window.exit_open_time == DT + 86_400 - BAR
    assert window.bars_used == 7
    assert window.entry_price == pytest.approx(107.0)
    assert window.exit_price == pytest.approx(113.0)


def test_window_refuses_a_premature_horizon() -> None:
    with pytest.raises(do.HorizonNotMaturedError):
        do.build_window(rows=_rows_4h(n_after=0), decision_time=DT, horizon="24H")


def test_window_ignores_bars_after_the_horizon() -> None:
    rows = [*_rows_4h(), _bar(DT + 6 * BAR, 10_000.0)]
    window = do.build_window(rows=rows, decision_time=DT, horizon="24H")
    assert window.exit_price == pytest.approx(113.0)
    assert window.bars_used == 7


def test_window_ignores_a_live_candle_at_the_decision_time() -> None:
    rows = [*_rows_4h(), _bar(DT, 999.0)]
    window = do.build_window(rows=rows, decision_time=DT, horizon="24H")
    assert window.entry_price == pytest.approx(107.0)
    assert window.entry_close_time == DT


def test_window_requires_a_completed_entry_bar() -> None:
    with pytest.raises(do.HorizonNotMaturedError):
        do.build_window(rows=_rows_4h(n_before=0, n_after=8), decision_time=DT, horizon="24H")


def test_horizon_seconds_are_the_frozen_contract() -> None:
    assert do.HORIZON_SECONDS == {"4H": 14_400, "24H": 86_400, "72H": 259_200}
    with pytest.raises(ValueError):
        do.horizon_seconds("1H")


# --------------------------------------------------------------------------- #
# the frozen deterministic comparator (B)
# --------------------------------------------------------------------------- #


def test_rule_is_honest_without_sma200_history() -> None:
    direction, reason = do.deterministic_trend_direction(
        rows_4h=_rows_4h(), daily_rows=_daily_rows(count=50), decision_time=DT
    )
    assert direction == "NO_TRADE"
    assert reason == ab.INSUFFICIENT_SMA200_HISTORY


def test_rule_refuses_an_overbought_monotonic_market() -> None:
    direction, reason = do.deterministic_trend_direction(
        rows_4h=_rows_4h(n_before=40, n_after=10, step=1.0),
        daily_rows=_daily_rows(final=130.0),
        decision_time=DT,
    )
    assert (direction, reason) == ("NO_TRADE", do.REASON_RSI_EXTREME)


def test_rule_refuses_a_mixed_signal() -> None:
    direction, reason = do.deterministic_trend_direction(
        rows_4h=_zigzag_rows(up=-0.6, down=0.4),
        daily_rows=_daily_rows(final=130.0),
        decision_time=DT,
    )
    assert (direction, reason) == ("NO_TRADE", do.REASON_SIGNAL_MIXED)


def test_rule_is_long_when_trend_and_momentum_agree_up() -> None:
    direction, reason = do.deterministic_trend_direction(
        rows_4h=_zigzag_rows(), daily_rows=_daily_rows(final=130.0), decision_time=DT
    )
    assert (direction, reason) == ("LONG", "TREND_UP_MACD_LONG")


def test_rule_shorts_a_confirmed_downtrend() -> None:
    direction, reason = do.deterministic_trend_direction(
        rows_4h=_zigzag_rows(up=-0.6, down=0.4),
        daily_rows=_daily_rows(final=90.0),
        decision_time=DT,
    )
    assert (direction, reason) == ("SHORT", "TREND_DOWN_MACD_SHORT")


def test_rule_is_honest_without_macd_history() -> None:
    direction, reason = do.deterministic_trend_direction(
        rows_4h=_zigzag_rows(n_before=10, n_after=10),
        daily_rows=_daily_rows(final=130.0),
        decision_time=DT,
    )
    assert (direction, reason) == ("NO_TRADE", do.REASON_MACD_HISTORY_INSUFFICIENT)


def test_rule_ignores_bars_after_the_decision_time() -> None:
    rows = _rows_4h()
    bumped = [*rows, *[_bar(DT + (4 + i) * BAR, 1.0) for i in range(4)]]
    first = do.deterministic_trend_direction(
        rows_4h=rows, daily_rows=_daily_rows(), decision_time=DT
    )
    second = do.deterministic_trend_direction(
        rows_4h=bumped, daily_rows=_daily_rows(), decision_time=DT
    )
    assert first == second


def test_rule_is_a_pure_function_of_its_inputs() -> None:
    args = {
        "rows_4h": _rows_4h(step=-1.0),
        "daily_rows": _daily_rows(final=90.0),
        "decision_time": DT,
    }
    assert do.deterministic_trend_direction(**args) == do.deterministic_trend_direction(**args)


# --------------------------------------------------------------------------- #
# the outcome record
# --------------------------------------------------------------------------- #


def test_long_outcome_arithmetic_and_label() -> None:
    outcome = _outcome("LONG")
    assert outcome.gross_return == pytest.approx(113.0 / 107.0 - 1.0)
    assert outcome.costs == pytest.approx(ROUND_TRIP)
    assert outcome.net_return == pytest.approx(outcome.gross_return - ROUND_TRIP)
    assert outcome.outcome == do.OUTCOME_WIN
    assert outcome.direction_correct is True
    assert outcome.mfe > 0.0
    assert outcome.is_verified()


def test_short_outcome_inverts_the_direction() -> None:
    outcome = _outcome("SHORT")
    assert outcome.gross_return == pytest.approx(1.0 - 113.0 / 107.0)
    assert outcome.outcome == do.OUTCOME_LOSS
    assert outcome.direction_correct is False
    assert outcome.mae < 0.0


def test_no_trade_is_a_real_decision_that_pays_nothing() -> None:
    outcome = _outcome("NO_TRADE")
    assert outcome.gross_return == 0.0
    assert outcome.costs == 0.0
    assert outcome.net_return == 0.0
    assert outcome.outcome == do.OUTCOME_NO_TRADE
    assert outcome.direction_correct is False
    assert outcome.is_verified()


def test_flat_outcome_when_the_net_is_exactly_zero() -> None:
    rows = _rows_4h(step=0.0)
    outcome = do.evaluate_decision(
        record=_record("LONG"), asset="BINANCE:BTCUSDT", horizon="24H", rows=rows
    )
    assert outcome.gross_return == 0.0
    assert outcome.outcome == do.OUTCOME_LOSS  # costs alone make a flat market a loss
    assert outcome.direction_correct is False


def test_evaluator_refuses_an_unsealed_record() -> None:
    tampered = dataclasses.replace(_record("LONG"), decision="SHORT")
    assert tampered.is_verified() is False
    with pytest.raises(ValueError):
        do.evaluate_decision(
            record=tampered, asset="BINANCE:BTCUSDT", horizon="24H", rows=_rows_4h()
        )


def test_free_text_invalidation_is_never_guessed() -> None:
    outcome = _outcome("LONG")
    assert outcome.invalidation_hit is None
    assert outcome.invalidation_rule == do.INVALIDATION_NOT_MACHINE_CHECKABLE


def test_structured_invalidation_is_honoured_when_supplied() -> None:
    hit = do.evaluate_decision(
        record=_record("LONG"),
        asset="BINANCE:BTCUSDT",
        horizon="24H",
        rows=_rows_4h(),
        invalidation_price=500.0,
    )
    missed = do.evaluate_decision(
        record=_record("LONG"),
        asset="BINANCE:BTCUSDT",
        horizon="24H",
        rows=_rows_4h(),
        invalidation_price=1.0,
    )
    assert (hit.invalidation_hit, hit.invalidation_rule) == (True, do.INVALIDATION_STRUCTURED_PRICE)
    assert missed.invalidation_hit is False


def test_outcome_hash_is_sensitive_to_any_change() -> None:
    outcome = _outcome("LONG")
    changed = dataclasses.replace(outcome, net_return=outcome.net_return + 1e-9)
    assert changed.hash() != outcome.outcome_hash
    assert changed.is_verified() is False
    assert do.outcome_payload_hash(outcome.hashable_dict()) == outcome.outcome_hash


def test_outcome_evidence_hash_is_stable_and_recorded() -> None:
    first = _outcome("LONG")
    second = _outcome("LONG")
    assert first.evidence_hash == second.evidence_hash
    assert len(first.evidence_hash) == 64
    assert first.evaluator == do.EVALUATOR_ID
    assert len(first.snapshot_hash) == 64
    assert first.asset == "BINANCE:BTCUSDT"


# --------------------------------------------------------------------------- #
# performance: record + outcome + seal-time comparators
# --------------------------------------------------------------------------- #


def test_performance_joins_the_seal_and_the_outcome() -> None:
    record = _record("LONG")
    outcome = _outcome("LONG", record=record)
    performance = do.build_performance(
        record=record, outcome=outcome, rows_4h=_rows_4h(), daily_rows=_daily_rows()
    )
    assert performance.decision_hash == record.decision_hash
    assert performance.outcome_hash == outcome.outcome_hash
    assert performance.decision_id == "DEC-" + record.decision_hash[:16]
    assert performance.decision_id == outcome.decision_id
    assert performance.is_verified()
    assert performance.cost_bps_per_side == 10.0
    assert performance.round_trip_cost == pytest.approx(ROUND_TRIP)


def test_performance_carries_b_and_c_but_never_d() -> None:
    record = _record("LONG")
    outcome = _outcome("LONG", record=record)
    performance = do.build_performance(
        record=record, outcome=outcome, rows_4h=_rows_4h(), daily_rows=_daily_rows()
    )
    produced = {item.baseline_id for item in performance.comparisons}
    assert produced == {do.BASELINE_ID_DETERMINISTIC, do.BASELINE_ID_BUY_AND_HOLD}
    assert do.BASELINE_ID_RANDOM_MATCHED not in produced
    buy_and_hold = performance.comparison(do.BASELINE_ID_BUY_AND_HOLD)
    assert buy_and_hold is not None
    assert buy_and_hold.net_return == pytest.approx(outcome.gross_return - ROUND_TRIP)
    assert performance.edge_vs(do.BASELINE_ID_RANDOM_MATCHED) is None


def test_performance_rule_stays_causal_at_seal_time() -> None:
    rows = _rows_4h()
    record = _record("LONG")
    outcome = _outcome("LONG", record=record)
    first = do.build_performance(
        record=record, outcome=outcome, rows_4h=rows, daily_rows=_daily_rows()
    )
    wider = [*rows, *[_bar(DT + (4 + i) * BAR, 5_000.0) for i in range(6)]]
    second = do.build_performance(
        record=record, outcome=outcome, rows_4h=wider, daily_rows=_daily_rows()
    )
    assert first.comparisons == second.comparisons


def test_performance_refuses_a_mismatched_outcome() -> None:
    record = _record("LONG")
    other = _record("SHORT")
    outcome = _outcome("SHORT", record=other)
    with pytest.raises(ValueError):
        do.build_performance(record=record, outcome=outcome, rows_4h=_rows_4h())


def test_performance_hash_recomputes_from_its_payload() -> None:
    record = _record("LONG")
    outcome = _outcome("LONG", record=record)
    performance = do.build_performance(record=record, outcome=outcome, rows_4h=_rows_4h())
    assert do.performance_payload_hash(performance.hashable_dict()) == performance.evaluation_hash


# --------------------------------------------------------------------------- #
# comparator D
# --------------------------------------------------------------------------- #


def test_random_directions_are_an_exact_permutation() -> None:
    directions = ["LONG"] * 5 + ["SHORT"] * 3 + ["NO_TRADE"] * 2
    assigned = do.matched_random_directions(directions, seed=asc.RANDOM_BASELINE_SEED)
    assert sorted(assigned) == sorted(directions)
    assert do.direction_distribution(assigned) == do.direction_distribution(directions)


def test_random_directions_are_reproducible_and_seed_sensitive() -> None:
    directions = ["LONG", "SHORT", "NO_TRADE", "LONG", "LONG", "SHORT"]
    first = do.matched_random_directions(directions, seed=1)
    assert first == do.matched_random_directions(directions, seed=1)
    assert set(do.matched_random_directions(directions, seed=2)) == set(first)


def test_direction_distribution_rejects_an_unknown_direction() -> None:
    with pytest.raises(ValueError):
        do.direction_distribution(["MAYBE"])


# --------------------------------------------------------------------------- #
# scorecard
# --------------------------------------------------------------------------- #


def _perf(
    index: int,
    *,
    decision: str = "LONG",
    net_return: float = 0.01,
    confidence: float = 0.6,
    direction_correct: bool = True,
) -> do.DecisionPerformance:
    entry = 100.0
    exit_price = entry * 1.01
    directional = decision != "NO_TRADE"
    gross = 0.0
    if decision == "LONG":
        gross = exit_price / entry - 1.0
    elif decision == "SHORT":
        gross = 1.0 - exit_price / entry
    return do.DecisionPerformance(
        decision_id=f"DEC-{index:016x}",
        decision_hash=f"{index:064x}",
        outcome_hash=f"{index + 1:064x}",
        asset="BINANCE:BTCUSDT" if index % 2 == 0 else "BINANCE:ETHUSDT",
        decision=decision,
        horizon="24H",
        confidence=confidence,
        decision_time=DT,
        evaluation_time=DT + 86_400,
        entry_price=entry,
        exit_price=exit_price,
        gross_return=gross,
        costs=ROUND_TRIP if directional else 0.0,
        net_return=net_return,
        direction_correct=direction_correct if directional else False,
        outcome="WIN" if net_return > 0 else "LOSS",
        invalidation_hit=None,
        mfe=0.02 if directional else 0.0,
        mae=-0.01 if directional else 0.0,
        comparisons=(
            do.BaselineComparison(
                baseline_id=do.BASELINE_ID_DETERMINISTIC,
                direction="NO_TRADE" if index % 3 == 0 else "LONG",
                available=True,
                gross_return=0.005,
                costs=0.0 if index % 3 == 0 else ROUND_TRIP,
                net_return=0.0 if index % 3 == 0 else 0.005 - ROUND_TRIP,
                rule_version=do.DETERMINISTIC_RULE_VERSION,
            ),
            do.BaselineComparison(
                baseline_id=do.BASELINE_ID_BUY_AND_HOLD,
                direction="LONG",
                available=True,
                gross_return=gross,
                costs=ROUND_TRIP,
                net_return=gross - ROUND_TRIP,
                rule_version="BUY_AND_HOLD",
            ),
        ),
        cost_bps_per_side=10.0,
        round_trip_cost=ROUND_TRIP,
        source="TEST",
    ).with_hash()


def test_scorecard_is_not_measurable_without_evaluations() -> None:
    scorecard = asc.alpha_scorecard([])
    assert scorecard["n_decisions_evaluated"] == 0
    assert scorecard["gate"]["conclusion"] == asc.CONCLUSION_NOT_MEASURABLE
    assert scorecard["comparators"][do.BASELINE_ID_RANDOM_MATCHED] is None
    assert scorecard["alpha_claimed"] is False
    assert scorecard["profitability_status"] == "NOT_DEMONSTRATED"


def test_scorecard_refuses_an_edge_verdict_below_the_sample_floor() -> None:
    performances = [_perf(index, net_return=0.05) for index in range(30)]
    scorecard = asc.alpha_scorecard(performances)
    assert scorecard["n_decisions_evaluated"] == 30
    assert scorecard["gate"]["conclusion"] == asc.CONCLUSION_INSUFFICIENT_SAMPLE
    assert scorecard["gate"]["status"] == "INSUFFICIENT_SAMPLE"
    assert scorecard["sample"]["checkpoint_reached"] == 20
    assert scorecard["sample"]["next_checkpoint"] == 50
    assert asc.MIN_EVALUABLE_DECISIONS == 100


def test_scorecard_verdict_is_available_at_the_declared_floor() -> None:
    winning = [_perf(index, net_return=0.05) for index in range(100)]
    scorecard = asc.alpha_scorecard(winning)
    assert scorecard["sample"]["checkpoint_reached"] == 100
    assert scorecard["gate"]["conclusion"] == asc.CONCLUSION_EDGE_POSITIVE_PRELIMINARY
    assert scorecard["kpi_agentic_decision_edge"] == 0

    losing = [_perf(index, net_return=-0.05) for index in range(100)]
    assert asc.alpha_scorecard(losing)["gate"]["conclusion"] == asc.CONCLUSION_EDGE_NON_POSITIVE


def test_scorecard_recomputes_the_agent_and_comparator_means() -> None:
    performances = [_perf(index, net_return=0.02) for index in range(10)]
    scorecard = asc.alpha_scorecard(performances)
    assert scorecard["agent"]["mean_net_return"] == pytest.approx(0.02)
    assert scorecard["agent"]["hit_rate_directional"] == pytest.approx(1.0)
    buy_and_hold = scorecard["comparators"][do.BASELINE_ID_BUY_AND_HOLD]
    assert buy_and_hold["n"] == 10
    assert scorecard["incremental_edges"][do.BASELINE_ID_BUY_AND_HOLD] == pytest.approx(
        0.02 - buy_and_hold["mean_net_return"]
    )


def test_scorecard_random_comparator_matches_the_distribution_and_seed() -> None:
    performances = [
        _perf(index, decision="LONG" if index % 2 == 0 else "NO_TRADE") for index in range(8)
    ]
    first = asc.alpha_scorecard(performances)
    second = asc.alpha_scorecard(performances)
    random_stats = first["comparators"][do.BASELINE_ID_RANDOM_MATCHED]
    assert random_stats["seed"] == asc.RANDOM_BASELINE_SEED
    assert random_stats["distribution"] == do.direction_distribution(
        [item.decision for item in performances]
    )
    assert (
        random_stats["assignment"]
        == second["comparators"][do.BASELINE_ID_RANDOM_MATCHED]["assignment"]
    )


def test_scorecard_counts_no_trade_as_a_real_decision() -> None:
    performances = [_perf(0, decision="NO_TRADE", net_return=0.0)] + [
        _perf(index, net_return=0.01) for index in range(1, 5)
    ]
    scorecard = asc.alpha_scorecard(performances)
    assert scorecard["n_decisions_evaluated"] == 5
    assert scorecard["n_no_trade"] == 1
    assert scorecard["n_directional"] == 4
    assert scorecard["action_rate"] == pytest.approx(0.8)
    assert scorecard["no_trade"]["n"] == 1


def test_scorecard_breakdowns_are_per_asset_and_per_horizon() -> None:
    scorecard = asc.alpha_scorecard([_perf(index) for index in range(4)])
    assert set(scorecard["per_asset"]) == {"BINANCE:BTCUSDT", "BINANCE:ETHUSDT"}
    assert set(scorecard["per_horizon"]) == {"24H"}
    assert scorecard["per_horizon"]["24H"]["n"] == 4


def test_random_matched_baseline_distribution_helper() -> None:
    assert do.direction_distribution([]) == {"LONG": 0, "SHORT": 0, "NO_TRADE": 0}
    assert rmc.CAMPAIGN_ASSETS == (
        "BINANCE:BTCUSDT",
        "BINANCE:ETHUSDT",
        "BINANCE:SOLUSDT",
        "BINANCE:XRPUSDT",
    )
