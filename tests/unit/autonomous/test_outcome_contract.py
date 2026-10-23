"""Outcome contract: availability by bar CLOSE, and idempotent resolution (§6).

Two hard rules are exercised here:

* ``reference_price_time_ms <= decision_time_ms < outcome_time_ms`` — a bar
  provides information when it CLOSES, never when it opens, in both
  directions (the entry reference and the outcome);
* ``OutcomeKey = decision_id + horizon`` — reprocessing the same decision with
  the same horizon and the same market data cannot create a second outcome.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from trading_bot.autonomous.contracts import DecisionMode, OutcomeRecord, OutcomeStatus
from trading_bot.autonomous.outcomes import OutcomeEvaluator
from trading_bot.autonomous.pit import availability_ms, closed_bar_slice, infer_bar_interval_ms
from trading_bot.autonomous.trace import DecisionTraceStore

from .helpers import bars
from .test_contracts import _proposal, _trace

BAR_MS = 5 * 60 * 1000
TS0 = 1_700_000_000_000


def _trace_for_outcome(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "proposal": _proposal(
            market_time_ms=TS0,
            decision_time_ms=TS0,
            horizon_minutes=5.0,
            entry_reference=100.0,
            direction="LONG",
            expected_gross_edge_bps=4.0,
            expected_cost_bps=21.0,
            expected_net_edge_bps=-17.0,
        ).to_dict(),
        "market_time_ms": TS0,
        "decision_time_ms": TS0,
        "mode": DecisionMode.SHADOW_TRADE,
        "classification": "COST_KILLED",
        "shadow": {"marked_shadow": True},
    }
    base.update(overrides)
    return _trace(**base)


# -- PIT availability -------------------------------------------------------


def test_bar_availability_is_its_close() -> None:
    series = bars("BTC/USDT", 3)
    interval = infer_bar_interval_ms(series)
    assert interval == BAR_MS
    assert availability_ms(series[0], interval) == TS0 + BAR_MS
    assert availability_ms(series[0], None) == TS0  # conservative fallback


def test_the_forming_bar_is_not_usable_at_the_decision_time() -> None:
    series = bars("BTC/USDT", 4)
    # A decision exactly at the open of bar 3: bar 3 has not closed yet.
    usable = closed_bar_slice(series, series[2].timestamp)
    assert [b.timestamp for b in usable] == [series[0].timestamp, series[1].timestamp]


def test_outcome_contract_temporal_ordering() -> None:
    evaluator = OutcomeEvaluator()
    series = bars("BTC/USDT", 7, rising=True)
    # Decision at the CLOSE of bar 1 (index 1): the reference bar has closed.
    decision_ts = TS0 + 2 * BAR_MS
    trace = _trace_for_outcome(
        market_time_ms=TS0 + BAR_MS,
        decision_time_ms=decision_ts,
        proposal=_proposal(
            market_time_ms=TS0 + BAR_MS,
            decision_time_ms=decision_ts,
            horizon_minutes=5.0,
            entry_reference=100.0,
            direction="LONG",
            expected_gross_edge_bps=4.0,
            expected_cost_bps=21.0,
            expected_net_edge_bps=-17.0,
        ).to_dict(),
    )
    evaluation = evaluator.evaluate(trace=trace, bars=series)
    assert evaluation.status is OutcomeStatus.RESOLVED
    record = evaluation.record
    assert record is not None
    assert record.reference_price_time_ms <= record.decision_time_ms
    assert record.decision_time_ms < record.outcome_time_ms
    assert record.future_price_time_ms == record.outcome_time_ms
    # The reference bar closed exactly at the decision instant.
    assert record.reference_price_time_ms == decision_ts
    assert record.market_time_ms <= record.decision_time_ms


def test_reference_price_time_is_a_close_never_an_open() -> None:
    evaluator = OutcomeEvaluator()
    series = bars("BTC/USDT", 7, rising=True)
    # Decision one millisecond before the close of bar 1 (index 1).
    decision_ts = TS0 + 2 * BAR_MS - 1
    trace = _trace_for_outcome(
        market_time_ms=TS0,
        decision_time_ms=decision_ts,
        proposal=_proposal(
            market_time_ms=TS0,
            decision_time_ms=decision_ts,
            horizon_minutes=5.0,
            entry_reference=100.0,
            direction="LONG",
            expected_gross_edge_bps=4.0,
            expected_cost_bps=21.0,
            expected_net_edge_bps=-17.0,
        ).to_dict(),
    )
    record = evaluator.evaluate(trace=trace, bars=series).record
    assert record is not None
    # Only bar 0 had closed by then: its close is the availability instant.
    assert record.reference_price_time_ms == TS0 + BAR_MS
    assert record.reference_price_time_ms < record.decision_time_ms


def test_outcome_record_rejects_a_reference_time_in_the_future() -> None:
    record = OutcomeRecord(
        run_id="r",
        decision_id="d",
        asset="BTC",
        symbol="BTC/USDT",
        strategy_id="ema_crossover@5m",
        mode=DecisionMode.SHADOW_TRADE,
        direction="LONG",
        decision_time_ms=TS0,
        outcome_time_ms=TS0 + BAR_MS,
        horizon_minutes=5.0,
        entry_reference=100.0,
        outcome_price=101.0,
        gross_return_bps=1.0,
        estimated_cost_bps=21.0,
        net_hypothetical_bps=-20.0,
        mfe_bps=1.0,
        mae_bps=-1.0,
        direction_correct=True,
    )
    with pytest.raises(ValueError, match="reference_price_time_ms"):
        replace(record, reference_price_time_ms=TS0 + 1)
    with pytest.raises(ValueError, match="outcome_time_ms must be >"):
        replace(record, outcome_time_ms=TS0)


# -- idempotency ------------------------------------------------------------


def test_outcome_key_is_the_stable_decision_plus_horizon_identity() -> None:
    evaluator = OutcomeEvaluator()
    record = evaluator.evaluate(
        trace=_trace_for_outcome(), bars=bars("BTC/USDT", 6, rising=True)
    ).record
    assert record is not None
    assert record.outcome_key == f"{record.decision_id}@5m"
    # Round-trips through its persisted form, key included and derived.
    assert OutcomeRecord.from_dict(record.to_dict()).outcome_key == record.outcome_key
    assert "outcome_key" in record.to_dict()


def test_appending_the_same_outcome_twice_creates_one_record(tmp_path: Path) -> None:
    store = DecisionTraceStore(tmp_path)
    record = (
        OutcomeEvaluator()
        .evaluate(trace=_trace_for_outcome(), bars=bars("BTC/USDT", 6, rising=True))
        .record
    )
    assert record is not None
    first = store.append_outcome(record)
    second = store.append_outcome(replace(record, created_at_ms=999))
    assert first.outcome_key == second.outcome_key
    assert store.outcome_keys() == {record.outcome_key}
    assert len(store.read_outcomes()) == 1
    # The stored record wins: the duplicate never overwrites it.
    assert store.read_outcomes()[0].created_at_ms == record.created_at_ms


def test_pending_then_resolved_is_idempotent(tmp_path: Path) -> None:
    """PENDING → RESOLVED exactly once, no matter how often it is reprocessed."""
    store = DecisionTraceStore(tmp_path)
    trace = _trace_for_outcome()
    trace = store.append(trace)
    evaluator = OutcomeEvaluator()
    short = bars("BTC/USDT", 1, rising=True)  # nothing has closed yet
    first = evaluator.resolve_pending(traces=[trace], bars_by_symbol={"BTC/USDT": short})
    assert first[0].status is OutcomeStatus.PENDING_OUTCOME
    assert store.read_outcomes() == []

    long = bars("BTC/USDT", 8, rising=True)
    resolved = evaluator.resolve_pending(traces=[trace], bars_by_symbol={"BTC/USDT": long})
    assert resolved[0].status is OutcomeStatus.RESOLVED
    record = resolved[0].record
    assert record is not None
    store.append_outcome(record)
    assert len(store.read_outcomes()) == 1

    # Reprocessing with the same market data must not add anything.
    again = evaluator.resolve_pending(
        traces=[trace],
        bars_by_symbol={"BTC/USDT": long},
        already_resolved=store.resolved_decision_ids(),
    )
    assert again == []
    replay = store.append_outcome(record)
    assert replay.outcome_key == record.outcome_key
    assert len(store.read_outcomes()) == 1
    assert store.verify_chain().ok
