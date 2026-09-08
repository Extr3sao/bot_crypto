from __future__ import annotations

import pytest

from trading_bot.execution import (
    ExecutionReliabilityError,
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


def test_same_economic_intent_same_intent_id() -> None:
    first = compute_intent_id(_intent())
    second = compute_intent_id(_intent())
    assert first == second
    assert first.startswith("TI-")


def test_wall_clock_metadata_does_not_change_identity() -> None:
    with_clock = _intent(metadata={"requested_at": 1_700_000_000.0, "trace_id": "trace-abc"})
    without_clock = _intent(metadata={})
    assert compute_intent_id(with_clock) == compute_intent_id(without_clock)


def test_economic_difference_changes_identity() -> None:
    assert compute_intent_id(_intent(symbol="ETH/USDT")) != compute_intent_id(_intent())
    assert compute_intent_id(_intent(side="sell")) != compute_intent_id(_intent())
    assert compute_intent_id(_intent(quantity=0.02)) != compute_intent_id(_intent())
    assert compute_intent_id(_intent(limit_price=61_000.0)) != compute_intent_id(_intent())


def test_client_order_id_is_deterministic_and_clock_free() -> None:
    intent_id = compute_intent_id(_intent())
    assert derive_client_order_id(intent_id) == derive_client_order_id(intent_id)
    assert derive_client_order_id(intent_id).startswith("CO-")
    assert "uuid" not in derive_client_order_id(intent_id).lower()
    assert "time" not in derive_client_order_id(intent_id).lower()


def test_retry_reuses_same_client_order_id() -> None:
    intent = _intent()
    intent_id = compute_intent_id(intent)
    assert derive_client_order_id(intent_id) == derive_client_order_id(intent_id)


def test_invalid_intents_rejected() -> None:
    with pytest.raises(ValueError):
        _intent(side="hold")
    with pytest.raises(ValueError):
        _intent(quantity=0.0)
    with pytest.raises(ValueError):
        _intent(order_type="limit", limit_price=None)
    with pytest.raises(ValueError):
        _intent(order_type="iceberg")


def test_execution_reliability_error_is_runtime_error() -> None:
    assert issubclass(ExecutionReliabilityError, RuntimeError)
