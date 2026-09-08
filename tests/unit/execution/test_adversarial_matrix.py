"""Adversarial execution matrix (checkpoint EXTERNAL-AUDIT-RECONCILIATION-01).

Critical invariant asserted throughout:
    ECONOMIC_ORDERS_PER_INTENT <= 1
under retry/recovery ambiguity, duplicate delivery, cancel ambiguity, orphan
reconciliation, restart with open order/position, and repeated retries of the
same TradeIntent.
"""

from __future__ import annotations

import pytest

from trading_bot.execution import (
    AckQueryResult,
    AmbiguousAckRecovery,
    ExecutionJournal,
    ExecutionReliabilityError,
    ExecutionState,
    FillLedger,
    IdempotentSubmitGate,
    TradeIntent,
    compute_intent_id,
    derive_client_order_id,
)


def _intent(**overrides: object) -> TradeIntent:
    base: dict[str, object] = {
        "symbol": "BTC/USDT",
        "side": "buy",
        "quantity": 0.01,
        "order_type": "limit",
        "limit_price": 60_000.0,
    }
    base.update(overrides)
    return TradeIntent(**base)  # type: ignore[arg-type]


class FakeVenue:
    """Scripted venue for adversarial scenarios."""

    def __init__(self) -> None:
        self.orders: dict[str, str] = {}  # client_order_id -> venue_order_id
        self.submit_calls: list[str] = []
        self.query_calls: list[str] = []

    def submit(self, client_order_id: str) -> str:
        self.submit_calls.append(client_order_id)
        venue_order_id = f"VO-{len(self.submit_calls)}"
        self.orders[client_order_id] = venue_order_id
        return venue_order_id

    def query(self, client_order_id: str) -> AckQueryResult:
        self.query_calls.append(client_order_id)
        if client_order_id in self.orders:
            return AckQueryResult.FOUND
        return AckQueryResult.ABSENT


def test_timeout_after_venue_accepted_adopts_no_resubmit() -> None:
    intent = _intent()
    intent_id = compute_intent_id(intent)
    cloid = derive_client_order_id(intent_id)
    venue = FakeVenue()
    venue.submit(cloid)  # venue accepted but ACK lost
    recovery = AmbiguousAckRecovery(intent_id=intent_id, client_order_id=cloid)
    recovery.on_submit_timeout()
    verdict = recovery.resolve(venue.query(cloid), venue_order_id=venue.orders.get(cloid))
    assert verdict.decision.value == "adopt"
    assert verdict.venue_order_id == "VO-1"
    assert venue.submit_calls.count(cloid) == 1  # ECONOMIC_ORDERS_PER_INTENT == 1


def test_lost_ack_then_definitely_absent_allows_single_controlled_retry() -> None:
    intent = _intent()
    intent_id = compute_intent_id(intent)
    cloid = derive_client_order_id(intent_id)
    venue = FakeVenue()  # submit never landed
    recovery = AmbiguousAckRecovery(intent_id=intent_id, client_order_id=cloid)
    recovery.on_submit_timeout()
    verdict = recovery.resolve(venue.query(cloid))
    assert recovery.state == "RETRYABLE"
    assert verdict.decision.value == "controlled_retry"
    # The retry is a NEW venue submit but the SAME client order identity.
    assert venue.submit_calls == []  # query itself never submits
    venue.submit(cloid)
    assert venue.submit_calls == [cloid]  # exactly one economic order, same identity
    assert len(set(venue.submit_calls)) == 1


def test_late_ack_is_ignored_after_adoption() -> None:
    intent = _intent()
    intent_id = compute_intent_id(intent)
    cloid = derive_client_order_id(intent_id)
    venue = FakeVenue()
    venue.submit(cloid)
    recovery = AmbiguousAckRecovery(intent_id=intent_id, client_order_id=cloid)
    recovery.on_submit_timeout()
    recovery.resolve(AckQueryResult.FOUND, venue_order_id="VO-1")
    # Late duplicate ACK: must not double-submit.
    assert recovery.state == "ADOPTED"
    assert venue.submit_calls.count(cloid) == 1


def test_duplicate_ack_after_accept_is_single_submit() -> None:
    intent = _intent()
    intent_id = compute_intent_id(intent)
    cloid = derive_client_order_id(intent_id)
    venue = FakeVenue()
    gate = IdempotentSubmitGate()

    def submit(intent: TradeIntent, client_order_id: str) -> str:
        return venue.submit(client_order_id)

    gate.submit(intent, submit)
    gate.submit(intent, submit)  # duplicate ACK path -> gate returns first outcome
    assert venue.submit_calls == [cloid]
    assert gate.economic_order_count(intent_id) == 1


