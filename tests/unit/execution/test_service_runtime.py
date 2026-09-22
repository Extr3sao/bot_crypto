"""Track C (EXECUTION-RUNTIME-WIRING-01): runtime-mounted ExecutionService.

Proves the runtime call path TradeIntent -> journal -> gateway -> venue with
restart recovery, ACK ambiguity and the adversarial matrix through the REAL
service boundary (C1-C5).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trading_bot.execution import (
    ExecutionService,
    FeedBlockedError,
    TradeIntent,
)
from trading_bot.execution.gateway import GatewayReceipt
from trading_bot.execution.intent import AckQueryResult
from trading_bot.execution.journal import ExecutionState
from trading_bot.execution.service import AmbiguousSubmit

# ---------------------------------------------------------------------------
# Simulated venue at the real runtime boundary
# ---------------------------------------------------------------------------


class FakeVenue:
    """VenuePort double that can simulate every adversarial venue behavior."""

    def __init__(self) -> None:
        self.orders: dict[str, str] = {}
        self.submit_calls: list[str] = []
        self.submit_should_raise = False
        self.raise_before_accept = False  # raise WITHOUT registering (never landed)
        self.query_should_raise = False
        self.ack_lost = False  # submit succeeds but ack never reaches client

    def submit(self, intent: TradeIntent, client_order_id: str) -> str:
        self.submit_calls.append(client_order_id)
        if self.raise_before_accept:
            raise OSError("connection reset before venue accepted")
        if self.submit_should_raise:
            # Order accepted venue-side, then the connection died.
            self.orders.setdefault(client_order_id, f"V-{client_order_id}")
            raise OSError("connection reset after venue accepted")
        self.orders[client_order_id] = f"V-{client_order_id}"
        return f"V-{client_order_id}"

    def query(self, client_order_id: str) -> AckQueryResult:
        if self.query_should_raise:
            raise OSError("query failed")
        return AckQueryResult.FOUND if client_order_id in self.orders else AckQueryResult.ABSENT

    def venue_order_id_of(self, client_order_id: str) -> str | None:
        return self.orders.get(client_order_id)


def _intent(symbol: str = "BTC/USDT", qty: float = 1.0) -> TradeIntent:
    return TradeIntent(
        symbol=symbol,
        side="buy",
        quantity=qty,
        order_type="market",
        venue="simulated",
        account_id="test-account",
    )


# ---------------------------------------------------------------------------
# EX-01/EX-03: runtime intent propagation + stable identity
# ---------------------------------------------------------------------------


class TestRuntimeIdentityPropagation:
    def test_execute_propagates_stable_identity(self) -> None:
        service = ExecutionService()
        venue = FakeVenue()
        r = service.execute(_intent(), venue)
        assert r.journal_state is ExecutionState.ACCEPTED
        assert r.submitted_now is True
        assert r.client_order_id == service.client_order_id(_intent())

    def test_retry_identity_stable_across_service_instances(self, tmp_path: Path) -> None:
        """Same economic intent across 10 sequential (restarted) services on the
        SAME durable journal: identical ids, exactly one economic order (EX-07)."""
        path = tmp_path / "journal.jsonl"
        venue = FakeVenue()
        intent = _intent()
        ids: set[str] = set()
        cloids: set[str] = set()
        for _ in range(10):
            service = ExecutionService.from_path(path)
            r = service.execute(intent, venue)
            ids.add(r.intent_id)
            cloids.add(r.client_order_id)
        assert len(ids) == 1
        assert len(cloids) == 1
        assert len(venue.submit_calls) == 1
        # Durable truth after 10 restarts: the intent lives exactly once,
        # accepted, with one economic submission recorded venue-side.
        assert service.journal.current_state(ids.pop()) is ExecutionState.ACCEPTED

    def test_wall_clock_in_metadata_never_changes_identity(self) -> None:
        service = ExecutionService()
        i1 = _intent()
        i2 = TradeIntent(
            symbol="BTC/USDT",
            side="buy",
            quantity=1.0,
            order_type="market",
            venue="simulated",
            account_id="test-account",
            metadata={"submitted_at": "2099-01-01T00:00:00Z", "request_id": "xyz"},
        )
        assert service.intent_id(i1) == service.intent_id(i2)
        assert service.client_order_id(i1) == service.client_order_id(i2)


# ---------------------------------------------------------------------------
# EX-02/EX-04: journal mount + ACK_UNKNOWN runtime E2E
# ---------------------------------------------------------------------------


class TestJournalMountAndAck:
    def test_journal_mounted_every_transition_recorded(self) -> None:
        service = ExecutionService()
        venue = FakeVenue()
        intent = _intent()
        service.execute(intent, venue)
        hist = service.journal.history(service.intent_id(intent))
        states = [t.new_state for t in hist]
        assert states == ["CREATED", "SUBMITTING", "ACCEPTED"]

    def test_ack_unknown_adopt_keeps_one_economic_order(self) -> None:
        service = ExecutionService()
        venue = FakeVenue()
        intent = _intent()
        venue.submit_should_raise = True  # accepted venue-side, connection dies
        with pytest.raises(AmbiguousSubmit):
            service.execute(intent, venue)
        assert service.journal.current_state(service.intent_id(intent)) is (
            ExecutionState.ACK_UNKNOWN
        )
        venue.submit_should_raise = False
        r = service.resolve_ack(intent, venue)
        assert r.journal_state is ExecutionState.ACCEPTED
        assert r.submitted_now is False
        assert len(venue.submit_calls) == 1  # ECONOMIC_ORDERS_PER_INTENT == 1

    def test_ack_unknown_absent_allows_single_controlled_retry(self) -> None:
        service = ExecutionService()
        venue = FakeVenue()
        intent = _intent()
        venue.raise_before_accept = True  # submit never landed venue-side
        with pytest.raises(AmbiguousSubmit):
            service.execute(intent, venue)
        venue.raise_before_accept = False
        r = service.resolve_ack(intent, venue)
        assert r.journal_state is ExecutionState.ACCEPTED
        assert r.submitted_now is True
        # Two transport attempts (first raised pre-accept) but exactly ONE
        # economic order exists venue-side (ECONOMIC_ORDERS_PER_INTENT == 1).
        assert len(venue.orders) == 1
        assert service.gateway.submit_gate.economic_order_count(service.intent_id(intent)) == 1

    def test_ack_unknown_uncertain_blocks(self) -> None:
        service = ExecutionService()
        venue = FakeVenue()
        intent = _intent()
        venue.submit_should_raise = True
        with pytest.raises(AmbiguousSubmit):
            service.execute(intent, venue)
        venue.query_should_raise = True
        r = service.resolve_ack(intent, venue)
        assert r.journal_state is ExecutionState.RECONCILING
        assert r.detail.startswith("blocked")
        assert len(venue.submit_calls) == 1


# ---------------------------------------------------------------------------
# EX-06: restart recovery with durable journal
# ---------------------------------------------------------------------------


class TestRestartRecovery:
    def test_journal_reloads_across_restart(self, tmp_path: Path) -> None:
        path = tmp_path / "journal.jsonl"
        venue = FakeVenue()
        intent = _intent()

        first = ExecutionService.from_path(path)
        first.execute(intent, venue)
        first_state = first.journal.current_state(first.intent_id(intent))

        # Restart: fresh service, same durable path.
        second = ExecutionService.from_path(path)
        assert second.journal.current_state(second.intent_id(intent)) is first_state
        assert second.journal.current_state(second.intent_id(intent)) is ExecutionState.ACCEPTED

    def test_restart_with_open_order_does_not_resubmit(self, tmp_path: Path) -> None:
        path = tmp_path / "journal.jsonl"
        venue = FakeVenue()
        intent = _intent()
        ExecutionService.from_path(path).execute(intent, venue)
        submit_count_before = len(venue.submit_calls)

        rebooted = ExecutionService.from_path(path)
        r = rebooted.execute(intent, venue)
        assert r.journal_state is ExecutionState.ACCEPTED
        assert r.submitted_now is False
        assert len(venue.submit_calls) == submit_count_before

    def test_startup_reconcile_adopts_venue_held_order(self, tmp_path: Path) -> None:
        path = tmp_path / "journal.jsonl"
        intent = _intent()
        ExecutionService.from_path(path).execute(_intent(), FakeVenue())

        rebooted = ExecutionService.from_path(path)
        report = rebooted.startup_reconcile(
            (intent,),
            venue_open_client_order_ids={rebooted.client_order_id(intent)},
            venue_order_ids={rebooted.client_order_id(intent): "V-adopted"},
            prerequisites={
                "instrument_metadata": True,
                "account": True,
                "positions": True,
                "open_orders": True,
                "recent_fills": True,
            },
        )
        assert report.adopted == (rebooted.intent_id(intent),)
        assert report.closed == ()
        assert report.clean
        assert rebooted.journal.current_state(rebooted.intent_id(intent)) is (
            ExecutionState.ACCEPTED
        )
        assert report.ready

    def test_startup_reconcile_closes_absent_order(self, tmp_path: Path) -> None:
        path = tmp_path / "journal.jsonl"
        intent = _intent()
        ExecutionService.from_path(path).execute(intent, FakeVenue())

        rebooted = ExecutionService.from_path(path)
        report = rebooted.startup_reconcile(
            (intent,),
            venue_open_client_order_ids=set(),  # venue lacks it
        )
        assert report.closed == (rebooted.intent_id(intent),)
        assert rebooted.journal.current_state(rebooted.intent_id(intent)) is (
            ExecutionState.CANCELLED
        )

    def test_startup_ready_is_fail_closed(self, tmp_path: Path) -> None:
        rebooted = ExecutionService.from_path(tmp_path / "journal.jsonl")
        report = rebooted.startup_reconcile((), venue_open_client_order_ids=set())
        assert not report.ready
        assert set(report.missing) == {
            "instrument_metadata",
            "account",
            "positions",
            "open_orders",
            "recent_fills",
        }
        ready, missing = rebooted.execution_ready(
            {
                "instrument_metadata": True,
                "account": True,
                "positions": True,
                "open_orders": True,
                "recent_fills": True,
            }
        )
        assert ready
        assert missing == ()


# ---------------------------------------------------------------------------
# Feed dead-man through the service boundary
# ---------------------------------------------------------------------------


class TestFeedGateAtService:
    def test_feed_block_sends_nothing(self) -> None:
        from trading_bot.execution.feed_guard import FeedGuardAction, FeedGuardVerdict

        service = ExecutionService()
        venue = FakeVenue()
        verdict = FeedGuardVerdict(
            action=FeedGuardAction.BLOCK_NEW_ENTRIES,
            stale_feeds=("ohlcv:BTC/USDT",),
            evidence={"reason": "test stale feed"},
        )
        with pytest.raises(FeedBlockedError) as excinfo:
            service.execute(_intent(), venue, evidence={"feed_verdict": verdict})
        assert excinfo.value.verdict is verdict
        assert venue.submit_calls == []
        assert service.journal.intents() == ()  # nothing journaled either


# ---------------------------------------------------------------------------
# EX-05 + C4: adversarial E2E through the real runtime call path
# ---------------------------------------------------------------------------


class TestRuntimeAdversarialE2E:
    def test_e2e_retry_x10_single_economic_order(self) -> None:
        service = ExecutionService()
        venue = FakeVenue()
        for _ in range(10):
            service.execute(_intent(), venue)
        assert len(venue.submit_calls) == 1

    def test_e2e_lost_ack_late_ack_duplicate_ack(self) -> None:
        service = ExecutionService()
        venue = FakeVenue()
        intent = _intent()
        venue.submit_should_raise = True  # venue accepts, then connection dies
        with pytest.raises(AmbiguousSubmit):
            service.execute(intent, venue)
        # late ack: venue already knows the order -> adopt
        venue.submit_should_raise = False
        r = service.resolve_ack(intent, venue)
        assert r.journal_state is ExecutionState.ACCEPTED
        # duplicate ack resolution is idempotent: still ACCEPTED, still 1 order
        r2 = service.resolve_ack(intent, venue)
        assert r2.journal_state is ExecutionState.ACCEPTED
        assert len(venue.submit_calls) == 1

    def test_e2e_duplicate_and_out_of_order_fills(self) -> None:
        service = ExecutionService()
        venue = FakeVenue()
        intent = _intent(qty=10.0)
        service.execute(intent, venue)
        a1 = service.apply_fill(intent, venue_fill_id="F1", quantity=4.0, price=100.0, fee=0.1)
        a2 = service.apply_fill(intent, venue_fill_id="F1", quantity=4.0, price=100.0, fee=0.1)
        a3 = service.apply_fill(intent, venue_fill_id="F2", quantity=6.0, price=101.0, fee=0.2)
        assert a1.applied and not a2.applied
        assert a3.applied
        ledger = service.gateway.fills
        assert ledger.is_known("F1") and ledger.is_known("F2")
        assert ledger.applied_count() == 2  # F1 counted once despite duplicate
        assert a1.position_delta == pytest.approx(4.0)
        assert a2.duplicate and a2.position_delta == 0.0
        assert a3.position_delta == pytest.approx(6.0)  # out-of-order partial applied

    def test_e2e_cancel_timeout_then_reconcile(self) -> None:
        service = ExecutionService()
        venue = FakeVenue()
        intent = _intent()
        service.execute(intent, venue)
        service.request_cancel(intent, venue)  # CANCEL_PENDING (timeout stays here)
        assert service.journal.current_state(service.intent_id(intent)) is (
            ExecutionState.CANCEL_PENDING
        )
        # authoritative reconciliation decides: venue still holds -> adopt back
        service.reconcile_intent(intent, venue_holds_order=True)
        assert service.journal.current_state(service.intent_id(intent)) is (ExecutionState.ACCEPTED)

    def test_e2e_orphan_venue_order(self, tmp_path: Path) -> None:
        path = tmp_path / "journal.jsonl"
        service = ExecutionService.from_path(path)
        intent = _intent()
        service.execute(intent, venue=FakeVenue())
        # restart; venue still holds, journal state was durable
        rebooted = ExecutionService.from_path(path)
        report = rebooted.startup_reconcile(
            (intent,),
            venue_open_client_order_ids={rebooted.client_order_id(intent)},
        )
        assert report.adopted
        assert not report.ready  # no prerequisites passed -> fail closed

    def test_e2e_full_lifecycle_single_economic_order(self) -> None:
        service = ExecutionService()
        venue = FakeVenue()
        intent = _intent(qty=2.0)
        service.execute(intent, venue)
        service.apply_fill(intent, venue_fill_id="F1", quantity=1.0, price=100.0)
        service.apply_fill(intent, venue_fill_id="F2", quantity=1.0, price=100.5)
        service.request_cancel(intent, venue)
        service.confirm_cancel(intent)
        assert service.journal.current_state(service.intent_id(intent)) is (
            ExecutionState.CANCELLED
        )
        assert service.gateway.submit_gate.economic_order_count(service.intent_id(intent)) == 1


class TestGatewayReceiptShape:
    def test_receipt_fields(self) -> None:
        service = ExecutionService()
        r: GatewayReceipt = service.execute(_intent(), FakeVenue())
        assert set(r.__dataclass_fields__) == {
            "intent_id",
            "client_order_id",
            "venue_order_id",
            "journal_state",
            "submitted_now",
            "detail",
        }
