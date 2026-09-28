"""Trace store / replay / outcome evaluation / experience learning."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from trading_bot.autonomous.contracts import (
    DecisionMode,
    OutcomeRecord,
    OutcomeStatus,
    ReplayStatus,
)
from trading_bot.autonomous.experience import (
    MAX_PRIORITY_ADJUSTMENT,
    MIN_SAMPLES_FOR_ADJUSTMENT,
    StrategyPerformanceStore,
)
from trading_bot.autonomous.outcomes import OutcomeEvaluator
from trading_bot.autonomous.trace import DecisionTraceStore, trace_hash

from .helpers import bars
from .test_contracts import _proposal, _trace

BAR_MS = 5 * 60 * 1000
TS0 = 1_700_000_000_000


def _shadow_trace(decision_id: str = "d-1", **overrides: Any) -> Any:
    proposal = overrides.pop(
        "proposal",
        _proposal(
            decision_id=decision_id,
            market_time_ms=TS0,
            decision_time_ms=TS0,
            horizon_minutes=5.0,
            entry_reference=100.0,
            expected_gross_edge_bps=4.0,
            expected_cost_bps=21.0,
            expected_net_edge_bps=-17.0,
        ),
    )
    return _trace(
        decision_id=decision_id,
        market_time_ms=TS0,
        decision_time_ms=TS0,
        mode=DecisionMode.SHADOW_TRADE,
        reason="gross below cost",
        classification="COST_KILLED",
        proposal=proposal.to_dict(),
        shadow={"mode": "SHADOW_TRADE", "marked_shadow": True},
        **overrides,
    )


def test_store_appends_and_chains(tmp_path: Path) -> None:
    store = DecisionTraceStore(tmp_path)
    first = store.append(_shadow_trace("d-1"))
    second = store.append(_shadow_trace("d-2"))
    assert first.sequence == 1
    assert second.prev_hash == first.trace_hash
    assert store.verify_chain().ok
    assert len(store.read()) == 2


def test_store_detects_tampering(tmp_path: Path) -> None:
    store = DecisionTraceStore(tmp_path)
    store.append(_shadow_trace("d-1"))
    store.append(_shadow_trace("d-2"))
    lines = store.trace_path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"reason":"gross below cost"', '"reason":"forged"')
    store.trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    verification = store.verify_chain()
    assert verification.ok is False
    assert verification.broken_at == 1


def test_store_resumes_the_chain_after_restart(tmp_path: Path) -> None:
    store = DecisionTraceStore(tmp_path)
    store.append(_shadow_trace("d-1"))
    reopened = DecisionTraceStore(tmp_path)
    second = reopened.append(_shadow_trace("d-2"))
    assert second.sequence == 2
    assert reopened.verify_chain().ok


def test_replay_reconstructs_without_market_access(tmp_path: Path) -> None:
    store = DecisionTraceStore(tmp_path)
    store.append(_shadow_trace("d-1"))
    replay = store.replay("d-1")
    assert replay.ok, [c.detail for c in replay.checks if not c.passed]
    assert replay.mode is DecisionMode.SHADOW_TRADE
    reconstruction = replay.reconstruction
    assert reconstruction["decision"]["classification"] == "COST_KILLED"
    assert reconstruction["proposal"] is not None
    assert reconstruction["execution_mode"] == "SHADOW_TRADE"
    assert reconstruction["outcome"] is None


def test_replay_reports_missing_decision(tmp_path: Path) -> None:
    store = DecisionTraceStore(tmp_path)
    with pytest.raises(KeyError):
        store.replay("nope")


def test_replay_status_is_partial_without_an_outcome(tmp_path: Path) -> None:
    """The decision is fully rebuilt, but its horizon has not closed yet."""
    store = DecisionTraceStore(tmp_path)
    store.append(_shadow_trace("d-1"))
    replay = store.replay("d-1")
    assert replay.ok
    assert replay.status is ReplayStatus.PARTIAL
    assert replay.to_dict()["status"] == "PARTIAL"
    # The reconstruction names the candidate, its cost estimate and the risk
    # review — a partial replay is still an honest, complete reconstruction.
    assert replay.reconstruction["candidate"] == "ema_crossover@5m"
    assert replay.reconstruction["cost_estimate"] is not None
    assert replay.reconstruction["risk"] is not None
    assert replay.reconstruction["shadow"] is not None


def test_replay_status_is_full_once_the_outcome_exists(tmp_path: Path) -> None:
    store = DecisionTraceStore(tmp_path)
    trace = store.append(_shadow_trace("d-1"))
    record = OutcomeEvaluator().evaluate(
        trace=trace, bars=bars("BTC/USDT", 6, rising=True)
    ).record
    assert record is not None
    store.append_outcome(record)
    replay = store.replay("d-1")
    assert replay.ok
    assert replay.status is ReplayStatus.FULL
    assert replay.reconstruction["outcome"] is not None


def test_replay_status_is_not_available_when_an_invariant_fails(tmp_path: Path) -> None:
    """A tampered record must never be reported as a successful replay."""
    store = DecisionTraceStore(tmp_path)
    store.append(_shadow_trace("d-1"))
    lines = store.trace_path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"reason":"gross below cost"', '"reason":"forged"')
    store.trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    replay = store.replay("d-1")
    assert not replay.ok
    assert replay.status is ReplayStatus.NOT_AVAILABLE
    assert "trace_hash" in [c.name for c in replay.checks if not c.passed]


def test_trace_hash_is_order_insensitive_but_content_sensitive() -> None:
    payload = {"a": 1, "b": [2, 3]}
    assert trace_hash(payload) == trace_hash({"b": [2, 3], "a": 1})
    assert trace_hash(payload) != trace_hash({"a": 1, "b": [2, 4]})


# -- outcomes ---------------------------------------------------------------


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


def test_outcome_is_pending_until_the_horizon_elapses() -> None:
    evaluator = OutcomeEvaluator()
    # Bars exist after the decision, but they stop before the 5m horizon.
    series = bars("BTC/USDT", 4, rising=True, step=60_000)
    evaluation = evaluator.evaluate(trace=_trace_for_outcome(), bars=series)
    assert evaluation.status is OutcomeStatus.PENDING_OUTCOME
    assert evaluation.record is None


def test_outcome_resolves_and_respects_direction() -> None:
    evaluator = OutcomeEvaluator()
    series = bars("BTC/USDT", 6, rising=True)  # last bar = decision + 5m
    evaluation = evaluator.evaluate(trace=_trace_for_outcome(), bars=series)
    assert evaluation.status is OutcomeStatus.RESOLVED
    record = evaluation.record
    assert record is not None
    assert record.outcome_time_ms > record.decision_time_ms
    assert record.gross_return_bps > 0
    assert record.net_hypothetical_bps == pytest.approx(
        record.gross_return_bps - record.estimated_cost_bps
    )
    assert record.direction_correct is True
    assert record.mfe_bps >= record.gross_return_bps - 1e-9


def test_outcome_instant_is_the_close_of_the_bar_not_its_open() -> None:
    """A bar yields information when it CLOSES: the outcome is priced there."""
    evaluator = OutcomeEvaluator()
    series = bars("BTC/USDT", 3, rising=True)
    evaluation = evaluator.evaluate(trace=_trace_for_outcome(), bars=series)
    assert evaluation.status is OutcomeStatus.RESOLVED
    record = evaluation.record
    assert record is not None
    # The bar opened at the decision time is the one that SPANS the 5m
    # horizon: its close is the first observation at or after the target.
    assert record.outcome_price == series[0].close
    assert record.outcome_time_ms == series[0].timestamp + BAR_MS
    assert record.outcome_time_ms == TS0 + BAR_MS
    # It is the CLOSE, never the OPEN of that bar.
    assert record.outcome_time_ms != series[0].timestamp
    assert record.reference_price_time_ms <= record.decision_time_ms


def test_short_direction_inverts_the_sign() -> None:
    evaluator = OutcomeEvaluator()
    trace = _trace_for_outcome(
        proposal=_proposal(
            market_time_ms=TS0,
            decision_time_ms=TS0,
            horizon_minutes=5.0,
            entry_reference=100.0,
            direction="SHORT",
            expected_gross_edge_bps=4.0,
            expected_cost_bps=21.0,
            expected_net_edge_bps=-17.0,
        ).to_dict()
    )
    evaluation = evaluator.evaluate(trace=trace, bars=bars("BTC/USDT", 6, rising=True))
    assert evaluation.record is not None
    assert evaluation.record.gross_return_bps < 0
    assert evaluation.record.direction_correct is False


def test_future_bars_are_never_used_for_a_past_decision() -> None:
    evaluator = OutcomeEvaluator()
    # A single bar stamped at the decision time has not closed yet: nothing to
    # observe, so the outcome must stay PENDING rather than be invented.
    series = [b for b in bars("BTC/USDT", 6, rising=True) if b.timestamp <= TS0]
    evaluation = evaluator.evaluate(trace=_trace_for_outcome(), bars=series)
    assert evaluation.status is OutcomeStatus.PENDING_OUTCOME
    assert evaluation.record is None


def test_no_proposal_means_not_applicable() -> None:
    evaluation = OutcomeEvaluator().evaluate(trace=_trace(), bars=bars("BTC/USDT", 6))
    assert evaluation.status is OutcomeStatus.NOT_APPLICABLE


def test_no_trade_hypothesis_is_evaluated_as_calibration(tmp_path: Path) -> None:
    """A rejected proposal is still a measurable prediction (calibration)."""
    trace = _trace(
        decision_id="d-nt",
        market_time_ms=TS0,
        decision_time_ms=TS0,
        mode=DecisionMode.NO_TRADE,
        classification="NO_GROSS_EDGE",
        proposal=_proposal(
            market_time_ms=TS0,
            decision_time_ms=TS0,
            horizon_minutes=5.0,
            entry_reference=100.0,
            expected_gross_edge_bps=-4.56,
            expected_cost_bps=21.0,
            expected_net_edge_bps=-25.56,
        ).to_dict(),
    )
    evaluations = OutcomeEvaluator().resolve_pending(
        traces=[trace], bars_by_symbol={"BTC/USDT": bars("BTC/USDT", 6, rising=True)}
    )
    assert len(evaluations) == 1
    record = evaluations[0].record
    assert record is not None
    assert record.mode is DecisionMode.NO_TRADE

    store = StrategyPerformanceStore(tmp_path / "performance.json")
    cell = store.update_from_outcome(record)
    assert cell.sample_size == 1
    assert cell.no_trade_sample_size == 1
    assert cell.shadow_sample_size == 0
    assert cell.paper_sample_size == 0
    # Calibration samples cannot reorder selection on their own.
    assert (
        store.selection_priority(
            strategy_id=record.strategy_id,
            asset="BTC",
            regime="UNKNOWN",
            timeframe="5m",
        )
        == 0.0
    )


def test_resolve_pending_skips_traces_without_a_hypothesis() -> None:
    """No proposal ⇒ no prediction ⇒ nothing to evaluate (not a fake PENDING)."""
    evaluations = OutcomeEvaluator().resolve_pending(
        traces=[_trace(decision_id="d-np")],
        bars_by_symbol={"BTC/USDT": bars("BTC/USDT", 6)},
    )
    assert evaluations == []


# -- experience -------------------------------------------------------------


def _outcome(decision_id: str, net: float, *, mode: DecisionMode = DecisionMode.SHADOW_TRADE) -> Any:
    return OutcomeRecord(
        run_id="run-1",
        decision_id=decision_id,
        asset="BTC",
        symbol="BTC/USDT",
        strategy_id="ema_crossover@5m",
        mode=mode,
        direction="LONG",
        decision_time_ms=TS0,
        outcome_time_ms=TS0 + 300_000,
        horizon_minutes=5.0,
        entry_reference=100.0,
        outcome_price=100.0 + net / 100.0,
        gross_return_bps=net + 21.0,
        estimated_cost_bps=21.0,
        net_hypothetical_bps=net,
        mfe_bps=max(net, 0.0),
        mae_bps=min(net, 0.0),
        direction_correct=net > 0,
        status=OutcomeStatus.RESOLVED,
    )


def test_performance_store_aggregates_and_is_idempotent(tmp_path: Path) -> None:
    store = StrategyPerformanceStore(tmp_path / "performance.json")
    for i, net in enumerate((10.0, -5.0, 20.0, -4.0)):
        store.update_from_outcome(_outcome(f"d-{i}", net))
    # Re-feeding the same decision must not double count.
    cell = store.update_from_outcome(_outcome("d-3", -4.0))
    assert cell.sample_size == 4
    assert cell.net_expectancy_bps == pytest.approx((10.0 - 5.0 + 20.0 - 4.0) / 4)
    assert cell.hit_rate == pytest.approx(0.5)
    assert cell.profit_factor == pytest.approx(30.0 / 9.0)
    assert cell.shadow_sample_size == 4
    assert cell.paper_sample_size == 0
    assert cell.no_trade_sample_size == 0


def test_performance_store_persists_across_restarts(tmp_path: Path) -> None:
    path = tmp_path / "performance.json"
    store = StrategyPerformanceStore(path)
    store.update_from_outcome(_outcome("d-1", 10.0))
    reopened = StrategyPerformanceStore(path)
    cell = reopened.get(
        strategy_id="ema_crossover@5m", asset="BTC", regime="UNKNOWN", timeframe="5m"
    )
    assert cell is not None and cell.sample_size == 1


def test_selection_priority_is_zero_below_the_minimum_sample(tmp_path: Path) -> None:
    store = StrategyPerformanceStore(tmp_path / "performance.json")
    for i in range(MIN_SAMPLES_FOR_ADJUSTMENT - 1):
        store.update_from_outcome(_outcome(f"d-{i}", 50.0))
    assert (
        store.selection_priority(
            strategy_id="ema_crossover@5m", asset="BTC", regime="UNKNOWN", timeframe="5m"
        )
        == 0.0
    )


def test_selection_priority_is_bounded(tmp_path: Path) -> None:
    store = StrategyPerformanceStore(tmp_path / "performance.json")
    for i in range(MIN_SAMPLES_FOR_ADJUSTMENT):
        store.update_from_outcome(_outcome(f"d-{i}", 100_000.0))
    priority = store.selection_priority(
        strategy_id="ema_crossover@5m", asset="BTC", regime="UNKNOWN", timeframe="5m"
    )
    assert priority == pytest.approx(MAX_PRIORITY_ADJUSTMENT)


def test_performance_cannot_be_updated_by_an_unresolved_outcome(tmp_path: Path) -> None:
    from dataclasses import replace

    store = StrategyPerformanceStore(tmp_path / "performance.json")
    with pytest.raises(ValueError, match="only RESOLVED outcomes"):
        store.update_from_outcome(
            replace(_outcome("d-1", 10.0), status=OutcomeStatus.PENDING_OUTCOME)
        )


def test_experience_module_exposes_no_policy_mutation_api(tmp_path: Path) -> None:
    """Experience may only influence selection: no limit/policy setters exist."""
    store = StrategyPerformanceStore(tmp_path / "performance.json")
    public = {name for name in dir(store) if not name.startswith("_")}
    forbidden_substrings = (
        "limit",
        "leverage",
        "capital",
        "admission",
        "risk",
        "threshold",
        "size",
    )
    assert not any(
        any(token in name.lower() for token in forbidden_substrings) for name in public
    ), public
