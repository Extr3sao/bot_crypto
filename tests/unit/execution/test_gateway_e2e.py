"""Track A E2E: execution reliability through the real runtime boundary.

A1: stable intent identity across retries (wall clock excluded).
A2: ACK_UNKNOWN E2E (found/absent/uncertain).
A3: fill idempotency E2E (duplicate + partial + out-of-order).
A4: startup reconciliation fail-closed gate.

All venue interaction happens through ExecutionGateway + a scripted fake
venue implementing VenuePort. No real venue, LIVE_CALLS = 0.
"""

from __future__ import annotations

import pytest

from trading_bot.execution import (
    AckQueryResult,
    ExecutionGateway,
    ExecutionReliabilityError,
    ExecutionState,
    FeedFreshness,
    FeedGuardAction,
    TradeIntent,
    compute_intent_id,
    derive_client_order_id,
)


def _intent() -> TradeIntent:
    return TradeIntent(
        symbol="BTC/USDT",
        side="buy",
        quantity=0.01,
        order_type="limit",
        limit_price=60_000.0,
        venue="fake",
        account_id="paper-01",
    )


class FakeVenue:
    """Scripted fake venue implementing the gateway's VenuePort."""

    def __init__(self) -> None:
        self.orders: dict[str, str] = {}
        self.submit_calls: list[str] = []
        self.query_calls: list[str] = []
        self.submit_should_raise = False

    def submit(self, intent: TradeIntent, client_order_id: str) -> str:
        if self.submit_should_raise:
            raise TimeoutError("simulated client timeout after venue accepted")
        self.submit_calls.append(client_order_id)
        venue_order_id = f"VO-{len(self.submit_calls)}"
        self.orders[client_order_id] = venue_order_id
        return venue_order_id

    def query(self, client_order_id: str) -> AckQueryResult:
        self.query_calls.append(client_order_id)
        return AckQueryResult.FOUND if client_order_id in self.orders else AckQueryResult.ABSENT

    def venue_order_id_of(self, client_order_id: str) -> str | None:
        return self.orders.get(client_order_id)


# ---------------------------------------------------------------------------
# A1 — stable intent in real path
# ---------------------------------------------------------------------------


def test_a1_same_intent_retried_n_times_same_identity() -> None:
    gateway = ExecutionGateway()
    venue = FakeVenue()
    intent = _intent()
    receipts = [gateway.submit(intent, venue) for _ in range(10)]
    intent_id = compute_intent_id(intent)
    cloid = derive_client_order_id(intent_id)
    assert all(r.intent_id == intent_id for r in receipts)
    assert all(r.client_order_id == cloid for r in receipts)
    assert all(r.venue_order_id == "VO-1" for r in receipts)
    assert venue.submit_calls == [cloid] * 1  # ONE economic order total


def test_a1_wall_clock_metadata_never_affects_identity() -> None:
    gateway = ExecutionGateway()
    venue = FakeVenue()
    base = _intent()
    stamped = TradeIntent(
        symbol=base.symbol,
        side=base.side,
        quantity=base.quantity,
        order_type=base.order_type,
        limit_price=base.limit_price,
        venue=base.venue,
        account_id=base.account_id,
        metadata={"wall_clock": 1_790_000_000.123, "request_seq": 42},
    )
    r1 = gateway.submit(base, venue)
    r2 = gateway.submit(stamped, venue)
    assert r1.intent_id == r2.intent_id
    assert r1.client_order_id == r2.client_order_id
    assert venue.submit_calls.count(derive_client_order_id(r1.intent_id)) == 1


def test_a1_submit_raising_enters_ack_unknown_never_retries_blindly() -> None:
    gateway = ExecutionGateway()
    venue = FakeVenue()
    venue.submit_should_raise = True
    intent = _intent()
    with pytest.raises(TimeoutError):
        gateway.submit(intent, venue)
    intent_id = compute_intent_id(intent)
    assert gateway.journal.current_state(intent_id) is ExecutionState.ACK_UNKNOWN
    assert venue.submit_calls == []  # the raise happened before venue bookkeeping