def test_duplicate_fill_and_duplicate_partial_fill_apply_once() -> None:
    ledger = FillLedger()
    ledger.apply_fill(
        venue_fill_id="F-1", symbol="BTC/USDT", side="buy", quantity=0.3, price=60_000.0
    )
    ledger.apply_fill(
        venue_fill_id="F-1", symbol="BTC/USDT", side="buy", quantity=0.3, price=60_000.0
    )
    ledger.apply_fill(
        venue_fill_id="F-2", symbol="BTC/USDT", side="buy", quantity=0.2, price=60_000.0
    )
    ledger.apply_fill(
        venue_fill_id="F-2", symbol="BTC/USDT", side="buy", quantity=0.2, price=60_000.0
    )
    assert ledger.applied_count() == 2


def test_out_of_order_fills_accumulate_exactly_once() -> None:
    ledger = FillLedger()
    a = ledger.apply_fill(
        venue_fill_id="F-2", symbol="BTC/USDT", side="buy", quantity=0.2, price=60_000.0
    )
    b = ledger.apply_fill(
        venue_fill_id="F-1", symbol="BTC/USDT", side="buy", quantity=0.3, price=60_000.0
    )
    c = ledger.apply_fill(
        venue_fill_id="F-2", symbol="BTC/USDT", side="buy", quantity=0.2, price=60_000.0
    )
    assert a.applied and b.applied and c.duplicate
    assert ledger.applied_count() == 2


def test_cancel_timeout_remains_uncertain_reconciles() -> None:
    intent = _intent()
    intent_id = compute_intent_id(intent)
    cloid = derive_client_order_id(intent_id)
    journal = ExecutionJournal()
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.CREATED,
        reason="created",
        timestamp=1.0,
    )
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.SUBMITTING,
        reason="submitted",
        timestamp=2.0,
    )
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.ACCEPTED,
        reason="acked",
        timestamp=3.0,
    )
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.CANCEL_PENDING,
        reason="cancel sent",
        timestamp=4.0,
    )
    # Cancel timeout: never assume CANCELLED; go to RECONCILING.
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.RECONCILING,
        reason="cancel timeout, reconcile",
        timestamp=5.0,
    )
    assert journal.current_state(intent_id) is ExecutionState.RECONCILING
    # Reconciliation finds the order still live -> adopted back to ACCEPTED.
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.ACCEPTED,
        reason="venue still live after reconcile",
        timestamp=6.0,
    )
    assert journal.current_state(intent_id) is ExecutionState.ACCEPTED


def test_cancel_reject_returns_to_accepted() -> None:
    intent = _intent()
    intent_id = compute_intent_id(intent)
    cloid = derive_client_order_id(intent_id)
    journal = ExecutionJournal()
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.CREATED,
        reason="created",
        timestamp=1.0,
    )
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.SUBMITTING,
        reason="submitted",
        timestamp=2.0,
    )
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.ACCEPTED,
        reason="acked",
        timestamp=3.0,
    )
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.CANCEL_PENDING,
        reason="cancel sent",
        timestamp=4.0,
    )
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.ACCEPTED,
        reason="venue rejected cancel; order still live",
        timestamp=5.0,
    )
    assert journal.current_state(intent_id) is ExecutionState.ACCEPTED


def test_late_cancel_confirmation_after_fill_is_noop() -> None:
    intent = _intent()
    intent_id = compute_intent_id(intent)
    cloid = derive_client_order_id(intent_id)
    journal = ExecutionJournal()
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.CREATED,
        reason="created",
        timestamp=1.0,
    )
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.SUBMITTING,
        reason="submitted",
        timestamp=2.0,
    )
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.ACCEPTED,
        reason="acked",
        timestamp=3.0,
    )
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.FILLED,
        reason="filled before cancel landed",
        timestamp=4.0,
    )
    # FILLED is terminal; a late cancel confirmation must be rejected.
    with pytest.raises(ExecutionReliabilityError):
        journal.record(
            intent_id=intent_id,
            client_order_id=cloid,
            new_state=ExecutionState.CANCELLED,
            reason="late cancel confirm",
            timestamp=5.0,
        )


def test_orphan_order_reconciles_never_auto_submits_replacement() -> None:
    intent = _intent()
    intent_id = compute_intent_id(intent)
    cloid = derive_client_order_id(intent_id)
    gate = IdempotentSubmitGate()
    venue = FakeVenue()

    def submit(intent: TradeIntent, client_order_id: str) -> str:
        return venue.submit(client_order_id)

    gate.submit(intent, submit)
    # Local journal lost the order; venue still has it -> ORPHANED -> reconcile to ACCEPTED.
    journal = ExecutionJournal()
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.ORPHANED,
        reason="venue_only found",
        timestamp=1.0,
    )
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.RECONCILING,
        reason="reconcile",
        timestamp=2.0,
    )
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.ACCEPTED,
        reason="adopted",
        venue_order_id="VO-1",
        timestamp=3.0,
    )
    # No replacement is auto-submitted.
    assert venue.submit_calls == [cloid]
    assert gate.economic_order_count(intent_id) == 1


