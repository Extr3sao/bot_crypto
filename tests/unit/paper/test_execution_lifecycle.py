"""EXP-003P lifecycle: contracts, durable store, state machine, ledger, reconciliation.

These tests state the properties the experiment rests on. Each one names the class of
failure it refuses, so a passing suite is evidence about *which* defect cannot happen,
not merely that nothing raised.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.paper.broker import BrokerOrderError, PaperBroker
from trading_bot.paper.lifecycle import (
    CausalityViolation,
    DurableEventStore,
    ExecutionEnvelope,
    FillFact,
    FillLedger,
    LifecycleEngine,
    LifecycleViolation,
    LiveModeForbidden,
    OrderIntent,
    PaperBrokerRecorder,
    ProvenanceViolation,
    RiskGateViolation,
    RunContext,
    SimulatedPaperVenue,
    VenueScript,
    project_orders,
    reconcile,
    utc_ms,
)
from trading_bot.strategies.types import Signal

NOW = 1_700_000_000_000


def context(**overrides: object) -> RunContext:
    values: dict[str, object] = {
        "run_id": "EXP-003P-TEST",
        "commit_sha": "0" * 40,
        "config_digest": "sha256:" + "1" * 64,
        "adapter_id": "OFFLINE_SIM_PAPER_VENUE",
        "provenance": "OFFLINE_SIMULATED",
        "provider_environment": "OFFLINE",
        "clock_source": "TEST_CLOCK",
    }
    values.update(overrides)
    return RunContext(**values)  # type: ignore[arg-type]


def intent(client_order_id: str = "PAPER-TEST-0001", *, quantity: float = 2.0) -> OrderIntent:
    return OrderIntent(
        client_order_id=client_order_id,
        asset="BTC",
        side="buy",
        order_type="market",
        quantity=quantity,
        strategy_id="ema_crossover",
        decision_time_utc=utc_ms(NOW),
        data_cutoff_utc=utc_ms(NOW - 60_000),
        risk_evaluation_id="RISK-EVAL-1",
        policy_verification_id="POLICY-1",
        notional_usdt=200.0,
    )


def drive(script: VenueScript, *, order: OrderIntent | None = None) -> tuple[LifecycleEngine, SimulatedPaperVenue]:
    engine = LifecycleEngine(context=context())
    venue = SimulatedPaperVenue()
    engine.drive(order or intent(), script=script, venue_any=venue, submit_ms=NOW)
    return engine, venue


def projection_of(engine: LifecycleEngine):
    return project_orders(
        [(index, envelope) for index, envelope in enumerate(engine.store.envelopes, start=1)]
    )


def envelope(**overrides: object) -> ExecutionEnvelope:
    values: dict[str, object] = {
        "run_id": "R",
        "commit_sha": "c" * 40,
        "config_digest": "d",
        "client_order_id": "C1",
        "event_id": "E1",
        "asset": "BTC",
        "strategy_id": "ema",
        "adapter_id": "SIM",
        "event_type": "ORDER_CREATED",
        "event_time_utc": utc_ms(NOW),
        "received_time_utc": utc_ms(NOW),
        "clock_source": "TEST",
        "provenance": "OFFLINE_SIMULATED",
        "provider_environment": "OFFLINE",
    }
    values.update(overrides)
    return ExecutionEnvelope(**values)  # type: ignore[arg-type]


# -- contracts ---------------------------------------------------------------


def test_provenance_cannot_be_promoted_by_relabelling() -> None:
    with pytest.raises(ProvenanceViolation):
        envelope(provenance="VENUE_REPORTED_PAPER", provider_environment="OFFLINE")


def test_live_environment_is_never_a_paper_environment() -> None:
    with pytest.raises(LiveModeForbidden):
        envelope(provider_environment="LIVE")


def test_event_received_before_it_happened_is_refused() -> None:
    with pytest.raises(CausalityViolation):
        envelope(received_time_utc=utc_ms(NOW - 5_000))


def test_decision_after_the_event_it_produced_is_refused() -> None:
    with pytest.raises(CausalityViolation):
        envelope(payload={"decision_time_utc": utc_ms(NOW + 1_000)})


def test_data_cutoff_after_the_decision_is_refused() -> None:
    with pytest.raises(CausalityViolation):
        envelope(
            payload={
                "decision_time_utc": utc_ms(NOW - 2_000),
                "data_cutoff_utc": utc_ms(NOW - 1_000),
            }
        )


def test_intent_rejects_data_from_after_the_decision() -> None:
    with pytest.raises(CausalityViolation):
        OrderIntent(
            client_order_id="C",
            asset="BTC",
            side="buy",
            order_type="market",
            quantity=1.0,
            strategy_id="ema",
            decision_time_utc=utc_ms(NOW),
            data_cutoff_utc=utc_ms(NOW + 1),
        )


# -- durable store -----------------------------------------------------------


def test_store_refuses_to_accept_one_event_twice() -> None:
    store = DurableEventStore()
    assert store.append(envelope()) == 1
    assert store.append(envelope()) is None
    assert len(store.events) == 1
    assert store.duplicates[0]["event_id"] == "E1"


def test_store_chain_detects_a_tampered_quantity(tmp_path: Path) -> None:
    engine, _venue = drive(VenueScript(mode="FULL_FILL"))
    path = tmp_path / "EXECUTION_TRACE.jsonl"
    engine.store.write_jsonl(path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        if row["event_type"] == "ORDER_FILLED":
            row["payload"]["fill"]["filled_quantity"] = 99.0
            break
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", "utf-8")
    with pytest.raises(LifecycleViolation):
        DurableEventStore.load_jsonl(path)


def test_persisted_trace_round_trips_and_has_the_same_digest(tmp_path: Path) -> None:
    engine, _venue = drive(VenueScript(mode="PARTIAL_THEN_FILL", tranches=(0.5, 0.5), fill_delays_ms=(10, 20)))
    path = tmp_path / "trace.jsonl"
    engine.store.write_jsonl(path)
    loaded = DurableEventStore.load_jsonl(path)
    assert loaded.digest() == engine.store.digest()
    assert [row["event_type"] for row in loaded.rows()] == [
        row["event_type"] for row in engine.store.rows()
    ]


# -- state machine and ledger ------------------------------------------------


def test_partial_fill_then_full_fill_accumulates_quantity_and_fees() -> None:
    engine, venue = drive(
        VenueScript(mode="PARTIAL_THEN_FILL", tranches=(0.4, 0.6), fill_delays_ms=(10, 20))
    )
    projection = projection_of(engine)
    assert [e.event_type for e in engine.store.envelopes] == [
        "ORDER_CREATED",
        "ORDER_SUBMITTED",
        "ORDER_ACKNOWLEDGED",
        "ORDER_PARTIALLY_FILLED",
        "ORDER_FILLED",
    ]
    order = projection.orders["OFFLINE:PAPER-TEST-0001"]
    assert order.state == "FILLED"
    assert order.cum_filled_qty == pytest.approx(2.0)
    assert len(order.fills) == 2
    assert engine.ledger.positions["BTC"]["quantity"] == pytest.approx(2.0)
    assert engine.ledger.fees_by_currency["USDT"] == pytest.approx(0.08)
    assert reconcile(
        run_id="R",
        as_of_utc=utc_ms(NOW + 10_000),
        projection=projection,
        ledger=engine.ledger,
        source="venue",
        venue_snapshot=venue.snapshot(),
    ).result == "PASS"


def test_cancel_after_partial_keeps_what_was_executed() -> None:
    engine, venue = drive(
        VenueScript(mode="PARTIAL_THEN_CANCEL", tranches=(0.4,), fill_delays_ms=(10,))
    )
    projection = projection_of(engine)
    order = projection.orders["OFFLINE:PAPER-TEST-0001"]
    assert order.state == "CANCELED"
    assert order.cum_filled_qty == pytest.approx(0.8)
    assert engine.ledger.positions["BTC"]["quantity"] == pytest.approx(0.8)
    assert projection.codes() == []
    assert reconcile(
        run_id="R",
        as_of_utc=utc_ms(NOW + 10_000),
        projection=projection,
        ledger=engine.ledger,
        source="venue",
        venue_snapshot=venue.snapshot(),
    ).result == "PASS"


def test_duplicate_delivery_books_the_fill_once() -> None:
    engine, venue = drive(VenueScript(mode="FULL_FILL", duplicate_last=True))
    assert engine.store.duplicates, "the duplicate must be visible, not swallowed"
    assert engine.ledger.applied_count == 1
    assert engine.ledger.positions["BTC"]["quantity"] == pytest.approx(2.0)
    assert reconcile(
        run_id="R",
        as_of_utc=utc_ms(NOW + 10_000),
        projection=projection_of(engine),
        ledger=engine.ledger,
        source="venue",
        venue_snapshot=venue.snapshot(),
    ).result == "PASS"


def test_rejected_order_books_nothing() -> None:
    engine, venue = drive(VenueScript(mode="REJECT_AT_SUBMIT"))
    assert projection_of(engine).orders["OFFLINE:PAPER-TEST-0001"].state == "REJECTED"
    assert engine.ledger.applied_count == 0
    assert engine.ledger.positions == {}
    assert venue.snapshot()["orders"] == {}


def test_acknowledgement_is_not_a_fill() -> None:
    engine, _venue = drive(VenueScript(mode="ACK_WITHOUT_FILL"))
    order = projection_of(engine).orders["OFFLINE:PAPER-TEST-0001"]
    assert order.state == "ACKNOWLEDGED"
    assert order.acked is True
    assert order.cum_filled_qty == 0.0
    assert engine.ledger.applied_count == 0


def test_timeout_leaves_the_order_unknown_and_blocks_another_submit() -> None:
    engine, _venue = drive(VenueScript(mode="TIMEOUT_UNKNOWN"))
    assert projection_of(engine).orders["OFFLINE:PAPER-TEST-0001"].state == "UNKNOWN"
    with pytest.raises(RiskGateViolation):
        engine.submit("PAPER-TEST-0001", now_ms=NOW + 1_000)
    assert [event.event_type for event in engine.store.envelopes].count("ORDER_SUBMITTED") == 1


@pytest.mark.parametrize("confirmed", ["REJECTED", "FILLED"])
def test_a_resolved_order_is_closed_for_its_intent(confirmed: str) -> None:
    engine, _venue = drive(VenueScript(mode="TIMEOUT_UNKNOWN"))
    engine.resolve_unknown(
        "PAPER-TEST-0001",
        confirmed_state=confirmed,
        now_ms=NOW + 2_000,
        evidence="PRIMARY_SOURCE_QUERY",
    )
    with pytest.raises(RiskGateViolation):
        engine.submit("PAPER-TEST-0001", now_ms=NOW + 3_000)
    assert projection_of(engine).orders["OFFLINE:PAPER-TEST-0001"].state == confirmed


def test_fill_before_acknowledgement_is_reported_not_invented() -> None:
    engine, _venue = drive(
        VenueScript(
            mode="PARTIAL_THEN_FILL",
            tranches=(0.5, 0.5),
            fill_delays_ms=(10, 20),
            deliver_fills_before_ack=True,
        )
    )
    codes = projection_of(engine).codes()
    assert "OUT_OF_ORDER_EVENT" in codes
    # The causal projection applies the acknowledgement before the fill it belongs to, so
    # there is no phantom ACK and no second accounting entry.
    assert engine.ledger.applied_count == 2


def test_submit_without_risk_approval_is_refused_before_transmission() -> None:
    engine = LifecycleEngine(context=context())
    order = intent()
    engine.create(order, now_ms=NOW, risk_approved=False, rejection_reason="DAILY_LOSS_LIMIT")
    with pytest.raises(RiskGateViolation):
        engine.submit(order.client_order_id, now_ms=NOW + 1)
    assert [e.event_type for e in engine.store.envelopes] == [
        "ORDER_CREATED",
        "ORDER_RISK_REJECTED",
    ]


def test_a_submitted_order_carries_the_policy_verification_identity() -> None:
    engine, _venue = drive(VenueScript(mode="FULL_FILL"))
    submitted = next(
        e for e in engine.store.envelopes if e.event_type == "ORDER_SUBMITTED"
    )
    assert submitted.payload["risk_evaluation_id"] == "RISK-EVAL-1"
    assert submitted.payload["policy_verification_id"] == "POLICY-1"


def test_a_live_context_cannot_emit_a_single_event() -> None:
    # Misconfiguration is the interesting case: the engine is handed a live
    # provider_environment and still writes nothing, because the envelope refuses it.
    engine = LifecycleEngine(
        context=context(
            provenance="VENUE_REPORTED_PAPER", provider_environment="LIVE", adapter_id="LIVE"
        )
    )
    with pytest.raises(LiveModeForbidden):
        engine.create(intent(), now_ms=NOW, risk_approved=True)
    assert engine.store.events == ()


# -- ledger ------------------------------------------------------------------


def test_fee_in_a_currency_without_conversion_makes_net_pnl_not_available() -> None:
    ledger = FillLedger()
    ledger.apply(
        FillFact(
            fill_key="F1",
            client_order_id="C1",
            asset="BTC",
            side="buy",
            filled_quantity=1.0,
            fill_price=100.0,
            fee_amount=0.1,
            fee_currency="BNB",
            event_time_utc=utc_ms(NOW),
            provenance="OFFLINE_SIMULATED",
            provider_environment="OFFLINE",
            raw_event_digest="sha256:0",
        )
    )
    assert ledger.net_realized_pnl_usdt is None
    assert ledger.to_row()["unpriced_fees"]


def test_unrealized_pnl_without_a_point_in_time_mark_is_not_available() -> None:
    engine, _venue = drive(VenueScript(mode="FULL_FILL"))
    assert engine.ledger.unrealized_pnl(None) is None
    assert engine.ledger.unrealized_pnl({"BTC": 150.0}) == pytest.approx(100.0)


# -- reconciliation ----------------------------------------------------------


def test_reconciliation_without_a_primary_source_is_incomplete() -> None:
    engine, _venue = drive(VenueScript(mode="FULL_FILL"))
    result = reconcile(
        run_id="R",
        as_of_utc=utc_ms(NOW + 10_000),
        projection=projection_of(engine),
        ledger=engine.ledger,
        source="venue",
        venue_snapshot=None,
    )
    assert result.result == "INCOMPLETE"
    assert "venue_snapshot=NOT_AVAILABLE" in result.evidence_refs


def test_reconciliation_fails_when_the_ledger_dropped_a_fill() -> None:
    engine, venue = drive(
        VenueScript(mode="PARTIAL_THEN_FILL", tranches=(0.5, 0.5), fill_delays_ms=(10, 20))
    )
    tampered = FillLedger()
    first = engine.ledger.raw_fills()[0]
    tampered.apply(
        FillFact(
            fill_key=str(first["fill_key"]),
            client_order_id=str(first["client_order_id"]),
            asset=str(first["asset"]),
            side=str(first["side"]),
            filled_quantity=float(first["filled_quantity"]),
            fill_price=float(first["fill_price"]),
            fee_amount=float(first["fee_amount"]),
            fee_currency=str(first["fee_currency"]),
            event_time_utc=str(first["event_time_utc"]),
            provenance=str(first["provenance"]),
            provider_environment=str(first["provider_environment"]),
            raw_event_digest=str(first["raw_event_digest"]),
            venue_order_id=first.get("venue_order_id"),
        )
    )
    result = reconcile(
        run_id="R",
        as_of_utc=utc_ms(NOW + 10_000),
        projection=projection_of(engine),
        ledger=tampered,
        source="venue",
        venue_snapshot=venue.snapshot(),
    )
    assert result.result == "FAIL"
    assert any(item["code"] == "LEDGER_MISMATCH" for item in result.differences)


# -- the real broker ---------------------------------------------------------


def _signal(**overrides: object) -> Signal:
    values: dict[str, object] = {
        "symbol": "BTC/USDT",
        "side": "buy",
        "strategy_name": "ema_crossover",
        "timeframe": "1h",
        "confidence": 0.6,
        "price": 100.0,
        "stop_loss_pct": 1.0,
        "take_profit_pct": 2.0,
        "metadata": {"notional_usdt": 1000.0, "decision_seq": 7},
    }
    values.update(overrides)
    return Signal(**values)  # type: ignore[arg-type]


def test_paper_broker_fill_is_recorded_as_an_envelope_with_its_own_provenance() -> None:
    engine = LifecycleEngine(context=context(adapter_id="PAPER_BROKER"))
    recorder = PaperBrokerRecorder(engine, book_id="book-003p")
    broker = PaperBroker(equity=10_000.0, book_id="book-003p", lifecycle=recorder)

    position = broker.execute_signal(_signal())
    assert position is not None
    events = [event.event_type for event in engine.store.envelopes]
    assert events == [
        "ORDER_CREATED",
        "ORDER_SUBMITTED",
        "ORDER_ACKNOWLEDGED",
        "ORDER_FILLED",
    ]
    envelope0 = engine.store.envelopes[0]
    assert envelope0.provenance == "OFFLINE_SIMULATED"
    assert envelope0.payload["risk_evaluation_source"] == "PAPERBROKER_NOTIONAL_GUARD"
    assert engine.ledger.positions["BTC"]["quantity"] == pytest.approx(position.quantity)
    assert engine.ledger.fees_by_currency["USDT"] == pytest.approx(position.entry_commission)

    result = reconcile(
        run_id="R",
        as_of_utc=utc_ms(NOW),
        projection=projection_of(engine),
        ledger=engine.ledger,
        source="paper_broker",
        venue_snapshot={
            "orders": {
                position.entry_order_id: {
                    "quantity": position.quantity,
                    "notional": position.quantity * position.entry_price,
                    "fees_usdt": position.entry_commission,
                }
            }
        },
        broker_snapshot=broker.accounting_snapshot(),
    )
    assert result.result == "PASS", result.differences


def test_broker_closes_and_the_exit_leg_is_recorded_and_reconciles() -> None:
    engine = LifecycleEngine(context=context(adapter_id="PAPER_BROKER"))
    recorder = PaperBrokerRecorder(engine, book_id="book-003p")
    broker = PaperBroker(equity=10_000.0, book_id="book-003p", lifecycle=recorder)
    position = broker.execute_signal(_signal())
    assert position is not None
    trade = broker.close_position("BTC/USDT", 110.0, "signal")
    assert trade is not None

    projection = projection_of(engine)
    assert projection.codes() == []
    assert engine.ledger.positions["BTC"]["quantity"] == pytest.approx(0.0, abs=1e-12)
    assert engine.ledger.net_realized_pnl_usdt == pytest.approx(trade.pnl, abs=1e-9)
    assert recorder.recorded_entries == 1
    assert recorder.recorded_exits == 1
    result = reconcile(
        run_id="R",
        as_of_utc=utc_ms(NOW),
        projection=projection,
        ledger=engine.ledger,
        source="paper_broker",
        venue_snapshot={
            "orders": {
                position.entry_order_id: {
                    "quantity": position.quantity,
                    "notional": position.quantity * position.entry_price,
                    "fees_usdt": position.entry_commission,
                },
                trade.exit_order_id: {
                    "quantity": trade.quantity,
                    "notional": trade.quantity * trade.exit_price,
                    "fees_usdt": trade.exit_commission,
                },
            }
        },
        broker_snapshot=broker.accounting_snapshot(),
    )
    assert result.result == "PASS", result.differences


def test_broker_refusal_is_recorded_and_cannot_move_money() -> None:
    engine = LifecycleEngine(context=context(adapter_id="PAPER_BROKER"))
    recorder = PaperBrokerRecorder(engine, book_id="book-003p")
    broker = PaperBroker(equity=10_000.0, book_id="book-003p", lifecycle=recorder)
    with pytest.raises(BrokerOrderError):
        broker.execute_signal(_signal(metadata={"decision_seq": 8}))
    assert [event.event_type for event in engine.store.envelopes] == [
        "ORDER_CREATED",
        "ORDER_RISK_REJECTED",
    ]
    assert engine.ledger.applied_count == 0
    assert engine.store.envelopes[1].payload["reason"] == "NOTIONAL_NOT_RISK_APPROVED"
    assert engine.store.envelopes[1].payload["stage"] == "risk"


def test_broker_numbers_are_identical_with_and_without_the_recorder() -> None:
    plain = PaperBroker(equity=10_000.0, book_id="book-plain")
    engine = LifecycleEngine(context=context(adapter_id="PAPER_BROKER"))
    watched = PaperBroker(
        equity=10_000.0,
        book_id="book-plain",
        lifecycle=PaperBrokerRecorder(engine, book_id="book-plain"),
    )
    for broker in (plain, watched):
        broker.execute_signal(_signal())
        broker.close_position("BTC/USDT", 101.5, "signal")
    left = plain.closed_trades[0]
    right = watched.closed_trades[0]
    for field in (
        "pnl",
        "gross_pnl",
        "entry_commission",
        "exit_commission",
        "execution_cost_usdt",
        "quantity",
        "entry_price",
        "exit_price",
    ):
        assert getattr(left, field) == pytest.approx(getattr(right, field), abs=1e-12)
    assert [trade.trade_id for trade in plain.closed_trades] == [
        trade.trade_id for trade in watched.closed_trades
    ]