def test_a1_feed_block_forbids_submission() -> None:
    gateway = ExecutionGateway()
    venue = FakeVenue()
    stale = FeedFreshness(
        feed_id="ohlcv-btc",
        last_update_ts=1_000.0,
        observed_at_ts=1_100.0,
        max_staleness_seconds=30.0,
    )
    verdict = gateway.evaluate_feeds((stale,))
    assert verdict.action is FeedGuardAction.BLOCK_NEW_ENTRIES
    with pytest.raises(ExecutionReliabilityError):
        gateway.submit(_intent(), venue, evidence={"feed_verdict": verdict})
    assert venue.submit_calls == []


# ---------------------------------------------------------------------------
# A2 — ACK_UNKNOWN in real path
# ---------------------------------------------------------------------------


def test_a2_venue_accepted_client_timeout_adopted_single_economic_order() -> None:
    gateway = ExecutionGateway()
    venue = FakeVenue()
    intent = _intent()
    cloid = derive_client_order_id(compute_intent_id(intent))
    # Venue accepts but the client "times out": raise AFTER venue acceptance.
    original_submit = venue.submit

    def raise_after_accept(intent_: TradeIntent, client_order_id: str) -> str:
        original_submit(intent_, client_order_id)
        raise TimeoutError("simulated client timeout")

    venue.submit = raise_after_accept  # type: ignore[method-assign]
    with pytest.raises(TimeoutError):
        gateway.submit(intent, venue)
    assert gateway.journal.current_state(compute_intent_id(intent)) is ExecutionState.ACK_UNKNOWN
    assert venue.orders.get(cloid) == "VO-1"  # venue DID accept
    receipt = gateway.resolve_ack_unknown(intent, venue)
    assert receipt.journal_state is ExecutionState.ACCEPTED
    assert receipt.venue_order_id == "VO-1"
    assert receipt.submitted_now is False
    assert venue.submit_calls.count(cloid) == 1  # ECONOMIC_ORDERS == 1


def test_a2_definitely_absent_controlled_retry_same_identity() -> None:
    gateway = ExecutionGateway()
    venue = FakeVenue()
    intent = _intent()
    cloid = derive_client_order_id(compute_intent_id(intent))
    venue.submit_should_raise = True  # submit raises: ambiguity
    with pytest.raises(TimeoutError):
        gateway.submit(intent, venue)
    # Venue definitively never received it (submit raised before bookkeeping).
    venue.submit_should_raise = False
    receipt = gateway.resolve_ack_unknown(intent, venue)
    assert receipt.submitted_now is True
    assert venue.orders.get(cloid) is not None  # same cloid used for retry
    assert venue.submit_calls == [cloid]  # exactly one economic order, same identity
    assert len(set(venue.submit_calls)) == 1


def test_a2_uncertain_blocks_no_economic_order() -> None:
    gateway = ExecutionGateway()
    venue = FakeVenue()
    intent = _intent()
    venue.submit_should_raise = True
    with pytest.raises(TimeoutError):
        gateway.submit(intent, venue)
    venue.submit_should_raise = False
    receipt = gateway.resolve_ack_unknown(intent, venue, query_result=AckQueryResult.UNCERTAIN)
    assert receipt.journal_state is ExecutionState.RECONCILING
    assert receipt.submitted_now is False
    assert receipt.detail.startswith("blocked")


# ---------------------------------------------------------------------------
# A3 — fill idempotency through the gateway
# ---------------------------------------------------------------------------


def test_a3_duplicate_fill_applies_exactly_once() -> None:
    gateway = ExecutionGateway()
    venue = FakeVenue()
    intent = _intent()
    gateway.submit(intent, venue)
    first = gateway.apply_fill(intent, venue_fill_id="F-1", quantity=0.005, price=60_000.0, fee=0.1)
    dup = gateway.apply_fill(intent, venue_fill_id="F-1", quantity=0.005, price=60_000.0, fee=0.1)
    assert first.applied and first.position_delta == 0.005
    assert dup.duplicate and dup.position_delta == 0.0
    assert gateway.fills.applied_count() == 1


