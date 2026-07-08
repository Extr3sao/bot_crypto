"""Tests for OrderBookImbalance concrete indicator (TSK-203).

These tests pin the behavior of the self-contained OrderBookImbalance
indicator shipped in TSK-203. They cover:

- Determinism (same input -> same output).
- Output bounds (clamped to [-1.0, +1.0]).
- Symmetry (balanced -> 0; bid-dominant -> positive; ask-dominant -> negative).
- Disabled raises IndicatorDisabledError by default.
- Zero total volume raises InsufficientHistoryError.
- Negative input raises InvalidOrderBookSnapshotError.
- OrderBookSummary is a frozen dataclass (mutation blocked).
- Depth levels defaults to 10 (per config/indicators.yaml catalog).
"""

from __future__ import annotations

import dataclasses

import pytest

from trading_bot.indicators.order_book_imbalance import (
    IndicatorDisabledError,
    InsufficientHistoryError,
    InvalidOrderBookSnapshotError,
    OrderBookImbalance,
    OrderBookSummary,
)


def test_compute_balanced_order_book_returns_zero() -> None:
    """Balanced order book (bid==ask) yields imbalance == 0.0."""
    indicator = OrderBookImbalance(enabled=True)
    summary = OrderBookSummary(bid_volume=100.0, ask_volume=100.0)
    assert indicator.compute(summary) == pytest.approx(0.0, abs=1e-12)


def test_compute_bid_dominant_returns_positive() -> None:
    """Bid-dominant order book yields positive imbalance."""
    indicator = OrderBookImbalance(enabled=True)
    summary = OrderBookSummary(bid_volume=100.0, ask_volume=50.0)
    # (100 - 50) / (100 + 50) = 50/150 = 0.3333...
    assert indicator.compute(summary) == pytest.approx(1.0 / 3.0, abs=1e-6)


def test_compute_ask_dominant_returns_negative() -> None:
    """Ask-dominant order book yields negative imbalance."""
    indicator = OrderBookImbalance(enabled=True)
    summary = OrderBookSummary(bid_volume=50.0, ask_volume=100.0)
    # (50 - 100) / (50 + 100) = -0.3333...
    assert indicator.compute(summary) == pytest.approx(-1.0 / 3.0, abs=1e-6)


def test_compute_clamped_at_plus_one_when_no_ask() -> None:
    """All bid, no ask -> imbalance == 1.0 (clamped)."""
    indicator = OrderBookImbalance(enabled=True)
    summary = OrderBookSummary(bid_volume=100.0, ask_volume=0.0)
    assert indicator.compute(summary) == pytest.approx(1.0, abs=1e-12)


def test_compute_clamped_at_minus_one_when_no_bid() -> None:
    """All ask, no bid -> imbalance == -1.0 (clamped)."""
    indicator = OrderBookImbalance(enabled=True)
    summary = OrderBookSummary(bid_volume=0.0, ask_volume=100.0)
    assert indicator.compute(summary) == pytest.approx(-1.0, abs=1e-12)


def test_compute_zero_total_volume_raises_insufficient_history() -> None:
    """Zero total volume raises InsufficientHistoryError."""
    indicator = OrderBookImbalance(enabled=True)
    summary = OrderBookSummary(bid_volume=0.0, ask_volume=0.0)
    with pytest.raises(InsufficientHistoryError):
        indicator.compute(summary)


def test_compute_negative_bid_raises_invalid_snapshot() -> None:
    """Negative bid_volume raises InvalidOrderBookSnapshotError."""
    indicator = OrderBookImbalance(enabled=True)
    summary = OrderBookSummary(bid_volume=-1.0, ask_volume=10.0)
    with pytest.raises(InvalidOrderBookSnapshotError):
        indicator.compute(summary)


def test_compute_negative_ask_raises_invalid_snapshot() -> None:
    """Negative ask_volume raises InvalidOrderBookSnapshotError."""
    indicator = OrderBookImbalance(enabled=True)
    summary = OrderBookSummary(bid_volume=10.0, ask_volume=-1.0)
    with pytest.raises(InvalidOrderBookSnapshotError):
        indicator.compute(summary)


def test_disabled_raises_indicator_disabled() -> None:
    """Default-constructed instance (enabled=False) raises on compute()."""
    indicator = OrderBookImbalance()  # default disabled
    summary = OrderBookSummary(bid_volume=100.0, ask_volume=50.0)
    with pytest.raises(IndicatorDisabledError):
        indicator.compute(summary)


def test_disabled_via_constructor_with_enabled_false_raises() -> None:
    """Explicit enabled=False also raises IndicatorDisabledError."""
    indicator = OrderBookImbalance(enabled=False)
    summary = OrderBookSummary(bid_volume=100.0, ask_volume=50.0)
    with pytest.raises(IndicatorDisabledError):
        indicator.compute(summary)


def test_compute_deterministic() -> None:
    """Same input -> same output (across multiple calls)."""
    indicator = OrderBookImbalance(enabled=True)
    summary = OrderBookSummary(bid_volume=100.0, ask_volume=42.0)
    first = indicator.compute(summary)
    second = indicator.compute(summary)
    third = indicator.compute(summary)
    assert first == second == third


def test_order_book_summary_is_frozen() -> None:
    """OrderBookSummary is a frozen dataclass; mutation is blocked."""
    summary = OrderBookSummary(bid_volume=100.0, ask_volume=50.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        summary.bid_volume = 999.0  # type: ignore[misc]


def test_depth_levels_defaults_to_10() -> None:
    """depth_levels default is 10 (per config/indicators.yaml catalog)."""
    summary = OrderBookSummary(bid_volume=100.0, ask_volume=50.0)
    assert summary.depth_levels == 10


def test_custom_depth_levels_preserved() -> None:
    """Custom depth_levels is preserved on the dataclass."""
    summary = OrderBookSummary(bid_volume=100.0, ask_volume=50.0, depth_levels=5)
    assert summary.depth_levels == 5
