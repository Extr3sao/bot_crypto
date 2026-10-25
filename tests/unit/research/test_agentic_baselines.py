"""CAP-002 — focused tests for the deterministic baseline outcome producer.

Only the wiring and arithmetic of the producer are tested here: cash is exactly
zero, buy-and-hold is exact-window, simple trend is the frozen RFC-039 SMA(200)
rule with no look-ahead, the passive benchmark is honest about a missing
mapping, costs are consistent, and the sealed decision stays immutable while a
separate future-only outcome links back to it by id + hash.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from trading_bot.research import agentic_baselines as ab
from trading_bot.research import agentic_contracts as ac
from trading_bot.research import small_capital_v1 as sc

DECISION_TIME = 1_600_000_000 + 200 * 86_400


def _seal(direction: str = "LONG") -> ac.DecisionRecord:
    return ac.seal_decision_record(
        timestamp=DECISION_TIME,
        prompt_version="CAP-002-SYNTHETIC-DRY-RUN-NOT-AN-LLM-RUN",
        evidence_snapshot_hash=ac.payload_digest({"synthetic": True}),
        agent_output={"_synthetic": True, "direction": direction},
        critic_output=None,
        decision=direction,
    )


def _daily_bars(count: int = 200, *, final_close: float | None = None) -> list[ab.DailyBar]:
    bars = [
        ab.DailyBar(open_time=1_600_000_000 + index * 86_400, close=100.0 + index * 0.5)
        for index in range(count)
    ]
    if final_close is not None:
        bars[-1] = dataclasses.replace(bars[-1], close=final_close)
    return bars


def _outcome(direction: str = "LONG", **overrides: Any) -> ab.OutcomeRecord:
    base: dict[str, Any] = {
        "record": _seal(direction),
        "asset": "BINANCE:BTCUSDT",
        "evaluation_time": DECISION_TIME + 86_400,
        "entry_reference": 100.0,
        "exit_reference": 110.0,
        "path": (105.0, 108.0, 110.0),
        "daily_bars": _daily_bars(),
    }
    base.update(overrides)
    return ab.build_outcome_record(**base)


# --------------------------------------------------------------------------- #
# cash baseline
# --------------------------------------------------------------------------- #


def test_cash_baseline_is_exactly_zero() -> None:
    cash = ab.cash_baseline()
    assert cash.baseline_id == "A_NO_TRADE_CASH"
    assert cash.exposure == 0.0
    assert cash.gross_return == 0.0
    assert cash.cost == 0.0
    assert cash.net_return == 0.0
    assert cash.available is True


# --------------------------------------------------------------------------- #
# buy-and-hold exact-window arithmetic
# --------------------------------------------------------------------------- #


def test_buy_and_hold_is_exact_window_arithmetic() -> None:
    model = ab.CostModel(fee_bps_per_side=10.0)
    outcome = ab.buy_and_hold_baseline(entry_price=100.0, exit_price=110.0, cost_model=model)
    assert outcome.exposure == 1.0
    assert outcome.gross_return == pytest.approx(0.10)
    assert outcome.cost == pytest.approx(0.002)  # 10 bps per side, round trip
    assert outcome.net_return == pytest.approx(0.098)
    assert outcome.available is True


def test_buy_and_hold_rejects_nonpositive_prices() -> None:
    model = ab.DEFAULT_COST_MODEL
    with pytest.raises(ValueError):
        ab.buy_and_hold_baseline(entry_price=0.0, exit_price=110.0, cost_model=model)
    with pytest.raises(ValueError):
        ab.buy_and_hold_baseline(entry_price=100.0, exit_price=-1.0, cost_model=model)


# --------------------------------------------------------------------------- #
# simple trend — canonical SMA200, no look-ahead, honest when short of history
# --------------------------------------------------------------------------- #


def test_simple_trend_reuses_rfc039_sma200_semantics() -> None:
    assert sc.SMA_WINDOW == 200
    bars = _daily_bars()
    closes = [bar.close for bar in bars]
    expected = sc.sma([float(value) for value in closes], sc.SMA_WINDOW)[-1]
    assert expected is not None
    outcome = ab.simple_trend_baseline(
        daily_bars=bars,
        decision_time=DECISION_TIME,
        entry_price=100.0,
        exit_price=110.0,
        cost_model=ab.DEFAULT_COST_MODEL,
    )
    assert outcome.available is True
    assert outcome.reason == "SIGNAL_LONG"
    assert closes[-1] > expected


def test_simple_trend_goes_to_cash_below_the_average() -> None:
    # A falling series ends below its own 200-bar average -> CASH, zero cost.
    bars = [
        ab.DailyBar(open_time=1_600_000_000 + index * 86_400, close=200.0 - index * 0.5)
        for index in range(200)
    ]
    outcome = ab.simple_trend_baseline(
        daily_bars=bars,
        decision_time=DECISION_TIME,
        entry_price=100.0,
        exit_price=110.0,
        cost_model=ab.DEFAULT_COST_MODEL,
    )
    assert outcome.available is True
    assert outcome.reason == "SIGNAL_CASH"
    assert outcome.exposure == 0.0
    assert outcome.cost == 0.0
    assert outcome.net_return == 0.0


def test_incomplete_daily_candle_is_excluded_no_lookahead() -> None:
    # 201 bars: the final candle opens exactly at decision_time, so it is still
    # in progress and must NOT be consumed. Its crash close would flip the signal.
    bars = _daily_bars(count=201, final_close=1.0)
    only_completed = ab.completed_daily_closes(bars, decision_time=DECISION_TIME)
    assert len(only_completed) == 200
    outcome = ab.simple_trend_baseline(
        daily_bars=bars,
        decision_time=DECISION_TIME,
        entry_price=100.0,
        exit_price=110.0,
        cost_model=ab.DEFAULT_COST_MODEL,
    )
    assert outcome.reason == "SIGNAL_LONG"


def test_future_bar_never_contributes() -> None:
    bars = [*_daily_bars(), ab.DailyBar(open_time=DECISION_TIME + 10 * 86_400, close=1.0)]
    closes = ab.completed_daily_closes(bars, decision_time=DECISION_TIME)
    assert closes[-1] == 100.0 + 199 * 0.5


def test_daily_bars_must_be_strictly_ascending() -> None:
    bars = [
        ab.DailyBar(open_time=100, close=1.0),
        ab.DailyBar(open_time=100, close=1.0),
    ]
    with pytest.raises(ValueError, match="strictly ascending"):
        ab.completed_daily_closes(bars, decision_time=10_000)


def test_insufficient_sma_history_is_honest() -> None:
    outcome = ab.simple_trend_baseline(
        daily_bars=_daily_bars(count=199),
        decision_time=DECISION_TIME,
        entry_price=100.0,
        exit_price=110.0,
        cost_model=ab.DEFAULT_COST_MODEL,
    )
    assert outcome.available is False
    assert outcome.reason == "INSUFFICIENT_SMA200_HISTORY"
    assert outcome.baseline_id == "C_SIMPLE_TREND_SMA200"


# --------------------------------------------------------------------------- #
# passive benchmark — only from a predeclared mapping
# --------------------------------------------------------------------------- #


def test_missing_passive_mapping_is_unavailable() -> None:
    assert ab.CANONICAL_PASSIVE_BENCHMARK_MAPPING == {}
    outcome = ab.passive_benchmark_baseline(
        asset="BINANCE:BTCUSDT",
        entry_price=100.0,
        exit_price=110.0,
        cost_model=ab.DEFAULT_COST_MODEL,
    )
    assert outcome.available is False
    assert outcome.reason == ab.NO_PREDECLARED_CANONICAL_MAPPING


def test_passive_benchmark_reuses_a_predeclared_mapping() -> None:
    mapping = {"BINANCE:BTCUSDT": "BINANCE:BTCUSDT"}
    outcome = ab.passive_benchmark_baseline(
        asset="BINANCE:BTCUSDT",
        entry_price=100.0,
        exit_price=110.0,
        cost_model=ab.DEFAULT_COST_MODEL,
        mapping=mapping,
    )
    assert outcome.available is True
    assert outcome.reason == "BENCHMARK=BINANCE:BTCUSDT"
    # Mapping the asset to itself is buy-and-hold exposure, flagged equivalent.
    assert outcome.economically_equivalent is True
    assert ab.passive_benchmark_equals_buy_and_hold(
        asset="BINANCE:BTCUSDT", mapping=mapping
    ) is True


def test_passive_benchmark_mapping_without_prices_is_unavailable() -> None:
    outcome = ab.passive_benchmark_baseline(
        asset="X",
        entry_price=None,
        exit_price=None,
        cost_model=ab.DEFAULT_COST_MODEL,
        mapping={"X": "SP:SPX"},
    )
    assert outcome.available is False
    assert outcome.reason == "BENCHMARK_PRICES_MISSING"


# --------------------------------------------------------------------------- #
# cost consistency
# --------------------------------------------------------------------------- #


def test_active_sleeves_share_one_cost_model() -> None:
    outcome = _outcome()
    baselines = {b.baseline_id: b for b in outcome.baseline_outcomes}
    assert baselines["A_NO_TRADE_CASH"].cost == 0.0
    assert baselines["B_BUY_AND_HOLD"].cost == pytest.approx(outcome.costs)
    assert baselines["C_SIMPLE_TREND_SMA200"].cost == pytest.approx(outcome.costs)
    # The agent is never the only side paying: B and C pay the same round trip.
    assert outcome.net_return == pytest.approx(outcome.gross_return - outcome.costs)


def test_cost_model_round_trip_and_guards() -> None:
    model = ab.CostModel(fee_bps_per_side=1.0, spread_bps_per_side=2.0, slippage_bps_per_side=3.0)
    assert model.round_trip_fraction == pytest.approx(0.0012)
    assert model.cost_for(0.0) == 0.0
    assert model.cost_for(1.0) == pytest.approx(0.0012)
    with pytest.raises(ValueError):
        ab.CostModel(fee_bps_per_side=-1.0)


# --------------------------------------------------------------------------- #
# immutability and outcome separation
# --------------------------------------------------------------------------- #


def test_sealed_decision_is_immutable_after_outcome() -> None:
    record = _seal()
    before = record.to_dict()
    ab.build_outcome_record(
        record=record,
        asset="BINANCE:BTCUSDT",
        evaluation_time=DECISION_TIME + 86_400,
        entry_reference=100.0,
        exit_reference=110.0,
        daily_bars=_daily_bars(),
    )
    assert record.to_dict() == before
    assert record.is_verified() is True
    assert record.decision_hash == before["decision_hash"]


def test_outcome_is_linked_by_id_and_hash() -> None:
    record = _seal()
    outcome = _outcome("LONG", record=record)
    assert outcome.decision_hash == record.decision_hash
    assert outcome.decision_id == ab.decision_id_for(record)
    assert outcome.decision_id.startswith("DEC-")


def test_outcome_does_not_contaminate_the_sealed_record() -> None:
    record = _seal()
    sealed_keys = set(record.to_dict())
    outcome_keys = set(_outcome(record=record).to_dict())
    # No snapshot / hypothesis / proposal field leaks into the outcome, and the
    # record keeps only its own six sealed fields plus the hash.
    assert outcome_keys.isdisjoint({"agent_output", "critic_output", "prompt_version"})
    assert sealed_keys == set(ac.SEALED_RECORD_FIELDS) | {"decision_hash"}


def test_outcome_refuses_an_unsealed_record() -> None:
    tampered = dataclasses.replace(_seal(), decision="SHORT")
    with pytest.raises(ValueError, match="unsealed or tampered"):
        ab.build_outcome_record(
            record=tampered,
            asset="BINANCE:BTCUSDT",
            evaluation_time=DECISION_TIME,
            entry_reference=100.0,
            exit_reference=110.0,
        )


# --------------------------------------------------------------------------- #
# synthetic provenance and evaluator wiring
# --------------------------------------------------------------------------- #


def test_synthetic_outcome_never_counts_toward_the_pilot() -> None:
    outcome = _outcome()
    assert outcome.source == "SYNTHETIC_FIXTURE"
    assert outcome.llm_invoked is False
    assert outcome.real_market_data is False
    assert outcome.agent_decision_real is False
    assert outcome.counts_toward_pilot is False


def test_generated_baseline_outcome_plugs_into_incremental_edge() -> None:
    outcome = _outcome()
    buy_hold = next(
        b for b in outcome.baseline_outcomes if b.baseline_id == ab.BASELINE_ID_BUY_AND_HOLD
    )
    baseline_edge = ac.incremental_edge(
        agent_outcome=outcome.net_return,
        baseline_outcome=buy_hold.net_return,
        cost=0.0,
        baseline=buy_hold.evaluator_label,
    )
    recorded = outcome.edge_by_id(ab.BASELINE_ID_BUY_AND_HOLD)
    assert recorded is not None
    assert recorded["edge"] == pytest.approx(baseline_edge.edge)
    assert recorded["evaluator_label"] == "B_BUY_AND_HOLD"


def test_long_agent_that_equals_buy_and_hold_has_zero_edge() -> None:
    # The mechanism demo must not manufacture edge where the exposure is identical.
    outcome = _outcome("LONG")
    assert outcome.edge_by_id(ab.BASELINE_ID_BUY_AND_HOLD)["edge"] == pytest.approx(0.0)
    # Cash is the only baseline it can beat, and only if the move is positive.
    assert outcome.edge_by_id(ab.BASELINE_ID_NO_TRADE)["edge"] > 0.0


def test_no_trade_decision_pays_no_cost_and_earns_nothing() -> None:
    outcome = _outcome("NO_TRADE")
    assert outcome.gross_return == 0.0
    assert outcome.costs == 0.0
    assert outcome.net_return == 0.0
    assert outcome.mfe == 0.0
    assert outcome.mae == 0.0
    # Cash and a flat agent tie exactly.
    assert outcome.edge_by_id(ab.BASELINE_ID_NO_TRADE)["edge"] == pytest.approx(0.0)


def test_short_direction_inverts_the_move() -> None:
    outcome = _outcome("SHORT")
    assert outcome.gross_return == pytest.approx(-0.10)
    assert outcome.net_return == pytest.approx(-0.102)
    assert outcome.edge_by_id(ab.BASELINE_ID_NO_TRADE)["edge"] < 0.0


def test_baseline_ids_match_the_canonical_producer_set() -> None:
    assert ab.BASELINE_IDS == (
        "A_NO_TRADE_CASH",
        "B_BUY_AND_HOLD",
        "C_SIMPLE_TREND_SMA200",
        "D_PASSIVE_ASSET_BENCHMARK",
    )
    # Every canonical id maps onto a label the frozen evaluator accepts.
    assert set(ab.EVALUATOR_LABELS) == set(ab.BASELINE_IDS)
    assert set(ab.EVALUATOR_LABELS.values()).issubset(set(ac.BASELINES))
    assert ab.G_AGENTIC_EDGE == "NOT_TESTED"


# --------------------------------------------------------------------------- #
# written dry-run artefacts (skipped until the runner has produced them)
# --------------------------------------------------------------------------- #

REPO = Path(__file__).resolve().parents[3]
HAS_CAP002_ARTIFACTS = (REPO / "reports" / "agentic-spike-cap002" / "CAP002_VERIFICATION.json").is_file()


@pytest.mark.skipif(not HAS_CAP002_ARTIFACTS, reason="CAP-002 dry run not generated yet")
def test_dry_run_verification_passed() -> None:
    verification = json.loads(
        (REPO / "reports" / "agentic-spike-cap002" / "CAP002_VERIFICATION.json").read_text(encoding="utf-8")
    )
    assert verification["status"] == "PASS"
    assert verification["mismatches"] == 0
    assert verification["false_success"] == 0
    assert verification["passed"] == verification["total"]


@pytest.mark.skipif(not HAS_CAP002_ARTIFACTS, reason="CAP-002 dry run not generated yet")
def test_dry_run_never_presents_synthetic_data_as_real() -> None:
    outcome = json.loads(
        (REPO / "reports" / "agentic-spike-cap002" / "CAP002_OUTCOME_RECORD.json").read_text(encoding="utf-8")
    )
    assert outcome["source"] == "SYNTHETIC_FIXTURE"
    assert outcome["counts_toward_pilot"] is False
    assert outcome["real_market_data"] is False
    assert outcome["llm_invoked"] is False