def test_a3_partial_out_of_order_fills_position_once_each() -> None:
    gateway = ExecutionGateway()
    venue = FakeVenue()
    intent = _intent()
    gateway.submit(intent, venue)
    a = gateway.apply_fill(intent, venue_fill_id="F-2", quantity=0.004, price=60_100.0)
    b = gateway.apply_fill(intent, venue_fill_id="F-1", quantity=0.006, price=60_000.0)
    dup = gateway.apply_fill(intent, venue_fill_id="F-2", quantity=0.004, price=60_100.0)
    assert a.applied and b.applied and dup.duplicate
    position = sum(app.position_delta for app in (a, b, dup))
    assert position == pytest.approx(0.010)  # 0.004 + 0.006 applied exactly once


def test_a3_fee_and_pnl_once_per_fill() -> None:
    gateway = ExecutionGateway()
    venue = FakeVenue()
    intent = _intent()
    gateway.submit(intent, venue)
    gateway.apply_fill(intent, venue_fill_id="F-1", quantity=0.5, price=60_000.0, fee=1.0)
    again = gateway.apply_fill(intent, venue_fill_id="F-1", quantity=0.5, price=60_000.0, fee=1.0)
    assert again.fee_delta == 0.0
    assert again.pnl_delta == 0.0


# ---------------------------------------------------------------------------
# A4 — startup reconciliation
# ---------------------------------------------------------------------------


def test_a4_execution_ready_requires_all_reconciliation_inputs() -> None:
    gateway = ExecutionGateway()
    ready, missing = gateway.execution_ready(
        instrument_metadata_loaded=True,
        account_loaded=True,
        positions_loaded=True,
        open_orders_loaded=False,
        recent_fills_loaded=True,
    )
    assert ready is False
    assert missing == ("open_orders",)


def test_a4_execution_ready_all_loaded() -> None:
    gateway = ExecutionGateway()
    ready, missing = gateway.execution_ready(
        instrument_metadata_loaded=True,
        account_loaded=True,
        positions_loaded=True,
        open_orders_loaded=True,
        recent_fills_loaded=True,
    )
    assert ready is True
    assert missing == ()


def test_a4_startup_reconcile_adopts_without_resubmit() -> None:
    gateway = ExecutionGateway()
    venue = FakeVenue()
    intent = _intent()
    cloid = derive_client_order_id(compute_intent_id(intent))
    venue.submit_should_raise = True
    with pytest.raises(TimeoutError):
        gateway.submit(intent, venue)  # interrupted run
    # Restart: reconciliation finds the venue still holds the order.
    receipt = gateway.reconcile(
        intent, venue_holds_order=True, venue_order_id=venue.orders.get(cloid)
    )
    assert receipt.journal_state is ExecutionState.ACCEPTED
    assert venue.submit_calls == []  # restart never resubmits


def test_a4_startup_reconcile_closes_when_venue_lacks_order() -> None:
    gateway = ExecutionGateway()
    intent = _intent()
    receipt = gateway.reconcile(intent, venue_holds_order=False)
    assert receipt.journal_state is ExecutionState.CANCELLED


# ---------------------------------------------------------------------------
# Cancel semantics through the gateway
# ---------------------------------------------------------------------------


def test_cancel_requires_venue_confirmation() -> None:
    gateway = ExecutionGateway()
    venue = FakeVenue()
    intent = _intent()
    gateway.submit(intent, venue)
    pending = gateway.request_cancel(intent, venue)
    assert pending.journal_state is ExecutionState.CANCEL_PENDING
    confirmed = gateway.confirm_cancel(intent)
    assert confirmed.journal_state is ExecutionState.CANCELLED
    # Terminal: no further transitions.
    with pytest.raises(ExecutionReliabilityError):
        gateway.journal.record(
            intent_id=compute_intent_id(intent),
            client_order_id=derive_client_order_id(compute_intent_id(intent)),
            new_state=ExecutionState.ACCEPTED,
            reason="revive after cancel",
        )


def test_fill_during_cancel_pending_transitions_to_partial() -> None:
    gateway = ExecutionGateway()
    venue = FakeVenue()
    intent = _intent()
    gateway.submit(intent, venue)
    gateway.request_cancel(intent, venue)
    app = gateway.apply_fill(intent, venue_fill_id="F-9", quantity=0.01, price=60_000.0)
    assert app.applied
    assert (
        gateway.journal.current_state(compute_intent_id(intent)) is ExecutionState.PARTIALLY_FILLED
    )