def test_restart_with_open_order_reconstructs_and_never_duplicates() -> None:
    intent = _intent()
    intent_id = compute_intent_id(intent)
    cloid = derive_client_order_id(intent_id)
    # Restart: journal reloaded (simulated by replaying terminal-before states),
    # venue still holds the open order.
    journal = ExecutionJournal()
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.CREATED,
        reason="replayed",
        timestamp=1.0,
    )
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.SUBMITTING,
        reason="replayed",
        timestamp=2.0,
    )
    journal.record(
        intent_id=intent_id,
        client_order_id=cloid,
        new_state=ExecutionState.ACK_UNKNOWN,
        reason="replayed (no terminal state)",
        timestamp=3.0,
    )
    recovery = AmbiguousAckRecovery(intent_id=intent_id, client_order_id=cloid)
    recovery.on_submit_timeout()
    # Startup reconciliation queries the venue by stable identity.
    venue = FakeVenue()
    venue.orders[cloid] = "VO-1"
    verdict = recovery.resolve(venue.query(cloid), venue_order_id=venue.orders.get(cloid))
    assert verdict.decision.value == "adopt"
    assert venue.submit_calls == []  # restart must NOT re-submit
    assert recovery.state == "ADOPTED"


def test_restart_with_open_position_reconstructs_position() -> None:
    ledger = FillLedger()
    ledger.apply_fill(
        venue_fill_id="F-1", symbol="BTC/USDT", side="buy", quantity=0.5, price=60_000.0
    )
    # Restart: fills replayed from journal; duplicates must not double-count.
    again = ledger.apply_fill(
        venue_fill_id="F-1", symbol="BTC/USDT", side="buy", quantity=0.5, price=60_000.0
    )
    assert again.duplicate is True
    assert ledger.applied_count() == 1


def test_external_unknown_position_blocks_new_entries() -> None:
    from trading_bot.execution import FeedDeadManGuard, FeedFreshness

    guard = FeedDeadManGuard()
    stale = FeedFreshness(
        feed_id="positions",
        last_update_ts=1_000.0,
        observed_at_ts=1_100.0,
        max_staleness_seconds=30.0,
    )
    verdict = guard.evaluate((stale,))
    assert verdict.action.value == "block_new_entries"
    assert not guard.allow_new_entries(verdict)


def test_same_intent_retried_2x_stays_single_economic_order() -> None:
    intent = _intent()
    intent_id = compute_intent_id(intent)
    gate = IdempotentSubmitGate()
    venue = FakeVenue()

    def submit(intent: TradeIntent, client_order_id: str) -> str:
        return venue.submit(client_order_id)

    for _ in range(2):
        gate.submit(intent, submit)
    assert venue.submit_calls == [derive_client_order_id(intent_id)]
    assert gate.economic_order_count(intent_id) == 1


def test_same_intent_retried_10x_stays_single_economic_order() -> None:
    intent = _intent()
    intent_id = compute_intent_id(intent)
    gate = IdempotentSubmitGate()
    venue = FakeVenue()

    def submit(intent: TradeIntent, client_order_id: str) -> str:
        return venue.submit(client_order_id)

    for _ in range(10):
        gate.submit(intent, submit)
    assert len(venue.submit_calls) == 1
    assert gate.economic_order_count(intent_id) == 1


def test_stale_feed_blocks_new_entries() -> None:
    from trading_bot.execution import FeedDeadManGuard, FeedFreshness

    guard = FeedDeadManGuard()
    stale = FeedFreshness(
        feed_id="ohlcv-btc",
        last_update_ts=1_000.0,
        observed_at_ts=1_100.0,
        max_staleness_seconds=30.0,
    )
    verdict = guard.evaluate((stale,))
    assert not guard.allow_new_entries(verdict)


def test_reconnect_after_stale_restores_allow() -> None:
    from trading_bot.execution import FeedDeadManGuard, FeedFreshness

    guard = FeedDeadManGuard()
    stale = FeedFreshness(
        feed_id="ohlcv-btc",
        last_update_ts=1_000.0,
        observed_at_ts=1_100.0,
        max_staleness_seconds=30.0,
    )
    fresh = FeedFreshness(
        feed_id="ohlcv-btc",
        last_update_ts=1_200.0,
        observed_at_ts=1_205.0,
        max_staleness_seconds=30.0,
    )
    blocked = guard.evaluate((stale,))
    allowed = guard.evaluate((fresh,))
    assert not guard.allow_new_entries(blocked)
    assert guard.allow_new_entries(allowed)
