from __future__ import annotations

import pytest

from trading_bot.execution import (
    AckQueryResult,
    AmbiguousAckRecovery,
    ExecutionReliabilityError,
    IdempotentSubmitGate,
    RecoveryDecision,
    TradeIntent,
    compute_intent_id,
)


def _recovery() -> AmbiguousAckRecovery:
    return AmbiguousAckRecovery(intent_id="TI-abc", client_order_id="CO-abc")


def test_submit_timeout_enters_ack_unknown_and_blocks() -> None:
    recovery = _recovery()
    verdict = recovery.on_submit_timeout()
    assert recovery.state == "ACK_UNKNOWN"
    assert verdict.decision is RecoveryDecision.BLOCK
    assert "query" in verdict.reason


def test_found_adopts_and_seals() -> None:
    recovery = _recovery()
    recovery.on_submit_timeout()
    verdict = recovery.resolve(AckQueryResult.FOUND, venue_order_id="VO-7")
    assert verdict.decision is RecoveryDecision.ADOPT
    assert verdict.venue_order_id == "VO-7"
    assert recovery.state == "ADOPTED"
    # A second resolve on an adopted order is a no-op ADOPT, never a resubmit.
    again = recovery.resolve(AckQueryResult.ABSENT)
    assert again.decision is RecoveryDecision.ADOPT


def test_definitely_absent_allows_controlled_retry() -> None:
    recovery = _recovery()
    recovery.on_submit_timeout()
    verdict = recovery.resolve(AckQueryResult.ABSENT)
    assert verdict.decision is RecoveryDecision.CONTROLLED_RETRY
    assert recovery.state == "RETRYABLE"


def test_uncertain_blocks() -> None:
    recovery = _recovery()
    recovery.on_submit_timeout()
    verdict = recovery.resolve(AckQueryResult.UNCERTAIN)
    assert verdict.decision is RecoveryDecision.BLOCK
    assert recovery.state == "BLOCKED"


def test_resolve_without_timeout_raises() -> None:
    recovery = _recovery()
    with pytest.raises(ExecutionReliabilityError):
        recovery.resolve(AckQueryResult.FOUND)


def _intent() -> TradeIntent:
    return TradeIntent(
        symbol="BTC/USDT", side="buy", quantity=0.01, order_type="limit", limit_price=60_000.0
    )


def test_gate_submits_exactly_once_per_intent() -> None:
    gate = IdempotentSubmitGate()
    calls: list[str] = []
    intent = _intent()

    def fake_submit(intent: TradeIntent, client_order_id: str) -> str:
        calls.append(client_order_id)
        return "VO-1"

    reference = gate.submit(intent, fake_submit)
    assert reference == "VO-1"
    assert len(calls) == 1
    assert calls[0] == derive_client_order_id_safe(compute_intent_id(intent))
    assert gate.economic_order_count(compute_intent_id(intent)) == 1


def derive_client_order_id_safe(intent_id: str) -> str:
    from trading_bot.execution import derive_client_order_id

    return derive_client_order_id(intent_id)


def test_gate_reuses_first_outcome_on_retry() -> None:
    gate = IdempotentSubmitGate()
    calls: list[str] = []
    intent = _intent()

    def fake_submit(intent: TradeIntent, client_order_id: str) -> str:
        calls.append(client_order_id)
        return "VO-1"

    first = gate.submit(intent, fake_submit)
    second = gate.submit(intent, fake_submit)
    assert first == second == "VO-1"
    assert len(calls) == 1
    assert gate.economic_order_count(compute_intent_id(intent)) == 1


def test_gate_sealed_intent_forbids_resubmission() -> None:
    gate = IdempotentSubmitGate()
    intent = _intent()
    intent_id = compute_intent_id(intent)

    def fake_submit(intent: TradeIntent, client_order_id: str) -> str:
        return "VO-1"

    gate.submit(intent, fake_submit)
    gate.seal(intent_id)
    with pytest.raises(ExecutionReliabilityError):
        gate.submit(intent, fake_submit)


def test_gate_different_intents_submit_independently() -> None:
    gate = IdempotentSubmitGate()
    count = 0

    def fake_submit(intent: TradeIntent, client_order_id: str) -> str:
        nonlocal count
        count += 1
        return f"VO-{count}"

    first = gate.submit(TradeIntent(symbol="BTC/USDT", side="buy", quantity=0.01), fake_submit)
    second = gate.submit(TradeIntent(symbol="BTC/USDT", side="buy", quantity=0.02), fake_submit)
    assert first != second
    assert count == 2
